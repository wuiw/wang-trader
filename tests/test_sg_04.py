import pandas as pd
from helpers import make_bars

from wangtrader.core import Side, run
from wangtrader.methods.sg_04_dent import Dent

# 測試用 MA3（方法預設 MA10），結構與週期無關。
MA = dict(ma_period=3)

PRE = [
    (10000, 10002, 9995, 9996),
    (9996, 9998, 9990, 9992),
    (9992, 9994, 9988, 9990),  # 收盤在 MA 下
]
A = (9990, 10010, 9989, 10008)  # 收盤站上 MA 的首根，高點 10010
AFTER = [
    (10006, 10008, 10000, 10002),  # 高點未過 A → A 為層級1峰點（此根確認）
    (10002, 10009, 10001, 10007),  # 仍未過峰點
]
B = (10007, 10025, 10006, 10020)  # 收盤突破 10010 → 凹洞買訊


def _mirror(rows, pivot=20000):
    return [(pivot - o, pivot - lo, pivot - h, pivot - c) for o, h, lo, c in rows]


def _long_rows(b=B):
    return PRE + [A] + AFTER + [b]


def test_buy_signal():
    res = run(Dent(**MA), make_bars(_long_rows()))
    sig = res.signals[0]
    assert sig.side == Side.LONG and sig.reason == "凹洞買訊"
    assert sig.i == 6 and sig.price == 10020 and sig.stop == 10000


def test_sell_signal_mirror():
    res = run(Dent(**MA), make_bars(_mirror(_long_rows())))
    sig = res.signals[0]
    assert sig.side == Side.SHORT and sig.reason == "凹洞空訊"
    assert sig.i == 6 and sig.price == 9980 and sig.stop == 10000


def test_peak_on_second_bar():
    rows = PRE + [A, (10006, 10012, 10000, 10009), (10009, 10011, 10003, 10010), B]
    sig = run(Dent(**MA), make_bars(rows)).signals[0]
    assert sig.side == Side.LONG and sig.i == 6


def test_no_peak_on_first_two_bars():
    # A、A+1 都不是峰點（A+1、A+2 連續創高）→ 不成立
    rows = PRE + [A, (10006, 10012, 10000, 10009), (10009, 10015, 10005, 10011), B]
    assert not run(Dent(**MA), make_bars(rows)).signals


def test_close_not_above_peak():
    rows = _long_rows(b=(10007, 10020, 10006, 10009))  # 影線過峰點、收盤未過
    assert not run(Dent(**MA), make_bars(rows)).signals


def test_session_boundary():
    day1 = make_bars(PRE + [A] + AFTER)
    day2 = make_bars([B], start="2024-01-03 08:45")
    assert not run(Dent(**MA), pd.concat([day1, day2])).signals


def test_max_wait_minutes():
    bars = make_bars(_long_rows())  # A 到 B 15 分
    assert not run(Dent(max_wait_minutes=10, **MA), bars).signals
    assert run(Dent(max_wait_minutes=15, **MA), bars).signals


BIG_B = (10007, 10035, 10006, 10030)  # 高低差 29


def test_large_bar_wait_fill():
    rows = _long_rows(b=BIG_B) + [(10030, 10032, 10024, 10028)]
    res = run(Dent(large_bar_points=20, **MA), make_bars(rows))
    sig = res.signals[0]
    assert sig.reason == "凹洞買訊（折返承接）" and sig.price == 10026 and sig.stop == 10006
    assert res.trades[0].entry_i == 7 and res.trades[0].entry_price == 10026


def test_large_bar_wait_expires_after_next_bar():
    rows = _long_rows(b=BIG_B) + [(10030, 10040, 10028, 10038), (10038, 10039, 10020, 10025)]
    res = run(Dent(large_bar_points=20, **MA), make_bars(rows))
    assert res.signals and not res.trades  # 次根未折返到 10026 → 不承接


def test_large_bar_short_wait():
    rows = _mirror(_long_rows(b=BIG_B) + [(10030, 10032, 10024, 10028)])
    res = run(Dent(large_bar_points=20, **MA), make_bars(rows))
    sig = res.signals[0]
    assert sig.side == Side.SHORT and sig.price == 9974 and sig.stop == 9994
    assert res.trades[0].entry_price == 9974


def test_large_bar_skip_and_threshold():
    rows = _long_rows(b=BIG_B)
    assert not run(Dent(large_bar_points=20, large_bar_mode="skip", **MA), make_bars(rows)).signals
    sig = run(Dent(large_bar_points=40, **MA), make_bars(rows)).signals[0]
    assert sig.reason == "凹洞買訊" and sig.stop == 10010


def test_cross_down_cancels_long_setup():
    # 峰點確認後收盤跌破 MA → 買訊設定清除，改出空方設定；之後同一根不應出買訊
    rows = PRE + [A, AFTER[0], (10002, 10004, 9985, 9988)]
    res = run(Dent(**MA), make_bars(rows))
    assert not res.signals
