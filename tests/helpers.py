"""測試用：用簡短描述快速組出 K 線。"""

from __future__ import annotations

import pandas as pd


def make_bars(rows, start="2024-01-02 08:45", freq="5min", prev_day=None) -> pd.DataFrame:
    """rows: [(open, high, low, close), ...] 或含 volume 的五元組。

    prev_day: 若給 (open, high, low, close)，會在前一天放一根 K 線，用來設定平盤（prev_close）、昨高、昨低。
    週期 freq 只影響時間戳，方法本身與週期無關。
    """
    recs = []
    t0 = pd.Timestamp(start)
    if prev_day is not None:
        recs.append((t0 - pd.Timedelta(days=1), *_ohlcv(prev_day)))
    for k, r in enumerate(rows):
        recs.append((t0 + k * pd.Timedelta(freq), *_ohlcv(r)))
    df = pd.DataFrame(recs, columns=["time", "open", "high", "low", "close", "volume"])
    return df.set_index("time")


def _ohlcv(r):
    return (*r, 0.0) if len(r) == 4 else tuple(r)
