"""K 線資料格式與盤中欄位。

所有方法共用同一種輸入：以時間排序的 OHLCV DataFrame，任何週期（1 分、5 分、30 分……）皆可。
方法模組只看「第幾根 K 線」與「點數」，不假設週期。
"""

from __future__ import annotations

import pandas as pd

REQUIRED = ("open", "high", "low", "close")


def prepare(df: pd.DataFrame, session_col: str | None = "session") -> pd.DataFrame:
    """驗證欄位並加上盤中（session）衍生欄位，回傳新的 DataFrame（RangeIndex）。

    輸入欄位：open, high, low, close，可選 volume。原本的 index（通常是時間）保留在 `time` 欄。
    session：交易日分段。若 df 有 `session_col` 欄就直接用；否則以 index 的日期分段
    （台指夜盤跨午夜時，請自行提供 session 欄）。

    新增欄位（全部只用到當下及之前的資料，不會偷看未來）：
      session       交易日編號（0, 1, 2 ...）
      bar_no        本交易日第幾根（0 = 開盤第一根）
      prev_close    平盤＝前一交易日最後一根收盤（第一個交易日為 NaN）
      prev_high     昨高；prev_low 昨低
      sess_open     今開（本交易日第一根開盤）
      sess_high     當下盤中最高（含本根）；sess_low 當下盤中最低
    若輸入有 `prev_valid` 欄（False = 前一日價格不可信，例如換月、資料缺漏），
    該交易日的 prev_close/prev_high/prev_low 設為 NaN。
    """
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(f"缺少欄位: {missing}")
    out = df.copy()
    if "volume" not in out.columns:
        out["volume"] = 0.0
    if session_col and session_col in out.columns:
        key = out[session_col]
    else:
        idx = out.index
        if not isinstance(idx, pd.DatetimeIndex):
            raise ValueError("沒有 session 欄時，index 必須是 DatetimeIndex")
        key = pd.Series(idx.date, index=idx)
    out["time"] = out.index
    out = out.reset_index(drop=True)
    key = pd.Series(pd.factorize(pd.Series(list(key)))[0], index=out.index)
    out["session"] = key
    g = out.groupby("session", sort=False)
    out["bar_no"] = g.cumcount()
    out["sess_open"] = g["open"].transform("first")
    out["sess_high"] = g["high"].cummax()
    out["sess_low"] = g["low"].cummin()
    last = g.agg(close=("close", "last"), high=("high", "max"), low=("low", "min"))
    prev = last.shift(1)
    out["prev_close"] = out["session"].map(prev["close"])
    out["prev_high"] = out["session"].map(prev["high"])
    out["prev_low"] = out["session"].map(prev["low"])
    if "prev_valid" in out.columns:  # 資料標記平盤不可信（換月、資料缺漏）→ 設為 NaN
        bad = ~out["prev_valid"].astype(bool)
        out.loc[bad, ["prev_close", "prev_high", "prev_low"]] = float("nan")
    return out


def is_red(df: pd.DataFrame) -> pd.Series:
    """紅K：收盤 > 開盤。"""
    return df["close"] > df["open"]


def is_black(df: pd.DataFrame) -> pd.Series:
    """黑K：收盤 < 開盤。"""
    return df["close"] < df["open"]


def body(df: pd.DataFrame) -> pd.Series:
    """實體長度（點）。"""
    return (df["close"] - df["open"]).abs()


def upper_shadow(df: pd.DataFrame) -> pd.Series:
    return df["high"] - df[["open", "close"]].max(axis=1)


def lower_shadow(df: pd.DataFrame) -> pd.Series:
    return df[["open", "close"]].min(axis=1) - df["low"]


def is_extreme_position(
    df: pd.DataFrame, i: int, min_range: float = 30.0, min_from_prev_close: float = 40.0
) -> bool:
    """極端位置（q3-01/q3-02 定義）：當下盤中震幅 ≥ min_range，
    或震幅不足時，當下盤中最高/最低距平盤 ≥ min_from_prev_close。"""
    r = df.at[i, "sess_high"] - df.at[i, "sess_low"]
    if r >= min_range:
        return True
    pc = df.at[i, "prev_close"]
    if pd.isna(pc):
        return False
    return max(df.at[i, "sess_high"] - pc, pc - df.at[i, "sess_low"]) >= min_from_prev_close
