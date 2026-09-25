"""gq-03-02 死叉後高轉折賣出訊號。

沿用 gq-03-01 測試同一組 fast=1/slow=2/signal=3 極短 MACD 參數，將收盤價序列以「200 - 原始收盤價」
鏡射，把原本的「金叉→N轉折」翻成「死叉→倒N轉折」（EMA 為線性運算，鏡射後交叉結構完全對稱翻轉，
已用 `_macd` 實際驗算）。
  bar6：死叉確認
  bar7：DIF 上勾但未穿越慢線（C2/C3）
  bar8：DIF 重新下彎，仍在慢線之下（C4，倒N轉折賣點）；收盤103.27仍 >= 死叉當根收盤102.98（F2通過）
死叉後至訊號K期間最高點在 bar7（103.70），停損 = 103.70 + stop_tick(1.0) = 104.70。
"""

from helpers import make_bars

from wangtrader.core import Side, run
from wangtrader.methods.gq_03_02_macd_reverse_n_turn import MacdDeathCrossHighTurn

ROWS = [
    (100.50, 101.00, 99.50, 100.00),
    (100.00, 100.20, 99.40, 99.52),
    (99.52, 101.00, 99.40, 100.69),
    (100.69, 102.50, 100.60, 102.16),
    (102.16, 102.30, 100.90, 101.04),
    (101.04, 103.70, 101.00, 103.40),
    (103.40, 103.60, 102.80, 102.98),  # bar6：死叉確認
    (102.98, 103.70, 102.90, 103.44),  # bar7：DIF上勾，仍在慢線之下
    (103.44, 103.60, 103.10, 103.27),  # bar8：倒N轉折向下 → 賣出訊號
]


def _params(**kw):
    return dict(fast=1, slow=2, signal=3, **kw)


def test_reverse_n_turn_signal_basic():
    res = run(MacdDeathCrossHighTurn(**_params()), make_bars(ROWS))
    assert len(res.signals) == 1
    sig = res.signals[0]
    assert sig.side == Side.SHORT and sig.reason == "死叉後高轉折賣出訊號"
    assert sig.price == 103.27
    assert abs(sig.stop - 104.70) < 1e-6  # 期間最高點 103.70（bar7）上方一跳


def test_fixed_pct_stop_mode():
    res = run(MacdDeathCrossHighTurn(**_params(stop_mode="pct")), make_bars(ROWS))
    sig = res.signals[0]
    assert abs(sig.stop - 103.27 * 1.07) < 1e-6  # 7% 最大停損


def test_f1_turn_too_late_is_filtered():
    # 死叉在bar6，倒N轉折在bar8，間隔2根；限縮 days_since_cross_max=1 → 逾時剔除
    res = run(MacdDeathCrossHighTurn(**_params(days_since_cross_max=1)), make_bars(ROWS))
    assert res.signals == []


def test_f2_immediate_drop_is_filtered():
    """死叉後價格若隨即下跌（訊號收盤低於死叉當根收盤），不符合「未立即下跌」的核心情境。"""
    rows = ROWS[:8] + [(103.44, 103.50, 100.90, 101.00)]  # bar8收盤101.00 < 死叉當根收盤102.98
    res = run(MacdDeathCrossHighTurn(**_params()), make_bars(rows))
    assert res.signals == []


def test_golden_cross_before_turn_invalidates():
    """上勾過程若真的穿越慢線形成金叉，即使之後DIF再度下彎也不算倒N轉折，須等全新死叉。"""
    rows = ROWS[:7] + [
        (102.98, 107.50, 102.90, 107.00),  # bar7：大漲，DIF 金叉穿越慢線
        (107.00, 107.10, 101.80, 102.00),  # bar8：拉回，只是形成新的死叉起點，不是C4轉折
    ]
    res = run(MacdDeathCrossHighTurn(**_params()), make_bars(rows))
    assert res.signals == []
