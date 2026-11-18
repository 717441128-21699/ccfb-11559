"""物理常数与纯数学工具。

所有距离以"格(tile)"为单位,时间以 60Hz 固定步长的"帧(frame)"为单位,
y 轴向下为正。游戏运行时与静态分析器都引用这里的常数,两边物理必然一致。

默认参数是一组手感常见的平台跳跃数值(策划可在关卡 JSON 的 physics 段覆盖):
    满跑速 6 格/秒,起跳初速 12.5 格/秒(向上),重力 36 格/秒²
    → 满跳高度约 2.17 格,滞空 41 帧,满跑水平跨度约 4.1 格。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

#: 固定模拟步长:游戏与分析器都按 60Hz 积分,不随帧率变化
FIXED_DT = 1.0 / 60.0
#: 一格的像素数(仅用于报告里换算像素,模拟内部全部用格)
TILE_PIXELS = 32
#: 角色碰撞盒(格)。宽 0.75、高 1.75,脚底中心为角色定位点
PLAYER_HALF_WIDTH = 0.375
PLAYER_HEIGHT = 1.75
#: 分析器允许的跳跃落点与实测落点偏差上限(格):需求为半格
MAX_LANDING_ERROR = 0.5
#: 落脚点横向分桶粒度(格)。0.25 格一个起跳桶,误差远小于半格
FOOT_BUCKET = 0.25


@dataclass(frozen=True)
class PhysicsConfig:
    """角色物理参数,关卡 JSON 的 ``physics`` 段可整体覆盖默认值。"""

    run_speed: float = 6.0            # 满跑速,格/秒
    ground_accel: float = 60.0        # 地面加速度,格/秒²
    air_accel: float = 40.0           # 空中水平加速度,格/秒²
    jump_velocity: float = 12.5       # 起跳初速(向上,故 vy 为负),格/秒
    gravity: float = 36.0             # 重力加速度(向下),格/秒²
    coyote_time: float = 0.10         # 土狼时间,秒(6 帧)
    max_air_jumps: int = 1            # 二段跳次数(1 = 一次二段跳)
    air_jump_velocity: float = 11.0   # 二段跳初速,格/秒
    jump_cut_ratio: float = 0.45      # 短跳:松开跳跃键后上升速度截断系数
    spring_velocity: float = 19.0     # 弹簧弹射初速,格/秒
    max_fall_speed: float = 20.0      # 终端下落速度,格/秒
    step_up: float = 0.0              # 自动上台阶高度(0 = 关闭)

    # ---- 派生量,统一在一处算,避免各处手写出错 ----
    @property
    def coyote_frames(self) -> int:
        return int(round(self.coyote_time / FIXED_DT))

    def full_jump_height(self) -> float:
        """满跳最大上升高度(格),与固定步长积分器逐项一致的离散公式。

        半隐式欧拉下第 n 帧位置(向上为负)::

            y(n) = -n·v0·dt + 0.5·g·dt²·n·(n-1)

        顶点帧 n* = v0/(g·dt) + 0.5,离散最大高度即 -min(y(n))。
        连续解 v²/2g 仅作手感参考,见 :meth:`continuous_jump_height`。
        """
        n_star = self.jump_velocity / (self.gravity * FIXED_DT) + 0.5
        n = max(1, int(round(n_star)))
        dt = FIXED_DT
        return n * self.jump_velocity * dt - 0.5 * self.gravity * dt * dt * n * (n - 1)

    def continuous_jump_height(self) -> float:
        """连续解析解高度 v²/2g(手感参考,与实测有一个步长量级的差)。"""
        return self.jump_velocity * self.jump_velocity / (2.0 * self.gravity)

    def full_jump_frames(self) -> int:
        """满跳从起跳到回到起跳高度的滞空帧数(离散)。"""
        # y(n)=0 → n=0 或 n = 2·v0/(g·dt)+1
        flight = 2.0 * self.jump_velocity / (self.gravity * FIXED_DT) + 1.0
        return int(round(flight))

    def discrete_spring_height(self) -> float:
        """弹簧弹射的离散最大高度(格)。"""
        n_star = self.spring_velocity / (self.gravity * FIXED_DT) + 0.5
        n = max(1, int(round(n_star)))
        dt = FIXED_DT
        return n * self.spring_velocity * dt - 0.5 * self.gravity * dt * dt * n * (n - 1)

    def spring_height(self) -> float:
        """弹簧弹射最大高度(连续解,格)。"""
        return self.spring_velocity * self.spring_velocity / (2.0 * self.gravity)


# ---------------------------------------------------------------------------
# 抛物线解析解 —— 分析器用它给静态地形做快速拦截判定,
# 积分器(simulate.step)是唯一的"事实来源";这里的解析公式仅用于加速,
# tests 里有专门用例验证两者偏差 <= MAX_LANDING_ERROR。
# ---------------------------------------------------------------------------

def jump_apex_frame(v0: float, gravity: float) -> float:
    """以初速 v0(向上为负)起跳后到达顶点的帧号。"""
    return -v0 / (gravity * FIXED_DT)


def vertical_position(v0: float, gravity: float, frame: int) -> float:
    """起跳后第 frame 帧的纵向位移(向上为负):y = v0*t + 0.5*g*t²。"""
    t = frame * FIXED_DT
    return v0 * t + 0.5 * gravity * t * t


def horizontal_position(vx: float, frame: int) -> float:
    """匀速水平位移(满跑后水平方向不再加速,见 simulate 的输入策略)。"""
    return vx * frame * FIXED_DT


def frames_to_reach_height(v0: float, gravity: float, dy: float) -> int | None:
    """从起跳点纵向到达相对高度 dy(向下为正)所需的最少帧数。

    无解(跳不到那么高)时返回 None。用于快速排除够不着的高台。
    """
    # dy = v0*t + 0.5*g*t²  →  0.5*g*t² + v0*t - dy = 0
    a = 0.5 * gravity
    b = v0
    c = -dy
    disc = b * b - 4.0 * a * c
    if disc < 0.0:
        return None
    t = (-b + math.sqrt(disc)) / (2.0 * a)  # 取下落段交点(正根)
    if t < 0.0:
        return None
    return int(math.ceil(t / FIXED_DT - 1e-9))


def max_clear_height(v0: float, gravity: float) -> float:
    """该起跳初速能越过的最大高度(正值,格)。"""
    return v0 * v0 / (2.0 * gravity)


def lcm_int(values: list[int]) -> int:
    """整数最小公倍数,用于求所有移动平台的联合周期。"""
    result = 1
    for v in values:
        result = result * v // math.gcd(result, v)
    return result
