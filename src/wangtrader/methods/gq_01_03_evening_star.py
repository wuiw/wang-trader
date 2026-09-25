"""gq-01-03 夜星反轉（《股技期招》第一章，p.6–9）。

規格文件：methods/股技期招/gq-01-03-夜星反轉.md

本節只有空方（高檔反轉賣出）訊號，書中明言低檔夜星無反轉意義，未見多方鏡像（見文件direction欄）。

訊號（空方，p.6）：
  C1：行情處於連續性大漲之後的相對高檔位置。
  C2：波段最高點附近出現一根小星線（夜星，緊接在長紅K線A之後），且小星線本身或A爆量。
  C3：小星線隔天K線收盤侵入A實體中點以下 → 初步反轉警訊觸發。
  C4（加強確認，可能延後數日）：後續某根K線收盤跌破A最低點 → 反轉之勢更明顯。
進場（p.6）：原文未明確二擇一「C3」或「C4」為正式進場點，本模組以 `entry_trigger` 參數選擇，
  預設 "c3"（初步訊號觸發即開始留意放空，p.6原句）。
停損：原文未規定明確點位，本模組不發明數值，`Order.enter(stop=None)`。
出場：書中未明確說明，本模組不實作停利／額外出場。
過濾（p.8）：
  F1 夜星出現在低檔 → 不做（已內建於C1「高檔」條件）。
  F2 夜星組合沒有爆量 → 不做（已內建於C2爆量條件）。
  F3 即使爆量，若後續成交量急速萎縮、且均線未走緩，反轉危機可被化解 → 訊號不成立
     （`check_volume_shrink_filter`，預設開啟，量化方式見下方參數說明，原文未定量處已標註推論）。

無法量化之處（原文未定量，預設值為推論，保守設定，詳見各參數註解）：
  「波段最高點附近」「連續性大漲」「長紅K線」「小星線」「爆量」「成交量急速萎縮」
  「均線未走緩」，書中均為定性描述，本模組各以獨立參數量化，預設值皆為推論估計。

週期：不限。所有百分比參數不隨週期或商品縮放；根數(lookback)類參數不縮放。
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from wangtrader.core import Context, Order, Side, Strategy
from wangtrader.core.indicators import sma

METHOD_ID = "gq-01-03"


@dataclass
class Params:
    high_lookback: int = 20  # C1：長紅K線A之高點須為近N根（含本身）新高，判定「波段最高點附近」。原文未定量，推論。
    rally_lookback: int = 10  # C1：「連續性大漲」回顧根數。原文未定量，推論。
    rally_min_pct: float = 15.0  # C1：回顧期間累計漲幅門檻（%）。原文未定量，推論。
    long_candle_min_pct: float = 3.0  # C2：「長紅K線」門檻（%，相對開盤）。原文未定量，推論。
    star_max_body_pct: float = 1.0  # C2：「小星線」實體門檻（%，相對開盤）。原文未定量，推論。
    vol_ma_period: int = 20  # 爆量比較基準均量週期（股票專屬概念，推論；台指期分K需依實際狀況調整）。
    vol_spike_ratio: float = 2.0  # 爆量門檻＝量 ≥ 均量 × 此倍數（推論，保守）。
    entry_trigger: str = "c3"  # 進場觸發點："c3"（初步訊號，預設）或"c4"（加強確認）。原文未二擇一，推論。
    check_volume_shrink_filter: bool = True  # F3（p.8）：爆量後量急縮且均線未走緩 → 訊號不成立。
    vol_shrink_ratio: float = 0.5  # F3：「量急縮」門檻＝觸發根均量 ≤ 夜星爆量 × 此比例。原文未定量，推論。
    shrink_ma_period: int = 10  # F3：判斷「均線未走緩」用之均線週期。原文未定量，推論。


@dataclass
class _Candidate:
    a_idx: int  # 長紅K線A的索引
    star_idx: int  # 小星線（夜星）索引
    a_low: float
    a_mid: float
    ref_vol: float  # 爆量參考值＝夜星與A中較大的成交量
    c3_done: bool = False


def _is_long_red(b: pd.Series, pct: float) -> bool:
    o, c = float(b["open"]), float(b["close"])
    return c > o and o != 0 and (c - o) / abs(o) * 100.0 >= pct


def _is_star(b: pd.Series, pct: float) -> bool:
    o, c = float(b["open"]), float(b["close"])
    return o != 0 and abs(c - o) / abs(o) * 100.0 <= pct


class EveningStar(Strategy):
    method_id = METHOD_ID
    intraday = False  # 波段反轉型態，非當沖方法（p.6–9 範例為日線）

    def __init__(self, **kw) -> None:
        self.p = Params(**kw)
        if self.p.entry_trigger not in ("c3", "c4"):
            raise ValueError("entry_trigger 須為 'c3' 或 'c4'")
        # 候選跨交易日持續有效（波段型態，intraday=False）。
        self._cand: _Candidate | None = None

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["roll_high"] = df["high"].rolling(self.p.high_lookback, min_periods=self.p.high_lookback).max()
        df["vol_ma"] = sma(df["volume"], self.p.vol_ma_period)
        df["shrink_ma"] = sma(df["close"], self.p.shrink_ma_period)
        return df

    def _volume_spike(self, df: pd.DataFrame, idx: int) -> bool:
        vm = df.at[idx, "vol_ma"]
        return bool(not pd.isna(vm) and vm > 0 and df.at[idx, "volume"] >= vm * self.p.vol_spike_ratio)

    def _try_form_candidate(self, df: pd.DataFrame, i: int) -> None:
        """第 i 根為小星線（夜星）時，檢查前一根 A 是否構成 C1/C2，成立則（重新）設定候選。"""
        p = self.p
        if i < 1:
            return
        a, star = df.iloc[i - 1], df.iloc[i]
        if not _is_long_red(a, p.long_candle_min_pct) or not _is_star(star, p.star_max_body_pct):
            return
        roll_high = df.at[i - 1, "roll_high"]
        if pd.isna(roll_high) or a["high"] < roll_high:  # C1：A須為近N根新高（波段最高點附近）
            return
        j = i - 1 - p.rally_lookback
        if j < 0:
            return
        base_close = df.at[j, "close"]
        if base_close <= 0 or (a["close"] - base_close) / base_close * 100.0 < p.rally_min_pct:  # C1：連續性大漲
            return
        if not (self._volume_spike(df, i - 1) or self._volume_spike(df, i)):  # C2：爆量
            return
        mid = (float(a["open"]) + float(a["close"])) / 2.0
        self._cand = _Candidate(i - 1, i, float(a["low"]), mid, float(max(a["volume"], star["volume"])))

    def _shrink_exception(self, df: pd.DataFrame, i: int) -> bool:
        """F3：夜星後成交量急速萎縮且均線未走緩 → 反轉危機化解，訊號不成立。"""
        c = self._cand
        window = df.iloc[c.star_idx + 1 : i + 1]["volume"]
        if window.empty:
            return False
        shrink = window.mean() <= c.ref_vol * self.p.vol_shrink_ratio
        ma_star, ma_now = df.at[c.star_idx, "shrink_ma"], df.at[i, "shrink_ma"]
        still_rising = bool(not pd.isna(ma_star) and not pd.isna(ma_now) and ma_now > ma_star)
        return shrink and still_rising

    def on_bar(self, ctx: Context):
        p, df, i = self.p, ctx.df, ctx.i
        order = None
        c = self._cand
        if c is not None and i > c.star_idx:
            close_ = float(df.at[i, "close"])
            triggered = False
            if not c.c3_done and close_ < c.a_mid:
                c.c3_done = True
                if p.entry_trigger == "c3":
                    triggered = True
            if p.entry_trigger == "c4" and close_ < c.a_low:
                triggered = True
            if triggered:
                if not (p.check_volume_shrink_filter and self._shrink_exception(df, i)):
                    order = Order.enter(Side.SHORT, stop=None, reason="夜星反轉",
                                         star_i=c.star_idx, a_i=c.a_idx)
                self._cand = None

        self._try_form_candidate(df, i)
        return [order] if order is not None else None
