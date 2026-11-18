"""生成百屏规模的性能压测关卡(100 屏 × 18 高)。

布局:每屏一个由地面台阶 + 高台 + 少量收集品组成的房间,房间之间用
高度差 ≤ 2 格、水平间距 ≤ 3.5 格的跳跃连接,保证全程可达;
再放几个移动平台和弹簧覆盖全部机制。生成结果写入 levels/perf_100.json。
"""

from __future__ import annotations

import json
from pathlib import Path

SCREENS = 100
SCREEN_W = 20
H = 18
W = SCREENS * SCREEN_W


def build() -> dict:
    rows = [["."] * W for _ in range(H)]
    collectibles = []
    platforms = []
    springs = []
    hazards = []

    # 全程贯通的地面,但每屏留一个缺口(必须小跳越过),缺口下是尖刺
    floor_y = H - 1
    for x in range(W):
        rows[floor_y][x] = "#"
    for s in range(SCREENS):
        gap_x = s * SCREEN_W + 14
        rows[floor_y][gap_x] = "."
        hazards.append({"x": float(gap_x), "y": floor_y + 0.5,
                        "width": 1.0, "height": 0.5, "kind": "spike"})
        # 每屏一个高台(2 格高,3 格宽),放在房间中部
        px = s * SCREEN_W + 6
        for dx in range(3):
            rows[floor_y - 2][px + dx] = "#"
            rows[floor_y - 1][px + dx] = "#"
        # 收集品:高台上方(可达)
        collectibles.append({
            "id": f"c{s:03d}",
            "x": float(px + 1),
            "y": float(floor_y - 2.8),
            "radius": 0.4,
        })

    # 每 10 屏放一组移动平台(水平 + 垂直交替),周期取小值控制联合周期
    for s in range(5, SCREENS, 10):
        bx = s * SCREEN_W + 10
        if (s // 10) % 2 == 0:
            platforms.append({
                "id": f"plat_h{s}",
                "x": float(bx), "y": float(floor_y - 4),
                "width": 3.0, "height": 0.5,
                "axis": "x", "amplitude": 2.0,
                "period_frames": 120, "motion": "triangle",
            })
        else:
            platforms.append({
                "id": f"plat_v{s}",
                "x": float(bx), "y": float(floor_y - 1),
                "width": 3.0, "height": 0.5,
                "axis": "y", "amplitude": -3.0,
                "period_frames": 90, "motion": "triangle",
            })

    # 每 20 屏一个弹簧,弹起高度足够碰到额外收集品
    for s in range(2, SCREENS, 20):
        sx = s * SCREEN_W + 3
        springs.append({"x": float(sx), "y": float(floor_y - 0.5),
                        "width": 1.0, "height": 0.5})
        collectibles.append({
            "id": f"c_spring{s:03d}",
            "x": float(sx + 0.5),
            "y": float(floor_y - 6.0),
            "radius": 0.4,
        })

    return {
        "name": f"perf_{SCREENS}_screens",
        "bounds": {"width": W, "height": H},
        "spawn": {"x": 1.5, "y": float(floor_y)},
        "goal": {"x": float(W - 1.5), "y": float(floor_y)},
        "rows": ["".join(r) for r in rows],
        "collectibles": collectibles,
        "platforms": platforms,
        "springs": springs,
        "hazards": hazards,
    }


def main() -> None:
    data = build()
    out = Path(__file__).resolve().parents[1] / "levels" / "perf_100.json"
    out.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {out} ({data['bounds']['width']}x{data['bounds']['height']}, "
          f"{len(data['collectibles'])} collectibles, "
          f"{len(data['platforms'])} platforms)")


if __name__ == "__main__":
    main()
