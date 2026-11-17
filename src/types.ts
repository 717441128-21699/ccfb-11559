/** 展位类型：按类型分别合并几何体并实例化 */
export type BoothType = 'standard' | 'peninsula' | 'island' | 'double' | 'custom';

export type Tool = 'select' | 'rect' | 'batch' | 'polygon' | 'erase';

export type AppMode = 'plan' | 'walk';

export interface AABB {
  minX: number;
  minZ: number;
  maxX: number;
  maxZ: number;
}

/** 单个展位。矩形用 w/d，异形用 polygon（世界坐标 XZ 多边形） */
export interface Booth {
  id: number;
  code: string;
  exhibitor: string;
  type: BoothType;
  x: number;
  z: number;
  w: number;
  d: number;
  rotation: number;
  polygon?: { x: number; z: number }[];
  color: number;
}

export interface HallConfig {
  width: number;
  depth: number;
  cell: number;
  eyeHeight: number;
  walkSpeed: number;
  runSpeed: number;
  fireLaneWidth: number;
}

export interface PlacementCheck {
  ok: boolean;
  reason?: string;
  /** 与最近障碍的实际净距（米） */
  clearance?: number;
}

export interface SearchHit {
  booth: Booth;
  score: number;
}

export interface FrameStats {
  fps: number;
  frameMs: number;
  drawCalls: number;
  triangles: number;
  booths: number;
  visible: number;
  occluders: number;
  occluded: number;
  pickMs: number;
}
