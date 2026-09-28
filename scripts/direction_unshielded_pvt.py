"""方向判斷驗證：無遮蔽原則（q1 AFL 移植）與 PVT 通道控盤方向（q2-03-01），同週期與 3 倍週期輸入。

報告：methods/方向判斷驗證/無遮蔽與PVT.md
明細：methods/方向判斷驗證/無遮蔽與PVT_明細.csv（工具×實驗×週期×h×子集）、
      methods/方向判斷驗證/無遮蔽與PVT_判定.csv（工具×實驗×週期判定）

步驟
1. 由 data/tx_day_1min.parquet 合成 2、3、5、6、9、15 分K 存 data_mtf/（每日自 08:45 起算、不跨日，
   同 scripts/build_bars.py 的 resample；另加 minutes 欄＝該根含幾根 1 分K，用來算收盤時刻）。
2. 方向工具（只用第 i 根含以前的資料）：
   - 無遮蔽_延續：methods/期貨奇績1/wang_unshielded.py 的 wang_afl()（AFL 逐行移植，不改）產生多空訊號，
     方向＝最近一次訊號（多 +1／空 −1），持續到反向訊號（跨日延續）。
   - 無遮蔽_當日：同上，但每日第一個訊號之前為 0（不沿用前一日）。
   - PVT_L2／PVT_L4：沿用 scripts/direction_state.py 的 _pvt_regime（其內部用 PVTNType 的峰谷點、
     _update_ladder、_reseed 照 on_bar 步驟 1–2 推進）：收盤突破空趨勢階梯（上緣）＝多、
     收盤跌破多趨勢階梯（下緣）＝空，其間延續。
   - 對照：scripts/direction_state.py 的 TOOLS（MA 類等），同一資料、同一指標。
3. 實驗：
   - 同週期：在 2、3、5 分K 上算方向並評估。
   - 3倍：在 6、9、15 分K 上算方向，映射到 2、3、5 分K：大週期K收盤時刻之後開始的第一根小週期K起才用新狀態
     （小週期K開始時刻 ≥ 大週期K收盤時刻）。
   - 3倍_無延遲（敏感度）：小週期K收盤時刻 ≥ 大週期K收盤時刻即用（即大週期最後一根成分K當根）。
4. 評估（評估週期 2、3、5 分K）：fwd(i,h)＝第 i 根收盤到 h 根後收盤（同日內，超過取當日最後一根），
   h＝1、3、6、12 根、60 分鐘、到收盤。bp＝點數 ÷ 當日開盤 × 10000。
   - 各方向平均 fwd（多、空，點與 bp）、多減空價差、順向平均 r＝dir×fwd、命中率（r>0 / r≠0）。
   - 顯著性：
     p日平移：方向矩陣（交易日×當日第幾根）整日循環平移 k 日（5 ≤ k ≤ G−5，全部平移都算，FFT），
       保留當日時段結構與狀態持續性；右尾比例。對順向平均與多空價差各算一次。
     p根平移：整條方向序列逐根循環平移（5%～95%，全部平移），同 direction_state.py 的 p平移。
     t日群集：交易日群集穩健 t（順向平均沿用 direction_state.day_t；價差用影響函數法）。
   - 資料第一個交易日（2024-05-09）不列入評估：AFL 從 i=2 起跑且無遮蔽線初值 0，第一天有假多單。
用法：uv run python scripts/direction_unshielded_pvt.py [--workers 64] [--skip-build]
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import direction_state as ds  # noqa: E402  重用工具函式與 day_t

from wangtrader.core.bars import prepare  # noqa: E402

_spec = importlib.util.spec_from_file_location("wang_unshielded", ROOT / "methods" / "期貨奇績1" / "wang_unshielded.py")
wu = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wu)

SRC = ROOT / "data" / "tx_day_1min.parquet"
MTF = ROOT / "data_mtf"
REP = ROOT / "methods" / "方向判斷驗證"
BASE_TF = [2, 3, 5, 6, 9, 15]
EVAL_TF = [2, 3, 5]
X3 = {2: 6, 3: 9, 5: 15}
HORIZONS = [("1根", 1), ("3根", 3), ("6根", 6), ("12根", 12), ("60分", "m60"), ("收盤", "close")]
MIN_DAY_SHIFT = 5


# ---------------------------------------------------------------- 1. 合成多週期K


def build_mtf() -> None:
    MTF.mkdir(exist_ok=True)
    df = pd.read_parquet(SRC)
    df["minutes"] = 1
    for n in BASE_TF:
        out = df.resample(f"{n}min", origin="start_day", offset="8h45min").agg(
            {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum",
             "prev_valid": "first", "minutes": "sum"}
        ).dropna()
        out = out[out["minutes"] > 0]
        out["prev_valid"] = out["prev_valid"].astype(bool)
        out = out.astype({"open": "int64", "high": "int64", "low": "int64", "close": "int64",
                          "volume": "int64", "minutes": "int64"})
        # 檢查：不跨日、每根完整落在同一日、每日自 08:45 起
        first = out.groupby(out.index.normalize()).head(1)
        assert (first.index.strftime("%H:%M") == "08:45").all()
        assert out.groupby(out.index.normalize())["minutes"].sum().isin([285, 300]).all()
        out.to_parquet(MTF / f"tx_day_{n}min.parquet")
        per = out.groupby(out.index.normalize()).size().value_counts().to_dict()
        print(f"{n} 分K：{len(out)} 根，{out.index.normalize().nunique()} 日，每日根數分布 {per}")


def load(tf: int) -> pd.DataFrame:
    df = prepare(pd.read_parquet(MTF / f"tx_day_{tf}min.parquet"))
    df["time"] = pd.to_datetime(df["time"])
    df["close_time"] = df["time"] + pd.to_timedelta(df["minutes"], unit="min")
    df["date"] = df["time"].dt.normalize()
    return df


# ---------------------------------------------------------------- 2. 方向工具


def unshielded_signals(df: pd.DataFrame) -> np.ndarray:
    """wang_afl 的訊號：多 +1、空 −1、無 0。TimeNum 由K線開始時刻換算（同 AFL TimeNum()）。"""
    t = df["time"]
    tn = (t.dt.hour * 10000 + t.dt.minute * 100 + t.dt.second).to_numpy()
    o, h, lo, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    res = wu.wang_afl(tn, o, h, lo, c)
    return (res["long"] - res["short"]).astype(np.int8)


def carry(sig: np.ndarray, sess: np.ndarray | None = None) -> np.ndarray:
    s = pd.Series(np.where(sig != 0, sig, np.nan).astype(float))
    s = s.ffill() if sess is None else s.groupby(sess).ffill()
    return s.fillna(0).to_numpy().astype(np.int8)


def t_unshielded_carry(df, tf, daily):
    return carry(unshielded_signals(df))


def t_unshielded_day(df, tf, daily):
    return carry(unshielded_signals(df), df["session"].to_numpy())


def t_pvt_l2(df, tf, daily):
    return ds._pvt_regime(df, 2)


def t_pvt_l4(df, tf, daily):
    return ds._pvt_regime(df, 4)


MAIN_TOOLS = [
    ("無遮蔽_延續", "無遮蔽：最近一次訊號方向，延續到反向訊號（跨日）", t_unshielded_carry),
    ("無遮蔽_當日", "無遮蔽：當日最近一次訊號方向，當日第一個訊號前為 0", t_unshielded_day),
    ("PVT_L2", "PVT 通道控盤方向（層級2）", t_pvt_l2),
    ("PVT_L4", "PVT 通道控盤方向（層級4）", t_pvt_l4),
]
# 對照：direction_state.py 的工具（PVT 兩個與上面重複，略過）
BASE_TOOLS = [(k, d, f) for k, d, f in ds.TOOLS if not k.startswith("q2-03-01")]
# 3 倍週期也跑的對照工具（與週期無關、非日線層級者）
X3_BASE = {"q2-01_MA30位置", "q2-02_SAR", "MA10方向", "MA10位置", "cz-04-01_河流全排列",
           "cz-04-01_河流EMA55換位", "cz-04-02_EMA30/55", "cz-03-01_MA10/20", "gq-01-11_MA20/50"}
ALL_TOOLS = {k: (d, f) for k, d, f in MAIN_TOOLS + BASE_TOOLS}
INTRADAY_ONLY = {"無遮蔽_當日"}

_CACHE: dict = {}


def _df(tf):
    if tf not in _CACHE:
        df = load(tf)
        _CACHE[tf] = (df, ds.daily_bars(df))
    return _CACHE[tf]


def job_direction(args):
    tf, key = args
    df, daily = _df(tf)
    t0 = time.time()
    d = np.asarray(ALL_TOOLS[key][1](df, tf, daily), dtype=np.int8)
    info = {}
    if key.startswith("無遮蔽"):
        sig = unshielded_signals(df)
        s0 = df["session"].to_numpy() == 0
        info = {"n_long_sig": int((sig > 0).sum()), "n_short_sig": int((sig < 0).sum()),
                "sig_per_day": float((sig != 0).sum() / df["session"].nunique()),
                "day0_sigs": [(str(df["time"].iat[i].time()), int(sig[i])) for i in np.flatnonzero(s0 & (sig != 0))]}
    return tf, key, d, info, time.time() - t0


# ---------------------------------------------------------------- 3. 映射


def map_htf(d_htf: np.ndarray, htf: pd.DataFrame, ltf: pd.DataFrame, intraday: bool, lag: bool) -> np.ndarray:
    """大週期狀態映射到小週期。lag=True：小週期K開始時刻 ≥ 大週期收盤時刻才用；False：小週期收盤時刻 ≥ 大週期收盤時刻。"""
    h = pd.DataFrame({"t": htf["close_time"].to_numpy(), "d": d_htf, "hdate": htf["date"].to_numpy()})
    key = ltf["time"] if lag else ltf["close_time"]
    lt = pd.DataFrame({"t": key.to_numpy(), "pos": np.arange(len(ltf)), "ldate": ltf["date"].to_numpy()})
    m = pd.merge_asof(lt.sort_values("t"), h.sort_values("t"), on="t", direction="backward",
                      allow_exact_matches=True).sort_values("pos")
    out = m["d"].fillna(0).to_numpy()
    if intraday:
        out = np.where(m["hdate"].to_numpy() == m["ldate"].to_numpy(), out, 0)
    return out.astype(np.int8)


# ---------------------------------------------------------------- 4. 評估


def forward(df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    n = len(df)
    last = df.groupby("session").cumcount(ascending=False).to_numpy() + np.arange(n)
    close = df["close"].to_numpy(float)
    ct = df["close_time"].to_numpy().astype("datetime64[m]").astype(np.int64)
    pts = np.zeros((n, len(HORIZONS)))
    for k, (_, h) in enumerate(HORIZONS):
        if h == "close":
            j = last
        elif h == "m60":
            j = np.minimum(np.searchsorted(ct, ct + 60, side="right") - 1, last)
        else:
            j = np.minimum(np.arange(n) + h, last)
        pts[:, k] = close[j] - close
    bp = pts / df["sess_open"].to_numpy(float)[:, None] * 1e4
    return pts, bp


def _corr_days(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """c[k] = Σ_d Σ_s a[d,s]·b[(d+k) mod G, s]（方向第 d 日套到第 d+k 日的報酬）。"""
    g = a.shape[0]
    return np.fft.irfft(np.conj(np.fft.rfft(a, axis=0)) * np.fft.rfft(b, axis=0), n=g, axis=0).sum(axis=1)


def _corr_1d(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    n = len(a)
    return np.fft.irfft(np.conj(np.fft.rfft(a)) * np.fft.rfft(b), n=n)


def _shift_stats(sp, npos, sm, nneg):
    tot = npos + nneg
    with np.errstate(invalid="ignore", divide="ignore"):
        mean_r = (sp - sm) / tot
        spread = sp / npos - sm / nneg
    return mean_r, spread


def _pval(dist: np.ndarray, actual: float, right=True) -> float:
    dist = dist[np.isfinite(dist)]
    if right:
        return float(((dist >= actual - 1e-12).sum() + 1) / (len(dist) + 1))
    return float(((dist <= actual + 1e-12).sum() + 1) / (len(dist) + 1))


def spread_t(x: np.ndarray, d: np.ndarray, day: np.ndarray) -> float:
    lo, sh = d > 0, d < 0
    nl, ns = lo.sum(), sh.sum()
    if nl < 2 or ns < 2:
        return np.nan
    ml, ms = x[lo].mean(), x[sh].mean()
    psi = np.where(lo, (x - ml) / nl, np.where(sh, -(x - ms) / ns, 0.0))
    g = pd.Series(psi).groupby(day).sum().to_numpy()
    G = len(g)
    se = np.sqrt((g ** 2).sum() * G / (G - 1))
    return float((ml - ms) / se) if se > 0 else np.nan


class EvalCtx:
    def __init__(self, tf: int):
        df = load(tf)
        self.tf = tf
        self.n = len(df)
        self.sess = df["session"].to_numpy()
        self.bar_no = df["bar_no"].to_numpy()
        self.G = int(self.sess.max()) + 1
        self.S = int(self.bar_no.max()) + 1
        self.pts, self.bp = forward(df)
        self.valid = self.sess != 0  # 排除資料第一個交易日（假多單）
        days = df.groupby("session")["date"].first()
        self.split_date = days.iloc[self.G // 2]
        self.half = (df["date"] >= self.split_date).to_numpy().astype(int)
        self.drift_bp = self.bp[self.valid].mean(axis=0)
        self.drift_pts = self.pts[self.valid].mean(axis=0)

    def mat(self, x: np.ndarray) -> np.ndarray:
        m = np.zeros((self.G, self.S))
        m[self.sess, self.bar_no] = x
        return m


_EC: dict = {}


def _ec(tf):
    if tf not in _EC:
        _EC[tf] = EvalCtx(tf)
    return _EC[tf]


def evaluate(key: str, exp: str, tf: int, d: np.ndarray) -> list[dict]:
    ec = _ec(tf)
    d = np.where(ec.valid, d, 0).astype(np.int8)
    nz = np.flatnonzero(d)
    if len(nz) == 0:
        return []
    V = ec.mat(ec.valid.astype(float))
    P, M = ec.mat((d > 0).astype(float)), ec.mat((d < 0).astype(float))
    npos_d, nneg_d = _corr_days(P, V), _corr_days(M, V)
    npos_b, nneg_b = _corr_1d((d > 0).astype(float), ec.valid.astype(float)), _corr_1d((d < 0).astype(float), ec.valid.astype(float))
    G, N = ec.G, ec.n
    dsh = np.arange(MIN_DAY_SHIFT, G - MIN_DAY_SHIFT + 1)
    bsh = np.arange(int(N * 0.05), int(N * 0.95))
    dz = d[nz].astype(float)
    dayz, halfz = ec.sess[nz], ec.half[nz]
    rows = []
    for k, (hname, _) in enumerate(HORIZONS):
        x_bp = np.where(ec.valid, ec.bp[:, k], 0.0)
        R = ec.mat(x_bp)
        md, sd = _shift_stats(_corr_days(P, R), npos_d, _corr_days(M, R), nneg_d)
        mb, sb = _shift_stats(_corr_1d((d > 0).astype(float), x_bp), npos_b, _corr_1d((d < 0).astype(float), x_bp), nneg_b)
        bpz, ptz = ec.bp[nz, k], ec.pts[nz, k]
        r_bp, r_pt = dz * bpz, dz * ptz
        base = {"tool": key, "desc": ALL_TOOLS[key][0], "exp": exp, "tf": tf, "h": hname,
                "drift_bp": float(ec.drift_bp[k]), "drift_pts": float(ec.drift_pts[k])}
        subsets = {"全部": np.ones(len(nz), bool), "前半": halfz == 0, "後半": halfz == 1}
        for sname, msk in subsets.items():
            if not msk.any():
                continue
            dd, xb, xp, rb, rp, dy = dz[msk], bpz[msk], ptz[msk], r_bp[msk], r_pt[msk], dayz[msk]
            lo, sh = dd > 0, dd < 0
            row = dict(base, subset=sname, n_bars=int(msk.sum()), n_days=int(len(np.unique(dy))),
                       frac_long=float(lo.mean()),
                       long_bp=float(xb[lo].mean()) if lo.any() else np.nan,
                       short_bp=float(xb[sh].mean()) if sh.any() else np.nan,
                       long_pts=float(xp[lo].mean()) if lo.any() else np.nan,
                       short_pts=float(xp[sh].mean()) if sh.any() else np.nan,
                       mean_bp=float(rb.mean()), mean_pts=float(rp.mean()),
                       hit=float((rb > 0).sum() / max(1, (rb != 0).sum())),
                       hit_long=float((rb[lo] > 0).sum() / max(1, (rb[lo] != 0).sum())) if lo.any() else np.nan,
                       hit_short=float((rb[sh] > 0).sum() / max(1, (rb[sh] != 0).sum())) if sh.any() else np.nan,
                       t_day=ds.day_t(rb, dy), t_day_spread=spread_t(xb, dd, dy))
            row["spread_bp"] = row["long_bp"] - row["short_bp"]
            row["spread_pts"] = row["long_pts"] - row["short_pts"]
            if sname == "全部":
                row["frac_zero"] = float(1 - len(nz) / ec.valid.sum())
                row["p_dshift"] = _pval(md[dsh], md[0])
                row["p_dshift_left"] = _pval(md[dsh], md[0], right=False)
                row["p_dshift_spread"] = _pval(sd[dsh], sd[0])
                row["p_bshift"] = _pval(mb[bsh], mb[0])
                row["null_dshift_mean"] = float(np.nanmean(md[dsh]))
                row["null_dshift_sd"] = float(np.nanstd(md[dsh]))
                assert abs(md[0] - row["mean_bp"]) < 1e-6, (key, exp, tf, hname, md[0], row["mean_bp"])
            rows.append(row)
    return rows


def job_eval(args):
    key, exp, tf, d = args
    return evaluate(key, exp, tf, d)


def verdict(m: pd.DataFrame) -> dict:
    """每個 h：通過＝p日平移<0.05 且 t日群集≥2 且前後兩半順向平均皆>0；
    弱＝p日平移<0.10 且兩半皆>0，或 p日平移<0.05 但兩半有一半≤0；反向＝左尾 p日平移<0.05 且 t≤−2；其餘無。
    綜合：60分或收盤任一通過→有用；否則任一 h（含 1/3/6/12 根）通過→僅短 h；否則有弱→弱；有反向→反向；否則無。"""
    res = {}
    for hname, _ in HORIZONS:
        a = m[(m.h == hname) & (m.subset == "全部")]
        if a.empty:
            continue
        a = a.iloc[0]
        f = m[(m.h == hname) & (m.subset == "前半")]
        s = m[(m.h == hname) & (m.subset == "後半")]
        fb = f.mean_bp.iat[0] if len(f) else np.nan
        sb = s.mean_bp.iat[0] if len(s) else np.nan
        halves = fb > 0 and sb > 0
        if a.p_dshift < 0.05 and a.t_day >= 2 and halves:
            v = "通過"
        elif a.p_dshift_left < 0.05 and a.t_day <= -2:
            v = "反向"
        elif (a.p_dshift < 0.10 and halves) or a.p_dshift < 0.05:
            v = "弱"
        else:
            v = "無"
        res[hname] = v
    passed = [h for h, v in res.items() if v == "通過"]
    if any(h in ("60分", "收盤") for h in passed):
        overall = "有用"
    elif passed:
        overall = "僅短h"
    elif "弱" in res.values():
        overall = "弱"
    elif "反向" in res.values():
        overall = "反向"
    else:
        overall = "無"
    return {"verdict": overall, "passed_h": "/".join(passed), **{f"v_{h}": v for h, v in res.items()}}


# ---------------------------------------------------------------- 主程式


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=min(64, os.cpu_count() or 8))
    ap.add_argument("--skip-build", action="store_true")
    args = ap.parse_args()
    if not args.skip_build:
        build_mtf()
    t0 = time.time()
    # 方向計算
    djobs = [(tf, k) for tf in EVAL_TF for k in ALL_TOOLS]
    djobs += [(X3[tf], k) for tf in EVAL_TF for k in ALL_TOOLS if k in dict.fromkeys([m[0] for m in MAIN_TOOLS]) or k in X3_BASE]
    djobs = sorted(set(djobs), key=lambda x: (not x[1].startswith("PVT"), x))  # PVT 最慢，先排
    dirs, infos = {}, {}
    with ProcessPoolExecutor(args.workers) as ex:
        for tf, key, d, info, sec in ex.map(job_direction, djobs):
            dirs[(tf, key)] = d
            if info:
                infos[(tf, key)] = info
    print(f"方向計算完成 {len(dirs)} 組，{time.time() - t0:.0f}s", flush=True)
    for (tf, key), info in sorted(infos.items()):
        if key == "無遮蔽_延續":
            print(f"  {tf} 分K 無遮蔽訊號：多 {info['n_long_sig']}、空 {info['n_short_sig']}、每日 {info['sig_per_day']:.2f} 次；"
                  f"第一日訊號 {info['day0_sigs']}")
    # 映射與評估
    htf_df = {tf: load(tf) for tf in X3.values()}
    ltf_df = {tf: load(tf) for tf in EVAL_TF}
    ejobs = []
    for tf in EVAL_TF:
        for key in ALL_TOOLS:
            ejobs.append((key, "同週期", tf, dirs[(tf, key)]))
            if (X3[tf], key) in dirs:
                for exp, lag in (("3倍", True), ("3倍_無延遲", False)):
                    d = map_htf(dirs[(X3[tf], key)], htf_df[X3[tf]], ltf_df[tf], key in INTRADAY_ONLY, lag)
                    ejobs.append((key, exp, tf, d))
    rows = []
    with ProcessPoolExecutor(args.workers) as ex:
        for r in ex.map(job_eval, ejobs):
            rows += r
    met = pd.DataFrame(rows)
    met.to_csv(REP / "無遮蔽與PVT_明細.csv", index=False, encoding="utf-8-sig")
    ver = []
    for (tool, exp, tf), m in met.groupby(["tool", "exp", "tf"], sort=False):
        ver.append({"tool": tool, "exp": exp, "tf": tf, **verdict(m)})
    ver = pd.DataFrame(ver)
    ver.to_csv(REP / "無遮蔽與PVT_判定.csv", index=False, encoding="utf-8-sig")
    ec = _ec(2)
    print(f"前後半切點：{ec.split_date.date()}；評估天數 {ec.G - 1}")
    show = met[(met.subset == "全部") & met.tool.isin([m[0] for m in MAIN_TOOLS]) & met.h.isin(["6根", "60分", "收盤"])]
    print(show[["tool", "exp", "tf", "h", "frac_long", "long_bp", "short_bp", "spread_bp", "mean_bp", "hit",
                "p_dshift", "p_dshift_spread", "p_bshift", "t_day"]].round(3).to_string())
    print(ver[ver.tool.isin([m[0] for m in MAIN_TOOLS])].to_string())
    print(f"總耗時 {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
