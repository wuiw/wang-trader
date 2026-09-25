"""gq-04-01 乖離率買點分布。

以 bias_period=3（取代原文10日，僅為縮短驗證用K線數）驗算：收盤價序列讓 bar3 的10日乖離率
(以3日均線近似) 觸及 -14.29%（<= -12%閾值），bar5 收盤突破前一天(bar4)最高點，通過濾網成立買訊；
之後價格再度回落，bar8 最低點跌破 D1（bar3）的最低點但本次乖離率未再觸及 -12%（背離），
bar10 收盤突破前一天(bar9)最高點，構成背離型買訊。
"""

from helpers import make_bars

from wangtrader.core import Side, run
from wangtrader.methods.gq_04_01_bias_reversal_buy import BiasReversalBuy

ROWS = [
    (99.5, 100.5, 99.0, 100.0),
    (100.0, 100.5, 99.5, 100.0),
    (100.0, 100.5, 99.5, 100.0),
    (85.0, 86.0, 78.0, 80.0),  # bar3：乖離觸及 -14.29%（D1）
    (80.0, 81.0, 77.0, 79.0),
    (80.0, 92.0, 79.0, 90.0),  # bar5：收盤90 > 前一天最高81 → 濾網成立，買訊
    (90.0, 97.0, 89.0, 95.0),
    (95.0, 98.0, 94.0, 96.0),
    (90.0, 91.0, 75.0, 85.0),  # bar8：最低點75 跌破 D1 低點78，乖離未再觸及閾值 → 背離確認
    (85.0, 86.0, 83.0, 84.0),
    (84.0, 97.0, 83.0, 95.0),  # bar10：收盤95 > 前一天最高86 → 背離型濾網成立，買訊
]


def _bars(rows):
    return make_bars(rows, freq="1D")


def _params(**kw):
    base = dict(bias_period=3)
    base.update(kw)
    return base


def test_filter_and_divergence_signals():
    res = run(BiasReversalBuy(**_params()), _bars(ROWS))
    assert len(res.signals) == 2
    s1, s2 = res.signals
    assert s1.side == Side.LONG and s1.reason == "乖離率買點" and s1.price == 90.0 and s1.stop == 78.0
    assert s2.side == Side.LONG and s2.reason == "乖離率買點(背離)" and s2.price == 95.0 and s2.stop == 75.0


def test_stop_mode_pct():
    res = run(BiasReversalBuy(**_params(stop_mode="pct")), _bars(ROWS[:6]))
    sig = res.signals[0]
    assert abs(sig.stop - 90.0 * 0.93) < 1e-9


def test_f1_search_window_expired_is_filtered():
    res = run(BiasReversalBuy(**_params(search_window=1)), _bars(ROWS[:6]))
    assert res.signals == []


def test_quality_shadow_too_long_is_filtered():
    rows = list(ROWS[:6])
    rows[5] = (88.0, 95.0, 79.0, 90.0)  # 上影線5 > 實體2 → 不符合品質濾網
    res = run(BiasReversalBuy(**_params()), _bars(rows))
    assert res.signals == []
