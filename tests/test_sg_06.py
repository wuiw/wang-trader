import pytest
from helpers import make_bars

from wangtrader.core import Side, run
from wangtrader.methods.sg_06_first_bar_color import FirstBarColor

PREV = (10000, 10010, 9990, 10000)  # 平盤 10000


def _run(rows, **kw):
    return run(FirstBarColor(**kw), make_bars(rows, prev_day=PREV))


def test_gap_down_red_first_bar_buy():
    rows = [(9900, 9930, 9870, 9920), (9920, 9925, 9915, 9922)]
    sig = _run(rows).signals[0]
    assert sig.side == Side.LONG and sig.reason == "首K收紅買訊"
    assert sig.price == 9920 and sig.stop == 9869  # 首K低點下 1 點


def test_gap_up_black_first_bar_sell():
    rows = [(10100, 10160, 10050, 10060), (10060, 10065, 10055, 10058)]
    sig = _run(rows).signals[0]
    assert sig.side == Side.SHORT and sig.reason == "首K收黑空訊"
    assert sig.price == 10060 and sig.stop == 10161  # 首K高點上 1 點；上影線 60 點不影響


def test_gap_up_red_first_bar_ignored():
    assert not _run([(10100, 10130, 10095, 10120), (10120, 10125, 10110, 10115)]).signals


def test_gap_down_black_first_bar_ignored():
    assert not _run([(9900, 9905, 9860, 9870), (9870, 9875, 9860, 9865)]).signals


def test_no_gap_ignored():
    assert not _run([(10000, 10030, 9990, 10020), (10020, 10025, 10015, 10022)]).signals


def test_gap_threshold():
    rows = [(9970, 9990, 9965, 9985), (9985, 9990, 9980, 9986)]  # 跳空 30 點
    assert _run(rows, gap_points=0).signals
    assert not _run(rows, gap_points=40).signals


def test_only_first_bar_counts():
    rows = [(10000, 10005, 9995, 10002), (9900, 9930, 9870, 9920)]
    assert not _run(rows).signals


def test_needs_prev_close():
    assert not run(FirstBarColor(), make_bars([(9900, 9930, 9870, 9920), (9920, 9925, 9915, 9922)])).signals


def test_stop_hit():
    rows = [(9900, 9930, 9870, 9920), (9920, 9921, 9860, 9880), (9880, 9890, 9870, 9885)]
    t = _run(rows).trades[0]
    assert t.reason_out == "停損" and t.exit_price == 9869


def test_max_stop_points_switches_to_digit_stop():
    rows = [(9900, 9930, 9870, 9923), (9923, 9925, 9915, 9922)]
    sig = _run(rows, max_stop_points=20).signals[0]
    assert sig.stop == 9923 - (10 + 3)


def test_breakout_short_enters_on_close_below_first_low():
    rows = [(10100, 10160, 10050, 10060), (10060, 10070, 10052, 10065), (10065, 10066, 10030, 10040)]
    sig = _run(rows, entry_mode="breakout").signals[0]
    assert sig.side == Side.SHORT and sig.i == 3 and sig.price == 10040 and sig.stop == 10161


def test_breakout_long_enters_on_close_above_first_high():
    rows = [(9900, 9930, 9870, 9920), (9920, 9925, 9910, 9922), (9922, 9950, 9920, 9945)]
    sig = _run(rows, entry_mode="breakout").signals[0]
    assert sig.side == Side.LONG and sig.price == 9945 and sig.stop == 9869


def test_breakout_cancel_on_recover():
    # 第二根下殺破首K低點 10050 但收盤收回（下殺收腳）→ 撤單，第三根再收低也不進場
    rows = [(10100, 10160, 10050, 10060), (10060, 10062, 10040, 10058), (10058, 10060, 10020, 10030)]
    assert not _run(rows, entry_mode="breakout").signals
    assert _run(rows, entry_mode="breakout", cancel_on_recover=False).signals[0].price == 10030


def test_breakout_window_minutes():
    rows = [(10100, 10160, 10050, 10060)] + [(10060, 10065, 10055, 10058)] * 3 + [(10058, 10060, 10020, 10030)]
    assert _run(rows, entry_mode="breakout", breakout_window_minutes=30).signals
    assert not _run(rows, entry_mode="breakout", breakout_window_minutes=15).signals  # 第 5 根距首根 20 分


def test_breakout_does_not_carry_to_next_session():
    df = make_bars([(10100, 10160, 10050, 10060), (10060, 10065, 10055, 10058)], prev_day=PREV)
    nxt = make_bars([(10058, 10060, 10000, 10010)], start="2024-01-03 08:45")
    import pandas as pd

    assert not run(FirstBarColor(entry_mode="breakout"), pd.concat([df, nxt])).signals


def test_bad_entry_mode():
    with pytest.raises(ValueError):
        FirstBarColor(entry_mode="x")
