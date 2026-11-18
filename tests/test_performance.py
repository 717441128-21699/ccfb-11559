"""性能: 100 屏关卡 10 秒内查完(需求硬指标)。"""
import time

from levelcheck import Level, PhysicsParams, check_level

SCREEN_W = 40
HEIGHT = 24


def make_benchmark_level(screens: int = 100) -> dict:
    """生成一个可通关的 100 屏关卡: 缺口 / 浮台 / 弹簧高台 / 移动平台宽沟 / 各类收集品。"""
    W = screens * SCREEN_W
    floor = ["#"] * W
    platforms, springs, moving, coins = [], [], [], []
    for s in range(screens):
        b = s * SCREEN_W
        if s % 10 == 9:
            # 20 格宽鸿沟 + 往返移动平台
            for c in range(b + 10, b + 30):
                floor[c] = "."
            moving.append({"id": f"m{s}", "x": b + 12, "y": 0.5, "w": 2, "h": 0.5,
                           "path": [[b + 26, 0.5]], "period": 4.0})
            coins.append({"id": f"ride{s}", "x": b + 19, "y": 1.6, "radius": 0.5})
        else:
            # 4 格缺口
            for c in range(b + 18, b + 22):
                floor[c] = "."
            if s % 4 == 0:
                # 缺口上方弧线上的金币
                coins.append({"id": f"arc{s}", "x": b + 19.5, "y": 2.8, "radius": 0.6})
        # 浮台 + 台上收集品
        platforms.append({"x": b + 6, "y": 2, "w": 4, "h": 1})
        coins.append({"id": f"plat{s}", "x": b + 8, "y": 3.4, "radius": 0.5})
        if s % 8 == 3 and s % 10 != 9:
            # 弹簧 + 6 格高台 + 台上收集品(移动平台屏上弹簧四周无起跳地面, 跳过)
            springs.append({"x": b + 30, "y": 1, "impulse": 22})
            platforms.append({"x": b + 29, "y": 6, "w": 8, "h": 1})
            coins.append({"id": f"spr{s}", "x": b + 32, "y": 7.4, "radius": 0.5})
    grid = ["." * W] * (HEIGHT - 1) + ["".join(floor)]
    return {
        "name": f"benchmark-{screens}",
        "grid": grid,
        "platforms": platforms,
        "springs": springs,
        "moving_platforms": moving,
        "collectibles": coins,
        "spawn": {"x": 2, "y": 1},
        "goal": {"x": W - 4, "y": 1, "w": 2, "h": 2},
    }


def test_benchmark_100_screens_under_10s():
    p = PhysicsParams()
    lv = Level.from_dict(make_benchmark_level(100))
    lv.finalize(p.spring_impulse, p.tick_rate)
    t0 = time.perf_counter()
    rep = check_level(lv, p, time_budget=10.0)
    elapsed = time.perf_counter() - t0
    print("\n" + rep.format_text())
    # 硬指标: 100 屏 < 10 秒
    assert elapsed < 10.0, f"超时: {elapsed:.1f}s"
    assert not rep.partial
    # 关卡按可通关构造
    assert rep.goal_reachable
    assert rep.unreachable_collectibles == []
    assert rep.verdict == "pass"
    assert rep.unreachable_platforms == []
    assert len(rep.moving_windows) == 10
    # 规模 sanity check(地板跨屏合并, 表面数远少于屏数x3)
    assert rep.surfaces_total > 150
    assert rep.trajectories_simulated > 50000
