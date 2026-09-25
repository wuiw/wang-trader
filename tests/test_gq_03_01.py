"""gq-03-01 金叉後低轉折買點。

用 fast=1/slow=2/signal=3 這組極短 MACD 參數，讓 DIF/慢線只需 2-3 根K線即可完成
「金叉 → 向下彎 → N轉折向上」的因果過程，方便手工驗證（原文未規定 12/26/9 以外的參數，
本測試僅為驗證邏輯正確性，不代表書中建議用法）。

以下收盤價序列（bars 0-8）事先以 `_macd(fast=1, slow=2, signal=3)` 驗算：
  bar6：金叉確認（dif 由 <=macd 轉為 >macd）
  bar7：DIF 向下彎，但仍高於慢線（C2/C3）
  bar8：DIF 重新上勾，仍高於慢線（C4，N轉折買點）；收盤96.73>開盤96.56為陽線（C5）
金叉前的最低點在 bar7（96.30），故停損 = 96.30 - stop_tick(1.0) = 95.30。
"""

from helpers import make_bars

from wangtrader.core import Side, run
from wangtrader.methods.gq_03_01_macd_n_turn import MacdGoldenCrossLowTurn

ROWS = [
    (99.50, 100.50, 99.00, 100.00),
    (100.00, 100.60, 99.80, 100.48),
    (100.48, 100.60, 99.00, 99.31),
    (99.31, 99.40, 97.50, 97.84),
    (97.84, 99.10, 97.70, 98.96),
    (98.96, 99.00, 96.30, 96.60),
    (96.60, 97.20, 96.40, 97.02),  # bar6：金叉確認
    (97.02, 97.10, 96.30, 96.56),  # bar7：DIF向下彎，仍在慢線之上
    (96.56, 96.90, 96.40, 96.73),  # bar8：N轉折向上，陽線 → 買進訊號
]


def _params(**kw):
    return dict(fast=1, slow=2, signal=3, **kw)


def test_n_turn_signal_basic():
    res = run(MacdGoldenCrossLowTurn(**_params(exit_mode="none")), make_bars(ROWS))
    assert len(res.signals) == 1
    sig = res.signals[0]
    assert sig.side == Side.LONG and sig.reason == "金叉後低轉折買點"
    assert sig.price == 96.73
    assert abs(sig.stop - 95.30) < 1e-6  # 期間最低點 96.30（bar7）下方一跳


def test_fixed_pct_stop_mode():
    res = run(MacdGoldenCrossLowTurn(**_params(stop_mode="pct", fixed_stop_pct=0.05, exit_mode="none")), make_bars(ROWS))
    sig = res.signals[0]
    assert abs(sig.stop - 96.73 * 0.95) < 1e-6


def test_f_not_red_bar_is_filtered():
    rows = list(ROWS)
    rows[8] = (97.00, 97.10, 96.40, 96.73)  # 開盤高於收盤 → 黑K，不符合C5
    res = run(MacdGoldenCrossLowTurn(**_params(exit_mode="none")), make_bars(rows))
    assert res.signals == []


def test_f_turn_too_late_is_filtered():
    # 金叉在bar6，N轉折在bar8，間隔2根；限縮 max_bars_since_cross=1 → 轉折確認前已逾時被剔除
    res = run(MacdGoldenCrossLowTurn(**_params(max_bars_since_cross=1, exit_mode="none")), make_bars(ROWS))
    assert res.signals == []


def test_f_death_cross_before_turn_invalidates():
    """向下彎過程若真的跌破慢線（死叉），即使之後DIF再度上勾也不算N轉折，須等全新金叉。"""
    rows = ROWS[:7] + [
        (97.02, 97.10, 92.50, 93.00),  # bar7：大跌，DIF 死叉跌破慢線
        (93.00, 98.20, 92.90, 98.00),  # bar8：反彈，但只是形成新的金叉起點，不是C4轉折
    ]
    res = run(MacdGoldenCrossLowTurn(**_params(exit_mode="none")), make_bars(rows))
    assert res.signals == []
