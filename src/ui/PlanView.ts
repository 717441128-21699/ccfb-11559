import { BOOTH_SPEC, HALL, SNAP } from '../core/config';
import { boothAabb, pointInPolygon, snap } from '../core/geometry';
import type { AABB, Booth, BoothType, Tool } from '../types';
import type { BoothStore } from '../data/BoothStore';

interface DragState {
  mode: 'move' | 'rect' | 'none';
  boothId: number;
  startX: number;
  startZ: number;
  origX: number;
  origZ: number;
}

/**
 * 底图平面编辑器：
 * - 0.5m 吸附网格、展位绘制、批量生成、手画异形、擦除、拖动移动
 * - 所有创建/移动实时走 BoothStore.canPlace 消防校验，不合法红框拦截
 * - 违规展位（净距不足 4m）红色填充
 */
export class PlanView {
  private ctx: CanvasRenderingContext2D;
  private scale = 1;
  private pad = 24;
  private tool: Tool = 'select';
  private boothType: BoothType = 'standard';
  private selectedId = -1;
  private mouse = { x: 0, z: 0, sx: 0, sy: 0 };
  private drag: DragState = { mode: 'none', boothId: -1, startX: 0, startZ: 0, origX: 0, origZ: 0 };
  private polyDraft: { x: number; z: number }[] = [];
  private batchRows = 4;
  private batchCols = 6;
  onSelect: ((b: Booth | null) => void) | null = null;
  onMessage: ((msg: string, ok: boolean) => void) | null = null;

  constructor(
    private canvas: HTMLCanvasElement,
    private store: BoothStore,
  ) {
    this.ctx = canvas.getContext('2d')!;
    this.resize();
    canvas.addEventListener('pointerdown', this.onDown);
    canvas.addEventListener('pointermove', this.onMove);
    canvas.addEventListener('pointerup', this.onUp);
    canvas.addEventListener('dblclick', this.onDblClick);
    canvas.addEventListener('contextmenu', (e) => e.preventDefault());
  }

  destroy(): void {
    this.canvas.removeEventListener('pointerdown', this.onDown);
    this.canvas.removeEventListener('pointermove', this.onMove);
    this.canvas.removeEventListener('pointerup', this.onUp);
    this.canvas.removeEventListener('dblclick', this.onDblClick);
  }

  resize(): void {
    const parent = this.canvas.parentElement!;
    this.canvas.width = parent.clientWidth;
    this.canvas.height = parent.clientHeight;
    this.scale = Math.min(
      (this.canvas.width - this.pad * 2) / HALL.width,
      (this.canvas.height - this.pad * 2) / HALL.depth,
    );
  }

  setTool(t: Tool): void {
    this.tool = t;
    this.polyDraft = [];
    if (t !== 'select') this.setSelected(-1);
  }

  setBoothType(t: BoothType): void {
    this.boothType = t;
  }

  setBatchSize(rows: number, cols: number): void {
    this.batchRows = rows;
    this.batchCols = cols;
  }

  get selected(): Booth | null {
    return this.selectedId >= 0 ? this.store.byId(this.selectedId) ?? null : null;
  }

  setSelected(id: number): void {
    this.selectedId = id;
    this.onSelect?.(this.selected);
  }

  private toScreen(x: number, z: number): [number, number] {
    return [this.pad + x * this.scale, this.pad + z * this.scale];
  }

  private toWorld(sx: number, sy: number): { x: number; z: number } {
    return {
      x: snap((sx - this.pad) / this.scale, SNAP),
      z: snap((sy - this.pad) / this.scale, SNAP),
    };
  }

  private pick(sx: number, sy: number): number {
    const w = this.toWorld(sx, sy);
    const hits = this.store.bvh.pointQuery(w.x, w.z);
    // 小叶子可能返回多个，精判并取最上层（最后创建的）
    for (let i = hits.length - 1; i >= 0; i--) {
      const b = this.store.booths[hits[i]];
      if (b.polygon ? pointInPolygon(w.x, w.z, b.polygon) : this.rectContains(b, w.x, w.z)) {
        return b.id;
      }
    }
    return -1;
  }

  private rectContains(b: Booth, x: number, z: number): boolean {
    return Math.abs(x - b.x) <= b.w / 2 && Math.abs(z - b.z) <= b.d / 2;
  }

  private onDown = (e: PointerEvent): void => {
    const rect = this.canvas.getBoundingClientRect();
    const sx = e.clientX - rect.left;
    const sy = e.clientY - rect.top;
    const w = this.toWorld(sx, sy);
    this.mouse = { x: w.x, z: w.z, sx, sy };

    if (this.tool === 'polygon') {
      this.polyDraft.push({ x: w.x, z: w.z });
      return;
    }

    if (this.tool === 'erase') {
      const id = this.pick(sx, sy);
      if (id >= 0) {
        this.store.remove(id);
        if (this.selectedId === id) this.setSelected(-1);
        this.flash(`已删除展位`, true);
      }
      return;
    }

    if (this.tool === 'select') {
      const id = this.pick(sx, sy);
      this.setSelected(id);
      if (id >= 0) {
        const b = this.store.byId(id)!;
        this.drag = {
          mode: 'move', boothId: id,
          startX: w.x, startZ: w.z, origX: b.x, origZ: b.z,
        };
      }
      return;
    }

    if (this.tool === 'rect' || this.tool === 'batch') {
      this.drag = {
        mode: 'rect', boothId: -1,
        startX: w.x, startZ: w.z, origX: 0, origZ: 0,
      };
    }
  };

  private onMove = (e: PointerEvent): void => {
    const rect = this.canvas.getBoundingClientRect();
    const sx = e.clientX - rect.left;
    const sy = e.clientY - rect.top;
    const w = this.toWorld(sx, sy);
    this.mouse = { x: w.x, z: w.z, sx, sy };

    if (this.drag.mode === 'move' && this.drag.boothId >= 0) {
      const b = this.store.byId(this.drag.boothId);
      if (!b) return;
      const nx = snap(this.drag.origX + (w.x - this.drag.startX), SNAP);
      const nz = snap(this.drag.origZ + (w.z - this.drag.startZ), SNAP);
      const candidate: Booth = { ...b, x: nx, z: nz };
      const check = this.store.canPlace(candidate, b.id);
      if (check.ok) this.store.update(candidate);
    }
  };

  private onUp = (): void => {
    if (this.drag.mode === 'rect') {
      const box = this.dragBox();
      if (box && (box.maxX - box.minX) >= 1 && (box.maxZ - box.minZ) >= 1) {
        if (this.tool === 'rect') this.createSingle(box);
        else this.createBatch(box);
      }
    }
    this.drag = { mode: 'none', boothId: -1, startX: 0, startZ: 0, origX: 0, origZ: 0 };
  };

  private onDblClick = (): void => {
    if (this.tool === 'polygon' && this.polyDraft.length >= 3) {
      this.createPolygon();
    }
  };

  /** 回车键也可闭合多边形 */
  finishPolygon(): void {
    if (this.polyDraft.length >= 3) this.createPolygon();
  }

  cancelPolygon(): void {
    this.polyDraft = [];
  }

  private dragBox(): AABB | null {
    if (this.drag.mode !== 'rect') return null;
    const { startX, startZ } = this.drag;
    return {
      minX: Math.min(startX, this.mouse.x),
      maxX: Math.max(startX, this.mouse.x),
      minZ: Math.min(startZ, this.mouse.z),
      maxZ: Math.max(startZ, this.mouse.z),
    };
  }

  private createSingle(box: AABB): void {
    const spec = BOOTH_SPEC[this.boothType];
    const booth: Booth = {
      id: this.store.allocId(),
      code: `M${this.store.booths.length + 1}`,
      exhibitor: '待命名展商',
      type: this.boothType,
      x: (box.minX + box.maxX) / 2,
      z: (box.minZ + box.maxZ) / 2,
      w: Math.max(spec.w, box.maxX - box.minX),
      d: Math.max(spec.d, box.maxZ - box.minZ),
      rotation: 0,
      color: spec.color,
    };
    const check = this.store.canPlace(booth);
    if (!check.ok) {
      this.flash(check.reason ?? '无法放置', false);
      return;
    }
    this.store.add(booth);
    this.setSelected(booth.id);
    this.flash(`已创建展位 ${booth.code}`, true);
  }

  /** 批量：在拖出的区域内按行列铺满，自动跳过不合规格位 */
  private createBatch(box: AABB): void {
    const spec = BOOTH_SPEC[this.boothType];
    const created: Booth[] = [];
    let skipped = 0;
    for (let r = 0; r < this.batchRows; r++) {
      for (let c = 0; c < this.batchCols; c++) {
        const x = box.minX + spec.w * (c + 0.5);
        const z = box.minZ + spec.d * (r + 0.5);
        if (x + spec.w / 2 > box.maxX || z + spec.d / 2 > box.maxZ) continue;
        const booth: Booth = {
          id: this.store.allocId(),
          code: `B${this.store.booths.length + created.length + 1}`,
          exhibitor: '待命名展商',
          type: this.boothType,
          x, z, w: spec.w, d: spec.d, rotation: 0, color: spec.color,
        };
        const check = this.store.canPlace(booth);
        if (check.ok) created.push(booth);
        else skipped++;
      }
    }
    if (created.length) this.store.addAll(created);
    this.flash(
      skipped ? `批量生成 ${created.length} 个，${skipped} 个因消防间距被拦截` : `批量生成 ${created.length} 个展位`,
      created.length > 0,
    );
  }

  private createPolygon(): void {
    const xs = this.polyDraft.map((p) => p.x);
    const zs = this.polyDraft.map((p) => p.z);
    const spec = BOOTH_SPEC.custom;
    const booth: Booth = {
      id: this.store.allocId(),
      code: `Z${this.store.booths.length + 1}`,
      exhibitor: '待命名展商',
      type: 'custom',
      x: (Math.min(...xs) + Math.max(...xs)) / 2,
      z: (Math.min(...zs) + Math.max(...zs)) / 2,
      w: Math.max(...xs) - Math.min(...xs),
      d: Math.max(...zs) - Math.min(...zs),
      rotation: 0,
      polygon: this.polyDraft.map((p) => ({ ...p })),
      color: spec.color,
    };
    const check = this.store.canPlace(booth);
    if (!check.ok) {
      this.flash(check.reason ?? '异形展位无法放置', false);
      return;
    }
    this.store.add(booth);
    this.polyDraft = [];
    this.setSelected(booth.id);
    this.flash(`已创建异形展位 ${booth.code}`, true);
  }

  private flash(msg: string, ok: boolean): void {
    this.onMessage?.(msg, ok);
  }

  // ---------------- 渲染 ----------------

  render(): void {
    const c = this.ctx;
    c.clearRect(0, 0, this.canvas.width, this.canvas.height);
    c.fillStyle = '#e9edf2';
    c.fillRect(0, 0, this.canvas.width, this.canvas.height);

    const [hx, hy] = this.toScreen(0, 0);
    const w = HALL.width * this.scale;
    const h = HALL.depth * this.scale;
    c.fillStyle = '#ffffff';
    c.fillRect(hx, hy, w, h);

    this.drawGrid(c, hx, hy, w, h);

    for (const b of this.store.booths) this.drawBooth(c, b);

    this.drawDraft(c);
    this.drawHover(c);
    this.drawPolyDraft(c);

    c.strokeStyle = '#1d2b3a';
    c.lineWidth = 2;
    c.strokeRect(hx, hy, w, h);
  }

  private drawGrid(c: CanvasRenderingContext2D, hx: number, hy: number, w: number, h: number): void {
    c.strokeStyle = '#eef1f5';
    c.lineWidth = 1;
    const step = this.scale * SNAP * 2; // 1m 一格
    for (let x = hx; x <= hx + w; x += step) {
      c.beginPath(); c.moveTo(x, hy); c.lineTo(x, hy + h); c.stroke();
    }
    for (let y = hy; y <= hy + h; y += step) {
      c.beginPath(); c.moveTo(hx, y); c.lineTo(hx + w, y); c.stroke();
    }
  }

  private drawBooth(c: CanvasRenderingContext2D, b: Booth): void {
    const selected = b.id === this.selectedId;
    const violation = this.store.violations.has(b.id);
    const fill = violation
      ? 'rgba(255,59,48,0.75)'
      : selected ? '#ff9f0a' : `#${b.color.toString(16).padStart(6, '0')}`;
    c.fillStyle = fill;
    c.strokeStyle = selected ? '#8a5400' : 'rgba(29,43,58,0.55)';
    c.lineWidth = selected ? 2 : 1;

    if (b.polygon && b.polygon.length >= 3) {
      c.beginPath();
      b.polygon.forEach((p, i) => {
        const [sx, sy] = this.toScreen(p.x, p.z);
        if (i === 0) c.moveTo(sx, sy); else c.lineTo(sx, sy);
      });
      c.closePath();
      c.fill();
      c.stroke();
    } else {
      const [x, y] = this.toScreen(b.x - b.w / 2, b.z - b.d / 2);
      c.fillRect(x, y, b.w * this.scale, b.d * this.scale);
      c.strokeRect(x, y, b.w * this.scale, b.d * this.scale);
    }

    // 展位号（缩放到合适才画，避免 5000 个挤成一团）
    if (this.scale > 0.8) {
      const [cx, cy] = this.toScreen(b.x, b.z);
      c.fillStyle = violation ? '#fff' : '#1d2b3a';
      c.font = `${Math.min(11, b.w * this.scale * 0.4)}px sans-serif`;
      c.textAlign = 'center';
      c.textBaseline = 'middle';
      c.fillText(b.code, cx, cy);
    }
  }

  private drawHover(c: CanvasRenderingContext2D): void {
    if (this.tool !== 'select' || this.drag.mode === 'move') return;
    const id = this.pick(this.mouse.sx, this.mouse.sy);
    if (id < 0) return;
    const b = this.store.byId(id)!;
    const a = boothAabb(b);
    const [x, y] = this.toScreen(a.minX, a.minZ);
    c.strokeStyle = '#ffd60a';
    c.lineWidth = 2;
    c.strokeRect(x, y, (a.maxX - a.minX) * this.scale, (a.maxZ - a.minZ) * this.scale);
  }

  private drawDraft(c: CanvasRenderingContext2D): void {
    const box = this.dragBox();
    if (!box) return;
    const spec = BOOTH_SPEC[this.boothType];
    const ok = this.previewOk(box);
    c.fillStyle = ok ? 'rgba(52,199,89,0.25)' : 'rgba(255,59,48,0.25)';
    c.strokeStyle = ok ? '#34c759' : '#ff3b30';
    c.lineWidth = 2;
    const [x, y] = this.toScreen(box.minX, box.minZ);
    c.fillRect(x, y, (box.maxX - box.minX) * this.scale, (box.maxZ - box.minZ) * this.scale);
    c.strokeRect(x, y, (box.maxX - box.minX) * this.scale, (box.maxZ - box.minZ) * this.scale);

    if (this.tool === 'batch') {
      c.strokeStyle = 'rgba(10,132,255,0.8)';
      c.lineWidth = 1;
      for (let r = 0; r < this.batchRows; r++) {
        for (let col = 0; col < this.batchCols; col++) {
          const gx = box.minX + spec.w * col;
          const gz = box.minZ + spec.d * r;
          if (gx + spec.w > box.maxX || gz + spec.d > box.maxZ) continue;
          const [sx, sy] = this.toScreen(gx, gz);
          c.strokeRect(sx, sy, spec.w * this.scale, spec.d * this.scale);
        }
      }
    }
  }

  private previewOk(box: AABB): boolean {
    const spec = BOOTH_SPEC[this.boothType];
    const candidate: Booth = {
      id: -1, code: '', exhibitor: '', type: this.boothType,
      x: (box.minX + box.maxX) / 2,
      z: (box.minZ + box.maxZ) / 2,
      w: Math.max(spec.w, box.maxX - box.minX),
      d: Math.max(spec.d, box.maxZ - box.minZ),
      rotation: 0, color: spec.color,
    };
    return this.store.canPlace(candidate).ok;
  }

  private drawPolyDraft(c: CanvasRenderingContext2D): void {
    if (this.tool !== 'polygon' || this.polyDraft.length === 0) return;
    c.strokeStyle = '#0a84ff';
    c.fillStyle = 'rgba(10,132,255,0.15)';
    c.lineWidth = 2;
    c.beginPath();
    this.polyDraft.forEach((p, i) => {
      const [sx, sy] = this.toScreen(p.x, p.z);
      if (i === 0) c.moveTo(sx, sy); else c.lineTo(sx, sy);
    });
    const [mx, my] = this.toScreen(this.mouse.x, this.mouse.z);
    c.lineTo(mx, my);
    c.stroke();
    for (const p of this.polyDraft) {
      const [sx, sy] = this.toScreen(p.x, p.z);
      c.beginPath();
      c.arc(sx, sy, 4, 0, Math.PI * 2);
      c.fillStyle = '#0a84ff';
      c.fill();
    }
  }
}
