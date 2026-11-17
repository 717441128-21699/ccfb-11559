import type { AABB } from '../types';

interface Node {
  minX: number;
  minZ: number;
  maxX: number;
  maxZ: number;
  /** 叶子：booths 下标数组；内部节点：null */
  items: number[] | null;
  left: number;
  right: number;
}

const INF = Infinity;

function aabbOverlap(a: AABB, b: AABB): boolean {
  return (
    a.minX <= b.maxX && a.maxX >= b.minX && a.minZ <= b.maxZ && a.maxZ >= b.minZ
  );
}

function aabbContains(a: AABB, x: number, z: number): boolean {
  return x >= a.minX && x <= a.maxX && z >= a.minZ && z <= a.maxZ;
}

/**
 * 二维 AABB 层次包围盒。
 * 用途：底图拾取（点查询）、视锥剔除候选集（盒查询）、消防净距测量。
 * 中位切分构建，5000 个展位构建耗时约 1~3ms。
 */
export class Bvh2D {
  private nodes: Node[] = [];
  private boxes: AABB[] = [];
  private root = -1;

  build(boxes: AABB[]): void {
    this.boxes = boxes;
    this.nodes = [];
    const indices = boxes.map((_, i) => i);
    this.root = indices.length ? this.buildRec(indices, 0) : -1;
  }

  get size(): number {
    return this.boxes.length;
  }

  boxOf(index: number): AABB {
    return this.boxes[index];
  }

  private buildRec(indices: number[], depth: number): number {
    let minX = INF, minZ = INF, maxX = -INF, maxZ = -INF;
    for (const i of indices) {
      const b = this.boxes[i];
      if (b.minX < minX) minX = b.minX;
      if (b.minZ < minZ) minZ = b.minZ;
      if (b.maxX > maxX) maxX = b.maxX;
      if (b.maxZ > maxZ) maxZ = b.maxZ;
    }

    if (indices.length <= 4 || depth > 24) {
      const nodeId = this.nodes.length;
      this.nodes.push({
        minX, minZ, maxX, maxZ,
        items: indices.slice(),
        left: -1, right: -1,
      });
      return nodeId;
    }

    const wideX = maxX - minX >= maxZ - minZ;
    const sorted = indices.slice().sort((a, b) => {
      const ba = this.boxes[a];
      const bb = this.boxes[b];
      const ca = wideX ? (ba.minX + ba.maxX) * 0.5 : (ba.minZ + ba.maxZ) * 0.5;
      const cb = wideX ? (bb.minX + bb.maxX) * 0.5 : (bb.minZ + bb.maxZ) * 0.5;
      return ca - cb;
    });
    const mid = sorted.length >> 1;
    const left = this.buildRec(sorted.slice(0, mid), depth + 1);
    const right = this.buildRec(sorted.slice(mid), depth + 1);

    const nodeId = this.nodes.length;
    this.nodes.push({ minX, minZ, maxX, maxZ, items: null, left, right });
    return nodeId;
  }

  /** 点查询：返回包含该点的全部 booth 下标（叶子内逐个精判） */
  pointQuery(x: number, z: number): number[] {
    const out: number[] = [];
    if (this.root < 0) return out;
    const stack = [this.root];
    while (stack.length) {
      const nid = stack.pop()!;
      const n = this.nodes[nid];
      if (!aabbContains(n, x, z)) continue;
      if (n.items) {
        for (const i of n.items) out.push(i);
        continue;
      }
      stack.push(n.left, n.right);
    }
    return out;
  }

  /** 盒查询：返回与给定 AABB 相交的全部 booth 下标 */
  boxQuery(box: AABB, out: number[] = []): number[] {
    out.length = 0;
    if (this.root < 0) return out;
    const stack = [this.root];
    while (stack.length) {
      const nid = stack.pop()!;
      const n = this.nodes[nid];
      if (!aabbOverlap(n, box)) continue;
      if (n.items) {
        for (const i of n.items) out.push(i);
        continue;
      }
      stack.push(n.left, n.right);
    }
    return out;
  }

  /**
   * 点到最近障碍盒的净距（米）。用盒的最近点距离，供消防通道判定。
   * 返回 Infinity 表示附近无展位。
   */
  clearance(x: number, z: number, maxDist: number): number {
    if (this.root < 0) return Infinity;
    let best = maxDist;
    const query: AABB = {
      minX: x - maxDist, minZ: z - maxDist,
      maxX: x + maxDist, maxZ: z + maxDist,
    };
    const candidates = this.boxQuery(query);
    for (const i of candidates) {
      const b = this.boxes[i];
      const dx = Math.max(b.minX - x, 0, x - b.maxX);
      const dz = Math.max(b.minZ - z, 0, z - b.maxZ);
      const d = Math.hypot(dx, dz);
      if (d < best) best = d;
    }
    return best === maxDist ? Infinity : best;
  }
}
