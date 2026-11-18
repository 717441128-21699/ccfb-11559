"""静态地形可达性: 缺口 / 高台 / 二段跳 / 弹簧 / 土狼时间 / 藏坏的收集品。"""
from levelcheck import Level, PhysicsParams, check_level


def run(grid, name="t", **phys):
    lv = Level.from_dict({"name": name, "grid": grid})
    p = PhysicsParams(**phys)
    lv.finalize(p.spring_impulse, p.tick_rate)
    return check_level(lv, p)


def test_flat_goal_reachable():
    rep = run([
        "##############",
        "#............#",
        "#S.........G.#",
        "##############",
    ])
    assert rep.goal_reachable
    assert rep.verdict == "pass"


def test_small_gap_reachable():
    rep = run([
        "##################",
        "#................#",
        "#S..............G#",
        "#####...##########",
    ])
    assert rep.goal_reachable


def test_huge_gap_unreachable():
    # 12 格缺口, 最大射程约 7.5 格(含二段跳约 11)仍不够
    rep = run([
        "########################",
        "#......................#",
        "#S....................G#",
        "#####............#######",
    ], double_jump=False)
    assert not rep.goal_reachable
    assert rep.verdict == "fail"


def test_hidden_collectible_on_too_high_platform():
    """上周事故的回归测试: 收集品放在跳不上去的平台上 -> 必须被单列出来。"""
    rep = run([
        "########################",
        "#......................#",
        "#......C...............#",
        "#.....###..............#",
        "#......................#",
        "#......................#",
        "#......................#",
        "#......................#",
        "#S..................G..#",
        "########################",
    ], name="stuck")
    assert rep.verdict == "fail"
    assert rep.goal_reachable  # 终点能到, 问题只在收集品
    assert len(rep.unreachable_collectibles) == 1
    c = rep.unreachable_collectibles[0]
    assert c["id"] == "c0" and abs(c["x"] - 7.5) < 0.01 and abs(c["y"] - 7.5) < 0.01


def test_collectible_on_reachable_platform():
    # 平台 3 格高(单段跳 3.27 格), 收集品可达
    rep = run([
        "########################",
        "#......................#",
        "#......................#",
        "#......................#",
        "#......................#",
        "#......C...............#",
        "#.....###..............#",
        "#S..................G..#",
        "########################",
    ])
    assert rep.verdict == "pass"
    assert rep.collectibles_reachable == 1


def test_double_jump_required():
    grid = [
        "########################",
        "#......................#",
        "#......................#",
        "#.....................G#",
        "#...................####",
        "#......................#",
        "#......................#",
        "#S.....................#",
        "########################",
    ]
    # 平台顶高 5 格: 单段 3.27 不够, 单段+二段 5.67 够
    assert run(grid, double_jump=True).goal_reachable
    assert not run(grid, double_jump=False).goal_reachable


def test_spring_reaches_high_platform():
    # 助跑跳跃落在弹簧上(x≈10), 弹起 8.07 格, 借势落到右上方 8 格高的平台
    grid = [
        "########################",
        "#......................#",
        "#............G.........#",
        "#...........####.......#",
        "#......................#",
        "#......................#",
        "#......................#",
        "#......................#",
        "#......................#",
        "#S........^............#",
        "########################",
    ]
    rep = run(grid, double_jump=False)
    assert rep.goal_reachable


def test_coyote_time_makes_gap():
    # 8 格缺口(关闭二段跳): 走出边缘直接跳射程约 7.5 不够;
    # 土狼时间 0.1s 允许离缘约 0.8 格后再起跳, 射程约 8.3 够
    grid = [
        "##############################",
        "#............................#",
        "#............................#",
        "#............................#",
        "#............................#",
        "#............................#",
        "#S..........................G#",
        "##########........############",
    ]
    assert run(grid, coyote_time=0.1, double_jump=False).goal_reachable
    assert not run(grid, coyote_time=0.01, double_jump=False).goal_reachable
