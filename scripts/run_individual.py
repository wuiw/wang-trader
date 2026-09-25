"""第一階段：每個方法單獨在 1/3/5 分K（台指期日盤）上以預設參數回測。

輸出：
  results/individual/summary.csv       方法 × 週期 的績效摘要
  results/individual/trades.parquet    全部交易明細
用法：uv run python scripts/run_individual.py [--cost 2] [--methods q3_01,q2_06_03] [--tf 1,3,5]
"""

from __future__ import annotations

import argparse
import importlib
import inspect
import pkgutil
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

import wangtrader.methods as M
from wangtrader.core import Strategy, run

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT = ROOT / "results" / "individual"


def strategy_classes() -> dict[str, type[Strategy]]:
    out = {}
    for m in pkgutil.iter_modules(M.__path__):
        mod = importlib.import_module(f"wangtrader.methods.{m.name}")
        for _, c in inspect.getmembers(mod, inspect.isclass):
            if issubclass(c, Strategy) and c is not Strategy and c.__module__ == mod.__name__:
                out[m.name] = c
    return dict(sorted(out.items()))


def metrics(tr: pd.DataFrame, cost: float, days: int) -> dict:
    if tr.empty:
        return {"trades": 0}
    pnl = tr["pnl"].to_numpy()
    net = pnl - cost
    eq = np.cumsum(net)
    dd = float((np.maximum.accumulate(np.concatenate([[0], eq]))[1:] - eq).max())
    wins, losses = net[net > 0], net[net <= 0]
    return {
        "trades": len(tr),
        "trades_per_day": len(tr) / days,
        "win_rate": float((net > 0).mean()),
        "gross_points": float(pnl.sum()),
        "net_points": float(net.sum()),
        "avg_net": float(net.mean()),
        "profit_factor": float(wins.sum() / -losses.sum()) if losses.sum() < 0 else np.inf,
        "max_drawdown": dd,
        "avg_bars_held": float((tr["exit_i"] - tr["entry_i"]).mean()),
        "long_share": float((tr["side"] == 1).mean()),
    }


# 依回測週期傳入的參數（方法模組本身不綁週期）：q2-04-01 書中用 15 分鐘 KD 判斷大方向，
# htf_bars 是「幾根小週期合成一根大週期」，所以 1/3/5 分K 分別用 15/5/3，讓大週期都等於 15 分鐘。
def tf_kwargs(name: str, tf: int) -> dict:
    if name == "q2_04_01_cross_kd_n_type":
        return {"htf_bars": max(1, 15 // tf)}
    return {}


def one(args):
    name, tf, cost = args
    cls = strategy_classes()[name]
    df = pd.read_parquet(DATA / f"tx_day_{tf}min.parquet")
    t0 = time.time()
    try:
        strat = cls(**tf_kwargs(name, tf))
        strat.enter_on_last_bar = False  # 最後一根收盤不建立新部位（避免進場即收盤平倉的零損益假交易）
        res = run(strat, df)
    except Exception as e:  # 記錄錯誤，不中斷其他組合
        return {"method": name, "tf": tf, "error": f"{type(e).__name__}: {e}"}, None
    tr = pd.DataFrame([{
        "side": int(t.side), "entry_i": t.entry_i, "exit_i": t.exit_i,
        "entry_time": res.df.at[t.entry_i, "time"], "exit_time": res.df.at[t.exit_i, "time"],
        "entry_price": t.entry_price, "exit_price": t.exit_price, "pnl": t.pnl,
        "reason_in": t.reason_in, "reason_out": t.reason_out,
    } for t in res.trades])
    days = res.df["session"].nunique()
    row = {"method": name, "tf": tf, "signals": len(res.signals), **metrics(tr, cost, days),
           "seconds": round(time.time() - t0, 1)}
    if not tr.empty:
        tr.insert(0, "tf", tf)
        tr.insert(0, "method", name)
    return row, tr


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cost", type=float, default=0.0, help="每筆來回成本（點）；預設 0，不計滑價、稅金、手續費")
    ap.add_argument("--methods", default="")
    ap.add_argument("--tf", default="1,3,5")
    a = ap.parse_args()
    names = [n for n in strategy_classes() if not a.methods or any(n.startswith(m) for m in a.methods.split(","))]
    jobs = [(n, int(tf), a.cost) for n in names for tf in a.tf.split(",")]
    OUT.mkdir(parents=True, exist_ok=True)
    rows, trades = [], []
    with ProcessPoolExecutor() as ex:
        for row, tr in ex.map(one, jobs):
            rows.append(row)
            if tr is not None and not tr.empty:
                trades.append(tr)
            print(row.get("method"), row.get("tf"), row.get("error") or f"{row.get('trades')} trades, net {row.get('net_points', 0):.0f}", flush=True)
    pd.DataFrame(rows).to_csv(OUT / "summary.csv", index=False)
    if trades:
        pd.concat(trades).to_parquet(OUT / "trades.parquet")


if __name__ == "__main__":
    main()
