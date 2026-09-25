"""gq-04-03 威廉指標找極端點（《股技期招》第四章第三節，p.192–204）。

規格文件：methods/股技期招/gq-04-03-威廉指標找極端點.md

core/indicators.py 沒有威廉指標，本模組私有實作，並依書中定義採「80-100為超買區（上方）、
0-20為超賣區（下方）」的方向（與一般威廉指標慣用的0-20超買、80-100超賣相反，p.193）：
  威廉值 = (收盤 - N日最低) / (N日最高 - N日最低) * 100
  （書中威廉值90表示收盤貼近N日最高點，與RSI/KD的%K同向，p.193）。

訊號：
### 賣出（超買區，p.192）
  C1 威廉值進入超買區（>= overbought_enter，書中80），且期間曾至少一根觸及
     overbought_extreme（書中90）。
  C2 威廉值首度離開超買區（跌破80）。
  C3 離開位置距最高峰（區間內最高價所在K線）不超過 max_bars_from_extreme（書中4天/根）。
  C4 K線收盤跌破前一根K線「真實低點」＝ min(前一天最低點, 前二天收盤價)（p.192）。
### 買進（超賣區，鏡像，p.192）
  C1'-C4' 同上鏡像，臨界值 oversold_enter（20）/ oversold_extreme（10），「真實高點」＝
     max(前一天最高點, 前二天收盤價)。
### 提前訊號（慣性破壞，E1/E2，p.192、195-196、198）
  威廉值尚未離開超買（超賣）區，但K線收盤已跌破（突破）前一天真實低（高）點；須配合先前連續
  inertia_bars（書中8）根以上K線未曾跌破（突破）真實低（高）點的慣性，此次首度突破才成立。
### 停留時間濾網（F3，p.195）
  進入到離開超買超賣區域超過 max_dwell_bars（書中10天，日線）仍未離開 → 不宜逆勢；此後即使
  離開也不視為有效訊號（除非啟用 long_stay_exception，見下）。
### 長時間停留例外（僅30分鐘以上K線圖適用，p.200-201；本模組以根數實作機制本身，書中限定的
    週期適用範圍由使用者自行判斷是否套用，預設關閉）：
  連續停留超過 long_stay_threshold（書中20）根未曾離開，首度離開時只要符合 C3/C4（或C3'/C4'），
  仍可視為訊號。

進場：C1-C4（或C1'-C4'）成立之K線收盤，或E1/E2提前訊號成立時（p.192、194、198）。
停損（p.194, 196-197）：stop_mode="recent_extreme"（預設，波峰/波谷 ± stop_tick，日線「上方一檔」、
  分時「1~3檔」化簡為單一參數）或 "pct"（固定7%，日線適用）。
出場：書中僅提及「階段出場方式」或「K線慣性操作法」（未展開規則），或分時「固定點數／階梯出場線」
  （亦未給參數），原文未提供可程式化的具體停利規則，本模組不實作任何停利，exit_mode 固定持有至
  觸價停損或資料結束。
過濾：
  F1　未觸及90/10不列入極端位置（見C1/C1'，overbought_extreme/oversold_extreme）。
  F2　距峰谷超過 max_bars_from_extreme（4）→ 不採用（見C3/C3'）。
  F3　停留超過 max_dwell_bars（10）仍未離開 → 不逆勢（見上）。
  F4　提前訊號須配合 inertia_bars（8）根以上慣性（見E1/E2）。
  F5　「假性進入超買超賣」（區間高低點快速下移造成的假象）：無法可靠程式化辨識，不實作。
  F6　尾盤（收盤前半小時）不宜進場：以 no_entry_after（時鐘時間，預設None關閉）近似實作，
      書中原為當沖情境下的建議（p.198）。
  反手規則（p.202）：需要「窄幅橫盤且時間夠長」的型態辨識，原文未給可程式化門檻，不實作。

本方法多空皆可，實作為對稱鏡像；提前訊號的買進方向書中同時明述兩方向（非推論）。
週期：不限。所有門檻以根數／百分比表示；長時間停留例外書中限定30分鐘以上K線圖，本模組
不判斷時鐘週期，機制本身可用但預設關閉，是否符合書中適用範圍由使用者自行判斷。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time

import pandas as pd

from wangtrader.core import Context, Order, Side, Strategy

METHOD_ID = "gq-04-03"


def _williams(df: pd.DataFrame, n: int) -> pd.Series:
    """書中定義的威廉值（80-100超買、0-20超賣，與%K同向）。"""
    hh = df["high"].rolling(n, min_periods=n).max()
    ll = df["low"].rolling(n, min_periods=n).min()
    rng = (hh - ll)
    wr = (df["close"] - ll) / rng * 100
    return wr.where(rng != 0, 50.0)


@dataclass
class Params:
    williams_period: int = 50  # 書中50或100，明確數字，可調整（p.192）
    overbought_enter: float = 80.0
    overbought_extreme: float = 90.0
    oversold_enter: float = 20.0
    oversold_extreme: float = 10.0
    max_bars_from_extreme: int = 4  # C3/C3'，明確數字（p.192）
    max_dwell_bars: int = 10  # F3，明確數字（日線，p.195）
    inertia_bars: int = 8  # E1/E2，明確數字（p.192、195-196、198）
    long_stay_exception: bool = False  # 長時間停留例外，書中限30分鐘以上K線圖，預設關閉
    long_stay_threshold: int = 20  # 明確數字（p.200-201）
    no_entry_after: time | None = None  # F6尾盤濾網，書中為當沖建議，預設關閉（p.198）
    stop_mode: str = "recent_extreme"  # "recent_extreme" | "pct"
    stop_tick: float = 1.0
    stop_pct: float = 7.0


@dataclass
class _Zone:
    in_zone: bool = False
    entered_i: int | None = None
    touched_extreme: bool = False
    extreme_i: int | None = None  # 區間內最高價(賣出)/最低價(買進)所在K線


class WilliamsExtreme(Strategy):
    method_id = METHOD_ID
    intraday = False

    def __init__(self, **kw) -> None:
        self.p = Params(**kw)
        self._ob = _Zone()  # 超買（賣出）
        self._os = _Zone()  # 超賣（買進）
        self._no_break_low_run = 0  # 連續未跌破真實低點的根數（E1慣性）
        self._no_break_high_run = 0  # 連續未突破真實高點的根數（E2慣性）

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["wr"] = _williams(df, self.p.williams_period)
        return df

    def _real_low(self, df: pd.DataFrame, i: int) -> float | None:
        if i < 2:
            return None
        return min(df.at[i - 1, "low"], df.at[i - 2, "close"])

    def _real_high(self, df: pd.DataFrame, i: int) -> float | None:
        if i < 2:
            return None
        return max(df.at[i - 1, "high"], df.at[i - 2, "close"])

    def _time_ok(self, b: pd.Series) -> bool:
        p = self.p
        if p.no_entry_after is None:
            return True
        t = b["time"]
        return not (hasattr(t, "time") and t.time() > p.no_entry_after)

    def _stop(self, extreme_price: float, side: Side, entry: float) -> float:
        p = self.p
        if p.stop_mode == "pct":
            return entry * (1 - p.stop_pct / 100) if side == Side.LONG else entry * (1 + p.stop_pct / 100)
        return (extreme_price - p.stop_tick) if side == Side.LONG else (extreme_price + p.stop_tick)

    def on_bar(self, ctx: Context):
        p, df, i = self.p, ctx.df, ctx.i
        b = df.iloc[i]
        wr = b["wr"]
        order = None

        real_low = self._real_low(df, i)
        real_high = self._real_high(df, i)
        broke_low = real_low is not None and b["close"] < real_low
        broke_high = real_high is not None and b["close"] > real_high

        if not pd.isna(wr):
            ob, os_ = self._ob, self._os
            # ---- 超買（賣出）狀態機 ----
            if wr >= p.overbought_enter:
                if not ob.in_zone:
                    ob.in_zone, ob.entered_i, ob.touched_extreme, ob.extreme_i = True, i, False, i
                if wr >= p.overbought_extreme:
                    ob.touched_extreme = True
                if b["high"] >= df.at[ob.extreme_i, "high"]:
                    ob.extreme_i = i
                # E1：尚未離開超買區，但已跌破真實低點，且先前有慣性
                if broke_low and self._no_break_low_run >= p.inertia_bars and order is None and self._time_ok(b):
                    entry = float(b["close"])
                    order = Order.enter(Side.SHORT, stop=self._stop(df.at[ob.extreme_i, "high"], Side.SHORT, entry),
                                         reason="威廉指標提前賣訊")
                    ob.__init__()
            elif ob.in_zone:  # 首度離開超買區
                dwell = i - ob.entered_i
                allowed = ob.touched_extreme and (dwell <= p.max_dwell_bars
                                                   or (p.long_stay_exception and dwell >= p.long_stay_threshold))
                if allowed and order is None and self._time_ok(b):
                    peak_i = ob.extreme_i
                    if (i - peak_i) <= p.max_bars_from_extreme and broke_low:
                        entry = float(b["close"])
                        order = Order.enter(Side.SHORT, stop=self._stop(df.at[peak_i, "high"], Side.SHORT, entry),
                                             reason="威廉指標找極端點-賣出")
                ob.__init__()

            # ---- 超賣（買進）狀態機（鏡像） ----
            if wr <= p.oversold_enter:
                if not os_.in_zone:
                    os_.in_zone, os_.entered_i, os_.touched_extreme, os_.extreme_i = True, i, False, i
                if wr <= p.oversold_extreme:
                    os_.touched_extreme = True
                if b["low"] <= df.at[os_.extreme_i, "low"]:
                    os_.extreme_i = i
                if broke_high and self._no_break_high_run >= p.inertia_bars and order is None and self._time_ok(b):
                    entry = float(b["close"])
                    order = Order.enter(Side.LONG, stop=self._stop(df.at[os_.extreme_i, "low"], Side.LONG, entry),
                                         reason="威廉指標提前買訊")
                    os_.__init__()
            elif os_.in_zone:
                dwell = i - os_.entered_i
                allowed = os_.touched_extreme and (dwell <= p.max_dwell_bars
                                                    or (p.long_stay_exception and dwell >= p.long_stay_threshold))
                if allowed and order is None and self._time_ok(b):
                    trough_i = os_.extreme_i
                    if (i - trough_i) <= p.max_bars_from_extreme and broke_high:
                        entry = float(b["close"])
                        order = Order.enter(Side.LONG, stop=self._stop(df.at[trough_i, "low"], Side.LONG, entry),
                                             reason="威廉指標找極端點-買進")
                os_.__init__()

        # 更新E1/E2慣性計數（須放在訊號判斷之後，避免用到當根尚未確定的狀態）
        self._no_break_low_run = 0 if broke_low else self._no_break_low_run + 1
        self._no_break_high_run = 0 if broke_high else self._no_break_high_run + 1

        if order is not None and ctx.pos is not None and ctx.pos.side == order.side:
            order = None
        return [order] if order is not None else None
