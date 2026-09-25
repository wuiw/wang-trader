"""逐根 K 線的策略引擎（與週期無關）。

每個方法模組實作一個 `Strategy` 子類別：
  - `prepare(df)`：一次算好指標欄位（必須是因果計算）。
  - `on_bar(ctx)`：第 i 根收盤時被呼叫，回傳要下的 `Order`。

成交規則：
  - 市價進出場一律以「當根收盤價」成交（書中訊號都是收盤確認）。
  - 停損：預設盤中觸價即出場，成交價＝停損價（跳空越過則用開盤價）；
    `stop_on_close=True` 時改為收盤越過停損才出場，以收盤價成交。
  - 限價進場（補進場）：`Order(limit=..., expire=N)`，之後 N 根內觸價即以限價成交；
    成交當根若也觸及停損，保守視為同根停損；成交當根的高低點不計入「持倉期間最有利價」
    （盤中先後順序不可知，一律保守）。
  - 持有反向部位時收到進場單 → 先平倉再進場（反手）。同向部位則忽略。
  - `intraday=True`：每個交易日最後一根收盤強制平倉。`enter_on_last_bar=False` 時，最後一根收盤
    產生的進場單只記錄訊號、不建立部位（否則會產生「進場即平倉」的零損益假交易；回測腳本一律設 False，
    預設 True 只為了讓以最後一根當訊號根的單元測試維持原行為）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any

import pandas as pd

from .bars import prepare as _prepare


class Side(IntEnum):
    LONG = 1
    SHORT = -1


@dataclass
class Order:
    action: str  # "enter" | "exit"
    side: Side | None = None
    stop: float | None = None
    limit: float | None = None
    expire: int | None = None
    reason: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def enter(side: Side, stop: float | None = None, reason: str = "", **meta: Any) -> "Order":
        return Order("enter", side=side, stop=stop, reason=reason, meta=meta)

    @staticmethod
    def enter_limit(
        side: Side, limit: float, expire: int, stop: float | None = None, reason: str = "", **meta: Any
    ) -> "Order":
        return Order("enter", side=side, stop=stop, limit=limit, expire=expire, reason=reason, meta=meta)

    @staticmethod
    def exit(reason: str = "") -> "Order":
        return Order("exit", reason=reason)


@dataclass
class Position:
    side: Side
    entry_i: int
    entry_price: float
    stop: float | None
    reason: str = ""
    meta: dict[str, Any] = field(default_factory=dict)
    best: float = 0.0  # 持倉期間最有利價格（多單最高、空單最低）

    def profit(self, price: float) -> float:
        return (price - self.entry_price) * int(self.side)

    def max_profit(self) -> float:
        return self.profit(self.best)


@dataclass
class Trade:
    side: Side
    entry_i: int
    entry_price: float
    exit_i: int
    exit_price: float
    reason_in: str
    reason_out: str
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def pnl(self) -> float:
        return (self.exit_price - self.entry_price) * int(self.side)


@dataclass
class Signal:
    method: str
    i: int
    time: Any
    side: Side
    price: float
    stop: float | None
    reason: str
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class Context:
    i: int
    df: pd.DataFrame
    pos: Position | None
    trades: list[Trade]
    stopped: Trade | None  # 本根被停損出場的交易（供反手判斷）

    def bar(self, k: int = 0) -> pd.Series:
        """第 i-k 根 K 線。"""
        return self.df.iloc[self.i - k]

    def last_trade(self) -> Trade | None:
        return self.trades[-1] if self.trades else None


class Strategy:
    method_id: str = ""
    intraday: bool = True
    stop_on_close: bool = False
    enter_on_last_bar: bool = True  # 當沖：交易日最後一根收盤是否允許建立新部位（見檔頭）

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        return df

    def on_bar(self, ctx: Context) -> list[Order] | None:  # pragma: no cover
        raise NotImplementedError


@dataclass
class Result:
    df: pd.DataFrame
    trades: list[Trade]
    signals: list[Signal]

    def summary(self) -> dict[str, float]:
        n = len(self.trades)
        pnl = [t.pnl for t in self.trades]
        return {
            "trades": n,
            "wins": sum(p > 0 for p in pnl),
            "win_rate": (sum(p > 0 for p in pnl) / n) if n else 0.0,
            "total_points": float(sum(pnl)),
        }


def run(strategy: Strategy, df: pd.DataFrame, prepared: bool = False) -> Result:
    """對整段 K 線跑策略。df 未經 `bars.prepare` 時會自動處理。"""
    if not prepared:
        df = _prepare(df)
    df = strategy.prepare(df)
    o, h, lo, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    sess = df["session"].to_numpy()
    n = len(df)
    pos: Position | None = None
    pending: Order | None = None
    pending_left = 0
    trades: list[Trade] = []
    signals: list[Signal] = []

    def close_pos(i: int, price: float, reason: str) -> Trade:
        nonlocal pos
        assert pos is not None
        t = Trade(pos.side, pos.entry_i, pos.entry_price, i, price, pos.reason, reason, pos.meta)
        trades.append(t)
        pos = None
        return t

    def open_pos(i: int, od: Order, price: float) -> None:
        nonlocal pos
        pos = Position(od.side, i, price, od.stop, od.reason, dict(od.meta), best=price)

    for i in range(n):
        stopped: Trade | None = None
        filled_limit = False
        # 1. 待成交的限價單
        if pending is not None and pos is None:
            lim = pending.limit
            hit = lo[i] <= lim if pending.side == Side.LONG else h[i] >= lim
            if hit:
                fill = min(o[i], lim) if pending.side == Side.LONG else max(o[i], lim)
                open_pos(i, pending, fill)
                pending = None
                filled_limit = True
            else:
                pending_left -= 1
                if pending_left <= 0:
                    pending = None
        # 2. 停損（限價單盤中成交的那一根也要檢查：保守假設先成交、後觸及停損）
        if pos is not None and pos.stop is not None and (pos.entry_i < i or filled_limit):
            s = pos.stop
            if strategy.stop_on_close:
                if (c[i] <= s) if pos.side == Side.LONG else (c[i] >= s):
                    stopped = close_pos(i, c[i], "停損")
            elif pos.side == Side.LONG and lo[i] <= s:
                stopped = close_pos(i, min(o[i], s), "停損")
            elif pos.side == Side.SHORT and h[i] >= s:
                stopped = close_pos(i, max(o[i], s), "停損")
        if pos is not None and not filled_limit:
            pos.best = max(pos.best, h[i]) if pos.side == Side.LONG else min(pos.best, lo[i])
        # 3. 策略
        last_of_session = i == n - 1 or sess[i + 1] != sess[i]
        ctx = Context(i, df, pos, trades, stopped)
        for od in strategy.on_bar(ctx) or []:
            if od.action == "exit":
                if pos is not None:
                    close_pos(i, c[i], od.reason or "出場")
                continue
            if od.side is None:
                raise ValueError("進場單必須指定 side")
            signals.append(
                Signal(strategy.method_id, i, df.at[i, "time"], od.side,
                       od.limit if od.limit is not None else c[i], od.stop, od.reason, dict(od.meta))
            )
            if pos is not None and pos.side == od.side:
                continue
            if strategy.intraday and last_of_session and not strategy.enter_on_last_bar:
                continue  # 當沖：最後一根不建立新部位（既有部位由步驟 4 收盤平倉）
            if pos is not None:
                close_pos(i, c[i], "反手")
            if od.limit is not None:
                pending, pending_left = od, int(od.expire or 1)
            else:
                open_pos(i, od, c[i])
                pending = None
            ctx.pos = pos
        # 4. 當沖：交易日最後一根平倉
        if strategy.intraday and last_of_session:
            if pos is not None:
                close_pos(i, c[i], "收盤平倉")
            pending = None
    return Result(df, trades, signals)
