from helpers import make_bars

from wangtrader.core import Side, run
from wangtrader.methods.q3_01_double_red_black import DoubleRedBlack

PREV = (9990, 10001, 9989, 10000)  # 平盤 10000


def test_top_double_black_immediate_entry():
    bars = make_bars([
        (10000, 10010, 9998, 10008),
        (10008, 10030, 10006, 10028),  # 拉到 +30
        (10028, 10040, 10025, 10027),  # A：當下最高、黑K，低點 10025
        (10027, 10030, 10018, 10022),  # B：黑K 收 10022 < 10025，距極端 18 點 → 頂雙黑
        (10015, 10016, 10000, 10002),
    ], prev_day=PREV)
    res = run(DoubleRedBlack(exit_mode="none"), bars)
    sig = res.signals[0]
    assert sig.side == Side.SHORT and sig.reason == "頂雙黑"
    assert sig.price == 10022 and sig.stop == 10041  # 停損在極端點 10040 上方 1 跳（p.23），風險 19 點


def test_stop_capped_at_stop_points_when_entering_direct():
    bars = make_bars([
        (10000, 10010, 9998, 10008),
        (10008, 10030, 10006, 10028),
        (10028, 10040, 10025, 10027),  # A：極端 10040
        (10027, 10030, 10005, 10008),  # B：距極端 32 點，直接進場 → 停損＝進場價 +20（p.19, 22）
    ], prev_day=PREV)
    res = run(DoubleRedBlack(exit_mode="none", far_entry_mode="direct"), bars)
    sig = res.signals[0]
    assert sig.reason == "頂雙黑(直接進場)" and sig.price == 10008 and sig.stop == 10028


def test_bottom_double_red_needs_pullback_when_far():
    bars = make_bars([
        (10000, 10002, 9985, 9988),
        (9988, 9990, 9960, 9962),
        (9962, 9975, 9950, 9970),   # A：當下最低、紅K，高點 9975
        (9970, 9999, 9968, 9998),   # B：紅K 收 9998 > 9975，距極端 48 點 → 補進場
        (9998, 10000, 9985, 9990),
        (9990, 9992, 9968, 9975),   # 拉回到 9970 → 成交
        (9975, 10010, 9974, 10005),
    ], prev_day=PREV)
    res = run(DoubleRedBlack(exit_mode="none"), bars)
    assert res.signals[0].reason == "底雙紅(補進場)"
    assert res.signals[0].stop == 9950  # 補進場後停損仍在極端點（p.18–20），風險 20 點
    t = res.trades[0]
    assert t.side == Side.LONG and t.entry_price == 9970 and t.entry_i == 6


def test_not_extreme_position_is_ignored():
    bars = make_bars([
        (10000, 10005, 9998, 10004),
        (10004, 10008, 10001, 10002),
        (10002, 10003, 9999, 10000),
    ], prev_day=PREV)
    assert run(DoubleRedBlack(), bars).signals == []


def test_f1_only_applies_when_distance_exceeds_stop_points():
    # 跳高 60 點開盤（距平盤 ≥40 → 極端位置），前兩根就構成頂雙黑；訊號K收盤雖是當下新低，
    # 但距極端只有 16 點，不屬「幅度過大」情境，不應被 F1 剔除（p.18）
    bars = make_bars([
        (10060, 10062, 10050, 10052),  # A：黑K，當下最高
        (10052, 10053, 10044, 10046),  # B：黑K 收 10046 < 10050，距極端 16 點
        (10046, 10048, 10030, 10035),
    ], prev_day=PREV)
    res = run(DoubleRedBlack(exit_mode="none"), bars)
    assert len(res.signals) == 1 and res.signals[0].side == Side.SHORT


def test_f1_filters_far_signal_that_becomes_new_extreme():
    bars = make_bars([
        (10000, 10010, 9998, 10008),
        (10008, 10045, 10006, 10043),
        (10043, 10050, 10035, 10037),  # A：黑K，當下最高 10050
        (10037, 10038, 9985, 9990),    # B：距極端 60 點，且收盤 9990 低於先前盤中最低 9998 → 剔除（p.18–19）
        (9990, 9995, 9980, 9985),
    ], prev_day=PREV)
    assert run(DoubleRedBlack(exit_mode="none"), bars).signals == []


def test_same_side_stopped_once_is_ignored():
    bars = make_bars([
        (10000, 10002, 9985, 9988),
        (9988, 9990, 9960, 9962),
        (9962, 9968, 9950, 9966),   # A：紅K，當下最低 9950
        (9966, 9972, 9964, 9970),   # B：底雙紅，距極端 20 點 → 進場 9970，停損 9950
        (9968, 9969, 9940, 9945),   # 觸停損
        (9945, 9948, 9920, 9925),
        (9925, 9935, 9915, 9932),   # A'：紅K，當下最低
        (9932, 9940, 9930, 9938),   # B'：底雙紅外觀成立，但當日多方已停損過 → 忽略（p.21）
    ], prev_day=PREV)
    res = run(DoubleRedBlack(exit_mode="none"), bars)
    assert len(res.signals) == 1
    assert res.trades[0].reason_out == "停損" and res.trades[0].exit_price == 9950


BASE = [
    (9985, 9990, 9975, 9980),
    (9980, 9982, 9960, 9962),
    (9962, 9968, 9950, 9966),   # A：紅K，當下最低 9950
    (9966, 9972, 9964, 9970),   # B：底雙紅，收 9970，距極端 20 → 立刻進場
    (9970, 9995, 9969, 9993),
]


def test_opposite_signal_not_invading_reverses_position():
    bars = make_bars(BASE + [
        (9993, 9998, 9985, 9990),   # A'：黑K，當下最高 9998
        (9990, 9991, 9975, 9978),   # B'：頂雙黑，收 9978 高於買訊收盤 9970 → 未侵入，平倉反手（p.56）
    ], prev_day=PREV)
    res = run(DoubleRedBlack(exit_mode="none"), bars)
    assert [s.side for s in res.signals] == [Side.LONG, Side.SHORT]
    assert res.trades[0].side == Side.LONG and res.trades[0].reason_out == "反手"
    assert res.trades[1].side == Side.SHORT and res.trades[1].entry_price == 9978
    assert res.signals[1].stop == 9998  # 極端點 9998 + 1 跳 = 9999 但受 20 點上限 → 9998


def test_top_extreme_not_unique_is_ignored():
    # p.17 C3：a 的最高點 10040 與先前 bar0 同高（共頂）→ 極端點非獨一無二，不成立頂雙黑
    bars = make_bars([
        (10000, 10040, 9995, 10010),
        (10010, 10015, 9990, 9995),
        (10005, 10040, 9980, 9985),   # a：黑K，高點與 bar0 同為 10040 → 共頂
        (9985, 9986, 9970, 9975),     # b：黑K，收盤跌破 a 低點，外觀符合但因不唯一而不成立
    ], prev_day=PREV)
    assert run(DoubleRedBlack(), bars).signals == []


def test_retracement_exit_mode():
    bars = make_bars([
        (10000, 10002, 9985, 9988),
        (9988, 9990, 9960, 9962),
        (9962, 9968, 9950, 9966),   # A：紅K，當下最低 9950
        (9966, 9972, 9964, 9970),   # B：底雙紅，進場 9970，停損 9950
        (9970, 9995, 9969, 9993),   # 達獲利目標且雙條件成立（新高9995＋新高收盤9993）→ 停利位置 9995-20=9975
        (9993, 9994, 9970, 9974),   # 收盤 9974 <= 9975 → 折返停利出場
    ], prev_day=PREV)
    res = run(DoubleRedBlack(exit_mode="retracement"), bars)
    t = res.trades[0]
    assert t.side == Side.LONG and t.entry_price == 9970
    assert t.reason_out == "折返停利" and t.exit_price == 9974


def test_opposite_signal_invading_prior_close_is_ignored():
    bars = make_bars(BASE + [
        (9993, 9998, 9985, 9990),   # A'：黑K，當下最高
        (9990, 9991, 9965, 9968),   # B'：頂雙黑外觀成立，但收 9968 ≤ 買訊收盤 9970 → 侵入，忽略（p.56）
    ], prev_day=PREV)
    res = run(DoubleRedBlack(exit_mode="none"), bars)
    assert [s.side for s in res.signals] == [Side.LONG]
    assert res.trades[0].reason_out == "收盤平倉"


def _far_bottom_rows():
    return [
        (10000, 10002, 9985, 9988),
        (9988, 9990, 9960, 9962),
        (9962, 9975, 9950, 9970),   # A：當下最低、紅K
        (9970, 9999, 9968, 9998),   # B：距極端 48 點 → 補進場（限價 9970）
        (9998, 10000, 9985, 9990),  # 第 1 根：未拉回
        (9990, 9992, 9968, 9975),   # 第 2 根：拉回到 9970
        (9975, 10010, 9974, 10005),
    ]


def test_max_wait_minutes_converts_to_bars_by_bar_interval():
    """max_wait_minutes：依K線時間差換成根數；5 分K 下 5 分鐘＝1 根（拉回在第 2 根，已失效），
    10 分鐘＝2 根（成交）；1 分K 下 2 分鐘＝2 根（成交）。"""
    bars5 = make_bars(_far_bottom_rows(), prev_day=PREV)
    assert run(DoubleRedBlack(exit_mode="none", max_wait_minutes=5), bars5).trades == []
    assert run(DoubleRedBlack(exit_mode="none", max_wait_minutes=10), bars5).trades[0].entry_price == 9970
    bars1 = make_bars(_far_bottom_rows(), prev_day=PREV, freq="1min")
    assert run(DoubleRedBlack(exit_mode="none", max_wait_minutes=1), bars1).trades == []
    assert run(DoubleRedBlack(exit_mode="none", max_wait_minutes=2), bars1).trades[0].entry_price == 9970


def test_max_wait_minutes_none_keeps_bar_count():
    """預設 max_wait_minutes=None：沿用 max_wait 根數（預設行為不變）。"""
    bars = make_bars(_far_bottom_rows(), prev_day=PREV)
    assert run(DoubleRedBlack(exit_mode="none", max_wait=1), bars).trades == []
    assert run(DoubleRedBlack(exit_mode="none", max_wait=2), bars).trades[0].entry_price == 9970


def test_wait_bars_minutes_converted_by_bar_interval():
    """max_wait_minutes：以同交易日相鄰K線時間差換成根數；None 或 time 欄非時間戳時用 max_wait 根。"""
    from helpers import make_bars as _mb

    from wangtrader.core import prepare as _prep
    from wangtrader.methods.q3_01_double_red_black import Params as _P, _wait_bars

    df = _prep(_mb([(100, 101, 99, 100)] * 6, freq="3min"))
    assert _wait_bars(df, 5, _P()) == 10
    assert _wait_bars(df, 5, _P(max_wait_minutes=10)) == 3
    assert _wait_bars(df, 5, _P(max_wait_minutes=1)) == 1
    assert _wait_bars(df.assign(time=range(len(df))), 5, _P(max_wait_minutes=10)) == 10
