"""sg-04 凹洞買訊／凹洞空訊（讀書會整理，書外方法）。

規格文件：methods/讀書會/sg-04-凹洞買訊空訊.md

來源：作者原文 2025-06-03（post 1910002686479150），規則只寫在兩張附圖上
（reference/study-group/fbdl_g3__img_1910002686479150_01.jpg、_02.jpg）：
  圖1：「以突破均線的首根或首二根形成層級1的峰點，出現凹洞買訊」；
       「B為凹洞買訊，但幅度過大，可以忽略或等次根折返再接，以距B的低點20點位置承接」；
       「若直接進場，則設置20點停損應對」。均線為 MA10。
  圖2：「以跌破均線的首根或首二根形成層級1的谷點，出現凹洞空訊」；
       「B為凹洞空訊，但幅度過大，可以忽略或等折返再接，以距B的高點20點位置承接」；
       「若直接進場，則設置20點停損應對」。

訊號：
  買訊：A＝收盤由 MA10 之下（含等於）站上 MA10 的首根。A 或 A 的下一根形成層級1峰點
    （core.pivots.find_pivots，只用已確認者：峰點右側 1 根走完才可用）。其後第一根收盤高於
    該峰點價的K線＝B（凹洞買訊），B 收盤進場（圖上未寫收盤或盤中，依圖推定收盤）。
    A、A+1 都沒有形成峰點 → 此次突破不成立。
  空訊：鏡像（跌破 MA10 首根、層級1谷點、收盤跌破谷點價）。
  設定只在同一交易日內有效；每個 A 只取第一次成立。
  同向再出現新的突破首根即以新 A 取代舊設定（「首根」的字面意義）；反向穿越均線時清除本方向設定
  （推論：原文未寫峰點後能否跌回均線下；收盤跌回均線下後要再突破峰點必先重新站上均線，形成新 A，
  所以此條與「以新 A 取代」效果相同）。
  max_wait_minutes（推論，預設 None 不限）：B 距 A 超過此分鐘數即作廢；原文未寫。
進場／停損：
  直接進場：B 收盤進場，停損＝收盤 ∓ stop_points（20，原文）。
  幅度過大（B 高低差 > large_bar_points；原文沒有門檻，預設 None＝不判斷，一律直接進場）：
    large_bar_mode="wait"：掛限價於 B 低點＋20（空：B 高點−20）等折返承接（原文），
      有效 wait_bars 根（原文多方「次根」＝1）；承接後停損＝B 低點（空：B 高點），即承接價外 20 點（推論，原文未寫）。
    large_bar_mode="skip"：忽略訊號（原文「可以忽略」）。
出場：原文未規定；不設停利，持有至停損、反向訊號（引擎先平倉再反手）或收盤。

週期：不限。所有門檻以點數／分鐘表示（「次根」依原文以根數表示）。
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from wangtrader.core import Context, Order, Side, Strategy
from wangtrader.core.indicators import sma
from wangtrader.core.pivots import find_pivots

METHOD_ID = "sg-04"


@dataclass
class Params:
    ma_period: int = 10  # 圖上標 MA10（1910002686479150，2025-06-03）
    pivot_level: int = 1  # 「層級1的峰點／谷點」（同上）
    stop_points: float = 20.0  # 「若直接進場，則設置20點停損應對」（同上）
    large_bar_points: float | None = None  # 「幅度過大」門檻：B 高低差超過即視為過大；原文無數值，None＝不判斷
    large_bar_mode: str = "wait"  # "wait"：距 B 低(高)點 20 點承接；"skip"：忽略（兩者皆原文）
    wait_offset: float = 20.0  # 「以距B的低點20點位置承接」（同上）
    wait_bars: int = 1  # 「等次根折返再接」（同上，多方圖）
    max_wait_minutes: float | None = None  # 推論：B 距 A 的時間上限；原文未寫，預設不限


def _elapsed_minutes(df: pd.DataFrame, a: int, b: int) -> float:
    try:
        return (df.at[b, "time"] - df.at[a, "time"]).total_seconds() / 60.0
    except (AttributeError, TypeError, KeyError):
        return float(b - a)


class Dent(Strategy):
    method_id = METHOD_ID

    def __init__(self, **kw) -> None:
        self.p = Params(**kw)
        if self.p.large_bar_mode not in ("wait", "skip"):
            raise ValueError(self.p.large_bar_mode)
        # 方向 → [A index, 峰谷點價格 or None]
        self._setup: dict[Side, list] = {}
        self._peaks: dict[int, float] = {}
        self._troughs: dict[int, float] = {}

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["ma"] = sma(df["close"], self.p.ma_period)
        piv = find_pivots(df, self.p.pivot_level)
        self._peaks = {pv.index: pv.price for pv in piv if pv.kind == "peak"}
        self._troughs = {pv.index: pv.price for pv in piv if pv.kind == "trough"}
        self._setup = {}
        return df

    def _advance(self, df: pd.DataFrame, i: int, side: Side) -> bool:
        """推進某方向的設定；回傳本根是否成立訊號（B）。"""
        st = self._setup.get(side)
        if st is None:
            return False
        a, level = st
        p = self.p
        if df.at[a, "session"] != df.at[i, "session"]:
            self._setup.pop(side)
            return False
        if p.max_wait_minutes is not None and _elapsed_minutes(df, a, i) > p.max_wait_minutes:
            self._setup.pop(side)
            return False
        if level is None:
            pivots = self._peaks if side == Side.LONG else self._troughs
            lv = p.pivot_level
            for j in (a, a + 1):  # 「首根或首二根」
                if j in pivots and j + lv <= i and df.at[j + lv, "session"] == df.at[a, "session"]:
                    st[1] = level = pivots[j]
                    break
            if level is None:
                if i >= a + 1 + lv:  # 首二根的峰谷也已可確認卻不成立 → 作廢
                    self._setup.pop(side)
                return False
        c = df.at[i, "close"]
        if (c > level) if side == Side.LONG else (c < level):
            self._setup.pop(side)
            return True
        return False

    def on_bar(self, ctx: Context):
        p, df, i = self.p, ctx.df, ctx.i
        if i < 1:
            return None
        ma, ma0 = df.at[i, "ma"], df.at[i - 1, "ma"]
        c, c0 = df.at[i, "close"], df.at[i - 1, "close"]
        if ma == ma and ma0 == ma0:
            up = c > ma and c0 <= ma0
            dn = c < ma and c0 >= ma0
            if up:
                self._setup[Side.LONG] = [i, None]
                self._setup.pop(Side.SHORT, None)
            elif dn:
                self._setup[Side.SHORT] = [i, None]
                self._setup.pop(Side.LONG, None)
        hit_l = self._advance(df, i, Side.LONG)
        hit_s = self._advance(df, i, Side.SHORT)
        if not (hit_l or hit_s):
            return None
        side = Side.LONG if hit_l else Side.SHORT
        name = "凹洞買訊" if side == Side.LONG else "凹洞空訊"
        hi, lo = float(df.at[i, "high"]), float(df.at[i, "low"])
        if p.large_bar_points is not None and hi - lo > p.large_bar_points:
            if p.large_bar_mode == "skip":
                return None
            if side == Side.LONG:
                return [Order.enter_limit(side, lo + p.wait_offset, p.wait_bars, stop=lo,
                                          reason=name + "（折返承接）")]
            return [Order.enter_limit(side, hi - p.wait_offset, p.wait_bars, stop=hi,
                                      reason=name + "（折返承接）")]
        stop = c - p.stop_points if side == Side.LONG else c + p.stop_points
        return [Order.enter(side, stop=float(stop), reason=name)]
