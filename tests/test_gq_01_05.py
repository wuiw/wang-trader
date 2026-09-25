from helpers import make_bars

from wangtrader.core import Context, Position, Side, prepare, run
from wangtrader.methods.gq_01_05_dark_cloud_cover import DarkCloudCover

# i0-i1 提供rally比較基準；i2-i3墊高roll_high；i4=A(長紅K線，漲幅14.9%，近3根新高，累計漲幅16.7%)；
# i5=B(覆蓋線：跳高1.79%<=3%，收盤102跌破A實體中點104.75)。
PREFIX = [
    (95, 96, 94, 95, 1000),
    (95, 96, 94, 96, 1000),
    (96, 97, 95, 96.5, 1000),
    (96.5, 98, 96, 97.5, 1000),
    (97.5, 115, 97, 112, 1000),   # A
    (114, 114.2, 100, 102, 1500),  # B：覆蓋線
]


def _strat(**kw):
    return DarkCloudCover(high_lookback=3, rally_lookback=3, rally_min_pct=10.0,
                           vol_ma_period=3, vol_spike_ratio=2.0, **kw)


def test_counter_buy_breaks_cover_high_with_stop_at_signal_low():
    bars = make_bars(PREFIX + [
        (102, 105, 99, 103, 1000),   # 未突破114.2
        (103, 120, 102, 118, 1000),  # 收盤118 > 114.2 → 反軋買點，停損=本根最低點102
    ])
    res = run(_strat(), bars)
    assert len(res.signals) == 1
    sig = res.signals[0]
    assert sig.side == Side.LONG and sig.reason == "反軋買點"
    assert sig.price == 118 and sig.stop == 102


def test_c5_confirms_reversal_exits_existing_long():
    bars = make_bars(PREFIX + [
        (102, 103, 90, 92, 1000),  # 收盤92 < A最低點97 → 轉空確認，既有多單出場
    ])
    df = prepare(bars)
    strat = _strat()
    df = strat.prepare(df)
    pos = Position(Side.LONG, entry_i=0, entry_price=100.0, stop=None, best=100.0)
    seen = []
    for i in range(len(df)):
        ctx = Context(i=i, df=df, pos=pos, trades=[], stopped=None)
        od = strat.on_bar(ctx)
        if od:
            seen.extend(od)
    assert len(seen) == 1
    assert seen[0].action == "exit" and seen[0].reason == "覆蓋線反轉(多單出場)"


def test_gap_over_threshold_no_candidate():
    rows = list(PREFIX)
    rows[5] = (118, 118.2, 100, 102, 1500)  # 跳高5.36%（>3%門檻）
    bars = make_bars(rows + [
        (102, 105, 99, 103, 1000),
        (103, 120, 102, 119, 1000),
    ])
    res = run(_strat(), bars)
    assert res.signals == []


def test_close_not_below_midpoint_no_candidate():
    rows = list(PREFIX)
    rows[5] = (114, 114.2, 108, 110, 1500)  # 收盤110未跌破實體中點104.75 → C3不成立
    bars = make_bars(rows + [
        (110, 112, 105, 108, 1000),
        (108, 120, 107, 118, 1000),  # 即使收盤突破114.2，因未成立候選，不觸發
    ])
    res = run(_strat(), bars)
    assert res.signals == []
