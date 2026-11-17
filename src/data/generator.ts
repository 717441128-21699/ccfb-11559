import type { Booth, BoothType } from '../types';
import { BOOTH_SPEC, HALL } from '../core/config';
import { Rng, randomCompanyName } from '../core/rng';

interface Reserved {
  x: number;
  z: number;
  w: number;
  d: number;
  island?: boolean;
}

/**
 * 批量规则生成。布局不变量（保证消防规则零违规）：
 * - 标摊 3x3 在“区 × 行块”网格内连续密铺，同行同列全部贴邻（gap=0 合法）
 * - 行块之间留 4m 净通道，每 24 块加宽到 5m 横通道
 * - 中央 5m 纵向主通道分开左右侧板
 * - 岛式特装是横跨侧板的横断条带，标摊行块整体让位，条带四周仍是通道
 */
export function generateHall(seed = 20261117): Booth[] {
  const rng = new Rng(seed);
  const booths: Booth[] = [];
  let id = 1;

  const mainAisle = 5;
  const lane = 4.0;
  const crossAisle = 5;
  const margin = 4.5;
  const s = 3;
  const blockDepth = 6;
  const blocksPerCross = 24;

  const halfW = HALL.width / 2;
  const colsPerZone = 15;
  const zoneWidth = colsPerZone * s;

  // 先按实际步进算出行块中心 z 序列（含每 24 块一次的 5m 横通道）
  const blockCenters: number[] = [];
  {
    let zCursor = margin;
    let blockIdx = 0;
    while (zCursor + blockDepth <= HALL.depth - margin + 0.01) {
      blockCenters.push(zCursor + s);
      blockIdx++;
      zCursor += blockDepth + (blockIdx % blocksPerCross === 0 ? crossAisle : lane);
    }
  }

  // 岛式条带占两个连续行块位（含中间 4m 通道），选第 4、第 5 块及其镜像位置
  const pickBand = (first: number): { z: number; d: number } => {
    const zTop = blockCenters[first] - s;                 // 第一块上边缘
    const zBottom = blockCenters[first + 1] + s;         // 第二块下边缘
    return { z: (zTop + zBottom) / 2, d: zBottom - zTop };
  };
  const band1 = pickBand(4);
  const band2Mirror = pickBand(blockCenters.length - 6);

  // 岛式横断条带：左右各一条，宽 = 侧板可用宽度
  const sideWidth = halfW - mainAisle / 2 - margin * 2;
  const islandBands: Reserved[] = [
    { x: margin + sideWidth / 2, z: band1.z, w: sideWidth, d: band1.d, island: true },
    { x: halfW + mainAisle / 2 + margin + sideWidth / 2, z: band2Mirror.z, w: sideWidth, d: band2Mirror.d, island: true },
  ];

  const intersects = (x: number, z: number, w: number, d: number, r: Reserved) =>
    Math.abs(x - r.x) < (w + r.w) / 2 && Math.abs(z - r.z) < (d + r.d) / 2;

  const zoneLetters = 'ABCDEFGHJKLMNPQRSTUWXY';
  let zoneIdx = 0;

  for (const side of [-1, 1]) {
    let xCursor = side === -1 ? margin : halfW + mainAisle / 2 + margin;
    const xLimit = side === -1 ? halfW - mainAisle / 2 - margin : HALL.width - margin;

    while (xCursor + zoneWidth <= xLimit + 0.01) {
      const letter = zoneLetters[zoneIdx % zoneLetters.length];
      let num = 1;
      let zCursor = margin;
      let blockIdx = 0;

      while (zCursor + blockDepth <= HALL.depth - margin + 0.01) {
        const groupCZ = zCursor + s;
        const inBand = islandBands.some((r) =>
          intersects(xCursor + zoneWidth / 2, groupCZ, zoneWidth, blockDepth, r),
        );

        if (!inBand) {
          for (let col = 0; col < colsPerZone; col++) {
            const cx = xCursor + col * s + s / 2;
            booths.push(
              makeBooth(id++, `${letter}${num++}`, 'standard', cx, groupCZ, rng),
            );
          }
        }

        blockIdx++;
        zCursor += blockDepth + (blockIdx % blocksPerCross === 0 ? crossAisle : lane);
      }
      zoneIdx++;
      xCursor += zoneWidth + lane;
    }
  }

  // 岛式条带内按 6m 栅格密铺两行，中间留 4m 通道
  let islandNum = 1;
  for (const band of islandBands) {
    const cols = Math.floor(band.w / 6);
    const startX = band.x - (cols * 6) / 2 + 3;
    const rowOffsets = [-5, 5]; // 两行中心相对条带中心的偏移（6m 岛位 + 4m 通道）
    for (let ix = 0; ix < cols; ix++) {
      for (const off of rowOffsets) {
        const cx = startX + ix * 6;
        const cz = band.z + off;
        booths.push(makeBooth(id++, `T${islandNum++}`, 'island', cx, cz, rng));
      }
    }
  }

  // 两个手画 L 形异形展位，贴在入口附近的侧板边缘，朝向通道
  const customs = [
    { x: margin + 3, z: HALL.depth - margin - 3, rot: 0 },
    { x: HALL.width - margin - 3, z: margin + 3, rot: Math.PI / 2 },
  ];
  for (const c of customs) {
    const poly = [
      { x: -3, z: -3 }, { x: 3, z: -3 }, { x: 3, z: 0 },
      { x: 0, z: 0 }, { x: 0, z: 3 }, { x: -3, z: 3 },
    ].map((p) => {
      const cos = Math.cos(c.rot), sin = Math.sin(c.rot);
      return { x: c.x + p.x * cos - p.z * sin, z: c.z + p.x * sin + p.z * cos };
    });
    booths.push({
      id: id++,
      code: `Z${id}`,
      exhibitor: randomCompanyName(rng),
      type: 'custom',
      x: c.x, z: c.z, w: 6, d: 6,
      rotation: c.rot,
      polygon: poly,
      color: BOOTH_SPEC.custom.color,
    });
  }

  return booths;
}

function makeBooth(
  id: number,
  code: string,
  type: BoothType,
  x: number,
  z: number,
  rng: Rng,
): Booth {
  const spec = BOOTH_SPEC[type];
  return {
    id,
    code,
    exhibitor: randomCompanyName(rng),
    type,
    x,
    z,
    w: spec.w,
    d: spec.d,
    rotation: 0,
    color: spec.color,
  };
}
