"""可达性分析引擎。

算法总览:
1. 静态 BFS: 从出生点出发, 对每个已到达的站立面生成全部跳跃轨迹
   (起跳点采样 x 水平速度采样 x 轨迹模板), 用 numpy 批量模拟,
   落点所在面标记为已到达, 迭代至不动点。
2. 移动平台: 对每个未到达的移动平台, 从附近已到达面模拟轨迹并记录
   路径, 用"平台相位位图"反解出所有能落上平台的起跳相位窗口(增量:
   每轮只模拟新出现的源); 已到达的移动平台按其周期采样产生新的
   起跳点, 回到第 1 步。
3. 收集品: 站立面邻近 -> 乘移动平台经过 -> 跳跃弧线经过 三级判定。
   弧线判定用"标准弧线包络"(无碰撞解析弧族到点的最近距离, 不会漏报)
   筛出候选, 再用参考积分器精确验证(不会误报)。
4. 终点: 轨迹经过终点格 / 站立在终点格 / 乘移动平台进入终点格。
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass

import numpy as np

from .level import Level, MovingPlatform
from .physics import (PhysicsParams, Template, build_templates,
                      simulate_reference, VX_FACTORS)
from .sim import simulate_batch

# 起跳点沿平台面的采样步长(格)。0.5 格采样保证落点预测误差在指标(半格)以内。
X0_STEP = 0.5
# 边缘起跳点的内缩偏移(避免脚底正好压在边界格线上)
EDGE_EPS = 0.005
# 移动平台起跳相位采样数
PLATFORM_PHASE_SAMPLES = 60
# 移动平台捕捉分析的轨迹时长上限(tick): 超过 4 秒的弧线不可能再落上平台
CATCH_MAX_TICKS = 240


# ---------------------------------------------------------------- 轨迹展开

def _template_arrays(templates):
    ev1t = np.array([t.events[0][0] if len(t.events) > 0 else -1 for t in templates])
    ev1v = np.array([t.events[0][1] if len(t.events) > 0 else 0.0 for t in templates])
    ev2t = np.array([t.events[1][0] if len(t.events) > 1 else -1 for t in templates])
    ev2v = np.array([t.events[1][1] if len(t.events) > 1 else 0.0 for t in templates])
    return ev1t, ev1v, ev2t, ev2v


def _span_points(lo: float, hi: float) -> np.ndarray:
    """站立面上的起跳点采样(含两端附近与中点)。"""
    if hi - lo < 0.1:
        return np.array([(lo + hi) / 2.0])
    pts = {lo + 0.05, hi - 0.05, (lo + hi) / 2.0}
    x = lo + 0.05
    while x < hi - 0.04:
        pts.add(round(x, 6))
        x += X0_STEP
    return np.array(sorted(pts))


def expand_sources(sources: list[tuple[float, float, float]], p: PhysicsParams,
                   templates) -> dict:
    """把站立面列表展开成轨迹数组。

    sources: list of (x_lo, x_hi, y) 可站立区间。
    返回 dict of numpy 数组 + src_idx(每条轨迹对应的 source 下标)。
    """
    jump_t = np.array([i for i, t in enumerate(templates) if not t.edge_only])
    edge_t = np.array([i for i, t in enumerate(templates) if t.edge_only])
    vx_all = np.array([f * p.run_speed for f in VX_FACTORS])
    vx_neg = vx_all[vx_all < 0]
    vx_pos = vx_all[vx_all > 0]

    X0, Y0, VX, TPL, SRC = [], [], [], [], []
    for si, (lo, hi, y) in enumerate(sources):
        pts = _span_points(lo, hi)
        np_, nv, nj = len(pts), len(vx_all), len(jump_t)
        X0.append(np.repeat(pts, nv * nj))
        VX.append(np.tile(np.repeat(vx_all, nj), np_))
        TPL.append(np.tile(jump_t, np_ * nv))
        Y0.append(np.full(np_ * nv * nj, y))
        SRC.append(np.full(np_ * nv * nj, si))
        # 边缘坠落/土狼类: 从两端向外走出
        ne = len(edge_t)
        for x0e, vxs in ((lo + EDGE_EPS, vx_neg), (hi - EDGE_EPS, vx_pos)):
            nn = len(vxs) * ne
            X0.append(np.full(nn, x0e))
            VX.append(np.repeat(vxs, ne))
            TPL.append(np.tile(edge_t, len(vxs)))
            Y0.append(np.full(nn, y))
            SRC.append(np.full(nn, si))

    ev1t, ev1v, ev2t, ev2v = _template_arrays(templates)
    tpl = np.concatenate(TPL)
    return {
        "x0": np.concatenate(X0), "y0": np.concatenate(Y0),
        "vx": np.concatenate(VX),
        "ev1_tick": ev1t[tpl], "ev1_val": ev1v[tpl],
        "ev2_tick": ev2t[tpl], "ev2_val": ev2v[tpl],
        "src_idx": np.concatenate(SRC).astype(np.int64),
    }


# ---------------------------------------------------------------- 报告

@dataclass
class CheckReport:
    level_name: str
    verdict: str                       # 'pass' | 'fail'
    goal_reachable: bool
    collectibles_total: int
    collectibles_reachable: int
    unreachable_collectibles: list     # list[dict]
    moving_windows: list               # list[dict] 移动平台起跳窗口
    unreachable_platforms: list        # list[str]
    surfaces_reached: int
    surfaces_total: int
    trajectories_simulated: int
    elapsed: float
    partial: bool = False

    def to_dict(self) -> dict:
        return {
            "level": self.level_name,
            "verdict": self.verdict,
            "goal_reachable": self.goal_reachable,
            "collectibles_total": self.collectibles_total,
            "collectibles_reachable": self.collectibles_reachable,
            "unreachable_collectibles": self.unreachable_collectibles,
            "moving_platform_windows": self.moving_windows,
            "unreachable_platforms": self.unreachable_platforms,
            "surfaces_reached": self.surfaces_reached,
            "surfaces_total": self.surfaces_total,
            "trajectories_simulated": self.trajectories_simulated,
            "elapsed_seconds": round(self.elapsed, 3),
            "partial": self.partial,
        }

    def format_text(self) -> str:
        L = []
        L.append(f"=== 关卡可通关性检查: {self.level_name} ===")
        if self.partial:
            L.append("!! 超出时间预算, 结果为部分检查(可能漏报)")
        ok = self.verdict == "pass"
        L.append(f"结论: {'✓ 可以通关' if ok else '✗ 不可通关'}")
        L.append(f"终点: {'可达' if self.goal_reachable else '不可达 ← 玩家无法通关!'}")
        L.append(f"收集品: {self.collectibles_reachable}/{self.collectibles_total} 可达")
        if self.unreachable_collectibles:
            L.append("  够不着的收集品:")
            for c in self.unreachable_collectibles:
                L.append(f"    - {c['id']} @ ({c['x']:.1f}, {c['y']:.1f})  {c['note']}")
        if self.moving_windows:
            L.append("移动平台起跳时机:")
            for w in self.moving_windows:
                wins = ", ".join(f"{a:.2f}s–{b:.2f}s" for a, b in w["windows"])
                L.append(f"    - {w['platform']}: 周期 {w['period']:.2f}s, "
                         f"在 {wins} 起跳可落上(从 {w['from']})")
        if self.unreachable_platforms:
            L.append("任何时机都落不上去的移动平台: " + ", ".join(self.unreachable_platforms))
        L.append(f"统计: 站立面 {self.surfaces_reached}/{self.surfaces_total}, "
                 f"模拟轨迹 {self.trajectories_simulated}, 用时 {self.elapsed:.2f}s")
        return "\n".join(L)


# ---------------------------------------------------------------- 工具

def _rot(bits: int, n: int, P: int, full: int) -> int:
    """位掩码循环右移 n 位(模 P)。注意强转 Python int: numpy 整数会劫持位移运算。"""
    bits = int(bits)
    n = int(n) % P
    if n == 0:
        return bits
    return ((bits >> n) | (bits << (P - n))) & full


def _bits_to_ranges(bits: int, P: int, dt: float) -> list[tuple[float, float]]:
    runs = []
    g = 0
    while g < P:
        if (bits >> g) & 1:
            a = g
            while g < P and (bits >> g) & 1:
                g += 1
            runs.append((round(a * dt, 2), round(g * dt, 2)))
        else:
            g += 1
    return runs


# ---------------------------------------------------------------- 主流程

def check_level(level: Level, p: PhysicsParams, time_budget: float = 10.0) -> CheckReport:
    t_start = time.perf_counter()
    partial = False

    def over_budget() -> bool:
        return (time.perf_counter() - t_start) > time_budget

    templates = build_templates(p)
    sx, sy = level.spawn

    reached: set[int] = set()
    # 出生点脚下的面直接可达
    below_col = math.floor(sx)
    below_row = math.floor(sy - 0.5)
    if 0 <= below_row < level.height and 0 <= below_col < level.width:
        sid = int(level.surf_id[below_row, below_col])
        if sid >= 0:
            reached.add(sid)

    goal_hit = False
    traj_count = 0
    hit_springs: set = set()             # (row, col) 被轨迹弹起的弹簧
    m_reached: dict[str, dict] = {}      # pid -> {"bits","windows","evidence"}
    m_state: dict[str, dict] = {}        # pid -> {"bits","seen"} 增量缓存
    m_takeoff: list[tuple[float, float, float]] = []

    def surf_source(sid):
        s = level.surfaces[sid]
        return (s.x0, s.x1, s.y)

    frontier: list[tuple[float, float, float]] = [(sx, sx, sy)]
    if reached:
        frontier += [surf_source(s) for s in reached]

    # ---- 主循环: 静态 BFS <-> 移动平台 ----
    while True:
        # 静态 BFS 至不动点
        while frontier:
            if over_budget():
                partial = True
                break
            tr = expand_sources(frontier, p, templates)
            traj_count += len(tr["x0"])
            res = simulate_batch(level, p, tr["x0"], tr["y0"], tr["vx"],
                                 tr["ev1_tick"], tr["ev1_val"],
                                 tr["ev2_tick"], tr["ev2_val"],
                                 goal_check=level.has_goal and not goal_hit)
            traj_count += 0
            goal_hit |= bool(res.goal.any())
            hit_springs |= res.spring_cells
            new_sids = set()
            for i in range(res.n):
                if res.landed[i]:
                    sid = int(level.surf_id[res.land_row[i], res.land_col[i]])
                    if sid >= 0 and sid not in reached:
                        new_sids.add(sid)
            reached |= new_sids
            frontier = [surf_source(s) for s in new_sids]
        if partial:
            break

        # 移动平台捕捉窗口(增量: 每轮只模拟新出现的源)
        cand_sources = [surf_source(s) for s in reached] + m_takeoff
        progress = False
        for m in level.moving:
            if m.pid in m_reached:
                continue
            if over_budget():
                partial = True
                break
            st = m_state.setdefault(m.pid, {"bits": 0, "seen": set()})
            near = _near_sources(m, cand_sources, p)
            new = [s for s in near if s not in st["seen"]]
            if not new:
                continue
            st["seen"].update(new)
            bits, evidence = _catch_window(level, p, templates, m, new)
            traj_count += evidence.get("simulated", 0)
            hit_springs |= evidence.get("springs", set())
            if bits:
                st["bits"] |= bits
                if "from" not in st and "from" in evidence:
                    st["from"] = evidence["from"]
            if st["bits"]:
                P = m.ticks
                m_reached[m.pid] = {
                    "bits": st["bits"],
                    "windows": _bits_to_ranges(st["bits"], P, p.dt),
                    "evidence": {"from": st.get("from", "?")},
                }
                # 从该平台起跳的新源(相位采样)
                step = max(1, P // PLATFORM_PHASE_SAMPLES)
                for g in range(0, P, step):
                    mx, my = m.pos(g)
                    top = my + m.h
                    lo = mx + min(0.2, m.w / 2)
                    hi = mx + max(m.w - 0.2, m.w / 2)
                    m_takeoff.append((lo, hi, top))
                    frontier.append((lo, hi, top))
                progress = True
        if not progress or partial:
            break

    # ---- 终点补充判定: 站立 / 乘移动平台 ----
    if not goal_hit:
        for sid in reached:
            s = level.surfaces[sid]
            r = int(s.y)
            if 0 <= r < level.height:
                c0 = max(0, int(s.x0))
                c1 = min(level.width - 1, int(math.ceil(s.x1 - 1e-6)) - 1)
                if c1 >= c0 and level.goal_grid[r, c0:c1 + 1].any():
                    goal_hit = True
                    break
    if not goal_hit:
        for m in level.moving:
            if m.pid not in m_reached:
                continue
            cols = np.floor(m.xs + m.w / 2).astype(np.int64)
            rows = np.floor(m.ys + m.h).astype(np.int64)
            inb = (cols >= 0) & (cols < level.width) & (rows >= 0) & (rows < level.height)
            if inb.any() and level.goal_grid[rows[inb], cols[inb]].any():
                goal_hit = True
                break

    # ---- 收集品判定 ----
    unreached_c = _cover_collectibles(
        level, p, templates, reached, m_reached, m_takeoff, hit_springs,
        over_budget,
    )
    if over_budget():
        partial = True

    elapsed = time.perf_counter() - t_start

    moving_windows = []
    for m in level.moving:
        if m.pid in m_reached:
            info = m_reached[m.pid]
            moving_windows.append({
                "platform": m.pid,
                "period": m.period,
                "windows": info["windows"],
                "from": info["evidence"].get("from", "?"),
            })
    unreachable_platforms = [m.pid for m in level.moving if m.pid not in m_reached]

    verdict = "pass" if (goal_hit or not level.has_goal) and not unreached_c else "fail"
    return CheckReport(
        level_name=level.name,
        verdict=verdict,
        goal_reachable=goal_hit if level.has_goal else True,
        collectibles_total=len(level.collectibles),
        collectibles_reachable=len(level.collectibles) - len(unreached_c),
        unreachable_collectibles=unreached_c,
        moving_windows=moving_windows,
        unreachable_platforms=unreachable_platforms,
        surfaces_reached=len(reached),
        surfaces_total=len(level.surfaces),
        trajectories_simulated=traj_count,
        elapsed=elapsed,
        partial=partial,
    )


# ---------------------------------------------------------------- 移动平台捕捉

def _near_sources(m: MovingPlatform, sources, p: PhysicsParams):
    """按跳跃能力包络过滤出可能够到该平台的源。"""
    mbx0, mby0, mbx1, mby1 = m.bbox
    R = p.max_range
    H_reach = p.max_total_height + 1.0
    return [s for s in sources
            if s[1] > mbx0 - R and s[0] < mbx1 + R
            and s[2] > mby0 - 2.0 and s[2] < mby1 + H_reach]


def _catch_window(level: Level, p: PhysicsParams, templates,
                  m: MovingPlatform, sources) -> tuple[int, dict]:
    """计算从给定源起跳、落上移动平台 m 的起跳相位位图。

    返回 (launch_bits, evidence)。launch_bits 第 g 位为 1 表示:
    在全局 tick ≡ g (mod P) 起跳, 存在一条轨迹能落上该平台。
    """
    if not sources:
        return 0, {"simulated": 0}
    P = m.ticks
    full = (1 << P) - 1
    mbx0, mby0, mbx1, mby1 = m.bbox

    tr = expand_sources(sources, p, templates)
    res = simulate_batch(level, p, tr["x0"], tr["y0"], tr["vx"],
                         tr["ev1_tick"], tr["ev1_val"],
                         tr["ev2_tick"], tr["ev2_val"],
                         record_paths=True, goal_check=False,
                         max_ticks=CATCH_MAX_TICKS)
    catch_map = m.build_catch_map()
    launch_bits = 0
    evidence: dict = {"simulated": len(tr["x0"]), "springs": res.spring_cells}
    src_of = tr["src_idx"]

    ex0, ex1 = mbx0 - 0.75, mbx1 + 0.75
    ey0, ey1 = mby0 - 0.75, mby1 + 0.75
    for i in range(res.n):
        L = int(res.path_len[i])
        if L <= 0:
            continue
        px = res.xs[i, :L]
        py = res.ys[i, :L]
        if px.min() > ex1 or px.max() < ex0 or py.min() > ey1 or py.max() < ey0:
            continue
        mask = (px >= ex0) & (px <= ex1) & (py >= ey0) & (py <= ey1)
        if not mask.any():
            continue
        idx = np.nonzero(mask)[0]
        # 下落判定: 该点低于上一点
        prev_y = np.empty(L)
        prev_y[0] = tr["y0"][i]
        prev_y[1:] = py[:-1]
        for j in idx:
            if py[j] >= prev_y[j]:
                continue
            key = (int(round(px[j] * 2.0)), int(round(py[j] * 2.0)))
            bits = catch_map.get(key)
            if bits:
                launch_bits |= _rot(bits, (j + 1) % P, P, full)
                if "from" not in evidence:
                    si = int(src_of[i])
                    lo, hi, y = sources[si]
                    evidence["from"] = f"站立面 ({lo:.1f}~{hi:.1f}, y={y:.1f})"
        if launch_bits == full:
            break
    return launch_bits, evidence


# ---------------------------------------------------------------- 收集品覆盖

class _ArcShapes:
    """标准弧线缓存: 每个 (事件表, 水平速度) 一条无碰撞相对弧线。"""

    def __init__(self, p: PhysicsParams):
        self.p = p
        self.empty = Level("~empty~", 4, 4)
        self.cache: dict = {}

    def get(self, events: tuple, vx: float):
        key = (events, vx)
        arc = self.cache.get(key)
        if arc is None:
            tpl = Template("arc", events, False)
            r = simulate_reference(self.empty, self.p, 0.0, 0.0, vx, tpl,
                                   y_min=-1e9)
            pts = np.array(r.path[1:], dtype=np.float64)  # 跳过起点
            if len(pts) == 0:
                pts = np.zeros((1, 2))
            arc = (pts[:, 0].copy(), pts[:, 1].copy())
            self.cache[key] = arc
        return arc


def _spring_templates(p: PhysicsParams, impulse: float) -> list[tuple]:
    """弹簧弹起后的弧线事件表(弹起 / 弹起接二段跳)。"""
    out = [((0, impulse),)]
    if p.double_jump:
        out.append(((0, impulse), (12, p.double_jump_velocity)))
        out.append(((0, impulse), (24, p.double_jump_velocity)))
    return out


def _cover_collectibles(level: Level, p: PhysicsParams, templates,
                        reached: set[int], m_reached: dict,
                        m_takeoff: list, hit_springs: set,
                        over_budget) -> list:
    """三级判定: 站立面邻近 -> 乘移动平台 -> 跳跃弧线经过(包络+验证)。"""
    cols = level.collectibles
    if not cols:
        return []
    covered = np.zeros(len(cols), dtype=bool)
    cx = np.array([c.x for c in cols])
    cy = np.array([c.y for c in cols])
    cr = np.array([c.radius for c in cols])

    # 1) 站立面邻近(含出生点)
    if reached:
        sx0 = np.array([level.surfaces[s].x0 for s in reached])
        sx1 = np.array([level.surfaces[s].x1 for s in reached])
        sy = np.array([level.surfaces[s].y for s in reached])
        for i in range(len(cols)):
            dx = np.maximum(np.maximum(sx0 - cx[i], 0.0), cx[i] - sx1)
            dy = np.abs(sy - cy[i])
            if ((dx ** 2 + dy ** 2) <= cr[i] ** 2).any():
                covered[i] = True
    spx, spy = level.spawn
    covered |= ((cx - spx) ** 2 + (cy - spy) ** 2) <= cr ** 2

    # 2) 乘移动平台经过
    for m in level.moving:
        if m.pid not in m_reached:
            continue
        top = m.ys + m.h
        for i in range(len(cols)):
            if covered[i]:
                continue
            dx = np.maximum(np.maximum(m.xs - cx[i], 0.0), cx[i] - (m.xs + m.w))
            dy = top - cy[i]
            if ((dx ** 2 + dy ** 2) <= (cr[i] + 0.3) ** 2).any():
                covered[i] = True

    # 3) 跳跃弧线经过: 标准弧线包络筛选 + 参考积分器精确验证
    rest = np.nonzero(~covered)[0]
    if len(rest):
        shapes = _ArcShapes(p)
        vx_all = [f * p.run_speed for f in VX_FACTORS]
        jump_tpls = [t for t in templates if not t.edge_only]
        edge_tpls = [t for t in templates if t.edge_only]
        # 源: 已到达站立面 + 移动平台起跳区间 + 被弹起的弹簧
        surf_like = [(level.surfaces[s].x0, level.surfaces[s].x1, level.surfaces[s].y)
                     for s in reached] + list(m_takeoff)
        spring_srcs = []
        for (r, c) in hit_springs:
            imp = float(level.spring[r, c])
            spring_srcs.append((c + 0.5, r + 0.5, imp))
        R = p.max_range
        # 预计算每个弧形的包络标量
        arc_meta = {}   # (events, vx) -> (DX, DY, dx_min, dx_max, dy_max)
        for tpl in jump_tpls + edge_tpls:
            for vx in vx_all:
                DX, DY = shapes.get(tpl.events, vx)
                arc_meta[(tpl.events, vx)] = (DX, DY, DX.min(), DX.max(), DY.max())
        spring_meta = {}
        for (_, _, imp) in spring_srcs:
            for ev in _spring_templates(p, imp):
                for vx in vx_all:
                    DX, DY = shapes.get(ev, vx)
                    spring_meta[(ev, vx)] = (DX, DY, DX.min(), DX.max(), DY.max())

        for i in rest:
            if over_budget():
                break
            x_c, y_c, r_c = cx[i], cy[i], cr[i]
            r2 = r_c * r_c
            found = False
            # 3a) 站立面/移动平台源
            for (lo, hi, y0) in surf_like:
                if found:
                    break
                if hi < x_c - R - r_c or lo > x_c + R + r_c:
                    continue
                if y0 + p.max_total_height + 1.0 < y_c - r_c:
                    continue
                for tpl in jump_tpls:
                    if found:
                        break
                    for vx in vx_all:
                        DX, DY, dx0, dx1, dym = arc_meta[(tpl.events, vx)]
                        if y0 + dym < y_c - r_c:
                            continue
                        if hi + dx1 < x_c - r_c or lo + dx0 > x_c + r_c:
                            continue
                        w = _arc_witness(DX, DY, lo, hi, y0, x_c, y_c, r2)
                        if w is not None and _verify(level, p, tpl, vx, w, y0,
                                                     x_c, y_c, r_c):
                            found = True
                            break
                    # end vx
                # 边缘模板: 两个边缘点源
                for tpl in edge_tpls:
                    if found:
                        break
                    for x0e, vxs in ((lo + EDGE_EPS, [v for v in vx_all if v < 0]),
                                     (hi - EDGE_EPS, [v for v in vx_all if v > 0])):
                        for vx in vxs:
                            DX, DY, dx0, dx1, dym = arc_meta[(tpl.events, vx)]
                            if y0 + dym < y_c - r_c:
                                continue
                            if x0e + dx1 < x_c - r_c or x0e + dx0 > x_c + r_c:
                                continue
                            w = _arc_witness(DX, DY, x0e, x0e, y0, x_c, y_c, r2)
                            if w is not None and _verify(level, p, tpl, vx, w, y0,
                                                         x_c, y_c, r_c):
                                found = True
                                break
                        if found:
                            break
            # 3b) 弹簧源
            if not found:
                for (sx0, sy0, imp) in spring_srcs:
                    if found:
                        break
                    if abs(sx0 - x_c) > R + r_c:
                        continue
                    for ev in _spring_templates(p, imp):
                        if found:
                            break
                        for vx in vx_all:
                            DX, DY, dx0, dx1, dym = spring_meta[(ev, vx)]
                            if sy0 + dym < y_c - r_c:
                                continue
                            if sx0 + dx1 < x_c - r_c or sx0 + dx0 > x_c + r_c:
                                continue
                            w = _arc_witness(DX, DY, sx0, sx0, sy0, x_c, y_c, r2)
                            if w is not None:
                                tpl = Template("spring", ev, False)
                                if _verify(level, p, tpl, vx, w, sy0,
                                           x_c, y_c, r_c):
                                    found = True
                                    break
            covered[i] = found

    # 未覆盖: 附带诊断信息
    unreached = []
    for i in np.nonzero(~covered)[0]:
        c = cols[int(i)]
        note = "附近没有任何可到达的站立面"
        if reached:
            best = min(
                math.hypot(
                    max(level.surfaces[s].x0 - c.x, 0.0, c.x - level.surfaces[s].x1),
                    abs(level.surfaces[s].y - c.y),
                )
                for s in reached
            )
            note = f"距最近可到达站立面 {best:.1f} 格"
        unreached.append({"id": c.cid, "x": c.x, "y": c.y, "note": note})
    return unreached


def _arc_witness(DX, DY, lo, hi, y0, x_c, y_c, r2):
    """弧族(x0 ∈ [lo,hi] 平移)到点的最近距离 <= r 时, 返回最优起跳点(证人), 否则 None。

    包络下界判定: 标准弧线是无碰撞弧, 真实弧线是它的前缀, 故不会漏报。
    """
    need = x_c - DX
    bx = np.clip(need, lo, hi)
    d2 = (bx + DX - x_c) ** 2 + (y0 + DY - y_c) ** 2
    n = int(np.argmin(d2))
    if d2[n] <= r2:
        return float(bx[n])
    return None


def _verify(level, p, tpl, vx, x0, y0, x_c, y_c, r_c) -> bool:
    """用参考积分器精确验证: 从证人起跳点实打一遍, 真实路径进入半径才算数(不误报)。"""
    res = simulate_reference(level, p, x0, y0, vx, tpl)
    r2 = r_c * r_c
    for (px, py) in res.path:
        if (px - x_c) ** 2 + (py - y_c) ** 2 <= r2:
            return True
    return False
