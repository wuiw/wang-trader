from datetime import time

from helpers import make_bars

from wangtrader.core import Side, run
from wangtrader.methods.q3_10_rsi_diff import RsiDiffSignal

PREV = (9990, 10001, 9989, 10000)  # 平盤 10000


def test_short_signal_basic():
    bars = make_bars([
        (9998, 10008, 9996, 10000),
        (10003, 10013, 10001, 10005),
        (10008, 10018, 10006, 10010),
        (10016, 10021, 10014, 10018),
        (10026, 10031, 10024, 10028),
        (10038, 10043, 10036, 10040),  # A：盤中最高K線，RSI由升轉降之峰點
        (10039, 10042, 10027, 10029),  # B：隔根RSI重挫 >=20 → 負差空訊
    ], prev_day=PREV)
    res = run(RsiDiffSignal(), bars)
    sig = res.signals[0]
    assert sig.side == Side.SHORT and sig.reason == "RSI負差空訊"
    assert sig.price == 10029 and sig.stop == 10063


def test_long_signal_basic():
    bars = make_bars([
        (10002, 10004, 9997, 10000),
        (9997, 9999, 9992, 9995),
        (9992, 9994, 9987, 9990),
        (9984, 9986, 9979, 9982),
        (9974, 9976, 9969, 9972),
        (9962, 9964, 9957, 9960),   # A：盤中最低K線，RSI由降轉升之谷點
        (9961, 9973, 9958, 9971),   # B：隔根RSI大幅上勾 >=20 → 正差買訊
    ], prev_day=PREV)
    res = run(RsiDiffSignal(), bars)
    sig = res.signals[0]
    assert sig.side == Side.LONG and sig.reason == "RSI正差買訊"
    assert sig.price == 9971 and sig.stop == 9937


def test_f1_first_bar_of_session_ignored():
    # rsi_period=1 讓RSI只看前一根方向，第一根即可算出非NaN值，藉此單獨驗證F1（開盤首根不可作依據）
    bars = make_bars([
        (10000, 10040, 9998, 10035),  # bar_no0：技術上符合極端＋RSI條件，但為開盤第一根
        (10035, 10038, 10010, 10020),
    ], prev_day=PREV)
    assert run(RsiDiffSignal(rsi_period=1), bars).signals == []


def test_f2_rsi_not_true_turning_point_ignored():
    bars = make_bars([
        (10000, 10004, 9998, 10001),
        (10001, 10008, 9999, 10005),
        (10005, 10015, 10003, 10012),
        (10012, 10028, 10008, 10025),
        (10025, 10037, 10020, 10035),  # 真正峰值（RSI=100）
        (10035, 10038, 10027, 10032),  # 當下最高K線，但RSI已提前下彎（非由升轉降之轉折點）
        (10032, 10032, 10013, 10018),  # 隔根RSI續跌 >=20，但不應算訊號
    ], prev_day=PREV)
    assert run(RsiDiffSignal(), bars).signals == []


def test_f3_not_extreme_position_ignored():
    bars = make_bars([
        (9999, 10001, 9998, 10000),
        (10001, 10003, 10000, 10002),
        (10003, 10005, 10002, 10004),
        (10006, 10008, 10005, 10007),
        (10010, 10012, 10009, 10011),
        (10015, 10017, 10014, 10016),  # 震幅僅19點，未達30點極端條件
        (10016, 10017, 10007, 10008),
    ], prev_day=PREV)
    assert run(RsiDiffSignal(), bars).signals == []


def test_f4_max_risk_too_large_ignored():
    bars = make_bars([
        (9998, 10008, 9996, 10000),
        (10003, 10013, 10001, 10005),
        (10008, 10018, 10006, 10010),
        (10016, 10021, 10014, 10018),
        (10026, 10031, 10024, 10028),
        (10038, 10043, 10012, 10040),
        (10039, 10042, 10008, 10010),  # 距停損價53點，超過max_risk(40)
    ], prev_day=PREV)
    assert run(RsiDiffSignal(), bars).signals == []


def test_f5_no_entry_after_cutoff():
    bars = make_bars([
        (9998, 10008, 9996, 10000),
        (10003, 10013, 10001, 10005),
        (10008, 10018, 10006, 10010),
        (10016, 10021, 10014, 10018),
        (10026, 10031, 10024, 10028),
        (10038, 10043, 10036, 10040),
        (10039, 10042, 10027, 10029),  # 訊號時間 09:15
    ], prev_day=PREV)
    assert run(RsiDiffSignal(no_entry_after=time(9, 10)), bars).signals == []


def test_f6_no_repeat_after_same_day_loss():
    bars = make_bars([
        (10000, 10022, 9995, 10020),
        (10020, 10052, 10018, 10050),   # A1
        (10050, 10051, 10040, 10048),   # B1：第一次空訊 10048
        (10048, 10075, 10045, 10070),   # 觸及停損 10072 → 第一筆虧損收場
        (10070, 10095, 10068, 10090),
        (10090, 10120, 10085, 10115),   # A2：新高，RSI再度轉折
        (10115, 10116, 10100, 10108),   # B2：技術上又是負差空訊，但同日同側已有虧損 → 應忽略
    ], prev_day=PREV)
    res = run(RsiDiffSignal(rsi_period=1, reverse_max_from_flat=0), bars)
    assert len(res.signals) == 1
    assert len(res.trades) == 1 and res.trades[0].pnl < 0


def test_retrace_exit_after_confirmed():
    bars = make_bars([
        (10000, 10022, 9995, 10020),
        (10020, 10063, 10015, 10060),   # A
        (10060, 10061, 10045, 10050),   # B：進場放空 10050，停損 10083
        (10050, 10052, 10015, 10020),   # 獲利曾達35點（已確認）
        (10020, 10060, 10018, 10055),   # 折返回到進場價之上 → 折返停利出場
    ], prev_day=PREV)
    res = run(RsiDiffSignal(rsi_period=1), bars)
    t = res.trades[0]
    assert t.reason_out == "折返停利" and t.exit_price == 10055 and t.pnl == -5


def test_reverse_when_unconfirmed_and_within_100():
    bars = make_bars([
        (9998, 10008, 9996, 10000),
        (10003, 10013, 10001, 10005),
        (10008, 10018, 10006, 10010),
        (10016, 10021, 10014, 10018),
        (10026, 10031, 10024, 10028),
        (10038, 10043, 10012, 10040),
        (10039, 10042, 10027, 10029),  # 進場放空 10029，停損 10063
        (10029, 10065, 10025, 10060),  # 未確認（獲利未達15點）即觸及停損，距平盤63點 <=100 → 反手
    ], prev_day=PREV)
    res = run(RsiDiffSignal(), bars)
    t0 = res.trades[0]
    assert t0.reason_out == "停損" and t0.pnl == -34
    rev = res.signals[-1]
    assert rev.side == Side.LONG and rev.reason == "RSI差值反手" and rev.stop == 10023


def test_no_reverse_when_distance_over_100():
    bars = make_bars([
        (10000, 10105, 9998, 10100),
        (10100, 10260, 10095, 10250),   # A：新高
        (10250, 10251, 10238, 10245),   # B：進場放空 10245，停損 10280
        (10245, 10285, 10240, 10260),   # 觸及停損，距平盤280點 >100 → 僅停損不反手
    ], prev_day=PREV)
    res = run(RsiDiffSignal(rsi_period=1), bars)
    assert len(res.signals) == 1
    assert res.trades[0].reason_out == "停損"


def test_no_reverse_when_already_confirmed():
    bars = make_bars([
        (10000, 10022, 9995, 10020),
        (10020, 10063, 10015, 10060),   # A
        (10060, 10061, 10045, 10050),   # B：進場放空 10050，停損 10083
        (10050, 10052, 10015, 10020),   # 獲利曾達35點 → 已確認
        (10020, 10090, 10018, 10085),   # 單根直接衝破停損 10083（未先觸發折返出場）
    ], prev_day=PREV)
    res = run(RsiDiffSignal(rsi_period=1), bars)
    assert len(res.signals) == 1  # 已確認後反轉，不可反手
    assert res.trades[0].reason_out == "停損"


def test_reverse_on_close_breakout_before_stop_is_hit():
    """未確認訊號：收盤反向突破濾網線（訊號前相對高點）即停損反手，不必等觸及 20 點停損（p.235）。"""
    bars = make_bars([
        (9998, 10008, 9996, 10000),
        (10003, 10013, 10001, 10005),
        (10008, 10018, 10006, 10010),
        (10016, 10021, 10014, 10018),
        (10026, 10031, 10024, 10028),
        (10038, 10043, 10036, 10040),  # A：相對高點 10043
        (10039, 10042, 10027, 10029),  # B：負差空訊，進場 10029，停損 10063
        (10029, 10050, 10025, 10048),  # 收盤 10048 > 10043（高點未達停損）-> 反手追買
    ], prev_day=PREV)
    res = run(RsiDiffSignal(), bars)
    assert res.trades[0].reason_out == "反手" and res.trades[0].exit_price == 10048
    rev = res.signals[-1]
    assert rev.side == Side.LONG and rev.reason == "RSI差值反手" and rev.stop == 10023


def test_stop_without_close_breakout_does_not_reverse():
    """盤中觸及停損但收盤未突破濾網線 -> 只停損，不反手（反手須「收盤突破 A 高點」，p.235）。"""
    bars = make_bars([
        (9998, 10008, 9996, 10000),
        (10003, 10013, 10001, 10005),
        (10008, 10018, 10006, 10010),
        (10016, 10021, 10014, 10018),
        (10026, 10031, 10024, 10028),
        (10038, 10043, 10036, 10040),
        (10039, 10042, 10027, 10029),  # 進場放空 10029，停損 10063
        (10029, 10065, 10025, 10040),  # 上影線觸及停損，收盤 10040 < 10043
    ], prev_day=PREV)
    res = run(RsiDiffSignal(), bars)
    assert len(res.signals) == 1 and res.trades[0].reason_out == "停損"


def test_close_beyond_signal_bar_extreme_confirms_no_reverse():
    """已確認判準 2（p.236）：K線收盤跌破空訊訊號K最低點後，即使未達 15 點獲利，之後反轉觸及停損
    也只能停損、不可反手。"""
    bars = make_bars([
        (9998, 10008, 9996, 10000),
        (10003, 10013, 10001, 10005),
        (10008, 10018, 10006, 10010),
        (10016, 10021, 10014, 10018),
        (10026, 10031, 10024, 10028),
        (10038, 10043, 10036, 10040),
        (10039, 10042, 10027, 10029),  # 訊號K：低點 10027，進場 10029
        (10029, 10030, 10020, 10022),  # 收盤 10022 < 10027 -> 已確認（獲利僅 9 點）
        (10022, 10070, 10020, 10065),  # 觸及停損 10063 且收盤突破 10043，但已確認 -> 不反手
    ], prev_day=PREV)
    res = run(RsiDiffSignal(), bars)
    assert len(res.signals) == 1 and res.trades[0].reason_out == "停損"


def test_c4_flat_rsi_is_not_turning_point():
    """C4（p.234）：RSI 因收盤相同而持平，隔根下彎不算負差空訊；A 收盤續漲才算由升轉降。"""
    flat = make_bars([
        (10000, 10060, 9995, 10020),   # 先留下較高的盤中高點，避免下面持平K本身被判為最高K
        (10020, 10052, 10018, 10050),
        (10050, 10056, 10046, 10050),  # 收盤持平（RSI 水平移動）
        (10050, 10061, 10048, 10050),  # A：新盤中高點，但收盤仍持平，RSI 前後值相同
        (10050, 10051, 10040, 10045),  # B：RSI 下彎 >=20，但 A 非「上漲進行中」-> 不算訊號
    ], prev_day=PREV)
    assert run(RsiDiffSignal(rsi_period=1), flat).signals == []
    rising = make_bars([
        (10000, 10060, 9995, 10020),
        (10020, 10052, 10018, 10050),
        (10050, 10056, 10046, 10050),
        (10050, 10061, 10048, 10051),  # A：收盤續漲，RSI 由升轉降的真正高點
        (10051, 10052, 10040, 10045),  # B：負差空訊（停損 10081，風險 36 <= 40）
    ], prev_day=PREV)
    sig = run(RsiDiffSignal(rsi_period=1), rising).signals[0]
    assert sig.side == Side.SHORT and sig.stop == 10081
