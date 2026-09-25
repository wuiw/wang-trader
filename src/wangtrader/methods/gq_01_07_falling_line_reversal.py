"""gq-01-07 下墜線反轉與反軋買點（《股技期招》第一章第二節，p.26-31）。

規格文件：methods/股技期招/gq-01-07-下墜線反轉與反軋買點.md

本方法為波段方法（intraday=False，可跨日持有）。書中範例為個股日K線，程式不綁週期，
以「%」表示長紅K／大跌等門檻維持百分比參數；沒有「漲停」「成交量倍數」等台股專屬硬性數值，
但「高檔位置」「跌勢已發展一段時間」原文皆為主觀圖形判斷、未給量化門檻，本模組以「回溯期最高點
的距離百分比」量化，標「原文未定量，推論」。

訊號（p.26-31）：
  下墜線（C1-C3，p.9, p.26）：前一根 a 為長紅K（實體漲幅 ≥ long_red_body_pct，原文未定量門檻，
    推論預設值）；本根 b 跳低開盤（開盤 < a 收盤）；b 收盤跌破 a 實體中點且跌破 a 最低點。
  高檔位置 / 跌勢中位置（C4 / C1''，p.26, p.30-31）：以 a 高點對照回溯 lookback_bars 根（不含
    a、b）的最高點 roll_high：距 roll_high 在 near_top_pct% 以內 → 視為「高檔」；距 roll_high
    跌幅 ≥ far_from_top_pct% → 視為「跌勢已發展一段時間」；兩者皆不符合則不追蹤（原文未定量，推論，
    p.26「須發生在高檔位置」、p.30-31「跌勢已發展一段時間」）。
  下墜線反轉確認（C5，賣出/出場，僅「高檔」情境，p.26）：下墜線隔一根K線收盤仍為黑K → 反轉事實
    明顯，若持有多單則出場；原文未使用「放空進場」字句，故不開新空單。
  反軋買點（Cr1-Cr2，多方，僅「高檔」情境，p.28-30）：下墜線最高點（a、b 高點孰高）被後續某根K線
    收盤突破 → 買進，停損＝突破K線最低點（p.29-30）。若原下墜線判定為「爆量」（a 成交量 ≥
    volume_lookback 根均量的 surge_volume_multiple 倍，原文未定量，推論），須等突破K線本身成交量
    降到 ≤ 均量的 low_volume_multiple 倍（原文未定量，推論，簡化為以突破K線當根量判斷，非逐日觀察
    萎縮過程）才成立突破。
  跌勢中買點（C3''，多方，僅「跌勢中」情境，p.30-31）：下墜線最高點被後續某根K線收盤突破 → 買進；
    原文未規定此情境的停損，不自行發明，stop=None（不設固定停損，僅能靠反向訊號反手或資料結束平倉）。
出場：書中未明確說明反軋買點與跌勢中買點的停利／出場規則（見 §6），本模組不發明停利規則。
過濾：見上「高檔/跌勢中」判定與爆量量縮判定；未爆量的反轉組合原文建議改用突破思路（即本模組的
  「跌勢中買點」／高檔情境的反軋買點，已涵蓋此精神，不另立規則）。

待確認事項：
  - 「長紅K」「爆量」「高檔位置」「跌勢已發展一段時間」皆為原文未定量的主觀描述，本模組以參數量化，
    預設值屬推論，使用者可依商品特性調整。
  - 跌勢中買點原文未規定停損，本模組不發明，stop=None。
  - 反軋買點/跌勢中買點皆無明確停利規則，原文亦未提及本節之外的出場模式（如 gq-01-12），本模組不
    強加停利。
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from wangtrader.core import Context, Order, Side, Strategy

METHOD_ID = "gq-01-07"


@dataclass
class Params:
    long_red_body_pct: float = 3.0  # 「長紅K」門檻：實體漲幅%（原文未定量，推論預設值，p.9,26）
    lookback_bars: int = 60  # 回溯根數，找近期最高點以判斷高檔/跌勢中（原文未定量，推論）
    near_top_pct: float = 5.0  # 距回溯期最高點在此百分比內 → 高檔位置（原文未定量，推論，p.26 C4）
    far_from_top_pct: float = 15.0  # 距回溯期最高點跌幅超過此百分比 → 跌勢已發展一段時間（原文未定量，推論，p.30-31）
    volume_lookback: int = 20  # 判斷「爆量」的基準期（原文未定量，推論，p.30）
    surge_volume_multiple: float = 2.0  # 長紅K量 ≥ 基準均量之此倍數 → 爆量（原文未定量，推論，p.26,30）
    low_volume_multiple: float = 1.2  # 突破K線量 ≤ 基準均量之此倍數 → 量縮到位（原文未定量，推論，p.30）


class FallingLineReversal(Strategy):
    method_id = METHOD_ID
    intraday = False  # 波段方法，可跨日持有

    def __init__(self, **kw) -> None:
        self.p = Params(**kw)
        self._active: dict | None = None  # 追蹤中的下墜線：falling_high/position/is_surge/base_vol
        self._c5_check_i: int | None = None  # 下墜線隔一根，須檢查是否收黑（C5）

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        p = self.p
        # roll_high_prior[i] = 不含第 i 根，之前 lookback_bars 根的最高點（因果，避免用到自身）
        df["roll_high_prior"] = df["high"].rolling(p.lookback_bars, min_periods=1).max().shift(1)
        # vol_ma_prior[i] = 不含第 i 根，之前 volume_lookback 根的平均量
        df["vol_ma_prior"] = df["volume"].rolling(p.volume_lookback, min_periods=1).mean().shift(1)
        return df

    def _classify_position(self, df: pd.DataFrame, a_idx: int) -> str | None:
        p = self.p
        rh = df.at[a_idx, "roll_high_prior"]
        if pd.isna(rh) or rh <= 0:
            return None
        a_high = float(df.at[a_idx, "high"])
        if a_high >= rh * (1 - p.near_top_pct / 100.0):
            return "high"
        decline = (rh - a_high) / rh * 100.0
        if decline >= p.far_from_top_pct:
            return "downtrend"
        return None

    def _is_surge(self, df: pd.DataFrame, a_idx: int) -> bool:
        base = df.at[a_idx, "vol_ma_prior"]
        if pd.isna(base) or base <= 0:
            return False
        return float(df.at[a_idx, "volume"]) >= base * self.p.surge_volume_multiple

    def _detect(self, df: pd.DataFrame, i: int):
        """判斷第 i 根是否與前一根構成下墜線。回傳 (falling_high, a_idx, position) 或 None。"""
        if i < 1:
            return None
        p = self.p
        a, b = df.iloc[i - 1], df.iloc[i]
        if a["open"] <= 0 or not (a["close"] > a["open"]):
            return None
        body_pct = (a["close"] - a["open"]) / a["open"] * 100.0
        if body_pct < p.long_red_body_pct:  # C1：長紅K（原文未定量門檻）
            return None
        if not (b["open"] < a["close"]):  # C2：跳低開盤
            return None
        mid = (a["open"] + a["close"]) / 2.0
        if not (b["close"] < mid and b["close"] < a["low"]):  # C3：跌破實體中點且跌破最低點
            return None
        position = self._classify_position(df, i - 1)
        if position is None:  # 既非高檔亦非跌勢已久，不追蹤（p.26 反例、原文亦未涵蓋此情境）
            return None
        falling_high = max(float(a["high"]), float(b["high"]))
        return falling_high, i - 1, position

    def on_bar(self, ctx: Context):
        p, df, i = self.p, ctx.df, ctx.i
        b = df.iloc[i]
        orders: list[Order] = []

        # C5：下墜線隔一根收盤是否續黑（僅高檔情境；只在既定的那一根檢查一次）
        if self._c5_check_i == i:
            if b["close"] < b["open"] and ctx.pos is not None and ctx.pos.side == Side.LONG:
                orders.append(Order.exit("下墜線反轉確認出場"))
            self._c5_check_i = None

        # 檢查既有追蹤中的下墜線是否被突破（反軋買點 / 跌勢中買點）
        if self._active is not None:
            act = self._active
            if float(b["close"]) > act["falling_high"]:
                volume_ok = True
                if act["position"] == "high" and act["is_surge"]:
                    base = act["base_vol"]
                    volume_ok = (not pd.isna(base)) and float(b["volume"]) <= base * p.low_volume_multiple
                if volume_ok:
                    if act["position"] == "high":
                        orders.append(Order.enter(Side.LONG, stop=float(b["low"]), reason="反軋買點"))
                    else:
                        orders.append(Order.enter(Side.LONG, stop=None, reason="跌勢中買點(下墜線)"))
                    self._active = None

        # 偵測新的下墜線
        hit = self._detect(df, i)
        if hit is not None:
            falling_high, a_idx, position = hit
            self._active = {
                "falling_high": falling_high,
                "position": position,
                "is_surge": self._is_surge(df, a_idx),
                "base_vol": df.at[a_idx, "vol_ma_prior"],
            }
            if position == "high":
                self._c5_check_i = i + 1

        return orders or None
