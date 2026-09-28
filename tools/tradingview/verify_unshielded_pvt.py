"""驗證 unshielded_pvt.pine 的逐根語意與本專案 Python 版一致。

用法：
    uv run python tools/tradingview/verify_unshielded_pvt.py

做法：無法執行 Pine，所以在這裡用 Python「模擬 Pine 逐根執行」：
  - 每根呼叫一次 step()，var 變數放在物件屬性（跨根保留），非 var 變數每根重新宣告；
  - 敘述順序、分支、比較運算與 .pine 一行對一行（變數名稱相同）。
再拿模擬結果和原本的 Python 逐根比對：
  1. 無遮蔽：methods/期貨奇績1/wang_unshielded.py 的 wang_afl()
     比對 short/long 訊號，以及判斷當下的兩條無遮蔽線（line_s、line_l）。
  2. PVT（倍數 1）：src/wangtrader/methods/q2_03_01_pvt_n_type.py 的 PVTNType
     逐根呼叫 on_bar（無部位），記錄每根結束時的 bull_ladder、bear_ladder、regime 比對。
  3. PVT（倍數 3）：scripts/direction_unshielded_pvt.py 的「3倍」實驗——
     data_mtf/ 大週期K（1 分K 每日自 08:45 resample）上跑 direction_state._pvt_regime，
     再用 map_htf(lag=True) 映射到小週期；Pine 模擬則在小週期K上自行手動聚合。
     比對控盤方向（另比上緣、下緣），並檢查「發展中暫定階梯」在大週期最後一根成分K上
     等於下一根的已確認值。組合：5→15、3→9、2→6、1→3 分，level 2／4。
  4. 3x 均線：手動聚合＋合成序列公式算出的已收完值，對 data_mtf 大週期收盤直接算的
     SMA／linreg／Hull 映射後比對（只驗證聚合與公式移植，不驗證 TradingView 內建函式）。
需要 data_mtf/（由 scripts/direction_unshielded_pvt.py 產生）。只讀資料，不寫任何檔案。
"""

from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wangtrader.core.bars import prepare  # noqa: E402
from wangtrader.core.engine import Context  # noqa: E402
from wangtrader.methods.q2_03_01_pvt_n_type import PVTNType  # noqa: E402

_spec = importlib.util.spec_from_file_location("wang_unshielded", ROOT / "methods" / "期貨奇績1" / "wang_unshielded.py")
wang_unshielded = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wang_unshielded)

NA = float("nan")


def na(x) -> bool:
    return x is None or (isinstance(x, float) and math.isnan(x))


# ---------------------------------------------------------------------------
# Pine 模擬：無遮蔽（對應 .pine 第一段）
# ---------------------------------------------------------------------------
class PineUnshielded:
    def __init__(self, fix_init: bool = False):
        self.fix_init = fix_init
        # var 宣告（只在第 0 根初始化一次）
        self.hh = self.hl = self.lineS = self.lh = self.ll = self.lineL = 0.0
        self.resetFlag = False

    def step(self, bar_index, is_new_day, o, h, l, c):
        s = self
        sigShort = False
        sigLong = False
        chkLineS = NA
        chkLineL = NA
        usActive = s.fix_init or bar_index >= 2
        if usActive:
            if (s.fix_init and bar_index == 0) or is_new_day or s.resetFlag:
                s.resetFlag = False
                s.hh, s.hl, s.lineS = h, l, l
                s.lh, s.ll, s.lineL = h, l, h
            else:
                if h > s.hh:
                    s.hh, s.hl, s.lineS = h, l, l
                elif h == s.hh and l > s.hl:
                    s.hh, s.hl, s.lineS = h, l, l
                if l < s.ll:
                    s.lh, s.ll, s.lineL = h, l, h
                elif l == s.ll and h < s.lh:
                    s.lh, s.ll, s.lineL = h, l, h
                chkLineS = s.lineS
                if c < s.lineS and h < s.hl and c < o and o - c > c - l:
                    sigShort = True
                    s.lh, s.ll, s.lineL = h, l, h
                    s.resetFlag = True
                elif l < s.lineS:
                    s.lineS = l
                chkLineL = s.lineL
                if c > s.lineL and l > s.lh and o < c and c - o > h - c:
                    sigLong = True
                    s.hh, s.hl, s.lineS = h, l, l
                    s.resetFlag = True
                elif h > s.lineL:
                    s.lineL = h
        return sigShort, sigLong, chkLineS, chkLineL


# ---------------------------------------------------------------------------
# Pine 模擬：PVT（對應 .pine 第二段）
# ---------------------------------------------------------------------------
MAX_PLATEAU = 4


def f_group(v, j, n, is_peak):
    e, dip, k, st, go = j, False, j + 1, 1, True
    while go:
        if k - j >= MAX_PLATEAU:
            go = False
        elif k >= n:
            st, go = 0, False
        else:
            vj, vk = v[j], v[k]
            if vk == vj:
                e = k
                k += 1
            elif not dip and (vj > vk if is_peak else vj < vk):
                if k + 1 >= n:
                    st, go = 0, False
                elif v[k + 1] == vj:
                    dip, e = True, k + 1
                    k += 2
                else:
                    go = False
            else:
                go = False
    return st, e


def f_is_pivot(v, s, e, lvl, is_peak):
    p, ok = v[s], True
    lo = max(0, s - lvl)
    if s - 1 >= lo:
        for x in range(lo, s):
            if not (p > v[x] if is_peak else p < v[x]):
                ok = False
                break
    if ok:
        for x in range(e + 1, e + lvl + 1):
            if not (p > v[x] if is_peak else p < v[x]):
                ok = False
                break
    return ok


def f_advance(v, j0, pendS, pendE, lvl, is_peak):
    n, j, go = len(v), j0, True
    while go and j < n:
        st, e = f_group(v, j, n, is_peak)
        if st == 0:
            go = False
        else:
            pendS.append(j)
            pendE.append(e)
            j = e + 1
    confirmed = NA
    t = n - 1
    while pendE and pendE[0] + lvl <= t:
        s = pendS.pop(0)
        e2 = pendE.pop(0)
        if e2 + lvl == t and f_is_pivot(v, s, e2, lvl, is_peak):
            confirmed = v[s]
    return j, confirmed


def f_ladder(trNew, pkNew, c, ign, bL, bA, sL, sA, rg, t1, t2, p1, p2):
    """.pine f_ladder：步驟 1（更新階梯）＋步驟 2（控盤易主），純函式。"""
    if not na(trNew):
        if na(bA):
            bA = trNew
        elif abs(trNew - bA) > ign:
            bL = min(bA, trNew)
            bA = trNew
        t2, t1 = t1, trNew
    if not na(pkNew):
        if na(sA):
            sA = pkNew
        elif abs(pkNew - sA) > ign:
            sL = max(sA, pkNew)
            sA = pkNew
        p2, p1 = p1, pkNew
    swBull = not na(sL) and c > sL and rg != 1
    swBear = not na(bL) and c < bL and rg != -1
    if rg == 0:
        swBull = swBull or (not na(bL) and c > bL)
        swBear = swBear or (not na(sL) and c < sL)
    if swBull:
        rg = 1
        if not na(t1):
            seed = t1 if na(t2) else min(t1, t2)
            bL = bA = seed
    elif swBear:
        rg = -1
        if not na(p1):
            seed = p1 if na(p2) else max(p1, p2)
            sL = sA = seed
    return bL, bA, sL, sA, rg, t1, t2, p1, p2


class PinePVT:
    """.pine 第二段：N 倍週期手動聚合＋已確認 PVT＋發展中暫定階梯。"""

    def __init__(self, level=2, ignore=2.0, mult=1):
        self.level, self.ignore, self.mult = level, ignore, mult
        self.pvH, self.pvL = [], []
        self.pkPendS, self.pkPendE, self.trPendS, self.trPendE = [], [], [], []
        self.pkJ = self.trJ = 0
        self.bullLadder = self.bullAdopted = self.bearLadder = self.bearAdopted = NA
        self.regime = 0
        self.trLast1 = self.trLast2 = self.pkLast1 = self.pkLast2 = NA
        # 聚合狀態
        self.dayT0 = None
        self.prevGid = None
        self.pdH = self.pdL = self.pdC = NA
        self.pdNewDay = False

    def _state(self):
        return (self.bullLadder, self.bullAdopted, self.bearLadder, self.bearAdopted, self.regime,
                self.trLast1, self.trLast2, self.pkLast1, self.pkLast2)

    def step(self, bar_index, is_new_day, t_ms, tf_ms, h, l, c):
        s = self
        # 換日與分組（.pine：dayT0／f_gid／pvStart）
        if is_new_day or s.dayT0 is None:
            s.dayT0 = t_ms
        firstBar = bar_index == 0
        pvGid = int(math.floor((t_ms - s.dayT0) / (s.mult * tf_ms)))
        pvStart = is_new_day or firstBar or pvGid != s.prevGid
        s.prevGid = pvGid
        pvDo, fH, fL, fC, fNewDay = False, NA, NA, NA, False
        if s.mult == 1:
            pvDo, fH, fL, fC, fNewDay = True, h, l, c, is_new_day
        else:
            if pvStart:
                if not na(s.pdH):
                    pvDo, fH, fL, fC, fNewDay = True, s.pdH, s.pdL, s.pdC, s.pdNewDay
                s.pdH, s.pdL, s.pdC = h, l, c
                s.pdNewDay = is_new_day or firstBar
            else:
                s.pdH = max(s.pdH, h)
                s.pdL = min(s.pdL, l)
                s.pdC = c
        s.pvDo = pvDo
        s.pkNew = s.trNew = NA
        if pvDo:
            if fNewDay:
                s.pvH.clear(); s.pvL.clear()
                s.pkPendS.clear(); s.pkPendE.clear(); s.trPendS.clear(); s.trPendE.clear()
                s.pkJ = s.trJ = 0
            s.pvH.append(fH)
            s.pvL.append(fL)
            s.pkJ, pkC = f_advance(s.pvH, s.pkJ, s.pkPendS, s.pkPendE, s.level, True)
            s.trJ, trC = f_advance(s.pvL, s.trJ, s.trPendS, s.trPendE, s.level, False)
            s.pkNew, s.trNew = pkC, trC
            (s.bullLadder, s.bullAdopted, s.bearLadder, s.bearAdopted, s.regime,
             s.trLast1, s.trLast2, s.pkLast1, s.pkLast2) = f_ladder(trC, pkC, fC, s.ignore, *s._state())
        # 發展中暫定（全部在副本上）
        s.devBull = s.devBear = NA
        s.devRg = None
        if s.mult > 1 and not na(s.pdH):
            tH, tL = list(s.pvH), list(s.pvL)
            tPkS, tPkE, tTrS, tTrE = list(s.pkPendS), list(s.pkPendE), list(s.trPendS), list(s.trPendE)
            tPkJ, tTrJ = s.pkJ, s.trJ
            if s.pdNewDay:
                tH, tL, tPkS, tPkE, tTrS, tTrE = [], [], [], [], [], []
                tPkJ = tTrJ = 0
            tH.append(s.pdH)
            tL.append(s.pdL)
            _, dPk = f_advance(tH, tPkJ, tPkS, tPkE, s.level, True)
            _, dTr = f_advance(tL, tTrJ, tTrS, tTrE, s.level, False)
            d = f_ladder(dTr, dPk, s.pdC, s.ignore, *s._state())
            s.devBull, s.devBear, s.devRg = d[0], d[2], d[4]
        return s.bullLadder, s.bearLadder, s.regime


# ---------------------------------------------------------------------------
# 比對
# ---------------------------------------------------------------------------
def new_day_flags(idx: pd.DatetimeIndex, mode: str) -> np.ndarray:
    """timeframe.change("D") 在日盤資料上等於「日期與前一根不同」；AFL 模式用 TimeNum 倒退。
    第 0 根：兩種模式都視為 True（照原樣模式第 0 根不處理，PVT 清空空陣列無影響）。"""
    if mode == "tf":
        d = idx.normalize()
        flag = np.r_[True, d[1:] != d[:-1]]
    else:
        tn = (idx.hour * 10000 + idx.minute * 100 + idx.second).to_numpy()
        flag = np.r_[True, tn[:-1] > tn[1:]]
    return flag


def same(a, b) -> np.ndarray:
    a, b = np.asarray(a, float), np.asarray(b, float)
    return (a == b) | (np.isnan(a) & np.isnan(b))


def to_ms(idx) -> np.ndarray:
    """K 棒開始時刻（Pine time，毫秒）。只用到同日內的差值，時區不影響。"""
    return (pd.DatetimeIndex(idx).as_unit("ns").asi8 // 1_000_000).astype(np.int64)


def bar_ms(idx) -> int:
    """圖表週期（Pine timeframe.in_seconds() × 1000）：取相鄰 K 棒時間差的眾數。"""
    d = np.diff(pd.DatetimeIndex(idx).as_unit("ns").asi8) // 1_000_000
    v, n = np.unique(d, return_counts=True)
    return int(v[n.argmax()])


def verify_unshielded(df: pd.DataFrame, label: str) -> bool:
    idx = df.index
    O, H, L, C = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    tn = (idx.hour * 10000 + idx.minute * 100 + idx.second).to_numpy()
    ref = wang_unshielded.wang_afl(tn, O, H, L, C)
    ok_all = True
    for mode in ("tf", "afl"):
        flags = new_day_flags(idx, mode)
        sim = PineUnshielded(fix_init=False)
        out = [sim.step(i, flags[i], O[i], H[i], L[i], C[i]) for i in range(len(df))]
        s_, l_, ls, ll = (np.array(x) for x in zip(*out))
        m_s = s_.astype(int) == ref["short"]
        m_l = l_.astype(int) == ref["long"]
        m_ls, m_ll = same(ls, ref["line_s"]), same(ll, ref["line_l"])
        n_sig = int(ref["short"].sum() + ref["long"].sum())
        match_sig = int(((s_ & (ref["short"] == 1)) | (l_ & (ref["long"] == 1))).sum())
        extra = int((s_ & (ref["short"] == 0)).sum() + (l_ & (ref["long"] == 0)).sum())
        ok = m_s.all() and m_l.all() and m_ls.all() and m_ll.all()
        ok_all &= ok
        print(f"[無遮蔽/{label}/換日={mode}] 參考訊號 {n_sig}，模擬命中 {match_sig}（{match_sig / max(n_sig, 1):.2%}），"
              f"多出 {extra}；逐根一致：訊號 {m_s.mean() * m_l.mean():.4%}，"
              f"無遮蔽線 {m_ls.mean() * m_ll.mean():.4%} → {'OK' if ok else 'MISMATCH'}")
    # 修正模式：預期只少掉資料起點的假訊號
    flags = new_day_flags(idx, "tf")
    sim = PineUnshielded(fix_init=True)
    out = [sim.step(i, flags[i], O[i], H[i], L[i], C[i]) for i in range(len(df))]
    s_, l_ = (np.array(x) for x in list(zip(*out))[:2])
    diff = np.flatnonzero((s_.astype(int) != ref["short"]) | (l_.astype(int) != ref["long"]))
    print(f"[無遮蔽/{label}/修正初值] 與照原樣不同的 K 棒 {len(diff)} 根：",
          [(str(idx[i]), "多" if ref["long"][i] else "空" if ref["short"][i] else "新增") for i in diff])
    return ok_all


def verify_pvt(df: pd.DataFrame, label: str, level: int) -> bool:
    pdf = prepare(df)
    strat = PVTNType(pivot_level=level)
    pdf = strat.prepare(pdf)
    ref = []
    for i in range(len(pdf)):
        strat.on_bar(Context(i, pdf, None, [], None))
        st = strat._st
        rg = {"bull": 1, "bear": -1, None: 0}[st["regime"]]
        ref.append((NA if st["bull_ladder"] is None else st["bull_ladder"],
                    NA if st["bear_ladder"] is None else st["bear_ladder"], rg))
    ref_bull, ref_bear, ref_rg = (np.array(x, float) for x in zip(*ref))

    flags = new_day_flags(df.index, "tf")
    sim = PinePVT(level=level, ignore=strat.p.ladder_ignore_diff, mult=1)
    H, L, C = (df[k].to_numpy(float) for k in ("high", "low", "close"))
    t_ms = to_ms(df.index)
    tf_ms = bar_ms(df.index)
    out, sim_pk, sim_tr = [], {}, {}
    for i in range(len(df)):
        out.append(sim.step(i, flags[i], t_ms[i], tf_ms, H[i], L[i], C[i]))
        if not na(sim.pkNew):
            sim_pk[i] = sim.pkNew
        if not na(sim.trNew):
            sim_tr[i] = sim.trNew
    # 轉折點本身：確認的 K 棒與價格要和 Python _pivots_by_session 完全相同
    ref_pk = {p.confirm: p.price for lst in strat._peaks_by_confirm.values() for p in lst}
    ref_tr = {p.confirm: p.price for lst in strat._troughs_by_confirm.values() for p in lst}
    piv_ok = sim_pk == ref_pk and sim_tr == ref_tr
    print(f"[PVT/{label}/level={level}] 轉折點：峰 {len(ref_pk)}／谷 {len(ref_tr)}（Python），"
          f"峰 {len(sim_pk)}／谷 {len(sim_tr)}（模擬），確認位置與價格 {'完全相同' if piv_ok else '不同'}")
    s_bull, s_bear, s_rg = (np.array(x, float) for x in zip(*out))
    mb, ms, mr = same(s_bull, ref_bull), same(s_bear, ref_bear), same(s_rg, ref_rg)
    ok = piv_ok and mb.all() and ms.all() and mr.all()
    switches = int((np.diff(ref_rg) != 0).sum())
    print(f"[PVT/{label}/level={level}] {len(df)} 根，易主 {switches} 次；逐根一致：下緣 {mb.mean():.4%}、"
          f"上緣 {ms.mean():.4%}、控盤方向 {mr.mean():.4%} → {'OK' if ok else 'MISMATCH'}")
    if not ok:
        bad = np.flatnonzero(~(mb & ms & mr))[:5]
        for i in bad:
            print("   ", df.index[i], "ref", ref_bull[i], ref_bear[i], ref_rg[i], "sim", s_bull[i], s_bear[i], s_rg[i])
    return ok


# ---------------------------------------------------------------------------
# N 倍週期：與 scripts/direction_unshielded_pvt.py 的「3倍」實驗比對
# ---------------------------------------------------------------------------
_dup = None


def dup():
    """延遲載入 scripts/direction_unshielded_pvt.py（只用其 load／map_htf 與 direction_state._pvt_regime，不執行 main）。"""
    global _dup
    if _dup is None:
        sp = importlib.util.spec_from_file_location("direction_unshielded_pvt", ROOT / "scripts" / "direction_unshielded_pvt.py")
        _dup = importlib.util.module_from_spec(sp)
        sp.loader.exec_module(_dup)
    return _dup


def load_ltf(tf: int) -> pd.DataFrame:
    """小週期（圖表）K 棒：2/3/5 分用 data_mtf（與 3倍 實驗相同）；1 分用來源 data/tx_day_1min.parquet。"""
    if tf != 1:
        return dup().load(tf)
    df = pd.read_parquet(ROOT / "data" / "tx_day_1min.parquet")
    df["minutes"] = 1
    df = prepare(df)
    df["time"] = pd.to_datetime(df["time"])
    df["close_time"] = df["time"] + pd.to_timedelta(df["minutes"], unit="min")
    df["date"] = df["time"].dt.normalize()
    return df


def ref_htf_ladders(htf: pd.DataFrame, level: int):
    """同 direction_state._pvt_regime 的逐根推進，另外記下每根結束時的上緣／下緣。"""
    s = PVTNType(pivot_level=level)
    s.prepare(htf)
    st = s._fresh()
    close = htf["close"].to_numpy(float)
    bull, bear = np.full(len(htf), NA), np.full(len(htf), NA)
    for i in range(len(htf)):
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
        bull[i] = NA if st["bull_ladder"] is None else st["bull_ladder"]
        bear[i] = NA if st["bear_ladder"] is None else st["bear_ladder"]
    return bull, bear, s.p.ladder_ignore_diff


def htf_pos(htf: pd.DataFrame, ltf: pd.DataFrame) -> np.ndarray:
    """每根小週期 K 採用的大週期 K 位置：最後一根收盤時刻 ≤ 小週期開始時刻者（map_htf lag=True 同一規則），沒有則 −1。"""
    hc = htf["close_time"].to_numpy()
    assert (np.diff(hc.astype("int64")) > 0).all()
    return np.searchsorted(hc, ltf["time"].to_numpy(), side="right") - 1


def verify_pvt_mult(ltf_tf: int, mult: int, level: int) -> bool:
    d = dup()
    htf_tf = ltf_tf * mult
    htf, ltf = d.load(htf_tf), load_ltf(ltf_tf)
    # 參考：direction_unshielded_pvt 的 3倍 實驗 ＝ _pvt_regime(大週期) → map_htf(lag=True)
    ref_rg = d.map_htf(d.ds._pvt_regime(htf, level), htf, ltf, False, True).astype(float)
    hb, hs, ign = ref_htf_ladders(htf, level)
    pos = htf_pos(htf, ltf)
    ref_bull = np.where(pos >= 0, hb[np.maximum(pos, 0)], NA)
    ref_bear = np.where(pos >= 0, hs[np.maximum(pos, 0)], NA)

    t = ltf["time"]
    dates = t.dt.normalize().to_numpy()
    flags = np.r_[True, dates[1:] != dates[:-1]]
    t_ms = to_ms(t)
    tf_ms = ltf_tf * 60_000
    H, L, C = (ltf[k].to_numpy(float) for k in ("high", "low", "close"))
    sim = PinePVT(level=level, ignore=ign, mult=mult)
    n = len(ltf)
    s_bull, s_bear, s_rg = np.full(n, NA), np.full(n, NA), np.zeros(n)
    dev_bull, dev_bear, dev_rg = np.full(n, NA), np.full(n, NA), np.full(n, NA)
    pv_do = np.zeros(n, bool)
    for i in range(n):
        s_bull[i], s_bear[i], s_rg[i] = sim.step(i, flags[i], t_ms[i], tf_ms, H[i], L[i], C[i])
        dev_bull[i], dev_bear[i] = sim.devBull, sim.devBear
        dev_rg[i] = NA if sim.devRg is None else sim.devRg
        pv_do[i] = sim.pvDo
    mr, mb, ms = same(s_rg, ref_rg), same(s_bull, ref_bull), same(s_bear, ref_bear)
    # 推進次數＝大週期根數 −1（最後一根要等下一根小週期 K 才推進，資料結束時沒有下一根）
    n_do = int(pv_do.sum())
    # 發展中暫定：大週期最後一根成分 K 的暫定值，要等於下一根（推進後）已確認值
    last = np.flatnonzero(pv_do)[0:] - 1
    last = last[last >= 0]
    dv = same(dev_rg[last], s_rg[last + 1]) & same(dev_bull[last], s_bull[last + 1]) & same(dev_bear[last], s_bear[last + 1])
    ok = mr.all() and mb.all() and ms.all() and n_do == len(htf) - 1 and dv.all()
    switches = int((np.diff(ref_rg) != 0).sum())
    dev_diff = float(((dev_rg != s_rg) & ~np.isnan(dev_rg)).mean())
    print(f"[PVT×{mult}/{ltf_tf}分→{htf_tf}分/level={level}] {n} 根（大週期 {len(htf)} 根，推進 {n_do} 次），易主 {switches} 次；"
          f"逐根一致：控盤方向 {mr.mean():.4%}（{int(mr.sum())}/{n}）、下緣 {mb.mean():.4%}、上緣 {ms.mean():.4%}；"
          f"暫定→確認銜接 {dv.mean():.4%}（{len(last)} 組）；暫定方向≠已確認的K棒 {dev_diff:.2%} → {'OK' if ok else 'MISMATCH'}")
    if not ok:
        for i in np.flatnonzero(~(mr & mb & ms))[:5]:
            print("   ", ltf["time"].iat[i], "ref", ref_bull[i], ref_bear[i], ref_rg[i], "sim", s_bull[i], s_bear[i], s_rg[i])
    return ok


# ---------------------------------------------------------------------------
# 3x 均線：close 手動聚合＋合成序列公式（.pine 第三段 f_sma_syn／f_lsma_syn／f_hma_syn）
# ---------------------------------------------------------------------------
def f_syn(arr, dev, age):
    m = len(arr)
    synN = m + (0 if na(dev) else 1)
    idx = synN - 1 - age
    if idx < 0:
        return NA
    return arr[idx] if idx < m else dev


def f_sma_syn(arr, dev, N):
    synN = len(arr) + (0 if na(dev) else 1)
    if synN < N:
        return NA
    return sum(f_syn(arr, dev, i) for i in range(N)) / N


def f_lsma_syn(arr, dev, N):
    synN = len(arr) + (0 if na(dev) else 1)
    if synN < N:
        return NA
    sx = sy = sxx = sxy = 0.0
    for i in range(N):
        yv = f_syn(arr, dev, N - 1 - i)
        sx += i; sy += yv; sxx += i * i; sxy += i * yv
    den = N * sxx - sx * sx
    if den == 0:
        return NA
    slope = (N * sxy - sx * sy) / den
    return (sy - slope * sx) / N + slope * (N - 1)


def f_wma_syn(arr, dev, L, shift):
    synN = len(arr) + (0 if na(dev) else 1)
    if synN - shift - L < 0:
        return NA
    num = den = 0.0
    for i in range(L):
        num += f_syn(arr, dev, shift + L - 1 - i) * (i + 1)
        den += i + 1
    return num / den


def f_hma_syn(arr, dev, ln):
    half, sq = ln // 2, int(math.floor(math.sqrt(ln)))
    num = den = 0.0
    for k in range(sq):
        sh = sq - 1 - k
        wh, wf = f_wma_syn(arr, dev, half, sh), f_wma_syn(arr, dev, ln, sh)
        if na(wh) or na(wf):
            return NA
        num += (2.0 * wh - wf) * (k + 1)
        den += k + 1
    return num / den if den > 0 else NA


def _wma(x: np.ndarray, L: int) -> np.ndarray:
    w = np.arange(1, L + 1, dtype=float)
    out = np.full(len(x), NA)
    for i in range(L - 1, len(x)):
        out[i] = (x[i - L + 1:i + 1] * w).sum() / w.sum()
    return out


def verify_ma3(ltf_tf: int, lens=(50, 100, 50)) -> bool:
    """3x 已收完值（conf）＝對 data_mtf 大週期收盤直接算 SMA／linreg／Hull 再照 lag 規則映射；
    3x 發展中值（dev）在大週期最後一根成分 K 上＝下一根的 conf。"""
    d = dup()
    htf, ltf = d.load(ltf_tf * 3), load_ltf(ltf_tf)
    hc = htf["close"].to_numpy(float)
    nS, nL, nH = lens
    r_sma = pd.Series(hc).rolling(nS).mean().to_numpy()
    r_lsma = np.full(len(hc), NA)
    xs = np.arange(nL, dtype=float)
    for i in range(nL - 1, len(hc)):
        b, a = np.polyfit(xs, hc[i - nL + 1:i + 1], 1)
        r_lsma[i] = a + b * (nL - 1)
    raw = 2 * _wma(hc, nH // 2) - _wma(hc, nH)
    r_hma = np.full(len(hc), NA)
    sq = int(math.floor(math.sqrt(nH)))
    ok_raw = ~np.isnan(raw)
    tmp = _wma(np.where(ok_raw, raw, 0.0), sq)
    valid = pd.Series(ok_raw).rolling(sq).sum().to_numpy() == sq
    r_hma[valid] = tmp[valid]
    pos = htf_pos(htf, ltf)
    t = ltf["time"]
    dates = t.dt.normalize().to_numpy()
    flags = np.r_[True, dates[1:] != dates[:-1]]
    t_ms, tf_ms = to_ms(t), ltf_tf * 60_000
    C = ltf["close"].to_numpy(float)
    m3c, m3d, dayT0, prev = [], NA, None, None
    conf, dev, starts = [], [], []
    for i in range(len(ltf)):
        if flags[i] or dayT0 is None:
            dayT0 = t_ms[i]
        gid = int(math.floor((t_ms[i] - dayT0) / (3 * tf_ms)))
        start = flags[i] or i == 0 or gid != prev
        prev = gid
        if start and not na(m3d):
            m3c.append(m3d)
        m3d = C[i]
        conf.append((f_sma_syn(m3c, NA, nS), f_lsma_syn(m3c, NA, nL), f_hma_syn(m3c, NA, nH)))
        dev.append((f_sma_syn(m3c, m3d, nS), f_lsma_syn(m3c, m3d, nL), f_hma_syn(m3c, m3d, nH)))
        starts.append(start)
    conf, dev, starts = np.array(conf), np.array(dev), np.array(starts)
    ok = True
    msg = []
    for k, (name, r) in enumerate((("SMA", r_sma), ("LSMA", r_lsma), ("HMA", r_hma))):
        ref = np.where(pos >= 0, r[np.maximum(pos, 0)], NA)
        a = conf[:, k]
        close_ = np.isclose(a, ref, rtol=0, atol=1e-6) | (np.isnan(a) & np.isnan(ref))
        nxt = np.flatnonzero(starts)[1:]
        dv = np.isclose(dev[nxt - 1, k], conf[nxt, k], rtol=0, atol=1e-9) | (np.isnan(dev[nxt - 1, k]) & np.isnan(conf[nxt, k]))
        ok &= close_.all() and dv.all()
        msg.append(f"{name} conf {close_.mean():.4%}／dev→conf {dv.mean():.4%}")
    print(f"[3x均線/{ltf_tf}分→{ltf_tf * 3}分] " + "；".join(msg) + f" → {'OK' if ok else 'MISMATCH'}")
    return ok


def main():
    d5 = pd.read_parquet(ROOT / "data" / "tx_day_5min.parquet")
    d1 = pd.read_parquet(ROOT / "data" / "tx_day_1min.parquet")
    ok = True
    ok &= verify_unshielded(d5, "5分全期")
    ok &= verify_unshielded(d1, "1分全期")
    ok &= verify_pvt(d5, "5分全期", 2)
    ok &= verify_pvt(d5, "5分全期", 4)
    ok &= verify_pvt(d1, "1分全期", 2)
    # 倍數 3：與 direction_unshielded_pvt.py 的 3倍 實驗（data_mtf 大週期＋map_htf lag）逐根比對
    if (ROOT / "data_mtf" / "tx_day_15min.parquet").exists():
        for ltf_tf in (5, 3, 2, 1):
            for level in (2, 4):
                ok &= verify_pvt_mult(ltf_tf, 3, level)
        ok &= verify_ma3(5)
    else:
        print("找不到 data_mtf/（先跑 uv run python scripts/direction_unshielded_pvt.py 合成多週期K），略過倍數 3 驗證")
        ok = False
    print("全部一致" if ok else "有不一致")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
