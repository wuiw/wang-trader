"""gq-02-06 KD 提前買點（均線多排，K值走低轉折向上，收陽線買進）
（《股技期招》第二章第五節之二，p.128–134）。

規格文件：methods/股技期招/gq-02-06-KD提前買點-均線多排K值轉折向上.md

本方法原文以個股/陸股日線為例。趨勢判斷（原文「均線多頭排列（多排）」未指定具體均線週期，
本模組以快慢均線 trend_fast/trend_slow（推論預設5/20）交叉近似：fast_ma>slow_ma 視為多排）。

訊號（p.129）：
  C1 均線呈多頭排列（fast_ma>slow_ma）。
  C2 KD 的 K 值下滑，跌破 k_threshold（預設50）。
  C3 K值出現向上轉折（今日K > 昨日K）；require_prior_decline=True（預設，推論）時另要求
     昨日K <= 前日K，確保昨日確實仍處於下滑段、今日才是真正的轉折點（原文「K值出現向上轉折」
     之字面定義本模組如此近似，屬推論）。
  C4 轉折當天K線收陽線（收盤>開盤）。
  特例（p.129）：若轉折當天同時形成KD金叉，提前買訊與傳統金叉買訊同步出現；本模組不特別
     標記此特例，兩套訊號各自獨立運作（本模組僅實作提前買訊本身）。

進場（p.129，依停損敘述反推，推論）：C1+C2+C3+C4 成立之訊號K線，當根收盤進場。

停損（p.129–130）：
  stop_mode="tick"（預設）：進場當根K線真實低點（K線低點與前一根收盤孰低）下方一檔
    （stop_tick，原文未量化，推論預設1.0）。
  stop_mode="pct"：固定 stop_pct（預設7%，p.130）。
  「谷點下方一檔」（若距谷點幅度不大）之替代停損，因需另行辨識「谷點」且原文未給明確判斷
    準則（「距離谷點幅度不大」未量化），本模組未實作（見模組尾端待確認事項）。

出場：原文未規定固定停利；書中特別提醒牛市中高檔KD死叉不宜作為出場訊號（應忽略），
  本模組不實作任何以KD死叉為出場的規則，僅靠停損出場。

過濾（p.129, 131）：
  F1 K值若在 k_threshold 之上形成向上轉折，不適用（已由 C2 的「K值先跌破50」要求自然達成）。
  F2 均線僅緩步上揚或橫向游走的牛皮股不適用：原文未提供可量化的「角度」門檻，本模組不實作。
  F3 同一位階多次訊號僅擇一：原文未提供可量化的「同位階」容忍範圍（僅定性描述），本模組不實作
     （註：gq-02-04 的同位階濾網有具體百分比可推論套用，但本節原文未提供對應描述，避免過度
     推論套用不同方法的參數，故不比照）。

週期：不限。k_threshold/stop_pct 為指標數值(0-100)/百分比，不隨價位縮放；stop_tick 比照 q3_01
  慣例不隨價位縮放；trend_fast/trend_slow/kd_n/k_period/d_period 為根數/週期，不隨價位縮放。
  本模組沒有「點數」型參數，不需要加入 scripts/point_params.py 的縮放表。
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from wangtrader.core import Context, Order, Side, Strategy
from wangtrader.core.indicators import kd, sma

METHOD_ID = "gq-02-06"


@dataclass
class Params:
    trend_fast: int = 5  # 原文未指定週期，推論預設
    trend_slow: int = 20  # 原文未指定週期，推論預設
    kd_n: int = 9
    k_period: int = 3
    d_period: int = 3
    k_threshold: float = 50.0  # C2，p.129
    require_prior_decline: bool = True  # C3 轉折確認，原文字面近似，推論
    stop_mode: str = "tick"  # "tick"|"pct"，p.129-130
    stop_tick: float = 1.0  # 原文未量化「一檔」大小，推論預設
    stop_pct: float = 0.07  # p.130


class KdEarlyTurnUp(Strategy):
    method_id = METHOD_ID
    intraday = False  # 波段方法（個股日線多日持有）

    def __init__(self, **kw) -> None:
        self.p = Params(**kw)

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        p = self.p
        df["fast_ma"] = sma(df["close"], p.trend_fast)
        df["slow_ma"] = sma(df["close"], p.trend_slow)
        kdf = kd(df, n=p.kd_n, k_period=p.k_period, d_period=p.d_period)
        df["k"] = kdf["k"]
        return df

    def detect(self, df: pd.DataFrame, i: int) -> bool:
        p = self.p
        if i < 2:
            return False
        f, s = df.at[i, "fast_ma"], df.at[i, "slow_ma"]
        k0, k1, k2 = df.at[i - 2, "k"], df.at[i - 1, "k"], df.at[i, "k"]
        if pd.isna(f) or pd.isna(s) or pd.isna(k0) or pd.isna(k1) or pd.isna(k2):
            return False
        if not (f > s):  # C1
            return False
        if not (k2 <= p.k_threshold):  # C2
            return False
        if not (k2 > k1):  # C3：今日K高於昨日
            return False
        if p.require_prior_decline and not (k1 <= k0):  # 確認昨日仍處下滑段
            return False
        b = df.iloc[i]
        return bool(b["close"] > b["open"])  # C4

    def _stop(self, df: pd.DataFrame, i: int, price: float) -> float:
        p = self.p
        if p.stop_mode == "pct":
            return price * (1 - p.stop_pct)
        prev_close = df.at[i - 1, "close"] if i > 0 else df.at[i, "low"]
        real_low = min(df.at[i, "low"], prev_close)
        return real_low - p.stop_tick

    def on_bar(self, ctx: Context):
        df, i = ctx.df, ctx.i
        if ctx.pos is not None:
            return None  # 出場僅靠停損，原文未規定停利，亦明言不以KD死叉出場
        if not self.detect(df, i):
            return None
        price = float(df.at[i, "close"])
        return [Order.enter(Side.LONG, stop=self._stop(df, i, price), reason="KD提前買點(均線多排K值轉折)")]
