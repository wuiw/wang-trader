"""q3-06 連五黑遇首紅（買訊）／連五紅遇首黑（空訊）（《期貨奇績3》第六章，p.121–135）。

規格文件：methods/期貨奇績3/q3-06-連五黑遇首紅與連五紅遇首黑.md

訊號（p.121）：
  連五黑遇首紅（多）：連續5根（含）以上階梯狀下降黑K，跌幅（含C2b可回溯整段）超過40點，
    最後一根黑K為當下盤中最低點，且下影線 ≤5點或≤實體1/5；隔一根K線收紅、未再創新低，
    且未超過最後一根黑K最高點，即成立訊號，市價買進。
  連五紅遇首黑（空）：鏡像。連續5根以上階梯狀上升紅K，漲幅超過40點，最後一根紅K為當下盤中最高點，
    上影線 ≤5點或≤實體1/5；隔一根K線收黑、上影線未創新高，且收盤未跌破最後一根紅K最低點。
進場（p.121, 124, 126）：反色K線收盤確認後立即市價進場，書中未提及需等拉回。
停損（p.124, 126）：固定20點，以訊號K（反色K線）收盤價為基準；書中未提及反手機制。
出場：書中未明確訂出停利／移動停損規則（p.135待確認事項）；可選 stale_bars（逾時無獲利平倉，
  書中為建議語氣、非嚴格規則，p.135，預設關閉）。

過濾（§7）：
  F1 隔根反色K線創新低（多方情境，用「影線」即最低價判斷）／創新高（空方情境，用最高價判斷）
     → 不能作新進場訊號，只能作既有同方向部位的出場（平倉）訊號（p.121, 132, 134）。
  F2 隔根反色K線超過最後一根同色K的高/低點（過一高／破一低）→ 屬「V字轉折」訊號，非本訊號，
     不進場也不出場（p.121）。
  F3 最後一根同色K線的（潛在反轉方向）影線 >5點且 >實體1/5 → 不視為有效反轉訊號，尤其海期
     商品（p.128-129, 135）。
  F4 「下跌的黑K線」／「上漲的紅K線」：每根收盤須低於／高於前一根收盤（p.121；「上漲K線」的定義
     見 p.55「B 雖為紅K線，但不為上漲K線」＝收盤未高於前一根收盤；p.127「每一根紅K線都是上漲」），
     require_stepping 開關控制，預設開啟。
  F5 訊號發生時間距當日收盤不到1小時 → 一般忽略不操作（p.123）。「距收盤」須知道未來收盤時刻，
     屬 CODING_SPEC 第4點所稱「時鐘時間規則」，故做成可選參數 no_entry_after（收盤前1小時的絕對
     時刻），預設 None（關閉）；書中示範收盤13:30，1小時前即12:30。

週期：不限（書中以5分鐘K線示範，程式不假設週期）。所有門檻以點數／根數表示。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time

import pandas as pd

from wangtrader.core import Context, Order, Side, Strategy

METHOD_ID = "q3-06"


@dataclass
class Params:
    min_run: int = 5  # 連續同色K最少根數（p.121）
    min_points: float = 40.0  # 該段（或可回溯整段）幅度門檻（p.121, C2b見p.127）
    require_stepping: bool = True  # 每根須為下跌/上漲K線（收盤低於/高於前一根收盤，p.121, 55, 127）
    shadow_max_points: float = 5.0  # 最後一根同色K影線濾網：點數上限（p.128-129）
    shadow_max_ratio: float = 1.0 / 5  # 影線濾網：占實體比例上限（p.128-129）
    stop_points: float = 20.0  # 停損點數，以訊號K收盤價為基準（p.124, 126）
    stale_bars: int | None = None  # 可選：持倉逾N根仍無獲利即平倉（p.135，書中為建議、非嚴格規則，預設關閉）
    no_entry_after: time | None = None  # F5：距收盤不到1小時忽略（p.123）；時鐘時間規則，預設關閉


class FiveInARowReversal(Strategy):
    method_id = METHOD_ID

    def __init__(self, **kw) -> None:
        self.p = Params(**kw)
        self._runs: dict[int, dict] = {}

    # ---------- 連續同色K階梯狀態 ----------

    def _steps(self, df: pd.DataFrame, prev_idx: int, idx: int, color: str) -> bool:
        """下跌／上漲K線：收盤低於／高於前一根收盤（p.55, 127）。"""
        if color == "black":
            return df.at[idx, "close"] < df.at[prev_idx, "close"]
        return df.at[idx, "close"] > df.at[prev_idx, "close"]

    def _update_run(self, df: pd.DataFrame, i: int, st: dict) -> None:
        b = df.iloc[i]
        color = "black" if b["close"] < b["open"] else "red" if b["close"] > b["open"] else None
        if color is None:
            st["color"], st["bars"] = None, []
            return
        if st["color"] == color and st["bars"] and (not self.p.require_stepping
                                                      or self._steps(df, st["bars"][-1], i, color)):
            st["bars"].append(i)
        else:
            st["color"], st["bars"] = color, [i]

    def _shadow_ok(self, df: pd.DataFrame, idx: int, color: str) -> bool:
        b = df.iloc[idx]
        body = abs(b["close"] - b["open"])
        shadow = (min(b["open"], b["close"]) - b["low"]) if color == "black" else (b["high"] - max(b["open"], b["close"]))
        if shadow <= self.p.shadow_max_points:
            return True
        return body > 0 and shadow / body <= self.p.shadow_max_ratio

    def _span_start(self, df: pd.DataFrame, bars: list[int], color: str) -> int | None:
        n = self.p.min_run
        last = bars[-1]
        cand5 = bars[-n]
        if color == "black":
            span5 = df.at[cand5, "high"] - df.at[last, "low"]
        else:
            span5 = df.at[last, "high"] - df.at[cand5, "low"]
        if span5 >= self.p.min_points:
            return cand5
        start_all = bars[0]
        if color == "black":
            span_all = df.at[start_all, "high"] - df.at[last, "low"]
        else:
            span_all = df.at[last, "high"] - df.at[start_all, "low"]
        if span_all >= self.p.min_points:
            return start_all
        return None

    def qualify(self, df: pd.DataFrame, st: dict) -> int | None:
        """判斷「前一狀態」的連續同色K是否已符合 C1-C3、C7；回傳採用的起點索引，否則 None。"""
        bars, color = st["bars"], st["color"]
        if color is None or len(bars) < self.p.min_run:
            return None
        last = bars[-1]
        if color == "black" and not (df.at[last, "low"] <= df.at[last, "sess_low"]):
            return None
        if color == "red" and not (df.at[last, "high"] >= df.at[last, "sess_high"]):
            return None
        start = self._span_start(df, bars, color)
        if start is None:
            return None
        if not self._shadow_ok(df, last, color):
            return None
        return start

    def on_bar(self, ctx: Context):
        p, df, i = self.p, ctx.df, ctx.i
        sess = int(df.at[i, "session"])
        st = self._runs.setdefault(sess, {"color": None, "bars": []})
        b = df.iloc[i]
        orders: list[Order] | None = None

        start = self.qualify(df, st)
        if start is not None:
            last = st["bars"][-1]
            color = st["color"]
            if color == "black" and b["close"] > b["open"]:  # 隔根收紅：連五黑遇首紅
                if b["low"] < df.at[last, "low"]:  # C4 失敗：影線創新低
                    if ctx.pos is not None and ctx.pos.side == Side.SHORT:
                        orders = [Order.exit("平倉(創新低)")]
                elif b["close"] > df.at[last, "high"]:  # C5 失敗：收盤過一高 → V字轉折，非本訊號（與空方對稱，p.121「反之」）
                    orders = None
                elif p.no_entry_after is not None and hasattr(b["time"], "time") and b["time"].time() > p.no_entry_after:
                    orders = None  # F5：距收盤不到1小時忽略（p.123）
                else:
                    stop = b["close"] - p.stop_points
                    orders = [Order.enter(Side.LONG, stop=stop, reason="連五黑遇首紅",
                                           run_start=start, run_last=last)]
            elif color == "red" and b["close"] < b["open"]:  # 隔根收黑：連五紅遇首黑
                if b["high"] > df.at[last, "high"]:  # C4 失敗：上影線創新高
                    if ctx.pos is not None and ctx.pos.side == Side.LONG:
                        orders = [Order.exit("平倉(創新高)")]
                elif b["close"] < df.at[last, "low"]:  # C5 失敗：破一低 → 頂倒V空訊，非本訊號
                    orders = None
                elif p.no_entry_after is not None and hasattr(b["time"], "time") and b["time"].time() > p.no_entry_after:
                    orders = None  # F5：距收盤不到1小時忽略（p.123）
                else:
                    stop = b["close"] + p.stop_points
                    orders = [Order.enter(Side.SHORT, stop=stop, reason="連五紅遇首黑",
                                           run_start=start, run_last=last)]

        if orders is None and ctx.pos is not None and p.stale_bars is not None:
            held = i - ctx.pos.entry_i
            if held >= p.stale_bars and ctx.pos.profit(float(b["close"])) <= 0:
                orders = [Order.exit("逾時平倉")]

        self._update_run(df, i, st)
        return orders
