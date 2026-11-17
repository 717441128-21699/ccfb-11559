import * as THREE from 'three';
import { HALL } from '../core/config';
import type { BoothStore } from '../data/BoothStore';
import type { FrameStats } from '../types';
import { HallRenderer } from './HallRenderer';
import { CullingSystem } from './CullingSystem';
import { Picker } from './Picker';
import { RouteLine } from './RouteLine';
import { WalkController } from '../nav/WalkController';
import { PathFinder } from '../nav/PathFinder';
import { Minimap } from '../ui/Minimap';

export class Scene3D {
  readonly renderer: THREE.WebGLRenderer;
  readonly scene = new THREE.Scene();
  readonly camera: THREE.PerspectiveCamera;
  private hall: HallRenderer;
  private culling: CullingSystem;
  private walk: WalkController;
  readonly finder: PathFinder;
  private picker: Picker;
  private routeLine = new RouteLine();
  minimap: Minimap;
  private raf = 0;
  private lastT = 0;
  private fpsAccum = 0;
  private fpsFrames = 0;
  private pickAccum = 0;
  private pickSamples = 0;
  private running = false;
  targetId = -1;
  onStats: ((s: FrameStats) => void) | null = null;
  onPickBooth: ((id: number) => void) | null = null;

  constructor(
    private canvas: HTMLCanvasElement,
    minimapCanvas: HTMLCanvasElement,
    private store: BoothStore,
  ) {
    this.renderer = new THREE.WebGLRenderer({
      canvas,
      antialias: true,
      powerPreference: 'high-performance',
    });
    this.renderer.setPixelRatio(Math.min(devicePixelRatio, 1.5));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;

    this.camera = new THREE.PerspectiveCamera(70, 1, 0.1, 800);
    this.hall = new HallRenderer(store);
    this.scene.add(this.hall.group);
    this.scene.add(this.routeLine.group);
    this.scene.background = new THREE.Color(0xdfe5ec);

    this.finder = new PathFinder(store);
    this.culling = new CullingSystem(store, this.renderer);
    this.walk = new WalkController(this.camera, canvas, this.finder);
    this.picker = new Picker(store);
    this.minimap = new Minimap(minimapCanvas, store);

    canvas.addEventListener('click', this.onClick);
    this.resize();
  }

  private onClick = (e: MouseEvent): void => {
    if (!this.walk.isLocked) return;
    const t0 = performance.now();
    const id = this.picker.pick(e.clientX, e.clientY, this.canvas, this.camera);
    this.pickAccum += performance.now() - t0;
    this.pickSamples++;
    if (id >= 0) this.onPickBooth?.(id);
  };

  setOcclusionEnabled(on: boolean): void {
    this.culling.enabled = on;
    if (!on) this.culling.invalidate();
  }

  rebuild(): void {
    this.hall.syncAll();
    this.finder.rebuild();
    this.culling.invalidate();
    this.minimap.markDirty();
  }

  refreshColors(hoverId = -1, selectedId = -1): void {
    this.hall.refreshColors(hoverId, selectedId);
  }

  start(x = HALL.width / 2, z = 8): void {
    if (this.running) return;
    this.running = true;
    // yaw=π 时前进方向为 (0,+1)，即从南入口沿中央主通道朝馆内看
    this.walk.setPosition(x, z, Math.PI);
    this.lastT = performance.now();
    const loop = (t: number) => {
      this.raf = requestAnimationFrame(loop);
      const dt = Math.min(0.05, (t - this.lastT) / 1000);
      this.lastT = t;
      this.frame(dt, t);
    };
    this.raf = requestAnimationFrame(loop);
  }

  stop(): void {
    this.running = false;
    cancelAnimationFrame(this.raf);
  }

  private frame(dt: number, t: number): void {
    this.walk.update(dt);

    // 1) 视锥剔除
    const visible = this.culling.frustumVisible(this.camera);
    // 2) 主场景渲染（写深度）
    this.renderer.render(this.scene, this.camera);
    // 3) 硬件遮挡查询（代理盒，不写颜色）
    const occluded = this.culling.update(this.camera, visible);
    // 4) 下一帧生效的实例剔除
    this.hall.applyCull(visible, occluded);

    this.minimap.render(
      this.camera.position.x,
      this.camera.position.z,
      this.walk.yaw,
      this.routeLineVisible(),
      this.targetId,
    );

    this.fpsAccum += dt;
    this.fpsFrames++;
    if (this.fpsAccum >= 0.5) {
      const fps = this.fpsFrames / this.fpsAccum;
      const avgPick = this.pickSamples ? this.pickAccum / this.pickSamples : 0;
      this.onStats?.({
        fps,
        frameMs: this.fpsAccum * 1000 / this.fpsFrames,
        drawCalls: this.renderer.info.render.calls,
        triangles: this.renderer.info.render.triangles,
        booths: this.store.booths.length,
        visible: visible.size,
        occluders: this.culling.enabled ? 10 : 0,
        occluded: this.culling.lastOccludedCount,
        pickMs: avgPick,
      });
      this.fpsAccum = 0;
      this.fpsFrames = 0;
      this.pickAccum = 0;
      this.pickSamples = 0;
    }
    void t;
  }

  private currentRoute: { x: number; z: number }[] = [];
  private routeLineVisible(): { x: number; z: number }[] {
    return this.currentRoute;
  }

  /** 搜索结果导航：寻路并进入自动行走 */
  navigateTo(boothId: number): boolean {
    const b = this.store.byId(boothId);
    if (!b) return false;
    const start = { x: this.camera.position.x, z: this.camera.position.z };
    // 目标点取展位正前方 2m
    const tx = b.x;
    const tz = b.z + b.d / 2 + 2;
    const route = this.finder.findPath(start.x, start.z, tx, tz);
    if (route.length < 2) return false;
    this.currentRoute = route;
    this.routeLine.setRoute(route);
    this.walk.follow(route);
    this.targetId = boothId;
    this.walk.onArrive = () => {
      this.routeLine.clear();
      this.currentRoute = [];
    };
    return true;
  }

  teleport(x: number, z: number, yaw = 0): void {
    this.walk.setPosition(x, z, yaw);
  }

  resize(): void {
    const parent = this.canvas.parentElement!;
    const w = parent.clientWidth;
    const h = parent.clientHeight;
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
  }

  dispose(): void {
    this.stop();
    this.canvas.removeEventListener('click', this.onClick);
    this.culling.dispose();
    this.hall.dispose();
    this.renderer.dispose();
  }
}
