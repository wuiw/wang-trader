from helpers import make_bars

from wangtrader.core import Side, run
from wangtrader.methods.sg_08_volume_expansion import VolumeExpansion


def _buy_rows(v_prev=1303, v_ext=3521, prev=None, ext=None, conf=None):
    """開盤後下跌：前一根黑K、擴量黑K創盤中最低、隔根紅K不創低。"""
    rows = [
        (10000, 10003, 9990, 9992, 800),
        (9992, 9994, 9982, 9984, 900),
        prev or (9984, 9986, 9975, 9977, v_prev),
        ext or (9977, 9979, 9965, 9968, v_ext),
        conf or (9968, 9976, 9966, 9974, 1500),
    ]
    return rows


def _sell_rows(v_prev=1523, v_ext=3623, conf=None):
    rows = [
        (10000, 10010, 9997, 10008, 800),
        (10008, 10018, 10006, 10016, 900),
        (10016, 10025, 10014, 10023, v_prev),
        (10023, 10035, 10021, 10032, v_ext),
        conf or (10032, 10034, 10024, 10026, 1500),
    ]
    return rows


def test_buy_signal():
    res = run(VolumeExpansion(), make_bars(_buy_rows()))
    sig = res.signals[0]
    assert sig.side == Side.LONG and sig.reason == "擴量買訊"
    assert sig.price == 9974 and sig.stop == 9965


def test_sell_signal_mirror():
    res = run(VolumeExpansion(), make_bars(_sell_rows()))  # 3623-1523=2100（原文例）
    sig = res.signals[0]
    assert sig.side == Side.SHORT and sig.reason == "擴量空訊"
    assert sig.price == 10026 and sig.stop == 10035


def test_increase_must_exceed_2000():
    assert not run(VolumeExpansion(), make_bars(_buy_rows(v_prev=1302, v_ext=3090))).signals  # 增 1788
    assert not run(VolumeExpansion(), make_bars(_buy_rows(v_prev=1000, v_ext=3000))).signals  # 恰 2000


def test_prev_over_2000_needs_triple():
    assert not run(VolumeExpansion(), make_bars(_buy_rows(v_prev=3888, v_ext=11085))).signals
    assert run(VolumeExpansion(), make_bars(_buy_rows(v_prev=3888, v_ext=11664))).signals


def test_color_pattern_required():
    # 擴量K收紅（紅K在最低點）→ 不是黑黑紅
    rows = _buy_rows(ext=(9968, 9979, 9965, 9975, 3521), conf=(9975, 9980, 9970, 9978, 1500))
    assert not run(VolumeExpansion(), make_bars(rows)).signals
    assert run(VolumeExpansion(require_color_pattern=False), make_bars(rows)).signals


def test_confirm_bar_must_be_red():
    rows = _buy_rows(conf=(9974, 9976, 9966, 9970, 1500))  # 不創低但收黑
    assert not run(VolumeExpansion(), make_bars(rows)).signals


def test_confirm_bar_new_low_fails():
    rows = _buy_rows(conf=(9966, 9976, 9960, 9974, 1500))  # 收紅但創低
    assert not run(VolumeExpansion(), make_bars(rows)).signals


def test_not_session_low_fails():
    rows = _buy_rows()
    rows[0] = (10000, 10003, 9950, 9992, 800)  # 開盤根已跌到 9950，擴量K不是盤中最低
    assert not run(VolumeExpansion(), make_bars(rows)).signals


def test_confirm_must_be_next_bar():
    rows = _buy_rows(conf=(9968, 9970, 9966, 9967, 1500))  # 隔根黑K，不成立
    rows.append((9967, 9978, 9966, 9976, 1500))  # 隔兩根才出現不創低紅K → 仍不成立
    assert not run(VolumeExpansion(), make_bars(rows)).signals


def test_bars_must_be_same_session():
    # 前一根在前一日，擴量K為當日第一根 → 三根不在同一盤別
    rows = [(9977, 9979, 9965, 9968, 3521), (9968, 9976, 9966, 9974, 1500)]
    bars = make_bars(rows, prev_day=(9984, 9986, 9975, 9977, 1303))
    assert not run(VolumeExpansion(), bars).signals


def test_far_stop_uses_digit_stop():
    rows = _buy_rows(ext=(9977, 9979, 9940, 9968, 3521), conf=(9968, 9976, 9950, 9974, 1500))
    sig = run(VolumeExpansion(), make_bars(rows)).signals[0]
    assert sig.stop == 9974 - 14  # 距擴量K低點 34 點 > 20 → 收盤 −(10＋個位數 4)
