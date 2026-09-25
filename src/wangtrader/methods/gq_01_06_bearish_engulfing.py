"""gq-01-06 陰線吞噬反轉（高檔放空）與吞噬線買點（無爆量／低檔）（《股技期招》第一章，p.21–25）。

規格文件：methods/股技期招/gq-01-06-吞噬線反轉與反軋買點.md

訊號共同構成（吞噬線，p.9, p.21）：前一日（A）長紅K線；隔日（B）跳高開盤（約A最高點上方3%以內），
之後越盤越低，收盤跌破A最低點，黑K實體完全吞噬A實體。依「是否處於高檔」與「是否爆量」分成
兩條互斥路徑（本模組以同一組C1「高檔」判定共用於兩條路徑，見docstring下方參數）：

  3.1 高檔爆量吞噬線（空方，反轉確認）C1–C4：
    C1 A處於高檔（本模組以「近N根新高」＋「N根累計漲幅」量化，推論）。
    C2 B跳高開盤（約A最高點上方engulf_gap_max_pct%以內），收盤跌破A最低點（吞噬構成）。
    C3 須爆量配合（A或B任一，見vol_ma_period/vol_spike_ratio）。
    C4（反轉確認，即放空進場點）後續某根K線收盤跌破吞噬線（B）本身的最低點 → 進場放空
       （p.23「吞噬線反轉組合在高檔區出現，宜掌握賣點，準備伺機放空」，與 gq-01-04/05 不同，
       本節原文明確授權「新開放空部位」）。
    3.2（過濾，非反軋買點）即使此類吞噬線最高點被突破，也不視為反軋買點（p.21–22，極易「突破
       逆轉」），本模組**不**為此路徑實作任何多方訊號，行為已與此一致。

  3.3 無爆量／低檔吞噬線最高點被突破（多方，買進訊號）C1'–C2'：
    C1' 吞噬線出現時**沒有爆量**，且**不**處於C1定義之高檔（本模組以「非高檔」近似「漲勢中途
       或低檔」，見待確認事項）。
    C2' 後續某根K線收盤突破該吞噬線最高點 → 買進。

進場（p.21, 23）：C4成立當根K線收盤進場放空；C2'成立當根K線收盤進場買進。
停損：原文未規定明確的停損點位或點數（與 gq-01-04/05 之反軋買點不同，本節兩種訊號皆無停損規則），
  本模組不發明，`Order.enter(stop=None)`。
出場：書中未明確說明，本模組不實作停利／額外出場。
過濾（p.21–24）：
  F1（=3.2）高檔爆量吞噬線最高點被突破，不視為反軋買點：本模組不實作對應多方訊號。
  F2 沒有爆量的吞噬線出現於非高檔位置，不應視為強烈反轉警訊：即3.3路徑本身只產生買進訊號，
     不產生空方反轉確認，已內建於分流邏輯（is_high 互斥判斷）。
  F3 若吞噬線未達爆量門檻，不應套用3.1邏輯，應改採3.3：已內建於互斥分流。

無法量化之處（原文未定量，預設值為推論，保守設定）：
  「高檔」（C1，含roll_high/rally門檻）、「長紅K線」（A之門檻）、「爆量」，各參數見下方註解。
  「漲勢中途或低檔」原文列出「起漲位置、探底尾端」等定性描述，本模組以「非高檔」近似，
  可能與原文本意有出入（見模組末待確認事項）。

週期：不限。百分比/倍率參數不隨週期或商品縮放；根數(lookback)類參數不縮放。
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from wangtrader.core import Context, Order, Side, Strategy
from wangtrader.core.indicators import sma

METHOD_ID = "gq-01-06"


@dataclass
class Params:
    long_candle_min_pct: float = 3.0  # A「長紅K線」門檻（%，相對開盤）。原文未定量，推論。
    high_lookback: int = 20  # C1：A之高點須為近N根（含本身）新高，判定「高檔」。原文未定量，推論。
    rally_lookback: int = 10  # C1：累計漲幅回顧根數。原文未定量，推論。
    rally_min_pct: float = 10.0  # C1：回顧期間累計漲幅門檻（%）。原文未定量，推論。
    engulf_gap_max_pct: float = 3.0  # C2：B跳高開盤幅度上限（%，相對A最高點）。明文"約3%以內"（p.9,21）。
    vol_ma_period: int = 20  # C3：爆量比較基準均量週期。推論；台指期分K需依實際狀況調整。
    vol_spike_ratio: float = 2.0  # C3：爆量門檻倍率。推論，保守。


@dataclass
class _Candidate:
    side: Side  # SHORT＝3.1路徑（高檔爆量）；LONG＝3.3路徑（無爆量/非高檔）
    a_idx: int
    engulf_idx: int
    level: float  # SHORT：B最低點；LONG：B最高點


def _is_long_red(b: pd.Series, pct: float) -> bool:
    o, c = float(b["open"]), float(b["close"])
    return c > o and o != 0 and (c - o) / abs(o) * 100.0 >= pct


class BearishEngulfing(Strategy):
    method_id = METHOD_ID
    intraday = False  # 波段反轉型態，非當沖方法（p.21–25 範例為日線）

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

    def _is_high(self, df: pd.DataFrame, a_idx: int) -> bool:
        p = self.p
        roll_high = df.at[a_idx, "roll_high"]
        if pd.isna(roll_high) or df.at[a_idx, "high"] < roll_high:
            return False
        j = a_idx - p.rally_lookback
        if j < 0:
            return False
        base_close = df.at[j, "close"]
        if base_close <= 0:
            return False
        return (df.at[a_idx, "close"] - base_close) / base_close * 100.0 >= p.rally_min_pct

    def _try_form_candidate(self, df: pd.DataFrame, i: int) -> None:
        """第 i 根為吞噬線B候選，檢查前一根A是否構成吞噬結構，成立則依高檔/爆量分流設定候選。"""
        p = self.p
        if i < 1:
            return
        a_idx = i - 1
        a, b = df.iloc[a_idx], df.iloc[i]
        if not _is_long_red(a, p.long_candle_min_pct):
            return
        a_high = float(a["high"])
        gap_pct = (float(b["open"]) - a_high) / a_high * 100.0 if a_high else -1.0
        if not (0.0 <= gap_pct <= p.engulf_gap_max_pct):
            return  # C2：跳高開盤幅度
        if float(b["close"]) >= float(a["low"]):
            return  # C2：收盤須跌破A最低點（吞噬構成）
        spike = self._volume_spike(df, a_idx) or self._volume_spike(df, i)
        is_high = self._is_high(df, a_idx)
        if is_high and spike:  # 3.1：高檔爆量吞噬線
            self._cand = _Candidate(Side.SHORT, a_idx, i, float(b["low"]))
        elif not is_high and not spike:  # 3.3：無爆量/非高檔吞噬線
            self._cand = _Candidate(Side.LONG, a_idx, i, float(b["high"]))
        # 其餘組合（高檔但無爆量、非高檔卻爆量）原文未涵蓋，不成立候選。

    def on_bar(self, ctx: Context):
        df, i = ctx.df, ctx.i
        order: Order | None = None
        c = self._cand
        if c is not None and i > c.engulf_idx:
            close_ = float(df.at[i, "close"])
            if c.side == Side.SHORT and close_ < c.level:  # C4：反轉確認，進場放空
                order = Order.enter(Side.SHORT, stop=None, reason="陰線吞噬反轉(空)",
                                     a_i=c.a_idx, engulf_i=c.engulf_idx)
                self._cand = None
            elif c.side == Side.LONG and close_ > c.level:  # C2'：突破吞噬線最高點，買進
                order = Order.enter(Side.LONG, stop=None, reason="吞噬線買點(多)",
                                     a_i=c.a_idx, engulf_i=c.engulf_idx)
                self._cand = None

        self._try_form_candidate(df, i)
        return [order] if order is not None else None
