import pandas as pd
import pytest
from helpers import make_bars

from wangtrader.core import Side, prepare, run
from wangtrader.methods.gq_02_04_kd_cross_gap_filter import KdCrossGapFilter

# 縮小版参数（快慢均線、KD週期）取代原文未指定的均線週期，讓交叉/趨勢可在少量K線內驗證。
KW = dict(trend_fast=5, trend_slow=15, kd_n=3, k_period=2, d_period=2, pivot_level=1, gap_days_max=3)


def _rows_black(closes):
    """open 恆高於 close，使每根K線皆為黑K（供空方測試使用，避免C5'干擾）。"""
    return [(c + 0.5, c + 1, c - 1, c) for c in closes]


def _rows_plain(closes):
    return [(c - 0.5, c + 1, c - 1, c) for c in closes]


# 多方：長多頭段(16根) + 4根回檔 + 1根反漲，於反漲根形成金叉（d<=65，均線多頭，距波谷1天）
LONG_CLOSES = list(range(100, 100 + 3 * 16, 3)) + [141, 137, 133, 129, 135]
# 空方：長空頭段(16根) + 4根反彈 + 1根回落，於回落根形成死叉（k>=20，均線空頭，距波峰1天）
SHORT_CLOSES = list(range(145, 145 - 3 * 16, -3)) + [104, 108, 112, 116, 110]


def test_golden_cross_signal_fires_in_bull_trend():
    bars = make_bars(_rows_plain(LONG_CLOSES))
    res = run(KdCrossGapFilter(**KW, long_stop_pct=0.07), bars)
    assert len(res.signals) == 1
    sig = res.signals[0]
    assert sig.side == Side.LONG and sig.reason == "KD金叉買點"
    assert sig.price == 135
    assert sig.stop == pytest.approx(135 * 0.93)


def test_death_cross_signal_fires_in_bear_trend_with_black_k():
    bars = make_bars(_rows_black(SHORT_CLOSES))
    res = run(KdCrossGapFilter(**KW), bars)
    assert len(res.signals) == 1
    sig = res.signals[0]
    assert sig.side == Side.SHORT and sig.reason == "KD死叉賣點"
    assert sig.price == 110
    assert sig.stop == pytest.approx(110 * 1.07)


def test_filtered_when_death_cross_bar_is_red():
    rows = _rows_black(SHORT_CLOSES)
    last = rows[-1]
    rows[-1] = (last[3] - 0.5, last[1], last[2], last[3])  # 訊號K線改為紅K（open<close）
    bars = make_bars(rows)
    res = run(KdCrossGapFilter(**KW), bars)
    assert res.signals == []


def test_gap_filter_allows_sideways_after_trough():
    # 谷點(idx2)之後價格未再創新低、橫向游走 -> 即使距離已超過3天仍不受限（p.115-116）
    closes = [110, 105, 100, 102, 101, 103, 102, 104, 103, 105]
    df = prepare(make_bars(_rows_plain(closes)))
    strat = KdCrossGapFilter(**KW)
    strat.prepare(df)
    assert strat._gap_ok(df, 9, "trough") is True


def test_gap_filter_blocks_when_far_and_made_new_low():
    # 谷點(idx2=100)之後又於idx7-9跌破100創新低，且該新低尚未形成新的已確認谷點 -> 不視為橫盤，距離>3天須剔除
    closes = [110, 105, 100, 102, 104, 103, 101, 97, 94, 90]
    df = prepare(make_bars(_rows_plain(closes)))
    strat = KdCrossGapFilter(**KW)
    strat.prepare(df)
    assert strat._gap_ok(df, 9, "trough") is False


def test_tier_filter_blocks_same_tier_unless_stopped_out():
    strat = KdCrossGapFilter(tier_pct=0.02)
    strat._last_entry[Side.LONG] = (100.0, False)
    assert strat._tier_blocked(Side.LONG, 101.0) is True  # 相差1% <= 2%，同位階
    assert strat._tier_blocked(Side.LONG, 105.0) is False  # 相差5% > 2%
    strat._last_entry[Side.LONG] = (100.0, True)  # 前次已停損
    assert strat._tier_blocked(Side.LONG, 101.0) is False


def test_short_trailing_stop_moves_down_and_exits():
    # 空單持有中出現長黑K(跌幅>=4%)，停損移到當根最高點(111，低於原始7%停損117.7)且只能下移；
    # 之後最高點觸及111即觸發停損出場（成交價＝停損價，因開盤已低於停損）
    extra = [
        (110.5, 111, 100, 101),  # 大跌K線(約-8.2%)，最高點111 -> 停損下移至111
        (102, 113, 101, 104),    # 最高點113 >= 111 -> 觸發停損出場
    ]
    bars = make_bars(_rows_black(SHORT_CLOSES) + extra)
    res = run(KdCrossGapFilter(trailing_black_bar=True, black_bar_pct=0.04, **KW), bars)
    assert len(res.trades) == 1
    t = res.trades[0]
    assert t.side == Side.SHORT and t.reason_out == "停損"
    assert t.exit_price == 111.0
