import pandas as pd
from helpers import make_bars

from wangtrader.core import Side, run
from wangtrader.methods.q3_08_02_pig_yang import PigYang

PREV = (10000, 10005, 9995, 10000)


def test_pig_yang_buy_signal():
    """黑K(A)接紅K(B)，B收盤突破A高點且為突破均線後最高K線 -> 豬陽買訊。"""
    bars = make_bars([
        (10000, 10002, 9988, 9990),
        (9990, 9992, 9980, 9985),
        (9985, 10008, 9983, 10005),   # 收盤站上MA10
        (10008, 10009, 10004, 10006),  # A：黑K，下影線在MA之上
        (10006, 10018, 10005, 10015),  # B：紅K，收盤突破A高點，創新高
    ], prev_day=PREV)
    res = run(PigYang(ma_period=3, strict_distance=True, use_retrace=False, use_five_reversal=False), bars)
    sig = res.signals[0]
    assert sig.side == Side.LONG and sig.reason == "豬陽買訊" and sig.stop == 9995  # 收盤 10015 - 20
    t = res.trades[0]
    assert t.entry_price == 10015


def test_pig_yang_sell_signal():
    """紅K(A)接黑K(B)，B收盤跌破A低點且為跌破均線後最低K線 -> 豬陽空訊。"""
    bars = make_bars([
        (10000, 10012, 9998, 10010),
        (10010, 10015, 10008, 10015),
        (10015, 10017, 9992, 9995),   # 收盤跌破MA10
        (9992, 9996, 9990, 9994),      # A：紅K，上影線在MA之下
        (9994, 9995, 9975, 9980),      # B：黑K，收盤跌破A低點，創新低
    ], prev_day=PREV)
    res = run(PigYang(ma_period=3, strict_distance=True, use_retrace=False, use_five_reversal=False), bars)
    sig = res.signals[0]
    assert sig.side == Side.SHORT and sig.reason == "豬陽空訊" and sig.stop == 10000  # 收盤 9980 + 20
    t = res.trades[0]
    assert t.entry_price == 9980


def test_f2_too_close_to_turn_point_ignored():
    """F2：訊號K線收盤離均線轉折點不足10點 -> 忽略（p.182）。"""
    bars = make_bars([
        (10000, 10002, 9988, 9990),
        (9990, 9992, 9980, 9985),
        (9985, 10008, 9983, 10005),  # 轉折點 10005
        (10005, 10007, 10003, 10004),
        (10004, 10009, 10003, 10008),  # 距轉折點僅 3 點
    ], prev_day=PREV)
    assert run(PigYang(ma_period=3, strict_distance=True), bars).signals == []
    res = run(PigYang(ma_period=3, strict_distance=False, use_retrace=False, use_five_reversal=False), bars)
    assert res.signals[0].side == Side.LONG


def test_not_new_extreme_is_ignored():
    """L5：B棒若非突破均線後最高K線，即使黑接紅外觀成立也不算豬陽買訊（p.182，圖8-29之B點）。"""
    bars = make_bars([
        (10000, 10002, 9988, 9990),
        (9990, 9992, 9980, 9985),
        (9985, 10030, 9983, 10005),   # 收盤站上MA10，但本根高點已到 10030（後續攻擊高點）
        (10010, 10011, 10004, 10006),  # A：黑K
        (10006, 10020, 10005, 10015),  # B：紅K突破A高點，但 high=10020 未超過前面已有的10030，非新高
    ], prev_day=PREV)
    assert run(PigYang(ma_period=3, strict_distance=False), bars).signals == []


def test_five_red_first_black_exits_long():
    """出場：連續5根以上紅K（幅度>=40）後首根不創新高的黑K -> 五紅遇首黑平倉（p.185-186）。"""
    bars = make_bars([
        (10000, 10002, 9988, 9990),
        (9990, 9992, 9980, 9985),
        (9985, 10008, 9983, 10005),
        (10008, 10009, 10004, 10006),
        (10006, 10018, 10005, 10015),  # 進場（豬陽買訊）
        (10015, 10025, 10014, 10024),
        (10024, 10035, 10023, 10034),
        (10034, 10045, 10033, 10044),
        (10044, 10055, 10043, 10054),
        (10054, 10065, 10053, 10064),  # 連續五紅K最後一根，當下最高
        (10064, 10064, 10050, 10055),  # 黑K未創新高、未破前低 -> 五紅遇首黑
    ], prev_day=PREV)
    res = run(PigYang(ma_period=3, strict_distance=True, use_retrace=False, use_five_reversal=True), bars)
    t = res.trades[0]
    assert t.reason_out == "五紅遇首黑" and t.exit_i == 11


def test_large_bar_waits_for_pullback_instead_of_huge_stop():
    """大K線（延用均線順向策略 p.162-163）：B棒收盤到反方向極端點距離已超過20點時，20點停損無法
    涵蓋極端點，預設 large_bar_mode="wait" 改掛「極端點-20」補進場限價單、停損設在極端點；
    此處限價未觸及故未成交。"""
    bars = make_bars([
        (10000, 10012, 9998, 10010),
        (10010, 10015, 10008, 10015),
        (10015, 10017, 9992, 9995),
        (9992, 9996, 9990, 9994),      # A：紅K，上影線在MA之下
        (9994, 10060, 9975, 9980),     # B：跌破A低點，但自身高點距收盤達80點，屬大K線
        (9980, 9985, 9970, 9975),      # 之後未觸及補進場限價 10040
    ], prev_day=PREV)
    res = run(PigYang(ma_period=3, strict_distance=True, use_retrace=False, use_five_reversal=False), bars)
    sig = res.signals[0]
    assert sig.reason == "豬陽空訊(補進場)" and sig.price == 10040 and sig.stop == 10060
    assert res.trades == []  # 限價未觸及，未進場


def test_large_bar_midpoint_mode_uses_body_midpoint_stop():
    """large_bar_mode="midpoint" 時大K線直接進場，停損設於B棒實體中點（p.174 圖8-20）。"""
    bars = make_bars([
        (10000, 10012, 9998, 10010),
        (10010, 10015, 10008, 10015),
        (10015, 10017, 9992, 9995),
        (9992, 9996, 9990, 9994),
        (9994, 10060, 9975, 9980),
        (9980, 9985, 9970, 9975),
    ], prev_day=PREV)
    res = run(PigYang(ma_period=3, strict_distance=True, use_retrace=False, use_five_reversal=False,
                       large_bar_mode="midpoint"), bars)
    sig = res.signals[0]
    assert sig.reason == "豬陽空訊(大K線)" and sig.stop == 9987  # mid=(9994+9980)/2
    assert res.trades[0].entry_price == 9980


def test_retrace_exit():
    """折返停利：達初始獲利後由最高獲利回吐 retrace_points 點觸價出場。"""
    bars = make_bars([
        (10000, 10002, 9988, 9990),
        (9990, 9992, 9980, 9985),
        (9985, 10008, 9983, 10005),
        (10008, 10009, 10004, 10006),
        (10006, 10018, 10005, 10015),  # 進場 10015
        (10015, 10035, 10014, 10034),  # 獲利19 > 15
        (10034, 10045, 10033, 10044),  # 最高獲利 30（best 10045）
        (10044, 10045, 10025, 10028),  # 回吐 17 點 >=15 -> 出場
    ], prev_day=PREV)
    res = run(PigYang(ma_period=3, strict_distance=True, use_retrace=True, use_five_reversal=False), bars)
    t = res.trades[0]
    assert t.reason_out == "折返停利" and t.exit_price == 10028


def _two_days(prev, day):
    bars = make_bars(prev + day, prev_day=PREV)
    idx = list(bars.index[: len(prev) + 1]) + [
        pd.Timestamp("2024-01-03 08:45") + k * pd.Timedelta("5min") for k in range(len(day))
    ]
    bars.index = pd.DatetimeIndex(idx)
    return bars


def test_f4_carryover_measures_from_session_low_for_long():
    """F4（p.184）：轉折在前一日的延續開盤，買訊看「收盤距開盤後最低點」<=60，而不是距最高點。"""
    prev = [
        (10000, 10002, 9988, 9990),
        (9990, 9992, 9980, 9985),
        (9985, 10008, 9983, 10005),   # 站上MA（轉折在前一日）
        (10005, 10030, 10003, 10025),
    ]
    day_ok = [
        (10040, 10060, 10038, 10050),
        (10050, 10055, 10045, 10048),  # A：黑K，下影線在MA之上
        (10048, 10070, 10046, 10065),  # B：紅K突破A高點且創新高；距開盤後最低點 27
    ]
    res = run(PigYang(ma_period=3, use_retrace=False, use_five_reversal=False), _two_days(prev, day_ok))
    assert len(res.signals) == 1 and res.signals[0].side == Side.LONG
    day_far = [
        (10040, 10060, 10038, 10050),
        (10050, 10055, 10045, 10048),
        (10048, 10110, 10046, 10105),  # B 收盤距開盤後最低點 67 > 60 -> 忽略
    ]
    assert run(PigYang(ma_period=3), _two_days(prev, day_far)).signals == []
