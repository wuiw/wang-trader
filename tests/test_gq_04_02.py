"""gq-04-02 DMI石筍現象。

以 dmi_period=3（取代原文未規定的預設14，僅為縮短驗證用K線數）驗算下列收盤價序列：
前4根小幅震盪使 +DI 落於 <=25（起升點基準），其後連續走高使 +DI 一路推升穿越40臨界點（第8根
達79.79），第9根收盤跌破前一根（第8根）最低點 → 放空訊號。

買進（-DI）測試以「200-原始收盤價」（此處取220）鏡射原始K線：反射會讓 +DM/-DM 互換，
使 minus_di(鏡射) 在數值上等於 plus_di(原始)，因此鏡射後會在對稱位置出現「一路推升穿越35→
收盤突破前一根最高點」的買進訊號（已用 `_dmi` 實際驗算）。
"""

from helpers import make_bars

from wangtrader.core import Side, run
from wangtrader.methods.gq_04_02_dmi_stalagmite import DmiStalagmite

SHORT_ROWS = [
    (100, 101, 99, 100.5),
    (100.2, 100.8, 99.5, 100.3),
    (100.1, 100.6, 99.6, 100.2),
    (100.0, 101.0, 99.8, 100.5),
    (100.5, 103, 100.4, 102.5),
    (102.5, 106, 102.4, 105.5),
    (105.5, 110, 105.4, 109),
    (109, 115, 108.9, 114),
    (114, 120, 113.9, 119),  # 第8根：+DI 越過40臨界點（79.79），峰位120
    (119, 120, 110, 111),  # 第9根：收盤跌破前一根最低點113.9 → 放空訊號
]

LONG_ROWS = [(round(220 - o, 2), round(220 - low, 2), round(220 - h, 2), round(220 - c, 2))
             for (o, h, low, c) in SHORT_ROWS]


def _bars(rows):
    return make_bars(rows, freq="1D")


def _params(**kw):
    base = dict(dmi_period=3, exit_mode="none")
    base.update(kw)
    return base


def test_short_signal_basic():
    res = run(DmiStalagmite(**_params()), _bars(SHORT_ROWS))
    assert len(res.signals) == 1
    sig = res.signals[0]
    assert sig.side == Side.SHORT and sig.reason == "DMI石筍放空"
    assert sig.price == 111.0
    assert sig.stop == 121.0  # 峰位120 + stop_tick(1)


def test_long_signal_basic():
    res = run(DmiStalagmite(**_params()), _bars(LONG_ROWS))
    assert len(res.signals) == 1
    sig = res.signals[0]
    assert sig.side == Side.LONG and sig.reason == "DMI石筍買進"
    assert sig.price == 109.0


def test_f_three_black_declines_invalidate_run():
    """一路推升期間出現3根收黑的下彎K線 → 本輪作廢，其後即使大跌破前低也不成立訊號（p.176、186）。"""
    rows = SHORT_ROWS[:9] + [
        (119, 119.3, 118.5, 118.8),  # 黑K，下彎1
        (118.8, 119.0, 118.2, 118.5),  # 黑K，下彎2
        (118.5, 118.7, 118.0, 118.2),  # 黑K，下彎3 → 作廢
        (118.2, 118.4, 90, 95),  # 大跌破前低，但本輪已作廢，不應成立
    ]
    res = run(DmiStalagmite(**_params()), _bars(rows))
    assert res.signals == []


def test_f_timing_filter_extreme_too_far():
    """距峰位超過 max_bars_from_extreme（預設3天）才出現破一低 → 訊號不明確，過濾（p.192、196-197）。"""
    rows = SHORT_ROWS[:9] + [
        (117.0, 117.6, 116.5, 117.2),
        (116.5, 117.0, 116.0, 116.7),
        (116.0, 116.5, 115.5, 116.2),
        (116.0, 116.3, 113.0, 114.0),  # 第4根才破一低，距峰位(第8根)已4根 > 預設3
    ]
    res_default = run(DmiStalagmite(**_params()), _bars(rows))
    assert res_default.signals == []
    res_relaxed = run(DmiStalagmite(**_params(max_bars_from_extreme=10, max_pct_from_extreme=None)), _bars(rows))
    assert len(res_relaxed.signals) == 1 and res_relaxed.signals[0].price == 114.0


def test_five_red_exception():
    """連續5根紅K推升越過臨界點後，首根黑K未破前低但收盤在前一根紅K實體一半之下，仍成立訊號（p.176-177）。"""
    rows = SHORT_ROWS[:9] + [
        (118, 118.5, 114.5, 115),  # 黑K，收115 < 前一根(第8根)實體中點116.5，且未跌破前低113.9
    ]
    res = run(DmiStalagmite(**_params()), _bars(rows))
    assert len(res.signals) == 1
    sig = res.signals[0]
    assert sig.side == Side.SHORT and sig.reason == "DMI石筍放空(五紅例外)" and sig.price == 115.0
