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
        (10015, 10016, 9998, 9999),   # B：黑K，跌16點，差距1點
    ], prev_day=PREV)
    res = run(TitForTat(), bars)
    sig = res.signals[0]
    assert sig.side == Side.SHORT and sig.reason == "以牙還牙空訊"
    assert sig.price == 9999 and sig.stop == 10019  # 極端點 10020+1 跳，但距進場價最多 20 → 10019


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
    res = run(TitForTat(), bars)
    assert len(res.signals) == 1
    assert res.trades[0].reason_out == "停損" and res.trades[0].exit_price == 9984
