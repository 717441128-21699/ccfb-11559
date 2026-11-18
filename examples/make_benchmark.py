"""生成 100 屏基准关卡(与性能测试同款), 用于手工体验检查速度。

用法: py examples/make_benchmark.py [屏数] > benchmark.json
"""
import json
import sys

SCREEN_W = 40
HEIGHT = 24


def make(screens: int = 100) -> dict:
    W = screens * SCREEN_W
    floor = ["#"] * W
    platforms, springs, moving, coins = [], [], [], []
    for s in range(screens):
        b = s * SCREEN_W
        if s % 10 == 9:
            for c in range(b + 10, b + 30):
                floor[c] = "."
            moving.append({"id": f"m{s}", "x": b + 12, "y": 0.5, "w": 2, "h": 0.5,
                           "path": [[b + 26, 0.5]], "period": 4.0})
            coins.append({"id": f"ride{s}", "x": b + 19, "y": 1.6, "radius": 0.5})
        else:
            for c in range(b + 18, b + 22):
                floor[c] = "."
            if s % 4 == 0:
                coins.append({"id": f"arc{s}", "x": b + 19.5, "y": 2.8, "radius": 0.6})
        platforms.append({"x": b + 6, "y": 2, "w": 4, "h": 1})
        coins.append({"id": f"plat{s}", "x": b + 8, "y": 3.4, "radius": 0.5})
        if s % 8 == 3 and s % 10 != 9:
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


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    json.dump(make(n), sys.stdout, ensure_ascii=False)
    print()
