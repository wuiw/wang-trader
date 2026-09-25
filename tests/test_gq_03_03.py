"""gq-03-03 MACD雙金叉反轉買點。

同樣使用 fast=1/slow=2/signal=3 便於手工驗算。事先以 `_macd` 驗算下列收盤價序列會在
bar1／bar5／bar9 出現三次金叉：
  bar1：首次金叉（僅觀望，不進場）
  bar5：第二次金叉（與bar1間隔4根），本測試設為黑K → 不成立，但仍成為下一次比較基準
  bar9：第三次金叉（與bar5間隔4根），本測試設為紅K → 雙金叉成立，買進訊號
"""

from helpers import make_bars

from wangtrader.core import Side, run
from wangtrader.methods.gq_03_03_macd_double_cross import MacdDoubleGoldenCross

ROWS = [
    (99.50, 100.50, 99.00, 100.00),
    (100.00, 100.60, 99.80, 100.42),  # bar1：首次金叉
    (100.42, 102.40, 100.30, 102.23),
    (102.23, 102.30, 99.40, 99.61),
    (99.61, 99.70, 97.00, 97.31),
    (99.00, 99.10, 98.60, 98.88),  # bar5：第二次金叉，黑K（開盤99.00>收盤98.88）→ 不成立
    (98.88, 99.00, 98.50, 98.71),
    (98.71, 98.80, 97.70, 97.99),
    (97.99, 98.00, 96.00, 96.25),
    (95.90, 96.40, 95.70, 96.18),  # bar9：第三次金叉，紅K（開盤95.90<收盤96.18）→ 買進訊號
    (96.18, 98.70, 96.00, 98.54),
]


def _params(**kw):
    return dict(fast=1, slow=2, signal=3, exit_mode="none", **kw)


def test_double_golden_cross_signal_basic():
    res = run(MacdDoubleGoldenCross(**_params()), make_bars(ROWS))
    assert len(res.signals) == 1
    sig = res.signals[0]
    assert sig.side == Side.LONG and sig.reason == "MACD雙金叉反轉買點"
    assert sig.price == 96.18
    assert sig.stop == 95.70  # 進場K（bar9）最低點


def test_f_black_second_cross_not_entered_but_becomes_new_reference():
    # 主測試已隱含驗證：bar5(黑K)未進場，但仍作為 bar9 的比較基準（否則 bar9 與 bar1 間隔達8根，
    # 若 max_bars_between_crosses 設為 5（介於4與8之間），只有「以bar5為基準」才會通過。
    res = run(MacdDoubleGoldenCross(**_params(max_bars_between_crosses=5)), make_bars(ROWS))
    assert len(res.signals) == 1 and res.signals[0].price == 96.18


def test_f_gap_between_crosses_too_large_is_filtered():
    res = run(MacdDoubleGoldenCross(**_params(max_bars_between_crosses=3)), make_bars(ROWS))
    assert res.signals == []


def test_f_second_cross_not_red_is_filtered():
    rows = list(ROWS)
    rows[9] = (96.40, 96.50, 95.70, 96.18)  # 開盤96.40>收盤96.18 → 黑K，bar9也不成立
    res = run(MacdDoubleGoldenCross(**_params()), make_bars(rows))
    assert res.signals == []


def test_stop_triggers_only_on_close_breach():
    """p.148：跌破進場K最低點的『收盤』才停損，盤中觸及不算。"""
    rows = ROWS + [
        (98.54, 99.00, 90.00, 97.00),  # 低點90遠穿停損95.70，但收盤97.00仍在停損之上 → 不停損
        (97.00, 97.50, 94.00, 95.00),  # 收盤95.00 <= 停損95.70 → 收盤停損
    ]
    res = run(MacdDoubleGoldenCross(**_params()), make_bars(rows))
    assert len(res.trades) == 1
    t = res.trades[0]
    assert t.reason_out == "停損" and t.exit_price == 95.00 and t.exit_i == 12


def test_exit_prev_low_break():
    """跌破一低出場：進場後新形成的第一個確認轉折低點被收盤跌破時出場（p.148）。"""
    rows = ROWS + [
        (98.54, 100.00, 98.30, 99.80),
        (99.80, 100.10, 97.50, 98.00),  # 轉折低點候選 97.50
        (98.00, 99.50, 98.20, 99.30),   # 右側確認
        (99.30, 99.40, 96.00, 96.80),   # 收盤96.80 < 97.50 → 跌破一低出場
    ]
    kw = _params()
    kw.update(pivot_level=1, exit_mode="prev_low_break")
    res = run(MacdDoubleGoldenCross(**kw), make_bars(rows))
    assert len(res.trades) == 1
    t = res.trades[0]
    assert t.reason_out == "跌破一低" and t.exit_price == 96.80
