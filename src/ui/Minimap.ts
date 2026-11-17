import { HALL } from '../core/config';
import type { BoothStore } from '../data/BoothStore';

/**
 * 小地图：离屏画布缓存静态展位层，每帧只重绘位置箭头与路线，
 * 5000 个展位的底图刷新与帧率解耦。
 */
export class Minimap {
  private ctx: CanvasRenderingContext2D;
  private staticCanvas: HTMLCanvasElement;
  private dirty = true;
  private scale: number;

  constructor(
    private canvas: HTMLCanvasElement,
    private store: BoothStore,
  ) {
    this.ctx = canvas.getContext('2d')!;
    this.staticCanvas = document.createElement('canvas');
    this.staticCanvas.width = canvas.width;
    this.staticCanvas.height = canvas.height;
    this.scale = Math.min(canvas.width / HALL.width, canvas.height / HALL.depth);
  }

  markDirty(): void {
    this.dirty = true;
  }

  private toX(x: number): number {
    return x * this.scale;
  }
  private toZ(z: number): number {
    return z * this.scale;
  }

  private renderStatic(): void {
    const c = this.staticCanvas.getContext('2d')!;
    c.clearRect(0, 0, this.canvas.width, this.canvas.height);
    c.fillStyle = '#f7f8fa';
    c.fillRect(0, 0, this.canvas.width, this.canvas.height);

    for (const b of this.store.booths) {
      const violation = this.store.violations.has(b.id);
      c.fillStyle = violation ? '#ff3b30' : `#${b.color.toString(16).padStart(6, '0')}`;
      if (b.polygon && b.polygon.length >= 3) {
        c.beginPath();
        b.polygon.forEach((p, i) => {
          const x = this.toX(p.x), z = this.toZ(p.z);
          if (i === 0) c.moveTo(x, z); else c.lineTo(x, z);
        });
        c.closePath();
        c.fill();
      } else {
        c.fillRect(
          this.toX(b.x - b.w / 2),
          this.toZ(b.z - b.d / 2),
          b.w * this.scale,
          b.d * this.scale,
        );
      }
    }
    this.dirty = false;
  }

  render(
    x: number,
    z: number,
    yaw: number,
    route: { x: number; z: number }[],
    targetId = -1,
  ): void {
    if (this.dirty) this.renderStatic();
    const c = this.ctx;
    c.clearRect(0, 0, this.canvas.width, this.canvas.height);
    c.drawImage(this.staticCanvas, 0, 0);

    // 路线
    if (route.length > 1) {
      c.strokeStyle = '#0a84ff';
      c.lineWidth = 2;
      c.beginPath();
      route.forEach((p, i) => {
        const px = this.toX(p.x), pz = this.toZ(p.z);
        if (i === 0) c.moveTo(px, pz); else c.lineTo(px, pz);
      });
      c.stroke();
    }

    // 目标展位描边
    if (targetId >= 0) {
      const b = this.store.byId(targetId);
      if (b) {
        c.strokeStyle = '#ff9f0a';
        c.lineWidth = 2;
        c.strokeRect(
          this.toX(b.x - b.w / 2) - 2,
          this.toZ(b.z - b.d / 2) - 2,
          b.w * this.scale + 4,
          b.d * this.scale + 4,
        );
      }
    }

    // 位置箭头
    const px = this.toX(x), pz = this.toZ(z);
    c.save();
    c.translate(px, pz);
    c.rotate(-yaw);
    c.fillStyle = '#1d2b3a';
    c.beginPath();
    c.moveTo(0, -7);
    c.lineTo(5, 6);
    c.lineTo(0, 3);
    c.lineTo(-5, 6);
    c.closePath();
    c.fill();
    c.restore();
  }
}
