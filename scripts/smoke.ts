/**
 * Node 冒烟测试：不依赖 DOM 的核心逻辑。
 * 运行：npx tsx scripts/smoke.ts （tsx 未装时用 vite-node 或编译后运行）
 */
import { generateHall } from '../src/data/generator';
import { BoothStore } from '../src/data/BoothStore';
import { PathFinder } from '../src/nav/PathFinder';
import { boothAabb } from '../src/core/geometry';
import { HALL } from '../src/core/config';
import type { Booth } from '../src/types';

function assert(cond: boolean, msg: string): void {
  if (!cond) {
    console.error(`✗ ${msg}`);
    process.exit(1);
  }
  console.log(`✓ ${msg}`);
}

const booths = generateHall();
assert(booths.length >= 4800 && booths.length <= 6200, `生成展位数量 ${booths.length} 落在 5000 量级`);

const store = new BoothStore();
store.addAll(booths);
assert(store.booths.length === booths.length, 'store 装载成功');
assert(store.bvh.size === booths.length, 'BVH 构建成功');

// 每个展位 AABB 必须在馆内
let outOfBounds = 0;
for (const b of store.booths) {
  const a = boothAabb(b);
  if (a.minX < -0.01 || a.minZ < -0.01 || a.maxX > HALL.width + 0.01 || a.maxZ > HALL.depth + 0.01) outOfBounds++;
}
assert(outOfBounds === 0, '全部展位在馆内');

// 生成数据自带的布局默认不应有消防违规（贴邻 gap=0 合法）
assert(store.violations.size === 0, `默认布局无消防违规（实际 ${store.violations.size}）`);

// 人为制造违规：把两个独立盒子放进中央主通道（无其他邻居）
const idA = store.allocId();
const idB = store.allocId();
const base: Booth = {
  id: idA, code: 'T-A', exhibitor: '测试甲', type: 'standard',
  x: HALL.width / 2 - 2, z: 120, w: 3, d: 3, rotation: 0, color: 0xffffff,
};
assert(store.canPlace(base).ok, '独立测试位可放置');
store.add(base);

// 北侧 2m 净距 -> 违规（中心距 = 半深 + 2 + 半深 = 5）
const moved: Booth = {
  ...base, id: idB, code: 'T-B',
  z: base.z + 5,
};
const check = store.canPlace(moved, idB);
assert(!check.ok && (check.reason ?? '').includes('消防'), '净距 2m 被消防规则拦截: ' + check.reason);

// 贴邻（gap=0）：中心距 = 两个半深之和 = 3
const adjacent: Booth = { ...moved, z: base.z + 3 };
const adjCheck = store.canPlace(adjacent, idB);
assert(adjCheck.ok, '贴邻展位 gap=0 合法: ' + (adjCheck.reason ?? 'ok'));

// 4m 净距：中心距 = 3 + 4 = 7
const fourMeter: Booth = { ...moved, z: base.z + 7 };
assert(store.canPlace(fourMeter, idB).ok, '净距 4m 合法');
store.remove(idA);

// 搜索
const name = store.booths[100].exhibitor;
const hits = store.search(name);
assert(hits.length > 0 && hits[0].booth.exhibitor === name, `展商名搜索命中「${name}」`);
const codeHits = store.search(store.booths[200].code);
assert(codeHits.length > 0, '展位号搜索命中');

// 寻路
const finder = new PathFinder(store);
const t0 = performance.now();
finder.rebuild();
const t1 = performance.now();
console.log(`  阻挡栅格构建耗时 ${(t1 - t0).toFixed(1)}ms`);

const a = finder.cellCenter(finder.nearestFree(finder.worldToCell(8, 8)));
const targetBooth = store.booths[Math.floor(store.booths.length / 2)];
const t2 = performance.now();
const route = finder.findPath(a.x, a.z, targetBooth.x, targetBooth.z + targetBooth.d / 2 + 2);
const t3 = performance.now();
console.log(`  A* 寻路耗时 ${(t3 - t2).toFixed(1)}ms，路径点 ${route.length}`);
assert(route.length >= 2, '寻路返回有效路径');

// 路径上的点都不能在阻挡格内
let blockedOnRoute = 0;
for (const p of route.slice(1, -1)) {
  if (finder.isBlockedCell(finder.worldToCell(p.x, p.z))) blockedOnRoute++;
}
assert(blockedOnRoute === 0, '路径不穿过展位');

console.log('\n全部冒烟测试通过。');
