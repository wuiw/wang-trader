import pandas as pd
from datetime import time

from helpers import make_bars

from wangtrader.core import Context, Position, Side, run
from wangtrader.methods.q2_01_ma_three_step import MAThreeStep, _digit_stop

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
    assert sig.price == 88 and sig.stop == 100  # 88 個位數8 -> 停損 88+(20-8)=100（p.14公式）


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


def test_short_stop_formula_matches_book_examples():
    """回歸測試（問題彙整.md C）：空單停損＝收盤+(20−個位數)，個位數0固定20點（p.14 IMG_8463 原文範例）。
    先前程式誤用鏡像公式 收盤+(10+個位數)，只有個位數5時數值相同。"""
    assert _digit_stop(Side.SHORT, 7665, 10.0, 20.0) == 7680
    assert _digit_stop(Side.SHORT, 7701, 10.0, 20.0) == 7720
    assert _digit_stop(Side.SHORT, 8636, 10.0, 20.0) == 8650
    assert _digit_stop(Side.SHORT, 7700, 10.0, 20.0) == 7720  # 整數價位固定20點
    assert _digit_stop(Side.LONG, 7905, 10.0, 20.0) == 7890  # 多方公式不變（p.13）


def test_ma_tier_exit_switches_from_slow_to_fast_ma_after_profit():
    """6.4（p.42-45）：達獲利目標後先用 MA(ma_period) 為停利線；獲利達 ma_fast_arm_profit 後改用 MA(ma_fast_period)。"""
    strat = MAThreeStep(profit_target=20.0, ma_fast_arm_profit=50.0)
    df = pd.DataFrame({
        "close": [100.0, 140.0],
        "ma": [95.0, 145.0],
        "ma_fast": [95.0, 135.0],
    })
    pos_big = Position(Side.LONG, entry_i=0, entry_price=100.0, stop=90.0, best=155.0)  # 獲利55點 >=50 -> 用MA10
    ctx_big = Context(i=1, df=df, pos=pos_big, trades=[], stopped=None)
    assert strat._ma_tier_exit(ctx_big) is None  # 收盤140 > MA10(135)，不出場

    pos_small = Position(Side.LONG, entry_i=0, entry_price=100.0, stop=90.0, best=125.0)  # 獲利25點 <50 -> 用MA30
    ctx_small = Context(i=1, df=df, pos=pos_small, trades=[], stopped=None)
    order = strat._ma_tier_exit(ctx_small)
    assert order is not None and order.reason == "均線停利"  # 收盤140 < MA30(145)，出場


def test_range_exit_uses_recent_window():
    """6.5（p.46-49）：達獲利目標後取最近 range_bars 根K線高/低點供停利參考，觸及＝影線超過停利點1點。"""
    strat = MAThreeStep(profit_target=20.0, range_bars=3, range_breach_points=1.0)
    df = pd.DataFrame({
        "low": [99.0, 99.0, 95.0, 98.0, 97.0],
        "high": [101.0, 130.0, 126.0, 121.0, 118.0],
    })
    pos = Position(Side.LONG, entry_i=0, entry_price=100.0, stop=90.0, best=130.0)  # 獲利30 >=20
    # 區間(i-3..i-1) 低點最低 95 -> 觸發價 94
    assert strat._range_exit(Context(i=4, df=df, pos=pos, trades=[], stopped=None)) is None  # 本根低點97 > 94
    df.loc[4, "low"] = 93.0
    order = strat._range_exit(Context(i=4, df=df, pos=pos, trades=[], stopped=None))
    assert order is not None and order.reason == "區間高低點停利"


def test_range_exit_floors_at_original_stop_when_window_is_worse():
    """6.5第3點（p.48）：計算出的區間低（高）點比原始停損更不利時，不可移動，須維持原始停損。"""
    strat = MAThreeStep(profit_target=20.0, range_bars=3, range_breach_points=1.0)
    df = pd.DataFrame({
        "low": [99.0, 60.0, 62.0, 65.0, 70.0],  # 區間最低點60，遠劣於原始停損90
        "high": [101.0, 130.0, 126.0, 121.0, 118.0],
    })
    pos = Position(Side.LONG, entry_i=0, entry_price=100.0, stop=90.0, best=130.0)
    order = strat._range_exit(Context(i=4, df=df, pos=pos, trades=[], stopped=None))
    # 停利參考需維持原始停損90（觸發價89），本根低點70已跌破；若誤用區間低點60（觸發價59）則不會出場
    assert order is not None and order.reason == "區間高低點停利"


def test_fixed_points_exit():
    """6.6（p.28）：窄幅盤整適用，達 fixed_exit_points 點即出場。"""
    strat = MAThreeStep(fixed_exit_points=10.0)
    pos = Position(Side.LONG, entry_i=0, entry_price=100.0, stop=90.0, best=111.0)
    df_hit = pd.DataFrame({"close": [100.0, 111.0]})
    assert strat._fixed_points_exit(Context(i=1, df=df_hit, pos=pos, trades=[], stopped=None)) is not None
    df_miss = pd.DataFrame({"close": [100.0, 109.0]})
    assert strat._fixed_points_exit(Context(i=1, df=df_miss, pos=pos, trades=[], stopped=None)) is None


def test_breakeven_exit_after_profit_returns_to_entry():
    """6.7求不賠（p.32-33）：獲利曾達 breakeven_arm_points 後回到進場價，立即出場，優先於 exit_mode。"""
    rows = LONG_BASE + [
        (112, 130, 111, 128),  # 獲利達16點（>=15）→ 求不賠啟動
        (128, 129, 111, 112),  # 收盤回到進場價 → 立即出場
    ]
    bars = make_bars(rows, prev_day=PREV)
    res = run(MAThreeStep(ma_period=3, pivot_level=1, exit_mode="none", breakeven_arm_points=15.0), bars)
    t = res.trades[0]
    assert t.reason_out == "折返停利" and t.exit_price == 112


def _timed(df: pd.DataFrame, minutes_per_bar: int) -> pd.DataFrame:
    df = df.copy()
    df["trade_min"] = [float(k * minutes_per_bar) for k in range(len(df))]
    return df


def test_range_minutes_window_follows_clock_not_bar_count():
    """range_minutes（預設15，書中 1 分K 15 根＝15 分鐘）：5 分K 時只取最近 15 分鐘（3 根）；None 退回 range_bars。"""
    df = _timed(pd.DataFrame({
        "low": [99.0, 95.0, 99.0, 99.0, 98.0, 97.0],
        "high": [101.0, 130.0, 126.0, 121.0, 118.0, 118.0],
    }), 5)
    pos = Position(Side.LONG, entry_i=0, entry_price=100.0, stop=90.0, best=130.0)
    ctx = Context(i=5, df=df, pos=pos, trades=[], stopped=None)
    # 分鐘版：i-3..i-1（10、15、20 分鐘前以內）低點最低 98 → 觸發價 97，本根低點 97 觸及
    order = MAThreeStep(profit_target=20.0, range_minutes=15.0)._range_exit(ctx)
    assert order is not None and order.reason == "區間高低點停利"
    # 根數版（range_bars=15）：區間含第1根低點95 → 觸發價94，不觸及
    assert MAThreeStep(profit_target=20.0, range_minutes=None)._range_exit(ctx) is None


def test_time_stop_minutes_overrides_bars():
    """time_stop_minutes：持倉逾此分鐘仍無獲利即出場（書中約1小時）；5 分K 12 根＝60 分鐘。"""
    df = _timed(pd.DataFrame({"close": [99.0] * 13}), 5)  # 小賠（獲利 < time_stop_min_profit=0）
    pos = Position(Side.LONG, entry_i=0, entry_price=100.0, stop=90.0, best=100.0)
    strat = MAThreeStep(time_stop_minutes=60.0)
    assert strat._time_stop(Context(i=11, df=df, pos=pos, trades=[], stopped=None)) is None  # 55 分鐘
    assert strat._time_stop(Context(i=12, df=df, pos=pos, trades=[], stopped=None)) is not None  # 60 分鐘
    # 根數版照舊；兩者皆未設時關閉
    assert MAThreeStep(time_stop_bars=12)._time_stop(Context(i=12, df=df, pos=pos, trades=[], stopped=None)) is not None
    assert MAThreeStep()._time_stop(Context(i=12, df=df, pos=pos, trades=[], stopped=None)) is None
