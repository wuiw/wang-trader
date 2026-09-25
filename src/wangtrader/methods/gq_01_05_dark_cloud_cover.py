"""gq-01-05 覆蓋線反轉與反軋買點（《股技期招》第一章，p.16–20）。

規格文件：methods/股技期招/gq-01-05-覆蓋線反轉與反軋買點.md

訊號（p.16–19）：
  覆蓋線（反轉確認，多單出場／空方參考）C1–C5：
    C1 前一日（A）為長紅K線，行情已推升至高檔區域（本模組以「近N根新高」＋「N根累計漲幅」量化，推論）。
    C2 隔日（B）跳高開盤，通常漲幅在3%以內。
    C3 之後一路向下趨軟，收盤反跌，收在A實體中點以下 → 覆蓋線構成。
    C4（機率加強因子，非必要條件）若配合爆量，反轉機率大幅增高；本模組**不**以此濾除訊號，
       僅將是否爆量記錄於訊號 meta（vol_spike）供參考（p.16–19明文非必要條件）。
    C5（轉空確認）後續某根K線收盤跌破A的最低點 → 既有多頭部位應出場（§6「爆量長紅K線最低點
       未被跌破前可續抱，跌破時反轉訊號確認」；本節未使用gq-01-04「真實低點」之表述，故本模組
       直接採用A最低點，不併入A之前一日收盤）。
  反軋買點（多方，新倉）Cr1–Cr2：
    Cr1 覆蓋線（B）已出現（不要求C4爆量）。
    Cr2 覆蓋線最高點（B的最高點）被後續K線收盤突破、收復 → 反軋買點，進場做多。
進場（p.18）：
  多單出場：C5成立當根K線收盤，既有多頭部位出場（僅在確有多頭部位時送出 Order.exit）。
  放空新倉：原文未明確規定，本模組不發明。
  反軋買點：Cr2成立當根K線收盤進場做多。
停損（p.18）：反軋買點以突破訊號K線（Cr2成立當根）最低點為停損，原文明文，非推論。
  覆蓋線反轉確認本身無獨立停損規則，原文未規定。
出場/停利：反軋買點原文未給固定停利，本模組不發明，僅停損；多單出場本身即是出場動作。
過濾（p.18–20）：
  F1 覆蓋線若沒有在相對區間內爆大量，且A價格未達反轉威脅程度，不宜視為強烈反轉警訊，應改為
     觀察最高點是否被突破尋找反向買點：本模組本就不以爆量濾除Cr2，行為已與此建議一致。
  F2 爆量若出現在行情推升一大段之後才特別危險，須加上反轉K線組合才形成警示：本模組C1已要求
     「高檔＋累計漲幅」，已隱含此濾網精神，不另外實作獨立的「爆量本身是否危險」判斷。
  F3 爆量反轉組合出現後若呈橫向整理，不宜貿然視為確認反轉，應等待真正突破組合最高價壓力：
     此即Cr2本身的定義（等待收盤突破），已內建。

無法量化之處（原文未定量，預設值為推論，保守設定）：
  「高檔區域」「長紅K線」，各自參數見下方註解；爆量僅作為meta記錄，不影響訊號成立與否。

週期：不限。百分比/倍率參數不隨週期或商品縮放；根數(lookback)類參數不縮放。
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from wangtrader.core import Context, Order, Side, Strategy
from wangtrader.core.indicators import sma

METHOD_ID = "gq-01-05"


@dataclass
class Params:
    long_candle_min_pct: float = 3.0  # C1：A「長紅K線」門檻（%，相對開盤）。原文未定量，推論。
    high_lookback: int = 20  # C1：A之高點須為近N根（含本身）新高，判定「高檔區域」。原文未定量，推論。
    rally_lookback: int = 10  # C1：累計漲幅回顧根數。原文未定量，推論。
    rally_min_pct: float = 10.0  # C1：回顧期間累計漲幅門檻（%）。原文未定量，推論。
    gap_up_max_pct: float = 3.0  # C2：隔日跳高開盤幅度上限（%，相對A收盤）。明文"通常3%以內"（p.9）。
    vol_ma_period: int = 20  # C4：爆量比較基準均量週期（僅供meta記錄，不濾除訊號）。推論。
    vol_spike_ratio: float = 2.0  # C4：爆量門檻倍率（僅供meta記錄）。推論，保守。


@dataclass
class _Candidate:
    a_idx: int
    cover_idx: int
    cover_high: float  # B的最高點
    a_low: float


def _is_long_red(b: pd.Series, pct: float) -> bool:
    o, c = float(b["open"]), float(b["close"])
    return c > o and o != 0 and (c - o) / abs(o) * 100.0 >= pct


class DarkCloudCover(Strategy):
    method_id = METHOD_ID
    intraday = False  # 波段反轉型態，非當沖方法（p.16–20 範例為日線）

    def __init__(self, **kw) -> None:
        self.p = Params(**kw)
        self._cand: _Candidate | None = None

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["roll_high"] = df["high"].rolling(self.p.high_lookback, min_periods=self.p.high_lookback).max()
        df["vol_ma"] = sma(df["volume"], self.p.vol_ma_period)
        return df

    def _volume_spike(self, df: pd.DataFrame, idx: int) -> bool:
        vm = df.at[idx, "vol_ma"]
        return bool(not pd.isna(vm) and vm > 0 and df.at[idx, "volume"] >= vm * self.p.vol_spike_ratio)

    def _try_form_candidate(self, df: pd.DataFrame, i: int) -> None:
        """第 i 根為覆蓋線B候選，檢查前一根A是否構成C1–C3，成立則（重新）設定候選。"""
        p = self.p
        if i < 1:
            return
        a_idx = i - 1
        a, b = df.iloc[a_idx], df.iloc[i]
        if not _is_long_red(a, p.long_candle_min_pct):
            return
        roll_high = df.at[a_idx, "roll_high"]
        if pd.isna(roll_high) or a["high"] < roll_high:
            return  # C1：A須為近N根新高（高檔區域）
        j = a_idx - p.rally_lookback
        if j < 0:
            return
        base_close = df.at[j, "close"]
        if base_close <= 0 or (a["close"] - base_close) / base_close * 100.0 < p.rally_min_pct:
            return  # C1：累計漲幅
        a_close = float(a["close"])
        gap_pct = (float(b["open"]) - a_close) / a_close * 100.0 if a_close else -1.0
        if not (0.0 < gap_pct <= p.gap_up_max_pct):
            return  # C2：跳高開盤幅度
        mid = (float(a["open"]) + a_close) / 2.0
        if float(b["close"]) >= mid:
            return  # C3：收盤須反跌至A實體中點以下
        self._cand = _Candidate(a_idx, i, float(b["high"]), float(a["low"]))

    def on_bar(self, ctx: Context):
        df, i = ctx.df, ctx.i
        order: Order | None = None
        c = self._cand
        if c is not None and i > c.cover_idx:
            close_ = float(df.at[i, "close"])
            spike = self._volume_spike(df, c.cover_idx) or self._volume_spike(df, c.a_idx)
            if close_ > c.cover_high:  # Cr2：反軋買點
                order = Order.enter(Side.LONG, stop=float(df.at[i, "low"]), reason="反軋買點",
                                     a_i=c.a_idx, cover_i=c.cover_idx, vol_spike=spike)
                self._cand = None
            elif close_ < c.a_low:  # C5：轉空確認
                if ctx.pos is not None and ctx.pos.side == Side.LONG:
                    order = Order.exit("覆蓋線反轉(多單出場)")
                self._cand = None

        self._try_form_candidate(df, i)
        return [order] if order is not None else None
