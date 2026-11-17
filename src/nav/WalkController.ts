import * as THREE from 'three';
import { HALL } from '../core/config';
import type { PathFinder } from './PathFinder';

/**
 * 第一人称漫游控制器：
 * - 指针锁定鼠标视角，WASD/方向键移动，Shift 加速
 * - 基于寻路栅格的滑动碰撞（分轴检测，贴墙可滑行）
 * - 支持自动导航：沿给定折线行走，到达每个拐点自动转向
 */
export class WalkController {
  yaw = 0;
  pitch = 0;
  private keys = new Set<string>();
  private route: { x: number; z: number }[] = [];
  private routeIdx = 0;
  autoWalking = false;
  /** 到达终点回调 */
  onArrive: (() => void) | null = null;
  /** 位置变化回调（驱动小地图） */
  onMove: ((x: number, z: number, yaw: number) => void) | null = null;
  private locked = false;
  private radius = 0.4;

  constructor(
    private camera: THREE.PerspectiveCamera,
    private dom: HTMLElement,
    private finder: PathFinder,
  ) {
    this.bind();
  }

  private bind(): void {
    document.addEventListener('keydown', (e) => {
      this.keys.add(e.code);
    });
    document.addEventListener('keyup', (e) => this.keys.delete(e.code));
    this.dom.addEventListener('click', () => {
      if (!this.locked) this.dom.requestPointerLock();
    });
    document.addEventListener('pointerlockchange', () => {
      this.locked = document.pointerLockElement === this.dom;
    });
    document.addEventListener('mousemove', (e) => {
      if (!this.locked) return;
      this.yaw -= e.movementX * 0.0022;
      this.pitch -= e.movementY * 0.0022;
      this.pitch = Math.max(-1.45, Math.min(1.45, this.pitch));
    });
  }

  get isLocked(): boolean {
    return this.locked;
  }

  setPosition(x: number, z: number, yaw = 0): void {
    this.camera.position.set(x, HALL.eyeHeight, z);
    this.yaw = yaw;
    this.pitch = 0;
  }

  follow(route: { x: number; z: number }[]): void {
    this.route = route;
    this.routeIdx = 1;
    this.autoWalking = route.length > 1;
  }

  stopAuto(): void {
    this.autoWalking = false;
    this.route = [];
  }

  update(dt: number): void {
    let vx = 0, vz = 0;
    const speed = this.keys.has('ShiftLeft') || this.keys.has('ShiftRight')
      ? HALL.runSpeed
      : HALL.walkSpeed;

    const forward = new THREE.Vector3(-Math.sin(this.yaw), 0, -Math.cos(this.yaw));
    const right = new THREE.Vector3(Math.cos(this.yaw), 0, -Math.sin(this.yaw));

    if (this.keys.has('KeyW') || this.keys.has('ArrowUp')) { vx += forward.x; vz += forward.z; }
    if (this.keys.has('KeyS') || this.keys.has('ArrowDown')) { vx -= forward.x; vz -= forward.z; }
    if (this.keys.has('KeyA') || this.keys.has('ArrowLeft')) { vx -= right.x; vz -= right.z; }
    if (this.keys.has('KeyD') || this.keys.has('ArrowRight')) { vx += right.x; vz += right.z; }

    if (vx || vz) {
      const len = Math.hypot(vx, vz);
      vx = (vx / len) * speed * dt;
      vz = (vz / len) * speed * dt;
      this.moveWithCollision(vx, vz);
    }

    if (this.autoWalking) this.updateAuto(dt);

    this.camera.rotation.set(0, 0, 0);
    this.camera.rotateY(this.yaw);
    this.camera.rotateX(this.pitch);
    this.onMove?.(this.camera.position.x, this.camera.position.z, this.yaw);
  }

  private updateAuto(dt: number): void {
    if (this.routeIdx >= this.route.length) {
      this.autoWalking = false;
      this.onArrive?.();
      return;
    }
    const target = this.route[this.routeIdx];
    const dx = target.x - this.camera.position.x;
    const dz = target.z - this.camera.position.z;
    const dist = Math.hypot(dx, dz);
    if (dist < 0.6) {
      this.routeIdx++;
      return;
    }
    // 平滑转向目标点
    const desiredYaw = Math.atan2(-dx, -dz);
    let dy = desiredYaw - this.yaw;
    while (dy > Math.PI) dy -= Math.PI * 2;
    while (dy < -Math.PI) dy += Math.PI * 2;
    this.yaw += dy * Math.min(1, dt * 6);

    const step = Math.min(dist, HALL.walkSpeed * dt);
    this.moveWithCollision((dx / dist) * step, (dz / dist) * step);
  }

  /** 分轴滑动碰撞：某方向被挡则该轴速度清零，另一轴保留 */
  private moveWithCollision(dx: number, dz: number): void {
    const p = this.camera.position;
    const tryX = p.x + dx;
    if (this.canStand(tryX, p.z)) p.x = tryX;
    const tryZ = p.z + dz;
    if (this.canStand(p.x, tryZ)) p.z = tryZ;

    p.x = Math.max(this.radius, Math.min(HALL.width - this.radius, p.x));
    p.z = Math.max(this.radius, Math.min(HALL.depth - this.radius, p.z));
    p.y = HALL.eyeHeight;
  }

  private canStand(x: number, z: number): boolean {
    // 采样行人包围圆上的 4 个点
    const r = this.radius;
    const cells = [
      this.finder.worldToCell(x, z),
      this.finder.worldToCell(x + r, z),
      this.finder.worldToCell(x - r, z),
      this.finder.worldToCell(x, z + r),
      this.finder.worldToCell(x, z - r),
    ];
    return cells.every((c) => !this.finder.isBlockedCell(c));
  }
}
