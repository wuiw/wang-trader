"""技術指標。全部為因果計算（第 i 根只用到 0..i 的資料）。"""

from __future__ import annotations

import numpy as np
import pandas as pd


def sma(s: pd.Series, n: int) -> pd.Series:
    """簡單移動平均（MA）。"""
    return s.rolling(n, min_periods=n).mean()


def rsi(close: pd.Series, n: int = 5, method: str = "wilder") -> pd.Series:
    """RSI，0–100。method='wilder'（台灣看盤軟體常用）或 'sma'。"""
    d = close.diff()
    up = d.clip(lower=0)
    dn = (-d).clip(lower=0)
    if method == "wilder":
        au = up.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
        ad = dn.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    elif method == "sma":
        au = up.rolling(n, min_periods=n).mean()
        ad = dn.rolling(n, min_periods=n).mean()
    else:
        raise ValueError(method)
    rs = au / ad
    out = 100 - 100 / (1 + rs)
    out = out.where(ad != 0, 100.0).where(~((au == 0) & (ad == 0)), 50.0)
    return out.where(au.notna())


def kd(df: pd.DataFrame, n: int = 9, k_period: int = 3, d_period: int = 3) -> pd.DataFrame:
    """台灣慣用 KD：RSV(n)，K = K前*(1-1/k_period) + RSV/k_period，D 同理，初值 50。
    回傳欄位 k, d。"""
    hh = df["high"].rolling(n, min_periods=1).max()
    ll = df["low"].rolling(n, min_periods=1).min()
    rng = (hh - ll).replace(0, np.nan)
    rsv = ((df["close"] - ll) / rng * 100).fillna(50.0).to_numpy()
    k = np.empty(len(df))
    d = np.empty(len(df))
    pk = pd_ = 50.0
    for i, v in enumerate(rsv):
        pk = pk * (1 - 1 / k_period) + v / k_period
        pd_ = pd_ * (1 - 1 / d_period) + pk / d_period
        k[i], d[i] = pk, pd_
    return pd.DataFrame({"k": k, "d": d}, index=df.index)


def sar(df: pd.DataFrame, af0: float = 0.02, step: float = 0.02, af_max: float = 0.2) -> pd.DataFrame:
    """拋物線轉向指標 SAR。回傳欄位 sar（價位）、trend（1 多 / -1 空）。"""
    h = df["high"].to_numpy(float)
    lo = df["low"].to_numpy(float)
    n = len(df)
    out = np.full(n, np.nan)
    tr = np.zeros(n, dtype=int)
    if n < 2:
        return pd.DataFrame({"sar": out, "trend": tr}, index=df.index)
    up = df["close"].iloc[1] >= df["close"].iloc[0]
    ep = h[0] if up else lo[0]
    s = lo[0] if up else h[0]
    af = af0
    for i in range(1, n):
        s = s + af * (ep - s)
        if up:
            s = min(s, lo[i - 1], lo[i - 2] if i >= 2 else lo[i - 1])
            if lo[i] < s:
                up, s, ep, af = False, ep, lo[i], af0
            elif h[i] > ep:
                ep, af = h[i], min(af + step, af_max)
        else:
            s = max(s, h[i - 1], h[i - 2] if i >= 2 else h[i - 1])
            if h[i] > s:
                up, s, ep, af = True, ep, h[i], af0
            elif lo[i] < ep:
                ep, af = lo[i], min(af + step, af_max)
        out[i] = s
        tr[i] = 1 if up else -1
    return pd.DataFrame({"sar": out, "trend": tr}, index=df.index)
