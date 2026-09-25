from helpers import make_bars

from wangtrader.core import Side, run
from wangtrader.methods.q2_06_03_rsi_divergence import RsiDivergence


def _flat(v):
    return (v, v, v, v)


def test_short_divergence_signal():
    closes = [
        10000, 10005, 10010, 10015, 10020, 10025,  # 0-5：上攻，RSI 於第5根達 100（A，高點10025）
        10020, 10015, 10010, 10008, 10010, 10012, 10014,  # 6-12：拉回破50、層級2谷點在第9根(10008)
        10020, 10030, 10040,  # 13-15：反彈突破 A，B 於第14根形成（10030，RSI<90）
        10035, 10030, 10025, 10020, 10015,  # 16-20：再度下跌，第19根 RSI 跌破50 → 進場
    ]
    bars = make_bars([_flat(c) for c in closes])
    res = run(RsiDivergence(), bars)
    assert len(res.signals) == 1
    sig = res.signals[0]
    assert sig.side == Side.SHORT
    assert sig.reason == "RSI背離向下"
    assert sig.i == 19
    assert sig.price == closes[19]
    assert sig.stop == 10040  # 端點極端值法：B 點＝第二波最高點（第15根 10040，RSI 89.8 < 90）


def test_long_divergence_signal():
    closes = [
        10000, 9995, 9990, 9985, 9980, 9975,  # 0-5：下跌，RSI 於第5根觸及 0（A，低點9975）
        9980, 9985, 9990, 9992, 9990, 9988, 9986,  # 6-12：反彈破50、層級2峰點在第9根(9992)
        9980, 9970, 9960,  # 13-15：再破 A，B 於第14根形成（9970，RSI>10）
        9965, 9970, 9975, 9980, 9985,  # 16-20：再度上漲，第19根 RSI 突破50 → 進場
    ]
    bars = make_bars([_flat(c) for c in closes])
    res = run(RsiDivergence(), bars)
    assert len(res.signals) == 1
    sig = res.signals[0]
    assert sig.side == Side.LONG
    assert sig.reason == "RSI背離向上"
    assert sig.i == 19
    assert sig.price == closes[19]
    assert sig.stop == 9960  # 端點極端值法：B 點＝第二波最低點


def test_time_distance_filter_ignored():
    """F1：A、B 時間距離超過 30 根 → 忽略，訊號不成立。"""
    closes = (
        [10000, 10005, 10010, 10015, 10020, 10025]  # 0-5：A（RSI 100，高點10025）
        + [10020, 10015, 10010, 10008, 10010, 10012, 10014]  # 6-12：拉回破50、層級2谷點
        + [10008] * 30  # 13-42：長時間盤整（RSI 停留在拉回水準不再變動），超過30根上限
        + [10020, 10030, 10040]  # 43-45：延遲後才出現的新高，理論上已逾時效
    )
    bars = make_bars([_flat(c) for c in closes])
    res = run(RsiDivergence(), bars)
    assert res.signals == []


def test_rsi_breach_below_20_filter_ignored_short():
    """F2：空方背離途中 RSI 跌破 20 → 放棄本輪，不構成訊號。"""
    closes = [
        10000, 10005, 10010, 10015, 10020, 10025,  # 0-5：A（RSI 100）
        10015, 10005, 9995, 9985, 9975,  # 6-10：劇烈拉回，RSI 跌破 20
        9985, 9995, 10005, 10015, 10030, 10040,  # 11-16：即使之後反彈創新高
    ]
    bars = make_bars([_flat(c) for c in closes])
    res = run(RsiDivergence(), bars)
    assert res.signals == []


def test_rsi_breach_above_80_filter_ignored_long():
    """F2：多方背離途中 RSI 突破 80 → 放棄本輪，不構成訊號。"""
    closes = [
        10000, 9995, 9990, 9985, 9980, 9975,  # 0-5：A（RSI 0）
        9985, 9995, 10005, 10015, 10025,  # 6-10：劇烈反彈，RSI 突破 80
        10015, 10005, 9995, 9985, 9970, 9960,  # 11-16：即使之後回跌創新低
    ]
    bars = make_bars([_flat(c) for c in closes])
    res = run(RsiDivergence(), bars)
    assert res.signals == []


def test_no_signal_when_never_reaches_extreme():
    """端點未達嚴重超買/超賣門檻，不構成有效端點。"""
    closes = [10000, 10003, 10006, 10009, 10012, 10009, 10006, 10009, 10012, 10015]
    bars = make_bars([_flat(c) for c in closes])
    res = run(RsiDivergence(), bars)
    assert res.signals == []


def test_b_updates_to_highest_point_before_trigger():
    """B 形成後、RSI 跌破 50 前若再創更高點，停損（端點極端值法）應以最高點為 B。"""
    closes = [
        10000, 10005, 10010, 10015, 10020, 10025,  # A
        10020, 10015, 10010, 10008, 10010, 10012, 10014,  # 拉回、層級2谷點
        10020, 10030, 10034,  # B 先於 10030 形成，再推高到 10034（RSI<90）
        10030, 10026, 10022, 10018, 10014,  # RSI 跌破 50 → 進場
    ]
    res = run(RsiDivergence(), make_bars([_flat(c) for c in closes]))
    assert len(res.signals) == 1 and res.signals[0].stop == 10034


def test_second_peak_reaching_extreme_is_not_divergence():
    """B 形成後 RSI 又衝到 90 以上 → 已非背離，該點改為新的 A，不得沿用舊 B 進場。"""
    closes = [
        10000, 10005, 10010, 10015, 10020, 10025,  # A
        10020, 10015, 10010, 10008, 10010, 10012, 10014,
        10020, 10030,  # B
        10040, 10050, 10060, 10070,  # 續強，RSI 回到 90 以上 → 新的 A
        10060, 10050, 10040, 10030,  # RSI 跌破 50，但已無有效背離
    ]
    res = run(RsiDivergence(), make_bars([_flat(c) for c in closes]))
    assert res.signals == []


def test_gap_limit_counts_a_to_b_not_to_trigger():
    """D4（p.227）：30 根限制是兩端點 A、B 的距離，B 之後等待 RSI 穿越 50 的時間不計。"""
    closes = (
        [10000, 10005, 10010, 10015, 10020, 10025]  # A@5
        + [10020, 10015, 10010, 10008, 10010, 10012, 10014]
        + [10020, 10030]  # B@14（距 A 9 根）
        + [10029] * 25  # 盤整 25 根（RSI 緩降但暫未破 50）
        + [10025, 10020, 10015, 10010]  # 之後才跌破 50 → 仍應進場
    )
    res = run(RsiDivergence(), make_bars([_flat(c) for c in closes]))
    assert len(res.signals) == 1 and res.signals[0].side == Side.SHORT
