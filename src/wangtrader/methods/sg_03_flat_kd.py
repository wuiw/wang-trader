"""sg-03 平盤KD訊號（讀書會整理，書外方法；作者原文）。

規格文件：methods/讀書會/sg-03-平盤KD訊號.md
整理檔：extracted/study-group/newmethods/平盤KD.md

來源：期跡奇績讀書會 2025-12-08（post 2066158764196874，作者原文，5 圖）：
  「以平盤為界，平盤上，找KD皆在20以下，金叉買進，在平盤下，找KD皆在80上，死叉做空。」
  KD 參數：作者留言確認 9、3、3（2025-12-09、2025-12-18）。

訊號：
  買訊：價格在平盤（昨收）之上，K、D 皆 < oversold（20），K 由下往上穿越 D（金叉）→ 當根收盤買進。
  空訊：價格在平盤之下，K、D 皆 > overbought（80），K 由上往下穿越 D（死叉）→ 當根收盤做空。
  金叉：前一根 K ≤ D、當根 K > D；死叉：前一根 K ≥ D、當根 K < D。
  未定參數（原文沒寫，依圖例選預設）：
    zone_bar：「KD皆在20下／80上」看哪一根。預設 "prev"＝交叉前一根（圖 1、2、3 交叉當根 K 已回到
      門檻內，只有前一根 K、D 都在門檻外；圖 5 兩根都成立）；"cross"＝交叉當根。
    flat_mode：「在平盤上／下」怎麼判斷。預設 "close"＝訊號K收盤（圖 2 A 點K棒上緣貼著平盤線、收盤在下）；
      "bar"＝整根K棒（多：最低 > 平盤；空：最高 < 平盤）。
停損（推論，原文未規定）：KD 在門檻外那一段（本交易日內、連續 K、D 皆在門檻外的K棒）到訊號K的
  最低（最高）點；距離超過 stop_points（20）時改用 q2-01 均線訊號停損法
  （多＝收盤 −(10＋個位數)、空＝收盤 ＋(20−個位數)，個位數 0 時 20 點），比照 sg-01。
出場：原文未規定；不設停利，持有至停損、反向訊號（引擎先平倉再反手）或收盤。

週期：不限（圖例推估 5 分K）。所有門檻以點數表示。
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from wangtrader.core import Context, Order, Side, Strategy
from wangtrader.core.indicators import kd as kd_indicator

METHOD_ID = "sg-03"


@dataclass
class Params:
    kd_n: int = 9  # 作者留言確認 9、3、3（post 2066158764196874，2025-12-09／12-18）
    k_period: int = 3
    d_period: int = 3
    oversold: float = 20.0  # 原文「KD皆在20以下」（2025-12-08）
    overbought: float = 80.0  # 原文「KD皆在80上」（2025-12-08）
    zone_bar: str = "prev"  # "prev"＝交叉前一根 K、D 皆在門檻外（依圖 1、2、3）；"cross"＝交叉當根
    flat_mode: str = "close"  # "close"＝收盤在平盤上/下（依圖 2 A 點）；"bar"＝整根K棒在平盤上/下
    stop_points: float = 20.0  # 停損上限（推論，比照 sg-01）
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


class FlatKd(Strategy):
    method_id = METHOD_ID

    def __init__(self, **kw) -> None:
        self.p = Params(**kw)
        if self.p.zone_bar not in ("prev", "cross"):
            raise ValueError("zone_bar 必須是 'prev' 或 'cross'")
        if self.p.flat_mode not in ("close", "bar"):
            raise ValueError("flat_mode 必須是 'close' 或 'bar'")

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        kd = kd_indicator(df, self.p.kd_n, self.p.k_period, self.p.d_period)
        df["k"] = kd["k"]
        df["d"] = kd["d"]
        return df

    def _in_zone(self, df: pd.DataFrame, j: int, long: bool) -> bool:
        k, d = df.at[j, "k"], df.at[j, "d"]
        if long:
            return k < self.p.oversold and d < self.p.oversold
        return k > self.p.overbought and d > self.p.overbought

    def detect(self, df: pd.DataFrame, i: int) -> tuple[Side, float] | None:
        """回傳 (方向, 停損參考價)；不成立回傳 None。"""
        p = self.p
        if i < 1:
            return None
        pc = df.at[i, "prev_close"]
        if pc != pc:
            return None
        k0, d0, k1, d1 = df.at[i - 1, "k"], df.at[i - 1, "d"], df.at[i, "k"], df.at[i, "d"]
        if k0 <= d0 and k1 > d1:
            long = True
        elif k0 >= d0 and k1 < d1:
            long = False
        else:
            return None
        zb = i - 1 if p.zone_bar == "prev" else i
        if not self._in_zone(df, zb, long):
            return None
        if p.flat_mode == "close":
            px = df.at[i, "close"]
            above, below = px > pc, px < pc
        else:
            above, below = df.at[i, "low"] > pc, df.at[i, "high"] < pc
        if (long and not above) or (not long and not below):
            return None
        # 停損參考（推論）：本交易日內連續 KD 在門檻外的一段起點 → 訊號K 的極端點
        sess = df.at[i, "session"]
        start = zb
        while start - 1 >= 0 and df.at[start - 1, "session"] == sess and self._in_zone(df, start - 1, long):
            start -= 1
        if df.at[start, "session"] != sess:
            start = i
        if long:
            return Side.LONG, float(df["low"].iloc[start : i + 1].min())
        return Side.SHORT, float(df["high"].iloc[start : i + 1].max())

    def on_bar(self, ctx: Context):
        p = self.p
        hit = self.detect(ctx.df, ctx.i)
        if hit is None:
            return None
        side, ref = hit
        entry = float(ctx.df.at[ctx.i, "close"])
        stop = ref
        if abs(entry - stop) > p.stop_points:
            stop = _digit_stop(side, entry, p.stop_min_offset, p.stop_integer_points)
        name = "平盤KD買訊" if side == Side.LONG else "平盤KD空訊"
        return [Order.enter(side, stop=float(stop), reason=name)]
