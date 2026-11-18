"""移动平台: 起跳时机窗口的正确性(对照暴力穷举)与链路可达性。"""
from levelcheck import Level, PhysicsParams, check_level
from levelcheck.physics import build_templates, simulate_reference, Template
from levelcheck.reachability import expand_sources, _catch_window

P_PHYS = PhysicsParams()


def make_level(with_platform=True):
    d = {
        "name": "gap",
        "platforms": [{"x": 0, "y": 0, "w": 10, "h": 1},
                      {"x": 30, "y": 0, "w": 10, "h": 1}],
        "spawn": {"x": 2, "y": 1},
        "goal": {"x": 35, "y": 1, "w": 2, "h": 2},
    }
    if with_platform:
        d["moving_platforms"] = [{
            "id": "m1", "x": 12, "y": 0.5, "w": 2, "h": 0.5,
            "path": [[26, 0.5]], "period": 4.0,
        }]
    lv = Level.from_dict(d)
    lv.finalize(P_PHYS.spring_impulse, P_PHYS.tick_rate)
    return lv


def test_goal_requires_platform():
    assert check_level(make_level(True), P_PHYS).goal_reachable
    assert not check_level(make_level(False), P_PHYS).goal_reachable


def test_launch_window_matches_brute_force():
    """检查器给出的起跳相位窗口 vs 逐相位暴力模拟, 不一致率 <= 5%(边界模糊)。"""
    lv = make_level(True)
    m = lv.moving[0]
    P = m.ticks
    templates = build_templates(P_PHYS)

    # 检查器窗口(内部接口, 直接取位图)
    bits, _ = _catch_window(lv, P_PHYS, templates, m, [(0.0, 10.0, 1.0)])
    assert bits != 0

    # 暴力: 每个起跳相位, 用参考积分器模拟全部轨迹, 逐 tick 对平台位置
    tr = expand_sources([(0.0, 10.0, 1.0)], P_PHYS, templates)
    brute = 0
    for i in range(len(tr["x0"])):
        ev = {}
        if tr["ev1_tick"][i] >= 0:
            ev[int(tr["ev1_tick"][i])] = float(tr["ev1_val"][i])
        if tr["ev2_tick"][i] >= 0:
            ev[int(tr["ev2_tick"][i])] = float(tr["ev2_val"][i])
        tpl = Template("t", tuple(sorted(ev.items())), False)
        r = simulate_reference(lv, P_PHYS, tr["x0"][i], tr["y0"][i], tr["vx"][i], tpl)
        path = r.path
        for tau0 in range(P):
            for n in range(1, len(path)):
                px, py = path[n]
                g = (tau0 + n) % P
                mx, my = m.pos(g)
                if (mx - 0.25 <= px <= mx + m.w + 0.25
                        and abs(py - (my + m.h)) <= 0.5 and py < path[n - 1][1]):
                    brute |= 1 << tau0
                    break

    diff = bin(bits ^ brute).count("1")
    assert diff / P <= 0.05, f"窗口不一致率 {diff / P:.1%} 超过 5%"
    # 窗口必须在可达一侧存在(平台靠近左岸时才能落上去)
    assert bits != 0 and brute != 0


def test_window_reported_in_text():
    rep = check_level(make_level(True), P_PHYS)
    assert rep.moving_windows, "报告应包含移动平台起跳窗口"
    w = rep.moving_windows[0]
    assert w["platform"] == "m1"
    assert w["windows"], "应给出具体起跳时间窗口"
    for a, b in w["windows"]:
        assert 0.0 <= a < b <= w["period"] + 0.02
    text = rep.format_text()
    assert "移动平台起跳时机" in text and "m1" in text


def test_chained_moving_platforms():
    """两个移动平台接力: 岸 -> m1 -> m2 -> 对岸。"""
    lv = Level.from_dict({
        "name": "chain",
        "platforms": [{"x": 0, "y": 0, "w": 8, "h": 1},
                      {"x": 42, "y": 0, "w": 8, "h": 1}],
        "moving_platforms": [
            {"id": "m1", "x": 9, "y": 0.5, "w": 2, "h": 0.5,
             "path": [[18, 0.5]], "period": 3.0},
            {"id": "m2", "x": 24, "y": 0.5, "w": 2, "h": 0.5,
             "path": [[33, 0.5]], "period": 3.0},
        ],
        "spawn": {"x": 2, "y": 1},
        "goal": {"x": 45, "y": 1, "w": 2, "h": 2},
    })
    lv.finalize(P_PHYS.spring_impulse, P_PHYS.tick_rate)
    rep = check_level(lv, P_PHYS)
    assert rep.goal_reachable
    assert not rep.unreachable_platforms
