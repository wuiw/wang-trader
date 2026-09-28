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
進場（p.84, 87）：訊號K（B）收盤確認後，若距A的極端點 ≤ stop_points 立即以收盤價進場（方向與B
  同向，即與A相反）；距離較大（>20點，圖4-4）則等拉回/反彈至距離縮小到 stop_points 以內再補進場
  （限價，max_wait 根（或 max_wait_minutes 分鐘）內未成交即失效）。
停損（p.87, 90-91）：設在 A 的極端點（穿越 stop_tick 即出場），但距進場價最多 stop_points
  （預設 20 點）。設 stop_points=None 則不設停損。
過濾：
  F1 漲跌點差距 > tolerance_points → 即使壘頂/壘底外觀相同，仍不成立（屬訊號定義本身，p.84）
  F2 母K未同時符合最高/最低點與收盤最高/最低 → 不是合法母K線（屬訊號定義本身，p.93）
  F3 同一天同一類型訊號第一次已停損 → 第二次出現忽略不進場（p.92）
  F4 必須在極端位置：盤中震幅 ≥ extreme_range 或距平盤 ≥ extreme_from_prev_close（p.84）
出場（p.90-91，更正舊版「書中未提供本訊號出場規則」的說法）：
  折返平倉：獲利曾達 retrace_trigger（15點）後又折返回進場價（含）以下 → 立刻撤單平倉（沿用
  core.exits.retrace_exit，trigger=15、keep=0）。
反手（p.91）：若持倉期間從未達到 retrace_trigger 的獲利門檻，隨後觸及停損，且停損當根K線
  「收盤」確認穿越A的極端點（原空單：收盤突破A高點；原多單：收盤跌破A低點），則停損出場後
  立即反手，並以反手收盤價為基準設 stop_points 點停損（reversal_enabled 開關，預設開啟，
  book 未提示台指不宜使用，故不像 q3-02 預設關閉）。
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

METHOD_ID = "q3-04"


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
    tolerance_points: float = 1.0  # p.84, 96
    stop_points: float | None = 20.0  # 單筆最大風險（推論：全書一貫 20 點）；None = 不設停損
    stop_tick: float = 1.0  # A 極端點穿越此點數即停損（p.23「穿越 1 個跳動單位」）
    max_wait: int = 10  # 補進場等待根數（書中未給明確數字，沿用第一章慣例，p.87）
    max_wait_minutes: float | None = None  # 補進場有效分鐘數；None＝用 max_wait 根數（預設）。原文未寫時間，見規格文件 §12
    require_extreme: bool = True  # 極端位置前提（p.84「定義和前面所有極端位置訊號一樣」）
    extreme_range: float = 30.0  # p.49, 57（第二章定義）
    extreme_from_prev_close: float = 40.0
    same_side_stop_once: bool = True  # F3，p.92
    retrace_trigger: float = 15.0  # 折返平倉／反手資格門檻（p.90-91）
    reversal_enabled: bool = True  # p.91；書中未提示台指不宜使用，預設開啟
    reversal_stop_points: float = 20.0  # 反手單停損點數，只在 stop_points=None 時使用（原寫死 20，推論：全書一貫 20 點）
    exit_mode: str = "none"  # 推論；書中未提供本訊號另外的移動停利規則
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

    def _reversal_stop(self) -> float:
        """反手單停損點數：stop_points；stop_points=None（不設停損）時改用 reversal_stop_points。"""
        return self.p.stop_points or self.p.reversal_stop_points

    def _stop(self, side: Side, entry: float, ext: float) -> float | None:
        """停損＝A 極端點外 stop_tick，但距進場價最多 stop_points（p.87, 90-91）。"""
        p = self.p
        if p.stop_points is None:
            return None
        if side == Side.LONG:
            return max(ext - p.stop_tick, entry - p.stop_points)
        return min(ext + p.stop_tick, entry + p.stop_points)

    def on_bar(self, ctx: Context):
        p, df, i = self.p, ctx.df, ctx.i
        sess = int(df.at[i, "session"])

        if ctx.pos is not None:
            # 追蹤是否曾達成折返門檻的獲利（供反手資格判斷，p.90-91）
            if ctx.pos.max_profit() >= p.retrace_trigger:
                ctx.pos.meta["reached_target"] = True
            ex = retrace_exit(ctx, p.retrace_trigger, 0.0)  # 折返平倉（p.90）
            if ex is not None:
                return [ex]
            ex = {
                "ladder": lambda: ladder_exit(ctx, p.profit_target),
                "ma": lambda: ma_exit(ctx, "ma", p.profit_target),
                "sar": lambda: sar_exit(ctx, p.profit_target),
                "none": lambda: None,
            }[p.exit_mode]()
            return [ex] if ex else None

        order: Order | None = None

        # 停損後反手（p.91）：未達折返門檻獲利即觸停損，且停損K收盤確認穿越A的極端點
        if ctx.stopped is not None:
            t = ctx.stopped
            if t.meta.get("tft_signal"):
                self._stopped_sides.setdefault(sess, set()).add(t.side)
                if p.reversal_enabled and not t.meta.get("reached_target"):
                    lvl = t.meta.get("stop_level")
                    close = float(df.at[i, "close"])
                    if lvl is not None:
                        if t.side == Side.LONG and close < lvl:
                            order = Order.enter(Side.SHORT, stop=close + self._reversal_stop(),
                                                reason="以牙還牙(反手)", reversal=True)
                        elif t.side == Side.SHORT and close > lvl:
                            order = Order.enter(Side.LONG, stop=close - self._reversal_stop(),
                                                reason="以牙還牙(反手)", reversal=True)

        if order is None:
            hit = self.detect(df, i)
            if hit is not None:
                side, ext = hit
                # F3：同方向已停損過一次
                if not (p.same_side_stop_once and side in self._stopped_sides.get(sess, set())):
                    # 極端位置前提（p.84）
                    if not p.require_extreme or is_extreme_position(df, i, p.extreme_range, p.extreme_from_prev_close):
                        b = df.iloc[i]
                        name = "以牙還牙空訊" if side == Side.SHORT else "以牙還牙買訊"
                        close = float(b["close"])
                        dist = abs(close - ext)
                        if p.stop_points is None or dist <= p.stop_points:  # 立刻進場（p.84）
                            stop = self._stop(side, close, ext)
                            order = Order.enter(side, stop=stop, reason=name, extreme=ext,
                                                stop_level=stop, tft_signal=True)
                        else:  # 距離 >20 點：等拉回至距A極端點 stop_points 內再補進場（p.87）
                            limit = ext + p.stop_points * int(side)
                            stop = self._stop(side, limit, ext)
                            order = Order.enter_limit(side, limit=limit, expire=_wait_bars(df, i, p), stop=stop,
                                                      reason=name + "(補進場)", extreme=ext,
                                                      stop_level=stop, tft_signal=True)

        return [order] if order is not None else None
