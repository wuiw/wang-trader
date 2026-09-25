from helpers import make_bars

from wangtrader.core import Side, run
from wangtrader.methods.gq_01_11_pivot_trendline_breakout import PivotTrendlineBreakout

P = dict(fast_period=2, slow_period=3, pivot_level=1)


def _long_setup_bars():
    return [
        (100, 102, 98, 100),
        (100, 101, 95, 99),    # 谷：低點95（下一根確認）
        (99, 103, 97, 101),    # 確認谷點
        (101, 115, 99, 105),   # 峰1：高115（下一根確認）
        (105, 108, 102, 104),  # 確認峰1
        (104, 110, 101, 103),  # 峰2：高110，遞減（下一根確認）
        (103, 106, 100, 102),  # 確認峰2
        (112, 120, 111, 118),  # 突破前2日高(110)且突破下降趨勢線(105) → 買進
    ]


def test_long_direct_entry_with_pivot_stop():
    res = run(PivotTrendlineBreakout(**P), make_bars(_long_setup_bars()))
    assert len(res.signals) == 1
    sig = res.signals[0]
    assert sig.side == Side.LONG and sig.reason == "轉折趨勢線突破"
    assert sig.price == 118 and sig.stop == 95  # 停損＝最近層級1谷點


def test_short_direct_entry_with_pivot_stop():
    bars = [
        (100, 102, 98, 100),
        (100, 105, 99, 101),   # 峰：高105（下一根確認）
        (101, 103, 97, 99),    # 確認峰點
        (99, 101, 85, 95),     # 谷1：低85（下一根確認）
        (95, 98, 92, 96),      # 確認谷1
        (96, 99, 90, 97),      # 谷2：低90，遞增（下一根確認）
        (97, 100, 94, 98),     # 確認谷2
        (88, 89, 80, 82),      # 跌破前2日低(90)且跌破上升趨勢線(95) → 放空
    ]
    res = run(PivotTrendlineBreakout(**P), make_bars(bars))
    assert len(res.signals) == 1
    sig = res.signals[0]
    assert sig.side == Side.SHORT and sig.reason == "轉折趨勢線突破"
    assert sig.price == 82 and sig.stop == 105  # 停損＝最近層級1峰點


def test_no_two_pivots_blocks_signal():
    bars = [
        (100, 102, 98, 100),
        (100, 101, 95, 99),
        (99, 103, 97, 101),
        (101, 115, 99, 105),   # 峰1：高115（下一根確認）
        (105, 108, 102, 104),  # 確認峰1（僅有一個峰點，無法連線）
        (112, 122, 110, 120),  # 收盤突破前2日高、快慢均線亦金叉，但只有1個峰點無法畫趨勢線 → 不成立
    ]
    res = run(PivotTrendlineBreakout(**P), make_bars(bars))
    assert res.signals == []


def test_big_candle_overrides_stop_to_midpoint():
    res = run(PivotTrendlineBreakout(**P, big_candle_range_points=5.0), make_bars(_long_setup_bars()))
    assert len(res.signals) == 1
    sig = res.signals[0]
    assert sig.stop == (120 + 111) / 2  # 訊號K振幅9 >= 5 → 以中點為停損，覆蓋 pivot 停損


def test_ma_confirm_waits_for_unshaded_bar_above_fast_ma():
    bars = [
        (100, 102, 98, 100),
        (100, 150, 99, 145),   # 高點噴出，拉高均線水準
        (125, 127, 120, 124),
        (124, 135, 122, 128),  # 峰1：高135（下一根確認）
        (122, 124, 121, 123),  # 確認峰1
        (123, 125, 118, 121),  # 峰2：高125，遞減（下一根確認）
        (121, 123, 115, 119),  # 確認峰2
        (120, 128, 119, 126),  # 突破前2日高(125)與趨勢線，但收盤仍低於快均線 → 等待無遮蔽確認
        (126, 132, 125, 130),  # 收盤站上快均線，且未被前面K線高點壓制 → 確認進場
    ]
    res = run(PivotTrendlineBreakout(fast_period=7, slow_period=8, pivot_level=1), make_bars(bars))
    assert len(res.signals) == 1
    sig = res.signals[0]
    assert sig.side == Side.LONG and sig.reason == "轉折趨勢線突破(無遮蔽確認)"
    assert sig.price == 130 and sig.stop == 115  # 停損＝最近層級1谷點（確認峰2的第7根同時也是谷點，低115）
