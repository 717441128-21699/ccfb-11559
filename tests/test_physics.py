"""物理常数与积分器一致性测试。

核心承诺:分析器与游戏实测共用同一个 step(),这里用离散解析公式
独立校验积分器的跳跃高度 / 滞空帧数,确保物理常数与积分严格对应。
"""

import unittest

from levelcheck.level import parse_level
from levelcheck.physics import FIXED_DT, PhysicsConfig
from levelcheck.simulate import (
    JumpInput,
    make_spawn_state,
    step,
)


def _flat_level(width: int = 12, floor_y: int = 10) -> dict:
    rows = ["." * width for _ in range(floor_y)] + ["#" * width]
    return {
        "name": "flat",
        "bounds": {"width": width, "height": floor_y + 1},
        "spawn": {"x": 2.0, "y": float(floor_y)},
        "goal": {"x": float(width - 2), "y": float(floor_y)},
        "rows": rows,
    }


class PhysicsConsistencyTests(unittest.TestCase):
    def setUp(self):
        self.level = parse_level(_flat_level())
        self.cfg = self.level.physics

    def test_full_jump_height_matches_discrete_formula(self):
        st = make_spawn_state(self.level)
        start_y = st.y
        # 第一帧起跳,之后只保持右移、不松跳跃键(满跳)
        apex_y = start_y
        for f in range(60):
            jump = f == 0
            step(self.level, st, JumpInput(move=0, jump_pressed=jump,
                                           jump_held=True))
            apex_y = min(apex_y, st.y)
            if st.grounded and f > 2:
                break
        sim_height = start_y - apex_y
        formula = self.cfg.full_jump_height()
        self.assertAlmostEqual(sim_height, formula, places=6,
                               msg="积分器跳跃高度必须与离散公式逐项一致")

    def test_double_jump_resets_air_action(self):
        st = make_spawn_state(self.level)
        self.assertEqual(st.air_jumps_left, self.cfg.max_air_jumps)
        # 第 1 帧地面跳(不消耗空中余量)。地面跳后土狼窗口仍残留几帧,
        # 期间按跳走土狼分支;等窗口耗尽后再按才是二段跳。
        step(self.level, st, JumpInput(jump_pressed=True))
        self.assertEqual(st.air_jumps_left, self.cfg.max_air_jumps)
        self.assertFalse(st.grounded)
        # 空转到土狼窗口耗尽,再按下二段跳
        for _ in range(self.cfg.coyote_frames + 1):
            step(self.level, st, JumpInput())
        self.assertEqual(st.air_jumps_left, self.cfg.max_air_jumps)
        step(self.level, st, JumpInput(jump_pressed=True))
        self.assertEqual(st.air_jumps_left, self.cfg.max_air_jumps - 1)
        # 落地后余量刷新
        for _ in range(60):
            step(self.level, st, JumpInput())
            if st.grounded:
                break
        self.assertEqual(st.air_jumps_left, self.cfg.max_air_jumps)

    def test_coyote_window_allows_late_jump(self):
        st = make_spawn_state(self.level)
        # 走出边缘(往右走到悬空),在土狼窗口内仍可起跳
        for _ in range(3):
            step(self.level, st, JumpInput(move=1))
        # 走到地板边缘外
        st.x = 10.2
        st.grounded = False
        st.coyote = self.cfg.coyote_frames
        before_vy = st.vy
        step(self.level, st, JumpInput(jump_pressed=True))
        self.assertAlmostEqual(st.vy, -self.cfg.jump_velocity, places=6)
        self.assertNotEqual(st.vy, before_vy)

    def test_terminal_velocity_capped(self):
        st = make_spawn_state(self.level)
        st.grounded = False
        for _ in range(200):
            step(self.level, st, JumpInput())
        self.assertLessEqual(st.vy, self.cfg.max_fall_speed + 1e-9)

    def test_gravity_constant_is_si_consistent(self):
        # 60Hz 下一帧重力增量 = g/60。把角色放到真正的空中(远离任何表面),
        # 避免出生点贴地时第一帧即被落地逻辑吸附。
        st = make_spawn_state(self.level)
        st.y = 3.0
        st.grounded = False
        st.riding = None
        st.coyote = 0
        st.vy = 0.0
        step(self.level, st, JumpInput())
        self.assertAlmostEqual(st.vy, self.cfg.gravity * FIXED_DT, places=9)


if __name__ == "__main__":
    unittest.main()
