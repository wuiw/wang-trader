"""測試資料以程式化方式產生：先強力上攻（推 K/D 至極端 >80 形成死叉 P1），
拉回（K 曾跌破 50 但不低於 20，再黃金交叉），再以短而急的一波推升過前高（全程 D 不再過 80、
K 不如 P1）形成第二次死叉，即完整的 KD 背離向下放空訊號（多方序列以價格對稱鏡射產生）。
數值序列已用 wangtrader.core.indicators.kd 實際試算校驗過交叉時機與 K/D 數值。
"""
import pandas as pd

from wangtrader.core import Side, run
from wangtrader.methods.q2_06_02_kd_divergence import KdDivergence

PREV = (9990, 10001, 9989, 10000)


def _mk(rows, prev_day=PREV, start="2024-01-02 08:45", freq="1min"):
    recs = []
    t0 = pd.Timestamp(start)
    if prev_day is not None:
        recs.append((t0 - pd.Timedelta(days=1), *prev_day, 0.0))
    for k, r in enumerate(rows):
        recs.append((t0 + k * pd.Timedelta(freq), *r, 0.0))
    return pd.DataFrame(recs, columns=["time", "open", "high", "low", "close", "volume"]).set_index("time")


def _short_rows(extra_chop: bool = False):
    rows, base = [], 10000
    for _ in range(12):
        o = base
        rows.append((o, o + 6, o - 1, o + 5))
        base += 5
    for _ in range(6):
        o = base
        rows.append((o, o + 1, o - 4, o - 3))
        base -= 3
    for _ in range(3):
        o = base
        rows.append((o, o + 1, o, o + 1))
        base += 1
    for step in range(3):  # 第二波須短而急，價格創新高但 D 值來不及再過 80（p.203「D 值不再過 80」）
        o = base
        rows.append((o, o + 7, o - 1, o + 6))
        base += 6
        if extra_chop and step == 0:
            rows.append((base, base + 1, base - 6, base - 5))
            base -= 5
            rows.append((base, base + 7, base - 1, base + 6))
            base += 6
    for _ in range(5):
        o = base
        rows.append((o, o + 1, o - 5, o - 4))
        base -= 4
    return rows


def _mirror_rows(rows, prev_day, m=10000):
    mrows = [(2 * m - o, 2 * m - lo, 2 * m - hi, 2 * m - c) for (o, hi, lo, c) in rows]
    mprev = (2 * m - prev_day[0], 2 * m - prev_day[2], 2 * m - prev_day[1], 2 * m - prev_day[3])
    return mrows, mprev


def test_short_divergence_immediate_entry():
    bars = _mk(_short_rows())
    res = run(KdDivergence(), bars)
    sig = res.signals[0]
    assert sig.side == Side.SHORT and sig.reason == "KD背離向下"
    assert sig.price == 10051 and sig.stop == 10064  # combined 停損＝max(端點B 10064, 均線訊號10062)


def test_long_divergence_immediate_entry():
    mrows, mprev = _mirror_rows(_short_rows(), PREV)
    bars = _mk(mrows, prev_day=mprev)
    res = run(KdDivergence(), bars)
    sig = res.signals[0]
    assert sig.side == Side.LONG and sig.reason == "KD背離向上"
    assert sig.price == 9949 and sig.stop == 9930  # combined 停損＝min(端點B 9936, 均線訊號9930)


def test_extra_cross_violates_c5_no_signal():
    """C5（p.205, 207）：兩個死叉之間只能夾唯一一個金叉；再出現反向交叉即整輪作廢。"""
    from wangtrader.methods.q2_06_02_kd_divergence import Params, _Chain, _track_side

    p = Params()
    df = pd.DataFrame({
        # 第1根死叉(D>80) → 第3根金叉(K曾到45) → 第4根又死叉 → 第5根又金叉（多餘交叉）→ 第7根死叉創新高
        "k": [85.0, 82.0, 45.0, 52.0, 50.0, 54.0, 60.0, 58.0],
        "d": [80.5, 84.0, 60.0, 50.0, 51.0, 52.0, 55.0, 59.0],
        "open": [100.0] * 8, "close": [99.0] * 8,
        "sess_high": [110.0, 110.0, 110.0, 110.0, 110.0, 110.0, 112.0, 112.0], "sess_low": [90.0] * 8,
    })
    chain = _Chain()
    out = [_track_side(chain, df, i, p, is_short=True) for i in range(8)]
    assert all(o is None for o in out) and chain.phase == "idle"


def test_far_stop_uses_pullback_limit_order():
    bars = _mk(_short_rows())
    res = run(KdDivergence(stop_points=5), bars)
    sig = res.signals[0]
    assert sig.reason == "KD背離向下(補進場)"
    assert sig.stop == 10064 and sig.price == 10059  # limit = stop - stop_points


def test_long_position_reverses_on_failed_bounce():
    mrows, mprev = _mirror_rows(_short_rows(), PREV)
    # 進場後小幅反彈(<20點)隨即再破背離端點 B(9936)，應停損反手放空
    mrows += [
        (9949, 9954, 9948, 9952),   # 小反彈，未達20點
        (9952, 9953, 9933, 9935),   # 收盤跌破背離端點 9936 → 反手（未觸及停損 9930）
    ]
    bars = _mk(mrows, prev_day=mprev)
    res = run(KdDivergence(), bars)
    trades = res.trades
    assert len(trades) >= 2
    long_trade = trades[0]
    assert long_trade.side == Side.LONG and long_trade.reason_out == "反手"
    reverse_sig = [s for s in res.signals if s.reason == "倒N型反手"]
    assert reverse_sig and reverse_sig[0].side == Side.SHORT


def test_endpoint_stop_uses_second_endpoint_b():
    """p.209「依背離低點(B)為停損」：端點停損是第二端點 B（本次創新低的極端價），不是前波谷位 P1。"""
    mrows, mprev = _mirror_rows(_short_rows(), PREV)
    res = run(KdDivergence(stop_mode="endpoint"), _mk(mrows, prev_day=mprev))
    sig = res.signals[0]
    assert sig.side == Side.LONG and sig.stop == 9936 and sig.stop < sig.price


def test_pullback_k_must_dip_below_50_at_some_point():
    """C2（p.203）：拉回段 K 值須曾跌破 50（以拉回段 K 值最低點判定），並非只看黃金交叉當根。"""
    from wangtrader.methods.q2_06_02_kd_divergence import Params, _Chain, _track_side

    p = Params()
    df = pd.DataFrame({
        "k": [85.0, 82.0, 78.0, 62.0, 55.0, 58.0],
        "d": [80.5, 84.0, 82.0, 70.0, 60.0, 57.0],  # 第1根死叉(D>80)，第5根金叉（K 最低 55，未跌破 50）
        "open": [100.0] * 6, "close": [100.0] * 6, "sess_high": [110.0] * 6, "sess_low": [90.0] * 6,
    })
    chain = _Chain()
    for i in range(6):
        _track_side(chain, df, i, p, is_short=True)
    assert chain.phase == "idle"  # 未曾跌破 50 → 不成立，回到 idle

    df2 = df.copy()
    df2.loc[3, "k"], df2.loc[3, "d"] = 45.0, 60.0  # 拉回段 K 曾到 45（<50 且 >=20）
    df2.loc[4, "k"], df2.loc[4, "d"] = 48.0, 55.0
    df2.loc[5, "k"], df2.loc[5, "d"] = 56.0, 54.0  # 金叉
    chain2 = _Chain()
    for i in range(6):
        _track_side(chain2, df2, i, p, is_short=True)
    assert chain2.phase == "wait_death"
