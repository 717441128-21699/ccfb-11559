"""命令行入口。

用法::

    py -m levelcheck <关卡.json>                 # 中文终端报告
    py -m levelcheck <关卡.json> --json          # CI 用 JSON
    py -m levelcheck <关卡.json> --md -o r.md    # 写 Markdown 报告
    py -m levelcheck <关卡.json> --budget 10     # 自定义性能预算(秒)

退出码:
    0  通过(终点 + 全部收集品可达)
    2  关卡可解析但存在不可达目标
    3  关卡数据不合法 / 分析超时 / 平台联合周期超限
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .analyzer import AnalyzerTimeout, LevelCycleError, analyze_level
from .level import LevelError, load_level
from .report import render_json, render_markdown, render_text, write_report


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="levelcheck",
        description="2D 平台跳跃关卡通关静态校验:可达性 / 收集品 / 移动平台节拍",
    )
    p.add_argument("level", help="编辑器导出的关卡 JSON 文件")
    p.add_argument("--json", action="store_true", help="输出 JSON(CI 用)")
    p.add_argument("--md", action="store_true", help="输出 Markdown")
    p.add_argument("-o", "--output", help="把报告写入文件而非 stdout")
    p.add_argument("--budget", type=float, default=10.0,
                   help="分析耗时预算(秒),默认 10")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    level_path = Path(args.level)

    # ---- 阶段 1:解析与结构自检 ----
    try:
        level = load_level(level_path)
    except LevelError as e:
        if args.json:
            import json
            print(json.dumps({"ok": False, "fatal": {
                "code": e.code, "message": e.message}}, ensure_ascii=False, indent=2))
        else:
            print(f"❌ 关卡数据不合法:[{e.code}] {e.message}", file=sys.stderr)
        return 3
    except FileNotFoundError:
        print(f"❌ 找不到关卡文件: {level_path}", file=sys.stderr)
        return 3

    # ---- 阶段 2:可达性分析 ----
    try:
        result = analyze_level(level, deadline_seconds=args.budget)
    except (AnalyzerTimeout, LevelCycleError) as e:
        print(f"❌ 分析失败: {e}", file=sys.stderr)
        return 3

    # ---- 阶段 3:渲染 ----
    if args.json:
        text = render_json(result)
    elif args.md:
        text = render_markdown(result, str(level_path))
    else:
        text = render_text(result, str(level_path))

    if args.output:
        fmt = "json" if args.json else ("md" if args.md else "txt")
        write_report(result, args.output, fmt)
        print(f"报告已写入 {args.output}")
    else:
        print(text)
    return 0 if result.ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
