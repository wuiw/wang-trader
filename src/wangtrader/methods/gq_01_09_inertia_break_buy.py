"""gq-01-09 慣性破壞買訊（《股技期招》第一章第四節，p.41-51）。

規格文件：methods/股技期招/gq-01-09-慣性破壞買訊.md

本方法為波段方法（intraday=False，可跨日持有，原文明言「應以波段角度持有」p.44）。書中僅示範多方
（原文未提供空方鏡像，不強行推論），程式不綁週期。「大漲K線」「大跌K線」門檻原文未定量，維持%參數。

訊號（多方，p.41-51）：
  C1 整理格局累計超過 lookback_days（預設20，p.41）個交易日，期間內每一根K線收盤皆未突破「前2日
     區間最高點」（K線慣性，追蹤方式：以連續未突破的根數為一段「慣性streak」，streak結束＝某根K線
     收盤突破前2日高，見 C2）。
  C2 該根K線（訊號K）須為「大漲K線」（實體漲幅 ≥ big_bar_body_pct，原文未定量，推論預設值）。
  C3 依整理格局形狀決定是否需再突破下降趨勢線（p.42、p.45、p.47、p.50-51）：
     水平式整理（整理區間高低差 ≤ 區間低點的 horizontal_range_pct%，p.42）：C2 成立即可，不需趨勢線。
     下斜式整理（超過此範圍）：需另外用區間內最近兩個依序遞減的層級 trend_pivot_level 峰點連線，
       訊號K收盤須同時突破此線（線性內插/外插至訊號K索引）；找不到兩個遞減峰點時，視同未突破。
  C4（加分，預設不強制）：訊號K收盤同時站上均線（require_ma_breakout=True 時才檢查，p.46）。
  C5（N字二次確認，僅下斜式整理且C3未過時）：等待後續某根K線收盤突破該大漲K線的最高點，才進場；
     此後續K線視為停損計算基準（p.48-49，原文未明言用哪一根K線計算停損，本模組採「實際觸發進場的
     那一根」，見待確認事項）。

進場（p.42-51）：C1-C4皆符合時，訊號K線收盤進場；C3不符合但C1/C2/C4符合時，等待C5成立後進場。
停損（二擇一，原文未強制指定優先序，p.42-43,47）：stop_mode="low"（訊號K最低點，預設）｜
  "pct7"（收盤價向下 stop_pct%，預設7%）｜"tighter"（兩者取風險較小者）｜"wider"（風險較大者）。
出場：停損未觸及前以波段角度持有（p.44），書中未提供另立的停利規則，本模組不發明停利。

待確認事項：
  - 「大漲K線」門檻原文未定量，本模組以%實體漲幅參數化，推論預設值。
  - 停損二擇一何者優先，原文未規定，本模組預設"low"，可切換。
  - N字二次確認進場時，停損計算基準K線原文未明言，本模組採確認進場當根，屬推論。
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from wangtrader.core import Context, Order, Side, Strategy
from wangtrader.core.indicators import sma
from wangtrader.core.pivots import Pivot, confirmed_before, find_pivots

METHOD_ID = "gq-01-09"


def _trendline_value(p1: Pivot, p2: Pivot, x: int) -> float:
    """兩峰谷點 p1(較早)、p2(較晚) 連線，回傳在索引 x 處的內插/外插值。"""
    if p2.index == p1.index:
        return p2.price
    slope = (p2.price - p1.price) / (p2.index - p1.index)
    return p1.price + slope * (x - p1.index)


@dataclass
class Params:
    lookback_days: int = 20  # C1：整理格局累計交易日門檻（p.41，「超過20個交易日」）
    big_bar_body_pct: float = 4.0  # C2：「大漲K線」實體漲幅門檻（原文未定量，推論預設值，p.41-49）
    horizontal_range_pct: float = 20.0  # C3：水平式整理判定，區間高低差 ≤ 此百分比（p.42）
    trend_pivot_level: int = 2  # C3：下斜式整理找峰點的層級（原文未指定，借用 gq-01-11 層級2慣例，推論）
    require_ma_breakout: bool = False  # C4：加分條件，預設不強制（p.46）
    ma_period: int = 20  # C4 用均線週期（原文未指定，推論預設值）
    stop_mode: str = "low"  # 停損二擇一："low"｜"pct7"｜"tighter"｜"wider"
    stop_pct: float = 7.0  # 收盤價向下 N% 停損（p.42-43,47）


class InertiaBreakBuy(Strategy):
    method_id = METHOD_ID
    intraday = False  # 波段方法，停損未觸及前以波段角度持有（p.44）

    def __init__(self, **kw) -> None:
        self.p = Params(**kw)
        self._streak_start = 2
        self._n_watch: dict | None = None  # {'high': 大漲K最高點}
        self._pivots: list[Pivot] = []

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["ma"] = sma(df["close"], self.p.ma_period)
        self._pivots = find_pivots(df, level=self.p.trend_pivot_level)
        return df

    def _stop(self, bar: pd.Series) -> float:
        p = self.p
        lo_stop = float(bar["low"])
        pct_stop = float(bar["close"]) * (1 - p.stop_pct / 100.0)
        if p.stop_mode == "pct7":
            return pct_stop
        if p.stop_mode == "tighter":
            return max(lo_stop, pct_stop)
        if p.stop_mode == "wider":
            return min(lo_stop, pct_stop)
        return lo_stop  # "low"（預設）

    def _shape_ok(self, df: pd.DataFrame, i: int, start: int) -> bool | None:
        """回傳 True＝直接通過(水平式或下斜式已突破趨勢線)；False＝下斜式但未突破趨勢線（需N字確認）。"""
        window = df.iloc[start:i]
        region_low = float(window["low"].min())
        region_high = float(window["high"].max())
        if region_low > 0 and (region_high - region_low) <= region_low * (self.p.horizontal_range_pct / 100.0):
            return True  # 水平式整理，不需趨勢線
        peaks = [pv for pv in confirmed_before(self._pivots, i - 1, "peak") if start <= pv.index < i]
        peaks.sort(key=lambda pv: pv.index)
        for k in range(len(peaks) - 1, 0, -1):
            p2, p1 = peaks[k], peaks[k - 1]
            if p2.price < p1.price:  # 依序遞減
                line_val = _trendline_value(p1, p2, i)
                return float(df.at[i, "close"]) > line_val
        return False  # 找不到兩個遞減峰點，視同未突破

    def _passes_ma(self, df: pd.DataFrame, i: int) -> bool:
        if not self.p.require_ma_breakout:
            return True
        ma = df.at[i, "ma"]
        return pd.notna(ma) and float(df.at[i, "close"]) > ma

    def on_bar(self, ctx: Context):
        p, df, i = self.p, ctx.df, ctx.i
        if i < 2:
            return None
        b = df.iloc[i]
        orders: list[Order] = []

        # N字二次確認：等待後續K線收盤突破大漲K線最高點
        if self._n_watch is not None and ctx.pos is None:
            if float(b["close"]) > self._n_watch["high"]:
                self._n_watch = None
                orders.append(Order.enter(Side.LONG, stop=self._stop(b), reason="慣性破壞買訊(N字確認)"))

        broke_2d_high = float(b["close"]) > max(float(df.at[i - 1, "high"]), float(df.at[i - 2, "high"]))
        if broke_2d_high:
            streak_len = i - self._streak_start
            if streak_len > p.lookback_days and ctx.pos is None and not orders:
                body_pct = (
                    (b["close"] - b["open"]) / b["open"] * 100.0 if b["open"] > 0 and b["close"] > b["open"] else -1
                )
                if body_pct >= p.big_bar_body_pct and self._passes_ma(df, i):
                    shape = self._shape_ok(df, i, self._streak_start)
                    if shape:
                        orders.append(Order.enter(Side.LONG, stop=self._stop(b), reason="慣性破壞買訊"))
                    elif shape is False:  # 下斜式整理但未突破趨勢線 → 進入N字二次確認觀察
                        self._n_watch = {"high": float(b["high"])}
            self._streak_start = i + 1

        return orders or None
