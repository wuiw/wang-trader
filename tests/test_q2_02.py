import pandas as pd

from helpers import make_bars

from wangtrader.core import Context, Position, Side, run
from wangtrader.methods.q2_02_sarc import SARC, _digit_stop, _Pivot

KW = dict(pivot_level=1)

# 單調下跌至底部才反轉（避免途中形成假的層級1轉折點），i=6大陽線觸及並翻多，形成峰(1)=102（斷點本身），
# i=11 收盤104突破峰(1) → 買進訊號（見探索腳本驗證）。
LONG_BASE = [
    (100, 100, 98, 99),
    (99, 99, 96, 97),
    (97, 97, 93, 94),
    (94, 94, 91, 92),
    (92, 92, 90.5, 91),
    (91, 92, 90.4, 91.5),
    (91.5, 102, 91, 101),
    (101, 101, 99, 100),
    (100, 101, 94, 95),
    (95, 97, 93, 96),
    (96, 98, 95, 97),
    (97, 105, 96, 104),
]
SHORT_BASE = [(200 - o, 200 - lo, 200 - h, 200 - c) for (o, h, lo, c) in LONG_BASE]

REVERSAL_ROWS = LONG_BASE + [
    (104, 104, 90.3, 90.3),   # SAR翻空
    (90.3, 90.8, 90.1, 90.2),
    (90.2, 90.6, 90.15, 90.4),
    (90.4, 95, 90.3, 94.5),
    (94.5, 94.8, 91, 92),
    (92, 92.5, 90.05, 90.05),  # 收盤90.05跌破谷(1')90.1 → 放空訊號（多單未觸及停損90即反手，低點僅到90.05）
]


def test_long_signal():
    bars = make_bars(LONG_BASE)
    res = run(SARC(**KW), bars)
    assert len(res.signals) == 1
    sig = res.signals[0]
    assert sig.side == Side.LONG and sig.reason == "SARC買進"
    assert sig.price == 104 and sig.stop == 90  # 個位數4 -> 停損104-(10+4)=90


def test_short_signal_mirror():
    bars = make_bars(SHORT_BASE)
    res = run(SARC(**KW), bars)
    assert len(res.signals) == 1
    sig = res.signals[0]
    assert sig.side == Side.SHORT and sig.reason == "SARC放空"
    assert sig.price == 96 and sig.stop == 110  # 個位數6 -> 停損96+(20-6)=110


def test_f1_signal_distance_filtered():
    """F1（p.75, 77）：(0)到(3)距離 > max_signal_points → 忽略。實際距離約13.6點（104−90.4）。"""
    bars = make_bars(LONG_BASE)
    res = run(SARC(max_signal_points=10.0, **KW), bars)
    assert res.signals == []


def test_reversal_flips_position_on_opposite_signal():
    bars = make_bars(REVERSAL_ROWS)
    res = run(SARC(exit_mode="none", breakeven_exit=False, **KW), bars)
    assert [s.side for s in res.signals] == [Side.LONG, Side.SHORT]
    assert res.trades[0].side == Side.LONG and res.trades[0].reason_out == "反手"
    assert res.trades[1].side == Side.SHORT and res.trades[1].entry_price == 90.05


def test_short_stop_formula_matches_book_examples():
    """回歸測試（問題彙整.md C）：空單停損＝收盤+(20−個位數)，個位數0固定20點（p.72-73原文重新明確列出）。
    先前程式誤用鏡像公式 收盤+(10+個位數)，只有個位數5時數值相同。"""
    assert _digit_stop(Side.SHORT, 7665, 10.0, 20.0) == 7680
    assert _digit_stop(Side.SHORT, 7701, 10.0, 20.0) == 7720
    assert _digit_stop(Side.SHORT, 8636, 10.0, 20.0) == 8650
    assert _digit_stop(Side.SHORT, 7700, 10.0, 20.0) == 7720  # 整數價位固定20點
    assert _digit_stop(Side.LONG, 7905, 10.0, 20.0) == 7890  # 多方公式不變（p.13）


def test_f2_same_direction_second_signal_needs_min_swing():
    """F2（p.77-79）：同向趨勢中第二個（以後）訊號，須與前一訊號間夾 same_dir_min_swing 點以上的
    單筆擺動才放行（以兩訊號間K線高低點範圍量測，屬量化詮釋，見模組docstring）。"""
    strat = SARC(same_dir_min_swing=30.0, max_signal_points=1000.0)
    sess = 0
    strat._last_signal_i[sess] = {"LONG": 2, "SHORT": None}

    df_small = pd.DataFrame({"high": [101, 102, 103, 104, 110], "low": [95, 96, 97, 98, 108]})
    assert strat._passes_filters(df_small, 4, sess, Side.LONG, close=104.0, c0=None) is False  # 範圍僅13點

    df_big = pd.DataFrame({"high": [101, 102, 140, 104, 110], "low": [95, 96, 60, 98, 108]})
    assert strat._passes_filters(df_big, 4, sess, Side.LONG, close=104.0, c0=None) is True  # 範圍80點 >=30


def test_pivot_move_cap_abandons_candidate_after_limit():
    """3.4（p.72-73）：濾網最多移動兩次（含首條共3條線），超過即放棄候選，重新尋找新的(1)。"""
    strat = SARC(max_pivot_moves=2, pivot_level=1)
    strat._peaks_by_confirm = {5: [_Pivot(index=4, confirm=5, price=110.0, kind="peak")]}
    st = strat._fresh_side()
    st.update(active=True, break_i=0, c0=None,
               c1=_Pivot(index=1, confirm=2, price=100.0, kind="peak"),
               phase="c3", max_high=100.0, move_count=2)
    df = pd.DataFrame({
        "close": [0, 0, 0, 0, 0, 90.0],
        "high": [0, 0, 0, 0, 0, 91.0],
        "low": [0, 0, 0, 0, 0, 89.0],
        "sar_trend": [0, 1, 1, 1, 1, 1],
    })
    result = strat._step_side(Side.LONG, st, df, 5)
    assert result is None
    assert st["c1"] is None and st["phase"] == "c1" and st["move_count"] == 0


def test_pivot_moves_to_more_extreme_point_within_cap():
    """3.3.1類推：折返段出現更極端峰位時移動C1，只要未超過移動上限。"""
    strat = SARC(max_pivot_moves=2, pivot_level=1)
    strat._peaks_by_confirm = {5: [_Pivot(index=4, confirm=5, price=110.0, kind="peak")]}
    st = strat._fresh_side()
    st.update(active=True, break_i=0, c0=None,
               c1=_Pivot(index=1, confirm=2, price=100.0, kind="peak"),
               phase="c3", max_high=100.0, move_count=0)
    df = pd.DataFrame({
        "close": [0, 0, 0, 0, 0, 90.0],
        "high": [0, 0, 0, 0, 0, 91.0],
        "low": [0, 0, 0, 0, 0, 89.0],
        "sar_trend": [0, 1, 1, 1, 1, 1],
    })
    strat._step_side(Side.LONG, st, df, 5)
    assert st["c1"].price == 110.0 and st["move_count"] == 1


def test_ladder_exit_trailing_stop():
    """6.1（p.81-83）：達獲利目標後，收盤與最高點同創新高才移動停利線；觸及超過1點即出場。"""
    strat = SARC(profit_target=20.0, trail_points=20.0, trail_breach_points=1.0)
    df = pd.DataFrame({
        "close": [112.0, 120.0, 135.0, 113.0],
        "high": [113.0, 120.0, 135.0, 134.0],
        "low": [111.0, 119.0, 119.0, 110.0],
    })
    pos = Position(Side.LONG, entry_i=0, entry_price=112.0, stop=90.0, best=112.0)

    pos.best = max(pos.best, df.at[1, "high"])  # 獲利8 <20
    assert strat._ladder_exit(Context(i=1, df=df, pos=pos, trades=[], stopped=None)) is None

    pos.best = max(pos.best, df.at[2, "high"])  # 獲利23>=20且創新高 -> 停利線135-20=115
    assert strat._ladder_exit(Context(i=2, df=df, pos=pos, trades=[], stopped=None)) is None

    pos.best = max(pos.best, df.at[3, "high"])  # 低點110跌破115逾1點 -> 出場
    order = strat._ladder_exit(Context(i=3, df=df, pos=pos, trades=[], stopped=None))
    assert order is not None and order.reason == "固定點數移動停利"


def test_range_exit_uses_recent_window():
    """6.2（p.84）：達獲利目標後取最近 range_bars 根K線高/低點供停利參考，觸及超過1點即出場。"""
    strat = SARC(profit_target=20.0, range_bars=3, range_breach_points=1.0)
    df = pd.DataFrame({
        "low": [99.0, 99.0, 95.0, 98.0, 97.0],
        "high": [101.0, 130.0, 126.0, 121.0, 118.0],
    })
    pos = Position(Side.LONG, entry_i=0, entry_price=100.0, stop=90.0, best=130.0)
    assert strat._range_exit(Context(i=4, df=df, pos=pos, trades=[], stopped=None)) is None
    df.loc[4, "low"] = 93.0
    order = strat._range_exit(Context(i=4, df=df, pos=pos, trades=[], stopped=None))
    assert order is not None and order.reason == "區間高低點停利"


def test_breakeven_exit_after_profit_returns_to_entry():
    """求不賠（p.82，6.4）：達 profit_target 後獲利回落至進場價（或以下）即出場，優先於 exit_mode。"""
    rows = LONG_BASE + [
        (104, 130, 103, 128),  # 獲利達26點（>=20）→ 求不賠啟動
        (128, 129, 100, 101),  # 收盤跌破進場價104 → 立即出場
    ]
    bars = make_bars(rows)
    res = run(SARC(exit_mode="none", breakeven_exit=True, **KW), bars)
    t = res.trades[0]
    assert t.reason_out == "折返停利" and t.exit_price == 101


def _timed(df: pd.DataFrame, minutes_per_bar: int) -> pd.DataFrame:
    df = df.copy()
    df["trade_min"] = [float(k * minutes_per_bar) for k in range(len(df))]
    return df


def test_range_minutes_window_follows_clock_not_bar_count():
    """range_minutes（預設20，書中 1 分K 20 根＝20 分鐘）：5 分K 時只取最近 20 分鐘（4 根）；None 退回 range_bars。"""
    df = _timed(pd.DataFrame({
        "low": [99.0, 95.0, 99.0, 99.0, 99.0, 98.0, 97.0],
        "high": [101.0, 130.0, 126.0, 121.0, 120.0, 118.0, 118.0],
    }), 5)
    pos = Position(Side.LONG, entry_i=0, entry_price=100.0, stop=90.0, best=130.0)
    ctx = Context(i=6, df=df, pos=pos, trades=[], stopped=None)
    order = SARC(profit_target=20.0, range_minutes=20.0)._range_exit(ctx)  # 區間 i-4..i-1 最低98 → 觸發97
    assert order is not None and order.reason == "區間高低點停利"
    assert SARC(profit_target=20.0, range_minutes=None)._range_exit(ctx) is None  # 20 根含低點95 → 觸發94


def test_time_stop_minutes_overrides_bars():
    """time_stop_minutes：持倉逾此分鐘仍無獲利即出場（書中約30-60分鐘）。"""
    df = _timed(pd.DataFrame({"close": [99.0] * 7}), 5)
    pos = Position(Side.LONG, entry_i=0, entry_price=100.0, stop=90.0, best=100.0)
    strat = SARC(time_stop_minutes=30.0)
    assert strat._time_stop(Context(i=5, df=df, pos=pos, trades=[], stopped=None)) is None  # 25 分鐘
    assert strat._time_stop(Context(i=6, df=df, pos=pos, trades=[], stopped=None)) is not None  # 30 分鐘
    assert SARC()._time_stop(Context(i=6, df=df, pos=pos, trades=[], stopped=None)) is None  # 預設關閉
