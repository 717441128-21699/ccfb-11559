"""批量模拟器 vs 参考积分器(游戏实测)的落点精度测试。

指标: 落点偏差 <= 0.5 格。两者共享同一套逐 tick 语义, 期望偏差为 0,
该测试主要防止向量化实现引入索引/时序错误。
"""
import numpy as np
import pytest

from levelcheck import Level, PhysicsParams
from levelcheck.physics import build_templates, simulate_reference, VX_FACTORS
from levelcheck.sim import simulate_batch

# 混合地形: 高台 / 墙 / 弹簧 / 坑
GRID = [
    "##############################",
    "#............................#",
    "#............................#",
    "#..........####..............#",
    "#............................#",
    "#....................####....#",
    "#.....####...................#",
    "#............................#",
    "#..^.........................#",
    "#######...####.....####...####",
]

P = PhysicsParams()


def make_level():
    lv = Level.from_dict({"name": "acc", "grid": GRID})
    lv.finalize(P.spring_impulse, P.tick_rate)
    return lv


def batch_single(level, x0, y0, vx, tpl):
    e1 = tpl.events[0] if len(tpl.events) > 0 else (-1, 0.0)
    e2 = tpl.events[1] if len(tpl.events) > 1 else (-1, 0.0)
    res = simulate_batch(
        level, P,
        np.array([x0]), np.array([y0]), np.array([vx]),
        np.array([e1[0]]), np.array([e1[1]]),
        np.array([e2[0]]), np.array([e2[1]]),
    )
    return res


def cases():
    level = make_level()
    templates = build_templates(P)
    out = []
    # 从地面和左侧高台上, 用各种模板/速度起跳
    for x0, y0 in [(2.5, 1.0), (7.0, 1.0), (13.5, 1.0), (6.5, 7.0), (24.0, 1.0)]:
        for tpl in templates:
            for f in VX_FACTORS:
                out.append((level, x0, y0, f * P.run_speed, tpl))
    return out


@pytest.mark.parametrize("level,x0,y0,vx,tpl", cases())
def test_batch_matches_reference(level, x0, y0, vx, tpl):
    ref = simulate_reference(level, P, x0, y0, vx, tpl)
    got = batch_single(level, x0, y0, vx, tpl)
    assert bool(got.landed[0]) == ref.landed, (
        f"落地状态不一致 tpl={tpl.name} vx={vx} 起=({x0},{y0})"
    )
    if ref.landed:
        dx = abs(got.land_x[0] - ref.x)
        dy = abs(got.land_y[0] - ref.y)
        assert dx <= 0.5 and dy <= 0.5, (
            f"落点偏差 ({dx:.3f},{dy:.3f}) 超过半格 tpl={tpl.name} vx={vx}"
        )
