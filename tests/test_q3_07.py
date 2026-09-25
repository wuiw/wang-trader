from helpers import make_bars

from wangtrader.core import Side, run
from wangtrader.methods.q3_07_opening_bar import OpeningBar

PREV = (9990, 10001, 9989, 10000)  # 平盤 10000


def test_gap_up_black_short_signal():
    bars = make_bars([
        (10045, 10046, 10025, 10030),  # 開盤首根：跳高45點，收黑，上影線1點
        (10030, 10032, 10010, 10015),
        (10015, 10018, 10005, 10008),
    ], prev_day=PREV)
    res = run(OpeningBar(), bars)
    sig = res.signals[0]
    assert sig.side == Side.SHORT and sig.reason == "跳高收黑"
    assert sig.price == 10030 and sig.stop == 10050
    assert res.trades[0].entry_price == 10030 and res.trades[0].entry_i == 1


def test_gap_down_red_long_signal():
    bars = make_bars([
        (9955, 9972, 9954, 9970),  # 開盤首根：跳低45點，收紅，下影線1點
        (9970, 9985, 9965, 9980),
        (9980, 9990, 9975, 9985),
    ], prev_day=PREV)
    res = run(OpeningBar(), bars)
    sig = res.signals[0]
    assert sig.side == Side.LONG and sig.reason == "跳低收紅"
    assert sig.price == 9970 and sig.stop == 9950


def test_gap_below_threshold_is_ignored():
    bars = make_bars([
        (10020, 10022, 10010, 10012),  # 只跳高20點，未達40點門檻
        (10012, 10015, 10005, 10008),
    ], prev_day=PREV)
    assert run(OpeningBar(), bars).signals == []


def test_shadow_too_long_is_ignored():
    bars = make_bars([
        (10045, 10052, 10025, 10030),  # 跳高45點收黑，但上影線7點 >3點
        (10030, 10032, 10010, 10015),
    ], prev_day=PREV)
    assert run(OpeningBar(), bars).signals == []


def test_oversized_bar_is_ignored():
    bars = make_bars([
        (10045, 10047, 10010, 10015),  # 上影線2點合格，但收盤到最高點距離32點 >20點停損
        (10015, 10018, 10005, 10008),
    ], prev_day=PREV)
    assert run(OpeningBar(), bars).signals == []


def test_stop_without_15pts_profit_reverses_on_close():
    bars = make_bars([
        (10045, 10046, 10025, 10030),  # 跳高收黑空訊，stop=10050
        (10040, 10060, 10038, 10055),  # 高點觸及停損且收盤突破訊號K高點10046 → 停損反手做多
        (10055, 10058, 10050, 10053),
    ], prev_day=PREV)
    res = run(OpeningBar(), bars)
    assert len(res.signals) == 2
    rev = res.signals[1]
    assert rev.side == Side.LONG and rev.reason == "停損反手" and rev.stop == 10035
    assert res.trades[0].reason_out == "停損"
    assert res.trades[1].side == Side.LONG and res.trades[1].entry_price == 10055


def test_retrace_exit_after_15pts_profit():
    bars = make_bars([
        (10045, 10046, 10025, 10030),  # 跳高收黑空訊，stop=10050
        (10028, 10032, 10010, 10018),  # 獲利達15點以上（最低10010，距收盤10030達20點）
        (10020, 10038, 10015, 10035),  # 折返回到收盤價附近（利潤<=0）→ 撤單出場
    ], prev_day=PREV)
    res = run(OpeningBar(), bars)
    t = res.trades[0]
    assert t.reason_out == "折返停利" and t.exit_price == 10035
