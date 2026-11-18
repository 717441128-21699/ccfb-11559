"""可达性场景测试:正常关 / 不可达收集品(事故回归)/ 弹簧 / 移动平台。"""

import unittest

from levelcheck.analyzer import analyze_level
from levelcheck.level import LevelError, parse_level


class UnreachableCollectibleTests(unittest.TestCase):
    """复刻上周事故:隐藏收集品放在任何弧线都到不了的高台。"""

    def _level(self) -> dict:
        return {
            "name": "regression",
            "bounds": {"width": 18, "height": 12},
            "spawn": {"x": 1.5, "y": 11.0},
            "goal": {"x": 16.5, "y": 11.0},
            "rows": [
                "..................",
                "..................",
                "..................",
                ".........###......",
                "..................",
                "..................",
                "..................",
                "..................",
                "..................",
                "....###...........",
                "..................",
                "##################",
            ],
            "collectibles": [
                {"id": "c_bad", "x": 10.0, "y": 2.6, "radius": 0.4},
                {"id": "c_ok", "x": 5.0, "y": 9.0, "radius": 0.4},
            ],
        }

    def test_unreachable_collectible_flagged(self):
        result = analyze_level(parse_level(self._level()))
        self.assertFalse(result.ok)
        self.assertTrue(result.goal.reachable, "终点本身应可达")
        self.assertFalse(result.collectibles["c_bad"].reachable)
        self.assertTrue(result.collectibles["c_ok"].reachable)
        # 不可达项要给出最近落脚点距离,方便策划定位
        self.assertIsNotNone(
            result.collectibles["c_bad"].nearest_distance)

    def test_reports_nearest_distance_in_tiles(self):
        result = analyze_level(parse_level(self._level()))
        self.assertGreater(result.collectibles["c_bad"].nearest_distance, 1.0)


class SpringTests(unittest.TestCase):
    def _level(self) -> dict:
        return {
            "name": "spring",
            "bounds": {"width": 14, "height": 12},
            "spawn": {"x": 1.5, "y": 11.0},
            "goal": {"x": 12.5, "y": 11.0},
            "rows": [
                "..............",
                "..............",
                "..............",
                "..............",
                ".........###..",
                "..............",
                "..............",
                "..............",
                "..............",
                "..............",
                "..............",
                "##############",
            ],
            "springs": [{"x": 6.0, "y": 10.5, "width": 1.0, "height": 0.5}],
            "collectibles": [
                # 弹簧弹起高度足够碰到的收集品
                {"id": "c_high", "x": 6.5, "y": 5.5, "radius": 0.4},
            ],
        }

    def test_spring_boost_reaches_high_collectible(self):
        result = analyze_level(parse_level(self._level()))
        self.assertTrue(result.collectibles["c_high"].reachable)


class MovingPlatformTests(unittest.TestCase):
    def _level(self):
        # 直接复用已验证可达的示例关卡,避免测试夹具与样例几何漂移
        from levelcheck.level import load_level
        from pathlib import Path
        return load_level(
            Path(__file__).resolve().parents[1]
            / "levels" / "level_1_3_moving.json")

    def test_platform_chain_reaches_goal_and_emits_timing(self):
        result = analyze_level(self._level())
        self.assertTrue(result.ok)
        # 两个平台都应给出搭乘时机
        self.assertIn("lift_h", result.platform_timing)
        self.assertIn("lift_v", result.platform_timing)
        for pid in ("lift_h", "lift_v"):
            self.assertTrue(result.platform_timing[pid])
            t = result.platform_timing[pid][0]
            self.assertGreaterEqual(t.phase, 0)
            self.assertIn("帧", t.catch_note)


class LevelValidationTests(unittest.TestCase):
    def test_platform_path_colliding_solid_is_rejected(self):
        level = {
            "name": "bad",
            "bounds": {"width": 12, "height": 12},
            "spawn": {"x": 1.5, "y": 11.0},
            "goal": {"x": 10.5, "y": 11.0},
            "rows": ["." * 12 for _ in range(11)] + ["#" * 12],
            "platforms": [
                # 平台轨道直接穿过一堵实心墙
                {"id": "p", "x": 4.0, "y": 5.0, "width": 2.0, "height": 0.5,
                 "axis": "x", "amplitude": 5.0, "period_frames": 60,
                 "motion": "triangle"},
            ],
        }
        # 在轨道上放墙
        rows = level["rows"]
        rows[5] = "........####"
        with self.assertRaises(LevelError) as ctx:
            parse_level(level)
        self.assertEqual(ctx.exception.code, "platform_path_collides")

    def test_duplicate_collectible_id_rejected(self):
        level = {
            "name": "dup",
            "bounds": {"width": 8, "height": 8},
            "spawn": {"x": 1.0, "y": 7.0},
            "goal": {"x": 6.0, "y": 7.0},
            "rows": ["........"] * 7 + ["########"],
            "collectibles": [
                {"id": "x", "x": 2.0, "y": 6.0},
                {"id": "x", "x": 3.0, "y": 6.0},
            ],
        }
        with self.assertRaises(LevelError) as ctx:
            parse_level(level)
        self.assertEqual(ctx.exception.code, "duplicate_id")


if __name__ == "__main__":
    unittest.main()
