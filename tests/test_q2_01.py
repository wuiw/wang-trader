import pandas as pd
from datetime import time

from helpers import make_bars

from wangtrader.core import Side, run
from wangtrader.methods.q2_01_ma_three_step import MAThreeStep

PREV = (90, 95, 85, 90)  # 平盤 90

LONG_BASE = [
    (100, 101, 99, 100),
    (100, 102, 99, 101),
    (101, 103, 100, 102),  # 收盤突破均線 (break_i)
    (102, 110, 101, 105),  # 峰位 C1（高點110，下一根確認）
    (105, 106, 103, 104),
    (104, 106, 103, 105),  # 折返段，收盤皆守均線
    (105, 108, 104, 107),
    (107, 113, 106, 112),  # 收盤112突破峰位110 → 買進訊號 C3
]

SHORT_BASE = [
    (100, 101, 99, 100),
    (100, 101, 98, 99),
    (99, 100, 97, 98),  # 收盤跌破均線 (break_i)
    (98, 99, 90, 95),  # 谷位 C1'（低點90）
    (95, 97, 94, 96),
    (96, 97, 94, 95),  # 折返段，收盤皆守均線
    (95, 96, 92, 93),
    (93, 94, 87, 88),  # 收盤88跌破谷位90 → 放空訊號 C3'
]

KW = dict(ma_period=3, pivot_level=1, exit_mode="none")


def test_long_three_step_signal():
    bars = make_bars(LONG_BASE, prev_day=PREV)
    res = run(MAThreeStep(**KW), bars)
    assert len(res.signals) == 1
    sig = res.signals[0]
    assert sig.side == Side.LONG and sig.reason == "均線三步驟買進"
    assert sig.price == 112 and sig.stop == 100  # 112 個位數2 -> 停損 112-12=100


def test_short_three_step_signal():
    bars = make_bars(SHORT_BASE, prev_day=(110, 115, 105, 110))
    res = run(MAThreeStep(**KW), bars)
    assert len(res.signals) == 1
    sig = res.signals[0]
    assert sig.side == Side.SHORT and sig.reason == "均線三步驟放空"
    assert sig.price == 88 and sig.stop == 106  # 88 個位數8 -> 停損 88+18=106


def test_reset_when_pullback_closes_cross_ma():
    """3.3.2：折返段任一根收盤跌破均線 → 整段重新計數，訊號不成立。"""
    bars_rows = list(LONG_BASE)
    bars_rows[5] = (104, 105, 95, 96)  # 收盤96 遠低於均線 → 重新計數
    bars = make_bars(bars_rows, prev_day=PREV)
    res = run(MAThreeStep(**KW), bars)
    assert res.signals == []


def test_f1_big_bar_is_filtered():
    bars = make_bars(LONG_BASE, prev_day=PREV)
    res = run(MAThreeStep(big_bar_points=3, **KW), bars)  # 訊號K線實際漲跌5點
    assert res.signals == []


def test_f2_deviation_from_break_is_filtered():
    bars = make_bars(LONG_BASE, prev_day=PREV)
    res = run(MAThreeStep(max_dev_from_break=5, **KW), bars)  # 實際距起漲收盤10點
    assert res.signals == []


def test_f3_deviation_from_prev_close_is_filtered():
    bars = make_bars(LONG_BASE, prev_day=PREV)  # 平盤90，訊號收盤112，距平盤22點
    res = run(MAThreeStep(max_dev_from_prev_close=10, **KW), bars)
    assert res.signals == []


def test_f4_min_bar_points_is_filtered():
    bars = make_bars(LONG_BASE, prev_day=PREV)
    res = run(MAThreeStep(min_bar_points=6, **KW), bars)  # 訊號K線實際漲跌僅5點
    assert res.signals == []


def test_f5_no_entry_after_blocks_same_day_but_carries_to_next_open():
    day1 = make_bars(LONG_BASE, prev_day=PREV)
    day2 = make_bars(
        [(110, 112, 108, 111), (111, 112, 109, 110)], start="2024-01-03 08:45"
    )  # 開盤第一根與昨日最後一根(106-113)重疊
    bars = pd.concat([day1, day2])
    res = run(MAThreeStep(no_entry_after=time(9, 0), **KW), bars)
    assert len(res.signals) == 1
    sig = res.signals[0]
    assert sig.side == Side.LONG and sig.reason == "隔日延續進場"
    assert sig.stop == 100
    t = res.trades[0]
    assert t.entry_price == 111  # 沿用隔日開盤第一根收盤價（引擎進場皆以收盤價成交）


def test_reversal_flips_position_on_opposite_signal():
    rows = LONG_BASE + [
        (119, 120, 108, 110),
        (110, 112, 106, 108),
        (108, 110, 104, 106),
        (106, 108, 105, 106),
        (106, 107, 102, 103),  # 收盤103跌破谷位104 → 放空訊號，未觸及多單停損即反手
    ]
    rows[7] = (107, 120, 106, 119)  # 訊號收盤改為119（個位數9，停損=100，留出反手空間）
    bars = make_bars(rows, prev_day=PREV)
    res = run(MAThreeStep(**KW), bars)
    assert [s.side for s in res.signals] == [Side.LONG, Side.SHORT]
    assert res.trades[0].reason_out == "反手"
    assert res.trades[1].side == Side.SHORT


def test_ladder_exit_trailing_stop():
    rows = LONG_BASE + [
        (112, 120, 111, 120),
        (120, 135, 119, 135),  # 獲利達20點且收盤=最高點 → 移動停利至 135-20=115
        (133, 134, 110, 113),  # 盤中跌破115超過1點 → 出場
        (113, 114, 111, 112),
    ]
    bars = make_bars(rows, prev_day=PREV)
    res = run(MAThreeStep(ma_period=3, pivot_level=1, exit_mode="ladder"), bars)
    t = res.trades[0]
    assert t.reason_out == "固定點數移動停利"
    assert t.exit_price == 113


def test_unmasked_requires_close_above_all_prior_highs():
    """3.3.3（p.17）：只有影線突破峰位的K線也會「遮蔽」後續訊號，
    訊號收盤必須高於突破均線以來至前一根為止所有K線的最高點，而非只高於最高收盤。"""
    rows = list(LONG_BASE[:6]) + [
        (105, 111, 104, 107),  # 影線 111 突破峰位 110，收盤未站上 → 遮蔽線上移到 111
        (107, 111.5, 106, 111),  # 收盤 111 > 峰位 110，但未高於前一根最高點 111（被遮蔽）→ 不成立
        (111, 114, 110, 113),  # 收盤 113 高於先前所有最高點 → 買進訊號
    ]
    bars = make_bars(rows, prev_day=PREV)
    res = run(MAThreeStep(**KW), bars)
    assert [s.i for s in res.signals] == [9]  # prev_day 佔 index 0，訊號在第 9 根（列 8）
    assert res.signals[0].price == 113


def test_f2_measured_from_original_ma_break_not_last_signal():
    """F2（p.18）：同一段出現第二組三步驟時，「均線起漲位置」仍是最初突破均線那根，不是前一個訊號。"""
    rows = LONG_BASE + [
        (112, 118, 111, 116),  # 第二組峰位 118
        (116, 117, 114, 115),  # 折返，確認峰位
        (115, 120, 114, 119),  # 收盤 119 突破 118 → 第二訊號；距起漲收盤(102) 17 點、距前一訊號僅 7 點
    ]
    bars = make_bars(rows, prev_day=PREV)
    assert [s.i for s in run(MAThreeStep(**KW), bars).signals] == [8, 11]
    res = run(MAThreeStep(max_dev_from_break=15, **KW), bars)
    assert [s.i for s in res.signals] == [8]  # 第二訊號距起漲 17 > 15 被 F2 濾掉


def test_ladder_moves_only_when_close_and_high_both_new_and_breach_needs_one_point():
    """6.2（p.30-31）：收盤與最高點同時創新高才移動停利線；只有收盤創新高（最高點未創）不移動；
    觸及＝盤中跌破停利線達 1 點，剛好碰到停利線不算。"""
    rows = LONG_BASE + [
        (112, 120, 111, 120),  # 未達 20 點目標
        (120, 135, 119, 135),  # 達目標且收盤/最高同創新高 → 停利線 115（觸發價 114）
        (135, 135, 120, 121),  # 未觸及
        (121, 140, 121, 136),  # 同創新高 → 停利線 120（觸發價 119）
        (136, 139, 135, 138),  # 收盤創新高但最高點 139 < 140 → 不移動
        (138, 139, 119.5, 130),  # 低點 119.5 未跌破 119 → 不出場
        (130, 131, 119, 125),  # 低點 119 跌破停利線 1 點 → 出場
    ]
    bars = make_bars(rows, prev_day=PREV)
    res = run(MAThreeStep(ma_period=3, pivot_level=1, exit_mode="ladder"), bars)
    t = res.trades[0]
    assert t.reason_out == "固定點數移動停利" and t.exit_i == 15 and t.exit_price == 125
