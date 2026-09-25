from helpers import make_bars

from wangtrader.core import Side, run
from wangtrader.methods.q3_03_mother_child import MotherChild

PREV = (9990, 10001, 9989, 10000)  # 平盤 10000


def test_top_mother_child_short_signal():
    bars = make_bars([
        (9990, 10030, 9985, 10020),  # M：母K，當下最高（雙重最高），紅K
        (10000, 10015, 9995, 10005),  # C：子K，懷孕於母K範圍
        (9995, 10000, 9975, 9980),   # S：黑K，收盤≤母K開盤、跌破子K低點
    ], prev_day=PREV)
    res = run(MotherChild(), bars)
    sig = res.signals[0]
    assert sig.side == Side.SHORT and sig.reason == "頂母子"
    assert sig.price == 9980 and sig.stop == 10000


def test_bottom_mother_child_long_signal():
    bars = make_bars([
        (10020, 10025, 9970, 9980),   # M：母K，當下最低（雙重最低），黑K
        (9990, 10010, 9985, 10005),   # C：子K，懷孕於母K範圍
        (9985, 10030, 9975, 10022),   # S：紅K，收盤≥母K開盤、突破子K高點
    ], prev_day=PREV)
    res = run(MotherChild(), bars)
    sig = res.signals[0]
    assert sig.side == Side.LONG and sig.reason == "底母子"
    assert sig.price == 10022 and sig.stop == 10002


def test_child_body_outside_mother_body_is_ignored():
    bars = make_bars([
        (9990, 10030, 9985, 10020),  # M
        (10000, 10015, 9995, 10025),  # C：實體高點10025超出母K實體高點10020
        (9995, 10000, 9975, 9980),   # S
    ], prev_day=PREV)
    assert run(MotherChild(), bars).signals == []


def test_child_ties_mother_high_is_ignored():
    bars = make_bars([
        (9990, 10030, 9985, 10020),  # M
        (10000, 10030, 9995, 10005),  # C：最高點與母K相等
        (9995, 10000, 9975, 9980),   # S
    ], prev_day=PREV)
    assert run(MotherChild(), bars).signals == []


def test_mother_only_highest_high_not_highest_close_is_ignored():
    bars = make_bars([
        (9990, 10010, 9985, 10005),  # 前一峰點：收盤較高
        (9990, 10030, 9985, 9995),   # M候選：最高點最高，但收盤非最高收盤
        (9990, 10015, 9970, 9998),   # C
        (9995, 10000, 9950, 9960),   # S
    ], prev_day=PREV)
    assert run(MotherChild(), bars).signals == []


def test_signal_bar_wick_breach_without_close_confirm_is_ignored():
    bars = make_bars([
        (9990, 10030, 9985, 10020),  # M
        (10000, 10015, 9995, 10005),  # C
        (9995, 10000, 9970, 9992),   # S：低點跌破母K開盤9990，但收盤9992未真正≤9990
    ], prev_day=PREV)
    assert run(MotherChild(), bars).signals == []


def test_not_extreme_position_is_ignored():
    bars = make_bars([
        (9998, 10005, 9995, 10003),  # M：範圍極小
        (10000, 10004, 9998, 10001),  # C
        (10001, 10002, 9985, 9997),  # S：震幅僅20點、距平盤僅15點
    ], prev_day=PREV)
    assert run(MotherChild(), bars).signals == []


def test_stop_sits_at_mother_extreme_when_within_20_points():
    bars = make_bars([
        (10018, 10030, 9998, 10026),  # M：母K，當下最高 10030，紅K
        (10020, 10025, 10015, 10024),  # C：子K
        (10024, 10025, 10008, 10013),  # S：黑K，收 ≤ 母K開盤 10018、跌破子K低點；距極端 17 點
    ], prev_day=PREV)
    res = run(MotherChild(), bars)
    sig = res.signals[0]
    assert sig.side == Side.SHORT and sig.price == 10013
    assert sig.stop == 10031  # 停損在母K極端點 10030 上方 1 跳（風險 18 點），而非進場價 +20
