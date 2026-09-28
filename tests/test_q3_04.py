from helpers import make_bars

from wangtrader.core import Side, run
from wangtrader.methods.q3_04_tit_for_tat import TitForTat

PREV = (9990, 10001, 9989, 10000)  # 平盤 10000
LOW_BAR = (9990, 9992, 9975, 9985)  # 先拉出 30 點以上震幅（極端位置前提，p.84）
HIGH_BAR = (10020, 10025, 10010, 10012)


def test_tit_for_tat_short_signal():
    bars = make_bars([
        LOW_BAR,
        (10000, 10020, 9998, 10015),  # A：當下最高（雙重最高），紅K，漲15點
        (10015, 10016, 9998, 10000),  # B：黑K，跌15點，差距0點，距極端20點 → 立刻進場
    ], prev_day=PREV)
    res = run(TitForTat(), bars)
    sig = res.signals[0]
    assert sig.side == Side.SHORT and sig.reason == "以牙還牙空訊"
    assert sig.price == 10000 and sig.stop == 10020  # 極端點 10020+1 跳，但距進場價最多 20 → 10020


def test_tit_for_tat_long_signal():
    bars = make_bars([
        HIGH_BAR,
        (10000, 10002, 9985, 9988),  # A：當下最低（雙重最低），黑K，跌12點
        (9988, 10001, 9987, 10000),  # B：紅K，漲12點，差距0點
    ], prev_day=PREV)
    res = run(TitForTat(), bars)
    sig = res.signals[0]
    assert sig.side == Side.LONG and sig.reason == "以牙還牙買訊"
    assert sig.price == 10000 and sig.stop == 9984  # 停損在 A 低點 9985 下方 1 跳（風險 16 點）


def test_point_gap_over_tolerance_is_ignored():
    bars = make_bars([
        (10000, 10002, 9950, 9970),  # A：黑K，跌30點，最低9950
        (9950, 9980, 9950, 9977),    # B：紅K，漲27點；雖壘底但差距3點>1點
    ], prev_day=PREV)
    assert run(TitForTat(), bars).signals == []


def test_mother_only_highest_high_not_highest_close_is_ignored():
    bars = make_bars([
        LOW_BAR,
        (9990, 10010, 9985, 10005),  # 前一根：收盤較高
        (9990, 10030, 9985, 9995),   # A候選：最高點最高，但收盤非最高收盤
        (9995, 9997, 9970, 9975),    # B
    ], prev_day=PREV)
    assert run(TitForTat(), bars).signals == []


def test_signal_bar_exceeding_extreme_is_ignored():
    bars = make_bars([
        LOW_BAR,
        (10000, 10020, 9998, 10015),  # A：紅K，漲15點
        (10015, 10022, 9998, 9999),   # B：黑K 跌16點，但高點 10022 越過 A 高點 → A 不再是當下最高K線
    ], prev_day=PREV)
    assert run(TitForTat(), bars).signals == []


def test_not_extreme_position_is_ignored():
    bars = make_bars([
        (10000, 10020, 9998, 10015),  # A、B 外觀符合，但盤中震幅 22 點、距平盤 20 點 → 非極端位置（p.84）
        (10015, 10016, 9998, 9999),
    ], prev_day=PREV)
    assert run(TitForTat(), bars).signals == []
    assert len(run(TitForTat(require_extreme=False), bars).signals) == 1


def test_same_side_stopped_once_is_ignored():
    bars = make_bars([
        HIGH_BAR,
        (10000, 10002, 9985, 9988),  # A1：跌12點
        (9988, 10001, 9987, 10000),  # B1：漲12點 → 以牙還牙買訊，進場10000，停損9984
        (9995, 9998, 9960, 9970),    # 觸停損（跌破9984）
        (9965, 9968, 9930, 9940),    # A2：新的當下最低，跌25點
        (9940, 9966, 9938, 9964),    # B2：漲24點，差距1點，外觀符合，但當日多方已停損過 → 忽略
    ], prev_day=PREV)
    res = run(TitForTat(reversal_enabled=False), bars)
    assert len(res.signals) == 1
    assert res.trades[0].reason_out == "停損" and res.trades[0].exit_price == 9984


def test_far_signal_needs_pullback():
    # p.87：漲跌點超過20點 → 等拉回至距組合高點20點內再補進場
    bars = make_bars([
        LOW_BAR,
        (10000, 10025, 9998, 10020),  # A：當下最高，紅K，漲20點
        (10020, 10021, 9999, 10000),  # B：黑K，跌20點，差距0點；收盤10000，距極端25點 → 補進場
        (10000, 10004, 9995, 10002),  # 未拉回到 limit=10025-20=10005
        (10002, 10008, 9998, 10006),  # 拉回觸及 10005 → 成交
    ], prev_day=PREV)
    res = run(TitForTat(exit_mode="none"), bars)
    assert res.signals[0].reason == "以牙還牙空訊(補進場)"
    assert res.signals[0].stop == 10025
    t = res.trades[0]
    assert t.side == Side.SHORT and t.entry_price == 10005


def test_retrace_15_flat_exit():
    # p.90：獲利曾達15點後折返回進場價 → 立刻撤單平倉
    bars = make_bars([
        LOW_BAR,
        (10000, 10020, 9998, 10015),  # A：漲15點
        (10015, 10016, 9998, 10000),  # B：以牙還牙空訊，進場10000，停損10020
        (9998, 9999, 9984, 9990),     # 行情下行，獲利達15點以上（最低9984，距10000達16點）
        (9990, 10002, 9988, 10000),   # 折返回到進場價（獲利<=0）→ 撤單平倉
    ], prev_day=PREV)
    res = run(TitForTat(exit_mode="none"), bars)
    t = res.trades[0]
    assert t.side == Side.SHORT and t.entry_price == 10000
    assert t.reason_out == "折返停利" and t.exit_price == 10000


def test_conditional_reversal_without_15pts():
    # p.91：未達15點獲利即觸停損，且停損K收盤確認突破A極端點 → 反手
    bars = make_bars([
        HIGH_BAR,
        (10000, 10002, 9985, 9988),  # A：跌12點，當下最低9985
        (9988, 10001, 9987, 10000),  # B：漲12點 → 以牙還牙買訊，進場10000，停損9984
        (9990, 10010, 9980, 9983),   # 低點觸及停損9984，且收盤9983跌破A低點9985 → 反手放空
        (9983, 9985, 9978, 9980),    # 收盤平倉（當沖）
    ], prev_day=PREV)
    res = run(TitForTat(exit_mode="none"), bars)
    assert len(res.signals) == 2
    rev = res.signals[1]
    assert rev.side == Side.SHORT and "反手" in rev.reason and rev.stop == 10003
    assert res.trades[0].reason_out == "停損"
    assert res.trades[1].side == Side.SHORT and res.trades[1].entry_price == 9983


def test_wait_bars_minutes_converted_by_bar_interval():
    """max_wait_minutes：以同交易日相鄰K線時間差換成根數；None 或 time 欄非時間戳時用 max_wait 根。"""
    from helpers import make_bars as _mb

    from wangtrader.core import prepare as _prep
    from wangtrader.methods.q3_04_tit_for_tat import Params as _P, _wait_bars

    df = _prep(_mb([(100, 101, 99, 100)] * 6, freq="3min"))
    assert _wait_bars(df, 5, _P()) == 10
    assert _wait_bars(df, 5, _P(max_wait_minutes=10)) == 3
    assert _wait_bars(df, 5, _P(max_wait_minutes=1)) == 1
    assert _wait_bars(df.assign(time=range(len(df))), 5, _P(max_wait_minutes=10)) == 10


def test_reversal_stop_points_parameter():
    """反手停損：stop_points 有值時用 stop_points；stop_points=None 時改用 reversal_stop_points（原寫死 20）。"""
    assert TitForTat()._reversal_stop() == 20.0
    assert TitForTat(stop_points=30.0)._reversal_stop() == 30.0
    assert TitForTat(stop_points=None)._reversal_stop() == 20.0
    assert TitForTat(stop_points=None, reversal_stop_points=45.0)._reversal_stop() == 45.0
