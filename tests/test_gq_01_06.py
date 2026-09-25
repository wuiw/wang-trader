from helpers import make_bars

from wangtrader.core import Side, run
from wangtrader.methods.gq_01_06_bearish_engulfing import BearishEngulfing

# 高檔情境：i0-i1提供rally基準；i2-i3墊高roll_high；i4=A(長紅K線，漲幅14.9%，近3根新高，累計漲幅16.7%，高檔成立)；
# i5=B(吞噜線：跳高0.87%<=3%，收盤90跌破A最低點97，且爆量5000)。
HIGH_PREFIX = [
    (95, 96, 94, 95, 1000),
    (95, 96, 94, 96, 1000),
    (96, 97, 95, 96.5, 1000),
    (96.5, 98, 96, 97.5, 1000),
    (97.5, 115, 97, 112, 1000),      # A
    (116, 116.5, 88, 90, 5000),      # B：高檔爆量吞噜線
]

# 非高檔情境：rally僅4%<10%門檻 → is_high不成立；j4=A(漲幅3.5%)；j5=B(跳高0.48%，跌破A最低點199，未爆量)。
LOW_PREFIX = [
    (200, 201, 199, 200, 1000),
    (200, 201, 199, 199, 1000),
    (199, 200, 198, 199.5, 1000),
    (199.5, 201, 199, 200, 1000),
    (200, 210, 199, 207, 1000),       # A
    (211, 212, 190, 195, 1000),       # B：無爆量/非高檔吞噜線
]


def _strat(**kw):
    return BearishEngulfing(high_lookback=3, rally_lookback=3, rally_min_pct=10.0,
                             vol_ma_period=3, vol_spike_ratio=2.0, **kw)


def test_high_volume_engulfing_confirms_short_entry():
    bars = make_bars(HIGH_PREFIX + [
        (90, 92, 80, 85, 1000),  # 收盤85 < B最低點88 → 反轉確認，進場放空
    ])
    res = run(_strat(), bars)
    assert len(res.signals) == 1
    sig = res.signals[0]
    assert sig.side == Side.SHORT and sig.reason == "陰線吞噬反轉(空)" and sig.stop is None


def test_no_volume_low_position_engulfing_confirms_long_entry():
    bars = make_bars(LOW_PREFIX + [
        (195, 220, 194, 215, 1000),  # 收盤215 > B最高點212 → 突破吞噬線最高點，買進
    ])
    res = run(_strat(), bars)
    assert len(res.signals) == 1
    sig = res.signals[0]
    assert sig.side == Side.LONG and sig.reason == "吞噬線買點(多)" and sig.stop is None


def test_high_position_without_volume_spike_no_candidate():
    rows = list(HIGH_PREFIX)
    rows[4] = (97.5, 115, 97, 112, 1000)
    rows[5] = (116, 116.5, 88, 90, 1000)  # 未爆量（高檔但不爆量 → 兩條路徑均不成立）
    bars = make_bars(rows + [
        (90, 92, 80, 85, 1000),
        (85, 120, 84, 118, 1000),
    ])
    res = run(_strat(), bars)
    assert res.signals == []


def test_low_position_with_volume_spike_no_candidate():
    rows = list(LOW_PREFIX)
    rows[5] = (211, 212, 190, 195, 5000)  # 爆量（非高檔但爆量 → 兩條路徑均不成立）
    bars = make_bars(rows + [
        (195, 220, 194, 215, 1000),
        (215, 216, 180, 185, 1000),
    ])
    res = run(_strat(), bars)
    assert res.signals == []
