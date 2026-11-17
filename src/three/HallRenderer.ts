import * as THREE from 'three';
import { HALL, MAX_BOOTHS } from '../core/config';
import type { Booth, BoothType } from '../types';
import { boothAabb } from '../core/geometry';
import { BoothStore } from '../data/BoothStore';
import { buildTemplates, BoothTemplate } from './geometry';
import { SignAtlas } from './SignAtlas';

const TYPES: BoothType[] = ['standard', 'peninsula', 'island', 'double', 'custom'];

interface TypeBin {
  body: THREE.InstancedMesh;
  fascia: THREE.InstancedMesh;
  /** 该实例槽位对应的 boothId，-1 为空槽 */
  ids: Int32Array;
  count: number;
}

/**
 * 展位三维渲染：
 * - 同类型展位的墙体/门头各自合批为 InstancedMesh（全馆 < 15 个 draw call）
 * - 门头文字走图集 + 每页一个实例化面片
 * - per-instance aCull 属性做视锥/遮挡剔除（着色器内坍缩为退化三角形）
 * - instanceColor 驱动常态/选中/悬停/消防违规配色
 */
export class HallRenderer {
  readonly group = new THREE.Group();
  readonly atlas = new SignAtlas();
  private templates: Record<BoothType, BoothTemplate>;
  private bins = new Map<BoothType, TypeBin>();
  private signMeshes: THREE.InstancedMesh[] = [];
  private signSlots: { mesh: THREE.InstancedMesh; index: number; boothId: number }[] = [];
  private idMap = new Map<number, { type: BoothType; slot: number }>();
  private dummy = new THREE.Object3D();
  private tmpColor = new THREE.Color();
  private cullAttrs: THREE.InstancedBufferAttribute[] = [];
  private signCullAttrs: THREE.InstancedBufferAttribute[] = [];
  private baseColors = new Map<number, THREE.Color>();

  constructor(private store: BoothStore) {
    this.templates = buildTemplates();
    this.buildBins();
    this.buildEnvironment();
  }

  private cullMaterial(mat: THREE.Material): THREE.Material {
    const m = mat.clone();
    m.onBeforeCompile = (shader) => {
      shader.vertexShader = shader.vertexShader
        .replace(
          '#include <common>',
          '#include <common>\nattribute float aCull;',
        )
        .replace(
          '#include <begin_vertex>',
          '#include <begin_vertex>\ntransformed *= aCull;',
        );
    };
    return m;
  }

  private buildBins(): void {
    for (const type of TYPES) {
      const tpl = this.templates[type];
      const bodyGeo = tpl.body;
      const fasciaGeo = tpl.fascia;

      const bodyMat = this.cullMaterial(new THREE.MeshStandardMaterial({
        color: 0xffffff,
        roughness: 0.85,
        metalness: 0.05,
      }));
      const fasciaMat = this.cullMaterial(new THREE.MeshStandardMaterial({
        color: 0xffffff,
        roughness: 0.6,
        metalness: 0.1,
      }));

      const body = new THREE.InstancedMesh(bodyGeo, bodyMat, MAX_BOOTHS);
      const fascia = new THREE.InstancedMesh(fasciaGeo, fasciaMat, MAX_BOOTHS);
      body.frustumCulled = false;
      fascia.frustumCulled = false;
      body.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
      fascia.instanceMatrix.setUsage(THREE.DynamicDrawUsage);

      const cull1 = this.attachCull(body);
      const cull2 = this.attachCull(fascia);
      this.cullAttrs.push(cull1, cull2);

      this.group.add(body, fascia);
      this.bins.set(type, {
        body, fascia,
        ids: new Int32Array(MAX_BOOTHS).fill(-1),
        count: 0,
      });
    }
  }

  private attachCull(mesh: THREE.InstancedMesh): THREE.InstancedBufferAttribute {
    const attr = new THREE.InstancedBufferAttribute(new Uint8Array(MAX_BOOTHS), 1);
    attr.setUsage(THREE.DynamicDrawUsage);
    mesh.geometry.setAttribute('aCull', attr);
    return attr;
  }

  private buildEnvironment(): void {
    // 地面
    const floorTex = this.makeFloorTexture();
    const floor = new THREE.Mesh(
      new THREE.PlaneGeometry(HALL.width, HALL.depth),
      new THREE.MeshStandardMaterial({ map: floorTex, roughness: 0.95 }),
    );
    floor.rotation.x = -Math.PI / 2;
    floor.position.set(HALL.width / 2, 0, HALL.depth / 2);
    this.group.add(floor);

    // 馆体矮墙（4m，仅边界提示）
    const wallMat = new THREE.MeshStandardMaterial({ color: 0xd8dde3, roughness: 0.9 });
    const walls = [
      { w: HALL.width, d: 0.4, x: HALL.width / 2, z: 0.2 },
      { w: HALL.width, d: 0.4, x: HALL.width / 2, z: HALL.depth - 0.2 },
      { w: 0.4, d: HALL.depth, x: 0.2, z: HALL.depth / 2 },
      { w: 0.4, d: HALL.depth, x: HALL.width - 0.2, z: HALL.depth / 2 },
    ];
    for (const w of walls) {
      const m = new THREE.Mesh(new THREE.BoxGeometry(w.w, 4, w.d), wallMat);
      m.position.set(w.x, 2, w.z);
      this.group.add(m);
    }

    const hemi = new THREE.HemisphereLight(0xffffff, 0xb8c0cc, 1.1);
    const dir = new THREE.DirectionalLight(0xffffff, 1.4);
    dir.position.set(120, 200, 80);
    const amb = new THREE.AmbientLight(0xffffff, 0.35);
    this.group.add(hemi, dir, amb);

    this.group.traverse((o) => {
      if (o instanceof THREE.Mesh) o.frustumCulled = false;
    });
  }

  private makeFloorTexture(): THREE.Texture {
    const c = document.createElement('canvas');
    c.width = c.height = 512;
    const ctx = c.getContext('2d')!;
    ctx.fillStyle = '#eef0f3';
    ctx.fillRect(0, 0, 512, 512);
    ctx.strokeStyle = '#dde2e8';
    ctx.lineWidth = 1;
    for (let i = 0; i <= 512; i += 32) {
      ctx.beginPath(); ctx.moveTo(i, 0); ctx.lineTo(i, 512); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(0, i); ctx.lineTo(512, i); ctx.stroke();
    }
    const tex = new THREE.CanvasTexture(c);
    tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
    tex.repeat.set(HALL.width / 8, HALL.depth / 8);
    tex.colorSpace = THREE.SRGBColorSpace;
    return tex;
  }

  /** 全量同步：生成/导入数据后调用 */
  syncAll(): void {
    for (const type of TYPES) {
      const bin = this.bins.get(type)!;
      bin.count = 0;
      bin.ids.fill(-1);
    }
    this.idMap.clear();
    this.baseColors.clear();
    this.atlas.dispose();
    this.clearSigns();

    for (const b of this.store.booths) {
      this.writeInstance(b);
    }
    for (const type of TYPES) {
      const bin = this.bins.get(type)!;
      bin.body.count = bin.count;
      bin.fascia.count = bin.count;
      bin.body.instanceMatrix.needsUpdate = true;
      bin.fascia.instanceMatrix.needsUpdate = true;
    }
    this.buildSigns();
    this.refreshColors();
    this.resetCull();
  }

  private writeInstance(b: Booth): void {
    const bin = this.bins.get(b.type)!;
    const slot = bin.count++;
    bin.ids[slot] = b.id;
    this.idMap.set(b.id, { type: b.type, slot });
    this.baseColors.set(b.id, new THREE.Color(b.color));

    this.dummy.position.set(b.x, 0, b.z);
    this.dummy.rotation.set(0, b.rotation, 0);
    this.dummy.scale.set(1, 1, 1);
    this.dummy.updateMatrix();
    bin.body.setMatrixAt(slot, this.dummy.matrix);
    bin.fascia.setMatrixAt(slot, this.dummy.matrix);
  }

  private clearSigns(): void {
    for (const m of this.signMeshes) {
      this.group.remove(m);
      m.geometry.dispose();
      (m.material as THREE.Material).dispose();
    }
    this.signMeshes = [];
    this.signSlots = [];
    this.signCullAttrs = [];
  }

  /** 为每个门头锚点生成实例化面片，按图集页分组合批 */
  private buildSigns(): void {
    const plane = new THREE.PlaneGeometry(1, 1);
    const groups = new Map<THREE.Texture, { boothId: number; matrix: THREE.Matrix4; uv: THREE.Vector2 }[]>();

    for (const b of this.store.booths) {
      const tpl = this.templates[b.type];
      const slot = this.atlas.getOrCreate(b.exhibitor);
      const group = groups.get(slot.texture) ?? [];
      groups.set(slot.texture, group);

      for (const anchor of tpl.signAnchor) {
        this.dummy.position.set(
          b.x + this.anchorX(anchor, b),
          anchor.y,
          b.z + this.anchorZ(anchor, b),
        );
        this.dummy.rotation.set(0, b.rotation + anchor.rotY, 0);
        this.dummy.scale.set(anchor.w, 0.42, 1);
        this.dummy.updateMatrix();
        group.push({ boothId: b.id, matrix: this.dummy.matrix.clone(), uv: slot.uvOffset.clone() });
      }
    }

    const cellU = 256 / 2048;
    const cellV = 96 / 2048;
    for (const [tex, items] of groups) {
      const geo = plane.clone();
      const uv = geo.attributes.uv as THREE.BufferAttribute;
      for (let i = 0; i < uv.count; i++) {
        uv.setXY(i, uv.getX(i) * cellU, uv.getY(i) * cellV);
      }
      const mat = new THREE.MeshBasicMaterial({ map: tex, side: THREE.DoubleSide });
      mat.onBeforeCompile = (shader) => {
        shader.vertexShader = shader.vertexShader
          .replace(
            '#include <common>',
            '#include <common>\nattribute vec2 iUvOffset;\nattribute float aCull;',
          )
          .replace(
            '#include <uv_vertex>',
            '#include <uv_vertex>\n#ifdef USE_MAP\n vMapUv += iUvOffset;\n#endif',
          )
          .replace(
            '#include <begin_vertex>',
            '#include <begin_vertex>\ntransformed *= aCull;',
          );
      };
      const mesh = new THREE.InstancedMesh(geo, mat, items.length);
      mesh.frustumCulled = false;
      const uvAttr = new THREE.InstancedBufferAttribute(
        new Float32Array(items.length * 2), 2,
      );
      const cullAttr = new THREE.InstancedBufferAttribute(
        new Uint8Array(items.length), 1,
      );
      cullAttr.setUsage(THREE.DynamicDrawUsage);
      items.forEach((it, i) => {
        mesh.setMatrixAt(i, it.matrix);
        uvAttr.setXY(i, it.uv.x, it.uv.y);
        cullAttr.setX(i, 1);
        this.signSlots.push({ mesh, index: i, boothId: it.boothId });
      });
      geo.setAttribute('iUvOffset', uvAttr);
      geo.setAttribute('aCull', cullAttr);
      this.signCullAttrs.push(cullAttr);
      mesh.instanceMatrix.needsUpdate = true;
      this.group.add(mesh);
      this.signMeshes.push(mesh);
    }
  }

  private anchorX(a: { x: number; z: number; rotY: number }, b: Booth): number {
    // 锚点本地坐标随展位旋转
    return a.x * Math.cos(b.rotation) - a.z * Math.sin(b.rotation);
  }
  private anchorZ(a: { x: number; z: number; rotY: number }, b: Booth): number {
    return a.x * Math.sin(b.rotation) + a.z * Math.cos(b.rotation);
  }

  /** 刷新全部实例颜色：违规红、常态用展位本色 */
  refreshColors(hoverId = -1, selectedId = -1): void {
    for (const [id, loc] of this.idMap) {
      const bin = this.bins.get(loc.type)!;
      const c = this.tmpColor;
      if (id === selectedId) c.setHex(0xff9f0a);
      else if (id === hoverId) c.setHex(0xffd60a);
      else if (this.store.violations.has(id)) c.setHex(0xff3b30);
      else c.copy(this.baseColors.get(id)!);
      bin.body.setColorAt(loc.slot, c);
      bin.fascia.setColorAt(loc.slot, c.clone().multiplyScalar(0.82));
    }
    for (const bin of this.bins.values()) {
      if (bin.body.instanceColor) bin.body.instanceColor.needsUpdate = true;
      if (bin.fascia.instanceColor) bin.fascia.instanceColor.needsUpdate = true;
    }
  }

  /** 每帧写入可见性：1 显示 / 0 坍缩剔除 */
  applyCull(visibleIds: Set<number>, occludedIds: Set<number>): void {
    for (const attr of this.cullAttrs) (attr.array as Uint8Array).fill(1);
    for (const attr of this.signCullAttrs) (attr.array as Uint8Array).fill(1);

    for (const [id, loc] of this.idMap) {
      const shown = visibleIds.has(id) && !occludedIds.has(id);
      const v = shown ? 1 : 0;
      const bin = this.bins.get(loc.type)!;
      bin.body.geometry.getAttribute('aCull').setX(loc.slot, v);
      bin.fascia.geometry.getAttribute('aCull').setX(loc.slot, v);
    }
    // 门头面片按顺序对应 signSlots
    for (let i = 0; i < this.signSlots.length; i++) {
      const s = this.signSlots[i];
      const shown = visibleIds.has(s.boothId) && !occludedIds.has(s.boothId);
      s.mesh.geometry.getAttribute('aCull').setX(s.index, shown ? 1 : 0);
    }
    for (const attr of this.cullAttrs) attr.needsUpdate = true;
    for (const attr of this.signCullAttrs) attr.needsUpdate = true;
  }

  resetCull(): void {
    for (const attr of this.cullAttrs) { (attr.array as Uint8Array).fill(1); attr.needsUpdate = true; }
    for (const attr of this.signCullAttrs) { (attr.array as Uint8Array).fill(1); attr.needsUpdate = true; }
  }

  /** 遮挡查询用的代理 AABB 列表（世界空间） */
  proxyBoxes(): { id: number; box: THREE.Box3 }[] {
    return this.store.booths.map((b) => {
      const a = boothAabb(b);
      return {
        id: b.id,
        box: new THREE.Box3(
          new THREE.Vector3(a.minX, 0, a.minZ),
          new THREE.Vector3(a.maxX, 4.2, a.maxZ),
        ),
      };
    });
  }

  locationOf(id: number) {
    return this.idMap.get(id);
  }

  dispose(): void {
    this.group.traverse((o) => {
      if (o instanceof THREE.Mesh) {
        o.geometry.dispose();
        (o.material as THREE.Material).dispose();
      }
    });
    this.atlas.dispose();
  }
}
