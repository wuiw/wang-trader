"""q2-04-01 跨週期KD指標搭配N型結構（《期貨奇績2》第四章，p.127–135）。

規格文件：methods/期貨奇績2/q2-04-01-跨週期KD搭配N型.md

核心概念（p.127）：用大週期 KD 的黃金/死亡交叉判斷多空區間，在區間內於小週期尋找
N 型（多）／倒 N 型（空）三步驟作為進場觸發。本模組用參數 `htf_bars`（幾根小週期
K 線合成一根大週期 K 線）在模組內因果合成大週期 K 線，並只用「已完成」的大週期
K 線計算 KD、判斷交叉（大週期 K 線尚未走完前，其 KD 值一律視為未知）。
`htf_bars` 是「根數比」而非時鐘週期：書中 15 分K／1 分K＝15；換成 3 分K 或 5 分K 輸入時，
預設值 15 會使大週期變成 45／75 分鐘，趨勢濾網的意義隨之改變（依「不區隔週期」原則，
本模組不讀取時鐘，由使用者依輸入週期自行調整 htf_bars）。大週期分組自每個交易日第一根起算，
交易日最後一組不足 htf_bars 根者於收盤時視為完成。

訊號（N型／倒N型三步驟，p.127, 129）：
  多：0（區間起始最低點，隨後續新低持續下探）→(1)（層級2峰點，若多個取最高者）
      →(2)（層級2拉回谷點，不可低於0，違反則以該谷點為新0重新尋找，C6/F5）
      →(3)（收盤「無遮蔽」突破(1)，買進訊號）。
  空：與多方鏡射（0=最高點→(1)谷點→(2)反彈峰點不可高於0→(3)收盤跌破(1)）。
  峰谷點一律用層級2轉折點，只用已確認者（confirm<=i）。
搜尋起點（p.127, 129, 135）：
  C1/C1' 黃金/死亡交叉確認的「隔根」才開始搜尋（F1：交叉當根不算）。
  C4/C4' 若多空區間延續自前一交易日尾盤，當日開盤第一根即開始搜尋——本模組因
    KD 狀態本就跨交易日連續累計、只有大週期分組隨 session 重置，此規則自然成立。
  C3/C3' 交叉當根若剛好對應完成步驟(3)、且該時刻為大週期收盤確認時刻，可提前使用（p.129）：
    「大週期收盤確認時刻」在根數語意下＝大週期K線的最後一根小週期K線，也就是交叉被確認的那根；
    本模組另維護一組不看區間的「影子」N型狀態機（每交易日從第一根起算），交叉確認當根若影子
    狀態機恰好完成步驟(3)，即採用該訊號。
進場（p.128, 127）：步驟(3)K線收盤立即進場；停損＝結構的 0 點（p.132，書中未給統一
  停損點數公式，見待確認事項）。
  F3　訊號K線的漲跌點數（|收盤−開盤|）> max_signal_points（書中15點）→ 忽略（big_bar_pullback=False）
      或等拉回/反彈使距停損縮小到 pullback_stop_max（書中10點）以內才補進場（預設，p.127）。
出場：
  折返停利（p.133）：「當價格通過預期目標時啟動停利機制，折返15點」＝最大獲利達 retrace_points
    後啟動，之後自最有利價回落達 retrace_points 即以收盤出場（含回到進場價的情形）。
  五黑過首紅（p.134）：放空後連續 five_bar_n（書中5）根以上黑K，首根紅K立即平倉，
    不論大週期KD是否翻轉；多方鏡射版本書中未明確說明，推論並預設開啟
    （mirror_five_bar_long，CODING_SPEC 規則6）。
過濾：
  F2　金叉/死叉區間內拉回/反彈段不得任意進場，須等新N型/倒N型完成（由狀態機自然達成）。
  F4　同區間第二次同向訊號，若第一次獲利不錯宜忽略：書中未給明確獲利門檻，用
      `second_signal_min_profit` 開關控制，預設 None（關閉），見待確認事項。
      訊號計數在區間起點（交叉隔根／開盤延續）歸零，區間內每個訊號累加。
  N型狀態機不論是否持倉都逐根推進（持倉期間的峰谷與新低仍須納入結構判斷）。
  F5　結構(2)違反0點限制 → 作廢重新尋找（見上）。

週期：不限。所有門檻以點數／根數表示；大週期以 `htf_bars` 根小週期K線因果合成。
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass

import numpy as np
import pandas as pd

from wangtrader.core import Context, Order, Side, Strategy
from wangtrader.core.indicators import kd
from wangtrader.core.pivots import Pivot, find_pivots

METHOD_ID = "q2-04-01"


@dataclass
class Params:
    htf_bars: int = 15  # 大週期／小週期根數比（書中15分鐘／1分鐘＝15，p.127）
    kd_n: int = 9  # 大週期 KD 的 RSV 週期（p.127）
    k_period: int = 3  # KD 的 K 平滑週期（書中未特別說明，沿用台式KD慣例）
    d_period: int = 3  # KD 的 D 平滑週期（同上）
    level: int = 2  # 峰谷點層級（p.127，層級2轉折點）
    max_signal_points: float = 15.0  # F3：訊號K線漲跌點數上限（p.127）
    pullback_stop_max: float = 10.0  # F3：補進場時距停損（0點）的目標距離（p.127）
    big_bar_pullback: bool = True  # F3：大K線訊號等拉回補進場（True）或直接忽略（False），書中兩者並列
    max_wait: int = 10  # 補進場等待根數（書中未給明確數字，比照 q3-01 慣例預設，見末待確認事項）
    retrace_points: float = 15.0  # 折返停利點數（p.133）
    five_bar_n: int = 5  # 五黑過首紅之連續根數門檻（p.134）
    mirror_five_bar_long: bool = True  # 推論：多方鏡射「五紅過首黑」，預設開啟（CODING_SPEC規則6）
    second_signal_min_profit: float | None = None  # F4：第二次同向訊號忽略門檻，書中未給數字，預設關閉


class CrossKDNType(Strategy):
    method_id = METHOD_ID

    def __init__(self, **kw) -> None:
        self.p = Params(**kw)
        self._pivots: list[Pivot] = []
        self._state: dict | None = None
        self._shadow: dict[Side, dict | None] = {Side.LONG: None, Side.SHORT: None}  # C3 例外用
        self._run_signal_count = 0
        self._run_first_pnl: float | None = None

    # ---- 大週期合成與交叉判斷 ----

    def _htf_group_ids(self, df: pd.DataFrame) -> np.ndarray:
        """每根小週期K線所屬的大週期分組序號（依 session 重置分組起點，因果、全表遞增）。"""
        grp_in_sess = (df["bar_no"] // self.p.htf_bars).astype(int)
        key = pd.Index(zip(df["session"].tolist(), grp_in_sess.tolist(), strict=False))
        codes, _ = pd.factorize(key, sort=False)
        return codes

    def _regime(self, df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
        """回傳 (regime, reset)：regime 為每根小週期K線「已知」的大週期金叉(1)/死叉(-1)/尚無(0)；
        reset 標示該根應開始（重新）搜尋 N 型／倒N型。只用已收完的大週期K線。"""
        n = len(df)
        gids = self._htf_group_ids(df)
        pos = np.arange(n)
        tmp = pd.DataFrame({"o": df["open"], "h": df["high"], "l": df["low"], "c": df["close"],
                             "grp": gids, "pos": pos, "session": df["session"].to_numpy()})
        htf = tmp.groupby("grp", sort=True).agg(
            open=("o", "first"), high=("h", "max"), low=("l", "min"), close=("c", "last"),
            last_pos=("pos", "max"), size=("pos", "size"), session=("session", "last"),
        )
        # 只用「已收完」的大週期K線：累積根數達 htf_bars，或所屬 session 已經結束
        # （即該 session 不是資料表中最後一個 session）；資料尾端尚未收完的大週期K線一律排除。
        last_session = df["session"].iat[-1] if n else None
        htf = htf[(htf["size"] >= self.p.htf_bars) | (htf["session"] != last_session)]
        kdf = kd(htf[["open", "high", "low", "close"]], n=self.p.kd_n,
                  k_period=self.p.k_period, d_period=self.p.d_period)
        k_arr, d_arr = kdf["k"].to_numpy(), kdf["d"].to_numpy()
        n_htf = len(htf)
        reg_htf = np.zeros(n_htf, dtype=np.int8)
        cur = 0
        for h in range(1, n_htf):
            if k_arr[h - 1] <= d_arr[h - 1] and k_arr[h] > d_arr[h]:
                cur = 1
            elif k_arr[h - 1] >= d_arr[h - 1] and k_arr[h] < d_arr[h]:
                cur = -1
            reg_htf[h] = cur
        reg_htf[0] = 0
        reg_at_close = np.full(n, np.nan)
        last_pos = htf["last_pos"].to_numpy()
        reg_at_close[last_pos] = reg_htf
        regime = pd.Series(reg_at_close).ffill().fillna(0).to_numpy().astype(int)
        reset = np.zeros(n, dtype=bool)
        bar_no = df["bar_no"].to_numpy()
        for i in range(1, n):
            if regime[i] != regime[i - 1] and regime[i] != 0 and i + 1 < n:
                reset[i + 1] = True  # C1/C1'：交叉隔根才開始搜尋
            if bar_no[i] == 0 and regime[i] == regime[i - 1] and regime[i] != 0:
                reset[i] = True  # C4/C4'：趨勢延續自前一日尾盤，開盤第一根即開始
        return regime, reset

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        regime, reset = self._regime(df)
        df["htf_regime"] = regime
        df["ntype_reset"] = reset
        self._pivots = find_pivots(df, level=self.p.level)
        self._piv_by_kind = {}
        for kind in ("peak", "trough"):
            arr = sorted((pv for pv in self._pivots if pv.kind == kind), key=lambda pv: pv.index)
            self._piv_by_kind[kind] = (arr, [pv.index for pv in arr])
        return df

    # ---- N型／倒N型三步驟狀態機 ----

    def _pivot_candidates(self, kind: str, after_index: int, as_of: int) -> list[Pivot]:
        """kind 的峰谷點中 index > after_index 且已確認（confirm <= as_of）者；以二分搜尋取區間。"""
        arr, idx = self._piv_by_kind[kind]
        lo = bisect.bisect_right(idx, after_index)
        hi = bisect.bisect_right(idx, as_of - self.p.level)  # confirm = index + level
        return arr[lo:hi]

    def _new_state(self, df: pd.DataFrame, i: int, side: Side) -> dict:
        b = df.iloc[i]
        zero_price = float(b["low"]) if side == Side.LONG else float(b["high"])
        return {"side": side, "zero_i": i, "zero_price": zero_price, "peak": None, "trough": None}

    def _start_search(self, df: pd.DataFrame, i: int, side: Side) -> None:
        """區間起點（交叉隔根／開盤延續）：重新開始尋找，訊號計數歸零（F4）。"""
        self._state = self._new_state(df, i, side)
        self._run_signal_count = 0
        self._run_first_pnl = None

    def _advance(self, df: pd.DataFrame, i: int, st: dict | None) -> tuple[Side, float, float] | None:
        """推進狀態機一根；回傳 (side, 0點價, (1)點價) 表示步驟(3)訊號成立（成立後由呼叫端重啟）。"""
        if st is None:
            return None
        long = st["side"] == Side.LONG
        b = df.iloc[i]
        step1_kind = "peak" if long else "trough"
        step2_kind = "trough" if long else "peak"
        if st["peak"] is None:
            cands = self._pivot_candidates(step1_kind, st["zero_i"], i)
            if cands:
                pk = max(cands, key=lambda p: p.price) if long else min(cands, key=lambda p: p.price)
                # 0 點＝(1)形成前（含起點到(1)當根）的最低（高）點；(1)之後的走勢屬拉回(2)，不能併入 0 點
                seg = df["low" if long else "high"].iloc[st["zero_i"]:pk.index + 1]
                st["zero_price"] = float(seg.min() if long else seg.max())
                st["peak"] = pk
            else:
                st["zero_price"] = min(st["zero_price"], float(b["low"])) if long \
                    else max(st["zero_price"], float(b["high"]))
            return None
        if st["trough"] is None:
            cands = self._pivot_candidates(step2_kind, st["peak"].index, i)
            if not cands:
                return None
            newest = max(cands, key=lambda p: p.index)
            violated = newest.price < st["zero_price"] if long else newest.price > st["zero_price"]
            if violated:  # F5/C6：(2) 違反 0 點限制，以此點為新 0 重新尋找
                st["zero_i"], st["zero_price"], st["peak"], st["trough"] = newest.index, newest.price, None, None
            else:
                st["trough"] = newest
            return None
        # 已armed：等待收盤突破(1)，同時持續追蹤更新的(2)
        cands = self._pivot_candidates(step2_kind, st["trough"].index, i)
        if cands:
            newest = max(cands, key=lambda p: p.index)
            violated = newest.price < st["zero_price"] if long else newest.price > st["zero_price"]
            if violated:
                st["zero_i"], st["zero_price"], st["peak"], st["trough"] = newest.index, newest.price, None, None
                return None
            st["trough"] = newest
        broke = b["close"] > st["peak"].price if long else b["close"] < st["peak"].price
        if not broke:
            return None
        return st["side"], st["zero_price"], st["peak"].price

    # ---- 出場 ----

    def _five_bar_exit(self, ctx: Context) -> Order | None:
        p, pos, b = self.p, ctx.pos, ctx.bar()
        black, red = b["close"] < b["open"], b["close"] > b["open"]
        if pos.side == Side.SHORT:
            if black:
                pos.meta["bar_run"] = pos.meta.get("bar_run", 0) + 1
                return None
            run = pos.meta.get("bar_run", 0)
            pos.meta["bar_run"] = 0
            return Order.exit("五黑過首紅") if red and run > p.five_bar_n else None
        if pos.side == Side.LONG and p.mirror_five_bar_long:
            if red:
                pos.meta["bar_run"] = pos.meta.get("bar_run", 0) + 1
                return None
            run = pos.meta.get("bar_run", 0)
            pos.meta["bar_run"] = 0
            return Order.exit("五紅過首黑(推論)") if black and run > p.five_bar_n else None
        return None

    def _giveback_exit(self, ctx: Context) -> Order | None:
        """折返停利（p.133）：最大獲利達 retrace_points 後啟動，自最有利價回落達 retrace_points 即出場。"""
        pos, p = ctx.pos, self.p
        if pos is None or ctx.i <= pos.entry_i or pos.max_profit() < p.retrace_points:
            return None
        if pos.max_profit() - pos.profit(ctx.bar()["close"]) >= p.retrace_points:
            return Order.exit("折返停利")
        return None

    def _advance_shadow(self, df: pd.DataFrame, i: int, side: Side) -> tuple[Side, float, float] | None:
        """C3/C3' 例外用的影子狀態機：不看區間、每交易日自第一根起算，訊號成立後重啟。"""
        if self._shadow[side] is None or df.at[i, "bar_no"] == 0:
            self._shadow[side] = self._new_state(df, i, side)
        sig = self._advance(df, i, self._shadow[side])
        if sig is not None:
            self._shadow[side] = self._new_state(df, i, side)
        return sig

    def on_bar(self, ctx: Context):
        p, df, i = self.p, ctx.df, ctx.i
        reg = int(df.at[i, "htf_regime"])
        reset = bool(df.at[i, "ntype_reset"])
        orders: list[Order] = []
        if ctx.trades and self._run_signal_count >= 1:
            self._run_first_pnl = ctx.trades[-1].pnl
        if ctx.pos is not None:
            ex = self._five_bar_exit(ctx) or self._giveback_exit(ctx)
            if ex:
                orders.append(ex)
        # 影子狀態機（C3 例外）：交叉確認當根若恰好完成步驟(3)，允許使用
        shadow_sigs = {side: self._advance_shadow(df, i, side) for side in (Side.LONG, Side.SHORT)}
        crossed_now = i > 0 and reg != 0 and reg != int(df.at[i - 1, "htf_regime"])
        if reset and reg != 0:  # reset 只會在 regime!=0 時成立
            self._start_search(df, i, Side.LONG if reg == 1 else Side.SHORT)
        sig = self._advance(df, i, self._state)
        if sig is not None:
            self._state = self._new_state(df, i, sig[0])  # 同區間可能出現第二組訊號（F4），從本根繼續找下一組
        if sig is None and crossed_now:
            sig = shadow_sigs[Side.LONG if reg == 1 else Side.SHORT]
        if sig is None:
            return orders or None
        side, zero_price, peak_price = sig
        self._run_signal_count += 1
        # F4：同區間第二次同向訊號，第一次獲利已達門檻則忽略（預設關閉，見模組docstring）
        if (p.second_signal_min_profit is not None and self._run_signal_count > 1
                and self._run_first_pnl is not None and self._run_first_pnl >= p.second_signal_min_profit):
            return orders or None
        stop = zero_price
        b = df.iloc[i]
        c = float(b["close"])
        name = "N型買訊" if side == Side.LONG else "倒N型空訊"
        if abs(c - b["open"]) <= p.max_signal_points:  # F3：訊號K線漲跌點數（p.127）
            orders.append(Order.enter(side, stop=stop, reason=name, zero=zero_price, peak=peak_price))
        elif p.big_bar_pullback:
            limit = stop + p.pullback_stop_max * int(side)
            orders.append(Order.enter_limit(side, limit=limit, expire=p.max_wait, stop=stop,
                                            reason=name + "(補進場)", zero=zero_price, peak=peak_price))
        return orders or None
