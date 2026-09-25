"""峰谷點（層級轉折點）。

層級 n 峰點：第 j 根的最高點高於左右各 n 根的最高點；谷點同理用最低點。
峰谷點要等右側 n 根走完才確認，所以「在第 i 根時可用的峰谷點」只有 j <= i - n 的那些，
用 `confirmed_*` 系列函式取用，避免偷看未來。
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class Pivot:
    index: int  # 峰谷所在 K 線
    confirm: int  # 確認的 K 線（index + level）
    price: float
    kind: str  # "peak" | "trough"


def find_pivots(df: pd.DataFrame, level: int = 1, strict: bool = True) -> list[Pivot]:
    """找出所有層級 `level` 的峰谷點（依 index 排序）。strict=False 時允許與鄰居等高/等低。"""
    h = df["high"].to_numpy(float)
    lo = df["low"].to_numpy(float)
    n = len(df)
    out: list[Pivot] = []
    for j in range(level, n - level):
        left_h, right_h = h[j - level : j], h[j + 1 : j + 1 + level]
        left_l, right_l = lo[j - level : j], lo[j + 1 : j + 1 + level]
        if strict:
            pk = (h[j] > left_h).all() and (h[j] > right_h).all()
            tg = (lo[j] < left_l).all() and (lo[j] < right_l).all()
        else:
            pk = (h[j] >= left_h).all() and (h[j] >= right_h).all()
            tg = (lo[j] <= left_l).all() and (lo[j] <= right_l).all()
        if pk:
            out.append(Pivot(j, j + level, float(h[j]), "peak"))
        if tg:
            out.append(Pivot(j, j + level, float(lo[j]), "trough"))
    return out


def confirmed_before(pivots: list[Pivot], i: int, kind: str | None = None) -> list[Pivot]:
    """第 i 根收盤時已確認的峰谷點。"""
    return [p for p in pivots if p.confirm <= i and (kind is None or p.kind == kind)]


def last_confirmed(pivots: list[Pivot], i: int, kind: str) -> Pivot | None:
    ps = confirmed_before(pivots, i, kind)
    return ps[-1] if ps else None
