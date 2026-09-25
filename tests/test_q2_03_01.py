import pandas as pd
from datetime import time

from helpers import make_bars

from wangtrader.core import Context, Position, Side, prepare, run
from wangtrader.methods.q2_03_01_pvt_n_type import PVTNType

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
