"""q2-03-01 PVT 通道 N型／倒N型突破訊號（《期貨奇績2》第三章，p.94-111）。

規格文件：methods/期貨奇績2/q2-03-01-PVT通道N型訊號.md（章節總覽：q2-03-00-章節總覽.md）

PVT 通道／趨勢階梯（p.95-98）：本模組自行實作（不與其他方法模組共用）。
  多趨勢階梯：相鄰兩個層級轉折谷點取較低者；比較對象是「上一個被採用的谷點」而非最新一個谷點，
    差距 ≤ 2 點時忽略此次比較、階梯不動（p.96）。空趨勢階梯：峰點鏡像。
  控盤易主：收盤突破空趨勢階梯 → 立即以「最近兩個層級谷點」孰低重建多趨勢階梯（p.97）；
    收盤跌破多趨勢階梯 → 立即以「最近兩個層級峰點」孰高重建空趨勢階梯（p.97，空方明確；多方重建為鏡像推論）。
    易主當根本身不是訊號（p.97）。「最近兩個峰谷點」只取當根已確認者，不偷看未確認的轉折點。
  階梯與控盤方向跨交易日延續（p.101：「前一天尾盤被PVT壓力線制壓…當天一開盤突破壓力線後」），
    只在資料起點做一次冷啟動；峰谷點仍逐交易日計算。

層級峰谷轉折點（p.4-5沿用第一章定義，本章 p.100-101 提及層級2或層級4皆可）：本模組自行實作，
  支援單峰/雙峰/三峰（等高相鄰）與「變形」（中間夾一根較低K線），峰谷點只用已右側 level 根確認者。

訊號（p.98-100）：階梯控盤區內尋找 0-1-2-3 結構：
  多方（N型）：C1 谷(0)<谷(2)；C2 峰(3)收盤>峰(1)；C3 (0)(1)(2)(3)皆為層級轉折點，且(1)(2)(3)須發生在
    收盤突破多趨勢階梯之後，(0)可在之前（p.104，「訊號只能發生在突破階梯之後」）。
  空方（倒N型）：峰(0)>峰(2)；谷(3)收盤<谷(1)；其餘鏡像。
  訊號確認峰(3)/谷(3)的收盤突破/跌破峰(1)/谷(1)時，即為訊號（p.98-100）；本模組將該收盤突破視為即時觸發，
  不要求峰(3)/谷(3)本身先完成層級確認才觸發（否則與「當根收盤觸發」矛盾），屬詮釋；
  谷(2)確認當根若收盤已突破峰(1)，當根即成立（p.16-17 同作者「不需等右側確認」的原則）。
  (0)須為結構最低（高）點：(1)尚未形成前若出現更低（高）的轉折點，(0)移到該點。

進場（p.98-100）：訊號K線收盤進場。
停損（p.100）：與均線三步驟策略相同的個位數公式（本模組自行複製，不 import q2-01），
  可選改採 PVT 階梯（兩者皆在 stop_max_risk 點內時取較優者，p.108）。
出場（p.108, 118-122）：
  折返 giveback_points 點停利：最大獲利達 giveback_points 後啟動，之後自最有利價回落達此點數即出場
    （p.108；啟動門檻依 q2-01 p.22「初始獲利15點，到達後啟動折返15點」、q2-04-01 p.133「通過預期目標啟動停利」）；
  已獲利部位收盤先跌破/突破 PVT 階梯即可停利（p.108，6.2）；
  反向訊號立即平倉反手（p.111，由引擎的反手機制處理）。
過濾（p.104-105, 110）：
  F1 (0)到(3)距離 > max_pattern_points(30) → 忽略。
  F2 (0)距階梯 > max_dev_from_ladder(20) → 不列入計數。
  F3 突破/跌破階梯後偏離 > max_drift_from_breakout(30) 或拖延 > max_bars_from_breakout(60) 根仍未成訊號 → 忽略。
  F4 no_entry_after：晚於此時刻不進場（書中收盤前1小時，p.105；預設 None 關閉，時鐘規則）。

不區隔週期：無任何 K 線週期常數；所有門檻皆為點數／根數參數。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time

import pandas as pd

from wangtrader.core import Context, Order, Side, Strategy

METHOD_ID = "q2-03-01"


# ---------- 層級峰谷點（含變形），本模組私有實作 ----------


@dataclass(frozen=True)
class _Pivot:
    index: int
    confirm: int
    price: float
    kind: str  # "peak" | "trough"


_MAX_PLATEAU = 4  # 單峰/雙峰/三峰及最多一根K線的「變形」凹陷之合理上限（原圖缺，屬詮釋）


def _groups(vals, better) -> list[tuple[int, int]]:
    n = len(vals)
    out = []
    j = 0
    while j < n:
        end = j
        dip_used = False
        k = j + 1
        while k < n and (k - j) < _MAX_PLATEAU:
            if vals[k] == vals[j]:
                end = k
                k += 1
            elif not dip_used and better(vals[j], vals[k]) and k + 1 < n and vals[k + 1] == vals[j]:
                dip_used = True
                end = k + 1
                k += 2
            else:
                break
        out.append((j, end))
        j = end + 1
    return out


def _find_level_pivots(high, low, level: int, kind: str) -> list[_Pivot]:
    vals = high if kind == "peak" else low
    better = (lambda a, b: a > b) if kind == "peak" else (lambda a, b: a < b)
    out = []
    for s, e in _groups(vals, better):
        v = vals[s]
        left = vals[max(0, s - level):s]
        right = vals[e + 1:e + 1 + level]
        if len(right) < level:
            continue
        if any(not better(v, x) for x in left) or any(not better(v, x) for x in right):
            continue
        out.append(_Pivot(index=e, confirm=e + level, price=float(v), kind=kind))
    return out


def _pivots_by_session(df: pd.DataFrame, level: int) -> tuple[list[_Pivot], list[_Pivot]]:
    peaks: list[_Pivot] = []
    troughs: list[_Pivot] = []
    for _, g in df.groupby("session", sort=False):
        off = g.index[0]
        h = g["high"].to_numpy(float)
        lo = g["low"].to_numpy(float)
        for p in _find_level_pivots(h, lo, level, "peak"):
            peaks.append(_Pivot(p.index + off, p.confirm + off, p.price, "peak"))
        for p in _find_level_pivots(h, lo, level, "trough"):
            troughs.append(_Pivot(p.index + off, p.confirm + off, p.price, "trough"))
    return peaks, troughs


def _group_by_confirm(pivots: list[_Pivot]) -> dict[int, list[_Pivot]]:
    out: dict[int, list[_Pivot]] = {}
    for p in pivots:
        out.setdefault(p.confirm, []).append(p)
    return out


def _digit_stop(side: Side, close_price: float, min_offset: float, integer_points: float) -> float:
    """個位數停損公式（與第一章均線策略相同，p.100；本模組自行複製）。"""
    digit = int(round(close_price)) % 10
    pts = integer_points if digit == 0 else min_offset + digit
    return close_price - pts if side == Side.LONG else close_price + pts


@dataclass
class Params:
    pivot_level: int = 2  # 層級2轉折點（p.100-101 亦可選層級4）
    ladder_ignore_diff: float = 2.0  # 兩轉折點差距 ≤ 此值忽略比較（p.96）
    stop_min_offset: float = 10.0
    stop_integer_points: float = 20.0
    stop_use_ladder: bool = True  # 停損可改採 PVT 階梯（p.108）
    stop_max_risk: float = 20.0  # 公式停損與階梯皆須在此風控範圍內才比較取優（p.108）
    max_pattern_points: float = 30.0  # F1：(0)到(3)距離上限（p.104）
    max_dev_from_ladder: float = 20.0  # F2：(0)距階梯上限（p.105）
    max_drift_from_breakout: float = 30.0  # F3：突破後偏離上限（p.110）
    max_bars_from_breakout: int = 60  # F3：突破後拖延根數上限（p.110）
    no_entry_after: time | None = None  # F4：書中收盤前1小時（p.105），預設關閉
    giveback_points: float = 15.0  # 折返停利點數（書中舉例15或20點，p.108/118）
    ladder_exit: bool = True  # 已獲利部位可用 PVT 階梯停利（p.108, 6.2）


class PVTNType(Strategy):
    method_id = METHOD_ID

    def __init__(self, **kw) -> None:
        self.p = Params(**kw)
        self._peaks_by_confirm: dict[int, list[_Pivot]] = {}
        self._troughs_by_confirm: dict[int, list[_Pivot]] = {}
        self._st: dict = self._fresh()

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        peaks, troughs = _pivots_by_session(df, self.p.pivot_level)
        self._peaks_by_confirm = _group_by_confirm(peaks)
        self._troughs_by_confirm = _group_by_confirm(troughs)
        self._st = self._fresh()
        return df

    # ---------- 狀態（階梯／控盤方向跨交易日延續，p.101） ----------

    def _fresh(self) -> dict:
        return {
            "bull_ladder": None, "bull_adopted": None,
            "bear_ladder": None, "bear_adopted": None,
            "regime": None, "breakout_i": None, "breakout_price": None,
            "LONG": {"c0": None, "c1": None, "c2": None, "phase": "need0"},
            "SHORT": {"c0": None, "c1": None, "c2": None, "phase": "need0"},
        }

    def _state(self, sess: int) -> dict:
        return self._st

    def _update_ladder(self, st: dict, kind: str, price: float) -> None:
        """兩兩取樣、取孰低（谷=多趨勢）或孰高（峰=空趨勢），差距 ≤2 忽略（p.95-96）。"""
        ignore = self.p.ladder_ignore_diff
        if kind == "trough":
            if st["bull_adopted"] is None:
                st["bull_adopted"] = price
                return
            if abs(price - st["bull_adopted"]) <= ignore:
                return
            st["bull_ladder"] = min(st["bull_adopted"], price)
            st["bull_adopted"] = price
        else:
            if st["bear_adopted"] is None:
                st["bear_adopted"] = price
                return
            if abs(price - st["bear_adopted"]) <= ignore:
                return
            st["bear_ladder"] = max(st["bear_adopted"], price)
            st["bear_adopted"] = price

    def _reseed(self, st: dict, kind: str, i: int) -> None:
        """控盤易主當下，立刻用最近兩個層級峰(谷)點重建初始階梯（p.97；多方重建為鏡像推論）。"""
        pivots = self._troughs_by_confirm if kind == "trough" else self._peaks_by_confirm
        recent = sorted(
            (p for lst in pivots.values() for p in lst if p.confirm <= i), key=lambda p: p.index
        )[-2:]
        if not recent:
            return
        val = (min if kind == "trough" else max)(p.price for p in recent)
        if kind == "trough":
            st["bull_ladder"], st["bull_adopted"] = val, val
        else:
            st["bear_ladder"], st["bear_adopted"] = val, val

    def _reset_structure(self, st: dict, side: str, c0: _Pivot | None) -> None:
        st[side] = {"c0": c0, "c1": None, "c2": None, "phase": "need1" if c0 else "need0"}

    def _last_confirmed(self, pivots_by_confirm: dict[int, list[_Pivot]], i: int) -> _Pivot | None:
        cand = [p for lst in pivots_by_confirm.values() for p in lst if p.confirm <= i]
        return max(cand, key=lambda p: p.index) if cand else None

    def _step_structure(self, side: str, sst: dict, better, price_at, high_low, breakout_i: int, df: pd.DataFrame, i: int):
        """側=LONG(多，谷0峰1谷2峰3) 或 SHORT(空，峰0谷1峰2谷3)。回傳 (c1_price, c0) 或 None。"""
        first_kind = "trough" if side == "LONG" else "peak"
        second_kind = "peak" if side == "LONG" else "trough"
        first_by_confirm = self._troughs_by_confirm if first_kind == "trough" else self._peaks_by_confirm
        second_by_confirm = self._peaks_by_confirm if second_kind == "peak" else self._troughs_by_confirm

        if sst["phase"] == "need0":
            new0 = [p for p in first_by_confirm.get(i, [])]
            if new0:
                sst["c0"] = new0[-1]
                sst["phase"] = "need1"
            return None
        if sst["phase"] == "need1":
            # (0)須為結構最低（高）點：(1)尚未形成前出現更低（高）的轉折點 → (0)移到該點
            for p in first_by_confirm.get(i, []):
                if p.index > sst["c0"].index and not better(p.price, sst["c0"].price):
                    sst["c0"] = p
            new1 = [p for p in second_by_confirm.get(i, []) if p.index > breakout_i and p.index > sst["c0"].index]
            if new1:
                sst["c1"] = new1[-1]
                sst["phase"] = "need2"
            return None
        if sst["phase"] == "need2":
            new2 = [p for p in first_by_confirm.get(i, []) if p.index > sst["c1"].index]
            for p in new2:
                if better(p.price, sst["c0"].price):  # (0)<(2) 多／(0)>(2) 空
                    sst["c2"] = p
                    sst["phase"] = "need3"
                else:
                    sst["c0"] = p
                    sst["c1"] = None
                    sst["phase"] = "need1"
            if sst["phase"] != "need3":
                return None
            # 谷(2)/峰(2) 確認當根若收盤已突破/跌破 (1)，當根即成立（不必再等一根）
        if sst["phase"] == "need3":
            close = df.at[i, "close"]
            if i > sst["c2"].index and (close > sst["c1"].price if side == "LONG" else close < sst["c1"].price):
                return sst["c1"].price, sst["c0"]
        return None

    def _giveback_exit(self, ctx: Context) -> Order | None:
        """折返停利：最大獲利達 giveback_points 後啟動，自最有利價回落達 giveback_points 即出場。"""
        pos = ctx.pos
        if pos is None or pos.max_profit() < self.p.giveback_points:
            return None
        cur = pos.profit(ctx.bar()["close"])
        if pos.max_profit() - cur >= self.p.giveback_points:
            return Order.exit(f"折返{self.p.giveback_points:g}點停利")
        return None

    def _ladder_exit_order(self, ctx: Context, st: dict) -> Order | None:
        pos = ctx.pos
        if pos is None or not self.p.ladder_exit or pos.profit(ctx.bar()["close"]) <= 0:
            return None
        close = ctx.bar()["close"]
        if pos.side == Side.LONG and st["bull_ladder"] is not None and close < st["bull_ladder"]:
            return Order.exit("PVT階梯停利")
        if pos.side == Side.SHORT and st["bear_ladder"] is not None and close > st["bear_ladder"]:
            return Order.exit("PVT階梯停利")
        return None

    def on_bar(self, ctx: Context):
        p, df, i = self.p, ctx.df, ctx.i
        sess = df.at[i, "session"]
        st = self._state(sess)
        close = df.at[i, "close"]
        orders: list[Order] = []

        if ctx.pos is not None:
            ex = self._giveback_exit(ctx) or self._ladder_exit_order(ctx, st)
            if ex is not None:
                orders.append(ex)

        # 1. 更新趨勢階梯（用本根新確認的峰谷點）
        for pv in self._troughs_by_confirm.get(i, []):
            self._update_ladder(st, "trough", pv.price)
        for pv in self._peaks_by_confirm.get(i, []):
            self._update_ladder(st, "peak", pv.price)

        # 2. 控盤易主判定（p.97）；本根本身不是訊號。
        #    多空皆已確立時：跌破多趨勢階梯 → 轉空；突破空趨勢階梯 → 轉多（p.97）。
        #    尚無任何控盤方向時（僅資料起點冷啟動一次；狀態跨日延續）：以率先被突破/跌破的階梯決定初始方向
        #    （書中未明文，屬詮釋）。
        switch_bull = st["bear_ladder"] is not None and close > st["bear_ladder"] and st["regime"] != "bull"
        switch_bear = st["bull_ladder"] is not None and close < st["bull_ladder"] and st["regime"] != "bear"
        if st["regime"] is None:
            switch_bull = switch_bull or (st["bull_ladder"] is not None and close > st["bull_ladder"])
            switch_bear = switch_bear or (st["bear_ladder"] is not None and close < st["bear_ladder"])
        if switch_bull:
            st["regime"] = "bull"
            st["breakout_i"], st["breakout_price"] = i, close
            self._reseed(st, "trough", i)
            c0 = self._last_confirmed(self._troughs_by_confirm, i)
            self._reset_structure(st, "LONG", c0)
            self._reset_structure(st, "SHORT", None)
        elif switch_bear:
            st["regime"] = "bear"
            st["breakout_i"], st["breakout_price"] = i, close
            self._reseed(st, "peak", i)
            c0 = self._last_confirmed(self._peaks_by_confirm, i)
            self._reset_structure(st, "SHORT", c0)
            self._reset_structure(st, "LONG", None)

        # 3. N型 / 倒N型 結構推進
        if st["regime"] == "bull":
            hit = self._step_structure("LONG", st["LONG"], lambda a, b: a > b, None, None, st["breakout_i"], df, i)
            if hit is not None:
                c1_price, c0 = hit
                if self._passes_filters(df, i, c0, c1_price, st, Side.LONG):
                    stop = self._final_stop(Side.LONG, close, st)
                    orders.append(Order.enter(Side.LONG, stop=stop, reason="PVT-N型買進"))
                self._reset_structure(st, "LONG", st["LONG"]["c2"])
        if st["regime"] == "bear":
            hit = self._step_structure("SHORT", st["SHORT"], lambda a, b: a < b, None, None, st["breakout_i"], df, i)
            if hit is not None:
                c1_price, c0 = hit
                if self._passes_filters(df, i, c0, c1_price, st, Side.SHORT):
                    stop = self._final_stop(Side.SHORT, close, st)
                    orders.append(Order.enter(Side.SHORT, stop=stop, reason="PVT倒N型放空"))
                self._reset_structure(st, "SHORT", st["SHORT"]["c2"])

        return orders or None

    def _final_stop(self, side: Side, close: float, st: dict) -> float:
        stop = _digit_stop(side, close, self.p.stop_min_offset, self.p.stop_integer_points)
        if not self.p.stop_use_ladder:
            return stop
        ladder = st["bull_ladder"] if side == Side.LONG else st["bear_ladder"]
        if ladder is None:
            return stop
        f_risk, l_risk = abs(close - stop), abs(close - ladder)
        if f_risk <= self.p.stop_max_risk and l_risk <= self.p.stop_max_risk:
            return min(stop, ladder) if side == Side.LONG else max(stop, ladder)
        return stop

    def _passes_filters(self, df: pd.DataFrame, i: int, c0: _Pivot, c1_price: float, st: dict, side: Side) -> bool:
        p = self.p
        close = df.at[i, "close"]
        if abs(close - c0.price) > p.max_pattern_points:  # F1
            return False
        ladder = st["bull_ladder"] if side == Side.LONG else st["bear_ladder"]
        if ladder is not None and abs(c0.price - ladder) > p.max_dev_from_ladder:  # F2
            return False
        if abs(close - st["breakout_price"]) > p.max_drift_from_breakout:  # F3 偏離
            return False
        if i - st["breakout_i"] > p.max_bars_from_breakout:  # F3 拖延
            return False
        if p.no_entry_after is not None and hasattr(df.at[i, "time"], "time") and df.at[i, "time"].time() > p.no_entry_after:  # F4
            return False
        return True
