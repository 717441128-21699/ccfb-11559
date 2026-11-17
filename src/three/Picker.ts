import * as THREE from 'three';
import { boothAabb } from '../core/geometry';
import type { BoothStore } from '../data/BoothStore';

/**
 * 三维拾取：屏幕射线先与 BVH 粗筛的候选 AABB 做 slab 求交，
 * 再按距离取最近展位。5000 个展位的拾取通常 < 1ms，满足 50ms 指标。
 */
export class Picker {
  private ray = new THREE.Raycaster();
  private ndc = new THREE.Vector2();

  constructor(private store: BoothStore) {}

  pick(
    clientX: number,
    clientY: number,
    dom: HTMLElement,
    camera: THREE.PerspectiveCamera,
  ): number {
    const rect = dom.getBoundingClientRect();
    this.ndc.x = ((clientX - rect.left) / rect.width) * 2 - 1;
    this.ndc.y = -((clientY - rect.top) / rect.height) * 2 + 1;
    this.ray.setFromCamera(this.ndc, camera);

    const o = this.ray.ray.origin;
    const d = this.ray.ray.direction;
    // 用射线方向投影的大盒从 BVH 取候选
    const reach = 300;
    const candidates = this.store.bvh.boxQuery({
      minX: o.x - reach, minZ: o.z - reach,
      maxX: o.x + reach, maxZ: o.z + reach,
    });

    let bestId = -1;
    let bestT = Infinity;
    for (const idx of candidates) {
      const b = this.store.booths[idx];
      const a = boothAabb(b);
      const t = this.rayBox(o, d, a.minX, 0.1, a.minZ, a.maxX, 4.2, a.maxZ);
      if (t !== null && t < bestT) {
        bestT = t;
        bestId = b.id;
      }
    }
    return bestId;
  }

  /**  slabs 法射线-AABB 求交，返回最近进入距离 t，不相交返回 null */
  private rayBox(
    o: THREE.Vector3, d: THREE.Vector3,
    minX: number, minY: number, minZ: number,
    maxX: number, maxY: number, maxZ: number,
  ): number | null {
    let tmin = -Infinity;
    let tmax = Infinity;

    // X
    let t1: number, t2: number;
    if (Math.abs(d.x) < 1e-8) {
      if (o.x < minX || o.x > maxX) return null;
    } else {
      t1 = (minX - o.x) / d.x;
      t2 = (maxX - o.x) / d.x;
      if (t1 > t2) [t1, t2] = [t2, t1];
      tmin = Math.max(tmin, t1);
      tmax = Math.min(tmax, t2);
      if (tmin > tmax) return null;
    }
    // Y
    if (Math.abs(d.y) < 1e-8) {
      if (o.y < minY || o.y > maxY) return null;
    } else {
      t1 = (minY - o.y) / d.y;
      t2 = (maxY - o.y) / d.y;
      if (t1 > t2) [t1, t2] = [t2, t1];
      tmin = Math.max(tmin, t1);
      tmax = Math.min(tmax, t2);
      if (tmin > tmax) return null;
    }
    // Z
    if (Math.abs(d.z) < 1e-8) {
      if (o.z < minZ || o.z > maxZ) return null;
    } else {
      t1 = (minZ - o.z) / d.z;
      t2 = (maxZ - o.z) / d.z;
      if (t1 > t2) [t1, t2] = [t2, t1];
      tmin = Math.max(tmin, t1);
      tmax = Math.min(tmax, t2);
      if (tmin > tmax) return null;
    }
    return tmax < 0 ? null : Math.max(tmin, 0);
  }
}
