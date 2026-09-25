"""gq-04-01 乖離率買點分布（負乖離搶反彈買進法）（《股技期招》第四章第一節，p.165–175）。

規格文件：methods/股技期招/gq-04-01-乖離率買點.md

core/indicators.py 沒有乖離率，本模組私有計算：10日乖離率 = (收盤 - 10日均線) / 10日均線 * 100%
（均線計算沿用 core.indicators.sma，乖離率公式本身為簡單算式，不另立私有指標模組）。

訊號（多，僅有買進規則，p.166）：
### 3.1 濾網型（未背離）
  C1 訊號K線前 search_window 天內，10日乖離率曾 <= bias_threshold（一般股 -12%，績優股多頭中可
     放寬至 -7%，由使用者依商品自行設定，p.166；明確數字）。
  C2a 其後某根K線收盤突破前一天K線最高點。
  C2b C1 隔天直接出現一根接近漲停之K線（不須突破前一天最高點）；「接近漲停」原文未定量，
      near_limit_pct 為推論值（p.167）。
  C_quality （適用C2a/C2b）上影線不宜超過實體長度（require_shadow_ok，p.167）；K線收盤最好落在
      當日高低震幅上3/4以上（close_position_ratio，原文「最好」非必要，預設關閉）；訊號K漲幅最好
      超過3%（require_gain_min，原文「最好」非必要，預設關閉）。
### 3.2 背離型（簡化實作）
  D1 價格第一次出現波段低點，其乖離率 <= bias_threshold（本模組以「乖離率<=閾值期間的最低價」
     近似波段低點，p.170、173）。
  D2 價格其後再破底創新低（收盤價低於D1低點），但乖離率未再 <= bias_threshold（背離）。
  D3 確認背離（跌破D1低點）後，開始依 3.1 節規則尋找C2a/C2b濾網K線。
  D4 背離型買訊最好於最低谷點隔天出現，最晚不超過 search_window 天（p.173，與F1同一參數）。
  例外（p.169）：若第二個波段低點乖離值也 <= bias_threshold，直接視為3.1濾網型（本模組的D1追蹤
  與3.1觸發共用同一狀態，此例外自然成立，不需特別處理）。

進場（p.166–167, 169）：濾網K線收盤時進場。
停損（p.168, 172）：stop_mode="recent_low"（預設，近期最低點：本次搜尋期間追蹤到的最低價）或
  "pct"（固定7%，stop_pct）。停損後是否反手：原文未規定，不實作。
出場：書中未明確說明，不實作任何停利，僅持有至觸價停損或資料結束。

過濾（§7）：
  F1　濾網搜尋逾 search_window 天未出現濾網K線，訊號過期（p.168，明確數字3）。
  F2　（例外，見上）兩個波段低點皆達閾值時不需背離判斷，直接用濾網——本模組狀態機自然滿足。

本方法為單向買進訊號；原文未針對高檔正乖離訂出放空規則，不實作空方（p.166）。
週期：不限。本節書中僅示範個股日線，乖離率百分比門檻理論上可套用於台指期分K，但原文未提供
分時範例佐證其適用性，使用時需自行驗證（docstring 依 CODING_SPEC 要求註明）。
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from wangtrader.core import Context, Order, Side, Strategy
from wangtrader.core.indicators import sma

METHOD_ID = "gq-04-01"


@dataclass
class Params:
    bias_period: int = 10  # 10日乖離率（p.166）
    bias_threshold: float = -12.0  # 一般股臨界值；績優股多頭中可設 -7.0（p.166，明確數字）
    search_window: int = 3  # 濾網搜尋期限（F1/D4，明確數字，p.168, 173）
    near_limit_pct: float = 8.0  # C2b「接近漲停」，原文未定量，預設值為推論（p.167）
    require_shadow_ok: bool = True  # 上影線不宜超過實體長度（p.167）
    close_position_ratio: float | None = None  # 收盤落在震幅上3/4以上，原文「最好」非必要，預設關閉
    require_gain_min: float | None = None  # 訊號K漲幅宜>3%，原文「最好」非必要，預設關閉
    enable_divergence: bool = True  # 3.2節背離型買訊
    stop_mode: str = "recent_low"  # "recent_low" | "pct"
    stop_pct: float = 7.0  # 明確數字（p.168, 172）


class BiasReversalBuy(Strategy):
    method_id = METHOD_ID
    intraday = False

    def __init__(self, **kw) -> None:
        self.p = Params(**kw)
        self._pending: dict | None = None  # {'trigger_i','expire_i','low','divergence'}
        self._d1_low: float | None = None  # 最近一次乖離觸及閾值期間的最低價（D1）
        self._d1_touching: bool = False

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        ma = sma(df["close"], self.p.bias_period)
        df["bias"] = (df["close"] - ma) / ma * 100
        return df

    def _quality_ok(self, b: pd.Series, prev_close: float) -> bool:
        p = self.p
        body = abs(b["close"] - b["open"])
        upper = b["high"] - max(b["open"], b["close"])
        if p.require_shadow_ok and body > 0 and upper > body:
            return False
        if p.require_shadow_ok and body == 0 and upper > 0:
            return False
        if p.close_position_ratio is not None:
            rng = b["high"] - b["low"]
            if rng > 0 and (b["close"] - b["low"]) / rng < p.close_position_ratio:
                return False
        if p.require_gain_min is not None:
            if prev_close <= 0 or (b["close"] - prev_close) / prev_close * 100 < p.require_gain_min:
                return False
        return True

    def _try_filter(self, df: pd.DataFrame, i: int) -> Order | None:
        """檢查第 i 根是否通過 C2a/C2b 濾網（假設目前有 self._pending 搜尋中）。"""
        p = self.p
        st = self._pending
        a, b = df.iloc[i - 1], df.iloc[i]
        c2a = b["close"] > a["high"]
        c2b = (i == st["trigger_i"] + 1) and a["close"] > 0 \
            and (b["close"] - a["close"]) / a["close"] * 100 >= p.near_limit_pct
        if not (c2a or c2b):
            return None
        if not self._quality_ok(b, float(a["close"])):
            return None
        entry = float(b["close"])
        stop = float(st["low"]) if p.stop_mode == "recent_low" else entry * (1 - p.stop_pct / 100)
        reason = "乖離率買點(背離)" if st.get("divergence") else "乖離率買點"
        return Order.enter(Side.LONG, stop=stop, reason=reason)

    def on_bar(self, ctx: Context):
        p, df, i = self.p, ctx.df, ctx.i
        b = df.iloc[i]
        bias = b["bias"]
        order = None

        if not pd.isna(bias):
            touching = bias <= p.bias_threshold
            if touching:
                self._d1_low = float(b["low"]) if self._d1_low is None or not self._d1_touching \
                    else min(self._d1_low, float(b["low"]))
                self._d1_touching = True
                if self._pending is None or not self._pending.get("divergence"):
                    if self._pending is None:
                        self._pending = {"trigger_i": i, "expire_i": i + p.search_window,
                                          "low": float(b["low"]), "divergence": False}
                    else:
                        self._pending["low"] = min(self._pending["low"], float(b["low"]))
                        self._pending["expire_i"] = max(self._pending["expire_i"], i + p.search_window)
            else:
                self._d1_touching = False
                # D2/D3：跌破D1低點且本次未觸及閾值 → 背離確認，開始新的搜尋
                if p.enable_divergence and self._d1_low is not None and float(b["low"]) < self._d1_low \
                        and (self._pending is None or self._pending.get("divergence")):
                    self._pending = {"trigger_i": i, "expire_i": i + p.search_window,
                                      "low": float(b["low"]), "divergence": True}
                    self._d1_low = float(b["low"])  # 新低點成為下一輪比較基準

        if self._pending is not None and i > self._pending["trigger_i"]:
            order = self._try_filter(df, i)
            if order is not None:
                self._pending = None
            elif i >= self._pending["expire_i"]:
                self._pending = None  # F1：逾期未出現濾網K線，訊號過期

        if order is not None and ctx.pos is not None and ctx.pos.side == order.side:
            order = None
        return [order] if order is not None else None
