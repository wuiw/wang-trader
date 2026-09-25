import pandas as pd

from helpers import make_bars

from wangtrader.core import Side, run
from wangtrader.methods.q2_03_02_pvt_rsi import PVTRSISignal, _digit_stop, _Pivot

KW = dict(pivot_level=1, ladder_ignore_diff=2.0, break_points=3.0, retrace_points=3.0, rsi_period=3)

LONG_BASE = [
    (100, 101, 99, 100),
    (100, 101, 95, 97),
    (97, 99, 96, 98),
    (98, 100, 97, 99),
    (99, 100, 90.5, 92),  # 深谷 -> 多趨勢階梯 90.5
    (92, 95, 91, 93),
    (93, 102, 92, 101),  # 突破階梯達3點以上，形成錨點峰位102
    (101, 101, 99, 100),
    (100, 101, 94, 95),  # 折返，RSI 跌破50
    (95, 97, 93, 96),
    (96, 98, 95, 97),  # 折返幅度>3點，RSI 重新站上50（早於過一高）
    (97, 109, 96, 108),  # 收盤108過一高（突破錨點102）→ 買進訊號
    (108, 110, 107, 109),
]

SHORT_BASE = [(200 - o, 200 - lo, 200 - h, 200 - c) for (o, h, lo, c) in LONG_BASE]


def test_long_signal_rsi_recross_before_break():
    bars = make_bars(LONG_BASE)
    res = run(PVTRSISignal(**KW), bars)
    assert len(res.signals) == 1
    sig = res.signals[0]
    assert sig.side == Side.LONG and sig.reason == "PVT+RSI買進"
    assert sig.price == 108
    assert sig.stop == 90  # 個位數公式 108-(10+8)=90，與階梯90.5皆在20點內取較低者


def test_short_signal_mirror():
    bars = make_bars(SHORT_BASE)
    res = run(PVTRSISignal(**KW), bars)
    assert len(res.signals) == 1
    sig = res.signals[0]
    assert sig.side == Side.SHORT and sig.reason == "PVT+RSI放空"
    assert sig.price == 200 - 108


def test_f1_breakout_magnitude_insufficient():
    bars = make_bars(LONG_BASE)
    res = run(PVTRSISignal(break_points=20.0, **{k: v for k, v in KW.items() if k != "break_points"}), bars)
    assert res.signals == []


def test_f1_retrace_magnitude_insufficient():
    bars = make_bars(LONG_BASE)
    res = run(PVTRSISignal(retrace_points=20.0, **{k: v for k, v in KW.items() if k != "retrace_points"}), bars)
    assert res.signals == []


def test_f2_rsi_never_crosses_mid():
    bars = make_bars(LONG_BASE)
    res = run(PVTRSISignal(rsi_mid=-10.0, **{k: v for k, v in KW.items() if k != "rsi_mid"}), bars)
    assert res.signals == []


def test_f4_drift_from_breakout_is_filtered():
    bars = make_bars(LONG_BASE)
    res = run(PVTRSISignal(max_drift_from_breakout=1.0, **KW), bars)
    assert res.signals == []


def test_f3_break_high_before_rsi_recross_delays_entry():
    """3.3：過一高先於RSI重新站上50時，須延後至RSI也滿足才進場；且「過一高」須無遮蔽：
    收盤要高於折返最低點以來所有K線的最高點，只高於錨點但被前面影線遮蔽者不算（p.113, p.118）。
    直接呼叫狀態機驗證（單一大幅反彈K線下 RSI(短週期) 極易與價格同根突破，難以自然構造）。"""
    strat = PVTRSISignal(pivot_level=1)
    leg = strat._fresh_leg()
    leg["phase"] = "watch_c4"
    leg["anchor"] = _Pivot(index=0, confirm=1, price=102.0, kind="peak")
    leg["rsi_dipped"] = True
    leg["extreme"], leg["extreme_i"] = 100.0, 0
    df = pd.DataFrame({
        "close": [103.0, 103.0, 105.0, 107.0],
        "high": [104.0, 106.0, 105.5, 108.0],
        "low": [100.0, 102.0, 104.0, 106.0],
        "rsi": [40.0, 40.0, 55.0, 55.0],
    })
    assert strat._step_leg("LONG", leg, df, 1, breakout_i=0, breakout_level=90.0) is None  # 影線 106 未收上
    assert leg["broke_high"] is False
    r2 = strat._step_leg("LONG", leg, df, 2, breakout_i=0, breakout_level=90.0)
    assert r2 is None and leg["broke_high"] is False and leg["rsi_recrossed"] is True  # 105 > 錨點但被 106 遮蔽
    r3 = strat._step_leg("LONG", leg, df, 3, breakout_i=0, breakout_level=90.0)
    assert r3 == (102.0, 107.0)  # 107 高於 104/106/105.5 → 無遮蔽過一高，RSI 已站上 50 → 成立


def test_anchor_must_exceed_broken_ladder_by_break_points():
    """C1（p.113 圖3-18）：幅度以「當初被跌破的階梯價位」為基準；只跌破 0.4 點的谷位不能當錨點。"""
    rows = LONG_BASE + [
        (108, 108, 90.3, 90.3),  # 收盤跌破多趨勢階梯(90.5) -> 控盤轉空，但只低 0.2
        (90.3, 90.8, 90.1, 90.2),
        (90.2, 90.6, 90.15, 90.4),  # 谷位 90.1 距階梯僅 0.4 < 3 → 不是錨點
        (90.4, 95, 90.3, 94.5),
        (94.5, 94.8, 90.05, 90.05),
    ]
    res = run(PVTRSISignal(giveback_points=1000.0, ladder_exit=False, breakeven_arm_points=1000.0, **KW),
              make_bars(rows))
    assert [s.side for s in res.signals] == [Side.LONG]


def test_giveback_exit():
    bars = make_bars(LONG_BASE + [(108, 125, 107, 124), (124, 126, 109, 110)])
    res = run(PVTRSISignal(giveback_points=15.0, **KW), bars)
    t = res.trades[0]
    assert t.reason_out == "折返15點停利"
    assert t.exit_price == 110


def test_breakeven_exit():
    bars = make_bars(LONG_BASE + [(108, 125, 107, 124), (124, 125, 104, 105)])
    res = run(PVTRSISignal(giveback_points=1000.0, breakeven_arm_points=15.0, **KW), bars)
    t = res.trades[0]
    assert t.reason_out == "折返停利"
    assert t.exit_price == 105


def test_reversal_flips_position_on_opposite_signal():
    rows = LONG_BASE + [
        (108, 108, 86, 86.5),  # 收盤跌破多趨勢階梯(90.5) -> 控盤轉空，被跌破的階梯＝90.5
        (86.5, 87, 85, 85.5),  # 谷位 85：距 90.5 達 5.5 > 3 → 錨點（下一根確認）
        (85.5, 95, 85.5, 94.5),  # 反彈 10 > 3，RSI 站上 50
        (94.5, 96, 93, 95),
        (95, 95.5, 84, 84.5),  # 破一低（低於反彈段所有低點）+ RSI 跌破 50 -> 放空訊號（多單未觸及停損即反手）
    ]
    bars = make_bars(rows)
    res = run(
        PVTRSISignal(giveback_points=1000.0, ladder_exit=False, breakeven_arm_points=1000.0,
                     stop_min_offset=30.0, **KW), bars
    )
    assert [s.side for s in res.signals] == [Side.LONG, Side.SHORT]
    assert res.trades[0].reason_out == "反手"
    assert res.trades[1].side == Side.SHORT


def test_giveback_exit_only_after_profit_target_reached():
    """折返停利須先達啟動門檻（p.118-119「跌超過15點，應可開始啟動停利機制」）。"""
    rows = LONG_BASE[:12] + [(108, 114, 107, 110), (110, 111, 96, 97), (97, 100, 96, 99)]
    res = run(PVTRSISignal(ladder_exit=False, breakeven_arm_points=1000.0, **KW), make_bars(rows))
    assert res.trades and not res.trades[0].reason_out.startswith("折返")


def test_short_stop_formula_matches_book_examples():
    """回歸測試（問題彙整.md C）：空單停損＝收盤+(20−個位數)，個位數0固定20點（p.14，本節推論比照 q2-03-01）。
    先前程式誤用鏡像公式 收盤+(10+個位數)，只有個位數5時數值相同。"""
    assert _digit_stop(Side.SHORT, 7665, 10.0, 20.0) == 7680
    assert _digit_stop(Side.SHORT, 7701, 10.0, 20.0) == 7720
    assert _digit_stop(Side.SHORT, 8636, 10.0, 20.0) == 8650
    assert _digit_stop(Side.SHORT, 7700, 10.0, 20.0) == 7720  # 整數價位固定20點
    assert _digit_stop(Side.LONG, 7905, 10.0, 20.0) == 7890  # 多方公式不變（p.13）
