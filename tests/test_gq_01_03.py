from helpers import make_bars

from wangtrader.core import Side, run
from wangtrader.methods.gq_01_03_evening_star import EveningStar

# 共用前段：i0-i1 提供「連續性大漲」比較基準；i2-i3 墊高 roll_high 視窗；
# i4＝長紅K線A（漲幅14.9%、當下(含)3根新高、相對i1累計漲幅16.7%）；i5＝夜星（小星線，爆量5000）。
PREFIX = [
    (95, 96, 94, 95, 1000),
    (95, 96, 94, 96, 1000),    # i1：rally 基準收盤 96
    (96, 97, 95, 96.5, 1000),
    (96.5, 98, 96, 97.5, 1000),
    (97.5, 115, 97, 112, 1000),   # i4＝A：長紅K線，漲幅14.9%，高點115（近3根新高），累計漲幅16.7%
    (112, 113, 111.5, 112.05, 5000),  # i5＝夜星：實體0.045%極小，爆量5000
]


def _strat(**kw):
    return EveningStar(high_lookback=3, rally_lookback=3, rally_min_pct=10.0,
                        vol_ma_period=3, vol_spike_ratio=2.0, shrink_ma_period=3, **kw)


def test_evening_star_c3_trigger_short_signal():
    bars = make_bars(PREFIX + [
        (112.05, 112.5, 105, 106, 1000),  # i6：拉回但收盤106仍>mid(104.75)，未觸發
        (106, 107, 99, 100, 1000),        # i7：收盤100<mid(104.75) → C3觸發，放空
    ])
    res = run(_strat(), bars)
    assert len(res.signals) == 1
    sig = res.signals[0]
    assert sig.side == Side.SHORT and sig.reason == "夜星反轉" and sig.stop is None


def test_volume_shrink_and_ma_still_rising_cancels_signal():
    # 夜星後量急縮(600<=5000*0.5)，且MA(3)未走緩（仍受i4/i5高收盤墊高而上升）→ 反轉危機化解，不成立訊號
    bars = make_bars(PREFIX + [
        (112.05, 113, 101, 104, 600),  # i6：收盤104<mid(104.75)，量僅600 → 應被F3濾掉
    ])
    res = run(_strat(), bars)
    assert res.signals == []


def test_disabling_shrink_filter_lets_signal_through():
    bars = make_bars(PREFIX + [
        (112.05, 113, 101, 104, 600),  # 同上組合，但關閉F3濾網
    ])
    res = run(_strat(check_volume_shrink_filter=False), bars)
    assert len(res.signals) == 1 and res.signals[0].side == Side.SHORT


def test_no_volume_spike_no_candidate():
    # 把i4/i5成交量都改小（無爆量）→ C2不成立，即使後續價格跌破mid也不觸發
    rows = list(PREFIX)
    rows[4] = (97.5, 115, 97, 112, 500)
    rows[5] = (112, 113, 111.5, 112.05, 500)
    bars = make_bars(rows + [
        (112.05, 112.5, 105, 106, 500),
        (106, 107, 99, 100, 500),
    ])
    res = run(_strat(), bars)
    assert res.signals == []


def test_entry_trigger_c4_waits_for_break_of_a_low():
    # c4模式：僅收盤跌破104.75(mid)不觸發，須等收盤跌破A最低點97才進場
    bars = make_bars(PREFIX + [
        (112.05, 112.5, 105, 100, 1000),  # 跌破mid但未破A低點97 → c4模式不觸發
        (100, 101, 90, 95, 1000),          # 跌破97 → 觸發
    ])
    res = run(_strat(entry_trigger="c4", check_volume_shrink_filter=False), bars)
    assert len(res.signals) == 1
    assert res.signals[0].price == 95
