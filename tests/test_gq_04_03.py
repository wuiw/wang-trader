"""gq-04-03 威廉指標找極端點。

各測試以 williams_period 覆寫書中50/100（僅為縮短驗證用K線數），並事先以 `_williams` 驗算。
"""

from helpers import make_bars

from wangtrader.core import Side, run
from wangtrader.methods.gq_04_03_williams_extreme import WilliamsExtreme

SHORT_ROWS = [
    (100, 101, 99, 100.5),
    (100.5, 103, 100, 102.5),
    (102.5, 106, 102, 105.5),
    (105.5, 110, 105, 109),
    (109, 115, 108, 114),
    (114, 120, 113, 119),  # 峰位：高點120
    (119, 120, 110, 112),  # 收盤112 < 前一根真實低點min(113,114)=113 → 賣出訊號
]

LONG_ROWS = [(round(220 - o, 2), round(220 - low, 2), round(220 - h, 2), round(220 - c, 2))
             for (o, h, low, c) in SHORT_ROWS]


def _bars(rows):
    return make_bars(rows, freq="1D")


def test_short_signal_basic():
    res = run(WilliamsExtreme(williams_period=4), _bars(SHORT_ROWS))
    assert len(res.signals) == 1
    sig = res.signals[0]
    assert sig.side == Side.SHORT and sig.reason == "威廉指標找極端點-賣出"
    assert sig.price == 112.0 and sig.stop == 121.0  # 峰位120 + stop_tick(1)


def test_long_signal_basic():
    res = run(WilliamsExtreme(williams_period=4), _bars(LONG_ROWS))
    assert len(res.signals) == 1
    sig = res.signals[0]
    assert sig.side == Side.LONG and sig.reason == "威廉指標找極端點-買進"
    assert sig.price == 108.0


def test_f1_never_touched_extreme_is_filtered():
    """進入超買區但未曾觸及90以上 → 不列入極端位置（p.193-194）。"""
    rows = [
        (100, 101, 99, 100.5),
        (100.5, 103, 100, 102.5),
        (102.5, 106, 102, 105.5),
        (105.5, 109, 105, 107.5),  # wr=85，進入區但不到90
        (107.5, 110, 106, 108.0),  # wr=80，仍在區內
        (108.0, 110.5, 104, 105.0),  # wr=35，離開；雖跌破真實低點但因F1不成立
    ]
    res = run(WilliamsExtreme(williams_period=4), _bars(rows))
    assert res.signals == []


def test_f2_distance_from_extreme_too_far_is_filtered():
    """離開位置距最高峰超過 max_bars_from_extreme（預設4）→ 不予採用（p.192、196-197）。"""
    rows = [
        (100, 101, 99, 100.3), (100.3, 101.3, 99.3, 100.6), (100.6, 101.6, 99.6, 100.9),
        (100.9, 101.9, 99.9, 101.2), (101.2, 102.2, 100.2, 101.5), (101.5, 102.5, 100.5, 101.8),
        (101.8, 102.8, 100.8, 102.1), (102.1, 105, 101, 104), (104, 110, 103, 109),
        (109, 120, 108, 119),  # 峰位（第9根，高點120）
        (119, 119.2, 117, 118.5), (118.5, 118.7, 116.5, 118), (118, 118.2, 116, 117.5),
        (117.5, 117.7, 115.5, 117),
        (117, 117.2, 115, 110),  # 第14根才破一低，距峰位已5根 > 預設4
    ]
    res_default = run(WilliamsExtreme(williams_period=8), _bars(rows))
    assert res_default.signals == []
    res_relaxed = run(WilliamsExtreme(williams_period=8, max_bars_from_extreme=10), _bars(rows))
    assert len(res_relaxed.signals) == 1 and res_relaxed.signals[0].price == 110.0


def test_f3_dwell_too_long_is_filtered():
    """進入到離開超過 max_dwell_bars（預設10天）仍未離開 → 不宜逆勢（p.195）。"""
    lead = []
    c = 100.0
    for _ in range(14):
        c += 0.3
        lead.append((c - 0.3, c + 0.2, c - 0.4, c))
    rows = lead + [(c, c + 5, c - 0.5, c + 5)]  # 峰位
    h = c + 5
    for _ in range(13):
        h -= 0.02
        rows.append((h - 0.3, h, h - 0.5, h - 0.2))
    rows.append((h - 0.3 - 0.02, h - 0.1, h - 15.02, h - 10.02))  # 離開＋破一低，距峰位已14天(超過10天)

    # max_bars_from_extreme 放寬到100，只單獨檢驗F3（停留天數）的過濾效果
    res_default = run(WilliamsExtreme(williams_period=14, max_bars_from_extreme=100), _bars(rows))
    assert res_default.signals == []
    res_relaxed = run(WilliamsExtreme(williams_period=14, max_bars_from_extreme=100, max_dwell_bars=20),
                       _bars(rows))
    assert len(res_relaxed.signals) == 1 and res_relaxed.signals[0].side == Side.SHORT


def test_e1_early_signal_requires_inertia():
    """提前訊號：威廉值尚未離開超買區時已跌破真實低點，須配合先前8根以上未破真實低點的慣性（p.192、198）。"""
    rows = [
        (100, 101, 50, 100.5),  # 極端低點50，讓窗口最低點長期偏低，威廉值不易因小回檔而離開超買區
        (100.5, 105, 101, 104),
        (104, 108, 103, 107),
        (107, 111, 106, 110),
        (110, 114, 109, 113),
        (113, 117, 112, 116),
        (116, 120, 115, 119),
        (119, 123, 118, 122),
        (122, 126, 121, 125),
        (125, 126, 110, 113),  # 威廉值首度達80仍在區內，但收盤113 < 真實低點121 → 提前賣訊
    ]
    res = run(WilliamsExtreme(williams_period=10), _bars(rows))
    assert len(res.signals) == 1
    sig = res.signals[0]
    assert sig.side == Side.SHORT and sig.reason == "威廉指標提前賣訊" and sig.price == 113.0

    res_strict = run(WilliamsExtreme(williams_period=10, inertia_bars=20), _bars(rows))
    assert res_strict.signals == []
