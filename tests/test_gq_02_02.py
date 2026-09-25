import pytest
from helpers import make_bars

from wangtrader.core import Side, run
from wangtrader.methods.gq_02_02_rsi_oversold_and_divergence import RsiOversoldAndDivergence

# 單腳下跌至低點後大漲：RSI(5) 在大漲當根仍 <=20，且漲幅 >=5%（用 python 事先驗證數值）
SINGLE_LEG = [150, 145, 139, 132, 124, 115, 105, 94]
RALLY_SINGLE = round(94 * 1.06, 2)  # +6%，RSI約14.9


def _rows(closes):
    return [(c - 1, c + 1, c - 1, c) for c in closes]


def test_rsi_oversold_signal_fires():
    bars = make_bars(_rows(SINGLE_LEG) + [(94, RALLY_SINGLE + 1, 93, RALLY_SINGLE)])
    res = run(RsiOversoldAndDivergence(), bars)
    assert len(res.signals) == 1
    sig = res.signals[0]
    assert sig.side == Side.LONG and sig.reason == "RSI低值買點"
    assert sig.price == RALLY_SINGLE
    assert sig.stop == pytest.approx(RALLY_SINGLE * 0.93)


def test_filtered_when_no_big_bar():
    # RSI雖<=20，但漲幅不足5%
    bars = make_bars(_rows(SINGLE_LEG) + [(94, 96, 93, 96)])
    res = run(RsiOversoldAndDivergence(), bars)
    assert res.signals == []


def test_divergence_tagged_when_price_new_low_but_rsi_not():
    # 兩腳下跌：第一腳低點(idx5=115,RSI≈0)反彈後，第二腳跌更深(idx15=68,RSI≈3.08>0)，
    # 隨後大漲(+5.5%)觸發訊號，應標記為「RSI背離買點」
    closes = [150, 145, 139, 132, 124, 115, 122, 116, 110, 104, 98, 92, 86, 80, 74, 68]
    rally = round(68 * 1.055, 2)
    bars = make_bars(_rows(closes) + [(68, rally + 2, 69, rally)])  # 反彈低點(69) 高於前腳低點(67)
    res = run(RsiOversoldAndDivergence(), bars)
    assert len(res.signals) == 1
    assert res.signals[0].reason == "RSI背離買點"


def test_exit_on_close_below_prior_low():
    bars = make_bars(
        _rows(SINGLE_LEG)
        + [
            (94, RALLY_SINGLE + 1, 93, RALLY_SINGLE),  # 進場
            (RALLY_SINGLE, RALLY_SINGLE + 2, RALLY_SINGLE - 1, RALLY_SINGLE + 1),  # 續漲，不出場
            (96, 97, 93, 95),  # 收盤(95)跌破前一根最低點(98.64)，但未觸及7%停損(92.665) -> 出場
        ]
    )
    res = run(RsiOversoldAndDivergence(), bars)
    assert len(res.trades) == 1
    assert res.trades[0].reason_out == "跌破前一天最低點"


def test_stop_mode_pivot_uses_recent_trough():
    # stop_mode="pivot"：以最近已確認谷點價位為停損
    closes = [150, 145, 139, 132, 124, 115, 122, 116, 110, 104, 98, 92, 86, 80, 74, 68]
    rally = round(68 * 1.055, 2)
    bars = make_bars(_rows(closes) + [(68, rally + 2, 69, rally)])
    res = run(RsiOversoldAndDivergence(stop_mode="pivot"), bars)
    assert len(res.signals) == 1
    assert res.signals[0].stop == 67.0  # 最近谷點K線(idx15, low=67)
