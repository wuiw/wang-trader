"""q3-02 底V字買訊／頂倒V空訊（《期貨奇績3》第二章，p.49–61）。

規格文件：methods/期貨奇績3/q3-02-V字轉折.md

訊號（p.49–50）：由兩根同向K線＋一根反向K線組成。
  底V字（多）：兩根下跌黑K，第二根黑K須是當下盤中「唯一」最低K線
    （最低點最低且收盤最低同時成立）；其後紅K最低點須高於該黑K最低點，
    且收盤突破其最高點（過一高）。
  頂倒V（空）：兩根上漲紅K，第二根紅K須是當下盤中「唯一」最高K線；
    其後黑K最高點須低於該紅K最高點，且收盤跌破其最低點（破一低）。
進場（p.50–51, 54, 57）：訊號K收盤時，距極端點（第二根同向K的高/低點）≤ stop_points
  → 立刻進場；距離較大 → far_entry_mode："pullback" 補進場等待拉回（限價，max_wait 根內未成交
  即失效）、"direct" 直接進場但停損固定 stop_points、"ignore" 忽略（p.50 三種皆可）。
  反向K本身為超大K線（實體 ≥ large_bar_threshold）時，簡化為直接以其收盤 ± stop_points
  設停損並立刻進場（p.54「不必將停損位置設在極端的 B 頂點」）。
停損（p.50, 54）：「以最低黑K線低點為停損」＝極端點（穿越 stop_tick 即出場）；
  進場價距極端點 ≤ stop_points 所以風險 ≤ stop_points；直接進場而距離較大時停損改為
  進場價 ± stop_points（p.50「直接進場，但停損點設在 20 點不變」）。
過濾：
  F1 對立訊號不可侵入前一（本模組自身）訊號K線收盤：空訊收盤 ≤ 先前買訊收盤（買訊收盤 ≥ 先前
     空訊收盤）→ 忽略（p.56：D 空訊收盤低於 B 買訊收盤 → 忽略 D；F 收盤未與 B 重疊 → 成立）。
     持倉中出現未侵入的對立訊號 → 平倉反手（p.56「F…即為訊號」）。
  F2 極端頂/底點須唯一：與其他K線同高/同低則訊號不成立（p.60，屬訊號定義本身）
  F3 反向K線須為真正上漲/下跌K線，僅創新高/新低不算（p.55，屬訊號定義本身）
  F4 必須在極端位置：盤中震幅 ≥ extreme_range，或距平盤 ≥ extreme_from_prev_close（p.49, 57）
  F5 同方向已停損過一次 → 本交易日同方向訊號不再做（p.60）
反手（p.59–60，reversal_enabled，預設關閉）：訊號被停損後，K線收盤確認跌破/突破訊號極端點
  時反手；反手單再被停損＝當日連二輸，本交易日停止操作（p.60）。書中提醒台指期不建議使用反手，
  故預設關閉。
出場：exit_mode = "ladder" | "ma" | "sar" | "none"（預設 none）。書中本章未證實可套用
  第一章的出場工具，此為推論，未經原文證實（p.73）。

週期：不限。所有門檻以點數／根數表示。
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from wangtrader.core import Context, Order, Side, Strategy
from wangtrader.core.bars import is_extreme_position
from wangtrader.core.exits import ladder_exit, ma_exit, sar_exit
from wangtrader.core.indicators import sar, sma

METHOD_ID = "q3-02"


@dataclass
class Params:
    stop_points: float = 20.0  # 單筆最大風險（p.50）
    stop_tick: float = 1.0  # 極端點穿越此點數即停損（p.23「穿越 1 個跳動單位」）
    max_wait: int = 10  # 補進場等待根數；書未載明具體根數（推論，比照 q3-01 預設）
    far_entry_mode: str = "pullback"  # 距離 > stop_points 時："pullback" | "direct" | "ignore"（p.50）
    large_bar_threshold: float | None = 30.0  # p.54，反向K線實體 ≥ 此值時簡化停損直接進場
    extreme_range: float = 30.0  # p.49, 57
    extreme_from_prev_close: float = 40.0  # p.49, 57
    opposite_signal_no_invade: bool = True  # F1，p.56
    same_side_stop_once: bool = True  # F5，p.60
    reversal_enabled: bool = False  # p.59-60；書中不建議台指使用，預設關閉
    exit_mode: str = "none"  # 推論；書中未證實可套用第一章出場法，預設關閉
    profit_target: float = 20.0
    ma_period: int = 10


class VReversal(Strategy):
    method_id = METHOD_ID

    def __init__(self, **kw) -> None:
        self.p = Params(**kw)
        self._stopped_sides: dict[int, set[Side]] = {}
        self._last_signal: dict[int, tuple[Side, float]] = {}  # session → (方向, 訊號K收盤)
        self._rev_watch: dict[int, tuple[Side, float]] = {}  # session → (被停損的方向, 極端點)
        self._halted: set[int] = set()  # 當日連二輸，停止操作（p.60）

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["sess_close_max"] = df.groupby("session")["close"].cummax()
        df["sess_close_min"] = df.groupby("session")["close"].cummin()
        df["ma"] = sma(df["close"], self.p.ma_period)
        s = sar(df)
        df["sar"], df["sar_trend"] = s["sar"], s["trend"]
        return df

    @staticmethod
    def _is_unique_extreme(df: pd.DataFrame, sess: int, idx: int, kind: str) -> bool:
        """idx 這根K線到本身為止，本交易日的 high(peak)/low(trough) 是否唯一（無同高/同低）。"""
        col = "high" if kind == "peak" else "low"
        mask = (df["session"] == sess) & (df.index <= idx)
        val = df.at[idx, col]
        return int((df.loc[mask, col] == val).sum()) == 1

    def detect(self, df: pd.DataFrame, i: int) -> tuple[Side, float] | None:
        """第 i 根（反向K）收盤時是否成立訊號，回傳 (方向, 第二根同向K的極端價)。"""
        if i < 2:
            return None
        a1, a2, b = df.iloc[i - 2], df.iloc[i - 1], df.iloc[i]
        if not (a1["session"] == a2["session"] == b["session"]):
            return None
        sess = int(a2["session"])
        # 底V字：兩根下跌黑K + 一根上漲紅K
        if a1["close"] < a1["open"] and a2["close"] < a2["open"]:
            if (
                a2["low"] == df.at[i - 1, "sess_low"]
                and a2["close"] == df.at[i - 1, "sess_close_min"]
                and self._is_unique_extreme(df, sess, i - 1, "trough")
            ):
                if b["close"] > b["open"] and b["low"] > a2["low"] and b["close"] > a2["high"]:
                    return Side.LONG, float(a2["low"])
        # 頂倒V：兩根上漲紅K + 一根下跌黑K
        if a1["close"] > a1["open"] and a2["close"] > a2["open"]:
            if (
                a2["high"] == df.at[i - 1, "sess_high"]
                and a2["close"] == df.at[i - 1, "sess_close_max"]
                and self._is_unique_extreme(df, sess, i - 1, "peak")
            ):
                if b["close"] < b["open"] and b["high"] < a2["high"] and b["close"] < a2["low"]:
                    return Side.SHORT, float(a2["high"])
        return None

    def _stop(self, side: Side, entry: float, ext: float) -> float:
        """停損＝極端點外 stop_tick，但距進場價最多 stop_points（p.50, 54）。"""
        p = self.p
        if side == Side.LONG:
            return max(ext - p.stop_tick, entry - p.stop_points)
        return min(ext + p.stop_tick, entry + p.stop_points)

    def _signal_order(self, ctx: Context) -> Order | None:
        """偵測訊號並套用 F1、F4、F5，回傳進場單（不更動狀態）。"""
        p, df, i = self.p, ctx.df, ctx.i
        hit = self.detect(df, i)
        if hit is None:
            return None
        side, ext = hit
        sess = int(df.at[i, "session"])
        b = df.iloc[i]
        close = float(b["close"])

        # F1：對立訊號不可侵入前一訊號K線收盤（p.56）
        if p.opposite_signal_no_invade:
            last = self._last_signal.get(sess)
            if last is not None and last[0] != side:
                if (side == Side.SHORT and close <= last[1]) or (side == Side.LONG and close >= last[1]):
                    return None
        # F5：同方向已停損過一次
        if p.same_side_stop_once and side in self._stopped_sides.get(sess, set()):
            return None
        # F4：極端位置
        if not is_extreme_position(df, i, p.extreme_range, p.extreme_from_prev_close):
            return None

        name = "底V字" if side == Side.LONG else "頂倒V"
        body_pts = abs(close - b["open"])
        if p.large_bar_threshold is not None and body_pts >= p.large_bar_threshold:
            stop = close - p.stop_points if side == Side.LONG else close + p.stop_points
            return Order.enter(side, stop=stop, reason=name + "(大K簡化)", extreme=ext, vsignal=True)
        dist = abs(close - ext)
        if dist <= p.stop_points:
            return Order.enter(side, stop=self._stop(side, close, ext), reason=name, extreme=ext, vsignal=True)
        if p.far_entry_mode == "direct":
            return Order.enter(side, stop=self._stop(side, close, ext), reason=name + "(直接進場)",
                               extreme=ext, vsignal=True)
        if p.far_entry_mode == "pullback":
            limit = ext + p.stop_points * int(side)
            return Order.enter_limit(side, limit=limit, expire=p.max_wait, stop=self._stop(side, limit, ext),
                                     reason=name + "(補進場)", extreme=ext, vsignal=True)
        return None  # far_entry_mode == "ignore"

    def _reversal_order(self, ctx: Context) -> Order | None:
        """停損後，收盤確認跌破/突破訊號極端點 → 反手（p.59）。"""
        p, df, i = self.p, ctx.df, ctx.i
        sess = int(df.at[i, "session"])
        watch = self._rev_watch.get(sess)
        if watch is None or ctx.pos is not None:
            return None
        side, ext = watch
        close = float(df.at[i, "close"])
        if side == Side.LONG and close < ext:
            self._rev_watch.pop(sess, None)
            return Order.enter(Side.SHORT, stop=close + p.stop_points, reason="頂倒V(破低反手)", extreme=ext, reversal=True)
        if side == Side.SHORT and close > ext:
            self._rev_watch.pop(sess, None)
            return Order.enter(Side.LONG, stop=close - p.stop_points, reason="底V字(破高反手)", extreme=ext, reversal=True)
        return None

    def on_bar(self, ctx: Context):
        p, df, i = self.p, ctx.df, ctx.i
        sess = int(df.at[i, "session"])

        if ctx.stopped is not None:
            t = ctx.stopped
            if t.meta.get("vsignal"):
                self._stopped_sides.setdefault(sess, set()).add(t.side)
                if p.reversal_enabled and t.meta.get("extreme") is not None:
                    self._rev_watch[sess] = (t.side, float(t.meta["extreme"]))
            if t.meta.get("reversal"):  # 反手單再停損 → 當日連二輸，停止操作（p.60）
                self._halted.add(sess)

        order: Order | None = None
        if sess not in self._halted:
            order = self._reversal_order(ctx) if p.reversal_enabled else None
            if order is None:
                order = self._signal_order(ctx)

        if order is not None:
            self._rev_watch.pop(sess, None)  # 已有新單，不再等待停損後反手
        if ctx.pos is not None:
            if order is not None and order.side != ctx.pos.side:  # 未侵入的對立訊號 → 平倉反手（p.56）
                if order.meta.get("vsignal"):
                    self._last_signal[sess] = (order.side, float(df.at[i, "close"]))
                return [order]
            ex = {
                "ladder": lambda: ladder_exit(ctx, p.profit_target),
                "ma": lambda: ma_exit(ctx, "ma", p.profit_target),
                "sar": lambda: sar_exit(ctx, p.profit_target),
                "none": lambda: None,
            }[p.exit_mode]()
            return [ex] if ex else None

        if order is None:
            return None
        if order.meta.get("vsignal"):
            self._last_signal[sess] = (order.side, float(df.at[i, "close"]))
        return [order]
