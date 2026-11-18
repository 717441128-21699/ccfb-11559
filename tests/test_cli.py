"""命令行接口测试:退出码、JSON 输出、CI 集成契约。"""

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEVELS = ROOT / "levels"


class CliTests(unittest.TestCase):
    def _run(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "levelcheck", *args],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8")

    def test_passing_level_exit_zero(self):
        p = self._run(str(LEVELS / "level_1_1_basic.json"))
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("通过", p.stdout)

    def test_unreachable_level_exit_two(self):
        p = self._run(str(LEVELS / "level_1_2_unreachable.json"))
        self.assertEqual(p.returncode, 2)
        self.assertIn("不可达", p.stdout)

    def test_json_output_machine_readable(self):
        p = self._run(str(LEVELS / "level_1_1_basic.json"), "--json")
        self.assertEqual(p.returncode, 0)
        payload = json.loads(p.stdout)
        self.assertEqual(payload["schema_version"], 1)
        self.assertTrue(payload["ok"])
        self.assertIn("goal", payload)
        self.assertIn("collectibles", payload)
        self.assertLessEqual(payload["elapsed_seconds"],
                             payload["performance_budget_seconds"])
        # 半格精度承诺写进 JSON 契约
        self.assertEqual(payload["landing_error_guarantee_tiles"], 0.5)

    def test_missing_file_exit_three(self):
        p = self._run("no_such_level.json")
        self.assertEqual(p.returncode, 3)

    def test_markdown_output(self):
        p = self._run(str(LEVELS / "level_1_1_basic.json"), "--md")
        self.assertEqual(p.returncode, 0)
        self.assertIn("# 关卡通关检查", p.stdout)


if __name__ == "__main__":
    unittest.main()
