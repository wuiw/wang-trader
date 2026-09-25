"""第二階段：多個方法合併使用（讀第一階段的交易明細 results/individual/trades.parquet）。

三種合併方式（同一週期內合併）：
  portfolio   投組疊加：每個方法各自一口，獨立運作，損益相加。
  first       單一部位、先到先做：同一時間只持有一口；空手時接受最早出現的訊號，
              持倉中出現同向訊號忽略；出現反向訊號時依 --reverse 決定是否以該訊號價位反手
              （書中「逆向訊號優先」的近似）。
  confirm     共識確認：窗口 --window 根內至少 --k 個不同方法出現同向進場，才在第 k 個訊號進場，
              出場沿用觸發那筆交易的出場（其餘同 first 的單一部位限制）。

方法挑選（避免事後諸葛）：資料切成前後兩半，只用「前半段」（樣本內）績效挑方法
（淨點數 > 0 且 PF >= --min-pf，交易數 >= --min-trades），在「後半段」（樣本外）評估；
另外也報告 `all`（全部方法）作為對照。不計任何交易成本。

輸出：results/combined/<source>/summary.csv、equity_*.csv、corr_*.csv、selection.csv
用法：uv run python scripts/run_combined.py --source individual|scaled
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
# 不納入合併的方法：q3_11 是選擇權買方策略（最大虧損＝權利金），期貨點數無法正確模擬，只看單獨結果
EXCLUDE = {"q3_11_option_swing_breakout"}
# 波段（非當沖）方法：只放進投組疊加（目前唯一的波段方法已在 EXCLUDE）
SWING = {"q3_11_option_swing_breakout"}
OUT = ROOT / "results" / "combined"


def stats(pnl: pd.Series, days: int) -> dict:
    pnl = pnl.astype(float)
    if pnl.empty:
        return {"trades": 0, "net_points": 0.0}
    eq = pnl.cumsum().to_numpy()
    dd = float((np.maximum.accumulate(np.concatenate([[0], eq]))[1:] - eq).max())
    w, l = pnl[pnl > 0].sum(), -pnl[pnl <= 0].sum()
    return {
        "trades": len(pnl), "trades_per_day": len(pnl) / max(days, 1),
        "win_rate": float((pnl > 0).mean()), "net_points": float(pnl.sum()),
        "avg": float(pnl.mean()), "profit_factor": float(w / l) if l > 0 else np.inf,
        "max_drawdown": dd, "return_over_dd": float(pnl.sum() / dd) if dd > 0 else np.inf,
    }


def single_position(tr: pd.DataFrame, reverse: bool) -> pd.DataFrame:
    """先到先做：tr 需依 entry_time 排序。回傳實際成交的交易（pnl 可能因反手被改寫）。"""
    taken = []
    cur = None
    for r in tr.itertuples(index=False):
        if cur is not None and r.entry_time >= cur["exit_time"]:
            taken.append(cur)
            cur = None
        if cur is None:
            cur = r._asdict()
            continue
        if r.side != cur["side"] and reverse and r.entry_time > cur["entry_time"]:
            cur["exit_time"], cur["exit_price"] = r.entry_time, r.entry_price
            cur["pnl"] = (r.entry_price - cur["entry_price"]) * cur["side"]
            cur["reason_out"] = f"反手({r.method})"
            taken.append(cur)
            cur = r._asdict()
    if cur is not None:
        taken.append(cur)
    if not taken:  # 保留欄位，讓後續的 entry_time 篩選在無交易時也能運作
        return tr.iloc[0:0].copy()
    return pd.DataFrame(taken)


def confirm(tr: pd.DataFrame, bars: pd.DatetimeIndex, k: int, window: int) -> pd.DataFrame:
    """共識確認：以 K 棒序號衡量窗口。回傳觸發的交易（再經單一部位限制）。"""
    pos = pd.Series(np.arange(len(bars)), index=bars)
    tr = tr.assign(bar=pos.reindex(tr["entry_time"]).to_numpy())
    keep = []
    for i, r in enumerate(tr.itertuples(index=False)):
        prior = tr.iloc[:i + 1]
        same = prior[(prior["side"] == r.side) & (prior["bar"] >= r.bar - window)]
        if same["method"].nunique() >= k and r.method in same["method"].to_numpy():
            keep.append(i)
    return single_position(tr.iloc[keep].drop(columns="bar"), reverse=False)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-pf", type=float, default=1.1)
    ap.add_argument("--min-trades", type=int, default=20)
    ap.add_argument("--k", type=int, default=2)
    ap.add_argument("--window", type=int, default=3)
    ap.add_argument("--reverse", action=argparse.BooleanOptionalAction, default=True)
    ap.add_argument("--source", choices=["individual", "scaled"], default="individual",
                    help="讀原始版（individual）或價位縮放版（scaled）的交易明細")
    a = ap.parse_args()
    out = OUT / a.source
    out.mkdir(parents=True, exist_ok=True)
    allt = pd.read_parquet(ROOT / "results" / a.source / "trades.parquet")
    rows, sel_rows = [], []
    for tf in sorted(allt["tf"].unique()):
        bars = pd.read_parquet(ROOT / "data" / f"tx_day_{tf}min.parquet").index
        days = pd.Index(bars.normalize().unique())
        split = days[len(days) // 2]
        tr = allt[(allt["tf"] == tf) & ~allt["method"].isin(EXCLUDE)].sort_values(["entry_time", "method"]).reset_index(drop=True)
        ins = tr[tr["entry_time"] < split]
        g = ins.groupby("method")["pnl"]
        perf = pd.DataFrame({"n": g.size(), "net": g.sum(),
                             "pf": g.apply(lambda s: s[s > 0].sum() / max(-s[s <= 0].sum(), 1e-9))})
        chosen = perf[(perf.net > 0) & (perf.pf >= a.min_pf) & (perf.n >= a.min_trades)].index.tolist()
        sel_rows += [{"tf": tf, "method": m, "in_sample_net": perf.at[m, "net"], "in_sample_pf": perf.at[m, "pf"]}
                     for m in chosen]
        for sel_name, methods in (("selected", chosen), ("all", sorted(tr["method"].unique()))):
            sub = tr[tr["method"].isin(methods)]
            # 波段方法（intraday=False，如 q3_11）持倉跨日，只參與投組疊加，不放進單一部位的合併
            intra = sub[~sub["method"].isin(SWING)]
            variants = {
                "portfolio": sub,
                "first": single_position(intra, a.reverse),
                f"confirm_k{a.k}_w{a.window}": confirm(intra, bars, a.k, a.window),
            }
            for mode, t in variants.items():
                for period, lo, hi in (("in_sample", None, split), ("out_of_sample", split, None), ("full", None, None)):
                    m = pd.Series(True, index=t.index)
                    if lo is not None:
                        m &= t["entry_time"] >= lo
                    if hi is not None:
                        m &= t["entry_time"] < hi
                    nd = len(days[(days >= (lo or days[0])) & (days < (hi or days[-1] + pd.Timedelta(days=1)))])
                    rows.append({"tf": tf, "selection": sel_name, "n_methods": len(methods), "mode": mode,
                                 "period": period, **stats(t.loc[m, "pnl"] if len(t) else pd.Series(dtype=float), nd)})
                if sel_name == "selected" and len(t):
                    t.assign(equity=t["pnl"].cumsum())[["entry_time", "method", "side", "pnl", "equity"]] \
                        .to_csv(out / f"equity_{tf}min_{mode}.csv", index=False)
        # 方法之間的日損益相關係數（全部方法）
        daily = tr.assign(day=tr["entry_time"].dt.normalize()).pivot_table(
            index="day", columns="method", values="pnl", aggfunc="sum").fillna(0)
        daily.corr().round(2).to_csv(out / f"corr_{tf}min.csv")
    pd.DataFrame(rows).to_csv(out / "summary.csv", index=False)
    pd.DataFrame(sel_rows).to_csv(out / "selection.csv", index=False)
    print(pd.DataFrame(rows).query("period != 'full'").to_string(index=False))


if __name__ == "__main__":
    main()
