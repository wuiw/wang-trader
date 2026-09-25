"""gq-01-02 倒T線反轉（買進）／T字線反轉（賣出）（《股技期招》第一章，p.4–5）。

規格文件：methods/股技期招/gq-01-02-轉變線反轉訊號.md

核心概念（p.4–5）：「轉變線」為開盤收盤同價（十字線）的延伸型態：帶長上影線、無下影線者為
「倒T線」；帶長下影線、無上影線者為「T字線」。倒T線於**上升趨勢**中出現，是買進參考；
T字線於**上升漲勢爆量之後**出現，是賣出警訊。

訊號（p.5）：
  倒T線（多）C1–C3：上升趨勢中出現倒T線 → 價格折回後，後續某根K線**收盤突破**倒T線最高點
    → 買進。
  T字線（空）C1'–C3'：上升漲勢已爆量 → 出現T字線 → 後續某根K線**收盤跌破**T字線最低點
    → 賣出。
進場（p.5）：訊號成立當根K線收盤價（由 core engine 以收盤成交）。
停損：原文未規定明確點位，本模組不發明數值，`Order.enter(stop=None)`。
出場：書中未明確說明，本模組不實作停利／額外出場；僅停損為None、且反向訊號會由引擎反手，
  或資料結束時未平倉（intraday=False，非當沖）。
過濾（p.5）：
  T字線須發生在上升漲勢**爆量**之後；倒T線須發生在**上升趨勢**中；不符者不成立候選。

無法量化之處（原文未定量，預設值為推論，見docstring下方參數說明）：
  1. 「開盤收盤同價」的容許誤差（doji_body_max_pct）。
  2. 判定「無」另一側影線的容許誤差（no_shadow_max_pct）。
  3. 判定影線為「長」的門檻（long_shadow_min_pct）。
  4. 「上升趨勢」的量化定義：本模組以「收盤在均線之上，且均線本身上揚」近似（uptrend_ma_period）。
  5. 「爆量」股票專屬概念（原文以「全圖最大量」舉例），本模組以「成交量 ≥ N根均量 × 倍數」
     替代（vol_ma_period, vol_spike_ratio）；**台指期分K不適用書中股票語境，門檻需依實際
     成交量規模調整，或以 require_volume_spike=False 關閉**。

週期：不限。doji_body_max_pct / no_shadow_max_pct / long_shadow_min_pct / vol_spike_ratio
為百分比或倍率參數，不隨週期或商品縮放；不涉及任何點數門檻。
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from wangtrader.core import Context, Order, Side, Strategy
from wangtrader.core.indicators import sma

METHOD_ID = "gq-01-02"


@dataclass
class Params:
    doji_body_max_pct: float = 0.3  # 開盤收盤視為「同價」的容許誤差（%）。原文未定量，推論。
    no_shadow_max_pct: float = 0.1  # 判定「無」另一側影線的容許誤差（%）。原文未定量，推論。
    long_shadow_min_pct: float = 2.0  # 判定影線為「長」的門檻（%）。原文未定量，推論。
    uptrend_ma_period: int = 20  # 判定「上升趨勢」的均線週期。原文未定量，推論。
    vol_ma_period: int = 20  # T字線「爆量」比較基準均量週期（推論，股票專屬，見docstring）。
    vol_spike_ratio: float = 2.0  # 爆量門檻＝量 ≥ 均量 × 此倍數（推論，保守值）。
    require_volume_spike: bool = True  # T字線是否須爆量（p.5明文要求；台指期分K可關閉）。


@dataclass
class _Candidate:
    idx: int
    level: float


def _shape(b: pd.Series, p: Params) -> str | None:
    """回傳 'inverted_t'（倒T線）、't'（T字線）或 None（p.4–5，見gq-01-01圖1-1轉變線定義）。"""
    o, c, h, lo = float(b["open"]), float(b["close"]), float(b["high"]), float(b["low"])
    if o == 0:
        return None
    ref = abs(o)
    body_pct = abs(c - o) / ref * 100.0
    if body_pct > p.doji_body_max_pct:
        return None
    lower_pct = (min(o, c) - lo) / ref * 100.0
    upper_pct = (h - max(o, c)) / ref * 100.0
    if lower_pct <= p.no_shadow_max_pct and upper_pct >= p.long_shadow_min_pct:
        return "inverted_t"
    if upper_pct <= p.no_shadow_max_pct and lower_pct >= p.long_shadow_min_pct:
        return "t"
    return None


def _is_uptrend(df: pd.DataFrame, i: int, ma_col: str) -> bool:
    """上升趨勢（推論）：收盤在均線之上，且均線本身呈上升。"""
    if i < 1:
        return False
    ma, pma = df.at[i, ma_col], df.at[i - 1, ma_col]
    if pd.isna(ma) or pd.isna(pma):
        return False
    return df.at[i, "close"] > ma and ma > pma


class TransitionCandle(Strategy):
    method_id = METHOD_ID
    intraday = False  # 波段反轉型態，非當沖方法（p.4–5 範例為日線）

    def __init__(self, **kw) -> None:
        self.p = Params(**kw)
        # 候選跨交易日持續有效，不因新的一天重置（本方法為波段型態，book 範例本身即橫跨多個交易日
        # 才等到突破，intraday=False，見 q3-11 同類慣例）。
        self._long_cand: _Candidate | None = None
        self._short_cand: _Candidate | None = None

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["trend_ma"] = sma(df["close"], self.p.uptrend_ma_period)
        df["vol_ma"] = sma(df["volume"], self.p.vol_ma_period)
        return df

    def on_bar(self, ctx: Context):
        p, df, i = self.p, ctx.df, ctx.i
        orders: list[Order] = []
        close_ = float(df.at[i, "close"])

        if self._long_cand is not None and close_ > self._long_cand.level:
            orders.append(Order.enter(Side.LONG, stop=None, reason="倒T線突破買進", signal_i=self._long_cand.idx))
            self._long_cand = None

        if self._short_cand is not None and close_ < self._short_cand.level:
            orders.append(Order.enter(Side.SHORT, stop=None, reason="T字線跌破賣出", signal_i=self._short_cand.idx))
            self._short_cand = None

        b = df.iloc[i]
        shape = _shape(b, p)
        if shape == "inverted_t" and _is_uptrend(df, i, "trend_ma"):
            self._long_cand = _Candidate(i, float(b["high"]))
        elif shape == "t" and _is_uptrend(df, i, "trend_ma"):
            spike = True
            if p.require_volume_spike:
                vm = df.at[i, "vol_ma"]
                spike = bool(not pd.isna(vm) and vm > 0 and b["volume"] >= vm * p.vol_spike_ratio)
            if spike:
                self._short_cand = _Candidate(i, float(b["low"]))

        return orders or None
