"""关卡数据模型、JSON 解析与格式自检。

关卡 JSON(编辑器导出)结构::

    {
      "name": "1-1",
      "bounds": {"width": 100, "height": 20},
      "physics": { ...可选,覆盖默认物理常数... },
      "spawn":      {"x": 1.5, "y": 18.0},   # 角色脚底中心
      "goal":       {"x": 98.0, "y": 18.0},  # 终点中心(脚底线)
      "rows":       ["....", "####"],        # '#' 实心瓦片,其余空气
      "solid_tiles": [[3, 4]],               # 也可直接给瓦片坐标(与 rows 二选一/叠加)
      "springs":    [{"x": 10, "y": 18.5, "width": 1, "height": 0.5}],
      "platforms":  [{"id": "p1", "x": 20, "y": 15, "width": 3, "height": 0.5,
                      "axis": "x", "amplitude": 4, "period_frames": 120,
                      "phase_frames": 0, "motion": "triangle"}],
      "hazards":    [{"x": 5, "y": 19.5, "width": 2, "height": 0.5, "kind": "spike"}],
      "collectibles":[{"id": "c1", "x": 12.0, "y": 17.0, "radius": 0.4}]
    }

坐标系:原点在左上角,x 向右、y 向下,单位为格。
矩形(弹簧/平台/危险物)的 x,y 是左上角;spawn/goal/收集品的 x,y 是中心
(其中 spawn/goal 的 y 是脚底线,收集品的 y 是悬浮中心)。
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

from .physics import PhysicsConfig, TILE_PIXELS


class LevelError(ValueError):
    """关卡数据本身不合法(区别于"能解析但不可达")。

    code 为机器可读的错误码,供编辑器 / CI 精确处理。
    """

    def __init__(self, code: str, message: str):
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Rect:
    """轴对齐矩形,坐标单位格。"""

    x: float
    y: float
    w: float
    h: float

    @property
    def left(self) -> float:
        return self.x

    @property
    def right(self) -> float:
        return self.x + self.w

    @property
    def top(self) -> float:
        return self.y

    @property
    def bottom(self) -> float:
        return self.y + self.h

    @property
    def cx(self) -> float:
        return self.x + self.w * 0.5

    def overlaps(self, other: "Rect") -> bool:
        return (
            self.x < other.right
            and self.right > other.x
            and self.y < other.bottom
            and self.bottom > other.y
        )

    def contains(self, px: float, py: float) -> bool:
        return self.x <= px <= self.right and self.y <= py <= self.bottom

    def expanded(self, dx: float) -> "Rect":
        return Rect(self.x - dx, self.y - dx, self.w + 2 * dx, self.h + 2 * dx)


@dataclass(frozen=True)
class Spring:
    """弹簧:单向平台,从上方踩中时把角色以 spring_velocity 弹起。"""

    rect: Rect

    @property
    def top_y(self) -> float:
        return self.rect.top


@dataclass(frozen=True)
class MovingPlatform:
    """移动平台:沿单轴做往返周期运动。

    motion = "triangle":线性往复(常见的电梯/平移台),速度恒定、端点换向
    motion = "sine":    正弦往复,端点速度为 0
    平台在第 frame 帧的偏移 = amplitude * cycle_s(frame),cycle_s ∈ [0,1]。
    phase_frames 为初始相位偏移(帧),多平台用它错开节奏。
    """

    id: str
    rect: Rect
    axis: str                 # "x" 或 "y"
    amplitude: float          # 单程幅度,格
    period_frames: int
    phase_frames: int = 0
    motion: str = "triangle"

    def cycle_s(self, frame: int) -> float:
        """第 frame 帧的归一化行程 [0,1],0 与 1 都对应基准端点。"""
        p = ((frame + self.phase_frames) % self.period_frames) / self.period_frames
        if self.motion == "sine":
            return 0.5 * (1.0 - math.cos(2.0 * math.pi * p))
        # triangle:前半程 0→1,后半程 1→0
        return 2.0 * p if p < 0.5 else 2.0 * (1.0 - p)

    def pose(self, frame: int) -> Rect:
        """第 frame 帧平台占据的世界矩形。

        幅度带符号:y 轴平台负幅度表示向上运动(基准点为最低位),
        x 轴平台负幅度表示向左运动(基准点为最右位)。
        """
        s = self.cycle_s(frame)
        if self.axis == "x":
            return Rect(self.rect.x + self.amplitude * s, self.rect.y,
                        self.rect.w, self.rect.h)
        return Rect(self.rect.x, self.rect.y + self.amplitude * s,
                    self.rect.w, self.rect.h)

    def travel_extent(self) -> float:
        """轨迹覆盖的绝对行程(格),用于碰撞采样。"""
        return abs(self.amplitude)

    def velocity_at(self, frame: int) -> tuple[float, float]:
        """第 frame 帧平台速度(格/秒),用于把惯性传给站立的角色。"""
        p = ((frame + self.phase_frames) % self.period_frames) / self.period_frames
        if self.motion == "sine":
            # ds/dt = (π/period_seconds) * sin(2πp)
            ds = (math.pi / (self.period_frames / 60.0)) * math.sin(2.0 * math.pi * p)
        else:
            # 每半程走 amplitude(带符号),半程时长 period/2
            half = self.period_frames / 2.0 / 60.0
            speed = self.amplitude / half if half > 0 else 0.0
            ds = speed if p < 0.5 else -speed
        return (ds, 0.0) if self.axis == "x" else (0.0, ds)


@dataclass(frozen=True)
class Hazard:
    rect: Rect
    kind: str = "spike"


@dataclass(frozen=True)
class Collectible:
    id: str
    x: float
    y: float
    radius: float = 0.4


@dataclass
class Level:
    name: str
    width: int
    height: int
    physics: PhysicsConfig
    spawn: tuple[float, float]
    goal: tuple[float, float]
    solid_tiles: set[tuple[int, int]] = field(default_factory=set)
    springs: list[Spring] = field(default_factory=list)
    platforms: list[MovingPlatform] = field(default_factory=list)
    hazards: list[Hazard] = field(default_factory=list)
    collectibles: list[Collectible] = field(default_factory=list)
    tile_pixels: int = TILE_PIXELS

    def __post_init__(self) -> None:
        self._build_spatial_index()

    def _build_spatial_index(self) -> None:
        """按"列(整数 x 格)"建立空间散列,把热路径查询从 O(实体总数)
        降到 O(该列附近实体数)。平台按整条运动轨迹覆盖的列登记。"""
        self._platform_by_id: dict[str, MovingPlatform] = {
            p.id: p for p in self.platforms}
        self._platform_cols: dict[int, list[MovingPlatform]] = {}
        for p in self.platforms:
            lo = math.floor(min(p.rect.left, p.rect.left + p.amplitude))
            hi = math.floor(max(p.rect.right, p.rect.right + p.amplitude))
            for tx in range(lo, hi + 1):
                self._platform_cols.setdefault(tx, []).append(p)
        self._hazard_cols: dict[int, list[Hazard]] = {}
        for hz in self.hazards:
            for tx in range(math.floor(hz.rect.left),
                            math.floor(hz.rect.right - 1e-9) + 1):
                self._hazard_cols.setdefault(tx, []).append(hz)
        self._spring_cols: dict[int, list[Spring]] = {}
        for sp in self.springs:
            for tx in range(math.floor(sp.rect.left),
                            math.floor(sp.rect.right - 1e-9) + 1):
                self._spring_cols.setdefault(tx, []).append(sp)
        self._collect_cols: dict[int, list[Collectible]] = {}
        for c in self.collectibles:
            for tx in range(math.floor(c.x - c.radius),
                            math.floor(c.x + c.radius) + 1):
                self._collect_cols.setdefault(tx, []).append(c)

    # ---- 空间查询:只看矩形覆盖到的列,百屏关卡下平均 O(1) ----
    def _near_cols(self, cols: dict[int, list], rect: Rect) -> list:
        x0 = math.floor(rect.left)
        x1 = math.floor(rect.right - 1e-9)
        if x0 == x1:
            return cols.get(x0, ())
        seen: dict = {}
        for tx in range(x0, x1 + 1):
            for obj in cols.get(tx, ()):
                seen[id(obj)] = obj
        return list(seen.values())

    def _col_at(self, cols: dict[int, list], x: float):
        """按世界 x 直接取所在列的实体(角色宽 < 1 格时的主路径,一次 floor)。"""
        return cols.get(math.floor(x), ())

    def platforms_near(self, rect: Rect) -> list[MovingPlatform]:
        return self._near_cols(self._platform_cols, rect)

    def platforms_at_x(self, x: float):
        return self._col_at(self._platform_cols, x)

    def hazards_at_x(self, x: float):
        return self._col_at(self._hazard_cols, x)

    def springs_at_x(self, x: float):
        return self._col_at(self._spring_cols, x)

    def collectibles_at_x(self, x: float):
        return self._col_at(self._collect_cols, x)

    def hazards_near(self, rect: Rect) -> list[Hazard]:
        return self._near_cols(self._hazard_cols, rect)

    def springs_near(self, rect: Rect) -> list[Spring]:
        return self._near_cols(self._spring_cols, rect)

    def collectibles_near(self, rect: Rect) -> list[Collectible]:
        return self._near_cols(self._collect_cols, rect)

    # ---- 实心瓦片查询(热路径,用整数 set + 边界检查)----
    def solid_at(self, tx: int, ty: int) -> bool:
        return (tx, ty) in self.solid_tiles

    def solid_aabb(self, rect: Rect) -> bool:
        """矩形是否与任何实心瓦片相交。"""
        x0 = math.floor(rect.left)
        x1 = math.floor(rect.right - 1e-9)
        y0 = math.floor(rect.top)
        y1 = math.floor(rect.bottom - 1e-9)
        for ty in range(y0, y1 + 1):
            for tx in range(x0, x1 + 1):
                if (tx, ty) in self.solid_tiles:
                    return True
        return False

    def platform_by_id(self, pid: str) -> MovingPlatform | None:
        return self._platform_by_id.get(pid)

    def validate(self) -> None:
        """结构自检:数据不合法直接抛 LevelError,不进入可达性分析。"""
        if self.width <= 0 or self.height <= 0:
            raise LevelError("bad_bounds", "关卡宽高必须为正数")
        sx, sy = self.spawn
        if not (0 <= sx <= self.width and 0 <= sy <= self.height + 2):
            raise LevelError("spawn_out_of_bounds", f"出生点 {sx},{sy} 超出关卡范围")
        gx, gy = self.goal
        if not (0 <= gx <= self.width and 0 <= gy <= self.height + 2):
            raise LevelError("goal_out_of_bounds", f"终点 {gx},{gy} 超出关卡范围")
        if self._player_embedded(sx, sy):
            raise LevelError("spawn_inside_solid", f"出生点 {sx},{sy} 卡在实心瓦片中")

        ids: set[str] = set()
        for p in self.platforms:
            if p.id in ids:
                raise LevelError("duplicate_id", f"移动平台 id 重复: {p.id}")
            ids.add(p.id)
            if p.axis not in ("x", "y"):
                raise LevelError("bad_platform_axis", f"平台 {p.id} 的 axis 只能是 x/y")
            if p.period_frames <= 0:
                raise LevelError("bad_platform_period", f"平台 {p.id} 周期必须为正")
            if p.amplitude == 0:
                raise LevelError("bad_platform_amplitude",
                                 f"平台 {p.id} 幅度不能为 0(静止平台请用瓦片)")
            if p.motion not in ("triangle", "sine"):
                raise LevelError("bad_platform_motion",
                                 f"平台 {p.id} motion 只能是 triangle/sine")
            if self._platform_path_hits_solid(p):
                raise LevelError(
                    "platform_path_collides",
                    f"平台 {p.id} 的运动轨迹与实心瓦片相交,物理行为未定义,请改轨道",
                )
        for c in self.collectibles:
            if c.id in ids:
                raise LevelError("duplicate_id", f"收集品 id 重复: {c.id}")
            ids.add(c.id)
            if not (0 <= c.x <= self.width and 0 <= c.y <= self.height + 2):
                raise LevelError("collectible_out_of_bounds",
                                 f"收集品 {c.id} 超出关卡范围")
        for s in self.springs:
            if s.rect.w <= 0 or s.rect.h <= 0:
                raise LevelError("bad_spring", f"弹簧矩形非法: {s.rect}")
        for h in self.hazards:
            if h.rect.w <= 0 or h.rect.h <= 0:
                raise LevelError("bad_hazard", f"危险物矩形非法: {h.rect}")

    def _player_embedded(self, foot_x: float, foot_y: float) -> bool:
        from .physics import PLAYER_HALF_WIDTH, PLAYER_HEIGHT
        body = Rect(foot_x - PLAYER_HALF_WIDTH, foot_y - PLAYER_HEIGHT,
                    PLAYER_HALF_WIDTH * 2, PLAYER_HEIGHT)
        return self.solid_aabb(body)

    def find_ground(self, foot_x: float, foot_y: float,
                    search: float = 0.75) -> float | None:
        """在脚底下 search 格内找支撑面顶面 y。

        编辑器导出的出生点/终点常带少量垂直偏差,统一吸附到表面可避免
        "出生即嵌入地板导致穿地"。找不到返回 None。
        """
        from .physics import PLAYER_HALF_WIDTH
        # 瓦片顶:脚下小探针与瓦片相交且顶面在脚底线下方不超过 search
        probe = Rect(foot_x - PLAYER_HALF_WIDTH, foot_y - 0.01,
                     PLAYER_HALF_WIDTH * 2, search + 0.01)
        x0 = math.floor(probe.left)
        x1 = math.floor(probe.right - 1e-9)
        y0 = math.floor(foot_y - 0.01)
        y1 = math.floor(foot_y + search)
        best: float | None = None
        for ty in range(y0, y1 + 1):
            top = float(ty)
            if not (foot_y - 1e-4 <= top <= foot_y + search):
                continue
            for tx in range(x0, x1 + 1):
                if (tx, ty) in self.solid_tiles and (tx, ty - 1) not in self.solid_tiles:
                    if best is None or top < best:
                        best = top
        # 移动平台顶面
        for p in self.platforms:
            pose = p.pose(0)
            if (pose.left < foot_x + PLAYER_HALF_WIDTH
                    and pose.right > foot_x - PLAYER_HALF_WIDTH
                    and foot_y - 1e-4 <= pose.top <= foot_y + search):
                if best is None or pose.top < best:
                    best = pose.top
        return best

    def snap_to_ground(self, point: tuple[float, float],
                       label: str) -> tuple[float, float]:
        x, y = point
        ground = self.find_ground(x, y)
        if ground is None:
            return point
        if abs(ground - y) > 1e-9:
            # 偏差大于 1 格说明是真悬空点(出生门),不强行吸附
            if ground - y <= 0.75 + 1e-9:
                return x, ground
        return point

    def _platform_path_hits_solid(self, p: MovingPlatform) -> bool:
        """采样平台整段轨迹(逐帧位姿)检查是否撞进实心瓦片。"""
        steps = max(p.period_frames, int(abs(p.amplitude) * 4) + 4)
        for f in range(steps):
            frame = int(f * p.period_frames / steps)
            if self.solid_aabb(p.pose(frame)):
                return True
        return False


# ---------------------------------------------------------------------------
# JSON 解析
# ---------------------------------------------------------------------------

def _require(d: dict, key: str, ctx: str) -> object:
    if key not in d:
        raise LevelError("missing_field", f"{ctx} 缺少字段 {key}")
    return d[key]


def _as_point(d: dict, ctx: str) -> tuple[float, float]:
    if not isinstance(d, dict) or "x" not in d or "y" not in d:
        raise LevelError("bad_point", f"{ctx} 必须是包含 x/y 的对象")
    return float(d["x"]), float(d["y"])


def _as_rect(d: dict, ctx: str) -> Rect:
    for key in ("x", "y", "width", "height"):
        if key not in d:
            raise LevelError("missing_field", f"{ctx} 缺少字段 {key}")
    return Rect(float(d["x"]), float(d["y"]),
                float(d["width"]), float(d["height"]))


def parse_level(data: dict) -> Level:
    if not isinstance(data, dict):
        raise LevelError("bad_format", "关卡文件根节点必须是 JSON 对象")
    bounds = _require(data, "bounds", "关卡")
    if not isinstance(bounds, dict):
        raise LevelError("bad_bounds", "bounds 必须是对象")
    width = int(_require(bounds, "width", "bounds"))
    height = int(_require(bounds, "height", "bounds"))

    phy_data = data.get("physics", {})
    if not isinstance(phy_data, dict):
        raise LevelError("bad_physics", "physics 必须是对象")
    allowed = set(PhysicsConfig.__dataclass_fields__)  # type: ignore[attr-defined]
    unknown = set(phy_data) - allowed
    if unknown:
        raise LevelError("unknown_physics_field", f"physics 含未知字段: {sorted(unknown)}")
    physics = PhysicsConfig(**{k: float(v) if k != "max_air_jumps" else int(v)
                               for k, v in phy_data.items()})

    spawn = _as_point(_require(data, "spawn", "关卡"), "spawn")
    goal = _as_point(_require(data, "goal", "关卡"), "goal")

    tiles: set[tuple[int, int]] = set()
    rows = data.get("rows")
    if rows is not None:
        if not isinstance(rows, list) or not all(isinstance(r, str) for r in rows):
            raise LevelError("bad_rows", "rows 必须是字符串数组")
        if len(rows) > height:
            raise LevelError("bad_rows", f"rows 行数 {len(rows)} 超过关卡高度 {height}")
        for ty, row in enumerate(rows):
            for tx, ch in enumerate(row):
                if tx >= width:
                    raise LevelError("bad_rows", f"第 {ty} 行长度超过关卡宽度 {width}")
                if ch == "#":
                    tiles.add((tx, ty))
    for tx, ty in data.get("solid_tiles", []):
        tiles.add((int(tx), int(ty)))

    springs = [Spring(_as_rect(s, "spring")) for s in data.get("springs", [])]
    hazards = [
        Hazard(_as_rect(h, "hazard"), str(h.get("kind", "spike")))
        for h in data.get("hazards", [])
    ]
    collectibles: list[Collectible] = []
    for c in data.get("collectibles", []):
        if "id" not in c:
            raise LevelError("missing_field", "collectible 缺少 id")
        collectibles.append(Collectible(
            str(c["id"]), float(_require(c, "x", "collectible")),
            float(_require(c, "y", "collectible")),
            float(c.get("radius", 0.4)),
        ))

    platforms: list[MovingPlatform] = []
    for p in data.get("platforms", []):
        ctx = f"platform {p.get('id', '?')}"
        pid = str(_require(p, "id", ctx))
        platforms.append(MovingPlatform(
            id=pid,
            rect=_as_rect(p, ctx),
            axis=str(p.get("axis", "x")),
            amplitude=float(p.get("amplitude", 0.0)),
            period_frames=int(_require(p, "period_frames", ctx)),
            phase_frames=int(p.get("phase_frames", 0)),
            motion=str(p.get("motion", "triangle")),
        ))

    level = Level(
        name=str(data.get("name", "未命名关卡")),
        width=width,
        height=height,
        physics=physics,
        spawn=spawn,
        goal=goal,
        solid_tiles=tiles,
        springs=springs,
        platforms=platforms,
        hazards=hazards,
        collectibles=collectibles,
        tile_pixels=int(data.get("tile_pixels", TILE_PIXELS)),
    )
    # 出生点/终点吸附到脚下支撑面(编辑器常见的小数偏差在这里收敛)
    spawn = level.snap_to_ground(spawn, "spawn")
    goal = level.snap_to_ground(goal, "goal")
    level.spawn = spawn
    level.goal = goal
    level.validate()
    return level


def load_level(path: str | Path) -> Level:
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise LevelError("bad_json", f"{path} 不是合法 JSON: {e}") from e
    return parse_level(data)
