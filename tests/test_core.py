from helpers import make_bars

from wangtrader.core import Order, Side, Strategy, prepare, run
from wangtrader.core.indicators import kd, rsi, sar, sma
from wangtrader.core.pivots import find_pivots, last_confirmed


def test_prepare_session_fields():
    df = prepare(make_bars([(100, 110, 95, 105), (105, 120, 104, 118)], prev_day=(90, 101, 89, 100)))
    assert list(df["session"]) == [0, 1, 1]
    assert df.at[1, "prev_close"] == 100 and df.at[1, "prev_high"] == 101
    assert df.at[2, "sess_high"] == 120 and df.at[2, "sess_low"] == 95
    assert df.at[2, "bar_no"] == 1 and df.at[2, "sess_open"] == 100


def test_indicators_shapes():
    df = prepare(make_bars([(100 + k, 101 + k, 99 + k, 100.5 + k) for k in range(30)]))
    assert sma(df["close"], 10).notna().sum() == 21
    r = rsi(df["close"], 5)
    assert r.iloc[-1] == 100.0  # 一路上漲
    assert kd(df).iloc[-1]["k"] > 80
    assert sar(df).iloc[-1]["trend"] == 1


def test_pivots_are_causal():
    df = prepare(make_bars([(10, 11, 9, 10), (10, 15, 9, 14), (14, 14, 8, 9), (9, 10, 7, 8)]))
    ps = find_pivots(df, level=1)
    peak = [p for p in ps if p.kind == "peak"][0]
    assert peak.index == 1 and peak.confirm == 2
    assert last_confirmed(ps, 1, "peak") is None
    assert last_confirmed(ps, 2, "peak") == peak


class _BuyFirst(Strategy):
    method_id = "test"

    def on_bar(self, ctx):
        if ctx.i == 0:
            return [Order.enter(Side.LONG, stop=ctx.bar()["close"] - 20, reason="t")]


def test_engine_stop_and_session_flat():
    bars = make_bars([(100, 101, 99, 100), (100, 105, 95, 104), (104, 104, 70, 75), (75, 76, 74, 75)])
    res = run(_BuyFirst(), bars)
    assert len(res.trades) == 1
    t = res.trades[0]
    assert t.reason_out == "停損" and t.exit_price == 80 and t.pnl == -20
    assert len(res.signals) == 1


class _LimitBuy(Strategy):
    method_id = "test"

    def on_bar(self, ctx):
        if ctx.i == 0:
            return [Order.enter_limit(Side.LONG, limit=95, expire=3, stop=90, reason="t")]


def test_limit_fill_bar_also_checks_stop():
    bars = make_bars([(100, 101, 99, 100), (100, 100, 80, 85), (85, 86, 84, 85)])
    t = run(_LimitBuy(), bars).trades[0]
    assert t.entry_i == 1 and t.entry_price == 95
    assert t.exit_i == 1 and t.exit_price == 90 and t.reason_out == "停損"


class _LimitBuyThenExitIfProfit(Strategy):
    """限價成交後，下一根若「持倉期間最有利價」已超過進場價就出場。"""

    method_id = "test"

    def on_bar(self, ctx):
        if ctx.i == 0:
            return [Order.enter_limit(Side.LONG, limit=95, expire=3, reason="t")]
        if ctx.pos is not None and ctx.i == ctx.pos.entry_i + 1 and ctx.pos.max_profit() > 0:
            return [Order.exit("hit")]


def test_limit_fill_bar_range_not_counted_as_best():
    # 第 1 根：開 100、高 130、低 95、收 100 → 限價 95 成交；該根的高點 130 不得算入最有利價。
    # 第 2 根高點 95 = 進場價 → max_profit 0 → 不出場（若誤計第 1 根高點 130 就會以 "hit" 出場）。
    bars = make_bars([(100, 101, 99, 100), (100, 130, 95, 100), (95, 95, 90, 92), (92, 93, 91, 92)])
    t = run(_LimitBuyThenExitIfProfit(), bars).trades[0]
    assert t.entry_i == 1 and t.entry_price == 95
    assert t.reason_out == "收盤平倉"
    # 對照：第 2 根有創高（高 100）→ max_profit 5 → 以 "hit" 出場
    bars2 = make_bars([(100, 101, 99, 100), (100, 130, 95, 100), (95, 100, 94, 96), (96, 97, 95, 96)])
    assert run(_LimitBuyThenExitIfProfit(), bars2).trades[0].reason_out == "hit"


class _EnterEveryBar(Strategy):
    method_id = "test"
    enter_on_last_bar = False

    def on_bar(self, ctx):
        if ctx.pos is None:
            return [Order.enter(Side.LONG, reason="t")]


def test_intraday_no_entry_on_last_bar_of_session():
    bars = make_bars([(100, 101, 99, 100), (100, 105, 95, 104)])
    res = run(_EnterEveryBar(), bars)
    # 第 0 根進場、第 1 根（最後一根）收盤平倉；第 1 根若再進場會變成零損益假交易
    assert len(res.trades) == 1 and res.trades[0].entry_i == 0 and res.trades[0].reason_out == "收盤平倉"
    assert len(res.signals) == 1  # 進場後同向訊號不再產生；最後一根無進場訊號因為仍持倉

    class _Swing(_EnterEveryBar):
        intraday = False

    res2 = run(_Swing(), bars)
    assert len(res2.trades) == 0  # 波段方法不受影響：部位一直持有到資料結束

    class _EnterLastOnly(Strategy):
        method_id = "test"
        enter_on_last_bar = False

        def on_bar(self, ctx):
            if ctx.i == 1:
                return [Order.enter(Side.SHORT, reason="t")]

    res3 = run(_EnterLastOnly(), bars)
    assert len(res3.signals) == 1 and len(res3.trades) == 0  # 訊號有記錄，但不建立部位
    _EnterLastOnly.enter_on_last_bar = True  # 預設行為：最後一根仍可進場（隨即收盤平倉，零損益）
    res4 = run(_EnterLastOnly(), bars)
    assert len(res4.trades) == 1 and res4.trades[0].pnl == 0


def test_combined_single_position_empty_keeps_columns():
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from run_combined import single_position

    import pandas as pd

    cols = ["method", "side", "entry_time", "exit_time", "entry_price", "exit_price", "pnl", "reason_out"]
    out = single_position(pd.DataFrame(columns=cols), reverse=True)
    assert list(out.columns) == cols and out.empty


def test_prev_valid_false_blanks_prev_fields():
    bars = make_bars([(100, 110, 95, 105)], prev_day=(90, 101, 89, 100))
    bars["prev_valid"] = [True, False]
    df = prepare(bars)
    assert df.at[1, "prev_close"] != df.at[1, "prev_close"]  # NaN
    assert df.at[1, "sess_high"] == 110
