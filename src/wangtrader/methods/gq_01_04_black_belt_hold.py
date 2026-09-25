"""gq-01-04 執帶反轉（黑執帶／會合線）與反軋買點（《股技期招》第一章，p.9–16）。

規格文件：methods/股技期招/gq-01-04-執帶反轉與反軋買點.md

訊號（p.9–12）：
  黑執帶（反轉確認，多單出場）C1–C6：
    C1 前一日（A）為長紅K線，且行情處於連續性上漲（尤其連續漲停）中。
    C2 隔日（B）跳空開高開盤（通常>5%），開盤價即為當日最高價。
    C3 之後走低，以最低點收盤。
    C4 B收盤相對A收盤漲幅<1.5%，但收盤通常不低於A收盤（此即黑執帶構成；若收盤與A收盤同價，
       稱「會合線」，屬執帶延伸型態，本模組以C4「收盤>=A收盤且漲幅<1.5%」已涵蓋同價情形）。
    C5（過濾）須配合爆大量，才視為有效反轉組合。
    C6（反轉確認）後續某根K線收盤跌破A的「真實低點」（A最低點與A之前一日收盤，取其低）
       → 既有多頭部位必須出場。
  反軋買點（多方新倉）Cr1–Cr2：
    Cr1 黑執帶K線（B）已出現且通過C1–C5。
    Cr2 後續某根K線收盤突破B的最高點（＝B之跳空開盤價）→ 反軋買點，進場做多。
進場（p.12）：
  多單出場：C6成立當根K線收盤，既有多頭部位出場（本模組僅在確有多頭部位時送出 Order.exit）。
  放空新倉：原文未明確規定，本模組不發明。
  反軋買點：Cr2成立當根K線收盤進場做多。
停損（p.12）：反軋買點以突破訊號K線（Cr2成立當根）最低點為停損，原文明文，非推論。
  黑執帶反轉確認本身無獨立停損規則，原文未規定。
出場/停利：反軋買點原文未給固定停利，本模組不發明，僅停損；黑執帶多單出場本身即是出場動作。
過濾（p.13–14）：
  F1（=C5）執帶未配合爆大量 → 不成立訊號。
  F2 反轉組合出現在上漲趨勢初期或中途，若均線仍多頭排列且未跌破階梯出場線，不必急於出脫：
     原文為定性判斷語（「不必急於出脫」），無可程式化的量化門檻，本模組不實作，
     於任務回報列為無法實作事項。
  F3 反軋買點後若突破K線本身再出現「突破逆轉」，可靠度打折扣：原文本節未見具體案例，
     本模組不實作（gq-01-06吞噬線一節有明確對應規則，見該模組）。

無法量化之處（原文未定量，預設值為推論，保守設定）：
  「連續性上漲」「長紅K線」「跳空開高即當日最高（容許誤差）」「以最低點收盤（容許誤差）」
  「爆大量」，各自參數見下方註解。「連續漲停」為股票專屬概念，本模組以 limit_up_pct 參數化，
  **預設關閉（None）；台指期分K無漲停機制，不適用，保持關閉或自行調整**。

週期：不限。百分比/倍率參數不隨週期或商品縮放；根數(lookback)類參數不縮放。
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from wangtrader.core import Context, Order, Side, Strategy
from wangtrader.core.indicators import sma

METHOD_ID = "gq-01-04"


@dataclass
class Params:
    long_candle_min_pct: float = 3.0  # C1：A「長紅K線」門檻（%，相對開盤）。原文未定量，推論。
    rally_lookback: int = 10  # C1：「連續性上漲」回顧根數。原文未定量，推論。
    rally_min_pct: float = 10.0  # C1：回顧期間累計漲幅門檻（%）。原文未定量，推論。
    limit_up_pct: float | None = None  # C1：「漲停」股票專屬概念（相對前收漲幅門檻）。
    # 台指期分K無漲停機制，預設關閉；設定時需自行依商品調整。
    consecutive_limit_up_min: int = 0  # 搭配limit_up_pct：A之前連續漲停根數門檻，0＝不檢查。
    gap_up_min_pct: float = 5.0  # C2：隔日跳空開高漲幅門檻（%，相對A收盤）。明文"通常超過5%"（p.9）。
    open_is_high_tolerance_pct: float = 0.1  # C2：判定「開盤即當日最高」的容許誤差（%）。原文未定量，推論。
    close_is_low_tolerance_pct: float = 0.1  # C3：判定「以最低點收盤」的容許誤差（%）。原文未定量，推論。
    belt_max_gain_pct: float = 1.5  # C4：收盤相對A收盤漲幅上限（%）。明文1.5%（p.9）。
    vol_ma_period: int = 20  # C5：爆量比較基準均量週期。推論；台指期分K需依實際狀況調整。
    vol_spike_ratio: float = 2.0  # C5：爆量門檻倍率。推論，保守。


@dataclass
class _Candidate:
    a_idx: int
    belt_idx: int
    belt_high: float  # B的最高點（＝跳空開盤價）
    real_low: float  # A的「真實低點」（A最低點與A之前一日收盤，取其低）


def _is_long_red(b: pd.Series, pct: float) -> bool:
    o, c = float(b["open"]), float(b["close"])
    return c > o and o != 0 and (c - o) / abs(o) * 100.0 >= pct


class BlackBeltHold(Strategy):
    method_id = METHOD_ID
    intraday = False  # 波段反轉型態，非當沖方法（p.9–16 範例為日線）

    def __init__(self, **kw) -> None:
        self.p = Params(**kw)
        self._cand: _Candidate | None = None

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["vol_ma"] = sma(df["volume"], self.p.vol_ma_period)
        return df

    def _volume_spike(self, df: pd.DataFrame, idx: int) -> bool:
        vm = df.at[idx, "vol_ma"]
        return bool(not pd.isna(vm) and vm > 0 and df.at[idx, "volume"] >= vm * self.p.vol_spike_ratio)

    def _consecutive_limit_up_ok(self, df: pd.DataFrame, a_idx: int) -> bool:
        p = self.p
        if p.limit_up_pct is None or p.consecutive_limit_up_min <= 0:
            return True
        n = 0
        idx = a_idx
        while idx >= 0:
            pc = df.at[idx, "prev_close"]
            if pd.isna(pc) or pc <= 0:
                break
            gain = (df.at[idx, "close"] - pc) / pc * 100.0
            if gain < p.limit_up_pct:
                break
            n += 1
            idx -= 1
        return n >= p.consecutive_limit_up_min

    def _try_form_candidate(self, df: pd.DataFrame, i: int) -> None:
        """第 i 根為黑執帶B候選，檢查前一根A是否構成C1–C5，成立則（重新）設定候選。"""
        p = self.p
        if i < 1:
            return
        a_idx = i - 1
        a, b = df.iloc[a_idx], df.iloc[i]
        if not _is_long_red(a, p.long_candle_min_pct):
            return
        j = a_idx - p.rally_lookback
        if j < 0:
            return
        base_close = df.at[j, "close"]
        if base_close <= 0 or (a["close"] - base_close) / base_close * 100.0 < p.rally_min_pct:
            return  # C1：連續性上漲
        if not self._consecutive_limit_up_ok(df, a_idx):
            return  # C1：連續漲停（股票專屬，預設關閉）
        a_close = float(a["close"])
        gap_pct = (float(b["open"]) - a_close) / a_close * 100.0 if a_close else -1.0
        if gap_pct < p.gap_up_min_pct:
            return  # C2：跳空開高幅度
        if (float(b["high"]) - float(b["open"])) > p.open_is_high_tolerance_pct / 100.0 * float(b["open"]):
            return  # C2：開盤須為當日最高
        if (float(b["close"]) - float(b["low"])) > p.close_is_low_tolerance_pct / 100.0 * float(b["low"] or b["open"]):
            return  # C3：以最低點收盤
        belt_gain = (float(b["close"]) - a_close) / a_close * 100.0
        if not (0.0 <= belt_gain < p.belt_max_gain_pct):
            return  # C4
        if not (self._volume_spike(df, a_idx) or self._volume_spike(df, i)):
            return  # C5：爆大量
        prev_close_a = df.at[a_idx, "prev_close"]
        real_low = min(float(a["low"]), float(prev_close_a)) if not pd.isna(prev_close_a) else float(a["low"])
        self._cand = _Candidate(a_idx, i, float(b["high"]), real_low)

    def on_bar(self, ctx: Context):
        df, i = ctx.df, ctx.i
        order: Order | None = None
        c = self._cand
        if c is not None and i > c.belt_idx:
            close_ = float(df.at[i, "close"])
            if close_ > c.belt_high:  # Cr2：反軋買點
                order = Order.enter(Side.LONG, stop=float(df.at[i, "low"]), reason="反軋買點",
                                     a_i=c.a_idx, belt_i=c.belt_idx)
                self._cand = None
            elif close_ < c.real_low:  # C6：反轉確認
                if ctx.pos is not None and ctx.pos.side == Side.LONG:
                    order = Order.exit("執帶反轉(多單出場)")
                self._cand = None

        self._try_form_candidate(df, i)
        return [order] if order is not None else None
