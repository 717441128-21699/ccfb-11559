"""角色状态机与固定步长碰撞积分。

**这是整个工具正确性的核心**:真实游戏侧的角色脚本与静态分析器调用的是
同一个 :func:`step`,物理不可能两边跑偏。分析报告里"跳跃落点与实测偏差
不超过半格"的承诺,本质上来自这一设计——分析器不是在重新实现物理,
而是在枚举输入策略后反复调用游戏自己的步进函数。

步进顺序(与常见平台跳跃游戏一致):
    1. 移动平台托举(站立者随平台位移,惯性在起跳时继承)
    2. 水平加速 / 摩擦,逼近目标跑速
    3. 跳跃处理(地面跳 / 土狼跳 / 二段跳 / 短跳截断)+ 重力
    4. 水平积分 + 轴向碰撞推出
    5. 垂直积分 + 轴向碰撞推出(落地 / 顶头 / 弹簧)
    6. 危险物、坠落、出界判定
    7. 土狼计时与落地状态刷新

热路径用标量边界 (l/r/t/b) 而非反复构造 Rect,行为与 AABB 完全等价。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from .level import Level, Rect
from .physics import (
    FIXED_DT,
    PLAYER_HALF_WIDTH,
    PLAYER_HEIGHT,
)


@dataclass(frozen=True)
class JumpInput:
    """一帧的操作输入。

    move:        -1 左 / 0 松 / 1 右
    jump_pressed: 本帧刚按下跳跃(边沿信号)
    jump_held:    本帧跳跃键处于按住状态
    """

    move: int = 0
    jump_pressed: bool = False
    jump_held: bool = True


@dataclass(frozen=True)
class Landing:
    """一次落地事件,分析器据此生成落脚点。"""

    kind: str            # "tile" | "platform" | "spring"
    surface_id: str      # 平台 id;瓦片为 "tile";弹簧为 "spring"
    x: float             # 落地时脚底中心 x
    y: float             # 落地时脚底线 y(= 表面顶面)
    frame: int


@dataclass
class StepEvents:
    landed: list[Landing] = field(default_factory=list)
    spring_bounces: list[Landing] = field(default_factory=list)
    touched_collectibles: list[str] = field(default_factory=list)
    deaths: list[str] = field(default_factory=list)


@dataclass
class PlayerState:
    """角色运行时状态。x/y 为脚底中心坐标(格)。"""

    x: float
    y: float
    vx: float = 0.0
    vy: float = 0.0
    grounded: bool = False
    coyote: int = 0
    air_jumps_left: int = 0
    riding: Optional[str] = None     # 正在站立的移动平台 id
    frame: int = 0
    dead: bool = False
    death_reason: Optional[str] = None

    def body(self) -> Rect:
        return Rect(self.x - PLAYER_HALF_WIDTH, self.y - PLAYER_HEIGHT,
                    PLAYER_HALF_WIDTH * 2.0, PLAYER_HEIGHT)


def make_spawn_state(level: Level) -> PlayerState:
    x, y = level.spawn
    st = PlayerState(x=x, y=y, air_jumps_left=level.physics.max_air_jumps)
    # 出生即判定脚下支撑:否则第一帧会以悬空状态下坠,进而穿进地面
    st.grounded, st.riding = _support_at(level, st.x, st.y)
    if st.grounded:
        st.coyote = level.physics.coyote_frames
    return st


def _support_at(level: Level, x: float, foot_y: float) -> tuple[bool, Optional[str]]:
    """判断 (x, foot_y) 脚底是否贴着可站立面,返回(是否着地, 平台id)。"""
    probe = Rect(x - PLAYER_HALF_WIDTH, foot_y - 0.05,
                 PLAYER_HALF_WIDTH * 2, 0.1)
    for tx, ty in _overlapping_tiles(level, probe):
        if abs(float(ty) - foot_y) <= 1e-4:
            return True, None
    for plat in level.platforms_near(probe):
        pr = plat.pose(0)
        if (x + PLAYER_HALF_WIDTH > pr.left and x - PLAYER_HALF_WIDTH < pr.right
                and abs(pr.top - foot_y) <= 1e-4):
            return True, plat.id
    return False, None


def _approach(current: float, target: float, max_delta: float) -> float:
    if current < target:
        return min(current + max_delta, target)
    return max(current - max_delta, target)


def _overlapping_tiles(level: Level, rect: Rect) -> list[tuple[int, int]]:
    """返回与 rect 相交的实心瓦片坐标。

    边界用 floor:右/下边恰好落在格线上时不算进入那一格,
    与 Level.solid_aabb 的离散化规则保持一致。
    """
    x0 = math.floor(rect.left)
    x1 = math.floor(rect.right - 1e-9)
    y0 = math.floor(rect.top)
    y1 = math.floor(rect.bottom - 1e-9)
    out: list[tuple[int, int]] = []
    for ty in range(y0, y1 + 1):
        for tx in range(x0, x1 + 1):
            if (tx, ty) in level.solid_tiles:
                out.append((tx, ty))
    return out


def _overlapping_tiles_bounds(level: Level, l: float, r: float,
                              t: float, b: float) -> list[tuple[int, int]]:
    """标量边界版的实心瓦片查询,省掉一次 Rect 构造。"""
    x0 = math.floor(l)
    x1 = math.floor(r - 1e-9)
    y0 = math.floor(t)
    y1 = math.floor(b - 1e-9)
    tiles = level.solid_tiles
    out: list[tuple[int, int]] = []
    for ty in range(y0, y1 + 1):
        for tx in range(x0, x1 + 1):
            if (tx, ty) in tiles:
                out.append((tx, ty))
    return out


def step(level: Level, st: PlayerState, inp: JumpInput) -> StepEvents:
    """推进一帧(FIXED_DT)。死亡后再调用是空操作。"""
    ev = StepEvents()
    if st.dead:
        return ev
    cfg = level.physics
    st.frame += 1

    # ---- 1. 移动平台托举:按平台本帧位移带着角色走 ----
    if st.riding is not None:
        plat = level.platform_by_id(st.riding)
        if plat is None:
            st.riding = None
        else:
            old = plat.pose(st.frame - 1)
            new = plat.pose(st.frame)
            st.x += new.cx - old.cx
            st.y += new.top - old.top
            if level.solid_aabb(st.body()):
                st.dead = True
                st.death_reason = "crushed_by_platform"
                ev.deaths.append(st.death_reason)
                return ev

    was_grounded = st.grounded
    prev_bottom = st.y

    # ---- 2. 水平加减速 ----
    target_vx = inp.move * cfg.run_speed
    accel = cfg.ground_accel if st.grounded else cfg.air_accel
    st.vx = _approach(st.vx, target_vx, accel * FIXED_DT)

    # ---- 3+4. 重力与跳跃 ----
    # 半隐式欧拉:每帧先更新速度再积分位置。跳跃放在重力之后,起跳帧
    # 直接以完整起跳速度进入位置积分,离散最大高度由 physics 中的
    # discrete_jump_height() 给出,与本积分器逐项一致。
    jump_this_frame = False
    if inp.jump_pressed:
        if st.grounded or st.coyote > 0:
            st.vy = -cfg.jump_velocity
            st.grounded = False
            st.coyote = 0
            st.riding = None
            jump_this_frame = True
        elif st.air_jumps_left > 0:
            st.vy = -cfg.air_jump_velocity
            st.air_jumps_left -= 1
            st.riding = None
            jump_this_frame = True
    if not jump_this_frame:
        st.vy = min(st.vy + cfg.gravity * FIXED_DT, cfg.max_fall_speed)
    # 短跳:上升途中松开跳跃键,持续削速度(几帧内收敛到截断值)
    if st.vy < 0.0 and not inp.jump_held:
        st.vy *= cfg.jump_cut_ratio

    def _bounds() -> tuple[float, float, float, float]:
        return (st.x - PLAYER_HALF_WIDTH, st.x + PLAYER_HALF_WIDTH,
                st.y - PLAYER_HEIGHT, st.y)

    # ---- 5. 水平积分与碰撞(瓦片 + 移动平台都是实体墙)----
    dx = st.vx * FIXED_DT
    st.x += dx
    l, r, t, b = _bounds()
    for tx, ty in _overlapping_tiles_bounds(level, l, r, t, b):
        tl = float(tx)
        if r > tl and l < tl + 1.0 and b > float(ty) and t < float(ty) + 1.0:
            if dx > 0:
                st.x = tl - PLAYER_HALF_WIDTH
            elif dx < 0:
                st.x = tl + 1.0 + PLAYER_HALF_WIDTH
            st.vx = 0.0
            l, r, t, b = _bounds()
    for plat in level.platforms_at_x(st.x):
        pr = plat.pose(st.frame)
        l, r, t, b = _bounds()
        if r > pr.left and l < pr.right and b > pr.top and t < pr.bottom:
            if dx > 0:
                st.x = pr.left - PLAYER_HALF_WIDTH
            elif dx < 0:
                st.x = pr.right + PLAYER_HALF_WIDTH
            else:
                # 平台自己横移挤进角色:顺着平台推
                st.x += pr.cx - plat.pose(st.frame - 1).cx
            st.vx = 0.0
            l, r, t, b = _bounds()

    # ---- 6. 垂直积分与碰撞 ----
    dy = st.vy * FIXED_DT
    st.y += dy
    st.grounded = False
    l, r, t, b = _bounds()
    prev_top = prev_bottom - PLAYER_HEIGHT

    # 6a. 实心瓦片
    for tx, ty in _overlapping_tiles_bounds(level, l, r, t, b):
        tr_top = float(ty)
        tr_bottom = tr_top + 1.0
        l, r, t, b = _bounds()
        if not (r > float(tx) and l < float(tx) + 1.0
                and b > tr_top and t < tr_bottom):
            continue
        if st.vy >= 0 and prev_bottom <= tr_top + 1e-4:
            st.y = tr_top
            st.vy = 0.0
            st.grounded = True
            st.riding = None
            if not was_grounded:
                ev.landed.append(Landing("tile", "tile", st.x, st.y, st.frame))
        elif st.vy < 0 and prev_top >= tr_bottom - 1e-4:
            st.y = tr_bottom + PLAYER_HEIGHT
            st.vy = 0.0
        l, r, t, b = _bounds()

    # 6b. 移动平台(六面实体;从上方落到顶面则进入 riding)
    for plat in level.platforms_at_x(st.x):
        pr = plat.pose(st.frame)
        l, r, t, b = _bounds()
        if not (r > pr.left and l < pr.right and b > pr.top and t < pr.bottom):
            continue
        pvx, pvy = plat.velocity_at(st.frame)
        if st.vy >= 0 and prev_bottom <= pr.top + 1e-4:
            st.y = pr.top
            st.vy = 0.0
            st.grounded = True
            st.riding = plat.id
            st.vx += pvx  # 站立瞬间继承平台水平速度,起跳时带走
            if not was_grounded:
                ev.landed.append(Landing("platform", plat.id, st.x, st.y, st.frame))
        elif st.vy < 0 and prev_top >= pr.bottom - 1e-4:
            st.y = pr.bottom + PLAYER_HEIGHT
            st.vy = 0.0
        elif pvy > 0 and prev_bottom <= pr.top + 1e-4:
            # 平台向上托举接住
            st.y = pr.top
            st.vy = 0.0
            st.grounded = True
            st.riding = plat.id
            if not was_grounded:
                ev.landed.append(Landing("platform", plat.id, st.x, st.y, st.frame))
        l, r, t, b = _bounds()

    # 6c. 弹簧(单向,只在从上方越过顶面时触发)
    for spring in level.springs_at_x(st.x):
        sr = spring.rect
        l, r, t, b = _bounds()
        if (
            r > sr.left and l < sr.right
            and st.vy >= 0
            and prev_bottom <= sr.top + 1e-4
            and b >= sr.top
        ):
            st.y = sr.top
            st.vy = -cfg.spring_velocity
            st.grounded = False
            st.riding = None
            # 弹簧把空中动作刷新:弹起后仍可二段跳
            st.air_jumps_left = cfg.max_air_jumps
            if not was_grounded:
                land = Landing("spring", "spring", st.x, st.y, st.frame)
                ev.landed.append(land)
                ev.spring_bounces.append(land)

    # ---- 7. 危险物 / 出界 ----
    l, r, t, b = _bounds()
    body = Rect(l, t, r - l, b - t)
    for hz in level.hazards_at_x(st.x):
        if body.overlaps(hz.rect):
            st.dead = True
            st.death_reason = f"hazard:{hz.kind}"
            ev.deaths.append(st.death_reason)
            return ev
    if st.y > level.height + 5.0:
        st.dead = True
        st.death_reason = "fell_out_of_world"
        ev.deaths.append(st.death_reason)
        return ev
    if st.x < -1.0 or st.x > level.width + 1.0:
        st.dead = True
        st.death_reason = "left_world_side"
        ev.deaths.append(st.death_reason)
        return ev

    # ---- 8. 土狼时间 / 二段跳余量 ----
    if st.grounded:
        st.coyote = cfg.coyote_frames
        st.air_jumps_left = cfg.max_air_jumps
    else:
        if was_grounded and st.coyote == 0:
            st.coyote = cfg.coyote_frames
        st.coyote = max(0, st.coyote - 1)

    # 收集品触碰(供实测对照;分析器另有几何判定)
    body = st.body()
    for c in level.collectibles_at_x(st.x):
        if _circle_hits_rect(c.x, c.y, c.radius, body):
            ev.touched_collectibles.append(c.id)
    return ev


def _circle_hits_rect(cx: float, cy: float, r: float, rect: Rect) -> bool:
    nx = min(max(cx, rect.left), rect.right)
    ny = min(max(cy, rect.top), rect.bottom)
    dx = cx - nx
    dy = cy - ny
    return dx * dx + dy * dy <= r * r + 1e-12


# ---------------------------------------------------------------------------
# 便捷驱动器:按一串输入跑完整段,返回轨迹(测试 / 实测对照用)
# ---------------------------------------------------------------------------

@dataclass
class Trajectory:
    states: list[PlayerState]
    events: list[StepEvents]

    @property
    def last(self) -> PlayerState:
        return self.states[-1]


def run_inputs(level: Level, inputs: list[JumpInput],
               start: PlayerState | None = None) -> Trajectory:
    st = start or make_spawn_state(level)
    states = [st]
    events: list[StepEvents] = []
    for inp in inputs:
        ev = step(level, st, inp)
        states.append(st)
        events.append(ev)
    return Trajectory(states, events)
