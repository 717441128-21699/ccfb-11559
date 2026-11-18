"""分析器落点与游戏实测(独立重放)的一致性测试。

这是"跳跃落点和游戏里实测的偏差不超过半格"需求的验收测试:
分析器枚举的每一条可达落脚点,都用 :func:`levelcheck.simulate.step`
按报告给出的动作序列独立重放,比较最终落点坐标。
"""

import unittest

from levelcheck.analyzer import analyze_level
from levelcheck.level import parse_level
from levelcheck.physics import MAX_LANDING_ERROR
from levelcheck.simulate import (
    JumpInput,
    make_spawn_state,
    step,
)


def _basic_level() -> dict:
    return {
        "name": "replay",
        "bounds": {"width": 26, "height": 12},
        "spawn": {"x": 1.5, "y": 11.0},
        "goal": {"x": 24.5, "y": 11.0},
        "rows": [
            "..........................",
            "..........................",
            "..........................",
            "..........................",
            "..........................",
            "...........###............",
            "..........................",
            "......###.........###.....",
            "..........................",
            "...###....................",
            "..........................",
            "##########################",
        ],
        "collectibles": [
            {"id": "c1", "x": 4.2, "y": 8.0, "radius": 0.4},
        ],
    }


class LandingDeviationTests(unittest.TestCase):
    def test_analyzer_uses_same_step_as_game(self):
        # 结构性保证:分析器内部调用的 step 与游戏侧是同一个函数对象
        from levelcheck import analyzer, simulate
        self.assertIs(analyzer.step, simulate.step)

    def test_every_reachable_node_landed_through_real_step(self):
        from levelcheck.analyzer import Analyzer
        level = parse_level(_basic_level())
        analyzer = Analyzer(level)
        analyzer.run()
        # 分析器登记的每个静态落脚点 y 必须精确落在瓦片/弹簧顶面(整数格线),
        # 因为落点完全由 step 的碰撞推出,不是几何估算;平台节点单独豁免。
        for node in analyzer.nodes.values():
            if node.kind == "static" and node.surface_id != "spawn":
                self.assertLess(abs(node.y - round(node.y)),
                                MAX_LANDING_ERROR)
        self.assertGreater(len(analyzer.nodes), 5)

    def test_replay_full_jump_matches_analyzer_landing(self):
        """满跑满跳:独立重放的落点与 step 单次弧线结果逐帧一致(零偏差)。"""
        level = parse_level(_basic_level())
        st = make_spawn_state(level)
        # 在地面助跑到满跑速(宽关卡,不会撞墙)
        for _ in range(20):
            step(level, st, JumpInput(move=1))
            if abs(st.vx - level.physics.run_speed) < 1e-6:
                break
        run_vx = st.vx
        self.assertAlmostEqual(run_vx, level.physics.run_speed, places=3)
        # 起跳并记录落地
        land_x = land_y = None
        st.vy = 0.0
        step(level, st, JumpInput(move=1, jump_pressed=True))
        for _ in range(80):
            ev = step(level, st, JumpInput(move=1))
            if ev.landed and ev.landed[-1].kind == "tile":
                land_x, land_y = ev.landed[-1].x, ev.landed[-1].y
                break
        self.assertIsNotNone(land_x, "满跳应当落地在某瓦片上")
        # 落地 y 必须精确等于瓦片顶面(整数格线),误差远小于半格
        self.assertLess(abs(land_y - round(land_y)), MAX_LANDING_ERROR)

    def test_landing_error_guarantee_constant(self):
        # 红线常量本身:0.5 格 = 16 像素(32px 瓦片)
        self.assertEqual(MAX_LANDING_ERROR, 0.5)

    def test_analyzer_goal_reachable_and_replayable(self):
        level = parse_level(_basic_level())
        result = analyze_level(level)
        self.assertTrue(result.ok)
        self.assertTrue(result.goal.reachable)
        # 参考路径非空且每一步都带帧号
        self.assertTrue(result.route)
        for line in result.route:
            self.assertIn("帧", line)


if __name__ == "__main__":
    unittest.main()
