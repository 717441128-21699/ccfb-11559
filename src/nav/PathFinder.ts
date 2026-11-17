import { HALL, PATH_MAX_NODES } from '../core/config';
import type { AABB } from '../types';
import { boothAabb } from '../core/geometry';
import type { BoothStore } from '../data/BoothStore';

/**
 * 栅格 A* 寻路。
 * - 0.5m 栅格覆盖全馆（720x480 ≈ 34.6 万格）
 * - 展位 AABB 膨胀 agent 半径后标记阻挡，贴邻展位之间的 4.5m 通道仍可通行
 * - 二叉堆 open list；单次搜索限制 PATH_MAX_NODES 个节点，超时返回最近路径
 * - 路径做视线弦切（string pulling）压缩，输出平滑折线
 */
export class PathFinder {
  readonly cell = HALL.cell;
  readonly cols: number;
  readonly rows: number;
  /** 阻挡栅格：Uint8 惰性分配行块，节省内存 */
  private blocked: Uint8Array;
  private heap: number[] = [];
  private gScore: Float32Array;
  private cameFrom: Int32Array;
  private closed: Int32Array;
  private stamp = 0;

  constructor(private store: BoothStore) {
    this.cols = Math.round(HALL.width / this.cell);
    this.rows = Math.round(HALL.depth / this.cell);
    const n = this.cols * this.rows;
    this.blocked = new Uint8Array(n);
    this.gScore = new Float32Array(n);
    this.cameFrom = new Int32Array(n);
    this.closed = new Int32Array(n);
  }

  /** 按当前展位重建阻挡栅格（数据变更后调用） */
  rebuild(): void {
    this.blocked.fill(0);
    const r = 0.4; // 行人半径，膨胀用
    for (const b of this.store.booths) this.rasterize(boothAabb(b), r);
    // 馆墙外一圈也挡住
    const wall = Math.ceil(r / this.cell);
    for (let x = 0; x < this.cols; x++) {
      for (let z = 0; z < wall; z++) {
        this.blocked[z * this.cols + x] = 1;
        this.blocked[(this.rows - 1 - z) * this.cols + x] = 1;
      }
    }
    for (let z = 0; z < this.rows; z++) {
      for (let x = 0; x < wall; x++) {
        this.blocked[z * this.cols + x] = 1;
        this.blocked[z * this.cols + (this.cols - 1 - x)] = 1;
      }
    }
  }

  private rasterize(box: AABB, radius: number): void {
    const x0 = Math.max(0, Math.floor((box.minX - radius) / this.cell));
    const x1 = Math.min(this.cols - 1, Math.floor((box.maxX + radius) / this.cell));
    const z0 = Math.max(0, Math.floor((box.minZ - radius) / this.cell));
    const z1 = Math.min(this.rows - 1, Math.floor((box.maxZ + radius) / this.cell));
    for (let z = z0; z <= z1; z++) {
      const base = z * this.cols;
      for (let x = x0; x <= x1; x++) this.blocked[base + x] = 1;
    }
  }

  worldToCell(x: number, z: number): number {
    const cx = Math.min(this.cols - 1, Math.max(0, Math.floor(x / this.cell)));
    const cz = Math.min(this.rows - 1, Math.max(0, Math.floor(z / this.cell)));
    return cz * this.cols + cx;
  }

  cellCenter(idx: number): { x: number; z: number } {
    const cx = idx % this.cols;
    const cz = Math.floor(idx / this.cols);
    return { x: (cx + 0.5) * this.cell, z: (cz + 0.5) * this.cell };
  }

  private isFree(idx: number): boolean {
    return idx >= 0 && idx < this.blocked.length && this.blocked[idx] === 0;
  }

  /** 返回世界坐标折线；不可达时返回走到最近可行点的路径 */
  findPath(sx: number, sz: number, tx: number, tz: number): { x: number; z: number }[] {
    this.stamp++;
    const start = this.nearestFree(this.worldToCell(sx, sz));
    const goal = this.nearestFree(this.worldToCell(tx, tz));
    if (start < 0 || goal < 0) return [];

    this.heap.length = 0;
    this.closed.fill(0);
    this.cameFrom.fill(-1);
    this.gScore.fill(Infinity);
    this.gScore[start] = 0;

    const h = (idx: number) => {
      const dx = (idx % this.cols) - (goal % this.cols);
      const dz = Math.floor(idx / this.cols) - Math.floor(goal / this.cols);
      // 八方向启发：对角系数 sqrt2
      const adx = Math.abs(dx), adz = Math.abs(dz);
      return (adx + adz) + (Math.SQRT2 - 2) * Math.min(adx, adz);
    };

    const fScore = new Map<number, number>();
    fScore.set(start, h(start));
    this.heapPush(start, fScore);
    let expanded = 0;
    let closest = start;
    let closestH = fScore.get(start)!;

    const N = this.cols;
    while (this.heap.length) {
      const cur = this.heapPop(fScore);
      if (cur === goal) return this.trace(cur, sx, sz, tx, tz);
      if (this.closed[cur] === this.stamp) continue;
      this.closed[cur] = this.stamp;
      if (++expanded > PATH_MAX_NODES) break;

      const cx = cur % N;
      const cz = Math.floor(cur / N);
      for (let dz = -1; dz <= 1; dz++) {
        for (let dx = -1; dx <= 1; dx++) {
          if (!dx && !dz) continue;
          const nx = cx + dx, nz = cz + dz;
          if (nx < 0 || nz < 0 || nx >= this.cols || nz >= this.rows) continue;
          const next = nz * N + nx;
          if (!this.isFree(next) || this.closed[next] === this.stamp) continue;
          // 对角移动不能贴角穿墙
          if (dx && dz) {
            if (!this.isFree(cur + dx) || !this.isFree(cur + dz * N)) continue;
          }
          const step = dx && dz ? Math.SQRT2 : 1;
          const g = this.gScore[cur] + step;
          if (g < this.gScore[next]) {
            this.gScore[next] = g;
            this.cameFrom[next] = cur;
            const f = g + h(next);
            fScore.set(next, f);
            this.heapPush(next, fScore);
            const hn = h(next);
            if (hn < closestH) { closestH = hn; closest = next; }
          }
        }
      }
    }

    // 不可达/超限：沿最近节点回溯
    return this.trace(closest, sx, sz, tx, tz, true);
  }

  private nearestFree(idx: number): number {
    if (this.isFree(idx)) return idx;
    // BFS 扩散找最近空闲格
    const q = [idx];
    const seen = new Set<number>([idx]);
    while (q.length) {
      const cur = q.shift()!;
      const cx = cur % this.cols, cz = Math.floor(cur / this.cols);
      for (let dz = -1; dz <= 1; dz++) {
        for (let dx = -1; dx <= 1; dx++) {
          const nx = cx + dx, nz = cz + dz;
          if (nx < 0 || nz < 0 || nx >= this.cols || nz >= this.rows) continue;
          const n = nz * this.cols + nx;
          if (seen.has(n)) continue;
          seen.add(n);
          if (this.isFree(n)) return n;
          q.push(n);
        }
      }
      if (seen.size > 4000) break;
    }
    return -1;
  }

  private trace(
    end: number, sx: number, sz: number, tx: number, tz: number, partial = false,
  ): { x: number; z: number }[] {
    const cells: number[] = [];
    let cur = end;
    while (cur >= 0) {
      cells.push(cur);
      cur = this.cameFrom[cur];
    }
    cells.reverse();
    const pts = cells.map((i) => this.cellCenter(i));
    pts.unshift({ x: sx, z: sz });
    if (!partial) pts.push({ x: tx, z: tz });
    return this.stringPull(pts);
  }

  /** 视线弦切：若两点连线不穿阻挡，则跳过中间节点 */
  private stringPull(pts: { x: number; z: number }[]): { x: number; z: number }[] {
    if (pts.length <= 2) return pts;
    const out = [pts[0]];
    let anchor = 0;
    for (let i = 2; i < pts.length; i++) {
      if (!this.lineFree(pts[anchor], pts[i])) {
        out.push(pts[i - 1]);
        anchor = i - 1;
      }
    }
    out.push(pts[pts.length - 1]);
    return out;
  }

  private lineFree(a: { x: number; z: number }, b: { x: number; z: number }): boolean {
    const dist = Math.hypot(b.x - a.x, b.z - a.z);
    const steps = Math.max(1, Math.ceil(dist / (this.cell * 0.5)));
    for (let i = 1; i < steps; i++) {
      const t = i / steps;
      const x = a.x + (b.x - a.x) * t;
      const z = a.z + (b.z - a.z) * t;
      if (!this.isFree(this.worldToCell(x, z))) return false;
    }
    return true;
  }

  private heapPush(idx: number, f: Map<number, number>): void {
    this.heap.push(idx);
    let i = this.heap.length - 1;
    while (i > 0) {
      const p = (i - 1) >> 1;
      if (f.get(this.heap[p])! <= f.get(this.heap[i])!) break;
      [this.heap[p], this.heap[i]] = [this.heap[i], this.heap[p]];
      i = p;
    }
  }

  private heapPop(f: Map<number, number>): number {
    const top = this.heap[0];
    const last = this.heap.pop()!;
    if (this.heap.length) {
      this.heap[0] = last;
      let i = 0;
      for (;;) {
        const l = i * 2 + 1, r = l + 1;
        let best = i;
        if (l < this.heap.length && f.get(this.heap[l])! < f.get(this.heap[best])!) best = l;
        if (r < this.heap.length && f.get(this.heap[r])! < f.get(this.heap[best])!) best = r;
        if (best === i) break;
        [this.heap[best], this.heap[i]] = [this.heap[i], this.heap[best]];
        i = best;
      }
    }
    return top;
  }

  /** 供小地图绘制阻挡层 */
  isBlockedCell(idx: number): boolean {
    return this.blocked[idx] === 1;
  }
}
