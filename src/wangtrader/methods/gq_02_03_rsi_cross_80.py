"""gq-02-03 RSI 穿越 80（及穿越 50）配合大漲 K 線買點（《股技期招》第二章第三節，p.109–114）。

規格文件：methods/股技期招/gq-02-03-RSI穿越80買點.md

本方法原文以個股日線的強勢股/飆股為例。書中「漲幅超過5%」「大漲K線」為百分比參數，套用於
台指期分K回測時幅度極小、幾乎不會觸發，需另行調高 big_bar_pct 才有意義。RSI 週期原文未指定，
依專案慣用預設5（wilder）沿用，屬推論預設值。

訊號（p.109–110, 113–114）：
  3.1 主要訊號 RSI 穿越 80：
    C1 RSI 前一日 < upper_threshold（預設80）。
    C2 當日 RSI 向上穿越 upper_threshold。
    C3 當日為大漲K線：漲幅 >= big_bar_pct（預設5%）。原文另提「上影線極短，最好收在當日
       最高價」，此為定性描述、原文未定量，本模組不強制檢查（避免自行發明門檻），僅提供可選
       開關 shadow_max_pct（預設 None＝不檢查；設為數值時要求 high-close <= shadow_max_pct*close）。
  3.2 輔助（較早期）訊號 RSI 穿越 50：
    C1' RSI 前一日 < mid_threshold（預設50）。
    C2' 當日 RSI 向上穿越 mid_threshold。
    C3' 同 C3（大漲K線）。
    兩訊號共用同一套進場/停損邏輯，書中以「錯過50才轉用80」描述其銜接關係（p.113–114），
    本模組不強制排他，兩者皆可能於各自時點獨立成立（enable_cross50 控制是否啟用 3.2）。

進場（p.109）：大漲K線當根收盤前進場（本模組以收盤價視同進場價）。

停損（p.109, 111, 113, 114）：以大漲K線真實低點（K線低點與前一根收盤孰低）下方一檔為停損，
  stop_tick 為「一檔」跳動單位，原文未量化其點數大小（隨商品而異），預設1.0（推論，比照
  q3-01「穿越1個跳動單位」慣例）。特殊情況（連續漲停等真實低點失效情境）書中改以「一根停板」
  為停損，此為個股漲跌停限制的特有機制，無法在不限商品/週期的通用K線規則中量化，本模組未實作
  （見模組尾端待確認事項）。

出場：原文未規定固定停利；「只要狀況不對，K線收盤跌破停損位置，跳車快逃」（p.113）＝停損觸發
  即出場，本模組不發明額外停利規則。

過濾（p.109, 111–112）：
  F1 訊號K線非大漲K線（漲幅未達 big_bar_pct，或啟用 shadow_max_pct 時上影線過長）→ 不成立。
  F2「量大不漲、長上影線倒T線/流星線、開高收長黑K、跳空小星線」等超買區警示型態：原文未提供
     可量化定義（不涉及本模組已有欄位如量能門檻），本模組不做成硬性 filter，避免自行發明門檻。

週期：不限。big_bar_pct/upper_threshold/mid_threshold/shadow_max_pct 為百分比或RSI數值(0-100)，
  不隨價位縮放；stop_tick 為「一檔」跳動單位，比照 q3_01 慣例不隨價位縮放。本模組沒有「點數」型
  參數，不需要加入 scripts/point_params.py 的縮放表。
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from wangtrader.core import Context, Order, Side, Strategy
from wangtrader.core.indicators import rsi

METHOD_ID = "gq-02-03"


@dataclass
class Params:
    rsi_period: int = 5  # 原文未指定，依專案慣用預設5（推論）
    rsi_method: str = "wilder"
    upper_threshold: float = 80.0  # C1/C2，p.109-110
    mid_threshold: float = 50.0  # C1'/C2'，p.113-114
    enable_cross50: bool = True  # 是否同時偵測「穿越50」輔助訊號，p.113-114
    big_bar_pct: float = 0.05  # C3/C3'，p.109
    shadow_max_pct: float | None = None  # 選用：上影線占比上限，原文未定量，預設關閉
    stop_tick: float = 1.0  # 真實低點下方一檔，原文未量化「一檔」大小，推論預設1.0


class RsiCross80(Strategy):
    method_id = METHOD_ID
    intraday = False  # 波段方法（個股日線多日持有）

    def __init__(self, **kw) -> None:
        self.p = Params(**kw)

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["rsi"] = rsi(df["close"], self.p.rsi_period, self.p.rsi_method)
        df["pct_chg"] = df["close"].pct_change()
        return df

    def _is_big_bar(self, df: pd.DataFrame, i: int) -> bool:
        p = self.p
        pct = df.at[i, "pct_chg"]
        if pd.isna(pct) or pct < p.big_bar_pct:
            return False
        if p.shadow_max_pct is not None:
            b = df.iloc[i]
            if (b["high"] - b["close"]) > p.shadow_max_pct * b["close"]:
                return False
        return True

    def detect(self, df: pd.DataFrame, i: int) -> str | None:
        """回傳成立的訊號名稱（穿越80／穿越50），皆不成立回傳 None。"""
        p = self.p
        if i < 1:
            return None
        r0, r1 = df.at[i - 1, "rsi"], df.at[i, "rsi"]
        if pd.isna(r0) or pd.isna(r1) or not self._is_big_bar(df, i):
            return None
        if r0 < p.upper_threshold <= r1:
            return "RSI穿越80買點"
        if p.enable_cross50 and r0 < p.mid_threshold <= r1:
            return "RSI穿越50買點"
        return None

    def on_bar(self, ctx: Context):
        p, df, i = self.p, ctx.df, ctx.i
        if ctx.pos is not None:
            return None  # 停損觸發即出場（引擎內建），原文未規定其他停利規則
        reason = self.detect(df, i)
        if reason is None:
            return None
        b = df.iloc[i]
        prev_close = df.at[i - 1, "close"] if i > 0 else b["low"]
        real_low = min(b["low"], prev_close)
        return [Order.enter(Side.LONG, stop=real_low - p.stop_tick, reason=reason)]
