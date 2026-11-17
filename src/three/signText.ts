/**
 * 门头文字自动排版：
 * - 先按单行最大字号绘制，超宽则逐档缩字
 * - 缩到下限仍超宽则折成两行，两行也超宽再继续缩
 * - 输出透明背景的 Canvas，供 THREE.CanvasTexture 使用
 */
export interface SignTextureResult {
  canvas: HTMLCanvasElement;
  /** 实际使用的字号占比，供调试/统计 */
  fontScale: number;
  lines: number;
}

const W = 256;
const H = 96;
const MAX_FONT = 58;
const MIN_FONT = 20;
const PAD = 10;

export function renderSignText(text: string): SignTextureResult {
  const canvas = document.createElement('canvas');
  canvas.width = W;
  canvas.height = H;
  const ctx = canvas.getContext('2d')!;
  ctx.clearRect(0, 0, W, H);

  const content = text.trim() || '展位';
  let fontSize = MAX_FONT;
  let lines: string[] = [content];

  const setFont = () => {
    ctx.font = `700 ${fontSize}px "Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", sans-serif`;
  };
  const lineWidth = (s: string) => ctx.measureText(s).width;

  // 第一阶段：单行缩字
  setFont();
  while (lineWidth(content) > W - PAD * 2 && fontSize > MIN_FONT) {
    fontSize -= 2;
    setFont();
  }

  // 第二阶段：到下限仍超宽 -> 折行
  if (lineWidth(content) > W - PAD * 2) {
    const wrapped = wrapToTwo(content, ctx);
    if (wrapped.length === 2) {
      lines = wrapped;
      while (
        lines.some((l) => lineWidth(l) > W - PAD * 2) &&
        fontSize > MIN_FONT
      ) {
        fontSize -= 2;
        setFont();
      }
    }
  }

  ctx.fillStyle = '#1d2b3a';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  const lineH = fontSize * 1.08;
  const totalH = lineH * lines.length;
  const y0 = H / 2 - totalH / 2 + lineH / 2;
  lines.forEach((l, i) => ctx.fillText(l, W / 2, y0 + i * lineH));

  return {
    canvas,
    fontScale: fontSize / MAX_FONT,
    lines: lines.length,
  };
}

/** 按显示宽度折成至多两行，优先在中间断点 */
function wrapToTwo(text: string, ctx: CanvasRenderingContext2D): string[] {
  if (text.length <= 1) return [text];
  const mid = Math.ceil(text.length / 2);
  const a = text.slice(0, mid);
  const b = text.slice(mid);
  // 若两半宽度差异过大，微调断点
  if (Math.abs(ctx.measureText(a).width - ctx.measureText(b).width) > 40 && mid > 1) {
    const alt = text.slice(0, mid - 1);
    const alt2 = text.slice(mid - 1);
    const diff1 = Math.abs(ctx.measureText(a).width - ctx.measureText(b).width);
    const diff2 = Math.abs(ctx.measureText(alt).width - ctx.measureText(alt2).width);
    return diff2 < diff1 ? [alt, alt2] : [a, b];
  }
  return [a, b];
}

let sharedCanvas: HTMLCanvasElement | null = null;
/** 预估文字在给定字号下的像素宽（用于编辑器侧预览，不建纹理） */
export function measureText(text: string, fontSize: number): number {
  if (!sharedCanvas) sharedCanvas = document.createElement('canvas');
  const ctx = sharedCanvas.getContext('2d')!;
  ctx.font = `700 ${fontSize}px "Microsoft YaHei", sans-serif`;
  return ctx.measureText(text).width;
}
