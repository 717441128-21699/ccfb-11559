import * as THREE from 'three';
import { BOOTH_SPEC } from '../core/config';
import type { BoothType } from '../types';

export interface BoothTemplate {
  type: BoothType;
  /** 墙体/地台等主体：一套实例化几何 */
  body: THREE.BufferGeometry;
  /** 门头梁：单独一套，便于高亮换色 */
  fascia: THREE.BufferGeometry;
  /** 门头文字面在本地空间的位姿（相对展位中心） */
  signAnchor: { x: number; z: number; y: number; rotY: number; w: number }[];
}

function box(w: number, h: number, d: number, x: number, y: number, z: number) {
  const g = new THREE.BoxGeometry(w, h, d);
  g.translate(x, y, z);
  return g;
}

function merge(geos: THREE.BufferGeometry[]): THREE.BufferGeometry {
  // 避免引入 BufferGeometryUtils 依赖，手写合并（属性集一致：position/normal/uv）
  let vCount = 0;
  let idxCount = 0;
  for (const g of geos) {
    vCount += g.attributes.position.count;
    idxCount += g.index ? g.index.count : g.attributes.position.count;
  }
  const pos = new Float32Array(vCount * 3);
  const nor = new Float32Array(vCount * 3);
  const uv = new Float32Array(vCount * 2);
  const idx = new Uint32Array(idxCount);
  let vo = 0, io = 0, base = 0;
  for (const g of geos) {
    pos.set(g.attributes.position.array as Float32Array, vo * 3);
    nor.set(g.attributes.normal.array as Float32Array, vo * 3);
    uv.set(g.attributes.uv.array as Float32Array, vo * 2);
    if (g.index) {
      const src = g.index.array;
      for (let i = 0; i < src.length; i++) idx[io++] = src[i] + base;
    } else {
      for (let i = 0; i < g.attributes.position.count; i++) idx[io++] = base + i;
    }
    base += g.attributes.position.count;
    vo += g.attributes.position.count;
  }
  const out = new THREE.BufferGeometry();
  out.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  out.setAttribute('normal', new THREE.BufferAttribute(nor, 3));
  out.setAttribute('uv', new THREE.BufferAttribute(uv, 2));
  out.setIndex(new THREE.BufferAttribute(idx, 1));
  return out;
}

const T = 0.12; // 墙板厚度

/** 按类型构建共享几何模板，所有展位复用同一套顶点数据 */
export function buildTemplates(): Record<BoothType, BoothTemplate> {
  const std = BOOTH_SPEC.standard;
  const isl = BOOTH_SPEC.island;

  // ---- 标准标摊 3x3：地台 + 三面 2.5m 墙板 + 前后门头梁 ----
  const stdBody = merge([
    box(std.w, 0.08, std.d, 0, 0.04, 0),
    box(T, std.wallH, std.d, -std.w / 2 + T / 2, std.wallH / 2, 0),
    box(std.w, std.wallH, T, 0, std.wallH / 2, -std.d / 2 + T / 2),
    box(T, std.wallH, std.d, std.w / 2 - T / 2, std.wallH / 2, 0),
  ]);
  const stdFascia = merge([
    box(std.w, 0.45, T, 0, std.fasciaH - 0.225, std.d / 2 - T / 2),
    box(std.w, 0.45, T, 0, std.fasciaH - 0.225, -std.d / 2 + T / 2),
  ]);

  // ---- 半岛 3x6：三面墙，单门头 ----
  const pen = BOOTH_SPEC.peninsula;
  const penBody = merge([
    box(pen.w, 0.08, pen.d, 0, 0.04, 0),
    box(T, pen.wallH, pen.d, -pen.w / 2 + T / 2, pen.wallH / 2, 0),
    box(pen.w, pen.wallH, T, 0, pen.wallH / 2, -pen.d / 2 + T / 2),
    box(T, pen.wallH, pen.d, pen.w / 2 - T / 2, pen.wallH / 2, 0),
  ]);
  const penFascia = merge([
    box(pen.w, 0.45, T, 0, pen.fasciaH - 0.225, pen.d / 2 - T / 2),
  ]);

  // ---- 岛式 6x6：无墙，四面门头围成框 ----
  const islBody = merge([box(isl.w, 0.1, isl.d, 0, 0.05, 0)]);
  const islFascia = merge([
    box(isl.w, 0.5, T, 0, isl.fasciaH - 0.25, isl.d / 2 - T / 2),
    box(isl.w, 0.5, T, 0, isl.fasciaH - 0.25, -isl.d / 2 + T / 2),
    box(T, 0.5, isl.d, isl.w / 2 - T / 2, isl.fasciaH - 0.25, 0),
    box(T, 0.5, isl.d, -isl.w / 2 + T / 2, isl.fasciaH - 0.25, 0),
  ]);

  // ---- 双面 6x3：背靠背，两侧门头 ----
  const dbl = BOOTH_SPEC.double;
  const dblBody = merge([
    box(dbl.w, 0.08, dbl.d, 0, 0.04, 0),
    box(dbl.w, dbl.wallH, T, 0, dbl.wallH / 2, 0),
  ]);
  const dblFascia = merge([
    box(dbl.w, 0.45, T, 0, dbl.fasciaH - 0.225, dbl.d / 2 - T / 2),
    box(dbl.w, 0.45, T, 0, dbl.fasciaH - 0.225, -dbl.d / 2 + T / 2),
  ]);

  // ---- 异形：占位盒，实际在 CustomMeshBuilder 里按多边形拉伸 ----
  const cus = BOOTH_SPEC.custom;
  const cusBody = merge([box(cus.w, 0.08, cus.d, 0, 0.04, 0)]);
  const cusFascia = merge([
    box(cus.w, 0.45, T, 0, cus.fasciaH - 0.225, cus.d / 2 - T / 2),
  ]);

  return {
    standard: {
      type: 'standard', body: stdBody, fascia: stdFascia,
      signAnchor: [
        { x: 0, z: std.d / 2 + 0.01, y: std.fasciaH, rotY: 0, w: std.w * 0.92 },
        { x: 0, z: -std.d / 2 - 0.01, y: std.fasciaH, rotY: Math.PI, w: std.w * 0.92 },
      ],
    },
    peninsula: {
      type: 'peninsula', body: penBody, fascia: penFascia,
      signAnchor: [
        { x: 0, z: pen.d / 2 + 0.01, y: pen.fasciaH, rotY: 0, w: pen.w * 0.92 },
      ],
    },
    island: {
      type: 'island', body: islBody, fascia: islFascia,
      signAnchor: [
        { x: 0, z: isl.d / 2 + 0.01, y: isl.fasciaH, rotY: 0, w: isl.w * 0.92 },
        { x: 0, z: -isl.d / 2 - 0.01, y: isl.fasciaH, rotY: Math.PI, w: isl.w * 0.92 },
      ],
    },
    double: {
      type: 'double', body: dblBody, fascia: dblFascia,
      signAnchor: [
        { x: 0, z: dbl.d / 2 + 0.01, y: dbl.fasciaH, rotY: 0, w: dbl.w * 0.92 },
        { x: 0, z: -dbl.d / 2 - 0.01, y: dbl.fasciaH, rotY: Math.PI, w: dbl.w * 0.92 },
      ],
    },
    custom: {
      type: 'custom', body: cusBody, fascia: cusFascia,
      signAnchor: [
        { x: 0, z: cus.d / 2 + 0.01, y: cus.fasciaH, rotY: 0, w: cus.w * 0.9 },
      ],
    },
  };
}
