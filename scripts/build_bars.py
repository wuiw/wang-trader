"""由 tick db 聚合好的日盤 1 分 K（data/tx_day_1min.csv）合成 1/3/5 分 K 並做基本檢查。

來源：../tick-db 的 TimescaleDB `txf_ticks`（TXFR1 連續月），台北時間 = ts(UTC) − 8h，
日盤 08:45–13:45，13:45 收盤撮合併入 13:44 那根。K 棒時間標籤＝該根開盤時刻。
"""

from pathlib import Path

import pandas as pd

DATA = Path(__file__).resolve().parents[1] / "data"


def main() -> None:
    df = pd.read_csv(DATA / "tx_day_1min.csv", parse_dates=["time"]).set_index("time")
    df = df[df.index.dayofweek < 5]  # 排除週六髒資料
    day = df.index.normalize()
    per_day = df.groupby(day).size()
    raw_days = per_day.index
    settle = {d for d in raw_days if d.dayofweek == 2 and 15 <= d.day <= 21}  # 第三個週三（結算日，13:30 收盤）
    keep = [d for d, n in per_day.items() if n >= 299 or (d in settle and n >= 280)]
    dropped = raw_days.difference(keep)
    print(f"交易日 {len(raw_days)}，保留 {len(keep)}，剔除 {len(dropped)}（根數不足：連續月混入次月合約、資料缺漏）：",
          ", ".join(str(d.date()) for d in dropped))
    # 平盤/昨高/昨低無效的交易日：前一日是結算日（TXFR1 換月，基差跳動）、與前一保留日相隔 > 4 天
    # （資料缺漏）、或中間有被剔除的日子。
    invalid = set()
    for prev, cur in zip(keep, keep[1:]):
        if prev in settle or (cur - prev).days > 4 or ((dropped > prev) & (dropped < cur)).any():
            invalid.add(cur)
    print(f"平盤/昨高低標為無效的交易日 {len(invalid)} 天")
    df = df[day.isin(keep)]
    df["prev_valid"] = ~df.index.normalize().isin(list(invalid))
    for n in (1, 3, 5):
        if n == 1:
            out = df.drop(columns="ticks")
        else:
            out = df.resample(f"{n}min", origin="start_day", offset="8h45min").agg(
                {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum", "prev_valid": "first"}
            ).dropna()
            out["prev_valid"] = out["prev_valid"].astype(bool)
        out.to_parquet(DATA / f"tx_day_{n}min.parquet")
        print(f"{n} 分K：{len(out)} 根，{out.index.min()} ～ {out.index.max()}")


if __name__ == "__main__":
    main()
