import pandas as pd
from helpers import make_bars

from wangtrader.core import Side, run
from wangtrader.methods.sg_05_inside_box import InsideBox

OPEN_L = (10020, 10022, 10005, 10006)  # 開盤根（幅度 17，不可能當首根）
FIRST_L = (10006, 10008, 10000, 10002)  # 首根 8 點，低點＝盤中最低
INNER_L = [(10002, 10006, 10001, 10004), (10004, 10007, 10002, 10005)]
BREAK_L = (10005, 10012, 10004, 10010)  # 收盤 10010 > 首根高 10008

OPEN_S = (10000, 10015, 9998, 10014)
FIRST_S = (10014, 10020, 10012, 10018)  # 首根高點＝盤中最高
INNER_S = [(10018, 10019, 10013, 10015), (10015, 10018, 10014, 10016)]
BREAK_S = (10016, 10017, 10008, 10010)  # 收盤 10010 < 首根低 10012


def _run(rows, **kw):
    return run(InsideBox(**kw), make_bars(rows, freq="1min"))


def test_buy_signal():
    res = _run([OPEN_L, FIRST_L, *INNER_L, BREAK_L])
    sig = res.signals[0]
    assert sig.side == Side.LONG and sig.reason == "內困買訊"
    assert sig.price == 10010 and sig.stop == 9990
    assert sig.meta["boxed_bars"] == 3


def test_sell_signal():
    res = _run([OPEN_S, FIRST_S, *INNER_S, BREAK_S])
    sig = res.signals[0]
    assert sig.side == Side.SHORT and sig.reason == "內困空訊"
    assert sig.price == 10010 and sig.stop == 10030


def test_needs_at_least_three_boxed_bars():
    assert not _run([OPEN_L, FIRST_L, INNER_L[0], BREAK_L]).signals


def test_max_boxed_bars():
    rows = [OPEN_L, FIRST_L, *(INNER_L * 2), INNER_L[0], BREAK_L]  # 含首根 6 根 → 第 7 根突破
    assert not _run(rows).signals
    assert _run(rows, max_boxed_bars=6).signals
    assert _run(rows, max_boxed_bars=None).signals
    ok = [OPEN_L, FIRST_L, *(INNER_L * 2), BREAK_L]  # 含首根 5 根 → 第 6 根突破
    assert _run(ok).signals[0].meta["boxed_bars"] == 5


def test_first_bar_range_limit():
    first = (10006, 10013, 10000, 10002)  # 13 點 > 10
    brk = (10005, 10016, 10004, 10015)
    rows = [OPEN_L, first, *INNER_L, brk]
    assert not _run(rows).signals
    assert _run(rows, max_first_range=20).signals
    assert _run(rows, max_first_range=None).signals


def test_position_near_session_extreme():
    low_open = (10020, 10022, 9985, 10006)  # 盤中最低 9985，首根低點 10000 距 15 點
    rows = [low_open, FIRST_L, *INNER_L, BREAK_L]
    assert not _run(rows).signals
    assert _run(rows, near_extreme_points=None).signals
    assert _run(rows, near_extreme_points=15).signals


def test_short_position_near_session_high():
    high_open = (10000, 10035, 9998, 10014)  # 盤中最高 10035，首根高點 10020 距 15 點
    assert not _run([high_open, FIRST_S, *INNER_S, BREAK_S]).signals


def test_bar_leaving_box_without_close_breaks_pattern():
    escape = (10004, 10010, 10001, 10006)  # 盤中越過首根高點但收在區間內 → 不再被框住
    brk = (10006, 10014, 10005, 10012)
    assert not _run([OPEN_L, FIRST_L, *INNER_L, escape, brk]).signals


def test_short_can_be_disabled():
    assert not _run([OPEN_S, FIRST_S, *INNER_S, BREAK_S], enable_short=False).signals


def test_box_does_not_span_sessions():
    d1 = make_bars([OPEN_L, FIRST_L, *INNER_L], start="2024-01-02 08:45", freq="1min")
    d2 = make_bars([BREAK_L], start="2024-01-03 08:45", freq="1min")
    assert not run(InsideBox(), pd.concat([d1, d2])).signals


def test_stop_fixed_20_even_with_widened_first_bar():
    first = (10006, 10021, 10000, 10002)  # 放大版：首根 21 點
    brk = (10005, 10025, 10004, 10023)
    sig = _run([OPEN_L, first, *INNER_L, brk], max_first_range=None).signals[0]
    assert sig.price - sig.stop == 20
