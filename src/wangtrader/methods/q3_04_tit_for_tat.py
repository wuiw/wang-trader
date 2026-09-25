"""q3-04 以牙還牙空訊／以牙還牙買訊（《期貨奇績3》第四章，p.84–97）。

規格文件：methods/期貨奇績3/q3-04-以牙還牙.md

訊號（p.84, 93）：當下盤中極端K線（A）＋隔一根反方向K線（B），
  兩者各自漲跌點數差距 ≤ tolerance_points（預設1點）。
  以牙還牙空訊：A為當下盤中最高K線（最高點最高且收盤最高同時成立）之紅K，
    漲點 X=close-open；B為黑K，跌點 Y=open-close；|X-Y| ≤ tolerance_points。
  以牙還牙買訊（鏡像）：A為當下盤中最低K線之黑K，跌點 X=open-close；
    B為紅K，漲點 Y=close-open；|X-Y| ≤ tolerance_points。
  B 不得越過 A 的極端點（B 高點 ≤ A 高點／B 低點 ≥ A 低點），否則 A 就不再是「當下最高／最低K線」
    （p.84「其中一根 K 線一定是最高 K 線」；壘頂／壘底＝同高／同低，p.84）。
  極端位置前提：p.84「以牙還牙的訊號必然出現在當下盤中極端位置…極端位置的定義也都和前面所有
    極端位置訊號一樣」→ 套用 30/40 點極端位置判定（is_extreme_position），require_extreme 開關控制。
進場（p.84）：訊號K（B）收盤確認後立即以收盤價進場，方向與B同向（即與A相反）。
  書中未提及需等拉回或有其他補進場條件。
停損（推論，本章未明文）：依本書極端位置訊號的一貫作法（p.21, 23, 50, 113），設在 A 的極端點
  （穿越 stop_tick 即出場），但距進場價最多 stop_points（預設 20 點）。設 stop_points=None 則不設停損。
過濾：
  F1 漲跌點差距 > tolerance_points → 即使壘頂/壘底外觀相同，仍不成立（屬訊號定義本身，p.84）
  F2 母K未同時符合最高/最低點與收盤最高/最低 → 不是合法母K線（屬訊號定義本身，p.93）
  F3 同一天同一類型訊號第一次已停損 → 第二次出現忽略不進場（p.92）
  F4 必須在極端位置：盤中震幅 ≥ extreme_range 或距平盤 ≥ extreme_from_prev_close（p.84）
出場：書中未提供本訊號出場規則（範例提及「連五紅遇首黑平倉」屬另一章 q3-06，獨立模組
  不得引用，故不實作）；exit_mode 提供 "ladder"/"ma"/"sar"/"none"（預設 none）作為推論性
  技術選項，未經原文證實。
反手：書中僅於「作者提醒」段落提及可能反手，但未給出明確觸發條件（p.88-89），
  屬提醒而非規則，本模組不實作（避免原文沒有的規則自行發明）。

週期：不限。所有門檻以點數表示。
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from wangtrader.core import Context, Order, Side, Strategy
from wangtrader.core.bars import is_extreme_position
from wangtrader.core.exits import ladder_exit, ma_exit, sar_exit
from wangtrader.core.indicators import sar, sma

METHOD_ID = "q3-04"


@dataclass
class Params:
    tolerance_points: float = 1.0  # p.84, 96
    stop_points: float | None = 20.0  # 單筆最大風險（推論：全書一貫 20 點）；None = 不設停損
    stop_tick: float = 1.0  # A 極端點穿越此點數即停損（p.23「穿越 1 個跳動單位」）
    require_extreme: bool = True  # 極端位置前提（p.84「定義和前面所有極端位置訊號一樣」）
    extreme_range: float = 30.0  # p.49, 57（第二章定義）
    extreme_from_prev_close: float = 40.0
    same_side_stop_once: bool = True  # F3，p.92
    exit_mode: str = "none"  # 推論；書中未提供本訊號出場規則
    profit_target: float = 20.0
    ma_period: int = 10


class TitForTat(Strategy):
    method_id = METHOD_ID

    def __init__(self, **kw) -> None:
        self.p = Params(**kw)
        self._stopped_sides: dict[int, set[Side]] = {}

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["sess_close_max"] = df.groupby("session")["close"].cummax()
        df["sess_close_min"] = df.groupby("session")["close"].cummin()
        df["ma"] = sma(df["close"], self.p.ma_period)
        s = sar(df)
        df["sar"], df["sar_trend"] = s["sar"], s["trend"]
        return df

    @staticmethod
    def _is_dual_high(df: pd.DataFrame, idx: int) -> bool:
        return bool(df.at[idx, "high"] == df.at[idx, "sess_high"] and df.at[idx, "close"] == df.at[idx, "sess_close_max"])

    @staticmethod
    def _is_dual_low(df: pd.DataFrame, idx: int) -> bool:
        return bool(df.at[idx, "low"] == df.at[idx, "sess_low"] and df.at[idx, "close"] == df.at[idx, "sess_close_min"])

    def detect(self, df: pd.DataFrame, i: int) -> tuple[Side, float] | None:
        """第 i 根（B，訊號K）收盤時是否成立訊號，回傳 (方向, A的極端價)。"""
        if i < 1:
            return None
        a, b = df.iloc[i - 1], df.iloc[i]
        if a["session"] != b["session"]:
            return None
        tol = self.p.tolerance_points
        if a["close"] > a["open"] and self._is_dual_high(df, i - 1) and b["close"] < b["open"] and b["high"] <= a["high"]:
            x = a["close"] - a["open"]
            y = b["open"] - b["close"]
            if abs(x - y) <= tol:
                return Side.SHORT, float(a["high"])
        if a["close"] < a["open"] and self._is_dual_low(df, i - 1) and b["close"] > b["open"] and b["low"] >= a["low"]:
            x = a["open"] - a["close"]
            y = b["close"] - b["open"]
            if abs(x - y) <= tol:
                return Side.LONG, float(a["low"])
        return None

    def on_bar(self, ctx: Context):
        p, df, i = self.p, ctx.df, ctx.i
        sess = int(df.at[i, "session"])

        if ctx.stopped is not None:
            self._stopped_sides.setdefault(sess, set()).add(ctx.stopped.side)

        if ctx.pos is not None:
            ex = {
                "ladder": lambda: ladder_exit(ctx, p.profit_target),
                "ma": lambda: ma_exit(ctx, "ma", p.profit_target),
                "sar": lambda: sar_exit(ctx, p.profit_target),
                "none": lambda: None,
            }[p.exit_mode]()
            return [ex] if ex else None

        hit = self.detect(df, i)
        if hit is None:
            return None
        side, ext = hit

        # F3：同方向已停損過一次
        if p.same_side_stop_once and side in self._stopped_sides.get(sess, set()):
            return None
        # 極端位置前提（p.84）
        if p.require_extreme and not is_extreme_position(df, i, p.extreme_range, p.extreme_from_prev_close):
            return None

        b = df.iloc[i]
        name = "以牙還牙空訊" if side == Side.SHORT else "以牙還牙買訊"
        stop = None
        if p.stop_points is not None:
            entry = float(b["close"])
            # 停損＝A 極端點外 stop_tick，但距進場價最多 stop_points
            if side == Side.LONG:
                stop = max(ext - p.stop_tick, entry - p.stop_points)
            else:
                stop = min(ext + p.stop_tick, entry + p.stop_points)
        return [Order.enter(side, stop=stop, reason=name, extreme=ext)]
