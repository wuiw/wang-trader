import pytest
from helpers import make_bars

from wangtrader.core import Side, run
from wangtrader.methods.gq_02_03_rsi_cross_80 import RsiCross80

# RSI(5) 於下列序列由 71.93 -> 83.01（穿越80），末根漲幅6% >=5%（事先以 core.indicators.rsi 驗證）
CROSS80 = [100, 103, 101.5, 105, 103.5, 107, 105.5, 109, 107.5]
CROSS80_RALLY = round(107.5 * 1.06, 2)

# RSI(5) 由 0.0 -> 60.43（穿越50，未達80），末根漲幅約8%
CROSS50 = [100, 98, 96.5, 95.5, 95, 94.7]
CROSS50_RALLY = round(94.7 * 1.08, 2)


def _rows(closes):
    return [(c - 1, c + 1, c - 1, c) for c in closes]


def test_cross_80_signal_fires():
    bars = make_bars(_rows(CROSS80) + [(107.5, CROSS80_RALLY + 1, CROSS80_RALLY - 1, CROSS80_RALLY)])
    res = run(RsiCross80(), bars)
    assert len(res.signals) == 1
    sig = res.signals[0]
    assert sig.side == Side.LONG and sig.reason == "RSI穿越80買點"
    assert sig.price == CROSS80_RALLY
    assert sig.stop == pytest.approx(106.5)  # 真實低點=min(112.95,107.5)=107.5，下方一檔(1.0)


def test_cross_50_signal_fires():
    bars = make_bars(_rows(CROSS50) + [(94.7, CROSS50_RALLY + 1, CROSS50_RALLY - 1, CROSS50_RALLY)])
    res = run(RsiCross80(), bars)
    assert len(res.signals) == 1
    assert res.signals[0].reason == "RSI穿越50買點"


def test_filtered_when_not_big_bar():
    bars = make_bars(_rows(CROSS80) + [(107.5, 109, 106, 109)])  # 漲幅僅約1.4%
    res = run(RsiCross80(), bars)
    assert res.signals == []


def test_filtered_when_shadow_too_long():
    # 啟用 shadow_max_pct 後，上影線過長（high 遠高於 close）應被剔除
    rows = _rows(CROSS80) + [(107.5, CROSS80_RALLY + 20, CROSS80_RALLY - 1, CROSS80_RALLY)]
    bars = make_bars(rows)
    res = run(RsiCross80(shadow_max_pct=0.01), bars)
    assert res.signals == []


def test_stop_triggers_and_no_further_takeprofit():
    bars = make_bars(
        _rows(CROSS80)
        + [
            (107.5, CROSS80_RALLY + 1, CROSS80_RALLY - 1, CROSS80_RALLY),  # 進場
            (CROSS80_RALLY, CROSS80_RALLY + 1, 100, 102),  # 跌破真實低點下方一檔 -> 停損出場
        ]
    )
    res = run(RsiCross80(), bars)
    assert len(res.trades) == 1
    assert res.trades[0].reason_out == "停損"
