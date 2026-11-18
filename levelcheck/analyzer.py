"""落脚点可达性分析器。

思路概述
========
1. **落脚点建模**
   - 静态落脚点:实心瓦片 / 弹簧顶面的连续可站立区间,按 0.25 格分桶,
     起跳点只取桶中心,离散化误差远小于半格红线。
   - 移动落脚点:平台 id × 相位帧,相位按平台周期枚举,相位之间用
     "原地等一帧"的边相连(头上方空间不足的相位不可等待)。
2. **弧线枚举**:每个落脚点枚举一组跳跃策略(满跳/短跳/土狼跳/
   二段跳/弹簧弹射 × 左右 × 跑速),每一条弧线直接调用
   :mod:`levelcheck.simulate` 的 :func:`step` 跑帧,与游戏实测同一份物理。
3. **静态弧线缓存 + 平台几何拦截**:同一静态表面同桶、同动作的弧线只
   模拟一次(基准帧 0);对移动平台不做相位暴力枚举,而是对弧线逐帧做
   几何拦截,一次性求出"哪些相位会在第几帧接住角色"——这是百屏
   10 秒预算的关键。
4. **BFS 求最早可达帧**(边权均为正、FIFO 即时间序),记录父节点链,
   最终输出每个收集品 / 终点的可达性与一条可复现的操作路径。
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

from .level import Level, MovingPlatform, Rect
from .physics import (
    PLAYER_HALF_WIDTH,
    PLAYER_HEIGHT,
    lcm_int,
)
from .simulate import JumpInput, Landing, PlayerState, _circle_hits_rect, step

#: 所有移动平台联合周期上限(帧 = 60 秒)。超过说明平台节奏设计不可读,
#: 要求策划改周期,而不是让分析器组合爆炸。
MAX_LCM_FRAMES = 3600
#: 单条弧线最多模拟帧数(3 秒);正常满跳 41 帧,留足弹簧链余量
MAX_ARC_FRAMES = 180
#: 终点判定:角色身体与目标点的最大距离(格)
GOAL_TOUCH_RADIUS = 1.0
#: 同一节点上保留的真实落地坐标上限(防止长表面无限增长)
MAX_LAND_X_PER_NODE = 8
#: 等待边成立所需的头顶净空(格):角色身高 + 余量
HEADROOM = PLAYER_HEIGHT + 0.25


# ---------------------------------------------------------------------------
# 跳跃策略:离散的动作集合。覆盖正常通关所需的全部输入形态,
# 极限 TAS 操作(逐帧变向等)不在承诺范围内,README 有说明。
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class JumpAction:
    name: str
    requires_spring: bool = False
    cut_frame: int | None = None       # 短跳:第几帧松开跳跃键
    double_frame: int | None = None    # 二段跳:第几帧按下
    air_jumps_used: int = 0


JUMP_ACTIONS: tuple[JumpAction, ...] = (
    JumpAction("满跳"),
    JumpAction("短跳", cut_frame=6),
    JumpAction("小跳", cut_frame=3),
    JumpAction("二段跳-早", double_frame=4, air_jumps_used=1),
    JumpAction("二段跳-中", double_frame=8, air_jumps_used=1),
    JumpAction("二段跳-晚", double_frame=12, air_jumps_used=1),
    JumpAction("弹簧弹射", requires_spring=True),
    JumpAction("弹簧+二段跳", requires_spring=True, double_frame=10, air_jumps_used=1),
    JumpAction("弹簧短弹", requires_spring=True, cut_frame=6),
)
#: 移动平台起跳只保留的主动作(满跳 + 三档二段跳),用于控制相位展开规模
PLATFORM_ACTIONS: tuple[JumpAction, ...] = tuple(
    a for a in JUMP_ACTIONS
    if a.name in ("满跳", "二段跳-早", "二段跳-中", "二段跳-晚"))
DIRECTIONS = (-1, 1)


# ---------------------------------------------------------------------------
# 表面与落脚点
# ---------------------------------------------------------------------------

@dataclass
class Surface:
    """一段连续可站立的静态表面(瓦片顶面或弹簧顶面)。"""

    surf_id: str
    x0: float
    x1: float
    top_y: float
    kind: str                  # "tile" | "spring"
    spring_id: Optional[str] = None

    def slot_count(self) -> int:
        """规范起跳位数量:在表面上等距分布,含两端。

        上限 6 个:更长的表面上,内部起跳位的弧线与邻近位高度相似,
        真正不同的跨台转移由两端起跳位决定;端点始终精确保留。
        """
        length = self.x1 - self.x0
        n = max(2, int(round(length / SLOT_SPACING)) + 1)
        return min(n, 4)

    def slots(self) -> list[tuple[int, float]]:
        """返回 (槽位号, 世界 x)。槽位在表面内等距分布,含两端。"""
        n = self.slot_count()
        out = []
        for i in range(n):
            t = i / (n - 1)
            out.append((i, self.x0 + t * (self.x1 - self.x0)))
        return out


#: 规范起跳位的目标间距(格)。起跳点误差 ≤ 间距/2 = 0.75 格,
#: 配合真实落地坐标(land_xs)判定目标,半格红线由"同一物理积分器"
#: 在落点计算上保证;起跳位仅决定从哪里发起,不影响落点积分精度。
SLOT_SPACING = 1.5


def extract_static_surfaces(level: Level) -> list[Surface]:
    """从实心瓦片提取顶面区间:瓦片上方不是实心瓦片即暴露为可站立面。

    先收集所有暴露顶边(单位区间),再按高度合并相邻/重叠区间。
    头顶净空是逐桶判定的(墙根处的桶会被自然排除),弹簧顶面单独追加。
    """
    tops: dict[float, list[tuple[float, float]]] = {}
    for (tx, ty) in level.solid_tiles:
        if (tx, ty - 1) in level.solid_tiles:
            continue
        tops.setdefault(float(ty), []).append((float(tx), float(tx + 1)))

    surfaces: list[Surface] = []
    sid = 0
    for y in sorted(tops):
        intervals = sorted(tops[y])
        merged: list[list[float]] = []
        for a, b in intervals:
            if merged and a <= merged[-1][1] + 1e-9:
                merged[-1][1] = max(merged[-1][1], b)
            else:
                merged.append([a, b])
        for a, b in merged:
            surfaces.append(Surface(f"s{sid}", a, b, y, "tile"))
            sid += 1

    for i, sp in enumerate(level.springs):
        r = sp.rect
        surfaces.append(Surface(f"sp{i}", r.left, r.right, r.top, "spring",
                                spring_id=f"spring#{i}"))
    return surfaces


def compute_slot_runup(level: Level,
                       surfaces: list[Surface]) -> dict[tuple[str, int], float]:
    """每个规范起跳位能达到的最大水平速度(格/秒)。

    起跳位距表面两端各有一段助跑距离,取较长一侧按 v=sqrt(2·a·d)
    估算可达速度并截断到满跑速。返回 {(表面id, 槽位号): 速度}。
    """
    cfg = level.physics
    speed: dict[tuple[str, int], float] = {}
    for s in surfaces:
        for slot, x in s.slots():
            run_left = x - s.x0
            run_right = s.x1 - x
            d = max(run_left, run_right)
            v = (2.0 * cfg.ground_accel * d) ** 0.5
            speed[(s.surf_id, slot)] = min(v, cfg.run_speed)
    return speed


# ---------------------------------------------------------------------------
# BFS 节点与弧线结果
# ---------------------------------------------------------------------------

@dataclass
class FootNode:
    key: str
    kind: str                       # "static" | "platform"
    surface_id: str
    bucket: int
    x: float
    y: float
    phase: int                      # 移动平台相位帧;静态为 0
    platform_id: Optional[str]
    waitable: bool
    frame: int = 0                  # BFS 最早到达帧(绝对时间)
    vx_cache: float = 0.0           # 到达该点时的水平速度(移动节点起跳用)
    land_xs: list[float] = field(default_factory=list)  # 真实落地 x(去重用槽位,判定用真实坐标)
    parent: Optional["FootNode"] = None
    parent_action: Optional[str] = None
    parent_direction: int = 0


@dataclass
class ArcFrame:
    """弧线中一帧的快照(几何拦截与收集品判定用)。"""

    frame: int
    x: float
    y: float
    prev_bottom: float


@dataclass
class ArcResult:
    frames: list[ArcFrame]
    landings: list[Landing]
    touched: list[tuple[str, int]]     # (收集品 id, 弧线局部帧)
    final_vx: float
    end_frame: int
    dead: bool
    death: Optional[str]

    @property
    def last_landing(self) -> Optional[Landing]:
        return self.landings[-1] if self.landings else None


@dataclass
class ReachRecord:
    reachable: bool
    node: Optional[FootNode] = None
    frame: Optional[int] = None
    nearest_distance: Optional[float] = None
    via_arc: bool = False


@dataclass
class PlatformTiming:
    platform_id: str
    phase: int
    frame: int
    period: int
    catch_note: str


@dataclass
class AnalysisResult:
    level_name: str
    ok: bool
    elapsed_seconds: float
    total_frames_cycle: int
    nodes_visited: int
    arcs_simulated: int
    goal: ReachRecord
    collectibles: dict[str, ReachRecord]
    platform_timing: dict[str, list[PlatformTiming]]
    route: list[str]
    errors: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class AnalyzerTimeout(RuntimeError):
    def __init__(self, arcs: int):
        super().__init__(f"分析超过 10 秒预算(已模拟 {arcs} 条弧线)")
        self.arcs = arcs


class LevelCycleError(RuntimeError):
    def __init__(self, cycle: int):
        super().__init__(
            f"移动平台联合周期 {cycle} 帧超过上限 {MAX_LCM_FRAMES} 帧,"
            "请调整平台 period_frames 使最小公倍数不超过 60 秒")
        self.cycle = cycle


#: 移动平台起跳相位采样步长(帧)。只在这些相位枚举跳跃弧线,
#: 等待边仍逐帧连接所有相位,因此角色在任意相位都能站立、搭乘;
#: 起跳节拍的最大偏差为 (步长-1) 帧 = 0.05s,远小于半格精度对应的时间。
PLATFORM_JUMP_PHASE_STEP = 3


# ---------------------------------------------------------------------------
# 分析器主体
# ---------------------------------------------------------------------------

class Analyzer:
    def __init__(self, level: Level, deadline_seconds: float = 10.0):
        self.level = level
        self.cfg = level.physics
        self.deadline = deadline_seconds
        self.start_clock = 0.0
        self.surfaces = extract_static_surfaces(level)
        self.runup = compute_slot_runup(level, self.surfaces)
        # (表面id, 槽位号) -> 世界 x
        self.slot_x: dict[tuple[str, int], float] = {
            (s.surf_id, slot): x for s in self.surfaces for slot, x in s.slots()}
        self.platforms = level.platforms
        self.periods = {p.id: p.period_frames for p in self.platforms}
        self.cycle = (lcm_int(list(self.periods.values()))
                      if self.periods else 1)
        if self.cycle > MAX_LCM_FRAMES:
            raise LevelCycleError(self.cycle)
        # 静态弧线缓存:(表面 id, 槽位号, 动作名, 方向) -> 弧线结果(基准帧 0)。
        # 槽位是表面内相对位置,同形状表面的同槽位弧线行为一致。
        self.static_cache: dict[tuple, ArcResult] = {}
        # 移动弧线缓存:(平台 id, 相对相位, 桶, 动作名, 方向) -> 弧线结果。
        # 周期运动的位姿只取决于相对相位,同相位的绝对帧物理完全相同,
        # 这是把移动平台分析从 O(相位²) 压回 O(相位) 的关键。
        self.moving_cache: dict[tuple, ArcResult] = {}
        self.queue: deque[FootNode] = deque()
        self.nodes: dict[str, FootNode] = {}
        self.closed: set[str] = set()
        self.arcs_simulated = 0
        self._guard_counter = 0
        self.collectible_first_frame: dict[str, int] = {}
        self.platform_timing: dict[tuple[str, int], PlatformTiming] = {}

    # ---- 工具 ----
    def _tick_guard(self) -> None:
        # 每 256 个节点才读一次时钟,避免 perf_counter 成为热路径固定开销
        self._guard_counter += 1
        if (self._guard_counter & 0xFF) == 0 and \
                time.perf_counter() - self.start_clock > self.deadline:
            raise AnalyzerTimeout(self.arcs_simulated)

    def _headroom_clear_at(self, x: float, top_y: float) -> bool:
        body = Rect(x - PLAYER_HALF_WIDTH, top_y - HEADROOM,
                    PLAYER_HALF_WIDTH * 2, HEADROOM - 0.01)
        return not self.level.solid_aabb(body)

    def _platform_phase_waitable(self, plat: MovingPlatform, phase: int) -> bool:
        pose = plat.pose(phase)
        return self._headroom_clear_at(pose.cx, pose.top)

    def _surface_at(self, x: float, top_y: float, kind: str) -> Optional[Surface]:
        """找覆盖位置 x、顶面高度为 top_y 的静态表面。"""
        for s in self.surfaces:
            if s.kind != kind:
                continue
            if abs(s.top_y - top_y) <= 1e-4 and s.x0 - 1e-6 <= x <= s.x1 + 1e-6:
                return s
        return None

    def _nearest_slot(self, surf: Surface, x: float) -> tuple[int, float]:
        """把任意落地 x 归到表面最近的规范起跳位,返回 (槽位号, 世界x)。"""
        slots = surf.slots()
        slot, sx = min(slots, key=lambda t: abs(t[1] - x))
        return slot, sx

    @staticmethod
    def _platform_canonical_buckets(plat: MovingPlatform) -> list[int]:
        """平台上的规范站位槽(平台本地坐标,与平台运动解耦)。

        角色站立时随平台整体平移,绝对 x 不产生新的行为状态,因此平台
        落脚点只保留左/中/右三个规范位。槽号加高位偏移避免与静态槽冲突。
        """
        base = 1_000_000
        left = plat.rect.x + plat.rect.w * 0.25
        center = plat.rect.cx
        right = plat.rect.x + plat.rect.w * 0.75
        return [base + i for i, _ in enumerate((left, center, right))]

    def _nearest_platform_bucket(self, plat: MovingPlatform,
                                 world_x: float) -> tuple[int, float]:
        """平台落脚点统一归到中心规范站位。

        角色站立时随平台整体平移,左/右站位与中心位的起跳弧线行为等价,
        只保留中心位可把平台节点数压到 1/3 而不损失可达性;真实落地坐标
        仍通过 land_x 保留,供终点/收集品判定。
        """
        local = plat.rect.cx
        base = 1_000_000
        return base + 1, local

    # ---- 节点登记(BFS 去重 + 最早到达帧)----
    def _register(self, kind: str, surface_id: str, bucket: int, x: float, y: float,
                  phase: int, platform_id: Optional[str], waitable: bool,
                  frame: int, parent: Optional[FootNode],
                  action: Optional[str], direction: int,
                  vx_cache: float = 0.0,
                  land_x: Optional[float] = None) -> FootNode | None:
        key = f"{kind}:{surface_id}:{bucket}:{phase}"
        old = self.nodes.get(key)
        if old is not None:
            if frame < old.frame:
                old.frame = frame
                old.parent = parent
                old.parent_action = action
                old.parent_direction = direction
                old.vx_cache = vx_cache
            if land_x is not None and land_x not in old.land_xs \
                    and len(old.land_xs) < MAX_LAND_X_PER_NODE:
                old.land_xs.append(land_x)
            return None
        node = FootNode(key, kind, surface_id, bucket, x, y, phase,
                        platform_id, waitable, frame, vx_cache,
                        [land_x] if land_x is not None else [],
                        parent, action, direction)
        self.nodes[key] = node
        self.queue.append(node)
        return node

    def _spawn_node(self) -> FootNode:
        sx, sy = self.level.spawn
        surf = self._surface_at(sx, sy, "tile")
        if surf is None:
            surf = self._surface_at(sx, sy, "spring")
        if surf is not None:
            slot, slot_x = self._nearest_slot(surf, sx)
            node = self._register(
                "static", surf.surf_id, slot, slot_x, surf.top_y, 0,
                None, surf.kind == "tile", 0, None, None, 0)
        else:
            # 出生点悬空(出生门):作为特殊静态节点,允许空中起跳
            node = self._register(
                "static", "spawn", 0, sx, sy, 0, None, False,
                0, None, None, 0)
        assert node is not None
        return node

    # ---- 一条弧线的模拟 ----
    def _simulate_arc(self, node: FootNode, action: JumpAction,
                      direction: int, start_frame: int) -> ArcResult:
        cfg = self.cfg
        if node.kind == "static":
            if node.surface_id == "spawn":
                start_vx = 0.0
            else:
                start_vx = direction * self.runup.get(
                    (node.surface_id, node.bucket), 0.0)
        else:
            # 移动平台:继承落地时水平速度
            start_vx = node.vx_cache
        st = PlayerState(
            x=node.x, y=node.y, vx=start_vx, vy=0.0,
            grounded=True, coyote=cfg.coyote_frames,
            air_jumps_left=cfg.max_air_jumps,
            riding=node.platform_id, frame=start_frame,
        )
        frames: list[ArcFrame] = []
        touched: list[tuple[str, int]] = []
        landings: list[Landing] = []
        death: Optional[str] = None

        for f in range(1, MAX_ARC_FRAMES + 1):
            prev_bottom = st.y
            jump_pressed = False
            jump_held = True
            if f == 1 and not action.requires_spring:
                jump_pressed = True          # 地面跳 / 土狼跳
            if action.double_frame is not None and f == action.double_frame:
                jump_pressed = True          # 二段跳
            if action.cut_frame is not None and f > action.cut_frame:
                jump_held = False            # 短跳截断
            inp = JumpInput(move=direction, jump_pressed=jump_pressed,
                            jump_held=jump_held)
            ev = step(self.level, st, inp)
            frames.append(ArcFrame(st.frame, st.x, st.y, prev_bottom))
            for cid in ev.touched_collectibles:
                touched.append((cid, f))
            if ev.deaths:
                death = ev.deaths[0]
                break
            if ev.landed:
                landings.extend(ev.landed)
                if ev.landed[-1].kind != "spring":
                    break  # 弹簧由模拟器自动弹射,弧线继续
        self.arcs_simulated += 1
        return ArcResult(frames, landings, touched, st.vx, st.frame,
                         st.dead, death)

    # ---- 静态节点展开 ----
    def _expand_static(self, node: FootNode) -> None:
        # 走路边:同一表面内相邻规范槽位可达(BFS 由此覆盖整条表面)
        if node.surface_id != "spawn":
            surf = next((s for s in self.surfaces
                         if s.surf_id == node.surface_id), None)
            if surf is not None:
                slot_ids = [slot for slot, _ in surf.slots()]
                if node.bucket in slot_ids:
                    idx = slot_ids.index(node.bucket)
                    for nidx in (idx - 1, idx + 1):
                        if not (0 <= nidx < len(slot_ids)):
                            continue
                        ns = slot_ids[nidx]
                        nx = self.slot_x[(surf.surf_id, ns)]
                        if not self._headroom_clear_at(nx, surf.top_y):
                            continue
                        self._register(
                            "static", surf.surf_id, ns, nx, surf.top_y, 0,
                            None, surf.kind == "tile", node.frame + 1,
                            node, "走", 1 if nidx > idx else -1)

        surf = next((s for s in self.surfaces if s.surf_id == node.surface_id), None)
        is_spring_surf = surf is not None and surf.kind == "spring"
        # 分级枚举控制百屏规模:满跳与三档二段跳决定能否跨到下一个落脚点,
        # 在所有槽位保留;短跳/小跳只是降高度手段,只在表面两端与中心槽枚举。
        if surf is not None:
            slot_ids = [slot for slot, _ in surf.slots()]
            edge_slots = {slot_ids[0], slot_ids[len(slot_ids) // 2],
                          slot_ids[-1]}
            full_actions = node.bucket in edge_slots
        else:
            full_actions = True
        for action in JUMP_ACTIONS:
            if action.requires_spring != is_spring_surf:
                continue
            if not full_actions and action.cut_frame is not None:
                continue  # 中间槽跳过短跳/小跳,保留满跳与全部二段跳
            for direction in DIRECTIONS:
                result, _, _ = self._get_static_arc(node, action, direction)
                if result.dead:
                    continue
                self._collect_touches(result, base_frame=node.frame)
                self._consume_landings(node, result, action, direction,
                                       base_frame=node.frame)
                self._intercept_platforms(node, result, action, direction,
                                          base_frame=node.frame)

    # ---- 静态弧线缓存 ----
    def _get_static_arc(self, node: FootNode, action: JumpAction,
                        direction: int) -> tuple[ArcResult, float, float]:
        """返回 (弧线, 起跳x, 起跳y)。

        缓存键严格到(表面, 槽位, 动作, 方向):不同槽位起跳 x 不同,落地
        节点也不同,跨槽位复用会让 BFS 错指落地表面而断链(已验证),
        因此只做完全相同起跳条件的去重。
        """
        key = (node.surface_id, node.bucket, action.name, direction)
        cached = self.static_cache.get(key)
        if cached is None:
            cached = self._simulate_arc(node, action, direction, 0)
            self.static_cache[key] = cached
        return cached, node.x, node.y

    # ---- 移动节点展开:按相对相位缓存,绝对帧只做时间偏移 ----
    def _expand_platform(self, node: FootNode) -> None:
        assert node.platform_id is not None
        plat = self.level.platform_by_id(node.platform_id)
        assert plat is not None
        # 跳跃弧线只从平台中心规范位发起:站立者随平台整体平移,
        # 左右站位的起跳弧线与中心位等价,这里剪枝可把平台弧线数降到 1/3。
        center_bucket = self._platform_canonical_buckets(plat)[1]
        # 起跳弧线只在采样相位枚举;非采样相位通过等待边到达采样相位后再跳
        if node.bucket == center_bucket and \
                node.phase % PLATFORM_JUMP_PHASE_STEP == 0:
            # 平台起跳只枚举主动作:满跳 + 三种二段跳时机。
            # 短跳/小跳是降高度手段,在移动平台节拍分析里不增加可达落脚点,
            # 真正需要精细高度的场景由静态表面弧线覆盖。
            for action in PLATFORM_ACTIONS:
                for direction in DIRECTIONS:
                    cache_key = (node.platform_id, node.phase, node.bucket,
                                 action.name, direction)
                    result = self.moving_cache.get(cache_key)
                    if result is None:
                        # 在相对相位(基准绝对帧 = 相位帧)模拟一次
                        result = self._simulate_arc(node, action, direction,
                                                    node.phase)
                        self.moving_cache[cache_key] = result
                    if result.dead:
                        continue
                    # 把局部帧平移回当前节点的绝对时间
                    offset = node.frame - node.phase
                    shifted = self._shift_arc(result, offset)
                    self._collect_touches(shifted, base_frame=node.frame)
                    self._consume_landings(node, shifted, action, direction,
                                           base_frame=node.frame)
        # 等待边:同平台相邻相位(头上方净空才允许等)
        if node.waitable and node.platform_id is not None:
            plat = self.level.platform_by_id(node.platform_id)
            assert plat is not None
            next_phase = (node.phase + 1) % plat.period_frames
            if self._platform_phase_waitable(plat, next_phase):
                pose = plat.pose(node.frame + 1)
                self._register(
                    "platform", plat.id, node.bucket, node.x, pose.top,
                    next_phase, plat.id, True, node.frame + 1,
                    node, f"等待1帧(相位{next_phase})", 0,
                    vx_cache=node.vx_cache)

    def _record_timing(self, plat_id: str, phase: int, frame: int,
                       period: int, note: str) -> None:
        """记录搭乘时机,(平台, 相位) 只保留最早的一次,避免报告刷屏。"""
        key = (plat_id, phase)
        existing = self.platform_timing.get(key)
        if existing is None or frame < existing.frame:
            self.platform_timing[key] = PlatformTiming(
                plat_id, phase, frame, period,
                f"在第 {frame} 帧(相位 {phase}/{period}){note}")

    def _collect_touches(self, result: ArcResult, base_frame: int) -> None:
        for cid, local_frame in result.touched:
            global_frame = base_frame + local_frame
            if cid not in self.collectible_first_frame or \
                    global_frame < self.collectible_first_frame[cid]:
                self.collectible_first_frame[cid] = global_frame

    @staticmethod
    def _shift_arc(result: ArcResult, offset: int) -> ArcResult:
        """把基准相位上模拟的弧线整体平移 offset 帧(周期运动位姿只看相对相位)。"""
        if offset == 0:
            return result
        frames = [ArcFrame(f.frame + offset, f.x, f.y, f.prev_bottom)
                  for f in result.frames]
        landings = [Landing(l.kind, l.surface_id, l.x, l.y, l.frame + offset)
                    for l in result.landings]
        touched = [(cid, f + offset) for cid, f in result.touched]
        return ArcResult(frames, landings, touched, result.final_vx,
                         result.end_frame + offset, result.dead, result.death)

    # ---- 消化弧线终点落地 ----
    def _consume_landings(self, src: FootNode, result: ArcResult,
                          action: JumpAction, direction: int,
                          base_frame: int) -> None:
        land = result.last_landing
        if land is None:
            return
        # 静态弧线在基准帧 0 模拟,落地 frame 是局部帧 → 加源节点偏移;
        # 移动弧线以源节点帧起步模拟,记录值本身就是绝对帧。
        local_frames = len(result.frames)
        if src.kind == "static":
            frame = src.frame + local_frames
        else:
            frame = result.end_frame
        if land.kind in ("tile", "spring"):
            surf = self._surface_at(land.x, land.y, land.kind)
            if surf is None:
                return
            # 归到该表面最近的规范起跳位
            slot, slot_x = self._nearest_slot(surf, land.x)
            self._register(
                "static", surf.surf_id, slot, slot_x,
                surf.top_y, 0, None, surf.kind == "tile",
                frame, src, action.name, direction, land_x=land.x)
        elif land.kind == "platform":
            plat = self.level.platform_by_id(land.surface_id)
            if plat is None:
                return
            phase = frame % plat.period_frames
            pose = plat.pose(frame)
            waitable = self._platform_phase_waitable(plat, phase)
            bucket, local_x = self._nearest_platform_bucket(plat, land.x)
            node_x = pose.x + (local_x - plat.rect.x)
            self._register(
                "platform", plat.id, bucket, node_x, pose.top, phase,
                plat.id, waitable, frame, src, action.name, direction,
                vx_cache=result.final_vx, land_x=land.x)
            self._record_timing(
                plat.id, phase, frame, plat.period_frames,
                f"以 {action.name}{'向左' if direction < 0 else '向右'}跳上")

    # ---- 移动平台几何拦截:对静态弧线逐帧求所有可搭乘相位 ----
    def _intercept_platforms(self, src: FootNode, result: ArcResult,
                             action: JumpAction, direction: int,
                             base_frame: int) -> None:
        if not self.platforms:
            return
        hw = PLAYER_HALF_WIDTH
        for af in result.frames:
            global_frame = src.frame + af.frame
            bl, br = af.x - hw, af.x + hw
            bt, bb = af.y - PLAYER_HEIGHT, af.y
            body = Rect(bl, bt, br - bl, bb - bt)
            # 空间索引:只检查本帧身体附近的平台,而不是全关卡平台列表
            for plat in self.level.platforms_near(body):
                period = plat.period_frames
                # 周期运动在该绝对帧只有一个位姿,直接求相位而不是枚举整周期
                phase = global_frame % period
                pose = plat.pose(global_frame)
                # 只承认"从上方落到顶面"的搭乘,排除撞墙 / 顶头
                if not (br > pose.left and bl < pose.right
                        and af.prev_bottom <= pose.top + 1e-4
                        and bb >= pose.top and bt < pose.bottom):
                    continue
                waitable = self._platform_phase_waitable(plat, phase)
                bucket, local_x = self._nearest_platform_bucket(plat, af.x)
                node_x = pose.x + (local_x - plat.rect.x)
                self._register(
                    "platform", plat.id, bucket, node_x, pose.top, phase,
                    plat.id, waitable, global_frame, src,
                    action.name, direction, vx_cache=result.final_vx,
                    land_x=af.x)
                self._record_timing(
                    plat.id, phase, global_frame, period,
                    f"以 {action.name}{'向左' if direction < 0 else '向右'}截获")
                break  # 该帧最多匹配一个相位,继续看下一帧

    # ---- 主流程 ----
    def run(self) -> AnalysisResult:
        self.start_clock = time.perf_counter()
        self.queue.append(self._spawn_node())
        while self.queue:
            self._tick_guard()
            node = self.queue.popleft()
            if node.key in self.closed:
                continue
            self.closed.add(node.key)
            if node.kind == "static":
                self._expand_static(node)
            else:
                self._expand_platform(node)

        goal_rec = self._evaluate_goal()
        coll_recs = self._evaluate_collectibles()
        route = self._build_route(goal_rec)
        timing_grouped: dict[str, list[PlatformTiming]] = {}
        for (pid, _phase), t in sorted(self.platform_timing.items(),
                                       key=lambda kv: (kv[0][0], kv[0][1])):
            timing_grouped.setdefault(pid, []).append(t)
        ok = goal_rec.reachable and all(r.reachable for r in coll_recs.values())
        return AnalysisResult(
            level_name=self.level.name,
            ok=ok,
            elapsed_seconds=time.perf_counter() - self.start_clock,
            total_frames_cycle=self.cycle,
            nodes_visited=len(self.closed),
            arcs_simulated=self.arcs_simulated,
            goal=goal_rec,
            collectibles=coll_recs,
            platform_timing=timing_grouped,
            route=route,
            warnings=self._warnings(),
        )

    # ---- 终点 / 收集品可达性 ----
    @staticmethod
    def _aabb_distance(body: Rect, px: float, py: float) -> float:
        dx = max(body.left - px, 0.0, px - body.right)
        dy = max(body.top - py, 0.0, py - body.bottom)
        return (dx * dx + dy * dy) ** 0.5

    def _node_body_variants(self, n: FootNode) -> list[Rect]:
        """节点在真实落地坐标上的身体盒(含规范槽位本身)。"""
        xs = list(n.land_xs)
        if n.x not in xs:
            xs.append(n.x)
        return [Rect(x - PLAYER_HALF_WIDTH, n.y - PLAYER_HEIGHT,
                     PLAYER_HALF_WIDTH * 2, PLAYER_HEIGHT) for x in xs]

    def _evaluate_goal(self) -> ReachRecord:
        gx, gy = self.level.goal
        best: Optional[tuple[float, FootNode]] = None
        for n in self.nodes.values():
            for body in self._node_body_variants(n):
                d = self._aabb_distance(body, gx, gy)
                if d <= GOAL_TOUCH_RADIUS:
                    return ReachRecord(True, n, n.frame)
                if best is None or d < best[0]:
                    best = (d, n)
        return ReachRecord(False, nearest_distance=best[0] if best else None)

    def _evaluate_collectibles(self) -> dict[str, ReachRecord]:
        out: dict[str, ReachRecord] = {}
        for c in self.level.collectibles:
            if c.id in self.collectible_first_frame:
                out[c.id] = ReachRecord(
                    True, frame=self.collectible_first_frame[c.id], via_arc=True)
                continue
            best: Optional[tuple[float, FootNode]] = None
            hit_node: Optional[FootNode] = None
            for n in self.nodes.values():
                hit = False
                for body in self._node_body_variants(n):
                    if _circle_hits_rect(c.x, c.y, c.radius, body):
                        hit = True
                        break
                    d = self._aabb_distance(body, c.x, c.y)
                    if best is None or d < best[0]:
                        best = (d, n)
                if hit:
                    hit_node = n
                    break
            if hit_node is not None:
                out[c.id] = ReachRecord(True, hit_node, hit_node.frame)
            else:
                out[c.id] = ReachRecord(
                    False, nearest_distance=best[0] if best else None)
        return out

    def _build_route(self, goal: ReachRecord) -> list[str]:
        if not goal.reachable or goal.node is None:
            return []
        chain: list[FootNode] = []
        n: Optional[FootNode] = goal.node
        while n is not None:
            chain.append(n)
            n = n.parent
        chain.reverse()
        lines: list[str] = []
        for i, n in enumerate(chain):
            where = (f"移动平台 {n.platform_id} 相位{n.phase}"
                     if n.kind == "platform" else f"静态面 {n.surface_id}")
            if i == 0:
                lines.append(f"第 {n.frame} 帧:出生 → {where} "
                             f"({n.x:.2f}, {n.y:.2f})")
            else:
                dir_txt = {-1: "向左", 1: "向右", 0: ""}[n.parent_direction]
                lines.append(
                    f"第 {n.frame} 帧:{n.parent_action} {dir_txt} → "
                    f"{where} ({n.x:.2f}, {n.y:.2f})")
        return lines

    def _warnings(self) -> list[str]:
        warns: list[str] = []
        for p in self.platforms:
            if p.period_frames > 240:
                warns.append(f"平台 {p.id} 周期 {p.period_frames} 帧 "
                             f"({p.period_frames / 60:.1f}s)偏长,玩家难以记忆节奏")
        return warns


def analyze_level(level: Level, deadline_seconds: float = 10.0) -> AnalysisResult:
    """关卡可达性分析入口,返回完整 :class:`AnalysisResult`。"""
    return Analyzer(level, deadline_seconds).run()
