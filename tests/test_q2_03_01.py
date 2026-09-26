import pandas as pd
from datetime import time

from helpers import make_bars

from wangtrader.core import Context, Position, Side, prepare, run
from wangtrader.methods.q2_03_01_pvt_n_type import PVTNType, _digit_stop

KW = dict(pivot_level=1, ladder_ignore_diff=2.0)

LONG_BASE = [
    (100, 101, 99, 100),
    (100, 101, 95, 97),
    (97, 99, 96, 98),
    (98, 100, 97, 99),
    (99, 100, 90.5, 92),  # 深谷（多趨勢階梯 = 90.5）
    (92, 95, 91, 93),
    (93, 102, 92, 101),  # 峰(1) 102（確認於下一根）
    (101, 101, 99, 100),
    (100, 101, 94, 95),
    (95, 97, 93, 96),  # 谷(2) 93 > 谷(0) 90.5，符合N型
    (96, 98, 95, 97),
    (97, 105, 96, 104),  # 收盤104突破峰(1)102 → 買進訊號
]

SHORT_BASE = [(200 - o, 200 - lo, 200 - h, 200 - c) for (o, h, lo, c) in LONG_BASE]

REVERSAL_ROWS = LONG_BASE + [
    (104, 104, 90.3, 90.3),  # 收盤跌破多趨勢階梯(90.5) → 控盤轉空
    (90.3, 90.8, 90.1, 90.2),
    (90.2, 90.6, 90.15, 90.4),  # 谷(1') 90.1 確認
    (90.4, 95, 90.3, 94.5),
    (94.5, 94.8, 91, 92),  # 峰(2') 95 確認
    (92, 92.5, 90.05, 90.05),  # 收盤90.05跌破谷(1')90.1 → 放空訊號（多單尚未觸及停損90即反手）
]


def test_long_n_type_signal():
    bars = make_bars(LONG_BASE)
    res = run(PVTNType(**KW), bars)
    assert len(res.signals) == 1
    sig = res.signals[0]
    assert sig.side == Side.LONG and sig.reason == "PVT-N型買進"
    assert sig.price == 104
    assert sig.stop == 90  # 個位數公式 104-(10+4)=90；與階梯90.5皆在20點內，取較低者


def test_short_inverse_n_type_signal():
    bars = make_bars(SHORT_BASE)
    res = run(PVTNType(**KW), bars)
    assert len(res.signals) == 1
    sig = res.signals[0]
    assert sig.side == Side.SHORT and sig.reason == "PVT倒N型放空"
    assert sig.price == 200 - 104


def test_f1_pattern_distance_is_filtered():
    bars = make_bars(LONG_BASE)
    res = run(PVTNType(max_pattern_points=10, **KW), bars)  # 實際 (0)到(3) 距離約13.5點
    assert res.signals == []


def test_f2_deviation_from_ladder_is_filtered():
    bars = make_bars(LONG_BASE)
    res = run(PVTNType(max_dev_from_ladder=-1, **KW), bars)
    assert res.signals == []


def test_f3_drift_from_breakout_is_filtered():
    bars = make_bars(LONG_BASE)
    res = run(PVTNType(max_drift_from_breakout=5, **KW), bars)
    assert res.signals == []


def test_f3_bars_from_breakout_is_filtered():
    bars = make_bars(LONG_BASE)
    res = run(PVTNType(max_bars_from_breakout=3, **KW), bars)
    assert res.signals == []


def test_f4_no_entry_after_is_filtered():
    bars = make_bars(LONG_BASE)
    res = run(PVTNType(no_entry_after=time(9, 0), **KW), bars)
    assert res.signals == []


def test_giveback_exit():
    bars = make_bars(LONG_BASE + [(104, 130, 103, 120), (120, 121, 109, 110)])
    res = run(PVTNType(giveback_points=15.0, **KW), bars)
    t = res.trades[0]
    assert t.reason_out == "折返15點停利"
    assert t.exit_price == 110


def test_reversal_flips_position_on_opposite_signal():
    bars = make_bars(REVERSAL_ROWS)
    res = run(PVTNType(giveback_points=1000.0, ladder_exit=False, **KW), bars)
    assert [s.side for s in res.signals] == [Side.LONG, Side.SHORT]
    assert res.trades[0].reason_out == "反手"
    assert res.trades[1].side == Side.SHORT


def test_pvt_ladder_exit_when_profitable():
    """PVT階梯可作為已獲利部位的停利參考（p.108, 6.2）：直接呼叫私有方法驗證，
    因階梯僅單調趨向歷史低點，於精簡情境下難以自然構造「階梯已上移且部位仍獲利」的完整K線序列。"""
    strat = PVTNType(**KW)
    st = strat._fresh()
    st["bull_ladder"] = 110.0
    df = prepare(make_bars([(100, 101, 99, 109)]))
    pos = Position(Side.LONG, entry_i=0, entry_price=100.0, stop=90.0, best=120.0)
    ctx = Context(i=0, df=df, pos=pos, trades=[], stopped=None)
    order = strat._ladder_exit_order(ctx, st)
    assert order is not None and order.reason == "PVT階梯停利"


def test_reseed_uses_only_confirmed_pivots():
    """控盤易主當下重建階梯（p.97）只能用「當根已確認」的峰谷點，不可偷看尚未確認的轉折點。"""
    from wangtrader.methods.q2_03_01_pvt_n_type import _Pivot

    strat = PVTNType(**KW)
    strat._peaks_by_confirm = {
        5: [_Pivot(index=4, confirm=5, price=100.0, kind="peak")],
        8: [_Pivot(index=7, confirm=8, price=101.0, kind="peak")],
        12: [_Pivot(index=11, confirm=12, price=130.0, kind="peak")],  # index<=11 但要到第 12 根才確認
    }
    st = strat._fresh()
    strat._reseed(st, "peak", 11)
    assert st["bear_ladder"] == 101.0  # 若誤用未確認峰點會變成 130


def test_ladder_and_regime_carry_over_to_next_session():
    """階梯與控盤方向跨日延續（p.101 圖3-7：開盤沿用前一日尾盤趨勢階梯）：
    隔日第一根收盤跌破昨日多趨勢階梯即轉空，並可在隔日產生倒N型空訊。"""
    day1 = make_bars(LONG_BASE)
    day2 = make_bars(REVERSAL_ROWS[12:], start="2024-01-03 08:45")
    bars = pd.concat([day1, day2])
    res = run(PVTNType(giveback_points=1000.0, ladder_exit=False, **KW), bars)
    assert [s.side for s in res.signals] == [Side.LONG, Side.SHORT]
    assert res.signals[1].i == len(LONG_BASE) + 5


def test_signal_fires_on_the_bar_that_confirms_point2():
    """谷(2)確認當根若收盤已突破峰(1)，當根即成立，不必再等一根。"""
    rows = list(LONG_BASE[:10]) + [(96, 105, 95, 104)]  # 第 10 根同時確認谷(2)=93 並收盤 104 > 峰(1)102
    res = run(PVTNType(**KW), make_bars(rows))
    assert [s.i for s in res.signals] == [10]


def test_giveback_exit_only_after_profit_target_reached():
    """折返停利須先達到啟動門檻（q2-01 p.22、q2-04-01 p.133），未達門檻前的回落不是「停利」。"""
    rows = LONG_BASE + [(104, 110, 103, 106), (106, 107, 92, 93), (93, 96, 92, 95)]
    res = run(PVTNType(ladder_exit=False, **KW), make_bars(rows))
    assert res.trades and not res.trades[0].reason_out.startswith("折返")


def test_short_stop_formula_matches_book_examples():
    """回歸測試（問題彙整.md C）：空單停損＝收盤+(20−個位數)，個位數0固定20點（p.14，本章p.100沿用第一章公式）。
    先前程式誤用鏡像公式 收盤+(10+個位數)，只有個位數5時數值相同。"""
    assert _digit_stop(Side.SHORT, 7665, 10.0, 20.0) == 7680
    assert _digit_stop(Side.SHORT, 7701, 10.0, 20.0) == 7720
    assert _digit_stop(Side.SHORT, 8636, 10.0, 20.0) == 8650
    assert _digit_stop(Side.SHORT, 7700, 10.0, 20.0) == 7720  # 整數價位固定20點
    assert _digit_stop(Side.LONG, 7905, 10.0, 20.0) == 7890  # 多方公式不變（p.13）


def test_carry_over_enters_next_open_when_stop_not_broken():
    """p.105-106：F4濾掉的訊號，隔日開盤第一根未跌破停損 → 沿用進場，停損不變。"""
    day1 = make_bars(LONG_BASE)
    day2 = make_bars([(104, 106, 100, 105)], start="2024-01-03 08:45")  # 低點100 > 停損90，未跌破
    bars = pd.concat([day1, day2])
    res = run(PVTNType(no_entry_after=time(0, 0), **KW), bars)
    assert len(res.signals) == 1
    sig = res.signals[0]
    assert sig.side == Side.LONG and sig.reason == "PVT-N型買進(隔日延續)" and sig.stop == 90
    t = res.trades[0]
    assert t.entry_price == 105  # 隔日開盤第一根收盤價進場


def test_carry_over_discarded_when_stop_broken():
    """p.105-106：隔日開盤第一根已跌破停損位置 → 訊號作廢，不進場。"""
    day1 = make_bars(LONG_BASE)
    day2 = make_bars([(104, 106, 85, 90)], start="2024-01-03 08:45")  # 低點85 <= 停損90 → 已跌破
    bars = pd.concat([day1, day2])
    res = run(PVTNType(no_entry_after=time(0, 0), **KW), bars)
    assert res.signals == []


def test_same_direction_reentry_after_exit_without_regime_switch():
    """p.106：控盤未易主（PVT階梯未被突破）時，第一次訊號停利出場後，可重新尋找同方向結構再進場，
    狀態機以前次(2)點接續作為新(0)點延續判斷（無需另立分支）。"""
    rows = LONG_BASE + [
        (104, 112, 103, 111),
        (111, 112, 104, 105),  # 觸發折返5點停利出場（收盤105）
        (105, 108, 100, 103),
        (103, 106, 104, 105),
        (105, 118, 104, 117),  # 收盤117突破新峰位112 → 第二次買進訊號
    ]
    bars = make_bars(rows)
    res = run(PVTNType(giveback_points=5.0, ladder_exit=False, **KW), bars)
    assert [s.side for s in res.signals] == [Side.LONG, Side.LONG]
    assert res.trades[0].reason_out.startswith("折返")
    assert res.trades[1].side == Side.LONG and res.trades[1].entry_price == 117


def test_reentry_keeps_first_stop_by_default():
    """p.124（圖3-33）：「無論拉軟，可以A買訊的停損為基準，在B補進場，停損位置不變」——
    同段控盤內第二次（B）進場預設沿用第一次（A）的停損，不依B自己的收盤價重新計算。"""
    rows = LONG_BASE + [
        (104, 112, 103, 111),
        (111, 112, 104, 105),  # 觸發折返5點停利出場（收盤105）
        (105, 108, 100, 103),
        (103, 106, 104, 105),
        (105, 118, 104, 117),  # 收盤117突破新峰位112 → 第二次買進訊號
    ]
    bars = make_bars(rows)
    res = run(PVTNType(giveback_points=5.0, ladder_exit=False, **KW), bars)
    assert [s.stop for s in res.signals] == [90, 90]


def test_reentry_keep_stop_false_recomputes_each_time():
    """reentry_keep_stop=False 時還原為逐次依當根收盤重新計算停損。"""
    rows = LONG_BASE + [
        (104, 112, 103, 111),
        (111, 112, 104, 105),
        (105, 108, 100, 103),
        (103, 106, 104, 105),
        (105, 118, 104, 117),
    ]
    bars = make_bars(rows)
    res = run(PVTNType(giveback_points=5.0, ladder_exit=False, reentry_keep_stop=False, **KW), bars)
    stops = [s.stop for s in res.signals]
    assert stops[0] == 90
    assert stops[1] != 90


def test_reentry_stop_resets_after_regime_switch():
    """控盤易主（regime切換）後應重新起算停損，不沿用前一段控盤的舊值（p.124：「同段控盤」內才不重新計算）。"""
    bars = make_bars(REVERSAL_ROWS)
    res = run(PVTNType(giveback_points=1000.0, ladder_exit=False, **KW), bars)
    assert [s.side for s in res.signals] == [Side.LONG, Side.SHORT]
    assert res.signals[0].stop == 90
    assert res.signals[1].stop != 90  # 新一段（空方）控盤重新計算，不沿用多方停損


def test_f2_exception_when_point2_is_within_threshold_at_confirmation():
    """p.107：(0)距階梯原本超過門檻，但確認(3)時(2)距當時階梯已在門檻內 → 訊號仍視為有效。"""
    from wangtrader.methods.q2_03_01_pvt_n_type import _Pivot

    strat = PVTNType(max_dev_from_ladder=20.0, max_pattern_points=1000.0,
                      max_drift_from_breakout=1000.0, max_bars_from_breakout=1000, **KW)
    st = strat._fresh()
    st["bull_ladder"] = 100.0
    st["breakout_price"] = 100.0
    st["breakout_i"] = 0
    c0 = _Pivot(index=0, confirm=1, price=130.0, kind="trough")  # (0)距階梯30點 >20 門檻

    st["LONG"]["c2"] = _Pivot(index=5, confirm=6, price=115.0, kind="trough")  # (2)距階梯15 ≤20 → 例外成立
    assert strat._passes_filters(pd.DataFrame({"close": [140.0]}), 0, c0, 140.0, st, Side.LONG) is True

    st["LONG"]["c2"] = _Pivot(index=5, confirm=6, price=125.0, kind="trough")  # (2)距階梯25 也超過門檻 → 無例外
    assert strat._passes_filters(pd.DataFrame({"close": [140.0]}), 0, c0, 140.0, st, Side.LONG) is False
