from datetime import time

from helpers import make_bars

from wangtrader.core import Side, run
from wangtrader.methods.q2_06_04_rsi_blunt_n_shape import RsiBluntNShape


def _flat(v):
    return (v, v, v, v)


_UP = [10000, 10005, 10010, 10015, 10020, 10025]  # 0-5：上攻，RSI 於第5根達 100（trig，高點10025）

SHORT_CLOSES = _UP + [
    10020, 10015, 10010, 10008, 10010, 10012,  # 6-11：拉回，層級2谷點（p1）在第9根(10008)，第11根確認
    10014, 10005,  # 12-13：反彈後再跌破 p1（10008）→ 第13根收盤跌破 → 放空訊號
]

LONG_CLOSES = [
    10000, 9995, 9990, 9985, 9980, 9975,  # 0-5：下跌，RSI 於第5根觸及 0（trig，低點9975）
    9980, 9985, 9990, 9992, 9990, 9988,  # 6-11：反彈，層級2峰點（p1）在第9根(9992)，第11根確認
    9986, 9995,  # 12-13：拉回後再突破 p1（9992）→ 第13根收盤突破 → 買進訊號
]


def test_short_n_shape_signal():
    res = run(RsiBluntNShape(), make_bars([_flat(c) for c in SHORT_CLOSES]))
    assert len(res.signals) == 1
    sig = res.signals[0]
    assert sig.side == Side.SHORT and sig.reason == "RSI鈍化倒N型"
    assert sig.i == 13 and sig.price == SHORT_CLOSES[13]
    assert sig.stop == 10025  # 停損＝觸發峰位 A（p.234）


def test_long_n_shape_signal():
    res = run(RsiBluntNShape(), make_bars([_flat(c) for c in LONG_CLOSES]))
    assert len(res.signals) == 1
    sig = res.signals[0]
    assert sig.side == Side.LONG and sig.reason == "RSI鈍化正N型"
    assert sig.i == 13 and sig.price == LONG_CLOSES[13]
    assert sig.stop == 9975


def test_stop_modes_follow_p234():
    """p.234：停損可取 A、或均線訊號個位數公式、或兩者較遠者；超過 20 點改用均線訊號公式。"""
    bars = make_bars([_flat(c) for c in SHORT_CLOSES])
    assert run(RsiBluntNShape(stop_mode="ma_signal"), bars).signals[0].stop == 10020  # 10005+(10+5)
    assert run(RsiBluntNShape(stop_mode="combined"), bars).signals[0].stop == 10025  # max(10025, 10020)
    assert run(RsiBluntNShape(stop_points=15), bars).signals[0].stop == 10020  # A 距 20 > 15 → 改用公式


def test_continuation_n_shape_buy_after_overbought():
    """p.235, 237：RSI 觸及 90 後拉回形成谷點，再向上走 N 型（(1) 達 A 高度、(2) 不破 0、收盤過 (1) 與 A）
    → 鈍化續勢買訊；此時倒 N 型可能性已排除。"""
    closes = _UP + [
        10020, 10015, 10010, 10008, 10012, 10016,  # 拉回谷點 0（=p1 10008，第11根確認）
        10022, 10030, 10026, 10022,  # (1) 峰 10030 ≥ A → 倒N型排除；(2) 拉回 10022 > 0
        10024, 10033,  # 收盤 10033 無遮蔽突破 (1) 且過 A → 續勢買訊
    ]
    res = run(RsiBluntNShape(), make_bars([_flat(c) for c in closes]))
    assert [(s.i, s.side, s.reason) for s in res.signals] == [(17, Side.LONG, "RSI鈍化續勢N型")]
    assert res.signals[0].meta["ref_price"] == 10008  # 停損參考＝續勢結構的 0
    assert run(RsiBluntNShape(continuation=False), make_bars([_flat(c) for c in closes])).signals == []


def test_rebound_reaching_trigger_high_cancels_inverse_n():
    """p.235：反彈峰點與 A 同高（或更高）→ 向下倒 N 型的可能性去除；之後跌破谷點不是空訊。"""
    closes = _UP + [
        10020, 10015, 10010, 10008, 10010, 10012,  # p1 = 10008
        10026,  # 反彈達 A 高度以上
        10015, 10005, 10008, 10010,  # 跌破 p1，但倒N型已排除；續勢 N 型的 (2) 也跌破 0 → 兩者皆作廢
    ]
    res = run(RsiBluntNShape(), make_bars([_flat(c) for c in closes]))
    assert res.signals == []


def test_peak_shift_allowed_once_within_window():
    """p.241：拉回谷點形成前，觸發峰可向上位移一次（5 根內），停損參考改為新峰。"""
    closes = _UP + [10020, 10032, 10028, 10024, 10020, 10018, 10020, 10022, 10015]
    res = run(RsiBluntNShape(), make_bars([_flat(c) for c in closes]))
    sig = res.signals[0]
    assert sig.reason == "RSI鈍化倒N型" and sig.meta["trig_i"] == 7 and sig.stop == 10032


def test_peak_shift_beyond_window_invalidates():
    """p.241：位移超過 5 根 K 線才出現的新峰不得採認，本輪作廢（RSI 未再觸及 90 則無新觸發）。"""
    closes = _UP + [10024, 10023, 10022, 10021, 10020, 10019, 10030, 10025, 10020, 10018, 10020, 10022, 10010]
    res = run(RsiBluntNShape(), make_bars([_flat(c) for c in closes]))
    assert res.signals == []


def test_rsi_crossing_opposite_extreme_cancels_round():
    """p.236：自超買區發動的空訊，觀察期間 RSI 不能已穿過嚴重超賣區；穿過即作廢。"""
    closes = _UP + [10015, 10005, 9995, 9985, 9975, 9965, 9955, 9945, 9950, 9955, 9940, 9935, 9945, 9950]
    res = run(RsiBluntNShape(), make_bars([_flat(c) for c in closes]))
    assert all(s.meta["trig_i"] != 5 for s in res.signals)


def test_delay_filter_ignored():
    """F2：訊號因濾網延遲過久（超過 max_delay_bars）才完成 → 忽略。"""
    closes = (
        _UP
        + [10020, 10015, 10010, 10008, 10010, 10012]  # 6-11：point1(10008) 於第11根確認
        + [10012] * 60  # 12-71：長時間盤整（未跌破 10008），逾 max_delay_bars(60) 上限
        + [10005, 9995]  # 72-73：延遲後才出現的跌破，理論上已逾時效
    )
    res = run(RsiBluntNShape(), make_bars([_flat(c) for c in closes]))
    assert res.signals == []


def test_no_entry_after_filter_ignored():
    """F6（推論）：臨近收盤（no_entry_after）忽略訊號。"""
    bars = make_bars([_flat(c) for c in SHORT_CLOSES])
    # 第13根時間為 09:50（08:45 起、5分鐘一根），設定 9:30 後不進場 → 應被忽略
    res = run(RsiBluntNShape(no_entry_after=time(9, 30)), bars)
    assert res.signals == []


def test_gap_filter_blocks_conflicting_direction():
    """F5（推論）：開盤跳空 <10 點（無縫接軌），與跳空方向相反的倒N型空訊忽略（p.244）。"""
    bars = make_bars([_flat(c) for c in SHORT_CLOSES], prev_day=(9990, 9996, 9989, 9995))
    # 跳空 = 開盤10000 - 昨收9995 = 5（<10、且 >=0），與放空方向相反 → 應忽略
    res = run(RsiBluntNShape(gap_filter=True), bars)
    assert res.signals == []
