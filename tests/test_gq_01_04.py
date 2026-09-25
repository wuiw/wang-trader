from helpers import make_bars

from wangtrader.core import Context, Position, Side, prepare, run
from wangtrader.methods.gq_01_04_black_belt_hold import BlackBeltHold

# i0-i1 提供rally比較基準；i2-i3墊高；i4=A(長紅K線，漲幅14.9%，累計漲幅16.7%)；
# i5=B(黑執帶：跳空開高7.14%、開盤即最高、收盤=最低點112.45、相對A漲幅0.45%<1.5%、爆量5000)。
PREFIX = [
    (95, 96, 94, 95, 1000),
    (95, 96, 94, 96, 1000),
    (96, 97, 95, 96.5, 1000),
    (96.5, 98, 96, 97.5, 1000),
    (97.5, 115, 97, 112, 1000),        # A
    (120, 120, 112.45, 112.45, 5000),  # B：黑執帶
]


def _strat(**kw):
    return BlackBeltHold(rally_lookback=3, rally_min_pct=10.0, vol_ma_period=3, vol_spike_ratio=2.0, **kw)


def test_counter_buy_breaks_belt_high_with_stop_at_signal_low():
    bars = make_bars(PREFIX + [
        (112.45, 115, 110, 113, 1000),  # 未突破120
        (113, 125, 112, 122, 1000),     # 收盤122 > 120 → 反軋買點，停損=本根最低點112
    ])
    res = run(_strat(), bars)
    assert len(res.signals) == 1
    sig = res.signals[0]
    assert sig.side == Side.LONG and sig.reason == "反軋買點"
    assert sig.price == 122 and sig.stop == 112


def test_c6_confirms_reversal_exits_existing_long():
    bars = make_bars(PREFIX + [
        (112.45, 113, 85, 90, 1000),  # 收盤90 < 真實低點(A最低點97) → 反轉確認，既有多單出場
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
    assert seen[0].action == "exit" and seen[0].reason == "執帶反轉(多單出場)"


def test_no_volume_spike_no_candidate():
    rows = list(PREFIX)
    rows[4] = (97.5, 115, 97, 112, 1000)
    rows[5] = (120, 120, 112.45, 112.45, 1000)  # 無爆量（僅1000，未達均量*2倍門檻）
    bars = make_bars(rows + [
        (112.45, 115, 110, 113, 1000),
        (113, 125, 112, 122, 1000),  # 即使收盤突破120，因未成立候選，不應觸發
    ])
    res = run(_strat(), bars)
    assert res.signals == []


def test_gap_up_below_threshold_no_candidate():
    rows = list(PREFIX)
    rows[5] = (115.36, 115.36, 112.45, 112.45, 5000)  # 跳空僅3%（<5%門檻）
    bars = make_bars(rows + [
        (112.45, 115, 110, 113, 1000),
        (113, 120, 112, 118, 1000),
    ])
    res = run(_strat(), bars)
    assert res.signals == []
