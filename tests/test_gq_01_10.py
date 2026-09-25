import pytest
from helpers import make_bars

from wangtrader.core import Side, run
from wangtrader.methods.gq_01_10_first_limit_up import FirstLimitUp

P = dict(lookback_days=3, year_bars=10, trough_pivot_level=1, max_from_trough_pct=20.0)


def test_first_limit_up_entry():
    bars = make_bars([
        (100, 102, 99, 100, 100),
        (100, 101, 98, 99, 100),
        (99, 100, 97, 98, 100),
        (104, 109, 105, 108, 100),  # 前3根無漲停，本根漲幅10.2% → 首度漲停買進
    ])
    res = run(FirstLimitUp(**P), bars)
    assert len(res.signals) == 1
    sig = res.signals[0]
    assert sig.side == Side.LONG and sig.reason == "首度漲停"
    assert sig.price == 108 and sig.stop == pytest.approx(108 * 0.93)


def test_f1_volume_too_high_is_filtered():
    bars = make_bars([
        (100, 102, 99, 100, 100),
        (100, 101, 98, 99, 100),
        (99, 100, 97, 98, 100),
        (104, 109, 105, 108, 200),  # 量200 > 近期最大量100*1.5=150 → 過濾
    ])
    res = run(FirstLimitUp(**P), bars)
    assert res.signals == []


def test_f2_far_from_trough_is_filtered():
    bars = make_bars([
        (100, 101, 90, 95, 100),
        (95, 96, 50, 55, 100),   # 波谷 low=50（下一根確認）
        (55, 60, 52, 58, 100),   # 確認波谷
        (58, 60, 55, 59, 100),
        (59, 63, 58, 62, 100),
        (62, 66, 61, 65, 100),
        (65, 69, 64, 68, 100),
        (68, 72, 67, 71, 100),
        (71, 75, 70, 74, 100),
        (74, 80, 73, 79, 100),   # 漲幅6.76%達漲停，但距波谷(50)已達58% > 20% → 過濾
    ])
    res = run(FirstLimitUp(**P), bars)
    assert res.signals == []


def test_reversal_on_break_signal_low():
    bars = make_bars([
        (100, 102, 99, 100, 100),
        (100, 101, 98, 99, 100),
        (99, 100, 97, 98, 100),
        (104, 109, 105, 108, 100),  # 首度漲停買進，訊號K最低點105，停損100.44
        (108, 110, 102, 103, 100),  # 收盤103 跌破訊號K最低點105（但未跌破停損100.44）→ 停損反手放空
    ])
    res = run(FirstLimitUp(**P, reversal_on_break_signal_low=True), bars)
    assert [s.side for s in res.signals] == [Side.LONG, Side.SHORT]
    assert res.signals[1].reason == "跌破訊號K最低點反手" and res.signals[1].stop is None
    t = res.trades[0]
    assert t.side == Side.LONG and t.reason_out == "反手" and t.exit_price == 103
