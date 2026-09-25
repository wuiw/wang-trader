"""gq-03-04 DIF連續下跌慣性改變買點。

以 fast=1/slow=2/signal=3 便於手工驗算：收盤價 [100,98,96,94,92,90,88] 讓DIF連續下跌6天
（bar1~bar6，每天皆小於前一天），bar7 收盤大漲至110（相對前一天收盤88，漲幅約25%>4%）使DIF止跌
上勾。測試以 min_decline_days=6 取代原文23天，僅為縮短驗證用K線數，邏輯與原文一致。

本方法用到「前一天收盤／最低點」（prev_close/prev_low），須每根K線各自一個交易日，
故一律以 freq="1D" 組K線（預設5分鐘會讓所有K線落在同一天，prev_close 全為NaN）。
"""

from helpers import make_bars

from wangtrader.core import Side, run
from wangtrader.methods.gq_03_04_dif_streak_reversal import DifStreakReversal

ROWS = [
    (99.5, 100.5, 99.0, 100.0),
    (100.0, 100.2, 97.8, 98.0),
    (98.0, 98.2, 95.8, 96.0),
    (96.0, 96.2, 93.8, 94.0),
    (94.0, 94.2, 91.8, 92.0),
    (92.0, 92.2, 89.8, 90.0),
    (90.0, 90.2, 87.8, 88.0),  # 連續下跌第6天，DIF跌幅止於此
    (90.0, 112.0, 89.0, 110.0),  # bar7：紅K，漲幅25% → DIF止跌上勾，買進訊號
]


def _bars(rows):
    return make_bars(rows, freq="1D")


def _params(**kw):
    base = dict(fast=1, slow=2, signal=3, min_decline_days=6, exit_mode="none")
    base.update(kw)
    return base


def test_signal_basic():
    res = run(DifStreakReversal(**_params()), _bars(ROWS))
    assert len(res.signals) == 1
    sig = res.signals[0]
    assert sig.side == Side.LONG and sig.reason == "DIF連續下跌慣性改變買點"
    assert sig.price == 110.0
    assert abs(sig.stop - 110.0 * 0.93) < 1e-9  # 固定7%停損


def test_f1_decline_run_not_long_enough_is_filtered():
    res = run(DifStreakReversal(**_params(min_decline_days=7)), _bars(ROWS))
    assert res.signals == []


def test_f_not_red_bar_is_filtered():
    rows = list(ROWS)
    rows[7] = (112.0, 113.0, 89.0, 110.0)  # 開盤高於收盤 → 黑K
    res = run(DifStreakReversal(**_params()), _bars(rows))
    assert res.signals == []


def test_f_gain_below_threshold_is_filtered():
    rows = list(ROWS)
    rows[7] = (88.5, 90.5, 87.9, 90.0)  # 漲幅僅約2.27%（<4%），但DIF仍止跌上勾
    res = run(DifStreakReversal(**_params()), _bars(rows))
    assert res.signals == []


def test_stop_7pct():
    rows = ROWS + [
        (110.0, 111.0, 90.0, 91.0),  # 觸及7%停損（102.3）
    ]
    res = run(DifStreakReversal(**_params()), _bars(rows))
    t = res.trades[0]
    assert t.reason_out == "停損" and abs(t.exit_price - 102.3) < 1e-9


def test_exit_prev_day_low_break():
    """出場：收盤價跌破前一天最低點即出場（p.160）；停損維持不變，以較不易觸及的價位驗證此規則獨立生效。"""
    rows = ROWS + [
        (110.0, 120.0, 108.0, 118.0),  # 續漲，低點108（高於停損102.3）
        (118.0, 125.0, 115.0, 122.0),  # 續漲，低點115（前一天最低點，供下一根比對）
        (122.0, 123.0, 108.0, 110.0),  # 收盤110 < 前一天(bar9)最低點115，且本根低點108仍高於停損 → 跌破前一天低點出場
    ]
    res = run(DifStreakReversal(**_params(exit_mode="prev_day_low")), _bars(rows))
    assert len(res.trades) == 1
    t = res.trades[0]
    assert t.reason_out == "跌破前一天低點" and t.exit_price == 110.0
