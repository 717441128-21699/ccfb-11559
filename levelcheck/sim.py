"""numpy 批量轨迹模拟器。

一次性模拟成千上万条跳跃轨迹(每条 = 起点 x0,y0 + 水平速度 vx + 轨迹模板),
语义与 physics.simulate_reference 的逐步积分完全一致(见该文件 docstring 的
每 tick 顺序), 因此检查器预测落点与"游戏实测"的偏差为 0(远优于 0.5 格指标)。

可选能力:
- record_paths: 记录每条轨迹每 tick 的位置(移动平台相位分析用)
- 终点检测:     每 tick 检查是否进入终点格(goal_check)
- 弹簧触碰:     记录被弹起的弹簧格(供收集品弧线判定的弹簧源)
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .level import Level
from .physics import PhysicsParams


@dataclass
class BatchResult:
    n: int
    landed: np.ndarray        # [N] bool
    land_x: np.ndarray        # [N] float
    land_y: np.ndarray
    land_col: np.ndarray      # [N] int 落地实心格
    land_row: np.ndarray
    land_tick: np.ndarray     # [N] int 落地时刻(未落地为 -1)
    goal: np.ndarray          # [N] bool 是否经过终点格
    path_len: np.ndarray      # [N] int 有效路径长度(tick 数)
    spring_cells: set         # set[(row, col)] 被弹起的弹簧格
    xs: np.ndarray | None     # [N, T] 仅 record_paths 时
    ys: np.ndarray | None


def simulate_batch(
    level: Level,
    p: PhysicsParams,
    x0: np.ndarray,
    y0: np.ndarray,
    vx: np.ndarray,
    ev1_tick: np.ndarray,
    ev1_val: np.ndarray,
    ev2_tick: np.ndarray,
    ev2_val: np.ndarray,
    record_paths: bool = False,
    goal_check: bool = True,
    max_ticks: int | None = None,
) -> BatchResult:
    """批量模拟。所有输入数组长度 N, 事件 tick 为 -1 表示无该事件。"""
    N = len(x0)
    x = x0.astype(np.float64).copy()
    y = y0.astype(np.float64).copy()
    vx = vx.astype(np.float64)
    vy = np.zeros(N)
    active = np.ones(N, dtype=bool)
    bounces = np.zeros(N, dtype=np.int8)

    landed = np.zeros(N, dtype=bool)
    land_x = np.zeros(N)
    land_y = np.zeros(N)
    land_col = np.full(N, -1, dtype=np.int64)
    land_row = np.full(N, -1, dtype=np.int64)
    land_tick = np.full(N, -1, dtype=np.int64)
    goal = np.zeros(N, dtype=bool)
    path_len = np.zeros(N, dtype=np.int64)
    spring_cells: set = set()

    solid = level.solid
    spring = level.spring
    goalg = level.goal_grid
    H, W = solid.shape
    dt = p.dt
    gdt = p.gravity * dt
    max_fall = p.max_fall_speed
    ph = p.player_height

    T = max_ticks if max_ticks is not None else p.max_ticks
    # 本批次出现过的跳跃事件时刻(大多数 tick 无事件, 门控掉)
    ev_ticks = set(ev1_tick[ev1_tick >= 0].tolist()) | set(ev2_tick[ev2_tick >= 0].tolist())

    xs = np.full((N, T), np.nan) if record_paths else None
    ys = np.full((N, T), np.nan) if record_paths else None

    for n in range(T):
        if not active.any():
            break
        # 1) 跳跃事件(仅在有事件的 tick 计算掩码)
        if n in ev_ticks:
            m = active & (ev1_tick == n)
            if m.any():
                vy[m] = ev1_val[m]
            m = active & (ev2_tick == n)
            if m.any():
                vy[m] = ev2_val[m]
        # 2) 重力(对全数组操作, 非活跃项的值不会被读取)
        np.subtract(vy, gdt, out=vy)
        np.maximum(vy, -max_fall, out=vy)
        # 3) 水平移动 + 撞墙
        nx = x + vx * dt
        col = np.floor(nx).astype(np.int64)
        row = np.floor(y).astype(np.int64)
        inb = (col >= 0) & (col < W) & (row >= 0) & (row < H)
        hit = np.zeros(N, dtype=bool)
        if inb.any():
            hit[inb] = solid[row[inb], col[inb]]
        blocked = active & hit
        x = np.where(blocked, x, nx)
        # 4) 垂直移动
        ny = y + vy * dt
        col = np.floor(x).astype(np.int64)
        row = np.floor(ny).astype(np.int64)
        inb = (col >= 0) & (col < W) & (row >= 0) & (row < H)
        cell_solid = np.zeros(N, dtype=bool)
        cell_spring = np.zeros(N, dtype=bool)
        if inb.any():
            cell_solid[inb] = solid[row[inb], col[inb]]
            cell_spring[inb] = spring[row[inb], col[inb]] > 0
        falling = vy < 0
        # 顶头(仅上升段)
        if (vy > 0).any():
            rising = vy > 0
            rowh = np.floor(ny + ph).astype(np.int64)
            inbh = (col >= 0) & (col < W) & (rowh >= 0) & (rowh < H)
            head_solid = np.zeros(N, dtype=bool)
            if inbh.any():
                head_solid[inbh] = solid[rowh[inbh], col[inbh]]
            bump = active & rising & head_solid
            if bump.any():
                vy[bump] = 0.0
                ny = np.where(bump, y, ny)
        # 弹簧
        spr = active & falling & ~cell_solid & cell_spring & (bounces < 8)
        if spr.any():
            vy[spr] = spring[row[spr], col[spr]]
            bounces[spr] += 1
            for r_, c_ in zip(row[spr].tolist(), col[spr].tolist()):
                spring_cells.add((r_, c_))
        # 落地
        land = active & falling & cell_solid
        if land.any():
            landed[land] = True
            land_x[land] = x[land]
            land_y[land] = row[land] + 1.0
            land_col[land] = col[land]
            land_row[land] = row[land]
            land_tick[land] = n + 1
            active[land] = False
        y = np.where(active, ny, y)
        if record_paths:
            path_len[active] = n + 1
            xs[:, n] = x
            ys[:, n] = y
        # 终点检测(取脚底所在格)
        if goal_check:
            rowg = np.floor(y).astype(np.int64)
            inbg = (col >= 0) & (col < W) & (rowg >= 0) & (rowg < H)
            ghit = np.zeros(N, dtype=bool)
            if inbg.any():
                ghit[inbg] = goalg[rowg[inbg], col[inbg]]
            goal |= ghit & active
        # 掉出世界
        dead = active & (y < -10.0)
        active[dead] = False

    return BatchResult(
        n=N,
        landed=landed,
        land_x=land_x,
        land_y=land_y,
        land_col=land_col,
        land_row=land_row,
        land_tick=land_tick,
        goal=goal,
        path_len=path_len,
        spring_cells=spring_cells,
        xs=xs,
        ys=ys,
    )
