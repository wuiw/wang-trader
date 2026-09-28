"""把 ../tick-db/kbars_1min.csv 換算成台北日盤 1 分 K（data/tx_day_1min.csv），供 build_bars.py 使用。

kbars_1min.csv 的時間欄＝台北時間＋16 小時，且標的是該根 K 棒的收盤時刻。換算：
  1. 減 16 小時得台北時間，再減 1 分鐘，改標成該根的開盤時刻（與 build_bars.py 的慣例一致）。
  2. 只取日盤 08:45～13:44。
  3. 排除週六、日（kbars 中偶有零星的週六髒資料）。
  4. 結算日（每月第三個週三，外加 2026-02-23 順延結算日）13:30 收盤，刪除 13:30 以後的 K 棒。
輸出欄位 time,open,high,low,close,volume,ticks（ticks 填 0）。

用法：uv run python scripts/kbars_to_day_csv.py [--src ../tick-db/kbars_1min.csv] [--out data/tx_day_1min.csv]
之後跑 uv run python scripts/build_bars.py 重建 data/tx_day_{1,3,5}min.parquet。
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
EXTRA_SETTLE = {pd.Timestamp("2026-02-23")}  # 順延結算日


def is_settle(day: pd.Series) -> pd.Series:
    third_wed = (day.dt.dayofweek == 2) & day.dt.day.between(15, 21)
    return third_wed | day.isin(EXTRA_SETTLE)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=str(ROOT.parent / "tick-db" / "kbars_1min.csv"))
    ap.add_argument("--out", default=str(ROOT / "data" / "tx_day_1min.csv"))
    args = ap.parse_args()

    k = pd.read_csv(args.src, parse_dates=["time"])
    k["time"] = k["time"] - pd.Timedelta(hours=16) - pd.Timedelta(minutes=1)
    hm = k["time"].dt.hour * 60 + k["time"].dt.minute
    k = k[(hm >= 8 * 60 + 45) & (hm <= 13 * 60 + 44) & (k["time"].dt.dayofweek < 5)]
    hm = hm.loc[k.index]
    settle = is_settle(k["time"].dt.normalize())
    k = k[~(settle & (hm >= 13 * 60 + 30))]
    out = k[["time", "open", "high", "low", "close", "volume"]].sort_values("time").copy()
    out["ticks"] = 0
    out.to_csv(args.out, index=False)
    print(f"{len(out)} 根，{out['time'].min()} ～ {out['time'].max()}，{out['time'].dt.normalize().nunique()} 日 → {args.out}")


if __name__ == "__main__":
    main()
