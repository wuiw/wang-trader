"""q2-03-02 PVT 通道結合 RSI 穿越 50（《期貨奇績2》第三章，p.112-123）。

規格文件：methods/期貨奇績2/q2-03-02-PVT通道結合RSI.md（章節總覽：q2-03-00-章節總覽.md）

PVT 通道／趨勢階梯（p.95-98，沿用 q2-03-01 之建構規則）：本模組自行實作（不與其他方法模組共用）；
  階梯與控盤方向跨交易日延續（p.101），易主重建只用已確認峰谷點。
層級峰谷轉折點：本模組自行實作（含變形），只用已確認者。

訊號（p.112-113）：
  多方：
    C1 價格向上突破 PVT 階梯（控盤易主時被突破的那條階梯價位）的最高點（非收盤）超過 break_points(10) 點，
       並形成層級2峰點（錨點峰位）（p.113 圖3-18：「跌到B低點，距離當初跌破PVT通道位置超過10點」）。
    C2 由錨點峰位向下折返，折返幅度（以折返段最低點量測）超過 retrace_points(10) 點（p.113「從B反彈到高點C」）。
    C3 折返過程中 RSI 曾跌破 50。
    C4 RSI 重新站上50，且K線收盤「過一高」：收盤高於折返最低點以來至前一根為止所有K線的最高點
       （p.113「K線收盤跌破前一根K線低點」、p.118「E點為從C反漲的最高無遮蔽K線」）；
       兩者可先後或同時成立，但若「過一高」先於 RSI 重新站上50，須延後到 RSI 也滿足時才進場（p.113）。
  空方（鏡像，p.112）：C1'~C4' 對稱，谷位、跌破50/站上50、破一低。

進場（p.112-113）：C4/C4' 成立當根收盤進場。
停損（p.100，本節未重新書寫，推論比照 q2-03-01：個位數公式，可選改採 PVT 階梯）。
出場（p.118-122）：
  折返 giveback_points 點停利：最大獲利達 giveback_points 後啟動，自最有利價回落達此點數即出場
    （p.118；啟動門檻依 q2-01 p.22、p.118-119「跌超過15點，應可開始啟動停利機制」）；
  已獲利部位收盤先跌破/突破 PVT 階梯即可停利（p.122，6.2）；
  保本出場（6.3）：獲利曾達 breakeven_arm_points(15) 點後，折返回進場價（獲利<=0）即出場——
    與 core.exits.retrace_exit(trigger=15, keep=0) 之範例完全對應，直接沿用該共用工具；
  反向訊號立即平倉反手（由引擎的反手機制處理）。
過濾（p.113, 116-121）：
  F1 突破/折返幅度任一未達門檻 → 訊號不成立（已內建於 C1/C2 判斷）。
  F2 幅度符合但 RSI 未曾真正穿越50 → 不成立（已內建於 C3/C4 判斷）。
  F3「過一高」先於 RSI 穿越50 → 暫不可進場（已內建於 C4 判斷，p.113）。
  F4 訊號確認前價格已偏離最初突破位置（被突破的階梯價位）過遠：書中僅舉例「約90點」，未給精確門檻，
     本模組提供 max_drift_from_breakout 參數（預設 None 關閉），避免自行發明精確數字。
出場（p.119，advisory）：持倉逾 time_stop_bars 根仍無明顯輸贏，考慮平手離場；門檻未量化，預設關閉。

不區隔週期：無任何 K 線週期常數；所有門檻皆為點數／根數參數。
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from wangtrader.core import Context, Order, Side, Strategy
from wangtrader.core.exits import retrace_exit
from wangtrader.core.indicators import rsi

METHOD_ID = "q2-03-02"


# ---------- 層級峰谷點（含變形），本模組私有實作 ----------


@dataclass(frozen=True)
class _Pivot:
    index: int
    confirm: int
    price: float
    kind: str  # "peak" | "trough"


_MAX_PLATEAU = 4


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
    """個位數停損公式（推論，比照 q2-03-01／第一章均線策略，本模組自行複製）。"""
    digit = int(round(close_price)) % 10
    pts = integer_points if digit == 0 else min_offset + digit
    return close_price - pts if side == Side.LONG else close_price + pts


@dataclass
class Params:
    pivot_level: int = 2
    ladder_ignore_diff: float = 2.0  # 兩轉折點差距 ≤ 此值忽略比較（p.96，沿用PVT階梯規則）
    break_points: float = 10.0  # C1：突破階梯最高點需超過此點數（p.112）
    retrace_points: float = 10.0  # C2：折返幅度需超過此點數（p.112）
    rsi_period: int = 5  # RSI 參數書中未明確數值，採核心預設
    rsi_mid: float = 50.0
    max_drift_from_breakout: float | None = None  # F4：書中僅舉例「約90點」，未量化，預設關閉
    stop_min_offset: float = 10.0
    stop_integer_points: float = 20.0
    stop_use_ladder: bool = True
    stop_max_risk: float = 20.0
    giveback_points: float = 15.0  # 折返停利點數（p.118舉例15或20點）
    ladder_exit: bool = True  # 已獲利部位可用 PVT 階梯停利（p.122, 6.2）
    breakeven_arm_points: float = 15.0  # 保本出場：獲利曾達此點數後折返回進場價即出場（p.118-119, 6.3）
    time_stop_bars: int | None = None  # 持倉逾此根數無明顯輸贏，考慮平手離場（p.119）；門檻未量化，預設關閉


class PVTRSISignal(Strategy):
    method_id = METHOD_ID

    def __init__(self, **kw) -> None:
        self.p = Params(**kw)
        self._peaks_by_confirm: dict[int, list[_Pivot]] = {}
        self._troughs_by_confirm: dict[int, list[_Pivot]] = {}
        self._st: dict = self._fresh()

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["rsi"] = rsi(df["close"], self.p.rsi_period)
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
            "regime": None, "breakout_i": None, "breakout_level": None,
            "LONG": self._fresh_leg(), "SHORT": self._fresh_leg(),
        }

    @staticmethod
    def _fresh_leg() -> dict:
        return {
            "phase": "seek_anchor",  # seek_anchor -> seek_retrace -> watch_c4
            "anchor": None,  # _Pivot
            "extreme": None,  # 折返段最低(多)/最高(空)價
            "extreme_i": None,  # 折返極值所在K線
            "rsi_dipped": False,
            "broke_high": False,
            "rsi_recrossed": False,
        }

    def _state(self, sess: int) -> dict:
        return self._st

    def _update_ladder(self, st: dict, kind: str, price: float) -> None:
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
        pivots = self._troughs_by_confirm if kind == "trough" else self._peaks_by_confirm
        recent = sorted((p for lst in pivots.values() for p in lst if p.confirm <= i), key=lambda p: p.index)[-2:]
        if not recent:
            return
        val = (min if kind == "trough" else max)(p.price for p in recent)
        if kind == "trough":
            st["bull_ladder"], st["bull_adopted"] = val, val
        else:
            st["bear_ladder"], st["bear_adopted"] = val, val

    # ---------- 訊號狀態機（多方 LONG／空方 SHORT） ----------

    def _step_leg(self, side: str, leg: dict, df: pd.DataFrame, i: int, breakout_i: int, breakout_level: float | None):
        """回傳 (anchor_price, entry_close) 於 C4/C4' 成立時，否則 None。"""
        p = self.p
        close = df.at[i, "close"]
        rsi_v = df.at[i, "rsi"]
        pivots_by_confirm = self._peaks_by_confirm if side == "LONG" else self._troughs_by_confirm
        better = (lambda a, b: a > b) if side == "LONG" else (lambda a, b: a < b)
        far_col, near_col = ("low", "high") if side == "LONG" else ("high", "low")  # far=折返極值欄, near=過一高參考欄

        def reset_retrace(anchor: _Pivot) -> None:
            # 折返段自錨點後一根起算：以折返段最低(多)/最高(空)價為極值（C2 以價格極值量測，p.113）
            seg = df[far_col].iloc[anchor.index + 1:i + 1]
            pos = int(seg.to_numpy().argmin() if side == "LONG" else seg.to_numpy().argmax())
            leg["extreme"], leg["extreme_i"] = float(seg.iloc[pos]), anchor.index + 1 + pos
            leg["rsi_dipped"] = False

        if leg["phase"] == "seek_anchor":
            for pv in pivots_by_confirm.get(i, []):
                if pv.index < breakout_i or breakout_level is None:
                    continue
                diff = (pv.price - breakout_level) if side == "LONG" else (breakout_level - pv.price)
                if diff > p.break_points:  # C1：突破被越過的階梯達門檻
                    if leg["anchor"] is None or better(pv.price, leg["anchor"].price):
                        leg["anchor"] = pv
                        leg["phase"] = "seek_retrace"
                        reset_retrace(pv)
            return None

        # 更新折返極值（以價格極值量測）與 RSI 是否曾穿越50（p.112-113）
        far_v = df.at[i, far_col]
        if leg["extreme"] is None or (far_v < leg["extreme"] if side == "LONG" else far_v > leg["extreme"]):
            leg["extreme"], leg["extreme_i"] = float(far_v), i
        if pd.notna(rsi_v):
            crossed_mid = rsi_v < p.rsi_mid if side == "LONG" else rsi_v > p.rsi_mid
            if crossed_mid:
                leg["rsi_dipped"] = True

        if leg["phase"] == "seek_retrace":
            # 折返段出現更高（低）錨點時移動（未特別記述，屬合理延伸，參照 q2-01 C1-update）
            for pv in pivots_by_confirm.get(i, []):
                if pv.index >= breakout_i and better(pv.price, leg["anchor"].price):
                    leg["anchor"] = pv
                    reset_retrace(pv)
            retrace = (leg["anchor"].price - leg["extreme"]) if side == "LONG" else (leg["extreme"] - leg["anchor"].price)
            if retrace > p.retrace_points:
                leg["phase"] = "watch_c4"
                leg["broke_high"] = False
                leg["rsi_recrossed"] = False
            return None

        # phase == "watch_c4"
        if not leg["rsi_dipped"]:
            return None  # C3 尚未滿足
        # 過一高／破一低（無遮蔽）：收盤高於折返極值以來至前一根為止所有K線的最高點（p.113, p.118）
        if leg["extreme_i"] < i:
            ref = df[near_col].iloc[leg["extreme_i"]:i]
            broke = close > ref.max() if side == "LONG" else close < ref.min()
            if broke:
                leg["broke_high"] = True
        if pd.notna(rsi_v):
            recrossed = rsi_v >= p.rsi_mid if side == "LONG" else rsi_v <= p.rsi_mid
            if recrossed:
                leg["rsi_recrossed"] = True
        if leg["broke_high"] and leg["rsi_recrossed"]:
            anchor_price = leg["anchor"].price
            return anchor_price, close
        return None

    # ---------- 出場 ----------

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

    def _time_stop(self, ctx: Context) -> Order | None:
        pos, p = ctx.pos, self.p
        if pos is None or p.time_stop_bars is None:
            return None
        if ctx.i - pos.entry_i >= p.time_stop_bars and abs(pos.profit(ctx.bar()["close"])) < 1e-9:
            return Order.exit("持倉過久平手出場")
        return None

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

    def on_bar(self, ctx: Context):
        p, df, i = self.p, ctx.df, ctx.i
        sess = df.at[i, "session"]
        st = self._state(sess)
        close = df.at[i, "close"]
        orders: list[Order] = []

        if ctx.pos is not None:
            ex = (
                self._giveback_exit(ctx)
                or self._ladder_exit_order(ctx, st)
                or retrace_exit(ctx, self.p.breakeven_arm_points, 0.0)
                or self._time_stop(ctx)
            )
            if ex is not None:
                orders.append(ex)

        for pv in self._troughs_by_confirm.get(i, []):
            self._update_ladder(st, "trough", pv.price)
        for pv in self._peaks_by_confirm.get(i, []):
            self._update_ladder(st, "peak", pv.price)

        # 控盤易主（p.95-98 沿用 q2-03-01 規則）；本根本身非訊號
        switch_bull = st["bear_ladder"] is not None and close > st["bear_ladder"] and st["regime"] != "bull"
        switch_bear = st["bull_ladder"] is not None and close < st["bull_ladder"] and st["regime"] != "bear"
        if st["regime"] is None:
            switch_bull = switch_bull or (st["bull_ladder"] is not None and close > st["bull_ladder"])
            switch_bear = switch_bear or (st["bear_ladder"] is not None and close < st["bear_ladder"])
        if switch_bull:
            # breakout_level：被突破的那條階梯價位（C1 的幅度基準，p.113）；冷啟動時為率先被突破的階梯
            level = st["bear_ladder"] if (st["bear_ladder"] is not None and close > st["bear_ladder"]) else st["bull_ladder"]
            st["regime"], st["breakout_i"], st["breakout_level"] = "bull", i, level
            self._reseed(st, "trough", i)
            st["LONG"] = self._fresh_leg()
            st["SHORT"] = self._fresh_leg()
        elif switch_bear:
            level = st["bull_ladder"] if (st["bull_ladder"] is not None and close < st["bull_ladder"]) else st["bear_ladder"]
            st["regime"], st["breakout_i"], st["breakout_level"] = "bear", i, level
            self._reseed(st, "peak", i)
            st["LONG"] = self._fresh_leg()
            st["SHORT"] = self._fresh_leg()

        for regime, side_name, side, reason in (("bull", "LONG", Side.LONG, "PVT+RSI買進"),
                                                ("bear", "SHORT", Side.SHORT, "PVT+RSI放空")):
            if st["regime"] != regime:
                continue
            hit = self._step_leg(side_name, st[side_name], df, i, st["breakout_i"], st["breakout_level"])
            if hit is None:
                continue
            _anchor_price, entry_close = hit
            drift = abs(entry_close - st["breakout_level"]) if st["breakout_level"] is not None else 0.0
            if p.max_drift_from_breakout is None or drift <= p.max_drift_from_breakout:  # F4
                stop = self._final_stop(side, entry_close, st)
                orders.append(Order.enter(side, stop=stop, reason=reason))
            st[side_name] = self._fresh_leg()

        return orders or None
