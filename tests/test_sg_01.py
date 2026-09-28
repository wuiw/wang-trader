from helpers import make_bars

from wangtrader.core import Side, run
from wangtrader.methods.sg_01_rsi_blunt_quick import RsiBluntQuick


def _rally(n=9, px=10000):
    rows = []
    for _ in range(n):
        rows.append((px, px + 6, px - 1, px + 5))
        px += 5
    return rows


def _fall(n=9, px=10000):
    rows = []
    for _ in range(n):
        rows.append((px, px + 1, px - 6, px - 5))
        px -= 5
    return rows


def test_buy_when_close_clears_first_bar_high():
    res = run(RsiBluntQuick(), make_bars(_rally(), freq="1min"))
    sig = res.signals[0]
    assert sig.side == Side.LONG and sig.reason == "RSI鈍化簡化買訊"


def test_sell_mirror():
    res = run(RsiBluntQuick(), make_bars(_fall(), freq="1min"))
    sig = res.signals[0]
    assert sig.side == Side.SHORT and sig.reason == "RSI鈍化簡化空訊"


def test_stop_is_first_bar_low_within_20_points():
    res = run(RsiBluntQuick(), make_bars(_rally(), freq="1min"))
    sig = res.signals[0]
    assert sig.price - sig.stop <= 20


def test_window_expires():
    rows = _rally(6)  # 最後一根為 RSI 首次觸及 90 的首根
    top = rows[-1][1]
    side = [(top - 2, top - 1, top - 6, top - 3)] * 3  # 橫盤 3 根（15 分）不突破首根高點
    brk = [(top - 3, top + 10, top - 4, top + 8)]
    bars = make_bars(rows + side + brk, freq="5min")
    assert not run(RsiBluntQuick(window_minutes=10), bars).signals
    assert run(RsiBluntQuick(window_minutes=30), bars).signals


def test_masked_close_does_not_count():
    rows = _rally(6)
    top = rows[-1][1]
    # 首根後一根衝高（新高點 top+10）但收盤低於首根高點；再下一根收盤只過首根高、未過該新高 → 有遮蔽
    rows += [(top - 1, top + 10, top - 2, top - 1), (top - 1, top + 5, top - 2, top + 3)]
    assert not run(RsiBluntQuick(window_minutes=30), make_bars(rows, freq="5min")).signals
