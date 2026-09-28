"""驗證 unshielded_pvt.pine 的逐根語意與本專案 Python 版一致。

用法：
    uv run python tools/tradingview/verify_unshielded_pvt.py

做法：無法執行 Pine，所以在這裡用 Python「模擬 Pine 逐根執行」：
  - 每根呼叫一次 step()，var 變數放在物件屬性（跨根保留），非 var 變數每根重新宣告；
  - 敘述順序、分支、比較運算與 .pine 一行對一行（變數名稱相同）。
再拿模擬結果和原本的 Python 逐根比對：
  1. 無遮蔽：methods/期貨奇績1/wang_unshielded.py 的 wang_afl()
     比對 short/long 訊號，以及判斷當下的兩條無遮蔽線（line_s、line_l）。
  2. PVT：src/wangtrader/methods/q2_03_01_pvt_n_type.py 的 PVTNType
     逐根呼叫 on_bar（無部位），記錄每根結束時的 bull_ladder、bear_ladder、regime 比對。
只讀資料，不寫任何檔案。
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


class PinePVT:
    def __init__(self, level=2, ignore=2.0):
        self.level, self.ignore = level, ignore
        self.pvH, self.pvL = [], []
        self.pkPendS, self.pkPendE, self.trPendS, self.trPendE = [], [], [], []
        self.pkJ = self.trJ = 0
        self.bullLadder = self.bullAdopted = self.bearLadder = self.bearAdopted = NA
        self.regime = 0
        self.trLast1 = self.trLast2 = self.pkLast1 = self.pkLast2 = NA

    def step(self, is_new_day, h, l, c):
        s = self
        if is_new_day:
            s.pvH.clear(); s.pvL.clear()
            s.pkPendS.clear(); s.pkPendE.clear(); s.trPendS.clear(); s.trPendE.clear()
            s.pkJ = s.trJ = 0
        s.pvH.append(h)
        s.pvL.append(l)
        pkJn, pkNew = f_advance(s.pvH, s.pkJ, s.pkPendS, s.pkPendE, s.level, True)
        trJn, trNew = f_advance(s.pvL, s.trJ, s.trPendS, s.trPendE, s.level, False)
        s.pkJ, s.trJ = pkJn, trJn
        s.pkNew, s.trNew = pkNew, trNew  # 驗證用：本根確認的轉折點（.pine 同名區域變數）
        if not na(trNew):
            if na(s.bullAdopted):
                s.bullAdopted = trNew
            elif abs(trNew - s.bullAdopted) > s.ignore:
                s.bullLadder = min(s.bullAdopted, trNew)
                s.bullAdopted = trNew
            s.trLast2, s.trLast1 = s.trLast1, trNew
        if not na(pkNew):
            if na(s.bearAdopted):
                s.bearAdopted = pkNew
            elif abs(pkNew - s.bearAdopted) > s.ignore:
                s.bearLadder = max(s.bearAdopted, pkNew)
                s.bearAdopted = pkNew
            s.pkLast2, s.pkLast1 = s.pkLast1, pkNew
        swBull = not na(s.bearLadder) and c > s.bearLadder and s.regime != 1
        swBear = not na(s.bullLadder) and c < s.bullLadder and s.regime != -1
        if s.regime == 0:
            swBull = swBull or (not na(s.bullLadder) and c > s.bullLadder)
            swBear = swBear or (not na(s.bearLadder) and c < s.bearLadder)
        if swBull:
            s.regime = 1
            if not na(s.trLast1):
                seed = s.trLast1 if na(s.trLast2) else min(s.trLast1, s.trLast2)
                s.bullLadder = s.bullAdopted = seed
        elif swBear:
            s.regime = -1
            if not na(s.pkLast1):
                seed = s.pkLast1 if na(s.pkLast2) else max(s.pkLast1, s.pkLast2)
                s.bearLadder = s.bearAdopted = seed
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
    sim = PinePVT(level=level, ignore=strat.p.ladder_ignore_diff)
    H, L, C = (df[k].to_numpy(float) for k in ("high", "low", "close"))
    out, sim_pk, sim_tr = [], {}, {}
    for i in range(len(df)):
        out.append(sim.step(flags[i], H[i], L[i], C[i]))
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


def main():
    d5 = pd.read_parquet(ROOT / "data" / "tx_day_5min.parquet")
    d1 = pd.read_parquet(ROOT / "data" / "tx_day_1min.parquet")
    ok = True
    ok &= verify_unshielded(d5, "5分全期")
    ok &= verify_unshielded(d1, "1分全期")
    ok &= verify_pvt(d5, "5分全期", 2)
    ok &= verify_pvt(d5, "5分全期", 4)
    ok &= verify_pvt(d1, "1分全期", 2)
    print("全部一致" if ok else "有不一致")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
