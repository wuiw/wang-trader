from helpers import make_bars

from wangtrader.core import Side, run
from wangtrader.methods.q3_02_v_reversal import VReversal

PREV = (9990, 10001, 9989, 10000)  # 平盤 10000


def test_bottom_v_immediate_entry():
    bars = make_bars([
        (10000, 10002, 9985, 9988),  # a1：黑K
        (9975, 9976, 9960, 9965),    # a2：當下唯一最低（雙重最低）
        (9965, 9982, 9963, 9979),    # b：紅K，過一高，距極端19點 → 立刻進場
    ], prev_day=PREV)
    res = run(VReversal(), bars)
    sig = res.signals[0]
    assert sig.side == Side.LONG and sig.reason == "底V字"
    assert sig.price == 9979 and sig.stop == 9959  # 停損在極端點 9960 下方 1 跳（p.50「以最低黑K線低點為停損」）


def test_top_inverted_v_large_bar_override():
    bars = make_bars([
        (10000, 10010, 9998, 10008),   # a1：紅K
        (10008, 10040, 10006, 10038),  # a2：當下唯一最高（雙重最高）
        (10038, 10039, 9995, 10000),   # b：長黑（實體38點＞30，超大K線），距實體中點10019僅19點(<20)→直接進場
    ], prev_day=PREV)
    res = run(VReversal(), bars)
    sig = res.signals[0]
    assert sig.side == Side.SHORT and sig.reason == "頂倒V(超大K)"
    assert sig.price == 10000 and sig.stop == 10020


def test_large_bar_tier1_direct_entry():
    # p.53：訊號K本身漲跌幅>20點、收盤離真實極端點在30點以內 → 直接進場，停損=收盤±20（不套用超大K中點）
    bars = make_bars([
        (10000, 10010, 9998, 10008),   # a1：紅K
        (10008, 10030, 10006, 10028),  # a2：當下唯一最高 10030（雙重最高）
        (10028, 10029, 10000, 10004),  # b：黑K，實體24點(>20 但<=30)，距極端 26 點(<=30) → tier1 直接進場
    ], prev_day=PREV)
    res = run(VReversal(), bars)
    sig = res.signals[0]
    assert sig.side == Side.SHORT and sig.reason == "頂倒V(大K直接)"
    assert sig.price == 10004 and sig.stop == 10024


def test_super_large_bar_needs_pullback_to_midpoint():
    # p.53-54：超大K線且距中點 >=20 點 → 等拉回至距中點 20 點內再補進場
    bars = make_bars([
        (10000, 10010, 9998, 10008),   # a1：紅K
        (10008, 10040, 10006, 10038),  # a2：當下唯一最高 10040
        (10038, 10039, 9960, 9970),    # b：超大黑K（實體68點），中點=(10038+9970)/2=10004，距收盤34點(>=20)
        (9990, 9982, 9975, 9980),      # 未拉回到 limit=10004-20=9984（高點9982<9984）
        (9980, 9985, 9975, 9982),      # 拉回觸及 9984（高點9985>=9984）→ 成交
        (9982, 9985, 9975, 9980),
    ], prev_day=PREV)
    res = run(VReversal(exit_mode="none"), bars)
    assert res.signals[0].reason == "頂倒V(超大K補進場)"
    t = res.trades[0]
    assert t.side == Side.SHORT and t.entry_price == 9984 and t.entry_i == 5


def test_time_stall_exit_when_no_progress():
    bars = make_bars(
        [
            (10000, 10002, 9985, 9988),  # a1：黑K
            (9975, 9976, 9960, 9965),    # a2：當下唯一最低（雙重最低）
            (9965, 9982, 9963, 9979),    # b：紅K，過一高，立刻進場 9979，停損 9959
        ]
        + [(9975, 9976, 9970, 9973)] * 12,  # 12 根原地打轉（未破9979新高、未觸9959停損）→ 無進展
        prev_day=PREV,
    )
    res = run(VReversal(exit_mode="none"), bars)
    assert res.trades[0].reason_out == "時間停滯出場"


def test_bottom_v_needs_pullback_when_far():
    bars = make_bars([
        (10000, 10002, 9985, 9988),   # a1
        (9975, 9995, 9960, 9965),     # a2：極端點 9960
        (9998, 10020, 9997, 10015),   # b：距極端55點、實體17點(<30) → 補進場
        (10010, 10012, 10005, 10008),  # 未拉回
        (9985, 9990, 9975, 9982),     # 拉回到 9980 → 成交
        (9982, 9990, 9978, 9985),
    ], prev_day=PREV)
    res = run(VReversal(exit_mode="none"), bars)
    assert res.signals[0].reason == "底V字(補進場)"
    assert res.signals[0].stop == 9960  # 補進場後停損在極端點，風險 20 點
    t = res.trades[0]
    assert t.side == Side.LONG and t.entry_price == 9980 and t.entry_i == 5


BASE = [
    (10000, 10005, 9990, 9995),   # a1：黑K
    (9985, 9987, 9970, 9974),     # a2：當下唯一最低 9970
    (9974, 9990, 9972, 9989),     # b：底V字，收 9989（距極端 19 → 立刻進場）
    (9989, 9995, 9985, 9993),     # a1'：紅K
    (9993, 10008, 9992, 10006),   # a2'：當下唯一最高 10008
]


def test_opposite_signal_invading_prior_close_is_ignored():
    # p.56：D 空訊收盤低於 B 買訊收盤 → 侵入 → 忽略 D
    bars = make_bars(BASE + [
        (10006, 10007, 9985, 9988),   # b'：頂倒V外觀成立，但收 9988 ≤ 買訊收盤 9989 → 忽略
    ], prev_day=PREV)
    res = run(VReversal(), bars)
    assert [s.side for s in res.signals] == [Side.LONG]
    assert res.trades[0].reason_out == "收盤平倉"


def test_opposite_signal_not_invading_reverses_position():
    # p.56：F 空訊收盤未與 B 收盤重疊 → 成立，多單平倉反手
    bars = make_bars(BASE + [
        (10006, 10007, 9989, 9991),   # b'：頂倒V，收 9991 > 9989 且跌破 a2' 低點 9992，距極端 17 → 立刻反手
    ], prev_day=PREV)
    res = run(VReversal(), bars)
    assert [s.side for s in res.signals] == [Side.LONG, Side.SHORT]
    assert res.trades[0].side == Side.LONG and res.trades[0].reason_out == "反手"
    assert res.trades[1].side == Side.SHORT and res.trades[1].entry_price == 9991
    assert res.signals[1].stop == 10009


def test_extreme_point_must_be_unique():
    bars = make_bars([
        (10000, 10005, 9960, 9998),  # 先前已有一根低點9960
        (9998, 9999, 9970, 9975),    # a1：黑K
        (9975, 9976, 9960, 9965),    # a2：低點與第一根同為9960 → 不唯一
        (9970, 9990, 9962, 9985),    # b：外觀符合但因不唯一而不成立
    ], prev_day=PREV)
    assert run(VReversal(), bars).signals == []


def test_second_bar_must_be_genuine_up_candle():
    bars = make_bars([
        (10000, 10010, 9998, 10008),  # a1：紅K
        (10008, 10030, 10005, 10006),  # a2：創新高但收盤未過開盤，不是真正上漲K
        (10006, 10008, 9985, 9990),   # 黑K
    ], prev_day=PREV)
    assert run(VReversal(), bars).signals == []


def test_not_extreme_position_is_ignored():
    bars = make_bars([
        (10000, 10005, 9995, 9998),
        (9998, 9999, 9990, 9993),   # a2：極小範圍
        (9993, 10002, 9991, 10001),  # b：震幅僅12點、距平盤僅15點
    ], prev_day=PREV)
    assert run(VReversal(), bars).signals == []


def test_same_side_stopped_once_is_ignored():
    bars = make_bars([
        (10000, 10002, 9985, 9988),   # a1
        (9975, 9976, 9960, 9965),     # a2：極端 9960
        (9965, 9982, 9963, 9979),     # b：底V字，立刻進場 9979，停損 9959
        (9975, 9977, 9930, 9935),     # 觸停損（跌破9959）
        (9935, 9940, 9910, 9915),     # a1''
        (9915, 9916, 9880, 9885),     # a2''：新的當下最低
        (9885, 9935, 9882, 9930),     # b''：外觀符合底V字，但當日多方已停損過 → 忽略
    ], prev_day=PREV)
    res = run(VReversal(exit_mode="none"), bars)
    assert len(res.signals) == 1
    assert res.trades[0].reason_out == "停損" and res.trades[0].exit_price == 9959


def test_reversal_on_confirmed_breakdown():
    bars = make_bars([
        (10000, 10002, 9985, 9988),  # a1
        (9975, 9976, 9960, 9965),    # a2：極端 9960
        (9965, 9982, 9963, 9979),    # b：底V字，立刻進場 9979，停損 9959
        (9975, 9977, 9930, 9935),    # 觸停損，且收盤9935跌破極端點9960 → 破低反手空訊
        (9935, 9940, 9925, 9930),    # 收盤平倉（當沖）
    ], prev_day=PREV)
    res = run(VReversal(reversal_enabled=True), bars)
    assert len(res.signals) == 2
    assert res.signals[1].side == Side.SHORT and "反手" in res.signals[1].reason
    assert res.signals[1].stop == 9955  # 反手單以進場價 +20 停損
    assert len(res.trades) == 2
    assert res.trades[0].reason_out == "停損"
    assert res.trades[1].side == Side.SHORT and res.trades[1].entry_price == 9935 and res.trades[1].entry_i == 4


def test_reversal_stopped_again_halts_session():
    # p.60：反手單再被停損＝當日連二輸，立即停止操作
    bars = make_bars([
        (10000, 10002, 9985, 9988),
        (9975, 9976, 9960, 9965),     # a2：極端 9960
        (9965, 9982, 9963, 9979),     # 底V字 → 多單 9979，停損 9959
        (9975, 9977, 9930, 9935),     # 停損；收 9935 < 9960 → 反手空 9935，停損 9955
        (9935, 9960, 9933, 9958),     # 反手單觸停損 9955 → 連二輸
        (9958, 9970, 9955, 9968),     # a1：紅K
        (9968, 10010, 9995, 10008),   # a2：當下唯一最高 10010
        (10008, 10009, 9990, 9992),   # b：頂倒V外觀成立（距極端 18），但當日已停止操作 → 忽略
    ], prev_day=PREV)
    res = run(VReversal(reversal_enabled=True), bars)
    assert len(res.signals) == 2 and len(res.trades) == 2
    assert res.trades[1].reason_out == "停損"


def test_wait_bars_minutes_converted_by_bar_interval():
    """max_wait_minutes：以同交易日相鄰K線時間差換成根數；None 或 time 欄非時間戳時用 max_wait 根。"""
    from helpers import make_bars as _mb

    from wangtrader.core import prepare as _prep
    from wangtrader.methods.q3_02_v_reversal import Params as _P, _wait_bars

    df = _prep(_mb([(100, 101, 99, 100)] * 6, freq="3min"))
    assert _wait_bars(df, 5, _P()) == 10
    assert _wait_bars(df, 5, _P(max_wait_minutes=10)) == 3
    assert _wait_bars(df, 5, _P(max_wait_minutes=1)) == 1
    assert _wait_bars(df.assign(time=range(len(df))), 5, _P(max_wait_minutes=10)) == 10
