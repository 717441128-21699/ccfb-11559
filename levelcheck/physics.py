"""角色物理参数、跳跃轨迹模板、参考物理积分器。

坐标约定:
    单位 = 格(tile), y 轴向上, 角色位置指**脚底中心**。
    关卡用格子(grid)表示, 格子 (col, row) 覆盖区域 [col, col+1) x [row, row+1)。

积分器(与游戏运行时一致的固定步长半隐式欧拉):
    每 tick 顺序:
      1. 应用该 tick 的跳跃事件(起跳/二段跳/弹簧, 直接设置 vy)
      2. vy -= g*dt, 并限制最大下落速度
      3. 水平移动; 若脚底进入实心格则取消本次水平移动(撞墙)
      4. 垂直移动; 上升时若头顶进入实心格则 vy=0(顶头);
         下落时若脚底进入实心格则落地(吸附到格顶);
         下落时若脚底进入弹簧格则 vy=弹簧冲量(弹起)

检查器的高速批量模拟器(sim.py)与本参考积分器逐步语义完全一致,
测试中用本积分器作为"游戏实测"基准, 要求落点偏差 <= 0.5 格。
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Sequence


@dataclass
class PhysicsParams:
    """角色物理参数。速度单位: 格/秒; 重力: 格/秒^2。"""

    run_speed: float = 8.0            # 跑动最大速度
    jump_velocity: float = 14.0       # 起跳初速(竖直向上)
    gravity: float = 30.0             # 重力加速度
    coyote_time: float = 0.1          # 土狼时间(离开边缘后仍可起跳的宽限), 秒
    double_jump: bool = True          # 是否允许二段跳
    double_jump_velocity: float = 12.0
    tick_rate: int = 60               # 物理帧率
    max_fall_speed: float = 25.0      # 最大下落速度
    player_height: float = 0.9        # 角色身高(顶头判定用)
    spring_impulse: float = 22.0      # 默认弹簧冲量(关卡可单独覆盖)
    max_flight_time: float = 10.0     # 单条轨迹最大模拟时长, 秒

    @property
    def dt(self) -> float:
        return 1.0 / self.tick_rate

    @property
    def coyote_ticks(self) -> int:
        return max(1, round(self.coyote_time * self.tick_rate))

    @property
    def max_ticks(self) -> int:
        return int(self.max_flight_time * self.tick_rate)

    @property
    def max_jump_height(self) -> float:
        """单段跳最大高度(解析解)。"""
        return self.jump_velocity ** 2 / (2.0 * self.gravity)

    @property
    def max_total_height(self) -> float:
        """含二段跳的最大高度(在顶点接二段跳的解析上界)。"""
        h = self.max_jump_height
        if self.double_jump:
            h += self.double_jump_velocity ** 2 / (2.0 * self.gravity)
        return h

    @property
    def max_range(self) -> float:
        """水平最大射程的宽松上界(空间剪枝用)。"""
        air = 2.0 * self.jump_velocity / self.gravity
        if self.double_jump:
            air += 2.0 * self.double_jump_velocity / self.gravity
        return self.run_speed * air + 2.0

    @classmethod
    def from_dict(cls, d: dict) -> "PhysicsParams":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})

    @classmethod
    def from_json(cls, path: str) -> "PhysicsParams":
        with open(path, "r", encoding="utf-8") as f:
            return cls.from_dict(json.load(f))

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


@dataclass(frozen=True)
class Template:
    """跳跃轨迹模板: 一串 (tick, vy) 事件, 到时刻直接把 vy 设为给定值。

    edge_only=True 的模板(坠落/土狼类)只从平台边缘生成。
    """

    name: str
    events: tuple  # tuple[tuple[int, float], ...] 按 tick 升序, 至多 2 个
    edge_only: bool


# 起跳水平速度采样(占跑速的比例)。落点覆盖对这些采样平移不变性良好。
VX_FACTORS = (-1.0, -0.5, 0.0, 0.5, 1.0)


def build_templates(p: PhysicsParams) -> list[Template]:
    """根据物理参数生成轨迹模板集合。

    - jump:            原地/跑动起跳
    - double@d:        起跳后第 d tick 接二段跳(d 采样覆盖整个上升段)
    - fall:            走出边缘自然坠落
    - coyote:          走出边缘 c tick(土狼时间)内起跳
    - coyote+double@d: 土狼起跳后再接二段跳
    """
    tpls: list[Template] = [Template("jump", ((0, p.jump_velocity),), False)]
    if p.double_jump:
        for d in range(6, 38, 4):
            tpls.append(
                Template(
                    f"double@{d}",
                    ((0, p.jump_velocity), (d, p.double_jump_velocity)),
                    False,
                )
            )
    tpls.append(Template("fall", (), True))
    c = p.coyote_ticks
    tpls.append(Template("coyote", ((c, p.jump_velocity),), True))
    if p.double_jump:
        for d in range(6, 34, 8):
            tpls.append(
                Template(
                    f"coyote+double@{d}",
                    ((c, p.jump_velocity), (c + d, p.double_jump_velocity)),
                    True,
                )
            )
    return tpls


@dataclass
class JumpResult:
    landed: bool
    x: float
    y: float
    col: int          # 落地实心格 col, 未落地为 -1
    row: int          # 落地实心格 row, 未落地为 -1
    ticks: int
    path: list        # list[(x, y)] 每 tick 末位置(含起点)


def simulate_reference(level, p: PhysicsParams, x0: float, y0: float,
                       vx: float, template: Template, y_min: float = -10.0) -> JumpResult:
    """单条轨迹的朴素逐步模拟 —— 作为"游戏实测"基准。

    批量模拟器(sim.py)必须与本函数在相同输入下给出偏差 <= 0.5 格的落点。
    y_min: 低于该高度判定掉出世界(标准弧线分析时传 -inf 类值)。
    """
    x, y, vy = float(x0), float(y0), 0.0
    events = dict(template.events)
    dt = p.dt
    bounces = 0
    path = [(x, y)]
    for n in range(p.max_ticks):
        if n in events:
            vy = events[n]
        vy = max(vy - p.gravity * dt, -p.max_fall_speed)
        nx = x + vx * dt
        if level.solid_at(nx, y):
            nx = x
        x = nx
        ny = y + vy * dt
        if vy > 0.0 and level.solid_at(x, ny + p.player_height):
            vy = 0.0
            ny = y
        elif vy < 0.0:
            if level.solid_at(x, ny):
                row = math.floor(ny)
                return JumpResult(True, x, row + 1.0, math.floor(x), row, n + 1, path)
            imp = level.spring_at(x, ny)
            if imp > 0.0 and bounces < 8:
                vy = imp
                bounces += 1
        y = ny
        path.append((x, y))
        if y < y_min:
            break
    return JumpResult(False, x, y, -1, -1, p.max_ticks, path)
