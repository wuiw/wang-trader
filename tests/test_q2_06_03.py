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
    # D5 幅度濾網另有專屬測試（test_swing_filter_*），此處聚焦於基本進場/停損機制，關閉 D5
    bars = make_bars([_flat(c) for c in closes])
    res = run(RsiDivergence(swing_points=0.0), bars)
    assert len(res.signals) == 1
    sig = res.signals[0]
    assert sig.side == Side.SHORT
    assert sig.reason == "RSI背離向下"
    assert sig.i == 19
    assert sig.price == closes[19]
    # 端點法(B=10040，距進場20點)、0位法(收盤10020個位數0→+(20-0)=10040，距進場20點)
    # 兩者距離相同且都<=20 → 取較大者：10040（p.225–226）
    assert sig.stop == 10040


def test_long_divergence_signal():
    closes = [
        10000, 9995, 9990, 9985, 9980, 9975,  # 0-5：下跌，RSI 於第5根觸及 0（A，低點9975）
        9980, 9985, 9990, 9992, 9990, 9988, 9986,  # 6-12：反彈破50、層級2峰點在第9根(9992)
        9980, 9970, 9960,  # 13-15：再破 A，B 於第14根形成（9970，RSI>10）
        9965, 9970, 9975, 9980, 9985,  # 16-20：再度上漲，第19根 RSI 突破50 → 進場
    ]
    # D5 幅度濾網另有專屬測試，此處聚焦於基本進場/停損機制，關閉 D5
    bars = make_bars([_flat(c) for c in closes])
    res = run(RsiDivergence(swing_points=0.0), bars)
    assert len(res.signals) == 1
    sig = res.signals[0]
    assert sig.side == Side.LONG
    assert sig.reason == "RSI背離向上"
    assert sig.i == 19
    assert sig.price == closes[19]
    # 端點法(B=9960，距進場20點)、0位法(收盤9980個位數0→-(10+0)=9970，距進場10點)
    # 較大者(端點法20)<=20 → 取較大者：9960（p.225–226）
    assert sig.stop == 9960


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
    # 關閉 D5（與本測試主題無關），以 meta["b_price"] 直接檢驗 B 端點追蹤結果（與停損算法無關）
    bars = make_bars([_flat(c) for c in closes])
    res = run(RsiDivergence(swing_points=0.0), bars)
    assert len(res.signals) == 1 and res.signals[0].meta["b_price"] == 10034


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
    # 關閉 D5（本測試重點在 D4 時間距離規則）
    bars = make_bars([_flat(c) for c in closes])
    res = run(RsiDivergence(swing_points=0.0), bars)
    assert len(res.signals) == 1 and res.signals[0].side == Side.SHORT


def test_swing_filter_blocks_small_amplitude_by_default():
    """D5（p.224）：預設 swing_points=30，A(10025)、B(10040) 幅度僅15點、且無開盤跳空，
    即使其餘條件（含RSI門檻、層級2谷點、時間距離）皆符合，也應忽略。"""
    closes = [
        10000, 10005, 10010, 10015, 10020, 10025,  # A
        10020, 10015, 10010, 10008, 10010, 10012, 10014,  # 拉回破50、層級2谷點
        10020, 10030, 10040,  # B（幅度僅15點）
        10035, 10030, 10025, 10020, 10015,  # RSI 跌破50
    ]
    res = run(RsiDivergence(), make_bars([_flat(c) for c in closes]))
    assert res.signals == []


def test_swing_filter_helper_gap_exemption():
    """D5（p.224）：直接檢驗濾網函式本身——幅度不足時，開盤跳空超過門檻可豁免。"""
    import pandas as pd

    from wangtrader.methods.q2_06_03_rsi_divergence import _passes_swing_filter

    df1 = pd.DataFrame({"sess_open": [10000.0], "prev_close": [9990.0]})  # 跳空僅10點
    assert not _passes_swing_filter(df1, 0, a_price=10025.0, b_price=10040.0, swing_points=30.0)  # 幅度15、跳空10皆不足
    df2 = pd.DataFrame({"sess_open": [10000.0], "prev_close": [9965.0]})  # 跳空35 > 30
    assert _passes_swing_filter(df2, 0, a_price=10025.0, b_price=10040.0, swing_points=30.0)  # 幅度不足但跳空豁免
    df3 = pd.DataFrame({"sess_open": [10100.0], "prev_close": [10100.0]})  # 無跳空
    assert _passes_swing_filter(df3, 0, a_price=10000.0, b_price=10040.0, swing_points=30.0)  # 幅度40本身已足夠


def test_choose_stop_matches_book_examples():
    """p.225–226（★已依補拍頁修正）：兩者皆<=20點時取較大者（圖6-44取8260）；
    圖6-45（0位法8990距11點、端點法8985距17點，皆<=20）取較大者8985。"""
    from wangtrader.methods.q2_06_03_rsi_divergence import _choose_stop, _digit_stop

    # 圖6-44：收盤8270（多單），0位法個位數0 → 8270-(10+0)=8260（距10點），端點法距5點 → 取較大者8260
    assert _digit_stop(8270.0, Side.LONG) == 8260.0
    assert _choose_stop(entry=8270.0, b_price=8265.0, side=Side.LONG, stop_points=20.0) == 8260.0
    # 圖6-45：進場9001，0位法8990（距11點），端點法8985（距16點，書中原文約17點），皆<=20 → 取較大者（端點法）8985
    assert _choose_stop(entry=9001.0, b_price=8985.0, side=Side.LONG, stop_points=20.0) == 8985.0


def test_choose_stop_falls_back_to_nearer_when_farther_exceeds_cap():
    """p.225：若兩者中較大者已超過20點，改採點數較小者。"""
    from wangtrader.methods.q2_06_03_rsi_divergence import _choose_stop

    # 0位法距10點（<=20），端點法距50點（>20）→ 較大者(50)超過20 → 改取較小者：0位法
    stop = _choose_stop(entry=10000.0, b_price=9950.0, side=Side.LONG, stop_points=20.0)
    assert stop == 9990.0  # 0位法：10000-(10+0)=9990
