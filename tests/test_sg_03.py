from helpers import make_bars

from wangtrader.core import Side, run
from wangtrader.methods.sg_03_flat_kd import FlatKd


def _fall(n=20, px=10000):
    rows = []
    for _ in range(n):
        rows.append((px, px + 1, px - 6, px - 5))
        px -= 5
    return rows, px  # 最後收盤 px（10000−5n）


def _rise(n=20, px=10000):
    rows = []
    for _ in range(n):
        rows.append((px, px + 6, px - 1, px + 5))
        px += 5
    return rows, px


def _long_rows():
    rows, px = _fall()  # 收 9900，K、D 都在 20 下
    # 小反彈兩根：第 2 根 K 上穿 D（金叉），當根 K≈13、D≈8 仍在 20 下
    rows += [(px, px + 2, px - 1, px + 1), (px + 1, px + 12, px + 2, px + 10)]
    return rows


def _short_rows():
    rows, px = _rise()  # 收 10100，K、D 都在 80 上
    rows += [(px, px + 1, px - 4, px - 3), (px - 3, px - 2, px - 12, px - 10)]
    return rows


def _flat(v):
    return (v, v, v, v)


def test_long_above_flat_golden_cross():
    res = run(FlatKd(), make_bars(_long_rows(), prev_day=_flat(9800)))
    sig = res.signals[0]
    assert sig.side == Side.LONG and sig.reason == "平盤KD買訊"
    assert sig.price == 9910
    assert sig.stop == 9899  # KD 在 20 下那一段到訊號K的最低點


def test_short_below_flat_dead_cross():
    res = run(FlatKd(), make_bars(_short_rows(), prev_day=_flat(10200)))
    sig = res.signals[0]
    assert sig.side == Side.SHORT and sig.reason == "平盤KD空訊"
    assert sig.price == 10090
    assert sig.stop == 10101


def test_long_filtered_when_below_flat():
    assert not run(FlatKd(), make_bars(_long_rows(), prev_day=_flat(10500))).signals


def test_short_filtered_when_above_flat():
    assert not run(FlatKd(), make_bars(_short_rows(), prev_day=_flat(9500))).signals


def test_no_flat_no_signal():
    assert not run(FlatKd(), make_bars(_long_rows())).signals  # 第一個交易日沒有平盤


def test_flat_mode_bar_requires_whole_bar():
    bars = make_bars(_long_rows(), prev_day=(9906, 9907, 9904, 9905))  # 訊號K 收 9910 > 平盤，但最低 9902 < 平盤
    assert run(FlatKd(flat_mode="close"), bars).signals
    assert not run(FlatKd(flat_mode="bar"), bars).signals


def test_kd_not_in_zone_filtered():
    bars = make_bars(_long_rows(), prev_day=_flat(9800))
    assert not run(FlatKd(oversold=4), bars).signals  # 交叉前一根 D≈4.6，不在 4 以下


def test_zone_bar_prev_vs_cross():
    rows, px = _fall()
    rows += [(px, px + 40, px - 1, px + 38)]  # 大紅K 金叉，當根 K 已遠離 20
    bars = make_bars(rows, prev_day=_flat(9800))
    res = run(FlatKd(zone_bar="prev"), bars)
    assert res.signals and res.signals[0].side == Side.LONG
    assert not run(FlatKd(zone_bar="cross"), bars).signals


def test_stop_over_20_uses_digit_stop():
    rows, px = _fall()
    rows += [(px, px + 40, px - 1, px + 38)]  # 進場 9938，區段低點 9899 距 39 點
    sig = run(FlatKd(), make_bars(rows, prev_day=_flat(9800))).signals[0]
    assert sig.price == 9938 and sig.stop == 9938 - (10 + 8)


def test_no_cross_no_signal():
    rows, _ = _fall()
    assert not run(FlatKd(), make_bars(rows, prev_day=_flat(9800))).signals
