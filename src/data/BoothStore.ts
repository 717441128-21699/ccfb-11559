import type { AABB, Booth, PlacementCheck, SearchHit } from '../types';
import { HALL } from '../core/config';
import { Bvh2D } from '../core/bvh';
import { aabbGap, boothAabb } from '../core/geometry';

export type StoreEvent = 'change' | 'violations';

type Listener = () => void;

/**
 * 展位数据中枢：BVH 空间索引 + 消防净距校验 + 搜索。
 * 编辑侧（底图）与运行侧（三维/寻路）共享同一份数据。
 */
export class BoothStore {
  booths: Booth[] = [];
  readonly bvh = new Bvh2D();
  /** 违反消防通道的展位 id 集合（净距 0<gap<4m） */
  violations = new Set<number>();
  private nextId = 1;
  private listeners = new Set<Listener>();

  on(_e: StoreEvent, fn: Listener): () => void {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  private emit(): void {
    for (const fn of this.listeners) fn();
  }

  allocId(): number {
    return this.nextId++;
  }

  add(booth: Booth): void {
    if (booth.id >= this.nextId) this.nextId = booth.id + 1;
    this.booths.push(booth);
    this.rebuildIndex();
    this.emit();
  }

  addAll(booths: Booth[]): void {
    for (const b of booths) {
      if (b.id >= this.nextId) this.nextId = b.id + 1;
      this.booths.push(b);
    }
    this.rebuildIndex();
    this.recomputeViolations();
    this.emit();
  }

  remove(id: number): void {
    this.booths = this.booths.filter((b) => b.id !== id);
    this.violations.delete(id);
    this.rebuildIndex();
    this.recomputeViolations();
    this.emit();
  }

  update(booth: Booth): void {
    const i = this.booths.findIndex((b) => b.id === booth.id);
    if (i >= 0) this.booths[i] = booth;
    this.rebuildIndex();
    this.recomputeViolations();
    this.emit();
  }

  clear(): void {
    this.booths = [];
    this.violations.clear();
    this.rebuildIndex();
    this.emit();
  }

  byId(id: number): Booth | undefined {
    return this.booths.find((b) => b.id === id);
  }

  byCode(code: string): Booth | undefined {
    return this.booths.find((b) => b.code === code);
  }

  rebuildIndex(): void {
    this.bvh.build(this.booths.map(boothAabb));
  }

  /**
   * 放置/移动校验：
   * 1. 必须在馆内；2. 不得与其他展位重叠；
   * 3. 与其他展位要么贴邻（gap=0，共用隔断），要么净距 >= 消防通道宽度。
   */
  canPlace(candidate: Booth, ignoreId = -1): PlacementCheck {
    const box = boothAabb(candidate);
    if (
      box.minX < 0 || box.minZ < 0 ||
      box.maxX > HALL.width || box.maxZ > HALL.depth
    ) {
      return { ok: false, reason: '超出展馆边界' };
    }
    const pad: AABB = {
      minX: box.minX - HALL.fireLaneWidth,
      minZ: box.minZ - HALL.fireLaneWidth,
      maxX: box.maxX + HALL.fireLaneWidth,
      maxZ: box.maxZ + HALL.fireLaneWidth,
    };
    const nearby = this.bvh.boxQuery(pad);
    let worst: number | undefined;
    for (const idx of nearby) {
      const other = this.booths[idx];
      if (other.id === ignoreId) continue;
      const gap = aabbGap(box, boothAabb(other));
      const eps = 0.05;
      if (gap < -eps) {
        return { ok: false, reason: `与展位 ${other.code} 重叠` };
      }
      if (gap > eps && gap < HALL.fireLaneWidth - eps) {
        worst = worst === undefined ? gap : Math.min(worst, gap);
      }
    }
    if (worst !== undefined) {
      return {
        ok: false,
        reason: `消防通道净距仅 ${worst.toFixed(1)}m，要求 ≥ ${HALL.fireLaneWidth}m`,
        clearance: worst,
      };
    }
    return { ok: true };
  }

  /**
   * 全量扫描违规展位，O(n log n)。
   * 规则：对每个展位只看四方向上【投影重叠最多、距离最近】的正对邻居，
   * 若最近净距落在 (0, 4m) 之间且缝隙未被第三个展位占据，判违规。
   * 隔位邻居（中间还隔着展位）不会被当成通道。
   */
  recomputeViolations(): void {
    const v = new Set<number>();
    const mark = (a: Booth, b: Booth, gap: number) => {
      if (this.gapObstructed(boothAabb(a), boothAabb(b), a.id, b.id)) return;
      v.add(a.id);
      v.add(b.id);
      void gap;
    };

    for (const b of this.booths) {
      const box = boothAabb(b);
      const nearby = this.bvh.boxQuery({
        minX: box.minX - HALL.fireLaneWidth,
        minZ: box.minZ - HALL.fireLaneWidth,
        maxX: box.maxX + HALL.fireLaneWidth,
        maxZ: box.maxZ + HALL.fireLaneWidth,
      });

      // 四个方向各找一个投影重叠且最近的邻居
      type Cand = { o: Booth; gap: number; overlap: number };
      let zPlus: Cand | null = null;
      let zMinus: Cand | null = null;
      let xPlus: Cand | null = null;
      let xMinus: Cand | null = null;

      for (const idx of nearby) {
        const o = this.booths[idx];
        if (o.id === b.id) continue;
        const ob = boothAabb(o);
        const overlapX = Math.min(box.maxX, ob.maxX) - Math.max(box.minX, ob.minX);
        const overlapZ = Math.min(box.maxZ, ob.maxZ) - Math.max(box.minZ, ob.minZ);
        if (overlapX > 0.05) {
          if (ob.minZ >= box.maxZ - 0.05) {
            const gap = ob.minZ - box.maxZ;
            if (gap > 0.05 && (!zPlus || gap < zPlus.gap)) zPlus = { o, gap, overlap: overlapX };
          } else if (ob.maxZ <= box.minZ + 0.05) {
            const gap = box.minZ - ob.maxZ;
            if (gap > 0.05 && (!zMinus || gap < zMinus.gap)) zMinus = { o, gap, overlap: overlapX };
          }
        }
        if (overlapZ > 0.05) {
          if (ob.minX >= box.maxX - 0.05) {
            const gap = ob.minX - box.maxX;
            if (gap > 0.05 && (!xPlus || gap < xPlus.gap)) xPlus = { o, gap, overlap: overlapZ };
          } else if (ob.maxX <= box.minX + 0.05) {
            const gap = box.minX - ob.maxX;
            if (gap > 0.05 && (!xMinus || gap < xMinus.gap)) xMinus = { o, gap, overlap: overlapZ };
          }
        }
      }

      for (const cand of [zPlus, zMinus, xPlus, xMinus]) {
        if (cand && cand.gap < HALL.fireLaneWidth - 0.05) mark(b, cand.o, cand.gap);
      }
    }
    this.violations = v;
  }

  /**
   * 判断两个正对盒子之间的缝隙是否被其他展位占据。
   * 沿净距方向在缝隙中点取一条采样线，若某采样点落在第三个展位内则视为有遮挡。
   */
  private gapObstructed(a: AABB, b: AABB, idA: number, idB: number): boolean {
    const overlapX = a.minX <= b.maxX && a.maxX >= b.minX;
    // 缝隙方向：overlapX 时沿 Z，否则沿 X
    const samples: { x: number; z: number }[] = [];
    if (overlapX) {
      const z = a.maxZ < b.minZ ? (a.maxZ + b.minZ) / 2 : (b.maxZ + a.minZ) / 2;
      const x0 = Math.max(a.minX, b.minX) + 0.1;
      const x1 = Math.min(a.maxX, b.maxX) - 0.1;
      for (let x = x0; x <= x1; x += 0.5) samples.push({ x, z });
    } else {
      const x = a.maxX < b.minX ? (a.maxX + b.minX) / 2 : (b.maxX + a.minX) / 2;
      const z0 = Math.max(a.minZ, b.minZ) + 0.1;
      const z1 = Math.min(a.maxZ, b.maxZ) - 0.1;
      for (let z = z0; z <= z1; z += 0.5) samples.push({ x, z });
    }
    if (samples.length === 0) return false;

    const pad: AABB = {
      minX: Math.min(...samples.map((p) => p.x)) - 0.6,
      minZ: Math.min(...samples.map((p) => p.z)) - 0.6,
      maxX: Math.max(...samples.map((p) => p.x)) + 0.6,
      maxZ: Math.max(...samples.map((p) => p.z)) + 0.6,
    };
    for (const i of this.bvh.boxQuery(pad)) {
      const third = this.booths[i];
      if (third.id === idA || third.id === idB) continue;
      const tb = boothAabb(third);
      // 用 AABB 包含采样点判断（规则展位都是矩形；异形极少且在边缘）
      for (const p of samples) {
        if (p.x >= tb.minX && p.x <= tb.maxX && p.z >= tb.minZ && p.z <= tb.maxZ) {
          return true;
        }
      }
    }
    return false;
  }

  /** 展商名/展位号搜索，前缀命中优先，返回前 20 条 */
  search(query: string): SearchHit[] {
    const q = query.trim().toLowerCase();
    if (!q) return [];
    const hits: SearchHit[] = [];
    for (const b of this.booths) {
      const name = b.exhibitor.toLowerCase();
      const code = b.code.toLowerCase();
      let score = -1;
      if (name.startsWith(q) || code.startsWith(q)) score = 0;
      else if (name.includes(q) || code.includes(q)) score = 1;
      else {
        // 拼音首字母式的字符包含兜底：每个查询字符都出现即命中
        const chars = [...new Set(q)];
        if (chars.every((c) => name.includes(c) || code.includes(c))) score = 2;
      }
      if (score >= 0) hits.push({ booth: b, score });
    }
    hits.sort((a, b) => a.score - b.score || a.booth.code.localeCompare(b.booth.code));
    return hits.slice(0, 20);
  }

  serialize(): string {
    return JSON.stringify({ version: 1, booths: this.booths });
  }

  load(json: string): void {
    const data = JSON.parse(json) as { booths: Booth[] };
    this.booths = data.booths;
    this.nextId = this.booths.reduce((m, b) => Math.max(m, b.id + 1), 1);
    this.rebuildIndex();
    this.recomputeViolations();
    this.emit();
  }
}
