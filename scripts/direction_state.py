"""方向判斷驗證：狀態型（S）方向工具（依 methods/方向判斷驗證/SPEC.md）。

每根K線給一個方向狀態 dir ∈ {+1, −1, 0}（只用第 i 根含以前的資料），
與未來 h 分鐘的收盤變化 fwd(i, h)（同一交易日內，超過收盤取收盤）比對：
  r(i, h) = dir(i) × fwd(i, h)，換成 ÷ 當日開盤價 × 10000 的 bp。
h = 15, 30, 60, 120 分鐘與「到收盤」。

基準：
  - 整體漂移：同一 h 下全部K線的平均 fwd（bp）。
  - 逐根置換檢定（SPEC 指定）：把該工具非 0 的方向在非 0 的K線之間隨機打亂 1000 次（保留多空根數），p＝右尾比例。
  - 循環平移檢定（補充，較保守）：整條方向序列隨機循環平移 1000 次（保留狀態的自相關），p＝右尾比例。
    狀態型方向高度持續、fwd 又互相重疊，逐根置換會低估變異，所以另報此 p 作「保守」參考。

用法：uv run python scripts/direction_state.py [--tf 1,3,5] [--perm 1000]
輸出：results/direction/state_metrics.csv（工具×週期×h×子集）、results/direction/state_verdict.csv（工具×週期判定）
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import numpy as np
import pandas as pd

from wangtrader.core.bars import prepare
from wangtrader.core.indicators import kd, sar, sma
from wangtrader.methods.q2_03_01_pvt_n_type import PVTNType
from wangtrader.methods.q2_04_01_cross_kd_n_type import CrossKDNType

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT = ROOT / "results" / "direction"

HORIZONS = [15, 30, 60, 120, "close"]
SPLIT = pd.Timestamp("2026-01-01")  # 前半 2025-03～2025-12，後半 2026-01～2026-09
DAY_SESSION_MIN = 300  # 日盤 08:45–13:45＝300 分鐘（只用於把「N 日均線」換成根數與大週期根數比）


# ---------------------------------------------------------------- 小工具


def _sign_carry(x) -> np.ndarray:
    """sign(x)，0（相等）沿用前值，NaN 視為 0（尚無狀態）。"""
    x = np.asarray(x, dtype=float)
    s = np.sign(np.nan_to_num(x, nan=0.0))
    s = pd.Series(np.where(s == 0, np.nan, s))
    valid = ~np.isnan(x)
    s = s.ffill().fillna(0.0).to_numpy().copy()
    s[~valid] = 0.0
    return s.astype(np.int8)


def _ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def _htf_last_completed(df: pd.DataFrame, htf_bars: int) -> tuple[pd.DataFrame, np.ndarray]:
    """每交易日自第一根起每 htf_bars 根合成一根大週期K線；回傳 (htf, 對應位置)。
    htf 的每一列只在其最後一根小週期K線收盤時才「已完成」（交易日最後不足 htf_bars 的一組，
    於該交易日最後一根收盤時完成；資料最後一個交易日未滿的組不用）。"""
    grp = (df["bar_no"] // htf_bars).astype(int)
    key = pd.factorize(pd.Index(zip(df["session"].tolist(), grp.tolist(), strict=False)))[0]
    tmp = pd.DataFrame({"o": df["open"], "h": df["high"], "l": df["low"], "c": df["close"],
                        "g": key, "pos": np.arange(len(df)), "s": df["session"].to_numpy()})
    htf = tmp.groupby("g", sort=True).agg(open=("o", "first"), high=("h", "max"), low=("l", "min"),
                                          close=("c", "last"), last_pos=("pos", "max"),
                                          size=("pos", "size"), session=("s", "last"))
    last_s = df["session"].iat[-1]
    htf = htf[(htf["size"] >= htf_bars) | (htf["session"] != last_s)].reset_index(drop=True)
    return htf, htf["last_pos"].to_numpy()


def _spread_htf(values: np.ndarray, last_pos: np.ndarray, n: int) -> np.ndarray:
    """把大週期狀態放到其完成當根，之後向後延續（因果）。"""
    out = np.full(n, np.nan)
    out[last_pos] = values
    return pd.Series(out).ffill().fillna(0).to_numpy().astype(np.int8)


# ---------------------------------------------------------------- 方向工具
# 每個函式 f(df, tf, daily) -> np.ndarray[int8]，長度＝K線數，只用當根（含）以前資料。


def t_q2_01(df, tf, daily):
    """q2-01：收盤在 MA30 上＝+1、下＝−1（模組 MAThreeStep.prepare 同 core.sma(close, 30)）。"""
    return _sign_carry((df["close"] - sma(df["close"], 30)).to_numpy())


def t_q2_02(df, tf, daily):
    """q2-02：SAR 在價格下方＝+1（core.indicators.sar 的 trend，模組 SARC 同）。"""
    return sar(df)["trend"].to_numpy().astype(np.int8)


def _pvt_regime(df: pd.DataFrame, level: int) -> np.ndarray:
    """q2-03-01 PVT 控盤方向：沿用模組 PVTNType 的峰谷點、_update_ladder、_reseed，
    照其 on_bar 步驟 1–2（更新階梯→控盤易主）逐根推進；只取 regime，不跑 N 型結構。"""
    s = PVTNType(pivot_level=level)
    s.prepare(df)
    st = s._fresh()
    close = df["close"].to_numpy(float)
    out = np.zeros(len(df), dtype=np.int8)
    for i in range(len(df)):
        for pv in s._troughs_by_confirm.get(i, []):
            s._update_ladder(st, "trough", pv.price)
        for pv in s._peaks_by_confirm.get(i, []):
            s._update_ladder(st, "peak", pv.price)
        c = close[i]
        sw_bull = st["bear_ladder"] is not None and c > st["bear_ladder"] and st["regime"] != "bull"
        sw_bear = st["bull_ladder"] is not None and c < st["bull_ladder"] and st["regime"] != "bear"
        if st["regime"] is None:
            sw_bull = sw_bull or (st["bull_ladder"] is not None and c > st["bull_ladder"])
            sw_bear = sw_bear or (st["bear_ladder"] is not None and c < st["bear_ladder"])
        if sw_bull:
            st["regime"] = "bull"
            s._reseed(st, "trough", i)
        elif sw_bear:
            st["regime"] = "bear"
            s._reseed(st, "peak", i)
        out[i] = 1 if st["regime"] == "bull" else (-1 if st["regime"] == "bear" else 0)
    return out


def t_q2_03_l2(df, tf, daily):
    return _pvt_regime(df, 2)


def t_q2_03_l4(df, tf, daily):
    return _pvt_regime(df, 4)


def t_q2_04_01(df, tf, daily):
    """q2-04-01：15 分鐘 KD 金叉區＝+1、死叉區＝−1（沿用 CrossKDNType._regime，htf_bars＝15/tf，只用已完成大週期K）。"""
    s = CrossKDNType(htf_bars=max(1, 15 // tf))
    reg, _ = s._regime(df)
    return reg.astype(np.int8)


def _four_pillars(df: pd.DataFrame, mode: str) -> np.ndarray:
    """q2-04-02 四柱（昨高、昨低、昨收、今開）根數優劣，照文件重寫（模組是逐關卡的突破狀態機，無可直接取用的方向欄）：
    每個關卡當日累計「收盤在上方根數」與「收盤在下方根數」（含本根）。
    mode="now"：收盤在關卡上方且上方根數 > 下方根數 → 該關卡 +1；鏡像 −1；否則 0。
    mode="count"：只看根數優劣 sign(上方根數 − 下方根數)。
    方向＝四個關卡投票總和的正負號（關卡值缺漏者不投票）。"""
    close = df["close"]
    total = np.zeros(len(df))
    for col in ("prev_high", "prev_low", "prev_close", "sess_open"):
        lvl = df[col]
        above = (close > lvl).astype(int)
        below = (close < lvl).astype(int)
        ca = above.groupby(df["session"]).cumsum()
        cb = below.groupby(df["session"]).cumsum()
        if mode == "now":
            v = np.where((above == 1) & (ca > cb), 1, np.where((below == 1) & (cb > ca), -1, 0))
        else:
            v = np.sign(ca - cb).to_numpy()
        v = np.where(lvl.isna().to_numpy(), 0, v)
        total += v
    return np.sign(total).astype(np.int8)


def t_q2_04_02_now(df, tf, daily):
    return _four_pillars(df, "now")


def t_q2_04_02_count(df, tf, daily):
    return _four_pillars(df, "count")


def t_ma10_slope(df, tf, daily):
    """q3-08-01／q3-08-02／q3-09-01：MA10 朝上＝+1、朝下＝−1，走平沿用前值（同 q3_09_01 模組 cur_dir 定義）。"""
    ma = sma(df["close"], 10).to_numpy()
    return _sign_carry(np.diff(ma, prepend=np.nan))


def t_ma10_pos(df, tf, daily):
    """q3-08-01／q3-08-02／sg-04：收盤在 MA10 上＝+1、下＝−1（sg-04「站上／跌破」）。"""
    return _sign_carry((df["close"] - sma(df["close"], 10)).to_numpy())


def t_q3_11(df, tf, daily):
    """q3-11：30 分K（htf_bars＝30/tf 合成，只用已完成者）收盤在 MA100 上＝+1、下＝−1。
    q3-11 模組本身沒有大週期合成（直接對輸入K線算 MA100），此處照文件以 30 分K 重寫。"""
    htf, pos = _htf_last_completed(df, max(1, 30 // tf))
    d = _sign_carry((htf["close"] - sma(htf["close"], 100)).to_numpy())
    return _spread_htf(d, pos, len(df))


RIVER = list(range(10, 60, 5))  # 河流圖 EMA10、15、…、55 共 10 條（cz-04-00，p.132）


def _river(df):
    return np.column_stack([_ema(df["close"], n).to_numpy() for n in RIVER])


def t_cz_04_01_full(df, tf, daily):
    """cz-04-01：河流圖全多排（EMA10>15>…>55）＝+1、全空排＝−1、其餘（糾結）＝0。"""
    e = _river(df)
    ok = ~np.isnan(e).any(axis=1)
    d = np.diff(e, axis=1)
    bull = ok & (d < 0).all(axis=1)
    bear = ok & (d > 0).all(axis=1)
    return np.where(bull, 1, np.where(bear, -1, 0)).astype(np.int8)


def t_cz_04_01_regime(df, tf, daily):
    """cz-04-00 趨勢反轉認定：最長天期 EMA55 移到排列最下方＝轉多、移到最上方＝轉空，其間沿用（p.129–131）。
    gq-01-11 的「河流圖」多空也用此定義。"""
    e = _river(df)
    ok = ~np.isnan(e).any(axis=1)
    last = e[:, -1]
    x = np.where(ok & (last <= e.min(axis=1)), 1.0, np.where(ok & (last >= e.max(axis=1)), -1.0, np.nan))
    s = pd.Series(x).ffill().fillna(0).to_numpy()
    return s.astype(np.int8)


def t_cz_04_02(df, tf, daily):
    """cz-04-02：EMA30 > EMA55（黃金交叉後）＝+1、死亡交叉後＝−1。"""
    c = df["close"]
    return _sign_carry((_ema(c, 30) - _ema(c, 55)).to_numpy())


def t_cz_03_01(df, tf, daily):
    """cz-03-01：MA10 > MA20（金叉到死叉區間）＝+1、反之 −1（未處理「交叉須維持」的主觀條件）。"""
    c = df["close"]
    return _sign_carry((sma(c, 10) - sma(c, 20)).to_numpy())


def t_gq_01_11_mod(df, tf, daily):
    """gq-01-11 模組預設：SMA20 > SMA50＝+1（模組 prepare 的 regime）。"""
    c = df["close"]
    return _sign_carry((sma(c, 20) - sma(c, 50)).to_numpy())


def t_gq_01_11_book(df, tf, daily):
    """gq-01-11 書中台指 5 分K 例：MA300（五日均線）/MA180（三日均線）交叉；換成各週期的「5 日／3 日」根數。"""
    per_day = DAY_SESSION_MIN // tf
    c = df["close"]
    return _sign_carry((sma(c, 3 * per_day) - sma(c, 5 * per_day)).to_numpy())


# ---- 簡單基準


def t_prev_close(df, tf, daily):
    """價格在平盤（昨收）上＝+1、下＝−1、等於或昨收缺漏＝0。"""
    return np.sign(np.nan_to_num((df["close"] - df["prev_close"]).to_numpy(), nan=0.0)).astype(np.int8)


def t_gap(df, tf, daily):
    """開盤跳空方向：sign(今開 − 昨收)，整天不變。"""
    return np.sign(np.nan_to_num((df["sess_open"] - df["prev_close"]).to_numpy(), nan=0.0)).astype(np.int8)


def t_first_bar(df, tf, daily):
    """當日第一根K線紅＝+1、黑＝−1，第一根收盤起整天不變。"""
    first = df.groupby("session")["close"].transform("first") - df.groupby("session")["open"].transform("first")
    return np.sign(first.to_numpy()).astype(np.int8)


# ---- 日線層級（以 session 合成日K；第 d 日只用 d−1 日（含）以前已完成的日K）


def _daily_to_bars(df, daily, day_state: np.ndarray) -> np.ndarray:
    prev = pd.Series(day_state).shift(1).fillna(0).to_numpy()  # 用前一日收盤時已知的狀態
    return prev[df["session"].to_numpy()].astype(np.int8)


def t_cz_05_01(df, tf, daily):
    """cz-05-01：前一日收盤在年線（日 MA240）上＝+1、下＝−1。資料只有約 311 日，MA240 只在最後約 70 日有值。"""
    return _daily_to_bars(df, daily, _sign_carry((daily["close"] - sma(daily["close"], 240)).to_numpy()))


def t_gs_02(df, tf, daily):
    """gs-02：週KD(9,3,3) K>D 多方區域＝+1、K<D＝−1；只用上一個已完成的週（交叉隔週才確認，p.76）。
    週K由日K合成；前 9 週暖身不給方向。"""
    wk = daily["date"].dt.isocalendar()
    wkey = wk["year"].astype(int) * 100 + wk["week"].astype(int)
    widx = pd.factorize(wkey)[0]
    weekly = daily.groupby(widx).agg(open=("open", "first"), high=("high", "max"), low=("low", "min"),
                                     close=("close", "last"))
    k = kd(weekly, n=9)
    ws = np.sign((k["k"] - k["d"]).to_numpy())
    ws[:9] = 0
    day_state = np.array([ws[w - 1] if w >= 1 else 0 for w in widx])
    return day_state[df["session"].to_numpy()].astype(np.int8)


def t_gq_02(df, tf, daily):
    """gq-02 牛熊市：日 MA5 > MA20＝牛市 +1、反之 −1（gq_02_04 模組 trend_fast/trend_slow 推論預設），用前一日。"""
    c = daily["close"]
    return _daily_to_bars(df, daily, _sign_carry((sma(c, 5) - sma(c, 20)).to_numpy()))


TOOLS = [
    ("q2-01_MA30位置", "q2-01 收盤在 MA30 上/下", t_q2_01),
    ("q2-02_SAR", "q2-02 SAR 在價格下/上", t_q2_02),
    ("q2-03-01_PVT_L2", "q2-03-01 PVT 控盤方向（層級2）", t_q2_03_l2),
    ("q2-03-01_PVT_L4", "q2-03-01 PVT 控盤方向（層級4）", t_q2_03_l4),
    ("q2-04-01_15分KD", "q2-04-01 15 分KD 金叉區/死叉區", t_q2_04_01),
    ("q2-04-02_四柱_位置+根數", "q2-04-02 四柱：在關卡同側且根數占優的投票", t_q2_04_02_now),
    ("q2-04-02_四柱_根數", "q2-04-02 四柱：只比根數優劣的投票", t_q2_04_02_count),
    ("MA10方向", "q3-08-01/q3-08-02/q3-09-01 MA10 朝上/朝下", t_ma10_slope),
    ("MA10位置", "q3-08-01/q3-08-02/q3-09-01/sg-04 收盤在 MA10 上/下", t_ma10_pos),
    ("q3-11_30分MA100", "q3-11 30 分K 收盤在 MA100 上/下", t_q3_11),
    ("cz-04-01_河流全排列", "cz-04-01 河流圖全多排/全空排（其餘 0）", t_cz_04_01_full),
    ("cz-04-01_河流EMA55換位", "cz-04-00/gq-01-11 河流圖：EMA55 移到最下/最上認定多空", t_cz_04_01_regime),
    ("cz-04-02_EMA30/55", "cz-04-02 EMA30/EMA55 交叉", t_cz_04_02),
    ("cz-03-01_MA10/20", "cz-03-01 MA10/MA20 金叉區/死叉區", t_cz_03_01),
    ("gq-01-11_MA20/50", "gq-01-11 模組預設 SMA20/SMA50 交叉", t_gq_01_11_mod),
    ("gq-01-11_5日/3日均線", "gq-01-11 書中 MA300/MA180（5 日/3 日均線）交叉", t_gq_01_11_book),
    ("基準_平盤上下", "基準：價格在平盤（昨收）上/下", t_prev_close),
    ("基準_跳空方向", "基準：開盤跳空方向", t_gap),
    ("基準_首根K方向", "基準：當日第一根K線紅/黑", t_first_bar),
    ("cz-05-01_年線", "cz-05-01 前日收盤在日 MA240 上/下", t_cz_05_01),
    ("gs-02_週KD", "gs-02 週KD 多方/空方區域（上一完成週）", t_gs_02),
    ("gq-02_牛熊(日MA5/20)", "gq-02 牛熊市：日 MA5/MA20（前一日）", t_gq_02),
]


# ---------------------------------------------------------------- 評估


def forward_bp(df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """回傳 (fwd 點數 N×H, fwd bp N×H)。以時間找目標：第 i 根收盤時刻 + h 分鐘時已收盤的最後一根（同交易日內）。"""
    n = len(df)
    t = pd.to_datetime(df["time"]).to_numpy().astype("datetime64[m]").astype(np.int64)
    last_in_sess = df.groupby("session").cumcount(ascending=False).to_numpy() + np.arange(n)
    close = df["close"].to_numpy(float)
    out = np.zeros((n, len(HORIZONS)))
    for k, h in enumerate(HORIZONS):
        if h == "close":
            j = last_in_sess
        else:
            # time 為K線開始時刻：第 i 根收盤時刻 = t_i + 週期；目標 = 開始時刻 ≤ t_i + h 的最後一根（收盤於 i 收盤後 h 分鐘）
            j = np.searchsorted(t, t + h, side="right") - 1
            j = np.minimum(j, last_in_sess)
        out[:, k] = close[j] - close
    bp = out / df["sess_open"].to_numpy(float)[:, None] * 1e4
    return out, bp


def day_t(r: np.ndarray, day: np.ndarray) -> float:
    """平均 r（逐根等權，與 mean_bp 一致）的交易日群集穩健 t 值：
    SE² = Σ_日 (Σ_該日 (r − r̄))² / n²，處理同日內K線高度相關與 fwd 重疊。"""
    n = len(r)
    if n == 0:
        return np.nan
    mu = r.mean()
    g = pd.Series(r - mu).groupby(day).sum().to_numpy()
    if len(g) < 3:
        return np.nan
    se = np.sqrt((g ** 2).sum() * len(g) / (len(g) - 1)) / n
    return float(mu / se) if se > 0 else np.nan


def evaluate(key: str, desc: str, tf: int, d: np.ndarray, pts: np.ndarray, bp: np.ndarray,
             day: np.ndarray, half: np.ndarray, n_perm: int, rng: np.random.Generator) -> list[dict]:
    rows = []
    nz = np.flatnonzero(d)
    n = len(nz)
    if n == 0:
        return rows
    dz = d[nz].astype(np.float64)
    bpz = bp[nz]
    ptz = pts[nz]
    r_bp = dz[:, None] * bpz
    r_pt = dz[:, None] * ptz
    actual = r_bp.mean(axis=0)

    # 逐根置換（SPEC）：保留多空根數，打亂位置
    perm_means = np.empty((n_perm, bp.shape[1]))
    B = 50
    for b0 in range(0, n_perm, B):
        m = min(B, n_perm - b0)
        idx = rng.permuted(np.tile(np.arange(n), (m, 1)), axis=1)
        perm_means[b0:b0 + m] = (dz[idx] @ bpz) / n
    p_right = ((perm_means >= actual).sum(axis=0) + 1) / (n_perm + 1)
    p_left = ((perm_means <= actual).sum(axis=0) + 1) / (n_perm + 1)

    # 循環平移（補充，保留自相關）：c[k] = Σ_i d[(i−k) mod N]·bp[i]，用 FFT 一次算完所有平移
    N = len(d)
    shifts = rng.integers(int(N * 0.05), int(N * 0.95), size=n_perm)
    fd = np.fft.rfft(d.astype(np.float64))
    shift_means = np.empty((n_perm, bp.shape[1]))
    for k in range(bp.shape[1]):
        c = np.fft.irfft(np.fft.rfft(bp[:, k]) * np.conj(fd), n=N)  # c[s] = Σ_i d[i]·bp[i+s]
        shift_means[:, k] = c[shifts] / n
    sp_right = ((shift_means >= actual).sum(axis=0) + 1) / (n_perm + 1)

    drift = bp.mean(axis=0)
    frac_long = float((dz > 0).mean())
    dayz, halfz = day[nz], half[nz]
    subsets = {
        "全部": np.ones(n, bool),
        "前半": halfz == 0,
        "後半": halfz == 1,
        "多(+1)": dz > 0,
        "空(-1)": dz < 0,
    }
    for k, h in enumerate(HORIZONS):
        for sname, msk in subsets.items():
            rb, rp = r_bp[msk, k], r_pt[msk, k]
            nn = int(msk.sum())
            row = {
                "tool": key, "desc": desc, "tf": tf, "h": str(h), "subset": sname,
                "n_bars": nn, "n_days": int(len(np.unique(dayz[msk]))) if nn else 0,
                "frac_long": frac_long if sname == "全部" else np.nan,
                "hit_rate": float((rb > 0).sum() / max(1, (rb != 0).sum())) if nn else np.nan,
                "zero_share": float((rb == 0).mean()) if nn else np.nan,
                "mean_bp": float(rb.mean()) if nn else np.nan,
                "mean_pts": float(rp.mean()) if nn else np.nan,
                "t_day": day_t(rb, dayz[msk]) if nn else np.nan,
                "drift_bp": float(drift[k]),
            }
            if sname == "全部":
                row.update({
                    "perm_mean_bp": float(perm_means[:, k].mean()),
                    "perm_sd_bp": float(perm_means[:, k].std()),
                    "excess_bp": float(actual[k] - perm_means[:, k].mean()),
                    "p_perm": float(p_right[k]), "p_perm_left": float(p_left[k]),
                    "p_shift": float(sp_right[k]),
                })
            if sname in ("多(+1)", "空(-1)") and nn:
                sgn = 1 if sname.startswith("多") else -1
                row["excess_vs_drift_bp"] = float(rb.mean() - sgn * drift[k])
            rows.append(row)
    return rows


def verdict(m: pd.DataFrame) -> dict:
    """依 SPEC 判定（60 分鐘或到收盤任一符合即可）：
    有用：置換 p<0.05、前後兩半平均順向 bp 皆 >0、多空兩側都不是明顯負值（平均<0 且日群集 t≤−2）、樣本足（≥30 日）。
    反向：左尾置換 p<0.05 且前後兩半皆 <0。
    無法評估：總日數或任一半 < 30 個交易日（例如年線只在後半有值）。
    弱：置換 p<0.05 但其他條件有一項不符；或 0.05≤p<0.10 且兩半皆 >0。
    無：其餘。另附「保守」：有用者的循環平移 p 是否也 <0.05。"""
    best = None
    notes = []
    for h in ("60", "close"):
        a = m[(m.h == h) & (m.subset == "全部")].iloc[0]
        f = m[(m.h == h) & (m.subset == "前半")].iloc[0]
        s = m[(m.h == h) & (m.subset == "後半")].iloc[0]
        lo = m[(m.h == h) & (m.subset == "多(+1)")].iloc[0]
        sh = m[(m.h == h) & (m.subset == "空(-1)")].iloc[0]
        halves = f.mean_bp > 0 and s.mean_bp > 0
        both_neg = f.mean_bp < 0 and s.mean_bp < 0
        side_bad = []
        for nm, x in (("多", lo), ("空", sh)):
            if x.n_bars > 0 and x.mean_bp < 0 and (x.t_day <= -2):
                side_bad.append(nm)
        enough = a.n_days >= 30 and f.n_days >= 30 and s.n_days >= 30
        if not enough:
            v = "無法評估"
        elif a.p_perm < 0.05 and halves and not side_bad:
            v = "有用"
        elif a.p_perm_left < 0.05 and both_neg and enough:
            v = "反向"
        elif (a.p_perm < 0.05) or (a.p_perm < 0.10 and halves):
            v = "弱"
        else:
            v = "無"
        why = []
        if not enough:
            why.append("樣本不足/缺一半")
        if a.p_perm < 0.05 and not halves:
            why.append("僅一半為正")
        if side_bad:
            why.append("明顯負值側:" + "".join(side_bad))
        rank = {"有用": 3, "弱": 2, "無": 1, "反向": 1.5, "無法評估": -1}[v]
        cand = (rank, h, v, a.p_shift < 0.05, "、".join(why))
        notes.append(cand)
        if best is None or rank > best[0]:
            best = cand
    return {"verdict": best[2], "verdict_h": best[1], "conservative_ok": bool(best[3]) if best[2] == "有用" else None,
            "notes": best[4]}


# ---------------------------------------------------------------- 主程式


def daily_bars(df: pd.DataFrame) -> pd.DataFrame:
    g = df.groupby("session")
    d = g.agg(open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"),
              date=("time", "first"))
    d["date"] = pd.to_datetime(d["date"]).dt.normalize()
    return d.reset_index(drop=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf", default="1,3,5")
    ap.add_argument("--perm", type=int, default=1000)
    ap.add_argument("--tools", default="")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    only = set(args.tools.split(",")) if args.tools else None
    rows = []
    rng = np.random.default_rng(20260928)
    for tf in [int(x) for x in args.tf.split(",")]:
        df = prepare(pd.read_parquet(DATA / f"tx_day_{tf}min.parquet"))
        daily = daily_bars(df)
        pts, bp = forward_bp(df)
        day = df["session"].to_numpy()
        half = (pd.to_datetime(df["time"]) >= SPLIT).to_numpy().astype(int)
        for key, desc, fn in TOOLS:
            if only and key not in only:
                continue
            t0 = time.time()
            d = np.asarray(fn(df, tf, daily), dtype=np.int8)
            assert len(d) == len(df)
            rows += evaluate(key, desc, tf, d, pts, bp, day, half, args.perm, rng)
            print(f"{tf}m {key}: {time.time() - t0:.1f}s  非0根數={int((d != 0).sum())}", flush=True)
    met = pd.DataFrame(rows)
    met.to_csv(OUT / "state_metrics.csv", index=False, encoding="utf-8-sig")
    ver = []
    for (tool, tf), m in met.groupby(["tool", "tf"], sort=False):
        v = verdict(m)
        g = {h: m[(m.h == h) & (m.subset == "全部")].iloc[0] for h in ("60", "close")}
        side = {(h, s): m[(m.h == h) & (m.subset == s)].iloc[0] for h in ("60", "close")
                for s in ("前半", "後半", "多(+1)", "空(-1)")}
        ver.append({
            "tool": tool, "desc": m["desc"].iat[0], "tf": tf, **v,
            "n_bars": int(g["60"].n_bars), "n_days": int(g["60"].n_days), "frac_long": g["60"].frac_long,
            **{f"{k}_{h}": g[h][k] for h in ("60", "close")
               for k in ("mean_bp", "hit_rate", "excess_bp", "p_perm", "p_perm_left", "p_shift", "drift_bp", "t_day")},
            **{f"{s}_{h}_bp": side[(h, s)].mean_bp for h in ("60", "close") for s in ("前半", "後半", "多(+1)", "空(-1)")},
        })
    pd.DataFrame(ver).to_csv(OUT / "state_verdict.csv", index=False, encoding="utf-8-sig")
    print(pd.DataFrame(ver)[["tool", "tf", "verdict", "verdict_h", "conservative_ok", "mean_bp_60", "p_perm_60",
                             "mean_bp_close", "p_perm_close", "notes"]].to_string())


if __name__ == "__main__":
    main()
