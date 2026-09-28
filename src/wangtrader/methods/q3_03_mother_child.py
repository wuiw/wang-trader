"""q3-03 頂母子空訊／底母子買訊（《期貨奇績3》第三章，p.67–79）。

規格文件：methods/期貨奇績3/q3-03-頂底母子.md

訊號（p.67–68）：母K（極端K）＋子K（懷孕於母K實體與高低點範圍內）＋訊號K（反向確認）。
  頂母子（空）：母K為當下盤中最高K線（最高點最高且收盤最高同時成立）之紅K；
    子K實體落在母K實體內、子K高低點嚴格夾在母K高低點內（不可相等）；
    訊號K為黑K，最高點不高於母K最高點，收盤 ≤ 母K開盤價，且收盤跌破子K最低點。
  底母子（多，鏡像）：母K為當下盤中最低K線之黑K；子K同上；訊號K為紅K，
    收盤 ≥ 母K開盤價，且收盤突破子K最高點。
    訊號K最低點不低於母K最低點（書中僅明確空方版本 C4，多方鏡像未見原文條列，
    以 mirror_low_bound 開關標示為推論，預設開啟）。
進場（p.70, 73）：訊號K距母K極端點 ≤ stop_points → 收盤直接進場；距離較大 → far_entry_mode：
  "pullback" 補進場等待拉回（限價，max_wait 根（或 max_wait_minutes 分鐘）內未成交即失效，p.73）、"direct" 直接進場但停損固定
  stop_points、"ignore" 忽略。距離 ≥ giveup_distance（40 點，p.73）時原則上放生不操作，直接忽略
  （即使書中允許執意進場也僅能等拉回，不可直接以進場價±20點方式進場，本模組簡化為一律忽略）。
停損（p.70）：設在母K極端點（頂母子＝母K最高點，穿越 stop_tick 即出場），但距進場價最多
  stop_points——p.70「A 的高點超過訊號收盤 30 點，在設停損位置自然不能超過 20 點限制」、
  圖3-4「訊號K距離最低點剛好 20 點…設停損 20 點」；本書極端位置訊號一貫以極端點為停損、
  20 點為風險上限（p.21, 23, 50, 113）。
過濾：
  F1 子K與母K高低點相等 → 不成立母子關係（屬訊號定義本身，p.67）
  F2 子K實體超出母K實體範圍 → 不成立（屬訊號定義本身，p.67, 74）
  F3 母K僅符合最高/最低點或收盤其中一項 → 不是合法母K線（屬訊號定義本身，p.74）
  F4 訊號K影線觸及母K開盤價但收盤未真正跨越 → 不成立（僅檢查收盤，屬訊號定義本身，p.71）
  F5 必須在極端位置：盤中震幅 ≥ extreme_range，或距平盤 ≥ extreme_from_prev_close（p.68-69）
  F6 訊號K距母K極端點 ≥ giveup_distance（40點）→ 放棄不操作（p.73）
出場（p.72-73，新增）：折返平倉——獲利曾達 retrace_trigger 點（書中未給明確門檻數字，示範為
  16 點，以「曾真正獲利」為門檻，預設 1 點）後又折返回進場價（含）以下，即撤單平倉了結，不論
  是否達一般 20 點停利目標（沿用 core.exits.retrace_exit）。此規則恆常啟用（retrace_to_entry）；
  exit_mode 另提供 "ladder"/"ma"/"sar"/"none"（預設 none）作為推論性技術選項，未經原文證實，
  與折返平倉可疊加使用。

週期：不限。所有門檻以點數表示。
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from wangtrader.core import Context, Order, Side, Strategy
from wangtrader.core.bars import is_extreme_position
from wangtrader.core.exits import ladder_exit, ma_exit, retrace_exit, sar_exit
from wangtrader.core.indicators import sar, sma

METHOD_ID = "q3-03"


def _wait_bars(df: pd.DataFrame, i: int, p) -> int:
    """補進場有效根數：max_wait_minutes 為 None 時用 max_wait 根；否則把分鐘換成根數——以第 i 根（含）
    以前、同交易日相鄰K線的最小時間差當作K線週期（只用已發生的K線，不寫死週期）；time 欄不是時間戳
    或找不到相鄰K線時退回 max_wait 根。"""
    minutes, fallback = p.max_wait_minutes, p.max_wait
    if minutes is None:
        return fallback
    t, s = df["time"], df["session"]
    step = None
    k = i
    while k > 0 and k > i - 20:
        if s.iat[k] == s.iat[k - 1]:
            try:
                d = (t.iat[k] - t.iat[k - 1]).total_seconds() / 60.0
            except (TypeError, AttributeError):
                return fallback
            if d > 0:
                step = d if step is None else min(step, d)
        k -= 1
    if step is None:
        return fallback
    return max(1, int(minutes / step + 1e-9))


@dataclass
class Params:
    stop_points: float = 20.0  # 單筆最大風險（p.70）
    stop_tick: float = 1.0  # 母K極端點穿越此點數即停損（p.23「穿越 1 個跳動單位」）
    far_entry_mode: str = "pullback"  # 距離 > stop_points 時："pullback" | "direct" | "ignore"（p.70, 73）
    max_wait: int = 10  # 補進場等待根數（書中未給明確數字，沿用第一章慣例）
    max_wait_minutes: float | None = None  # 補進場有效分鐘數；None＝用 max_wait 根數（預設）。原文未寫時間，見規格文件 §12
    giveup_distance: float = 40.0  # F6：距母K極端點 ≥ 此值原則上放生不操作（p.73）
    extreme_range: float = 30.0  # p.68-69
    extreme_from_prev_close: float = 40.0  # p.68-69
    mirror_low_bound: bool = True  # 推論：底母子鏡像「訊號K最低點不低於母K最低點」（書中僅空方 C4 有明文）
    retrace_to_entry: bool = True  # 折返平倉（p.72-73），恆常啟用
    retrace_trigger: float = 1.0  # 折返平倉的「曾真正獲利」門檻（書中未給明確數字，示範獲利16點）
    exit_mode: str = "none"  # 推論；書中未提供本訊號另外的移動停利規則
    profit_target: float = 20.0
    ma_period: int = 10


class MotherChild(Strategy):
    method_id = METHOD_ID

    def __init__(self, **kw) -> None:
        self.p = Params(**kw)

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["sess_close_max"] = df.groupby("session")["close"].cummax()
        df["sess_close_min"] = df.groupby("session")["close"].cummin()
        df["ma"] = sma(df["close"], self.p.ma_period)
        s = sar(df)
        df["sar"], df["sar_trend"] = s["sar"], s["trend"]
        return df

    @staticmethod
    def _is_mother_top(df: pd.DataFrame, idx: int) -> bool:
        return bool(df.at[idx, "high"] == df.at[idx, "sess_high"] and df.at[idx, "close"] == df.at[idx, "sess_close_max"])

    @staticmethod
    def _is_mother_bottom(df: pd.DataFrame, idx: int) -> bool:
        return bool(df.at[idx, "low"] == df.at[idx, "sess_low"] and df.at[idx, "close"] == df.at[idx, "sess_close_min"])

    @staticmethod
    def _child_ok(m: pd.Series, c: pd.Series) -> bool:
        """子K實體落在母K實體內（懷孕），且高低點嚴格夾在母K高低點內（不可相等）。"""
        m_hi, m_lo = max(m["open"], m["close"]), min(m["open"], m["close"])
        c_hi, c_lo = max(c["open"], c["close"]), min(c["open"], c["close"])
        pure_body = m["high"] == m_hi and m["low"] == m_lo  # 母K無上下影線
        body_ok = (c_hi < m_hi and c_lo > m_lo) if pure_body else (c_hi <= m_hi and c_lo >= m_lo)
        range_ok = c["high"] < m["high"] and c["low"] > m["low"]
        return bool(body_ok and range_ok)

    def detect(self, df: pd.DataFrame, i: int) -> tuple[Side, float] | None:
        """第 i 根（訊號K）收盤時是否成立訊號，回傳 (方向, 母K極端價)。"""
        if i < 2:
            return None
        m, c, s = df.iloc[i - 2], df.iloc[i - 1], df.iloc[i]
        if not (m["session"] == c["session"] == s["session"]):
            return None
        if m["close"] > m["open"] and self._is_mother_top(df, i - 2) and self._child_ok(m, c):
            if s["close"] < s["open"] and s["high"] <= m["high"] and s["close"] <= m["open"] and s["close"] < c["low"]:
                return Side.SHORT, float(m["high"])
        if m["close"] < m["open"] and self._is_mother_bottom(df, i - 2) and self._child_ok(m, c):
            low_ok = (s["low"] >= m["low"]) if self.p.mirror_low_bound else True
            if s["close"] > s["open"] and low_ok and s["close"] >= m["open"] and s["close"] > c["high"]:
                return Side.LONG, float(m["low"])
        return None

    def _stop(self, side: Side, entry: float, ext: float) -> float:
        """停損＝母K極端點外 stop_tick，但距進場價最多 stop_points（p.70）。"""
        p = self.p
        if side == Side.LONG:
            return max(ext - p.stop_tick, entry - p.stop_points)
        return min(ext + p.stop_tick, entry + p.stop_points)

    def on_bar(self, ctx: Context):
        p, df, i = self.p, ctx.df, ctx.i
        if ctx.pos is not None:
            if p.retrace_to_entry:  # 折返平倉（p.72-73）：獲利曾為正、其後折返回進場價 → 撤單平倉
                ex = retrace_exit(ctx, p.retrace_trigger, 0.0)
                if ex is not None:
                    return [ex]
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

        # F5：極端位置
        if not is_extreme_position(df, i, p.extreme_range, p.extreme_from_prev_close):
            return None

        b = df.iloc[i]
        name = "頂母子" if side == Side.SHORT else "底母子"
        close = float(b["close"])
        dist = abs(close - ext)
        # F6：距母K極端點達 giveup_distance（40點）以上，原則上放生不操作（p.73）
        if dist >= p.giveup_distance:
            return None
        if dist <= p.stop_points:
            return [Order.enter(side, stop=self._stop(side, close, ext), reason=name, extreme=ext)]
        if p.far_entry_mode == "direct":
            return [Order.enter(side, stop=self._stop(side, close, ext), reason=name + "(直接進場)", extreme=ext)]
        if p.far_entry_mode == "pullback":
            limit = ext + p.stop_points * int(side)
            return [Order.enter_limit(side, limit=limit, expire=_wait_bars(df, i, p), stop=self._stop(side, limit, ext),
                                      reason=name + "(補進場)", extreme=ext)]
        return None  # far_entry_mode == "ignore"
