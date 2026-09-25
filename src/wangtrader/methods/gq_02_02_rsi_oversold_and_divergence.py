"""gq-02-02 RSI 低值買點及背離買點（《股技期招》第二章第二節，p.99–108）。

規格文件：methods/股技期招/gq-02-02-RSI低值買點與背離買點.md

本方法原文以個股日線為例。書中「漲幅超過5%」「停損7%」為百分比參數，套用於台指期分K
回測時幅度極小、幾乎不會觸發，需另行調高 big_bar_pct / stop_pct 才有意義。RSI 週期原文
未指定，依專案慣用預設5（wilder）沿用，屬推論預設值。

訊號（p.99, 104）：
  3.1 RSI 低值買點（主要）：
    C1 RSI 觸及超賣區 oversold_level（預設20）以下。
    C2 配合出現漲幅 >= big_bar_pct（預設5%）的紅K線（收盤>開盤）。
    C1+C2 同根成立 → 當根收盤直接進場，不受「收盤須突破RSI最低值K線最高點」之傳統濾網限制（p.99）。
  3.2 RSI 背離買點（同一進場規則的延伸標記，非另立訊號）：
    以層級 pivot_level（原文未定量，推論預設1）取「最近兩個已確認谷點」比較：較早者為背離
    起始點，須對應RSI <= oversold_level（D1）；較近者（本次下跌腳低點）收盤價 < 起始點收盤價
    （價格創新低，以收盤價為準，p.104 D2），但其RSI高於起始點RSI（RSI未同步創新低）。若當次
    C1+C2 訊號出現時最近兩谷點符合上述背離關係，則標記本次訊號為「RSI背離買點」而非「RSI低值
    買點」；進場/停損/出場規則完全相同（p.101, 104：背離不改變進場規則，僅是輔助標記）。

進場（p.99）：C1+C2成立之大漲K線，當根收盤進場。

停損（p.100）：書中列出兩種選項，未言明優先取捨：
  stop_mode="pct"（預設）：最大 stop_pct（預設7%）。
  stop_mode="pivot"：以最近谷點（層級 pivot_level）價位為停損（若尚無已確認谷點則退回 pct 法）。

出場（p.100–102，全節重申的同一條規則）：後續某根K線收盤價跌破前一天K線最低點時出場，
  可考慮反手放空，書中未提供固定停利目標，本模組亦不發明。

過濾（p.100, 104）：
  F1 RSI<=oversold_level 但未配合大漲K線 → 不成立訊號（已由 C1+C2 同根要求自然達成）。
  F2 背離起始點（谷點）RSI 未達 oversold_level 以下 → 不構成有效背離起始點，僅退回一般
     「RSI低值買點」標記（若C1+C2仍成立），不因此整體剔除訊號。
  F3 價格新低須以收盤價認定（本模組本就以收盤價比較，天然符合）。

週期：不限。big_bar_pct/stop_pct/oversold_level 為百分比或RSI數值(0-100)，不隨價位縮放；
  pivot_level 為層級，不隨價位縮放。本模組沒有「點數」型參數，不需要加入 scripts/point_params.py。
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from wangtrader.core import Context, Order, Side, Strategy
from wangtrader.core.indicators import rsi
from wangtrader.core.pivots import Pivot, confirmed_before, find_pivots, last_confirmed

METHOD_ID = "gq-02-02"


@dataclass
class Params:
    rsi_period: int = 5  # 原文未指定，依專案慣用預設5（推論）
    rsi_method: str = "wilder"
    oversold_level: float = 20.0  # C1/D1，p.99, 104
    big_bar_pct: float = 0.05  # C2，p.99
    pivot_level: int = 1  # 背離「前波谷點」層級，原文未定量，推論預設1
    stop_mode: str = "pct"  # "pct"|"pivot"，p.100
    stop_pct: float = 0.07  # p.100


class RsiOversoldAndDivergence(Strategy):
    method_id = METHOD_ID
    intraday = False  # 波段方法（個股日線多日持有）

    def __init__(self, **kw) -> None:
        self.p = Params(**kw)
        self._pivots: list[Pivot] = []

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["rsi"] = rsi(df["close"], self.p.rsi_period, self.p.rsi_method)
        self._pivots = find_pivots(df, self.p.pivot_level)
        return df

    def detect(self, df: pd.DataFrame, i: int) -> str | None:
        """C1+C2 是否成立；回傳訊號標籤（一般 / 背離），不成立回傳 None。"""
        p = self.p
        r = df.at[i, "rsi"]
        if pd.isna(r) or r > p.oversold_level:
            return None
        b = df.iloc[i]
        if not (b["close"] > b["open"]):
            return None
        pct = (b["close"] - df.at[i - 1, "close"]) / df.at[i - 1, "close"] if i > 0 else float("nan")
        if pd.isna(pct) or pct < p.big_bar_pct:
            return None
        # 背離判定（p.104 D1/D2）：比較「最近兩個已確認谷點」——較早者為背離起始點，
        # 須RSI<=超賣區；較近者（本次下跌腳的低點）收盤價創新低，但其RSI未創新低（高於起始點）。
        troughs = confirmed_before(self._pivots, i, "trough")
        if len(troughs) >= 2:
            t_prev, t_last = troughs[-2], troughs[-1]
            prev_rsi, last_rsi = df.at[t_prev.index, "rsi"], df.at[t_last.index, "rsi"]
            prev_close, last_close = df.at[t_prev.index, "close"], df.at[t_last.index, "close"]
            if (pd.notna(prev_rsi) and prev_rsi <= p.oversold_level and pd.notna(last_rsi)
                    and last_close < prev_close and last_rsi > prev_rsi):
                return "RSI背離買點"
        return "RSI低值買點"

    def _stop(self, df: pd.DataFrame, i: int, price: float) -> float:
        p = self.p
        if p.stop_mode == "pivot":
            piv = last_confirmed(self._pivots, i, "trough")
            if piv is not None:
                return piv.price
        return price * (1 - p.stop_pct)

    def on_bar(self, ctx: Context):
        p, df, i = self.p, ctx.df, ctx.i
        if ctx.pos is not None:
            # 出場：收盤跌破前一天K線最低點（p.100–102）
            if i > ctx.pos.entry_i and df.at[i, "close"] < df.at[i - 1, "low"]:
                return [Order.exit("跌破前一天最低點")]
            return None
        reason = self.detect(df, i)
        if reason is None:
            return None
        price = float(df.at[i, "close"])
        return [Order.enter(Side.LONG, stop=self._stop(df, i, price), reason=reason)]
