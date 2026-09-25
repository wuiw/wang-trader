"""q3-07 開盤戰法：跳高收黑空訊／跳低收紅買訊（《期貨奇績3》第七章，p.137–153）。

規格文件：methods/期貨奇績3/q3-07-開盤首根K線戰法.md

「開盤首根」以 `prepare()` 產生的 `bar_no == 0` 判斷（本交易日第一根），不假設任何特定週期。

訊號（p.138–139）：
  跳高收黑空訊：開盤價跳高，乖離平盤（昨收）≥40點；開盤首根K線收黑；上影線 ≤3點。
  跳低收紅買訊：鏡像。開盤價跳低，乖離平盤 ≥40點；開盤首根K線收紅；下影線 ≤3點。
進場（p.140-141）：訊號K（開盤首根）收盤確認後立即市價進場。
過濾：超大K線（p.150）：訊號K收盤到「同方向」極端點（空：高點；多：低點）距離已超過停損點數，
  以收盤價20點無法涵蓋，忽略本次訊號（書中未給明確數值門檻的替代拉回做法，故不實作，見§12待確認）。
停損（p.140-141, 144）：固定20點，以訊號K收盤價為基準。
出場 / 折返停利（p.145, 147）：獲利曾達15點後，若回落至（含）進場價（keep=0）即收盤出場，
  沿用 core.exits.retrace_exit；達此門檻後不得再反手（見下）。
停損後反手（p.145-147, 153）：同一根停損K線，若持倉期間未曾達15點獲利，且該停損K線收盤
  突破（原空單）／跌破（原多單）訊號K的反方向極端點，則停損出場後立即反手，同樣以（反手）
  收盤價為基準設20點停損。
時間停滯出場（p.148，新增）：進場後若既未觸及20點停損、也未達15點折返停利，經過約
  stall_minutes 分鐘仍無明確輸贏，撤單離場觀望（書中「約一小時」，以K線時間戳計算，不綁週期）。

週期：不限；「開盤首根」用 bar_no==0 判斷。所有門檻以點數表示。
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from wangtrader.core import Context, Order, Side, Strategy
from wangtrader.core.exits import retrace_exit

METHOD_ID = "q3-07"



def _elapsed_minutes(df: pd.DataFrame, entry_i: int, i: int) -> float:
    """進場K線到第 i 根K線經過的分鐘數（用 prepare() 保留的 time 欄；非時間戳時退回根數）。"""
    t0, t1 = df.at[entry_i, "time"], df.at[i, "time"]
    try:
        return (t1 - t0).total_seconds() / 60.0
    except (TypeError, AttributeError):
        return float(i - entry_i)

@dataclass
class Params:
    gap_threshold: float = 40.0  # 開盤乖離平盤門檻（p.138-139）
    shadow_max: float = 3.0  # 訊號K反方向影線上限（p.138-139）
    stop_points: float = 20.0  # 停損點數，以訊號K收盤價為基準（p.140-141, 144）
    profit_trigger: float = 15.0  # 折返停利／反手資格門檻（p.145, 147）
    stall_minutes: float | None = 60.0  # 時間停滯出場：進場後約一小時（p.148），以 K 線時間戳計算，不綁週期；None 關閉


class OpeningBar(Strategy):
    method_id = METHOD_ID

    def detect(self, df: pd.DataFrame, i: int) -> Side | None:
        """判斷開盤首根（bar_no==0）是否成立訊號，回傳方向；非首根一律回傳 None。"""
        if df.at[i, "bar_no"] != 0:
            return None
        b = df.iloc[i]
        prev_close = b["prev_close"]
        if pd.isna(prev_close):
            return None
        gap = b["open"] - prev_close
        p = self.p
        if gap >= p.gap_threshold and b["close"] < b["open"]:  # 跳高收黑
            upper_shadow = b["high"] - max(b["open"], b["close"])
            if upper_shadow <= p.shadow_max and (b["high"] - b["close"]) <= p.stop_points:
                return Side.SHORT
            return None
        if gap <= -p.gap_threshold and b["close"] > b["open"]:  # 跳低收紅
            lower_shadow = min(b["open"], b["close"]) - b["low"]
            if lower_shadow <= p.shadow_max and (b["close"] - b["low"]) <= p.stop_points:
                return Side.LONG
            return None
        return None

    def __init__(self, **kw) -> None:
        self.p = Params(**kw)

    def _reached_profit(self, df: pd.DataFrame, side: Side, entry_i: int, entry_price: float, exit_i: int) -> bool:
        if exit_i <= entry_i + 1:
            return False
        seg = df.iloc[entry_i + 1:exit_i]
        if side == Side.LONG:
            return (seg["high"].max() - entry_price) >= self.p.profit_trigger
        return (entry_price - seg["low"].min()) >= self.p.profit_trigger

    def on_bar(self, ctx: Context):
        p, df, i = self.p, ctx.df, ctx.i
        b = df.iloc[i]
        result: list[Order] | None = None

        # 1. 停損後反手：同一根停損K線判斷
        if ctx.stopped is not None:
            t = ctx.stopped
            reached = self._reached_profit(df, t.side, t.entry_i, t.entry_price, t.exit_i)
            if not reached:
                sig_high, sig_low = t.meta.get("sig_high"), t.meta.get("sig_low")
                if t.side == Side.SHORT and sig_high is not None and b["close"] > sig_high:
                    result = [Order.enter(Side.LONG, stop=b["close"] - p.stop_points, reason="停損反手")]
                elif t.side == Side.LONG and sig_low is not None and b["close"] < sig_low:
                    result = [Order.enter(Side.SHORT, stop=b["close"] + p.stop_points, reason="停損反手")]

        # 2. 折返停利：獲利曾達 profit_trigger 後回落至進場價（含）即出場
        if result is None and ctx.pos is not None:
            ex = retrace_exit(ctx, p.profit_trigger, keep=0.0)
            if ex:
                result = [ex]

        # 2b. 時間停滯出場（p.148）：約 stall_minutes 分鐘仍無明確輸贏（未觸停損、未達折返停利）→ 撤單離場
        if result is None and ctx.pos is not None and p.stall_minutes is not None:
            if _elapsed_minutes(ctx.df, ctx.pos.entry_i, i) >= p.stall_minutes:
                result = [Order.exit("時間停滯出場")]

        # 3. 開盤首根訊號
        if result is None and ctx.pos is None:
            side = self.detect(df, i)
            if side is not None:
                if side == Side.SHORT:
                    stop = b["close"] + p.stop_points
                    reason = "跳高收黑"
                else:
                    stop = b["close"] - p.stop_points
                    reason = "跳低收紅"
                result = [Order.enter(side, stop=stop, reason=reason,
                                       sig_high=float(b["high"]), sig_low=float(b["low"]))]

        return result
