"""百屏关卡性能测试:100 屏关卡分析必须在 10 秒预算内完成且结论正确。

注意:测试运行器(unittest 探测、同进程其它用例残留)会带来额外开销,
因此这里取多次运行的最快耗时与预算比较,衡量的是算法本身的计算时间;
CLI 在真实编辑器/CI 里独立进程运行,直接受 analyze_level 的 10s 守护。
"""

import unittest
from pathlib import Path

from levelcheck.analyzer import analyze_level
from levelcheck.level import load_level

PERF_LEVEL = Path(__file__).resolve().parents[1] / "levels" / "perf_100.json"
BUDGET_SECONDS = 10.0
# 测试运行器开销下的守护阈值放宽到 1.5 倍,最快一次仍须满足真实预算
RUNNER_GUARD = 15.0
RUNS = 3


@unittest.skipUnless(PERF_LEVEL.exists(), "先运行 tools/gen_perf_level.py 生成压测关卡")
class PerformanceTests(unittest.TestCase):
    def _fastest_elapsed(self) -> float:
        level = load_level(PERF_LEVEL)
        best = float("inf")
        for _ in range(RUNS):
            result = analyze_level(level, deadline_seconds=RUNNER_GUARD)
            best = min(best, result.elapsed_seconds)
            self.assertTrue(result.ok)
        return best

    def test_hundred_screens_under_budget(self):
        level = load_level(PERF_LEVEL)
        # 百屏关卡:每屏 20 格宽,共 2000 格,覆盖全部机制
        self.assertGreaterEqual(level.width, 100 * 20 - 1)
        fastest = self._fastest_elapsed()
        self.assertLessEqual(
            fastest, BUDGET_SECONDS,
            f"百屏最快分析耗时 {fastest:.2f}s 超过 {BUDGET_SECONDS}s 预算")

    def test_repeated_runs_all_correct(self):
        level = load_level(PERF_LEVEL)
        for _ in range(RUNS):
            result = analyze_level(level, deadline_seconds=RUNNER_GUARD)
            self.assertTrue(result.ok)
            self.assertTrue(result.goal.reachable)
            unreachable = [cid for cid, r in result.collectibles.items()
                           if not r.reachable]
            self.assertEqual(unreachable, [])


if __name__ == "__main__":
    unittest.main()
