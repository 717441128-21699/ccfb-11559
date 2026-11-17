import type { AABB, Booth } from '../types';

/** 展位世界坐标 AABB（异形取多边形包围盒） */
export function boothAabb(b: Booth): AABB {
  if (b.polygon && b.polygon.length >= 3) {
    let minX = Infinity, minZ = Infinity, maxX = -Infinity, maxZ = -Infinity;
    for (const p of b.polygon) {
      if (p.x < minX) minX = p.x;
      if (p.z < minZ) minZ = p.z;
      if (p.x > maxX) maxX = p.x;
      if (p.z > maxZ) maxZ = p.z;
    }
    return { minX, minZ, maxX, maxZ };
  }
  const cos = Math.abs(Math.cos(b.rotation));
  const sin = Math.abs(Math.sin(b.rotation));
  const hw = (b.w * cos + b.d * sin) * 0.5;
  const hd = (b.w * sin + b.d * cos) * 0.5;
  return { minX: b.x - hw, minZ: b.z - hd, maxX: b.x + hw, maxZ: b.z + hd };
}

/** 点是否在展位内（矩形按旋转判断；异形用射线法） */
export function boothContains(b: Booth, x: number, z: number): boolean {
  if (b.polygon && b.polygon.length >= 3) return pointInPolygon(x, z, b.polygon);
  const dx = x - b.x;
  const dz = z - b.z;
  const cos = Math.cos(-b.rotation);
  const sin = Math.sin(-b.rotation);
  const lx = dx * cos - dz * sin;
  const lz = dx * sin + dz * cos;
  return Math.abs(lx) <= b.w * 0.5 && Math.abs(lz) <= b.d * 0.5;
}

export function pointInPolygon(
  x: number,
  z: number,
  poly: { x: number; z: number }[],
): boolean {
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const xi = poly[i].x, zi = poly[i].z;
    const xj = poly[j].x, zj = poly[j].z;
    const intersect =
      zi > z !== zj > z &&
      x < ((xj - xi) * (z - zi)) / (zj - zi) + xi;
    if (intersect) inside = !inside;
  }
  return inside;
}

/**
 * 两 AABB 的消防净距：
 * - 真重叠（有面积交叠）返回负值，负多少表示穿透深度
 * - 仅共享一条边（贴邻）返回 0，合法
 * - 一个轴投影重叠时返回另一轴的净距；斜对角（两轴都不重叠）返回 Infinity
 */
export function aabbGap(a: AABB, b: AABB): number {
  const overlapX = a.minX < b.maxX && a.maxX > b.minX;
  const overlapZ = a.minZ < b.maxZ && a.maxZ > b.minZ;
  if (overlapX && overlapZ) {
    const penX = Math.min(a.maxX - b.minX, b.maxX - a.minX);
    const penZ = Math.min(a.maxZ - b.minZ, b.maxZ - a.minZ);
    return -Math.min(penX, penZ);
  }
  const touchX = a.minX <= b.maxX && a.maxX >= b.minX;
  const touchZ = a.minZ <= b.maxZ && a.maxZ >= b.minZ;
  if (touchX && touchZ) return 0;
  if (touchX) return Math.max(b.minZ - a.maxZ, a.minZ - b.maxZ, 0);
  if (touchZ) return Math.max(b.minX - a.maxX, a.minX - b.maxX, 0);
  return Infinity;
}

/** 吸附到 0.5m 网格 */
export function snap(v: number, step: number): number {
  return Math.round(v / step) * step;
}

export function round1(v: number): number {
  return Math.round(v * 10) / 10;
}
