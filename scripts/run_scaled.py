"""第二階段：依「價位等比例縮放」書中點數門檻，與原始（書中固定數值）版本對照。

背景：書中點數門檻（20 點停損、40 點極端位置…）是在台指期約 8,500 點（《期貨奇績2》，q2_*）
與 10,000 點（《期貨奇績3》，q3_*）的年代訂的；本專案回測期間台指期約 22,000→48,000 點。
本腳本額外跑一組「點數門檻依當時價位等比例放大」的版本，與 `run_individual.py`（原始固定門檻）對照。

作法：
  - 依「月份」切段；每段的縮放倍數 = 該月第一根K棒開盤價 / REF_PRICE[書]（q2:8500 / q3:10000），
    只用當時已知（該月第一根K棒）的資料，不偷看未來。
  - 每段用縮放後的參數（見 `point_params.py` 的 POINT_PARAMS 分類）建立新的策略實例來跑；
    為了讓平盤、昨高低、各種指標（MA/RSI/KD…）有暖身，每段往前多帶 N 個交易日（預設5，
    可用 --warmup-days 或 --warmup-override 調整；q3_11 因用到 MA100，建議加大）當暖身，
    暖身期間進場的交易（entry_i 落在暖身區）會被丟棄，只保留「進場時間在當月」的交易。
  - 波段方法（intraday=False，目前僅 q3_11）跨月持倉會被切斷：在每段最後一根K棒若仍有未平倉
    部位，強制以該根收盤價平倉（reason_out="段尾強制平倉"）。這是月切段固有的副作用，
    對長波段的 q3_11 影響最大（見腳本輸出時的提示與最終報告）。
  - cost 預設 0（不計滑價、稅金、手續費），與 run_individual 一致。

輸出：
  results/scaled/summary.csv     方法 × 週期 的績效摘要（與 run_individual 相同欄位＋avg_scale）
  results/scaled/trades.parquet  全部交易明細（與 run_individual 相同欄位＋month/scale）
  results/scaled/compare.csv     方法 × 週期：原始版（讀 results/individual/summary.csv 當下內容）
                                  與縮放版並列的 trades/win_rate/net_points/profit_factor/max_drawdown

用法：
  uv run python scripts/run_scaled.py [--methods q3_01] [--tf 1,3,5] [--warmup-days 5]
      [--warmup-override q3_11_option_swing_breakout=15] [--force-scale 1.0] [--cost 0]
  uv run python scripts/run_scaled.py --compare-only   # 只重建 compare.csv，不重跑回測
"""

from __future__ import annotations

import argparse
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT = ROOT / "results" / "scaled"
INDIVIDUAL_SUMMARY = ROOT / "results" / "individual" / "summary.csv"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_individual import metrics, strategy_classes, tf_kwargs  # noqa: E402

from point_params import POINT_PARAMS, REF_PRICE  # noqa: E402
from wangtrader.core import Order, Strategy, run as engine_run  # noqa: E402

DEFAULT_WARMUP_DAYS = 5
# q3_11 用到 MA100／MA10／RSI 與最長20根的拉回濾網；100根MA在5分K上約需 1.7 個交易日即可
# 完整暖身，但為求穩妥（波段方法本來就該有更長記憶）預設給更多天數。可用 --warmup-override 覆寫。
WARMUP_OVERRIDE_DEFAULT = {"q3_11_option_swing_breakout": 15}


class _CutoffWrapper(Strategy):
    """包住非當沖（intraday=False）策略：段尾（sub_df 最後一根）若仍有未平倉部位，強制平倉。

    只在 run_scaled.py 內使用，不修改任何方法模組或 core/engine.py 本身。
    """

    def __init__(self, inner: Strategy) -> None:
        self.inner = inner
        self.method_id = inner.method_id
        self.intraday = inner.intraday
        self.stop_on_close = inner.stop_on_close
        self.enter_on_last_bar = inner.enter_on_last_bar
        self._n = 0

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        df = self.inner.prepare(df)
        self._n = len(df)
        return df

    def on_bar(self, ctx):
        orders = list(self.inner.on_bar(ctx) or [])
        if ctx.i == self._n - 1 and ctx.pos is not None:
            orders.append(Order.exit(reason="段尾強制平倉"))
        return orders


def _day_bounds(df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """回傳 (day_start_pos, day_end_pos, day_date)：每個交易日在 df 中的 [start,end) 整數位置與日期。"""
    days = np.array(df.index.date)
    change = np.flatnonzero(days[1:] != days[:-1]) + 1
    starts = np.r_[0, change]
    ends = np.r_[change, len(days)]
    dates = days[starts]
    return starts, ends, dates


def _month_key(d) -> tuple[int, int]:
    return (d.year, d.month)


def scaled_kwargs(cls: type[Strategy], name: str, scale: float) -> dict:
    """依 POINT_PARAMS[name] 把預設 Params 中列出的欄位乘上 scale；None 值維持 None。"""
    default_p = cls().p
    fields = POINT_PARAMS.get(name, [])
    kw = {}
    for f in fields:
        v = getattr(default_p, f)
        if v is None:
            continue
        kw[f] = v * scale
    return kw


def build_segments(df: pd.DataFrame, warmup_days: int) -> list[dict]:
    """把整段資料切成「月」段，附上該段（含暖身）在 df 的位置範圍與暖身長度、月首開盤價。"""
    starts, ends, dates = _day_bounds(df)
    n_days = len(dates)
    month_of_day = np.array([_month_key(d) for d in dates])
    uniq_months = sorted(set(map(tuple, month_of_day)))
    segs = []
    for mk in uniq_months:
        day_idx = [k for k in range(n_days) if tuple(month_of_day[k]) == mk]
        first_day, last_day = day_idx[0], day_idx[-1]
        warm_first_day = max(0, first_day - warmup_days)
        seg_start_pos = int(starts[warm_first_day])
        month_start_pos = int(starts[first_day])
        seg_end_pos = int(ends[last_day])
        warmup_bars = month_start_pos - seg_start_pos
        first_open = float(df["open"].iloc[month_start_pos])
        segs.append({
            "month": f"{mk[0]:04d}-{mk[1]:02d}",
            "seg_start_pos": seg_start_pos,
            "seg_end_pos": seg_end_pos,
            "warmup_bars": warmup_bars,
            "warmup_days_used": first_day - warm_first_day,
            "first_open": first_open,
        })
    return segs


def one(args) -> tuple[dict, pd.DataFrame | None]:
    name, tf, cost, warmup_days, force_scale = args
    cls = strategy_classes()[name]
    ref = REF_PRICE["q2"] if name.startswith("q2") else REF_PRICE["q3"]
    df = pd.read_parquet(DATA / f"tx_day_{tf}min.parquet")
    t0 = time.time()
    wd = WARMUP_OVERRIDE_DEFAULT.get(name, warmup_days)
    try:
        segs = build_segments(df, wd)
        all_trades = []
        scales_used = []
        n_signals = 0
        for seg in segs:
            scale = force_scale if force_scale is not None else seg["first_open"] / ref
            scales_used.append(scale)
            sub = df.iloc[seg["seg_start_pos"]:seg["seg_end_pos"]].copy()
            kw = scaled_kwargs(cls, name, scale)
            strat: Strategy = cls(**kw, **tf_kwargs(name, tf))
            strat.enter_on_last_bar = False  # 與 run_individual 一致
            if not strat.intraday:
                strat = _CutoffWrapper(strat)
            res = engine_run(strat, sub)
            wb = seg["warmup_bars"]
            n_signals += sum(1 for s in res.signals if s.i >= wb)
            for t in res.trades:
                if t.entry_i < wb:
                    continue
                all_trades.append({
                    "side": int(t.side), "entry_i": t.entry_i, "exit_i": t.exit_i,
                    "entry_time": res.df.at[t.entry_i, "time"], "exit_time": res.df.at[t.exit_i, "time"],
                    "entry_price": t.entry_price, "exit_price": t.exit_price, "pnl": t.pnl,
                    "reason_in": t.reason_in, "reason_out": t.reason_out,
                    "month": seg["month"], "scale": scale,
                })
    except Exception as e:  # 記錄錯誤，不中斷其他組合
        return {"method": name, "tf": tf, "error": f"{type(e).__name__}: {e}"}, None
    tr = pd.DataFrame(all_trades)
    days_total = len(_day_bounds(df)[2])
    row = {
        "method": name, "tf": tf, "signals": n_signals, **metrics(tr, cost, days_total),
        "avg_scale": float(np.mean(scales_used)) if scales_used else float("nan"),
        "months": len(segs), "warmup_days": wd,
        "seconds": round(time.time() - t0, 1),
    }
    if not tr.empty:
        tr.insert(0, "tf", tf)
        tr.insert(0, "method", name)
    return row, tr


def parse_warmup_override(s: str) -> dict:
    out = dict(WARMUP_OVERRIDE_DEFAULT)
    if not s:
        return out
    for kv in s.split(","):
        k, v = kv.split("=")
        out[k.strip()] = int(v)
    return out


def build_compare(out_dir: Path = OUT, individual_csv: Path = INDIVIDUAL_SUMMARY) -> pd.DataFrame:
    """把 results/individual/summary.csv（原始版，執行當下的檔案內容）與 results/scaled/summary.csv
    （縮放版）依 method×tf 並列，輸出 results/scaled/compare.csv。可重跑（--compare-only）。"""
    orig = pd.read_csv(individual_csv)
    scaled = pd.read_csv(out_dir / "summary.csv")
    cols = ["trades", "win_rate", "net_points", "profit_factor", "max_drawdown"]
    o = orig[["method", "tf"] + cols].rename(columns={c: f"{c}_orig" for c in cols})
    s = scaled[["method", "tf", "avg_scale"] + cols].rename(columns={c: f"{c}_scaled" for c in cols})
    cmp = o.merge(s, on=["method", "tf"], how="outer").sort_values(["method", "tf"])
    cmp["net_points_diff"] = cmp["net_points_scaled"] - cmp["net_points_orig"]
    cmp.to_csv(out_dir / "compare.csv", index=False)
    return cmp


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cost", type=float, default=0.0, help="每筆來回成本（點）；預設 0")
    ap.add_argument("--methods", default="")
    ap.add_argument("--tf", default="1,3,5")
    ap.add_argument("--warmup-days", type=int, default=DEFAULT_WARMUP_DAYS)
    ap.add_argument("--warmup-override", default="", help="name=days,name2=days2")
    ap.add_argument("--force-scale", type=float, default=None,
                     help="驗證用：固定所有月份的縮放倍數（例如 1 代表不縮放）")
    ap.add_argument("--compare-only", action="store_true", help="只重建 compare.csv，不重跑回測")
    a = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    if a.compare_only:
        cmp = build_compare()
        print(f"compare.csv: {len(cmp)} rows -> {OUT / 'compare.csv'}")
        return

    global WARMUP_OVERRIDE_DEFAULT
    WARMUP_OVERRIDE_DEFAULT = parse_warmup_override(a.warmup_override)

    names = [n for n in strategy_classes() if not a.methods or any(n.startswith(m) for m in a.methods.split(","))]
    jobs = [(n, int(tf), a.cost, a.warmup_days, a.force_scale) for n in names for tf in a.tf.split(",")]
    rows, trades = [], []
    with ProcessPoolExecutor() as ex:
        for row, tr in ex.map(one, jobs):
            rows.append(row)
            if tr is not None and not tr.empty:
                trades.append(tr)
            print(row.get("method"), row.get("tf"), row.get("error") or
                  f"{row.get('trades')} trades, net {row.get('net_points', 0):.0f}, "
                  f"avg_scale {row.get('avg_scale', float('nan')):.2f}", flush=True)
    pd.DataFrame(rows).to_csv(OUT / "summary.csv", index=False)
    if trades:
        pd.concat(trades).to_parquet(OUT / "trades.parquet")

    if INDIVIDUAL_SUMMARY.exists():
        cmp = build_compare()
        print(f"compare.csv: {len(cmp)} rows -> {OUT / 'compare.csv'}")
    else:
        print(f"（{INDIVIDUAL_SUMMARY} 不存在，略過 compare.csv；之後可用 --compare-only 補建）")


if __name__ == "__main__":
    main()
