import * as THREE from 'three';
import { renderSignText } from './signText';

/**
 * 门头纹理图集：多个 2048x2048 画布，每格 256x96。
 * 每个展位的展商名渲染到某一格，实例化面片通过 per-instance uvOffset/uvScale 采样。
 * 5000 个展位约 2~3 张图集，显存占用可控。
 */
const ATLAS_SIZE = 2048;
const CELL_W = 256;
const CELL_H = 96;
const COLS = ATLAS_SIZE / CELL_W; // 8
const ROWS = ATLAS_SIZE / CELL_H; // 21
const PER_PAGE = COLS * ROWS; // 168

export interface SignSlot {
  texture: THREE.Texture;
  uvScale: THREE.Vector2;
  uvOffset: THREE.Vector2;
}

export class SignAtlas {
  private pages: { canvas: HTMLCanvasElement; ctx: CanvasRenderingContext2D; texture: THREE.Texture }[] = [];
  private cursor = 0;
  private cache = new Map<string, SignSlot>();

  private newPage() {
    const canvas = document.createElement('canvas');
    canvas.width = ATLAS_SIZE;
    canvas.height = ATLAS_SIZE;
    const ctx = canvas.getContext('2d')!;
    ctx.fillStyle = '#f4f1ea';
    ctx.fillRect(0, 0, ATLAS_SIZE, ATLAS_SIZE);
    const texture = new THREE.CanvasTexture(canvas);
    texture.colorSpace = THREE.SRGBColorSpace;
    texture.anisotropy = 4;
    texture.minFilter = THREE.LinearMipmapLinearFilter;
    texture.magFilter = THREE.LinearFilter;
    const page = { canvas, ctx, texture };
    this.pages.push(page);
    return page;
  }

  /** 同名展商复用格子，减少纹理填充与占用 */
  getOrCreate(name: string): SignSlot {
    const hit = this.cache.get(name);
    if (hit) return hit;

    if (this.cursor % PER_PAGE === 0) this.newPage();
    const page = this.pages[this.pages.length - 1];
    const indexInPage = this.cursor % PER_PAGE;
    const col = indexInPage % COLS;
    const row = Math.floor(indexInPage / COLS);
    const { canvas } = renderSignText(name);
    page.ctx.drawImage(canvas, col * CELL_W, row * CELL_H);
    page.texture.needsUpdate = true;

    const slot: SignSlot = {
      texture: page.texture,
      uvScale: new THREE.Vector2(CELL_W / ATLAS_SIZE, CELL_H / ATLAS_SIZE),
      uvOffset: new THREE.Vector2(
        (col * CELL_W) / ATLAS_SIZE,
        1 - ((row + 1) * CELL_H) / ATLAS_SIZE,
      ),
    };
    this.cache.set(name, slot);
    this.cursor++;
    return slot;
  }

  get pageCount(): number {
    return this.pages.length;
  }

  dispose(): void {
    for (const p of this.pages) p.texture.dispose();
    this.pages = [];
    this.cache.clear();
    this.cursor = 0;
  }
}
