from helpers import make_bars

from wangtrader.core import Side, run
from wangtrader.methods.gq_01_08_ma_inertia import MaInertia

P = dict(fast_period=2, slow_period=3, long_exit_n=2, short_exit_n=2)


def test_long_entry_and_n_day_low_exit():
    bars = make_bars([
        (99, 101, 98, 100),
        (100, 110, 99, 102),
        (102, 105, 101, 104),   # 快2>慢3 → 黃金交叉，多頭（尚未突破前一根高點110，不進場）
        (105, 112, 104, 108),   # 收盤108 > 前一根高點105 → 買進
        (108, 115, 107, 113),
        (113, 116, 109, 111),
        (110, 111, 95, 100),    # 收盤100 < min(107,109)=107 → 跌破2日低出場
    ])
    res = run(MaInertia(**P), bars)
    assert len(res.signals) == 1
    sig = res.signals[0]
    assert sig.side == Side.LONG and sig.reason == "K線慣性買進" and sig.stop is None
    t = res.trades[0]
    assert t.side == Side.LONG and t.entry_price == 108
    assert t.reason_out == "跌破N日低點出場" and t.exit_price == 100


def test_short_direct_entry_and_n_day_high_exit_when_flat_filter_disabled():
    bars = make_bars([
        (101, 103, 99, 100),
        (100, 101, 90, 98),
        (98, 99, 95, 96),      # 快2<慢3 → 死亡交叉，空頭
        (94, 96, 90, 88),      # 收盤88 < 前一根低點95 → 放空
        (88, 90, 85, 86),
        (86, 88, 83, 84),
        (85, 95, 84, 93),      # 收盤93 > max(90,88)=90 → 突破2日高回補
    ])
    res = run(MaInertia(**P, no_short_below_flat=False), bars)
    assert len(res.signals) == 1
    sig = res.signals[0]
    assert sig.side == Side.SHORT and sig.reason == "K線慣性放空" and sig.stop is None
    t = res.trades[0]
    assert t.side == Side.SHORT and t.entry_price == 88
    assert t.reason_out == "突破N日高點回補" and t.exit_price == 93


def test_short_signal_waits_for_flat_before_filling():
    bars = make_bars([
        (101, 103, 99, 100),
        (100, 101, 90, 98),
        (98, 99, 95, 96),      # 死亡交叉，空頭
        (94, 96, 90, 88),      # 收盤88 < 前一根低點95 → 放空訊號，須待隔日觸及平盤(88)以上
        (85, 90, 84, 87),      # 隔日最高90 >= 88 → 觸價成交，成交價 max(開85, 88)=88
        (87, 89, 83, 85),
        (85, 87, 80, 82),
        (83, 95, 82, 92),      # 收盤92 > max(89,87)=89 → 突破2日高回補
    ])
    res = run(MaInertia(**P), bars)
    assert len(res.signals) == 1 and res.signals[0].reason == "K線慣性放空(等平盤)"
    t = res.trades[0]
    assert t.side == Side.SHORT and t.entry_i == 4 and t.entry_price == 88
    assert t.reason_out == "突破N日高點回補" and t.exit_price == 92
