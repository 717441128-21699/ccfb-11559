"""命令行入口: python -m levelcheck check <level.json> [--physics p.json] [--json out.json]

退出码: 0 = 可以通关(终点可达且所有收集品可达), 1 = 不可通关, 2 = 用法/文件错误。
编辑器集成: "检查"按钮调用本命令, 按退出码亮绿灯/红灯, --json 输出供编辑器内嵌展示。
"""
from __future__ import annotations

import argparse
import json
import sys

from .level import Level
from .physics import PhysicsParams
from .reachability import check_level


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="levelcheck",
        description="平台跳跃关卡可通关性检查: 找出够不着的收集品和终点",
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="检查一个关卡")
    c.add_argument("level", help="关卡 JSON 文件")
    c.add_argument("--physics", default=None, help="物理参数 JSON(缺省用内置默认值)")
    c.add_argument("--json", dest="json_out", default=None, help="把机器可读报告写到该文件")
    c.add_argument("--time-budget", type=float, default=10.0,
                   help="检查时间预算(秒), 默认 10")
    args = ap.parse_args(argv)

    try:
        level = Level.from_json(args.level)
        p = PhysicsParams.from_json(args.physics) if args.physics else PhysicsParams()
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as e:
        print(f"读取输入失败: {e}", file=sys.stderr)
        return 2

    level.finalize(p.spring_impulse, p.tick_rate)
    rep = check_level(level, p, time_budget=args.time_budget)
    print(rep.format_text())
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(rep.to_dict(), f, ensure_ascii=False, indent=2)
    return 0 if rep.verdict == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
