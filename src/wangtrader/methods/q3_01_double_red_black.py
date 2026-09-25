"""q3-01 頂雙黑／底雙紅（《期貨奇績3》第一章，p.14–41）。

規格文件：methods/期貨奇績3/q3-01-頂底雙紅黑.md

訊號（p.15, 17）：
  頂雙黑（空）：前一根是當下盤中最高點的黑K，本根也是黑K且收盤跌破前一根最低點。
  底雙紅（多）：前一根是當下盤中最低點的紅K，本根也是紅K且收盤突破前一根最高點。
  C3 極端點須獨一無二（p.17）：頂雙黑第一根黑K的最高點、底雙紅第一根紅K的最低點，
    須為本交易日截至訊號K為止唯一一根達到該高（低）點的K線；若前面另有K線同高（同低，共頂／共底），
    訊號不成立（圖1-4：C、D 同低，D 屬「共底紅K線」非底雙紅）。
進場（p.15, 18–20）：極端點到收盤距離 ≤ stop_points → 收盤立刻進場；
  距離較大 → far_entry_mode："pullback" 掛限價等拉回到「極端點 ± stop_points」，
  max_wait 根內未成交即失效（預設，p.19–20）；"direct" 直接進場但停損固定 stop_points
  （p.19「超過 20 點不多…立刻進場差別不大」、p.22 特殊放大行情）；"ignore" 不做。
停損（p.18–19, 21, 23）：設在極端點（頂雙黑＝第一根黑K高點；p.21「跌破 A 低點，造成停損」、
  p.23「停損設在 3944 點…穿越 1 個跳動單位即停損」），穿越 stop_tick 即出場。
  進場價距極端點 ≤ stop_points 才立刻進場，所以單筆風險 ≤ stop_points；距離較大而直接進場時
  停損改設「進場價 ± stop_points」（p.19, 22「但停損維持 20 點」）。
過濾：
  F1 幅度超過 stop_points 且訊號K收盤成為當下盤中新的反向極端（兩根就從最高打到最低）→ 忽略（p.18–19）
  F2 同方向已停損過 → 本交易日同方向訊號不再做（p.21）
  F3 必須在極端位置：盤中震幅 ≥ 30 或距平盤 ≥ 40（p.36）
  F4 兩根合計點數 < min_pattern_points → 忽略（p.40；書中用於 5 分K以上，預設關閉）
  F5 no_entry_after：時間晚於此不做（p.37，書中為 12:30；預設關閉）
  F6 對立訊號不可侵入前一訊號K收盤：空訊收盤 ≤ 先前買訊收盤（買訊收盤 ≥ 先前空訊收盤）→ 忽略
     （p.56，第二章以「底雙紅之後的頂雙黑」為例）。未侵入的對立訊號在持倉中出現 → 平倉反手（p.56）。
出場：exit_mode = "retracement" | "ladder" | "ma" | "sar" | "none"，達 profit_target 後啟動（p.28–35）。
  "retracement"（折返點數停利，p.28–30，新增第4種）：達獲利目標後，若某根K線同時符合「自進場後
  最高(低)K線的極端點」與「自進場後最高(低)K線的收盤」雙條件，即以其極端點扣（多單）／加（空單）
  retrace_step 點設為新停利位置；只符合其一則不移動；收盤觸及即出場。

週期：不限。所有門檻以點數／根數表示。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time

import pandas as pd

from wangtrader.core import Context, Order, Side, Strategy
from wangtrader.core.bars import is_extreme_position
from wangtrader.core.exits import ladder_exit, ma_exit, sar_exit
from wangtrader.core.indicators import sar, sma

METHOD_ID = "q3-01"


@dataclass
class Params:
    stop_points: float = 20.0  # 單筆最大風險（p.15, 18–19）
    stop_tick: float = 1.0  # 極端點穿越此點數即停損（p.23「穿越 1 個跳動單位」）
    max_wait: int = 10  # 補進場等待根數（p.20）
    far_entry_mode: str = "pullback"  # 距離 > stop_points 時："pullback" | "direct" | "ignore"（p.19–20, 22）
    extreme_range: float = 30.0
    extreme_from_prev_close: float = 40.0
    min_pattern_points: float = 0.0  # F4，書中 5 分K以上建議 10
    no_entry_after: time | None = None  # F5，書中 12:30
    opposite_signal_no_invade: bool = True  # F6，p.56
    exit_mode: str = "ladder"
    profit_target: float = 20.0
    retrace_step: float = 20.0  # 折返點數停利的扣抵點數（p.28-30，exit_mode="retracement"）
    ma_period: int = 10


class DoubleRedBlack(Strategy):
    method_id = METHOD_ID

    def __init__(self, **kw) -> None:
        self.p = Params(**kw)
        self._stopped_sides: dict[int, set[Side]] = {}
        self._last_signal: dict[int, tuple[Side, float]] = {}  # session → (方向, 訊號K收盤)

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["ma"] = sma(df["close"], self.p.ma_period)
        s = sar(df)
        df["sar"], df["sar_trend"] = s["sar"], s["trend"]
        return df

    @staticmethod
    def _is_unique_extreme(df: pd.DataFrame, i: int, kind: str) -> bool:
        """a（第 i-1 根）的極端點到第 i 根為止，是否本交易日唯一（無同高/同低，p.17 C3）。"""
        a = df.iloc[i - 1]
        sess_start = i - 1 - int(a["bar_no"])
        window = df.iloc[sess_start : i + 1]
        col = "high" if kind == "peak" else "low"
        return int((window[col] == a[col]).sum()) == 1

    def detect(self, df: pd.DataFrame, i: int) -> tuple[Side, float] | None:
        """第 i 根收盤時是否成立訊號，回傳 (方向, 極端價)。"""
        if i < 1:
            return None
        a, b = df.iloc[i - 1], df.iloc[i]
        if a["session"] != b["session"]:
            return None
        # 頂雙黑：a 為當下（到 a 為止）盤中最高的黑K
        if a["close"] < a["open"] and a["high"] >= a["sess_high"] and b["close"] < b["open"] and b["close"] < a["low"]:
            if b["high"] <= a["high"]:  # b 沒有再創新高，a 仍是最高點
                if self._is_unique_extreme(df, i, "peak"):  # C3：極端點須獨一無二（p.17）
                    return Side.SHORT, float(a["high"])
        if a["close"] > a["open"] and a["low"] <= a["sess_low"] and b["close"] > b["open"] and b["close"] > a["high"]:
            if b["low"] >= a["low"]:
                if self._is_unique_extreme(df, i, "trough"):
                    return Side.LONG, float(a["low"])
        return None

    def _stop(self, side: Side, entry: float, ext: float) -> float:
        """停損＝極端點外 stop_tick，但距進場價最多 stop_points（p.18–19, 22, 23）。"""
        p = self.p
        if side == Side.LONG:
            return max(ext - p.stop_tick, entry - p.stop_points)
        return min(ext + p.stop_tick, entry + p.stop_points)

    def _signal_order(self, ctx: Context) -> Order | None:
        """偵測訊號並套用 F1–F6，回傳進場單（不更動狀態）。"""
        p, df, i = self.p, ctx.df, ctx.i
        hit = self.detect(df, i)
        if hit is None:
            return None
        side, ext = hit
        sess = int(df.at[i, "session"])
        b, a = df.iloc[i], df.iloc[i - 1]
        close = float(b["close"])
        dist = abs(close - ext)
        # F1：幅度過大且訊號K收盤變成當下盤中新的反向極端（p.18「幅度超過 20 點以外，最不合理是 D 點變成當下最低點」）
        if dist > p.stop_points:
            if side == Side.SHORT and close <= df.at[i - 1, "sess_low"]:
                return None
            if side == Side.LONG and close >= df.at[i - 1, "sess_high"]:
                return None
        # F2
        if side in self._stopped_sides.get(sess, set()):
            return None
        # F3
        if not is_extreme_position(df, i, p.extreme_range, p.extreme_from_prev_close):
            return None
        # F4
        if abs(close - a["open"]) < p.min_pattern_points:
            return None
        # F5
        if p.no_entry_after is not None and hasattr(b["time"], "time") and b["time"].time() > p.no_entry_after:
            return None
        # F6：對立訊號不可侵入前一訊號K收盤（p.56：D 空訊收盤低於 B 買訊收盤 → 忽略 D）
        if p.opposite_signal_no_invade:
            last = self._last_signal.get(sess)
            if last is not None and last[0] != side:
                if (side == Side.SHORT and close <= last[1]) or (side == Side.LONG and close >= last[1]):
                    return None
        name = "頂雙黑" if side == Side.SHORT else "底雙紅"
        if dist <= p.stop_points:
            return Order.enter(side, stop=self._stop(side, close, ext), reason=name, extreme=ext)
        if p.far_entry_mode == "direct":
            return Order.enter(side, stop=self._stop(side, close, ext), reason=name + "(直接進場)", extreme=ext)
        if p.far_entry_mode == "pullback":
            # 等價格拉回到距極端點 stop_points 以內（多：ext+20；空：ext-20），停損仍在極端點
            limit = ext + p.stop_points * int(side)
            return Order.enter_limit(side, limit=limit, expire=p.max_wait, stop=self._stop(side, limit, ext),
                                     reason=name + "(補進場)", extreme=ext)
        return None  # far_entry_mode == "ignore"

    def _retracement_exit(self, ctx: Context) -> Order | None:
        """折返點數停利（p.28-30）：達獲利目標後，若某根K線同時符合「自進場後最高(低)K線的
        極端點」與「最高(低)K線的收盤」雙條件，以其極端點扣（多）/加（空）retrace_step 設為新停利位置；
        只符合其中一項不移動；收盤觸及該停利位置即出場。"""
        p, pos = self.p, ctx.pos
        if pos is None or ctx.i <= pos.entry_i or pos.max_profit() < p.profit_target:
            return None
        b = ctx.bar()
        long = pos.side == Side.LONG
        close_key = "retr_close_ext"
        prev_close_ext = pos.meta.get(close_key, pos.entry_price)
        close_is_new = (b["close"] > prev_close_ext) if long else (b["close"] < prev_close_ext)
        if close_is_new:
            pos.meta[close_key] = float(b["close"])
        high_is_new = (b["high"] >= pos.best) if long else (b["low"] <= pos.best)
        if close_is_new and high_is_new:  # 雙條件同時成立才移動停利位置（p.28）
            lvl = float(b["high"] - p.retrace_step) if long else float(b["low"] + p.retrace_step)
            pos.meta["retr_level"] = lvl
        lvl = pos.meta.get("retr_level")
        if lvl is None:
            return None
        if (b["close"] <= lvl) if long else (b["close"] >= lvl):
            return Order.exit("折返停利")
        return None

    def on_bar(self, ctx: Context):
        p, df, i = self.p, ctx.df, ctx.i
        sess = int(df.at[i, "session"])
        if ctx.stopped is not None:
            self._stopped_sides.setdefault(sess, set()).add(ctx.stopped.side)
        order = self._signal_order(ctx)
        if ctx.pos is not None:
            if order is not None and order.side != ctx.pos.side:  # 未侵入的對立訊號 → 平倉反手（p.56）
                self._last_signal[sess] = (order.side, float(df.at[i, "close"]))
                return [order]
            ex = {"retracement": lambda: self._retracement_exit(ctx),
                  "ladder": lambda: ladder_exit(ctx, p.profit_target),
                  "ma": lambda: ma_exit(ctx, "ma", p.profit_target),
                  "sar": lambda: sar_exit(ctx, p.profit_target),
                  "none": lambda: None}[p.exit_mode]()
            return [ex] if ex else None
        if order is None:
            return None
        self._last_signal[sess] = (order.side, float(df.at[i, "close"]))
        return [order]
