from helpers import make_bars

from wangtrader.core import Side, run
from wangtrader.methods.gq_01_09_inertia_break_buy import InertiaBreakBuy


def test_horizontal_consolidation_direct_entry():
    bars = make_bars([
        (100, 102, 98, 100),
        (100, 103, 97, 101),
        (101, 104, 98, 100),
        (100, 102, 96, 99),
        (99, 101, 95, 100),
        (100, 103, 97, 101),
        (104, 112, 103, 110),  # 大漲K線收盤突破前2日高(103)，水平整理不需趨勢線 → 買進
    ])
    res = run(InertiaBreakBuy(lookback_days=3), bars)
    assert len(res.signals) == 1
    sig = res.signals[0]
    assert sig.side == Side.LONG and sig.reason == "慣性破壞買訊"
    assert sig.price == 110 and sig.stop == 103


def test_small_bar_breakout_is_filtered():
    bars = make_bars([
        (100, 102, 98, 100),
        (100, 103, 97, 101),
        (101, 104, 98, 100),
        (100, 102, 96, 99),
        (99, 101, 95, 100),
        (100, 103, 97, 101),
        (103.5, 105, 103, 104),  # 收盤突破前2日高(103)，但只是小漲K線(<4%) → 不成立
    ])
    res = run(InertiaBreakBuy(lookback_days=3), bars)
    assert res.signals == []


def test_downslope_trendline_direct_entry():
    bars = make_bars([
        (100, 102, 98, 100),
        (100, 103, 97, 101),
        (101, 118, 99, 102),   # 峰1：高118（確認於下一根）
        (105, 110, 100, 104),  # 確認峰1
        (104, 106, 98, 100),
        (100, 110, 99, 105),   # 峰2：高110（確認於下一根，遞減）
        (105, 108, 101, 103),  # 確認峰2
        (105, 120, 104, 118),  # 大漲K線：突破前2日高(110)且突破下降趨勢線 → 買進
    ])
    res = run(InertiaBreakBuy(lookback_days=3, trend_pivot_level=1, horizontal_range_pct=1.0), bars)
    assert len(res.signals) == 1
    sig = res.signals[0]
    assert sig.side == Side.LONG and sig.reason == "慣性破壞買訊"
    assert sig.price == 118 and sig.stop == 104


def test_downslope_needs_n_shape_confirmation():
    bars = make_bars([
        (100, 102, 98, 100),
        (100, 103, 97, 101),
        (101, 118, 99, 102),   # 峰1：高118（確認於下一根）
        (105, 110, 100, 104),  # 確認峰1
        (104, 106, 98, 100),
        (100, 116, 99, 105),   # 峰2：高116（確認於下一根，遞減）
        (105, 108, 101, 103),  # 確認峰2
        (103, 105, 100, 102),
        (102, 104, 99, 101),
        (100, 112, 99, 110),   # 突破前2日高(105)，但未突破下降趨勢線(~113.3) → 進入N字確認觀察
        (110, 120, 109, 115),  # 收盤突破前一根大漲K高點(112) → N字確認進場
    ])
    res = run(InertiaBreakBuy(lookback_days=3, trend_pivot_level=1, horizontal_range_pct=1.0), bars)
    assert len(res.signals) == 1
    sig = res.signals[0]
    assert sig.side == Side.LONG and sig.reason == "慣性破壞買訊(N字確認)"
    assert sig.price == 115 and sig.stop == 109
