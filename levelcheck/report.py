"""检查报告渲染:中文终端文本、CI 用 JSON、Markdown 三种形态。"""

from __future__ import annotations

import json
from pathlib import Path

from .analyzer import AnalysisResult, ReachRecord
from .physics import MAX_LANDING_ERROR, TILE_PIXELS


def _reach_line(name: str, rec: ReachRecord) -> str:
    if rec.reachable:
        via = "弧线途经拾取" if rec.via_arc else "落脚可达"
        frame_txt = f",第 {rec.frame} 帧({rec.frame / 60:.2f}s)" if rec.frame is not None else ""
        return f"  ✅ {name}:可达({via}{frame_txt})"
    near = (f",最近落脚点距离 {rec.nearest_distance:.2f} 格 "
            f"({rec.nearest_distance * TILE_PIXELS:.0f} 像素)"
            if rec.nearest_distance is not None else "")
    return f"  ❌ {name}:不可达{near}"


def render_text(result: AnalysisResult, level_path: str | None = None) -> str:
    """渲染给策划看的中文终端报告。"""
    title = f"关卡通关检查: {result.level_name}"
    lines: list[str] = [
        "=" * 64,
        title,
        "=" * 64,
        f"关卡文件: {level_path or '-'}",
        f"结论: {'✅ 通过,关卡可通关且收集品全部可达' if result.ok else '❌ 未通过,存在不可达目标'}",
        f"耗时: {result.elapsed_seconds:.2f}s(预算 10s)",
        f"落脚点节点: {result.nodes_visited} 个;模拟跳跃弧线: {result.arcs_simulated} 条",
        f"移动平台联合周期: {result.total_frames_cycle} 帧 "
        f"({result.total_frames_cycle / 60:.2f}s)",
        f"落点精度承诺: 与游戏实测偏差 ≤ {MAX_LANDING_ERROR} 格 "
        f"({MAX_LANDING_ERROR * TILE_PIXELS:.0f} 像素,同一物理积分器)",
        "-" * 64,
        "终点:",
        _reach_line("goal", result.goal),
        "收集品:",
    ]
    if result.collectibles:
        lines.extend(_reach_line(cid, rec)
                     for cid, rec in sorted(result.collectibles.items()))
    else:
        lines.append("  (本关无收集品)")

    if result.platform_timing:
        lines.append("-" * 64)
        lines.append("移动平台搭乘时机(给策划的节拍说明):")
        for pid, timings in sorted(result.platform_timing.items()):
            period = timings[0].period
            phases = sorted(t.phase for t in timings)
            earliest = min(timings, key=lambda t: t.frame)
            lines.append(f"  平台 {pid}(周期 {period} 帧 = {period / 60:.2f}s):")
            lines.append(f"    · 可搭乘相位: {phases[0]}..{phases[-1]}"
                         f"(共 {len(phases)} 个相位,即整周期均可找节拍跳上)")
            lines.append(f"    · 最早搭乘: {earliest.catch_note}")

    if result.route:
        lines.append("-" * 64)
        lines.append("参考通关路径(动作序列,可在编辑器回放):")
        lines.extend(f"  {step}" for step in result.route)

    if result.warnings:
        lines.append("-" * 64)
        lines.append("警告:")
        lines.extend(f"  ⚠️  {w}" for w in result.warnings)

    if result.errors:
        lines.append("-" * 64)
        lines.append("关卡数据错误:")
        for e in result.errors:
            lines.append(f"  ❌ [{e.get('code')}] {e.get('message')}")

    lines.append("=" * 64)
    return "\n".join(lines)


def _record_to_dict(rec: ReachRecord) -> dict:
    return {
        "reachable": rec.reachable,
        "frame": rec.frame,
        "time_seconds": round(rec.frame / 60.0, 3) if rec.frame is not None else None,
        "via_arc": rec.via_arc,
        "nearest_distance_tiles": (round(rec.nearest_distance, 3)
                                   if rec.nearest_distance is not None else None),
    }


def render_json(result: AnalysisResult) -> str:
    """渲染给 CI / 编辑器消费的机器可读 JSON。"""
    payload = {
        "schema_version": 1,
        "level_name": result.level_name,
        "ok": result.ok,
        "elapsed_seconds": round(result.elapsed_seconds, 3),
        "performance_budget_seconds": 10,
        "nodes_visited": result.nodes_visited,
        "arcs_simulated": result.arcs_simulated,
        "platform_cycle_frames": result.total_frames_cycle,
        "landing_error_guarantee_tiles": MAX_LANDING_ERROR,
        "goal": _record_to_dict(result.goal),
        "collectibles": {cid: _record_to_dict(rec)
                         for cid, rec in sorted(result.collectibles.items())},
        "platform_timing": {
            pid: [{"phase": t.phase, "frame": t.frame,
                   "period": t.period, "note": t.catch_note}
                  for t in timings]
            for pid, timings in sorted(result.platform_timing.items())
        },
        "route": result.route,
        "warnings": result.warnings,
        "errors": result.errors,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def render_markdown(result: AnalysisResult, level_path: str | None = None) -> str:
    """渲染 Markdown 摘要,适合贴到关卡评审单 / PR 评论。"""
    status = "✅ 通过" if result.ok else "❌ 未通过"
    lines = [
        f"# 关卡通关检查 — {result.level_name}",
        "",
        f"- **结论**:{status}",
        f"- 关卡文件:`{level_path or '-'}`",
        f"- 分析耗时:{result.elapsed_seconds:.2f}s / 预算 10s",
        f"- 落脚节点 {result.nodes_visited} 个,模拟弧线 {result.arcs_simulated} 条",
        f"- 落点精度:与实测偏差 ≤ {MAX_LANDING_ERROR} 格(同一物理积分器)",
        "",
        "## 目标可达性",
        "",
        "| 目标 | 结果 | 到达帧 | 时间 | 最近距离(格) |",
        "| --- | --- | --- | --- | --- |",
    ]
    g = result.goal
    g_time = f"{g.frame / 60:.2f}s" if g.frame is not None else "-"
    g_near = (f"{g.nearest_distance:.2f}"
              if g.nearest_distance is not None else "-")
    lines.append(
        f"| 终点 | {'✅' if g.reachable else '❌'} | "
        f"{g.frame if g.frame is not None else '-'} | {g_time} | {g_near} |"
    )
    for cid, rec in sorted(result.collectibles.items()):
        lines.append(
            f"| {cid} | {'✅' if rec.reachable else '❌'} | "
            f"{rec.frame if rec.frame is not None else '-'} | "
            f"{(str(round(rec.frame / 60, 2)) + 's') if rec.frame is not None else '-'} | "
            f"{round(rec.nearest_distance, 2) if rec.nearest_distance is not None else '-'} |"
        )
    if result.platform_timing:
        lines += ["", "## 移动平台搭乘时机", ""]
        for pid, timings in sorted(result.platform_timing.items()):
            phases = sorted({t.phase for t in timings})
            lines.append(f"- **{pid}**:可搭乘相位 {phases}")
            for t in timings[:6]:
                lines.append(f"  - {t.catch_note}")
    if result.route:
        lines += ["", "## 参考通关路径", ""]
        lines += [f"1. {s}" if i == 0 else f"{i + 1}. {s}"
                  for i, s in enumerate(result.route)]
    if result.warnings:
        lines += ["", "## 警告", ""] + [f"- ⚠️ {w}" for w in result.warnings]
    if result.errors:
        lines += ["", "## 数据错误", ""] + [
            f"- ❌ [{e.get('code')}] {e.get('message')}" for e in result.errors]
    return "\n".join(lines) + "\n"


def write_report(result: AnalysisResult, out_path: str | Path,
                 fmt: str = "json") -> None:
    path = Path(out_path)
    if fmt == "json":
        path.write_text(render_json(result), encoding="utf-8")
    elif fmt == "md":
        path.write_text(render_markdown(result), encoding="utf-8")
    else:
        path.write_text(render_text(result), encoding="utf-8")
