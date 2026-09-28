from helpers import make_bars

from wangtrader.core import Side, prepare, run
from wangtrader.methods.q3_09_01_ma_dragonfly import MaDragonfly

PREV = (10000, 10005, 9995, 10000)


def _rising_prefix(step=20, n=14, start=10000):
    return [start + step * (k + 1) for k in range(n)]


def _rows_from_closes(closes, start_open=10000):
    rows = []
    prev_c = start_open
    for c in closes:
        o = prev_c
        h, l = (c + 2, o - 2) if c >= o else (o + 2, c - 2)
        rows.append((o, h, l, c))
        prev_c = c
    return rows


def test_dragonfly_buy_signal():
    """均線朝上，A棒黑K收盤跌破MA10（均線未因此反轉），B棒紅K收盤收回MA10之上 -> 買訊。"""
    closes = _rising_prefix() + [10180, 10210]  # A: 跌破; B: 收回
    bars = make_bars(_rows_from_closes(closes), prev_day=PREV)
    res = run(MaDragonfly(use_five_reversal=False), bars)
    sig = res.signals[0]
    assert sig.side == Side.LONG and sig.reason == "均線蜻蜓點水買訊"
    t = res.trades[0]
    assert t.entry_price == 10210 and sig.stop == 10190  # 進場價 - 20


def test_dragonfly_sell_signal():
    """均線朝下，A棒紅K收盤突破MA10（均線未因此反轉），B棒黑K收盤收回MA10之下 -> 空訊。"""
    closes = _rising_prefix(step=-20) + [9820, 9790]
    bars = make_bars(_rows_from_closes(closes), prev_day=PREV)
    res = run(MaDragonfly(use_five_reversal=False), bars)
    sig = res.signals[0]
    assert sig.side == Side.SHORT and sig.reason == "均線蜻蜓點水空訊"
    t = res.trades[0]
    assert t.entry_price == 9790 and sig.stop == 9810  # 進場價 + 20


def test_f1_ma_just_reversed_is_ignored_even_if_bar_count_looks_enough():
    """F1（p.197，圖9-8）：均線剛由降轉升（谷點才剛形成），即使跌破/收回的兩根K線本身沒問題，
    仍不能視為蜻蜓點水買訊——均線須已朝方向運行一段時間。長期下跌後單一根急拉尚不足以確立多方
    趨勢，均線仍在追價、離真正翻揚沒幾根，此時的跌破/收回不合理。"""
    def rows_from_closes(closes, start_open=10000):
        rows = []
        prev_c = start_open
        for c in closes:
            o = prev_c
            h, l = (c + 2, o - 2) if c >= o else (o + 2, c - 2)
            rows.append((o, h, l, c))
            prev_c = c
        return rows

    falling = [10000 - 20 * (k + 1) for k in range(20)]  # 長期下跌至9600
    rebound = [9620, 9640, 9660, 9680, 9700, 9720]  # 急拉反彈，MA10剛在最後一根轉為朝上
    pullback = [9640]  # A：黑K，MA剛轉折沒幾根就跌破
    recover = [9700]   # B：紅K，收盤收回MA之上
    bars = make_bars(rows_from_closes(falling + rebound + pullback + recover), prev_day=PREV)
    res = run(MaDragonfly(use_five_reversal=False), bars)
    assert res.signals == []


def test_f1_trend_too_short_ignored():
    """F1：均線本波方向持續根數不足 -> 不宜操作（p.199）。"""
    closes = _rising_prefix() + [10180, 10210]
    bars = make_bars(_rows_from_closes(closes), prev_day=PREV)
    assert run(MaDragonfly(min_trend_bars=6, use_five_reversal=False), bars).signals == []
    res = run(MaDragonfly(min_trend_bars=5, use_five_reversal=False), bars)
    assert res.signals[0].side == Side.LONG


def test_f3_turn_distance_too_small_ignored():
    """F3/C5：峰谷點距均線轉折點不足 min_turn_dist -> 忽略（p.192-193, 199）。"""
    closes = _rising_prefix() + [10180, 10210]
    bars = make_bars(_rows_from_closes(closes), prev_day=PREV)
    assert run(MaDragonfly(min_turn_dist=200, use_five_reversal=False), bars).signals == []
    res = run(MaDragonfly(min_turn_dist=190, use_five_reversal=False), bars)
    assert res.signals[0].side == Side.LONG


def test_f2_region_uniqueness_blocks_second_breach_too_close():
    """F2：距離上一次跌破/突破不足 region_min_bars -> 非本波段第一次回測，忽略（p.199）。"""
    base = _rising_prefix()
    after1 = [10230 + 20 * k for k in range(10)]
    dip2, rec2 = after1[-1] - 100, after1[-1] - 100 + 30
    closes = base + [10180, 10210] + after1 + [dip2, rec2]
    bars = make_bars(_rows_from_closes(closes), prev_day=PREV)
    df = prepare(bars)

    strat_wide = MaDragonfly(region_min_bars=15, min_trend_bars=0, min_turn_dist=0, use_five_reversal=False)
    sig_wide = strat_wide.prepare(df)["sig_side"]
    assert (sig_wide != 0).sum() == 1  # 第二次跌破因距上次僅12根 < 15，被F2忽略

    strat_narrow = MaDragonfly(region_min_bars=5, min_trend_bars=0, min_turn_dist=0, use_five_reversal=False)
    sig_narrow = strat_narrow.prepare(df)["sig_side"]
    assert (sig_narrow != 0).sum() == 2  # 距上次12根 >= 5，兩次都成立


def test_f5_opposite_extreme_signal_suppresses_dragonfly():
    """F5：A棒與其前一根構成逆向極端訊號（頂雙黑）時，忽略本順向訊號，逆向優先（p.200-201）。"""
    rows = _rows_from_closes(_rising_prefix(n=12))
    rows.append((10260, 10300, 10236, 10255))  # X：黑K，創新高（頂雙黑第一根）
    rows.append((10255, 10256, 10160, 10165))  # Y(A)：黑K跌破MA，同時收盤跌破X低點 -> 頂雙黑
    rows.append((10165, 10225, 10160, 10220))  # B：紅K收回MA之上
    bars = make_bars(rows, prev_day=PREV)

    res_skip = run(MaDragonfly(region_min_bars=0, min_trend_bars=0, min_turn_dist=0,
                                use_five_reversal=False, skip_on_opposite_extreme=True), bars)
    assert res_skip.signals == []

    res_keep = run(MaDragonfly(region_min_bars=0, min_trend_bars=0, min_turn_dist=0,
                                use_five_reversal=False, skip_on_opposite_extreme=False), bars)
    assert res_keep.signals[0].side == Side.LONG


def test_five_red_first_black_exits_long():
    """出場：連續5根以上紅K（幅度>=40）後首根不創新高的黑K -> 五紅遇首黑平倉（p.191, 193, 195）。"""
    rows = _rows_from_closes(_rising_prefix() + [10180, 10210])  # 進場 10210（index16）
    prev_c = 10210
    for c in [10290, 10310, 10330, 10350, 10370]:
        o = prev_c
        rows.append((o, c + 1, o - 1, c))
        prev_c = c
    rows.append((prev_c, prev_c, 10369, 10365))  # 黑K未創新高、未破前低 -> 五紅遇首黑
    bars = make_bars(rows, prev_day=PREV)
    res = run(MaDragonfly(use_five_reversal=True), bars)
    t = res.trades[0]
    assert t.reason_out == "五紅遇首黑" and t.exit_price == 10365


def test_large_bar_midpoint_stop_capped_at_20_points():
    """大K線 midpoint 模式（p.198）：停損設實體中點，但最大虧損仍以 20 點為上限。"""
    closes = _rising_prefix() + [10180, 10250]  # B 實體 70 點 > 30 -> 大K線
    bars = make_bars(_rows_from_closes(closes), prev_day=PREV)
    res = run(MaDragonfly(use_five_reversal=False, large_bar_mode="midpoint"), bars)
    sig = res.signals[0]
    assert sig.reason == "均線蜻蜓點水買訊(大K線)"
    assert sig.stop == 10230  # max(中點 10215, 進場價 10250 - 20)
    res_wait = run(MaDragonfly(use_five_reversal=False), bars)
    sig_w = res_wait.signals[0]
    assert sig_w.reason == "均線蜻蜓點水買訊(補進場)" and sig_w.stop == 10178 and sig_w.price == 10198


def test_wait_bars_minutes_converted_by_bar_interval():
    """max_wait_minutes：以同交易日相鄰K線時間差換成根數；None 或 time 欄非時間戳時用 max_wait 根。"""
    from helpers import make_bars as _mb

    from wangtrader.core import prepare as _prep
    from wangtrader.methods.q3_09_01_ma_dragonfly import Params as _P, _wait_bars

    df = _prep(_mb([(100, 101, 99, 100)] * 6, freq="3min"))
    assert _wait_bars(df, 5, _P()) == 10
    assert _wait_bars(df, 5, _P(max_wait_minutes=10)) == 3
    assert _wait_bars(df, 5, _P(max_wait_minutes=1)) == 1
    assert _wait_bars(df.assign(time=range(len(df))), 5, _P(max_wait_minutes=10)) == 10


def test_f1_min_trend_minutes():
    """F1 分鐘版：均線轉折到 A 棒 6 根，5 分K＝30 分鐘；須「超過」門檻，設定時取代根數判斷。"""
    closes = _rising_prefix() + [10180, 10210]
    bars = make_bars(_rows_from_closes(closes), prev_day=PREV)
    assert run(MaDragonfly(min_trend_minutes=30, use_five_reversal=False), bars).signals == []
    res = run(MaDragonfly(min_trend_minutes=29, min_trend_bars=100, use_five_reversal=False), bars)
    assert res.signals[0].side == Side.LONG
    bars1 = make_bars(_rows_from_closes(closes), prev_day=PREV, freq="1min")
    assert run(MaDragonfly(min_trend_minutes=15, use_five_reversal=False), bars1).signals == []


def test_f2_region_min_minutes():
    """F2 分鐘版：兩次跌破間隔 12 根，5 分K＝60 分鐘。"""
    base = _rising_prefix()
    after1 = [10230 + 20 * k for k in range(10)]
    dip2, rec2 = after1[-1] - 100, after1[-1] - 100 + 30
    closes = base + [10180, 10210] + after1 + [dip2, rec2]
    df = prepare(make_bars(_rows_from_closes(closes), prev_day=PREV))
    kw = dict(region_min_bars=0, min_trend_bars=0, min_turn_dist=0, use_five_reversal=False)
    assert (MaDragonfly(region_min_minutes=61, **kw).prepare(df)["sig_side"] != 0).sum() == 1
    assert (MaDragonfly(region_min_minutes=60, **kw).prepare(df)["sig_side"] != 0).sum() == 2
