"""关卡数据模型与 JSON 加载。

关卡 JSON 格式(单位均为格, y 向上):

{
  "name": "level-01",
  "grid": [                // 可选, 字符串数组, 第一行是最上面一行
    "########",
    "#......#",
    "#..C...#",
    "#S....G#",
    "########"
  ],                       // 字符: '#'实心  'S'出生点  'C'收集品  'G'终点  '^'弹簧(默认冲量)
  "platforms": [{"x":0,"y":0,"w":8,"h":1}],   // 可选, 实心矩形(光栅化进格子)
  "moving_platforms": [{                      // 可选, 移动平台
     "id":"m1", "x":10, "y":3, "w":2, "h":0.5,
     "path":[[16,3]],                         // 依次经过的路点(绝对坐标, 起点为 x,y)
     "period":4.0                             // 往返周期(秒)
  }],
  "springs": [{"x":5,"y":1,"impulse":24}],    // 可选, 弹簧(可覆盖默认冲量)
  "collectibles": [{"id":"c1","x":6,"y":4,"radius":0.5}],
  "goal": {"x":14,"y":1,"w":1,"h":2},         // 终点区域(也可用 'G' 格)
  "spawn": {"x":1.5,"y":1}                    // 出生点(脚底位置, 也可用 'S' 格)
}
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field

import numpy as np


@dataclass
class Surface:
    """一段可站立的静态顶面。"""

    sid: int
    x0: float   # 左端(含)
    x1: float   # 右端(不含)
    y: float    # 顶面高度

    @property
    def width(self) -> float:
        return self.x1 - self.x0


@dataclass
class MovingPlatform:
    """移动平台: 沿路点折线匀速往返(ping-pong), period 为往返周期(秒)。"""

    pid: str
    w: float
    h: float
    period: float
    waypoints: list          # list[(x, y)] 左下角绝对坐标
    xs: np.ndarray = None    # 每个 tick 的左下角 x, 长度 = P
    ys: np.ndarray = None
    top_surface: int = -1    # 兼容字段, 未用

    @property
    def ticks(self) -> int:
        return len(self.xs)

    def pos(self, g: int) -> tuple[float, float]:
        i = g % len(self.xs)
        return float(self.xs[i]), float(self.ys[i])

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        """运动范围包围盒 (x0, y0, x1, y1), 含自身尺寸。"""
        return (float(self.xs.min()), float(self.ys.min()),
                float(self.xs.max()) + self.w, float(self.ys.max()) + self.h)

    def build_cache(self, tick_rate: int) -> None:
        """按物理帧率预计算每个 tick 的位置。"""
        P = max(2, round(self.period * tick_rate))
        pts = [(float(x), float(y)) for x, y in self.waypoints]
        if len(pts) == 1:
            pts = pts * 2
        # 折线段长度
        segs = []
        total = 0.0
        for a, b in zip(pts, pts[1:]):
            L = math.hypot(b[0] - a[0], b[1] - a[1])
            segs.append((a, b, L))
            total += L
        if total <= 0:
            pts = [pts[0], pts[0]]
            segs = [(pts[0], pts[0], 0.0)]
            total = 0.0
        xs = np.empty(P)
        ys = np.empty(P)
        for g in range(P):
            # ping-pong: 一个周期走 2*total
            d = (g / P) * 2.0 * total
            if d > total:
                d = 2.0 * total - d
            # 沿线插值
            x, y = pts[0]
            acc = 0.0
            for a, b, L in segs:
                if L <= 0:
                    continue
                if d <= acc + L or (a, b, L) is segs[-1]:
                    t = 0.0 if L <= 0 else (d - acc) / L
                    t = min(max(t, 0.0), 1.0)
                    x = a[0] + (b[0] - a[0]) * t
                    y = a[1] + (b[1] - a[1]) * t
                    break
                acc += L
            xs[g] = x
            ys[g] = y
        self.xs = xs
        self.ys = ys

    def build_catch_map(self) -> dict:
        """构建"被落上"的相位位图: dict[(kx, ky)] -> int 位掩码。

        键是 0.5 格分辨率的格子键(覆盖平台顶面 ±0.5 格容差),
        值的第 g 位为 1 表示平台在第 g tick(相位)顶面覆盖该键。
        """
        P = len(self.xs)
        bits: dict[tuple[int, int], int] = {}
        offs = np.arange(-0.25, self.w + 0.26, 0.5)
        for g in range(P):
            top = float(self.ys[g]) + self.h
            ky = int(round(top * 2.0))
            bx = float(self.xs[g])
            bit = 1 << g
            for off in offs:
                kx = int(round((bx + float(off)) * 2.0))
                for dky in (-1, 0, 1):
                    key = (kx, ky + dky)
                    bits[key] = bits.get(key, 0) | bit
        return bits


@dataclass
class Collectible:
    cid: str
    x: float
    y: float
    radius: float = 0.5


class Level:
    """光栅化后的关卡。"""

    def __init__(self, name: str, width: int, height: int):
        self.name = name
        self.width = width
        self.height = height
        self.solid = np.zeros((height, width), dtype=bool)
        self.spring = np.zeros((height, width), dtype=np.float64)   # 冲量, 0=无, -1=用默认
        self.goal_grid = np.zeros((height, width), dtype=bool)
        self.surf_id = np.full((height, width), -1, dtype=np.int32)  # 实心格 -> 其顶面 surface id
        self.surfaces: list[Surface] = []
        self.moving: list[MovingPlatform] = []
        self.collectibles: list[Collectible] = []
        self.spawn: tuple[float, float] = (1.5, 1.0)
        self.has_goal = False

    # ---- 查询 ----
    def solid_at(self, x: float, y: float) -> bool:
        c = math.floor(x)
        r = math.floor(y)
        if c < 0 or c >= self.width or r < 0 or r >= self.height:
            return False
        return bool(self.solid[r, c])

    def spring_at(self, x: float, y: float) -> float:
        c = math.floor(x)
        r = math.floor(y)
        if c < 0 or c >= self.width or r < 0 or r >= self.height:
            return 0.0
        return float(self.spring[r, c])

    # ---- 构建 ----
    def finalize(self, default_spring_impulse: float, tick_rate: int) -> None:
        """填充完内容后调用: 解析默认弹簧冲量, 提取顶面, 预计算移动平台。"""
        self.spring[self.spring < 0] = default_spring_impulse
        self._extract_surfaces()
        for m in self.moving:
            m.build_cache(tick_rate)

    def _extract_surfaces(self) -> None:
        H, W = self.solid.shape
        sid = 0
        for r in range(H):
            c = 0
            while c < W:
                if self.solid[r, c] and (r + 1 >= H or not self.solid[r + 1, c]):
                    c0 = c
                    while c < W and self.solid[r, c] and (
                        r + 1 >= H or not self.solid[r + 1, c]
                    ):
                        self.surf_id[r, c] = sid
                        c += 1
                    self.surfaces.append(Surface(sid, float(c0), float(c), float(r + 1)))
                    sid += 1
                else:
                    c += 1

    # ---- JSON ----
    @classmethod
    def from_json(cls, path: str) -> "Level":
        with open(path, "r", encoding="utf-8") as f:
            return cls.from_dict(json.load(f))

    @classmethod
    def from_dict(cls, d: dict) -> "Level":
        grid = d.get("grid")
        if grid:
            H = len(grid)
            W = max(len(row) for row in grid)
        else:
            # 由内容推断尺寸
            maxx, maxy = 10.0, 5.0
            for r in d.get("platforms", []):
                maxx = max(maxx, r["x"] + r["w"])
                maxy = max(maxy, r["y"] + r["h"])
            for m in d.get("moving_platforms", []):
                for x, y in [ (m["x"], m["y"]) ] + [tuple(p) for p in m.get("path", [])]:
                    maxx = max(maxx, x + m.get("w", 2) + 2)
                    maxy = max(maxy, y + 3)
            for c in d.get("collectibles", []):
                maxx = max(maxx, c["x"] + 2)
                maxy = max(maxy, c["y"] + 2)
            g = d.get("goal")
            if g:
                maxx = max(maxx, g["x"] + g.get("w", 1) + 1)
                maxy = max(maxy, g["y"] + g.get("h", 2) + 1)
            s = d.get("spawn")
            if s:
                maxx = max(maxx, s["x"] + 2)
                maxy = max(maxy, s["y"] + 2)
            W = int(math.ceil(maxx)) + 2
            H = int(math.ceil(maxy)) + 4
        lv = cls(d.get("name", "level"), W, H)

        # 1) 字符网格(第一行最上)
        if grid:
            for i, rowstr in enumerate(grid):
                r = H - 1 - i
                for c, ch in enumerate(rowstr):
                    if ch == "#":
                        lv.solid[r, c] = True
                    elif ch == "S":
                        lv.spawn = (c + 0.5, float(r))
                    elif ch == "C":
                        lv.collectibles.append(
                            Collectible(f"c{len(lv.collectibles)}", c + 0.5, r + 0.5)
                        )
                    elif ch == "G":
                        lv.goal_grid[r, c] = True
                        lv.has_goal = True
                    elif ch == "^":
                        lv.spring[r, c] = -1.0  # 默认冲量, finalize 时解析

        # 2) 实心矩形
        for rct in d.get("platforms", []):
            x, y, w, h = rct["x"], rct["y"], rct["w"], rct["h"]
            c0 = int(math.floor(x))
            c1 = int(math.ceil(x + w)) - 1
            r0 = int(math.floor(y))
            r1 = int(math.ceil(y + h)) - 1
            for r in range(max(0, r0), min(H - 1, r1) + 1):
                for c in range(max(0, c0), min(W - 1, c1) + 1):
                    lv.solid[r, c] = True

        # 3) 弹簧
        for s in d.get("springs", []):
            c = int(math.floor(s["x"]))
            r = int(math.floor(s["y"]))
            if 0 <= r < H and 0 <= c < W:
                lv.spring[r, c] = float(s.get("impulse", -1.0))

        # 4) 移动平台
        for m in d.get("moving_platforms", []):
            wps = [(float(m["x"]), float(m["y"]))]
            wps += [(float(px), float(py)) for px, py in m.get("path", [])]
            lv.moving.append(
                MovingPlatform(
                    pid=str(m.get("id", f"m{len(lv.moving)}")),
                    w=float(m.get("w", 2.0)),
                    h=float(m.get("h", 0.5)),
                    period=float(m["period"]),
                    waypoints=wps,
                )
            )

        # 5) 收集品
        for cdt in d.get("collectibles", []):
            lv.collectibles.append(
                Collectible(
                    str(cdt.get("id", f"c{len(lv.collectibles)}")),
                    float(cdt["x"]),
                    float(cdt["y"]),
                    float(cdt.get("radius", 0.5)),
                )
            )

        # 6) 终点矩形
        g = d.get("goal")
        if g:
            c0 = int(math.floor(g["x"]))
            c1 = int(math.ceil(g["x"] + g.get("w", 1))) - 1
            r0 = int(math.floor(g["y"]))
            r1 = int(math.ceil(g["y"] + g.get("h", 2))) - 1
            for r in range(max(0, r0), min(H - 1, r1) + 1):
                for c in range(max(0, c0), min(W - 1, c1) + 1):
                    lv.goal_grid[r, c] = True
            lv.has_goal = True

        # 7) 出生点
        s = d.get("spawn")
        if s:
            lv.spawn = (float(s["x"]), float(s["y"]))
        return lv
