"""sg-01 RSI 鈍化簡化訊號（讀書會整理，書外方法；由 q2-06-04 衍生）。

規格文件：methods/讀書會/sg-01-RSI鈍化簡化訊號.md

來源：期跡奇績讀書會 2021-04-09（post 1395231430824767），學員整理、助教未否認：
  「不需要跳空多少點以上才成立的限制，只有第一根K線的RSI觸90的條件，而之後5分K三根內、1分K十根內，
   K線收盤越過首根K線高點，呈現無遮蔽，就成為鈍化買訊，中間是否出現黑K造成RSI低於90，沒有限制」。

訊號：
  買訊：RSI(5) 首次觸及 ob_extreme（90）以上的那根為首根（前一根未達 90 或無值）；首根之後
    window_minutes 分鐘內（依K線時間戳計算，不綁週期；原文 5分K三根≈15分、1分K十根＝10分），
    某根收盤高於首根至前一根所有K線的最高點（無遮蔽）→ 當根收盤買進。
  空訊：鏡像，RSI 首次觸及 os_extreme（10）以下，收盤低於首根至前一根所有K線的最低點。
  每個首根只取第一次成立；超過時間窗仍未成立即作廢，等下一次「首次觸及」。
停損（推論，原文未規定）：首根最低（最高）點；距離超過 stop_points（20）時，改用 q2-01 均線訊號
  停損法（多＝收盤 −(10＋個位數)、空＝收盤 ＋(20−個位數)，個位數 0 時 20 點），比照 q2-06-04。
出場：原文未規定；不設停利，持有至停損、反向訊號（引擎先平倉再反手）或收盤。

週期：不限。所有門檻以點數／分鐘表示。
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from wangtrader.core import Context, Order, Side, Strategy
from wangtrader.core.indicators import rsi as rsi_indicator

METHOD_ID = "sg-01"


@dataclass
class Params:
    rsi_period: int = 5  # 讀書會確認 RSI 參數為 5（2020-04 post 1121217044892875）
    rsi_method: str = "wilder"  # 與 q2-06-04 相同
    ob_extreme: float = 90.0
    os_extreme: float = 10.0
    window_minutes: float = 10.0  # 原文 1分K十根＝10分；5分K三根≈15分
    stop_points: float = 20.0  # 停損上限（推論，比照 q2-06-04「宜控制在 20 點以內」）
    stop_min_offset: float = 10.0  # 均線訊號停損法固定部分（q2-01 p.13）
    stop_integer_points: float = 20.0  # 均線訊號停損法整數價位固定點數（q2-01 p.13）


def _digit_stop(side: Side, close_price: float, min_offset: float, integer_points: float) -> float:
    """均線訊號停損法（q2-01 p.13–14）：多＝收盤 −(10 + 個位數)；空＝收盤 +(20 − 個位數)；個位數 0 時固定點數。"""
    digit = int(round(close_price)) % 10
    if digit == 0:
        pts = integer_points
    elif side == Side.LONG:
        pts = min_offset + digit
    else:
        pts = 2 * min_offset - digit
    return close_price - pts if side == Side.LONG else close_price + pts


def _elapsed_minutes(df: pd.DataFrame, a: int, b: int) -> float:
    try:
        return (df.at[b, "time"] - df.at[a, "time"]).total_seconds() / 60.0
    except (AttributeError, TypeError, KeyError):
        return float(b - a)


class RsiBluntQuick(Strategy):
    method_id = METHOD_ID

    def __init__(self, **kw) -> None:
        self.p = Params(**kw)
        self._first: dict[tuple, int] = {}  # (session, 觸發側) → 首根 index

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["rsi"] = rsi_indicator(df["close"], self.p.rsi_period, self.p.rsi_method)
        return df

    def _step(self, df: pd.DataFrame, i: int, sess, ob_side: bool) -> tuple[Side, float] | None:
        """ob_side=True：超買側（產生買訊）；False：超賣側（產生空訊）。回傳 (方向, 首根停損參考價)。"""
        p = self.p
        r = df.at[i, "rsi"]
        if r != r:
            return None
        key = (sess, ob_side)
        hit = r >= p.ob_extreme if ob_side else r <= p.os_extreme
        first = self._first.get(key)
        if first is not None and _elapsed_minutes(df, first, i) > p.window_minutes:
            self._first.pop(key)
            first = None
        if first is None:
            prev_hit = False
            if i >= 1 and df.at[i - 1, "session"] == sess:
                r0 = df.at[i - 1, "rsi"]
                prev_hit = r0 == r0 and (r0 >= p.ob_extreme if ob_side else r0 <= p.os_extreme)
            if hit and not prev_hit:
                self._first[key] = i
            return None
        close = df.at[i, "close"]
        if ob_side:
            if close > df["high"].iloc[first:i].max():
                self._first.pop(key)
                return Side.LONG, float(df.at[first, "low"])
        elif close < df["low"].iloc[first:i].min():
            self._first.pop(key)
            return Side.SHORT, float(df.at[first, "high"])
        return None

    def on_bar(self, ctx: Context):
        p, df, i = self.p, ctx.df, ctx.i
        sess = df.at[i, "session"]
        hit_l = self._step(df, i, sess, True)  # 兩側都要推進狀態
        hit_s = self._step(df, i, sess, False)
        hit = hit_l if hit_l is not None else hit_s
        if hit is None:
            return None
        side, ref = hit
        entry = float(df.at[i, "close"])
        stop = ref
        if abs(entry - stop) > p.stop_points:
            stop = _digit_stop(side, entry, p.stop_min_offset, p.stop_integer_points)
        name = "RSI鈍化簡化買訊" if side == Side.LONG else "RSI鈍化簡化空訊"
        return [Order.enter(side, stop=float(stop), reason=name)]
