"""方向判斷驗證：事件型（E）——把方法的進出點訊號本身當「方向判斷」評估。

規範：`methods/方向判斷驗證/SPEC.md`；報告：`methods/方向判斷驗證/事件型.md`。

作法：
  - 訊號取自方法 `run()` 的 `res.signals`（i、side、reason），不管方法自己的停損出場。
    `enter_on_last_bar=False` 與 `run_individual.py` 一致；q2-04-01 依週期傳 htf_bars。
  - 原始版：方法預設參數跑整段資料。
    縮放版：照 `run_scaled.py` 的月切段（每段前帶暖身日、暖身期訊號丟棄）與 `point_params.py`
    的欄位、參考價（`ref_price()`，含 sg 各方法個別參考價）縮放。POINT_PARAMS 未登記點數欄位的方法
    不跑縮放（例如 gq_04_03 沒有點數欄位，縮放版等於原始版）。
  - fwd(i, h)：第 i 根收盤後 h 分鐘（K 線開始時間 ≤ t_i + h 的同日最後一根）的收盤價 − 第 i 根收盤；
    超過收盤取當日最後一根收盤。h＝5,10,15,30,45,60,90,120,180,240 分鐘與「到收盤」。
    r = side × fwd；bp = r ÷ 當日開盤價 × 10000。
  - 基準（SPEC）：每個事件在「同一半段、bar_no ±15 分鐘」的K線中隨機抽一根、隨機方向，重複 1000 次，
    得到平均順向 bp 的分布；p_rand＝基準 ≥ 觀察值的比例（單尾，(k+1)/(B+1)）；p_rand_lo 為反向單尾。
    另報「漂移基準」：同樣抽時間點但方向＝事件本身方向（保留多空比例），p_drift 與 excess_bp＝觀察值−漂移基準平均，
    用來看扣掉「這段期間大漲、同時段自然走勢」之後還剩多少。
  - 子集合：多空（全部／多／空）× 半段（全期／前半 2025／後半 2026）× 每日只取第一個事件（否／是）。

輸出（results/direction/）：
  events_signals_{mode}.csv   全部訊號（method, tf, mode, i, time, side, reason, family）
  events_stats.csv            每個 method×tf×mode×family×side×half×first×h 的統計
  events_verdict.csv          每個 method×tf×mode×family 的判定與關鍵數字
  events_horizon.csv          方向有效期（順向 bp 峰值所在 h、到收盤是否衰退）

用法：
  uv run python scripts/direction_events.py [--methods q2,q3_01] [--tf 1,3,5] [--mode 原始,縮放]
      [--boot 1000] [--seed 0]
  uv run python scripts/direction_events.py --report-only   # 只由 csv 重建判定與有效期表
"""

from __future__ import annotations

import argparse
import re
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT = ROOT / "results" / "direction"

sys.path.insert(0, str(Path(__file__).resolve().parent))
import point_params as _pp  # noqa: E402
from point_params import POINT_PARAMS, REF_PRICE  # noqa: E402
from run_individual import strategy_classes, tf_kwargs  # noqa: E402
from run_scaled import (  # noqa: E402
    DEFAULT_WARMUP_DAYS,
    WARMUP_OVERRIDE_DEFAULT,
    _CutoffWrapper,
    build_segments,
    scaled_kwargs,
)

from wangtrader.core import run as engine_run  # noqa: E402
from wangtrader.core.bars import prepare  # noqa: E402

SCOPE_PREFIX = ("q2_", "q3_", "sg_", "gq_01_11", "gq_04_02", "gq_04_03")
H_ALL = [5, 10, 15, 30, 45, 60, 90, 120, 180, 240, "close"]
H_MAIN = [15, 30, 60, 120, "close"]
HALF_SPLIT = pd.Timestamp("2026-01-01")
MIN_N = 30

# 同一訊號類型的多空兩面合併成一個「家族」（補進場、反手等仍各自一族）
_FAMILY_RULES = [
    (r"買進CALL|買進PUT", "買CALL/PUT"),
    (r"RSI鈍化正N型|RSI鈍化倒N型", "RSI鈍化N型"),
    (r"RSI正N型|RSI倒N型", "RSI N型"),
    (r"PVT-N型買進|PVT倒N型放空", "PVT N型"),
    (r"倒N型空訊|N型買訊", "N型"),
    (r"紅三兵|黑三兵", "紅黑三兵"),
    (r"底雙紅|頂雙黑", "頂底雙紅黑"),
    (r"底V字|頂倒V", "V字"),
    (r"底母子|頂母子", "母子"),
    (r"過三高|破三低", "過三高破三低"),
    (r"連五黑遇首紅|連五紅遇首黑", "連五反轉"),
    (r"跳高收黑|跳低收紅", "跳空反向K"),
    (r"創新低|創新高", "創新高低"),
    (r"RSI正差買訊|RSI負差空訊", "RSI差值"),
    (r"五黑例外|五紅例外", "五連例外"),
    (r"首K收黑空訊|首K收紅買訊", "首K顏色"),
    (r"提前買訊|提前賣訊", "提前訊"),
    (r"向上|向下", ""),
    (r"\(多\)|\(空\)", ""),
    (r"-買進|-賣出", ""),
    (r"突破|跌破", "突破跌破"),
    (r"買進|放空|買訊|空訊", ""),
]


def family(reason: str) -> str:
    s = reason
    for pat, rep in _FAMILY_RULES:
        s = re.sub(pat, rep, s)
    s = s.strip(" -") or reason
    return s


def in_scope(name: str) -> bool:
    return name.startswith(SCOPE_PREFIX)


def ref_price(name: str) -> float:
    """優先用 point_params.ref_price（含 REF_PRICE_BY_METHOD 個別參考價），舊版則依前綴。"""
    if hasattr(_pp, "ref_price"):
        return _pp.ref_price(name)
    for k in ("q2", "gq", "sg"):
        if name.startswith(k):
            return REF_PRICE[k]
    return REF_PRICE["q3"]


def has_scaled(name: str) -> bool:
    return bool(POINT_PARAMS.get(name))


# ---------------------------------------------------------------- 訊號收集

def collect_signals(name: str, tf: int, mode: str) -> pd.DataFrame:
    cls = strategy_classes()[name]
    raw = pd.read_parquet(DATA / f"tx_day_{tf}min.parquet")
    rows = []
    if mode == "原始":
        strat = cls(**tf_kwargs(name, tf))
        strat.enter_on_last_bar = False
        res = engine_run(strat, raw)
        rows = [(s.i, int(s.side), s.reason) for s in res.signals]
    else:
        wd = WARMUP_OVERRIDE_DEFAULT.get(name, DEFAULT_WARMUP_DAYS)
        ref = ref_price(name)
        for seg in build_segments(raw, wd):
            scale = seg["first_open"] / ref
            sub = raw.iloc[seg["seg_start_pos"]:seg["seg_end_pos"]].copy()
            strat = cls(**scaled_kwargs(cls, name, scale), **tf_kwargs(name, tf))
            strat.enter_on_last_bar = False
            if not strat.intraday:
                strat = _CutoffWrapper(strat)
            res = engine_run(strat, sub)
            wb = seg["warmup_bars"]
            rows += [(seg["seg_start_pos"] + s.i, int(s.side), s.reason) for s in res.signals if s.i >= wb]
    sig = pd.DataFrame(rows, columns=["i", "side", "reason"])
    sig.insert(0, "mode", mode)
    sig.insert(0, "tf", tf)
    sig.insert(0, "method", name)
    sig["family"] = sig["reason"].map(family)
    return sig


# ---------------------------------------------------------------- 前瞻報酬

def bar_table(tf: int) -> tuple[pd.DataFrame, dict]:
    """回傳 prepared df（加 half、date）與 {h: fwd_bp 陣列}、{h: fwd_pts 陣列}。"""
    df = prepare(pd.read_parquet(DATA / f"tx_day_{tf}min.parquet"))
    t = pd.to_datetime(df["time"]).to_numpy("datetime64[m]").astype(np.int64)  # 分鐘
    sess = df["session"].to_numpy()
    close = df["close"].to_numpy(float)
    sopen = df["sess_open"].to_numpy(float)
    n = len(df)
    # 每根所屬交易日的最後一根位置
    last = np.empty(n, dtype=np.int64)
    change = np.r_[np.flatnonzero(sess[1:] != sess[:-1]), n - 1]
    start = 0
    for e in change:
        last[start:e + 1] = e
        start = e + 1
    fwd_pts, fwd_bp = {}, {}
    for h in H_ALL:
        if h == "close":
            j = last
        else:
            j = np.searchsorted(t, t + h, side="right") - 1
            j = np.minimum(j, last)
        fp = close[j] - close
        fwd_pts[h] = fp
        fwd_bp[h] = fp / sopen * 1e4
    df["date"] = pd.to_datetime(df["time"]).dt.normalize()
    df["half"] = np.where(df["date"] < HALF_SPLIT, 1, 2)
    return df, {"pts": fwd_pts, "bp": fwd_bp}


# ---------------------------------------------------------------- 統計

def _subset_masks(ev: pd.DataFrame) -> tuple[np.ndarray, list[tuple[str, str, str]]]:
    side = ev["side"].to_numpy()
    half = ev["half"].to_numpy()
    sess = ev["session"].to_numpy()
    first_all = ~pd.Series(sess).duplicated().to_numpy()
    masks, keys = [], []
    for sname, sm in (("全部", np.ones(len(ev), bool)), ("多", side == 1), ("空", side == -1)):
        # 每日第一個：在該多空子集內取每日第一個
        if sname == "全部":
            fm = first_all
        else:
            fm = np.zeros(len(ev), bool)
            idx = np.flatnonzero(sm)
            fm[idx[~pd.Series(sess[idx]).duplicated().to_numpy()]] = True
        for hname, hm in (("全期", np.ones(len(ev), bool)), ("前半", half == 1), ("後半", half == 2)):
            for fname, ff in (("否", np.ones(len(ev), bool)), ("是", fm)):
                masks.append(sm & hm & ff)
                keys.append((sname, hname, fname))
    return np.stack(masks, axis=1), keys


def event_stats(ev: pd.DataFrame, bars: pd.DataFrame, fwd: dict, tf: int, B: int, seed: int) -> list[dict]:
    """ev 需已含 i, side, session, half, bar_no（依 i 排序）。"""
    n = len(ev)
    rng = np.random.default_rng(seed)
    # 基準抽樣池：依 (half, bar_no) 排序，每個事件取同半段、bar_no ±w 的連續區間
    w = max(1, 15 // tf)
    key_all = bars["half"].to_numpy() * 10000 + bars["bar_no"].to_numpy()
    order = np.argsort(key_all, kind="stable")
    keys_sorted = key_all[order]
    eh = ev["half"].to_numpy()
    eb = ev["bar_no"].to_numpy()
    lo = np.searchsorted(keys_sorted, eh * 10000 + np.maximum(eb - w, 0), side="left")
    hi = np.searchsorted(keys_sorted, eh * 10000 + eb + w, side="right")
    S = order[lo + (rng.random((B, n)) * (hi - lo)).astype(np.int64)]
    D = rng.choice(np.array([-1.0, 1.0], dtype=np.float32), size=(B, n))
    side = ev["side"].to_numpy().astype(np.float32)
    ii = ev["i"].to_numpy()

    M, keys = _subset_masks(ev)
    cnt = M.sum(0)
    Mf = M.astype(np.float32)
    safe = np.maximum(cnt, 1)
    out = []
    for h in H_ALL:
        rb = side * fwd["bp"][h][ii]
        rp = side * fwd["pts"][h][ii]
        obs = rb @ M / safe
        obs_p = rp @ M / safe
        pos = (rb > 0).astype(float) @ M
        neg = (rb < 0).astype(float) @ M
        G = fwd["bp"][h][S].astype(np.float32)  # B×n
        base_r = (G * D) @ Mf / safe
        base_d = (G * side) @ Mf / safe
        for k, (sname, hname, fname) in enumerate(keys):
            c = int(cnt[k])
            if c == 0:
                continue
            br, bd = base_r[:, k], base_d[:, k]
            out.append({
                "side": sname, "half": hname, "first": fname,
                "h": str(h), "n": c,
                "mean_pts": float(obs_p[k]), "mean_bp": float(obs[k]),
                "hit": float(pos[k] / (pos[k] + neg[k])) if pos[k] + neg[k] > 0 else np.nan,
                "n_tie": int(c - pos[k] - neg[k]),
                "base_rand_mean": float(br.mean()), "base_rand_sd": float(br.std()),
                "p_rand": float(((br >= obs[k]).sum() + 1) / (B + 1)),
                "p_rand_lo": float(((br <= obs[k]).sum() + 1) / (B + 1)),
                "base_drift_mean": float(bd.mean()),
                "excess_bp": float(obs[k] - bd.mean()),
                "p_drift": float(((bd >= obs[k]).sum() + 1) / (B + 1)),
                "p_drift_lo": float(((bd <= obs[k]).sum() + 1) / (B + 1)),
            })
    return out


def job(args) -> tuple[pd.DataFrame, pd.DataFrame, str]:
    name, tf, mode, B, seed = args
    try:
        sig = collect_signals(name, tf, mode)
    except Exception as e:  # 不中斷其他組合
        return pd.DataFrame(), pd.DataFrame(), f"{name} {tf} {mode} 錯誤：{type(e).__name__}: {e}"
    bars, fwd = bar_table(tf)
    if sig.empty:
        return sig, pd.DataFrame(), f"{name} {tf} {mode}：0 訊號"
    sig = sig.sort_values("i", kind="stable").reset_index(drop=True)
    for c in ("session", "bar_no", "half"):
        sig[c] = bars[c].to_numpy()[sig["i"].to_numpy()]
    sig["time"] = bars["time"].to_numpy()[sig["i"].to_numpy()]
    rows = []
    groups = [("全部", sig.drop_duplicates(["i", "side"]))]
    fams = sorted(sig["family"].unique())
    if len(fams) > 1:
        groups += [(f, sig[sig["family"] == f]) for f in fams]
    for gi, (fam, ev) in enumerate(groups):
        ev = ev.reset_index(drop=True)
        for r in event_stats(ev, bars, fwd, tf, B, seed + gi):
            rows.append({"method": name, "tf": tf, "mode": mode, "family": fam, **r})
    return sig, pd.DataFrame(rows), f"{name} {tf} {mode}：{len(sig)} 訊號"


# ---------------------------------------------------------------- 判定

def _get(st: pd.DataFrame, side: str, half: str, first: str, h: str) -> pd.Series | None:
    m = st[(st["side"] == side) & (st["half"] == half) & (st["first"] == first) & (st["h"] == h)]
    return None if m.empty else m.iloc[0]


def judge(st: pd.DataFrame, first: str = "否") -> dict:
    """st：單一 method×tf×mode×family 的統計列。依 SPEC 判定。"""
    out = {}
    base = _get(st, "全部", "全期", first, "60")
    n = int(base["n"]) if base is not None else 0
    verdict_h, tags = None, []
    status = "無"
    for h in ("60", "close"):
        a = _get(st, "全部", "全期", first, h)
        if a is None:
            continue
        h1, h2 = _get(st, "全部", "前半", first, h), _get(st, "全部", "後半", first, h)
        L, S = _get(st, "多", "全期", first, h), _get(st, "空", "全期", first, h)
        halves_pos = all(x is not None and x["mean_bp"] > 0 for x in (h1, h2))
        halves_neg = all(x is not None and x["mean_bp"] < 0 for x in (h1, h2))
        side_bad = any(x is not None and x["mean_bp"] < 0 and x["p_rand_lo"] < 0.05 for x in (L, S))
        sig = a["mean_bp"] > 0 and a["p_rand"] < 0.05
        if sig and halves_pos and not side_bad and n >= MIN_N:
            cand = "有用"
        elif a["mean_bp"] < 0 and a["p_rand_lo"] < 0.05 and halves_neg:
            cand = "反向"
        elif a["mean_bp"] > 0 and (a["p_rand"] < 0.10 or (halves_pos and a["p_rand"] < 0.20)):
            cand = "弱"
        else:
            cand = "無"
        rank = {"有用": 3, "反向": 2, "弱": 1, "無": 0}
        if rank[cand] > rank[status]:
            status, verdict_h = cand, h
            tags = []
            if sig and not halves_pos:
                tags.append("不穩定")
            if side_bad:
                tags.append("單側明顯負")
    if n < MIN_N:
        tags.append("樣本不足")
    out["判定"] = status + (f"（{'、'.join(tags)}）" if tags else "")
    out["判定_h"] = verdict_h or ""
    out["n"] = n
    for h in ("60", "close"):
        a = _get(st, "全部", "全期", first, h)
        if a is None:
            continue
        hs = "60" if h == "60" else "收"
        out[f"bp{hs}"] = a["mean_bp"]
        out[f"hit{hs}"] = a["hit"]
        out[f"p{hs}"] = a["p_rand"]
        out[f"excess{hs}"] = a["excess_bp"]
        out[f"pdrift{hs}"] = a["p_drift"]
        for half in ("前半", "後半"):
            x = _get(st, "全部", half, first, h)
            out[f"{half}{hs}"] = x["mean_bp"] if x is not None else np.nan
        for sd in ("多", "空"):
            x = _get(st, sd, "全期", first, h)
            out[f"{sd}{hs}"] = x["mean_bp"] if x is not None else np.nan
            out[f"n{sd}"] = int(x["n"]) if x is not None else 0
    return out


def horizon(st: pd.DataFrame) -> dict:
    sub = st[(st["side"] == "全部") & (st["half"] == "全期") & (st["first"] == "否")].set_index("h")
    hs = [str(h) for h in H_ALL if str(h) in sub.index]
    bp = sub.loc[hs, "mean_bp"].to_numpy()
    ex = sub.loc[hs, "excess_bp"].to_numpy()
    k, ke = int(np.argmax(bp)), int(np.argmax(ex))
    peak, close_bp = bp[k], bp[-1]
    if peak <= 0:
        trend = "全為負或零"
    elif close_bp >= 0.8 * peak:
        trend = "持續到收盤"
    elif close_bp > 0:
        trend = "峰後衰退"
    else:
        trend = "峰後翻負"
    # 有效期：第一個達到峰值 80% 的 h（峰值 > 0 時）
    reach = next((hs[j] for j in range(len(hs)) if peak > 0 and bp[j] >= 0.8 * peak), "")
    d = {"peak_h": hs[k], "peak_bp": peak, "close_bp": close_bp, "trend": trend, "reach80_h": reach,
         "excess_peak_h": hs[ke], "excess_peak_bp": ex[ke], "excess_close_bp": ex[-1]}
    for h, v in zip(hs, bp):
        d[f"bp_{h}"] = v
    return d


def build_tables(stats: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    ver, hor = [], []
    for key, st in stats.groupby(["method", "tf", "mode", "family"], sort=True):
        base = dict(zip(["method", "tf", "mode", "family"], key))
        j = judge(st, "否")
        jf = judge(st, "是")
        ver.append({**base, **j, "判定_每日首個": jf["判定"], "n_首個": jf["n"],
                    "bp60_首個": jf.get("bp60"), "p60_首個": jf.get("p60"),
                    "bp收_首個": jf.get("bp收"), "p收_首個": jf.get("p收")})
        hor.append({**base, "n": j["n"], **horizon(st)})
    return pd.DataFrame(ver), pd.DataFrame(hor)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--methods", default="", help="模組名稱前綴，逗號分隔（例如 q2,q3_01,sg）")
    ap.add_argument("--tf", default="1,3,5")
    ap.add_argument("--mode", default="原始,縮放")
    ap.add_argument("--boot", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--report-only", action="store_true")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    if a.report_only:
        stats = pd.read_csv(OUT / "events_stats.csv", dtype={"h": str})
    else:
        names = [n for n in strategy_classes() if in_scope(n)
                 and (not a.methods or any(n.startswith(m) for m in a.methods.split(",")))]
        jobs = []
        for n in names:
            for mode in a.mode.split(","):
                if mode == "縮放" and not has_scaled(n):
                    print(f"{n}：POINT_PARAMS 未登記點數欄位，縮放版略過（只跑原始）", flush=True)
                    continue
                if mode == "縮放":
                    print(f"{n}：縮放參考價 {ref_price(n):.0f}，欄位 {POINT_PARAMS[n]}", flush=True)
                for tf in a.tf.split(","):
                    jobs.append((n, int(tf), mode, a.boot, a.seed))
        sigs, stats_l = [], []
        with ProcessPoolExecutor(max_workers=a.workers) as ex:
            for sig, st, msg in ex.map(job, jobs):
                print(msg, flush=True)
                if not sig.empty:
                    sigs.append(sig)
                if not st.empty:
                    stats_l.append(st)
        sig_all = pd.concat(sigs) if sigs else pd.DataFrame()
        stats = pd.concat(stats_l) if stats_l else pd.DataFrame()
        # 部分重跑（--methods/--tf/--mode）時，與既有結果合併，只替換本次跑的組合
        done = {(j[0], j[1], j[2]) for j in jobs}

        def merge(path: Path, new: pd.DataFrame) -> pd.DataFrame:
            if path.exists() and (a.methods or a.tf != "1,3,5" or a.mode != "原始,縮放"):
                old = pd.read_csv(path, dtype={"h": str})
                keep = ~old.apply(lambda r: (r["method"], int(r["tf"]), r["mode"]) in done, axis=1)
                new = pd.concat([old[keep], new])
            new.to_csv(path, index=False)
            return new

        if not sig_all.empty:
            merge(OUT / "events_signals.csv", sig_all[["method", "tf", "mode", "i", "time", "side", "reason", "family",
                                                       "session", "bar_no", "half"]])
        stats = merge(OUT / "events_stats.csv", stats)
    stats["h"] = stats["h"].astype(str)
    ver, hor = build_tables(stats)
    ver.to_csv(OUT / "events_verdict.csv", index=False)
    hor.to_csv(OUT / "events_horizon.csv", index=False)
    print(f"verdict {len(ver)} 列、horizon {len(hor)} 列 -> {OUT}")


if __name__ == "__main__":
    main()
