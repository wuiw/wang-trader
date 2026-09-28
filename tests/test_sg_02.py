import pytest
from helpers import make_bars

from wangtrader.core import Side, run
from wangtrader.methods.sg_02_counterattack_line import CounterattackLine

PREV = (10000, 10000, 10000, 10000)  # 平盤 10000


def _long_rows(black=(10000, 10001, 9990, 9992), red=(9992, 10000, 9991, 9999)):
    return [(10000, 10002, 9998, 10000), black, red]


def _short_rows(red=(10000, 10010, 9999, 10008), black=(10008, 10009, 10000, 10001)):
    return [(10000, 10002, 9998, 10000), red, black]


def _sig(rows, prev=PREV, **kw):
    return run(CounterattackLine(**kw), make_bars(rows, freq="1min", prev_day=prev)).signals


def test_buy_signal():
    sig = _sig(_long_rows())[0]
    assert sig.side == Side.LONG and sig.reason == "逆襲線買訊"
    assert sig.price == 9999 and sig.stop == 9979  # 助教 20 點停損


def test_sell_mirror():
    sig = _sig(_short_rows())[0]
    assert sig.side == Side.SHORT and sig.reason == "逆襲線空訊"
    assert sig.price == 10001 and sig.stop == 10021


def test_disable_short():
    assert not _sig(_short_rows(), enable_short=False)


def test_low_gap_over_1_filtered():
    assert not _sig(_long_rows(red=(9992, 10000, 9992, 9999)))  # 低點差 2


def test_black_drop_under_7_filtered():
    # 跌 6（收盤差與實體皆 6）
    assert not _sig(_long_rows(black=(10000, 10001, 9990, 9994), red=(9994, 10000, 9991, 9999)))


def test_red_rise_under_5_filtered():
    assert not _sig(_long_rows(red=(9992, 9998, 9991, 9996)))  # 漲 4


def test_short_high_gap_over_1_filtered():
    assert not _sig(_short_rows(black=(10008, 10008, 10000, 10001)))  # 高點差 2


def test_color_required():
    # 第二根收盤高於前根收盤但為黑K（開高收低）→ 不是「一黑一紅」
    assert not _sig(_long_rows(red=(10000, 10001, 9991, 9998)))


def test_move_basis_close_diff_vs_body():
    # 黑K 跳空開低：實體只跌 5，但與前根收盤差跌 10
    rows = _long_rows(black=(9995, 9996, 9990, 9990), red=(9990, 9998, 9990, 9997))
    assert _sig(rows, move_basis="close_diff")
    assert not _sig(rows, move_basis="body")


def test_move_basis_body_only():
    # 紅K 跳空開高：實體只漲 4，但與前根收盤差漲 9 → 只有 close_diff 成立
    rows = _long_rows(red=(9997, 10002, 9991, 10001))
    assert _sig(rows, move_basis="close_diff")
    assert not _sig(rows, move_basis="body")


def test_extreme_session_filter():
    rows = [(10000, 10002, 9980, 10000)] + _long_rows()[1:]  # 早先已有更低點 9980
    assert not _sig(rows)
    assert _sig(rows, extreme_mode="none")
    assert _sig(rows, extreme_mode="session", extreme_tol=10)


def test_extreme_prev_close_filter():
    assert not _sig(_long_rows(), extreme_mode="prev_close")  # 距平盤只 10 點
    rows = _long_rows()
    far = [tuple(v - 50 for v in r) for r in rows]
    assert _sig(far, extreme_mode="prev_close")
    assert _sig(far, extreme_mode="both")
    assert not _sig(far, extreme_mode="prev_close", extreme_from_prev_close=70)


def test_high_match_tol():
    rows = _long_rows()  # 黑K 高 10001、紅K 高 10000
    assert _sig(rows, high_match_tol=1)
    assert not _sig(_long_rows(red=(9992, 9998, 9991, 9997)), high_match_tol=1)  # 高點差 3


def test_structure_stop():
    sig = _sig(_long_rows(), stop_mode="structure")[0]
    assert sig.stop == 9990  # 組合最低點，距離 9 點
    # 組合很長：距離超過 20 → 均線訊號停損法（收盤 9999，個位數 9 → 19 點）
    rows = _long_rows(black=(10000, 10001, 9970, 9972), red=(9972, 10000, 9971, 9999))
    sig = _sig(rows, stop_mode="structure")[0]
    assert sig.stop == 9999 - 19


def test_first_bar_of_session_uses_prev_close():
    # 當日首根即黑K：開 9995 收 9992，實體跌 3，但與平盤 10000 差 8
    rows = [(9995, 9996, 9990, 9992), (9992, 10000, 9991, 9999)]
    assert _sig(rows)
    assert not _sig(rows, move_basis="body")
    assert not _sig(rows, prev=None)  # 沒有平盤 → 首根跌點無法計算


def test_pair_across_sessions_not_counted():
    day1 = make_bars([(10000, 10001, 9990, 9992)], freq="1min", prev_day=PREV)
    day2 = make_bars([(9992, 10000, 9991, 9999)], start="2024-01-03 08:45", freq="1min")
    import pandas as pd

    assert not run(CounterattackLine(extreme_mode="none"), pd.concat([day1, day2])).signals


def test_bad_param():
    with pytest.raises(ValueError):
        CounterattackLine(move_basis="x")
