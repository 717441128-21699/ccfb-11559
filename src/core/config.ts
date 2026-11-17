import type { HallConfig } from '../types';

export const HALL: HallConfig = {
  width: 680,
  depth: 340,
  cell: 0.5,
  eyeHeight: 1.7,
  walkSpeed: 7,
  runSpeed: 14,
  fireLaneWidth: 4,
};

/** 不同类型展位的默认尺寸（米）与门头顶高。标摊为真实的 3x3m */
export const BOOTH_SPEC: Record<
  string,
  { w: number; d: number; wallH: number; fasciaH: number; color: number }
> = {
  standard: { w: 3, d: 3, wallH: 2.5, fasciaH: 3.0, color: 0x9fc7e8 },
  peninsula: { w: 6, d: 3, wallH: 2.5, fasciaH: 3.2, color: 0xb9d8a2 },
  island: { w: 6, d: 6, wallH: 0, fasciaH: 4.0, color: 0xe8c79f },
  double: { w: 6, d: 3, wallH: 2.8, fasciaH: 3.4, color: 0xd8a7b9 },
  custom: { w: 6, d: 6, wallH: 2.6, fasciaH: 3.6, color: 0xc4b0e0 },
};

/** 编辑吸附网格（米） */
export const SNAP = 0.5;

/** 实例化缓冲区预留上限，超出时重建 */
export const MAX_BOOTHS = 8000;

/** 每帧用于遮挡查询的查询对象数量（时间切片，轮询覆盖全部展位） */
export const OCCLUSION_BUDGET = 4;

/** 距离相机多少米内的展位不做遮挡剔除，避免走近时闪现 */
export const OCCLUSION_NEAR_SKIP = 18;

/** 遮挡状态最长保留帧数，相机大幅移动后强制失效 */
export const OCCLUSION_TTL = 240;

/** A* 单帧路径长度上限（格数） */
export const PATH_MAX_NODES = 20000;

export const COLORS = {
  fireRed: 0xff3b30,
  validGreen: 0x34c759,
  hover: 0xffd60a,
  selected: 0xff9f0a,
  route: 0x0a84ff,
};
