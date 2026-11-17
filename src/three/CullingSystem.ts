import * as THREE from 'three';
import { OCCLUSION_BUDGET, OCCLUSION_NEAR_SKIP, OCCLUSION_TTL } from '../core/config';
import type { Booth } from '../types';
import { boothAabb } from '../core/geometry';
import type { BoothStore } from '../data/BoothStore';

interface OcclState {
  occluded: boolean;
  /** 上一次拿到查询结果的帧号 */
  lastFrame: number;
}

interface Slot {
  query: WebGLQuery;
  boothId: number;
  /** 发起查询的帧号 */
  frame: number;
}

/**
 * 视锥剔除 + 硬件遮挡查询（WebGL2 核心 ANY_SAMPLES_PASSED）。
 *
 * 策略：
 * - 视锥：BVH 盒查询求候选，再做 8 角点精确测试
 * - 遮挡：维护 OCCLUSION_BUDGET 个查询槽，每个代理盒单独一个查询。
 *   WebGL2 允许同帧多个查询在途，隔帧轮询结果，精确到单个展位，
 *   且 getQueryParameter 只查在途查询，不造成 CPU/GPU 同步停顿
 * - 代理盒仅做深度测试、不写颜色；结果带 TTL，相机大幅移动后整体失效
 * - 近处展位豁免遮挡剔除，避免走近时闪现
 */
export class CullingSystem {
  private frustum = new THREE.Frustum();
  private projScreen = new THREE.Matrix4();
  private corner = new THREE.Vector3();
  private states = new Map<number, OcclState>();
  private gl: WebGL2RenderingContext | null = null;
  private slots: Slot[] = [];
  private frameNo = 0;
  private lastCamPos = new THREE.Vector3();
  private proxyMesh: THREE.Mesh;
  private proxyScene: THREE.Scene;
  enabled = true;
  /** 上一帧实际被遮挡的数量，供 HUD 展示 */
  lastOccludedCount = 0;

  constructor(private store: BoothStore, private renderer: THREE.WebGLRenderer) {
    this.proxyMesh = new THREE.Mesh(
      new THREE.BoxGeometry(1, 1, 1),
      new THREE.MeshBasicMaterial({ colorWrite: false, depthWrite: false }),
    );
    this.proxyMesh.frustumCulled = false;
    this.proxyMesh.matrixAutoUpdate = false;
    this.proxyScene = new THREE.Scene();
    this.proxyScene.add(this.proxyMesh);
  }

  private ensureGl(): WebGL2RenderingContext | null {
    if (this.gl) return this.gl;
    const gl = this.renderer.getContext();
    if (!(gl instanceof WebGL2RenderingContext)) return null;
    for (let i = 0; i < OCCLUSION_BUDGET; i++) {
      this.slots.push({ query: gl.createQuery()!, boothId: -1, frame: -1 });
    }
    this.gl = gl;
    return gl;
  }

  /** 当前视锥内可见的展位 id（未考虑遮挡） */
  frustumVisible(camera: THREE.Camera): Set<number> {
    this.projScreen.multiplyMatrices(
      camera.projectionMatrix,
      camera.matrixWorldInverse,
    );
    this.frustum.setFromProjectionMatrix(this.projScreen);

    const visible = new Set<number>();
    const range = 700;
    const p = camera.position;
    const candidates = this.store.bvh.boxQuery({
      minX: p.x - range, minZ: p.z - range,
      maxX: p.x + range, maxZ: p.z + range,
    });
    for (const idx of candidates) {
      const b = this.store.booths[idx];
      if (this.inFrustum(b)) visible.add(b.id);
    }
    return visible;
  }

  private inFrustum(b: Booth): boolean {
    const a = boothAabb(b);
    for (let i = 0; i < 8; i++) {
      this.corner.set(
        i & 1 ? a.maxX : a.minX,
        i & 2 ? 4.2 : 0.1,
        i & 4 ? a.maxZ : a.minZ,
      );
      if (this.frustum.containsPoint(this.corner)) return true;
    }
    return false;
  }

  /**
   * 每帧驱动：先回收到期查询结果，再给空闲槽派发新查询。
   * 必须在主场景 render 之后调用，保证深度缓冲已包含全部展位。
   * 返回当前应隐藏（遮挡且状态有效）的展位 id 集合。
   */
  update(camera: THREE.PerspectiveCamera, visibleIds: Set<number>): Set<number> {
    this.frameNo++;
    const occluded = new Set<number>();
    if (!this.enabled) return occluded;

    const gl = this.ensureGl();
    if (!gl) return occluded;

    if (camera.position.distanceTo(this.lastCamPos) > 6) {
      for (const s of this.states.values()) s.lastFrame = -OCCLUSION_TTL;
      this.lastCamPos.copy(camera.position);
    }

    this.collectResults(gl);
    this.dispatchQueries(gl, camera, visibleIds);

    for (const [id, st] of this.states) {
      if (
        st.occluded &&
        this.frameNo - st.lastFrame < OCCLUSION_TTL &&
        visibleIds.has(id)
      ) {
        occluded.add(id);
      }
    }
    this.lastOccludedCount = occluded.size;
    return occluded;
  }

  private getState(id: number): OcclState {
    let s = this.states.get(id);
    if (!s) {
      s = { occluded: false, lastFrame: -OCCLUSION_TTL };
      this.states.set(id, s);
    }
    return s;
  }

  private dispatchQueries(
    gl: WebGL2RenderingContext,
    camera: THREE.PerspectiveCamera,
    visibleIds: Set<number>,
  ): void {
    const free = this.slots.filter((s) => s.boothId < 0);
    let used = 0;

    for (const id of visibleIds) {
      if (used >= free.length) break;
      const b = this.store.byId(id)!;
      const dist = Math.hypot(b.x - camera.position.x, b.z - camera.position.z);
      if (dist < OCCLUSION_NEAR_SKIP) continue;
      const st = this.getState(id);
      if (this.frameNo - st.lastFrame <= OCCLUSION_TTL * 0.5) continue;

      const slot = free[used++];
      const a = boothAabb(b);
      const sx = Math.max(a.maxX - a.minX, 0.3);
      const sz = Math.max(a.maxZ - a.minZ, 0.3);
      this.proxyMesh.position.set((a.minX + a.maxX) / 2, 2.1, (a.minZ + a.maxZ) / 2);
      this.proxyMesh.scale.set(sx, 3.8, sz);
      this.proxyMesh.updateMatrixWorld();

      slot.boothId = id;
      slot.frame = this.frameNo;

      gl.beginQuery(gl.ANY_SAMPLES_PASSED, slot.query);
      this.renderer.render(this.proxyScene, camera);
      gl.endQuery(gl.ANY_SAMPLES_PASSED);
    }
  }

  private collectResults(gl: WebGL2RenderingContext): void {
    for (const slot of this.slots) {
      if (slot.boothId < 0) continue;
      // 至少隔一帧再取，避免 GPU/CPU 同步停顿
      if (this.frameNo - slot.frame < 2) continue;
      const available = gl.getQueryParameter(slot.query, gl.QUERY_RESULT_AVAILABLE);
      if (!available) continue;
      const passed = gl.getQueryParameter(slot.query, gl.QUERY_RESULT) as number;
      const st = this.getState(slot.boothId);
      st.occluded = passed === 0;
      st.lastFrame = this.frameNo;
      slot.boothId = -1;
    }
  }

  invalidate(): void {
    this.states.clear();
    for (const s of this.slots) s.boothId = -1;
  }

  dispose(): void {
    if (this.gl) for (const s of this.slots) this.gl.deleteQuery(s.query);
    this.proxyMesh.geometry.dispose();
    (this.proxyMesh.material as THREE.Material).dispose();
  }
}
