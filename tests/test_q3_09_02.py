from helpers import make_bars

from wangtrader.core import Side, run
from wangtrader.methods.q3_09_02_flat_dragonfly import FlatDragonfly

PREV = (9990, 10001, 9989, 10000)  # 平盤 10000


def test_buy_signal_basic():
    bars = make_bars([
        (10000, 10010, 9998, 10008),
        (10008, 10030, 10006, 10028),  # 距平盤30點，符合 C1
        (10025, 10028, 9995, 9998),    # A：僅一根黑K跌破平盤
        (9998, 10006, 9996, 10003),    # B：紅K收盤收回平盤之上 → 買訊
    ], prev_day=PREV)
    res = run(FlatDragonfly(exit_mode := None) if False else FlatDragonfly(), bars)
    sig = res.signals[0]
    assert sig.side == Side.LONG and sig.reason == "平盤蜻蜓點水買訊"
    assert sig.price == 10003 and sig.stop == 9983


def test_sell_signal_basic():
    bars = make_bars([
        (10000, 10002, 9990, 9992),
        (9992, 9994, 9970, 9972),      # 距平盤30點，符合 C1'
        (9975, 10005, 9972, 10002),    # A：僅一根紅K突破平盤
        (10002, 10004, 9994, 9997),    # B：黑K收盤收回平盤之下 → 空訊
    ], prev_day=PREV)
    res = run(FlatDragonfly(), bars)
    sig = res.signals[0]
    assert sig.side == Side.SHORT and sig.reason == "平盤蜻蜓點水空訊"
    assert sig.price == 9997 and sig.stop == 10017


def test_f1_two_bars_crossing_is_ignored():
    bars = make_bars([
        (10000, 10010, 9998, 10008),
        (10008, 10030, 10006, 10028),
        (10025, 10028, 9990, 9995),  # 第一根黑K跌破平盤
        (9995, 9998, 9985, 9990),    # 第二根黑K仍在平盤之下（連續兩根，不符合F1）
        (9990, 10005, 9988, 10002),  # 收紅回到平盤之上
    ], prev_day=PREV)
    assert run(FlatDragonfly(), bars).signals == []


def test_f2_giant_bar_is_ignored():
    bars = make_bars([
        (10000, 10010, 9998, 10008),
        (10008, 10030, 10006, 10028),
        (10025, 10028, 9995, 9998),
        (9998, 10070, 9996, 10003),  # B 波動達74點，屬超大K線
    ], prev_day=PREV)
    assert run(FlatDragonfly(), bars).signals == []


def test_f3_wrong_extreme_position_is_ignored():
    bars = make_bars([
        (10000, 10010, 9998, 10008),
        (10008, 10030, 10006, 10028),
        (10025, 10028, 9995, 9998),
        (9998, 10028, 9996, 10025),  # B 收盤反而較接近當日最高，不合理
    ], prev_day=PREV)
    assert run(FlatDragonfly(), bars).signals == []


def test_f4_too_many_flat_touches_is_ignored():
    bars = make_bars([
        (10000, 10010, 9998, 10008),   # 觸及平盤第1次
        (10005, 10009, 9997, 10006),   # 觸及平盤第2次
        (10006, 10030, 10004, 10028),
        (10025, 10028, 9995, 9998),    # A
        (9998, 10006, 9996, 10003),    # B
    ], prev_day=PREV)
    assert run(FlatDragonfly(), bars).signals == []


def test_early_exit_before_15_points():
    bars = make_bars([
        (10000, 10010, 9998, 10008),
        (10008, 10030, 10006, 10028),
        (10025, 10028, 9995, 9998),   # A
        (9998, 10006, 9996, 10003),   # B：進場 10003，進場K低點 9996
        (10003, 10005, 9990, 9995),   # 未達15點即跌破進場K影線 9996 → 提前出場
    ], prev_day=PREV)
    res = run(FlatDragonfly(), bars)
    t = res.trades[0]
    assert t.reason_out == "未達15點提前出場" and t.exit_price == 9995 and t.pnl == -8


def test_retrace_exit_after_15_points():
    bars = make_bars([
        (10000, 10010, 9998, 10008),
        (10008, 10030, 10006, 10028),
        (10025, 10028, 9995, 9998),   # A
        (9998, 10006, 9996, 10003),   # B：進場 10003
        (10003, 10020, 10000, 10015),  # 推進到 10020，獲利達17點
        (10015, 10016, 9995, 10000),   # 折返回到進場價 10003 之下
    ], prev_day=PREV)
    res = run(FlatDragonfly(), bars)
    t = res.trades[0]
    assert t.reason_out == "折返停利" and t.exit_price == 10000 and t.pnl == -3


def test_stop_then_reverse_within_60_points():
    bars = make_bars([
        (10000, 10010, 9998, 10008),
        (10008, 10030, 10006, 10028),
        (10025, 10028, 9995, 9998),   # A，低點 9995（反手距離基準）
        (9998, 10006, 9996, 10003),   # B：進場 10003，停損 9983
        (10003, 10005, 9980, 9982),   # 觸及停損 9983，距 A 低點 9995 僅12點 → 反手放空
    ], prev_day=PREV)
    res = run(FlatDragonfly(), bars)
    t0 = res.trades[0]
    assert t0.reason_out == "停損" and t0.exit_price == 9983 and t0.pnl == -20
    sig_rev = res.signals[-1]
    assert sig_rev.side == Side.SHORT and sig_rev.reason == "平盤蜻蜓點水反手"


def test_reversed_position_does_not_chain_reverse_again():
    """反手部位本身停損後，不應再度反手（規格書 p.214-221 只示範單次反手；修 bug 前，反手部位會
    把自己的停損價誤植為下一次的「盤中極端點」，導致距離濾網恆成立、產生連環反手）。"""
    bars = make_bars([
        (10000, 10010, 9998, 10008),
        (10008, 10030, 10006, 10028),
        (10025, 10028, 9995, 9998),   # A，低點 9995
        (9998, 10006, 9996, 10003),   # B：進場 10003，停損 9983
        (10003, 10005, 9980, 9982),   # 觸及停損 9983 → 反手放空 9982，停損 10002
        (9982, 10005, 9978, 9995),    # 反手空單觸及停損 10002（獲利未達15點）
    ], prev_day=PREV)
    res = run(FlatDragonfly(), bars)
    assert len(res.trades) == 2
    assert res.trades[1].side == Side.SHORT and res.trades[1].reason_out == "停損"
    assert len(res.signals) == 2  # 沒有第三筆「反手」訊號


def test_reverse_distance_measured_from_session_extreme():
    """反手距離（p.215 圖9-25）：多單被停損時量「盤中最高極端點」到停損點，超過 60 點只停損不反手；
    A 棒低點離停損點雖近，也不能作為距離基準。"""
    bars = make_bars([
        (10000, 10010, 9998, 10008),
        (10008, 10080, 10006, 10075),  # 盤中最高 10080
        (10075, 10076, 9995, 9998),    # A：僅一根黑K跌破平盤
        (9998, 10006, 9996, 10003),    # B：買訊，進場 10003，停損 9983
        (10003, 10005, 9980, 9982),    # 觸及停損：距盤中最高點 97 > 60 -> 不反手
    ], prev_day=PREV)
    res = run(FlatDragonfly(), bars)
    assert len(res.trades) == 1 and res.trades[0].reason_out == "停損"
    assert len(res.signals) == 1
