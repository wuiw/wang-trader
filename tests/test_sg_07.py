import pandas as pd
import pytest
from helpers import make_bars

from wangtrader.core import Side, run
from wangtrader.methods.sg_07_gap_hundred import GapHundred

PREV = (17000, 17010, 16990, 17000)  # 昨收 17000


def _gap_up_break_low():
    # 開 17110（+110），首根 17100~17120；第 2 根收 17095 跌破首根低點
    return [(17110, 17120, 17100, 17115), (17112, 17114, 17090, 17095), (17095, 17098, 17080, 17085)]


def _gap_down_break_high():
    return [(16890, 16900, 16880, 16885), (16886, 16910, 16884, 16905), (16905, 16915, 16900, 16910)]


def test_fade_short_on_gap_up():
    res = run(GapHundred(), make_bars(_gap_up_break_low(), prev_day=PREV))
    sig = res.signals[0]
    assert sig.side == Side.SHORT and sig.reason == "跳空百點空訊"
    assert sig.price == 17095
    assert len(res.signals) == 1


def test_stop_digit_rule_when_far():
    # 上例首根高 17120，距收盤 25 點 > 20 → 空＝收盤 +(20−5)=17110
    res = run(GapHundred(), make_bars(_gap_up_break_low(), prev_day=PREV))
    assert res.signals[0].stop == 17110


def test_stop_first_bar_extreme_within_20():
    rows = [(17110, 17112, 17100, 17105), (17104, 17106, 17095, 17097)]
    sig = run(GapHundred(), make_bars(rows, prev_day=PREV)).signals[0]
    assert sig.side == Side.SHORT and sig.stop == 17112


def test_fade_long_on_gap_down():
    sig = run(GapHundred(), make_bars(_gap_down_break_high(), prev_day=PREV)).signals[0]
    assert sig.side == Side.LONG and sig.reason == "跳空百點買訊"
    assert sig.price == 16905 and sig.stop == 16890  # 首根低 16880 距 25 > 20 → 多＝收盤 −(10+5)


def test_follow_direction():
    # 開高後收盤突破首根高點 → follow 做多、fade 不做
    rows = [(17110, 17120, 17100, 17115), (17115, 17130, 17112, 17125)]
    bars = make_bars(rows, prev_day=PREV)
    assert not run(GapHundred(), bars).signals
    sig = run(GapHundred(direction="follow"), bars).signals[0]
    assert sig.side == Side.LONG and sig.stop == 17110  # 首根低 17100 距 25 → 收盤 17125 −(10+5)
    # follow 模式下開高跌破首根低點不做
    assert not run(GapHundred(direction="follow"), make_bars(_gap_up_break_low(), prev_day=PREV)).signals


def test_both_direction_takes_whichever_first():
    rows = [(17110, 17120, 17100, 17115), (17115, 17130, 17112, 17125)]
    sig = run(GapHundred(direction="both"), make_bars(rows, prev_day=PREV)).signals[0]
    assert sig.side == Side.LONG


def test_bad_direction_rejected():
    with pytest.raises(ValueError):
        GapHundred(direction="x")


def test_gap_threshold_boundary():
    ok = [(17100, 17110, 17095, 17105), (17104, 17106, 17090, 17092)]  # 剛好 100 點
    assert run(GapHundred(), make_bars(ok, prev_day=PREV)).signals
    no = [(17094, 17104, 17089, 17099), (17098, 17100, 17080, 17082)]  # 94 點
    assert not run(GapHundred(), make_bars(no, prev_day=PREV)).signals
    assert run(GapHundred(gap_threshold=90), make_bars(no, prev_day=PREV)).signals


def test_first_bar_itself_not_signal():
    # 首根收黑但後續沒有收盤跌破首根低點 → 無訊號
    rows = [(17110, 17112, 17090, 17092), (17092, 17100, 17091, 17095)]
    assert not run(GapHundred(), make_bars(rows, prev_day=PREV)).signals


def test_masked_close_does_not_count():
    # 第 2 根下探 17085 但收回；第 3 根收 17095 只破首根低 17100、未破 17085 → 有遮蔽
    rows = [(17110, 17120, 17100, 17115), (17112, 17114, 17085, 17105), (17105, 17106, 17090, 17095)]
    bars = make_bars(rows, prev_day=PREV)
    assert not run(GapHundred(), bars).signals
    assert run(GapHundred(unmasked=False), bars).signals


def test_window_minutes():
    rows = [(17110, 17120, 17100, 17115)] + [(17112, 17118, 17102, 17110)] * 6 + [(17105, 17106, 17090, 17095)]
    bars = make_bars(rows, prev_day=PREV)  # 突破根在首根後 35 分鐘
    assert run(GapHundred(), bars).signals
    assert not run(GapHundred(window_minutes=30), bars).signals
    assert run(GapHundred(window_minutes=35), bars).signals


def test_first_only():
    # 空訊後被停損，再次創新低 → first_only=True 不再進場；False 再進一次
    rows = [(17110, 17112, 17100, 17105), (17104, 17106, 17095, 17097),
            (17097, 17125, 17096, 17120), (17120, 17121, 17090, 17092)]
    bars = make_bars(rows, prev_day=PREV)
    assert len(run(GapHundred(), bars).signals) == 1
    assert len(run(GapHundred(first_only=False), bars).signals) == 2


def test_no_signal_next_day_without_gap():
    rows = _gap_up_break_low()
    bars1 = make_bars(rows, prev_day=PREV)
    bars2 = make_bars([(17090, 17095, 17080, 17085), (17085, 17086, 17070, 17072)],
                      start="2024-01-03 08:45")
    res = run(GapHundred(), pd.concat([bars1, bars2]))
    assert len(res.signals) == 1
