"""sg-05 內困買訊／內困空訊（讀書會整理，書外方法）。

規格文件：methods/讀書會/sg-05-內困買訊空訊.md
整理來源：extracted/study-group/newmethods/內困.md（作者定義原文不在下載資料中，以下依助教說明、學員上課筆記與實例圖）

訊號：
  首根：某根K棒的高點～低點構成區間；其後各根K棒的最高、最低都不超出此區間（被「困」住，含等於）。
  內困買訊：含首根被框住的K棒數在 min_boxed_bars～max_boxed_bars 之間，下一根收盤高於首根高點 → 當根收盤買進。
  內困空訊：鏡像，收盤低於首根低點 → 當根收盤放空。
  - 含首根至少 3 根（學員上課筆記 2019-08-29 post 496345524511547；助教「我是抓至少3根的內困區間」
    2021-04-20 post 927353921410703）。
  - 含首根最多 5 根、第 6 根突破（同一學員上課筆記）；助教實例常超過（2018-05-16 約 8 根、2019-05-06 約 10 根），
    做成參數 max_boxed_bars，None＝不設上限。
  - 首根高低差 ≤10 點（學員筆記 2019-08-29「首根K線長度為13，大於10」判定非內困；助教 2018-10-25
    post 738492329832017「原先限制上下10點」）；大行情「放大版」沒有量化門檻，參數 max_first_range 可放寬、None＝不限。
  - 位置：買訊的首根低點距當下盤中最低 ≤10 點、空訊的首根高點距盤中最高 ≤10 點（學員轉述老師說法
    2021-04-20 post 927353921410703；助教同意該例不算內困）。部分助教實例不符，參數 near_extreme_points，None＝不檢查。
  - 同一根可對應多個首根時，取最早（框住最多根）的那個。
停損：進場價 ∓ 20 點固定（助教 2018-11-13 post 748528852161698「最大停損20點不變」、2018-11-21
  post 753275555020361「雖然是放大版, 但停損抓20點不變」、2018-03-23 post 597500737264511）。
出場：原文沒有統一規則（推論）：不設停利，持有至停損、反向訊號（引擎先平倉再反手）或收盤。
未實作：助教 2019-05-15「開與昨收小於10，所以才有內困買訊」語意不明；尾盤 13:00 後忽略是對所有訊號的通則。

週期：不限。所有門檻以點數／根數表示。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from wangtrader.core import Context, Order, Side, Strategy

METHOD_ID = "sg-05"


@dataclass
class Params:
    min_boxed_bars: int = 3  # 含首根至少 3 根（學員上課筆記 2019-08-29；助教 2021-04-20）
    max_boxed_bars: int | None = 5  # 含首根最多 5 根（學員上課筆記 2019-08-29）；助教實例常超過，None＝不限
    max_first_range: float | None = 10.0  # 首根高低差上限（點）；「放大版」無量化門檻，None＝不限
    near_extreme_points: float | None = 10.0  # 首根距盤中最低（買）／最高（空）上限（點，學員轉述 2021-04-20）；None＝不檢查
    stop_points: float = 20.0  # 固定停損（助教 2018-11-13、2018-11-21，放大版不變）
    enable_short: bool = True  # 內困空訊（助教多篇實例）


def detect(df: pd.DataFrame, p: Params) -> tuple[np.ndarray, np.ndarray]:
    """回傳 (sig, first)：sig[i]＝1 買訊／−1 空訊／0；first[i]＝首根 index（無訊號為 −1）。只用 0..i 的資料。"""
    h = df["high"].to_numpy(float)
    lo = df["low"].to_numpy(float)
    c = df["close"].to_numpy(float)
    sess = df["session"].to_numpy()
    sh = df["sess_high"].to_numpy(float)
    sl = df["sess_low"].to_numpy(float)
    n = len(df)
    sig = np.zeros(n, dtype=int)
    first = np.full(n, -1, dtype=int)
    for i in range(1, n):
        inner_hi, inner_lo = -np.inf, np.inf
        f = i - 1
        while f >= 0 and sess[f] == sess[i]:
            if f < i - 1:  # 被框住的K棒：f+1..i-1
                inner_hi = max(inner_hi, h[f + 1])
                inner_lo = min(inner_lo, lo[f + 1])
            cnt = i - f  # 含首根被框住的根數
            if p.max_boxed_bars is not None and cnt > p.max_boxed_bars:
                break
            if p.max_first_range is not None and inner_hi - inner_lo > p.max_first_range:
                break  # 更早的首根也不可能在幅度上限內框住它們
            if (
                cnt >= p.min_boxed_bars
                and inner_hi <= h[f]
                and inner_lo >= lo[f]
                and (p.max_first_range is None or h[f] - lo[f] <= p.max_first_range)
            ):
                near = p.near_extreme_points
                if c[i] > h[f] and (near is None or lo[f] - sl[i - 1] <= near):
                    sig[i], first[i] = 1, f
                elif p.enable_short and c[i] < lo[f] and (near is None or sh[i - 1] - h[f] <= near):
                    sig[i], first[i] = -1, f
            f -= 1
    return sig, first


class InsideBox(Strategy):
    method_id = METHOD_ID

    def __init__(self, **kw) -> None:
        self.p = Params(**kw)

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        sig, first = detect(df, self.p)
        df["ib_sig"] = sig
        df["ib_first"] = first
        return df

    def on_bar(self, ctx: Context):
        df, i = ctx.df, ctx.i
        s = int(df.at[i, "ib_sig"])
        if s == 0:
            return None
        side = Side.LONG if s > 0 else Side.SHORT
        entry = float(df.at[i, "close"])
        stop = entry - self.p.stop_points if side == Side.LONG else entry + self.p.stop_points
        f = int(df.at[i, "ib_first"])
        name = "內困買訊" if side == Side.LONG else "內困空訊"
        return [Order.enter(side, stop=stop, reason=name, first_i=f, boxed_bars=i - f)]
