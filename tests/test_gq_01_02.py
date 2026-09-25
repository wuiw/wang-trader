from helpers import make_bars

from wangtrader.core import Side, run
from wangtrader.methods.gq_01_02_transition_candle import TransitionCandle

UPTREND_PREFIX = [
    (100, 101, 99, 100, 1000),
    (100, 102, 99, 101, 1000),
    (101, 103, 100, 102, 1000),  # ma(3)首次有效但前值NaN → 尚未判定為上升趨勢
    (102, 104, 101, 103, 1000),  # ma(3)上升且收盤在均線上 → 上升趨勢成立
]


def _strat(**kw):
    return TransitionCandle(uptrend_ma_period=3, vol_ma_period=3, vol_spike_ratio=2.0, **kw)


def test_inverted_t_breakout_is_buy_signal():
    bars = make_bars(UPTREND_PREFIX + [
        (103, 108, 103, 103.05, 1000),  # 倒T線：實體極小、無下影線、長上影線，高點108
        (103.05, 106, 102, 105, 1000),  # 折回，未突破108
        (105, 110, 104, 109, 1000),     # 收盤109 > 108 → 突破倒T線最高點，買進
    ])
    res = run(_strat(), bars)
    assert len(res.signals) == 1
    sig = res.signals[0]
    assert sig.side == Side.LONG and sig.reason == "倒T線突破買進"
    assert sig.stop is None


def test_t_shape_breakdown_with_volume_spike_is_sell_signal():
    bars = make_bars(UPTREND_PREFIX + [
        (105, 105, 98, 104.95, 5000),  # T字線：實體極小、無上影線、長下影線，且爆量(5000 vs 均量約2333)，低點98
        (104.95, 105, 95, 97, 1000),   # 收盤97 < 98 → 跌破T字線最低點，賣出
    ])
    res = run(_strat(), bars)
    assert len(res.signals) == 1
    sig = res.signals[0]
    assert sig.side == Side.SHORT and sig.reason == "T字線跌破賣出"
    assert sig.stop is None


def test_t_shape_without_volume_spike_is_ignored():
    bars = make_bars(UPTREND_PREFIX + [
        (105, 105, 98, 104.95, 1000),  # 外觀是T字線，但量僅1000，未達爆量門檻 → 不成立候選
        (104.95, 105, 95, 97, 1000),   # 即使之後跌破98，也不應觸發訊號
    ])
    res = run(_strat(), bars)
    assert res.signals == []


def test_inverted_t_without_uptrend_is_ignored():
    # 平盤／無趨勢環境下出現外觀相同的倒T線，因不在上升趨勢中 → 不成立候選
    bars = make_bars([
        (100, 101, 99, 100, 1000),
        (100, 100, 100, 100, 1000),
        (100, 101, 100, 100.05, 1000),  # 倒T線外觀，但無上升趨勢
        (100.05, 106, 99, 105, 1000),   # 即使突破其高點101，也不應觸發訊號
    ])
    res = run(_strat(), bars)
    assert res.signals == []
