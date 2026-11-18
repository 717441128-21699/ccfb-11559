"""收集品判定: 站立面邻近 / 跳跃弧线经过 / 乘移动平台。"""
from levelcheck import Level, PhysicsParams, check_level

P = PhysicsParams()


def run(d, name="t"):
    d.setdefault("name", name)
    lv = Level.from_dict(d)
    lv.finalize(P.spring_impulse, P.tick_rate)
    return check_level(lv, P)


def test_coin_along_jump_arc_reachable():
    """缺口上方沿跳跃弧线的金币(不在任何站立面附近) -> 可达。"""
    rep = run({
        "platforms": [{"x": 0, "y": 0, "w": 10, "h": 1},
                      {"x": 14, "y": 0, "w": 10, "h": 1}],
        "collectibles": [{"id": "coin", "x": 12.0, "y": 2.5, "radius": 0.6}],
        "spawn": {"x": 2, "y": 1},
        "goal": {"x": 20, "y": 1, "w": 2, "h": 2},
    })
    assert rep.collectibles_reachable == 1, rep.format_text()


def test_coin_too_high_unreachable():
    """漂浮在 6.5 格高的金币(跳跃最高 5.67+1) -> 不可达。"""
    rep = run({
        "platforms": [{"x": 0, "y": 0, "w": 24, "h": 1}],
        "collectibles": [{"id": "coin", "x": 12.0, "y": 7.5, "radius": 0.5}],
        "spawn": {"x": 2, "y": 1},
        "goal": {"x": 20, "y": 1, "w": 2, "h": 2},
    })
    assert rep.collectibles_reachable == 0
    assert rep.unreachable_collectibles[0]["id"] == "coin"
    assert rep.verdict == "fail"


def test_coin_at_double_jump_apex_reachable():
    """5 格高的金币: 单段跳(3.27)够不着, 接二段跳(5.67)弧线经过 -> 可达。"""
    rep = run({
        "platforms": [{"x": 0, "y": 0, "w": 24, "h": 1}],
        "collectibles": [{"id": "coin", "x": 12.0, "y": 6.0, "radius": 0.5}],
        "spawn": {"x": 2, "y": 1},
        "goal": {"x": 20, "y": 1, "w": 2, "h": 2},
    })
    assert rep.collectibles_reachable == 1, rep.format_text()


def test_coin_on_moving_platform_path():
    """移动平台驮着玩家经过的金币 -> 可达(乘骑判定)。"""
    rep = run({
        "platforms": [{"x": 0, "y": 0, "w": 10, "h": 1},
                      {"x": 30, "y": 0, "w": 10, "h": 1}],
        "moving_platforms": [{"id": "m1", "x": 12, "y": 0.5, "w": 2, "h": 0.5,
                              "path": [[26, 0.5]], "period": 4.0}],
        "collectibles": [{"id": "coin", "x": 20.0, "y": 1.6, "radius": 0.5}],
        "spawn": {"x": 2, "y": 1},
        "goal": {"x": 35, "y": 1, "w": 2, "h": 2},
    })
    assert rep.collectibles_reachable == 1, rep.format_text()
    assert rep.verdict == "pass"
