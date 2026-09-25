from helpers import make_bars

from wangtrader.core import Context, Position, Side, prepare
from wangtrader.methods.gq_01_01_big_bar_trail_exit import BigBarTrailExit, big_bar_trail_exit


def _run_exit(bars, side, entry_price=100.0):
    """手動驅動出場函式：本方法不含進場規則，run() 永遠不會有交易（見模組docstring）。"""
    df = prepare(bars)
    strat = BigBarTrailExit()
    df = strat.prepare(df) if hasattr(strat, "prepare") else df
    pos = Position(side, entry_i=0, entry_price=entry_price, stop=None, best=entry_price)
    results = []
    for i in range(len(df)):
        ctx = Context(i=i, df=df, pos=pos, trades=[], stopped=None)
        ex = big_bar_trail_exit(ctx, 4.0)
        results.append(ex)
        if ex is not None:
            break
    return results


def test_long_exit_on_close_below_big_bar_low():
    bars = make_bars([
        (100, 106, 98, 105),   # i0：大陽線 (5%>=4%)，最低點98 → 出場水準=98
        (105, 110, 100, 108),  # i1：漲幅僅2.86%，非大陽線，不更新，98仍有效，收盤108未跌破
        (108, 109, 101, 97),   # i2：收盤97 < 98 → 出場
    ])
    res = _run_exit(bars, Side.LONG)
    assert res[0] is None and res[1] is None
    assert res[2] is not None and res[2].reason == "大陽線出場"


def test_long_stop_only_moves_up_never_down():
    bars = make_bars([
        (100, 106, 98, 105),    # i0：大陽線，低點98 → stop=98
        (105, 130, 90, 125),    # i1：漲幅19%大陽線，但低點90<98 → stop仍維持98（只朝有利方向）
        (125, 126, 97, 96),     # i2：收盤96 < 98 → 出場（若曾被下修到90則不會在此出場）
    ])
    res = _run_exit(bars, Side.LONG)
    assert res[0] is None and res[1] is None
    assert res[2] is not None and res[2].reason == "大陽線出場"


def test_short_exit_on_close_above_big_bar_high_body_rule():
    bars = make_bars([
        (100, 102, 93, 94),   # i0：黑K，實體跌幅6%>=4% → 大陰線，高點102 → stop=102
        (94, 96, 90, 93),     # i1：小K，不更新
        (93, 105, 92, 104),   # i2：收盤104 > 102 → 出場
    ])
    res = _run_exit(bars, Side.SHORT)
    assert res[0] is None and res[1] is None
    assert res[2] is not None and res[2].reason == "大陰線出場"


def test_short_gap_down_4pct_alt_rule():
    # 實體跌幅僅2.04%（<4%，不符「長黑K線」推論門檻），但跳空開低且跌幅（相對前一日收盤）達4% → 仍成立
    bars = make_bars([
        (196, 197, 190, 192),  # i0：開盤196<前收200（跳空開低），跌幅(200-192)/200=4.0% → 大陰線，高點197→stop=197
        (192, 200, 191, 198),  # i1：收盤198 > 197 → 出場
    ], prev_day=(199, 201, 198, 200))
    res = _run_exit(bars, Side.SHORT)
    # prepare() 在有 prev_day 時會多出一根前一日K線在最前面（session 0），
    # 故 res[0]=前一日K線（無事發生）、res[1]=i0（設定出場水準，未出場）、res[2]=i1（出場）
    assert res[0] is None and res[1] is None
    assert res[2] is not None and res[2].reason == "大陰線出場"


def test_small_body_does_not_qualify_as_big_bar():
    # 全程都是小K線（漲跌幅<4%），出場水準永遠不會被設定，不論收盤如何都不出場
    bars = make_bars([
        (100, 101, 99, 100.5),
        (100.5, 101.2, 99.5, 100.2),
        (100.2, 100.8, 90, 91),  # 即使大跌，因為從未出現「大K線」設定出場水準，不會出場
    ])
    res = _run_exit(bars, Side.LONG)
    assert all(r is None for r in res)
