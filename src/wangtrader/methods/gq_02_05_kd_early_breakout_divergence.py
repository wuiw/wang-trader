"""gq-02-05 KD 提前買點（K值走低、K線收紅、隔天過高買進）
（《股技期招》第二章第五節之一，p.121–128）。

規格文件：methods/股技期招/gq-02-05-KD提前買點-K值背離收盤過高.md

本方法原文以個股/陸股日線為例。「回檔逾2成」「量縮」為軟性提醒，非量化過濾條件，原文亦未提供
數值化定義，本模組不實作（避免自行發明門檻），僅在 docstring 註明。

趨勢判斷（原文「均線呈牛市排列」未指定具體均線週期，本模組以快慢均線 trend_fast/trend_slow
（推論預設5/20）交叉近似：fast_ma>slow_ma 視為牛市排列）。

訊號（p.121）：
  C1 均線呈牛市排列（fast_ma>slow_ma）。
  C2 候選K線（第j根）：K值 <= k_threshold（預設50），且該根K線收紅（收盤>開盤，「反漲的陽線」），
     但當天K值仍較前一日低（k[j] < k[j-1]，K線與K值背離）。
  C3 隔天（第j+1根）K線收盤突破候選K線最高點 → 成立提前買訊，於該隔天收盤進場。
     若隔天未突破，候選作廢（原文用語「隔天」，本模組嚴格解讀為僅次一根可確認，不往後展延）。

進場（p.121）：C3 成立當根（候選K線隔天）收盤進場。

停損（p.121, 125）：
  stop_mode="tick"（預設）：進場K線真實低點（K線低點與前一根收盤孰低）下方一檔
    （stop_tick，原文未量化，推論預設1.0）。
  stop_mode="pct"：最大 stop_pct（預設7%）。

出場：原文未規定固定停利（p.126：「行情不對就出場，不必執著於高檔的認定」＝僅靠停損）。

過濾（p.121）：
  F1 K值若在 k_threshold 之上形成向上轉折，不適用（已由 C2 的「K值<=50」要求自然達成）。
  F2/F3 回檔逾2成、量能未縮至前波谷點量附近水準等軟性提醒，原文未量化，未實作。

週期：不限。k_threshold/stop_pct 為指標數值(0-100)/百分比，不隨價位縮放；stop_tick 比照 q3_01
  慣例不隨價位縮放；trend_fast/trend_slow/kd_n/k_period/d_period 為根數/週期，不隨價位縮放。
  本模組沒有「點數」型參數，不需要加入 scripts/point_params.py 的縮放表。
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from wangtrader.core import Context, Order, Side, Strategy
from wangtrader.core.indicators import kd, sma

METHOD_ID = "gq-02-05"


@dataclass
class Params:
    trend_fast: int = 5  # 原文未指定週期，推論預設
    trend_slow: int = 20  # 原文未指定週期，推論預設
    kd_n: int = 9
    k_period: int = 3
    d_period: int = 3
    k_threshold: float = 50.0  # C2，p.121
    stop_mode: str = "tick"  # "tick"|"pct"，p.121, 125
    stop_tick: float = 1.0  # 原文未量化「一檔」大小，推論預設
    stop_pct: float = 0.07  # p.125


class KdEarlyBreakoutDivergence(Strategy):
    method_id = METHOD_ID
    intraday = False  # 波段方法（個股日線多日持有）

    def __init__(self, **kw) -> None:
        self.p = Params(**kw)
        self._candidate: int | None = None  # 候選K線索引

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        p = self.p
        df["fast_ma"] = sma(df["close"], p.trend_fast)
        df["slow_ma"] = sma(df["close"], p.trend_slow)
        kdf = kd(df, n=p.kd_n, k_period=p.k_period, d_period=p.d_period)
        df["k"] = kdf["k"]
        return df

    def _is_candidate(self, df: pd.DataFrame, i: int) -> bool:
        p = self.p
        if i < 1:
            return False
        b = df.iloc[i]
        k0, k1 = df.at[i - 1, "k"], df.at[i, "k"]
        if pd.isna(k0) or pd.isna(k1):
            return False
        return bool(k1 <= p.k_threshold and b["close"] > b["open"] and k1 < k0)

    def _bull(self, df: pd.DataFrame, i: int) -> bool:
        f, s = df.at[i, "fast_ma"], df.at[i, "slow_ma"]
        return bool(pd.notna(f) and pd.notna(s) and f > s)

    def _stop(self, df: pd.DataFrame, i: int, price: float) -> float:
        p = self.p
        if p.stop_mode == "pct":
            return price * (1 - p.stop_pct)
        prev_close = df.at[i - 1, "close"] if i > 0 else df.at[i, "low"]
        real_low = min(df.at[i, "low"], prev_close)
        return real_low - p.stop_tick

    def on_bar(self, ctx: Context):
        df, i = ctx.df, ctx.i
        order = None
        if ctx.pos is None and self._candidate is not None and i == self._candidate + 1:
            high = df.at[self._candidate, "high"]
            if df.at[i, "close"] > high and self._bull(df, i):
                price = float(df.at[i, "close"])
                order = Order.enter(Side.LONG, stop=self._stop(df, i, price), reason="KD提前買點(K值背離過高)")
            self._candidate = None  # 隔天無論是否突破皆作廢，見docstring C3
        if self._is_candidate(df, i):
            self._candidate = i
        return [order] if order else None
