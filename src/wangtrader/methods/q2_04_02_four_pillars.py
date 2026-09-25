"""q2-04-02 四柱戰法（《期貨奇績2》第四章，p.141–151, 154–155）。

規格文件：methods/期貨奇績2/q2-04-02-四柱戰法.md

核心概念（p.141）：以「昨高、昨低、昨收、今開」四個價格關卡為觀察焦點，比較關卡前後
K 線收盤根數多寡判定多空優劣，再結合 N 型／倒 N 型三步驟產生突破/跌破進場訊號。
四個關卡值直接取 `wangtrader.core.bars.prepare()` 已算好的欄位：
  昨高=prev_high、昨低=prev_low、昨收=prev_close、今開=sess_open。
四個關卡各自獨立追蹤（同一時段可能同時或先後在不同關卡上尋找訊號，p.147–150 範例）。

訊號（多方 C1–C5／空方 C1'–C5'，p.141–143）：
  C1　突破關卡前，關卡下方須有 >= min_side_bars 根K線收盤（書中3根）。
  C2　突破後價格形成層級2峰點(1)（若多個取最高者）。
  C3　折返形成層級2谷點(2)，谷點可以跌破關卡（拉回期間收盤跌破關卡不會中止這組觀察）。
  C4　突破後「收盤站在關卡上方的根數」> 「拉回跌到關卡下方的根數」才是有效突破（p.141, 143 圖4-18：
      上方 8 根 vs 拉回下方 4 根）；比較時點為價格重新站回關卡上方時（p.141）與訊號成立時，
      未取得優勢即放棄（F2）。（注意不是與「突破前」的下方根數比較。）
  C5　收盤「無遮蔽」進一步突破(1)峰點，為買進訊號。
  同一關卡可同時存在多、空各一組觀察（例如先跌破關卡又站回，跌破的那段若有 >=3 根也成為向上突破的
  前置根數，p.147 圖4-21）。0 點＝突破前弱側那段走勢的最低（高）點與突破當根的較低（高）者。
  空方為鏡射（下方>=3根、層級2谷點(1)取最低者、峰點(2)可突破關卡、下方根數>上方根數、跌破(1)谷點）。
  C6　（沿用自 q2-04-01 之通用規則，p.151）N型結構起始0點須為結構最極端點，
      拉回/反彈(2)不可越過0點，違反則以該點為新0重新尋找。

進場（p.142–143）：訊號K線收盤突破/跌破(1)時，立即以收盤進場（書中未提及本方法有
  補進場機制，故不同於 q2-04-01）。
停損（p.147–148, 150）：設於構成訊號前的拉回層級2谷點(2)（多方）或反彈層級2峰點(2)
  （空方）——注意與 q2-04-01 不同，本方法停損＝結構(2)點而非0點；一般情況下點數控制在
  stop_points_cap（預設20）以內，超過則改用「進場價 ± stop_points_cap」。
  重大事件（如公投、選舉開票，p.152–153）發生當下波動放大，允許停損距離超過20點，
  以 major_event_stop 開關控制（預設 False，即沿用一般20點上限）。
出場：折返停利（推論延用 q2-04-01 同一機制，書中本節未重新定義，僅圖例點數一致，
  見模組末待確認事項）：最大獲利達 retrace_points（書中15點）後啟動，自最有利價回落達
  retrace_points 即出場（p.150「超過 15 點折返，多單觸及停利出場」）。
過濾：
  F1　同 C1/C1'：弱側根數不足 min_side_bars，不得從該處起算訊號。
  F2　同 C4/C4'：未取得根數優勢，視為無效突破，放棄該次嘗試（須重新出現有效翻邊才重試）。
  F3　同 C6：結構(2)越過0點，作廢重新尋找。
  F4　同 C5/C5'：僅影線突破/跌破、收盤未突破/跌破者不算（已內建於「收盤」比較）。

週期：不限。所有門檻以點數／根數表示。
"""

from __future__ import annotations

import bisect
import math
from dataclasses import dataclass

import pandas as pd

from wangtrader.core import Context, Order, Side, Strategy
from wangtrader.core.pivots import Pivot, find_pivots

METHOD_ID = "q2-04-02"

_LEVELS = ("prev_high", "prev_low", "prev_close", "sess_open")  # 檢查順序（書中未規定優先序，見待確認事項）


@dataclass
class Params:
    level: int = 2  # 峰谷點層級（p.143, p.151，層級2轉折點）
    min_side_bars: int = 3  # C1/C1'：突破前弱側須有的最少收盤根數（p.141, p.143）
    retrace_points: float = 15.0  # 折返停利（推論延用 q2-04-01 同一機制，書中未重新定義，見docstring）
    stop_points_cap: float = 20.0  # 停損點數上限，一般情況超過則改用「進場價 ± 此點數」
    major_event_stop: bool = False  # 重大事件（公投、選舉開票等）停損可超過20點，預設關閉（p.152–153）


class FourPillars(Strategy):
    method_id = METHOD_ID

    def __init__(self, **kw) -> None:
        self.p = Params(**kw)
        self._pivots: list[Pivot] = []
        self._levels: dict[str, dict] = {lv: self._fresh_level() for lv in _LEVELS}

    @staticmethod
    def _fresh_level() -> dict:
        # side/run：目前收盤所在側與連續根數；run_low/run_high：該段走勢的最低/最高點（作為 0 點來源）；
        # search：多、空各一組 N 型觀察（可並存）
        return {"side": None, "run": 0, "run_low": math.inf, "run_high": -math.inf,
                "search": {Side.LONG: None, Side.SHORT: None}}

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        self._pivots = find_pivots(df, level=self.p.level)
        self._piv_by_kind = {}
        for kind in ("peak", "trough"):
            arr = sorted((pv for pv in self._pivots if pv.kind == kind), key=lambda pv: pv.index)
            self._piv_by_kind[kind] = (arr, [pv.index for pv in arr])
        return df

    def _pivot_candidates(self, kind: str, after_index: int, as_of: int) -> list[Pivot]:
        """kind 的峰谷點中 index > after_index 且已確認（confirm <= as_of）者；以二分搜尋取區間。"""
        arr, idx = self._piv_by_kind[kind]
        lo = bisect.bisect_right(idx, after_index)
        hi = bisect.bisect_right(idx, as_of - self.p.level)  # confirm = index + level
        return arr[lo:hi]

    def _start_search(self, df: pd.DataFrame, i: int, side: Side, run_low: float, run_high: float) -> dict:
        b = df.iloc[i]
        zero_base = min(run_low, float(b["low"])) if side == Side.LONG else max(run_high, float(b["high"]))
        return {"side": side, "zero_i": i, "zero_base": zero_base, "zero_price": zero_base,
                "peak": None, "trough": None, "strong": 0, "weak_after": 0}

    def _advance_search(self, df: pd.DataFrame, i: int, st: dict) -> tuple[Side, float, float] | str | None:
        """與 q2-04-01 相同的 N型／倒N型三步驟狀態機，另加四柱的根數優勢判定（C4/C4'）。"""
        long = st["side"] == Side.LONG
        b = df.iloc[i]
        step1_kind = "peak" if long else "trough"
        step2_kind = "trough" if long else "peak"
        if st["peak"] is None:
            cands = self._pivot_candidates(step1_kind, st["zero_i"], i)
            if cands:
                pk = max(cands, key=lambda p: p.price) if long else min(cands, key=lambda p: p.price)
                # 0 點＝(1)形成前的最低（高）點；(1)之後的走勢屬拉回(2)，不能併入 0 點
                seg = df["low" if long else "high"].iloc[st["zero_i"]:pk.index + 1]
                st["zero_price"] = min(st["zero_base"], float(seg.min())) if long \
                    else max(st["zero_base"], float(seg.max()))
                st["peak"] = pk
            return None
        if st["trough"] is None:
            cands = self._pivot_candidates(step2_kind, st["peak"].index, i)
            if not cands:
                return None
            newest = max(cands, key=lambda p: p.index)
            violated = newest.price < st["zero_price"] if long else newest.price > st["zero_price"]
            if violated:  # F3/C6：(2) 越過 0 點，以此點為新 0 重新尋找
                st["zero_i"], st["zero_base"], st["zero_price"] = newest.index, newest.price, newest.price
                st["peak"], st["trough"] = None, None
            else:
                st["trough"] = newest
            return None
        cands = self._pivot_candidates(step2_kind, st["trough"].index, i)
        if cands:
            newest = max(cands, key=lambda p: p.index)
            violated = newest.price < st["zero_price"] if long else newest.price > st["zero_price"]
            if violated:
                st["zero_i"], st["zero_base"], st["zero_price"] = newest.index, newest.price, newest.price
                st["peak"], st["trough"] = None, None
                return None
            st["trough"] = newest
        broke = b["close"] > st["peak"].price if long else b["close"] < st["peak"].price
        if not broke:
            return None
        if st["strong"] <= st["weak_after"]:  # F2/C4：未取得根數優勢，放棄本次嘗試
            return "invalid"
        return st["side"], st["zero_price"], st["peak"].price

    def _update_level(self, df: pd.DataFrame, i: int, lv: dict, lvl_price: float):
        b = df.iloc[i]
        close, low, high = float(b["close"]), float(b["low"]), float(b["high"])
        cur_side = "above" if close > lvl_price else ("below" if close < lvl_price else lv["side"])
        if cur_side is None:  # 收盤剛好在關卡上且尚無所屬側
            return None
        flipped = lv["side"] is not None and cur_side != lv["side"]
        searches = lv["search"]
        if flipped:
            direction = Side.LONG if cur_side == "above" else Side.SHORT
            # 站回強側：既有同向觀察要通過根數優勢檢查（C4：關卡上方根數 > 拉回下方根數，p.141）
            cur = searches[direction]
            if cur is not None and cur["strong"] <= cur["weak_after"]:
                searches[direction] = None  # F2：突破無效
            # 尚無同向觀察時，本次翻邊即為一次突破/跌破嘗試：翻邊前弱側須有 >= min_side_bars 根（C1/F1）
            if searches[direction] is None and lv["run"] >= self.p.min_side_bars:
                searches[direction] = self._start_search(df, i, direction, lv["run_low"], lv["run_high"])
        for side, st in searches.items():
            if st is None:
                continue
            strong_side = "above" if side == Side.LONG else "below"
            if cur_side == strong_side:
                st["strong"] += 1
            else:
                st["weak_after"] += 1
        if flipped or lv["side"] is None:
            lv["side"], lv["run"], lv["run_low"], lv["run_high"] = cur_side, 1, low, high
        else:
            lv["run"] += 1
            lv["run_low"], lv["run_high"] = min(lv["run_low"], low), max(lv["run_high"], high)
        signal = None
        for side in (Side.LONG, Side.SHORT):
            st = searches[side]
            if st is None:
                continue
            sig = self._advance_search(df, i, st)
            if sig == "invalid":
                searches[side] = None
            elif sig is not None and signal is None:
                signal = sig
        return signal

    def _giveback_exit(self, ctx: Context) -> Order | None:
        """折返停利：最大獲利達 retrace_points 後啟動，自最有利價回落達 retrace_points 即出場。"""
        pos, p = ctx.pos, self.p
        if pos is None or ctx.i <= pos.entry_i or pos.max_profit() < p.retrace_points:
            return None
        if pos.max_profit() - pos.profit(ctx.bar()["close"]) >= p.retrace_points:
            return Order.exit("折返停利")
        return None

    def on_bar(self, ctx: Context):
        p, df, i = self.p, ctx.df, ctx.i
        if df.at[i, "bar_no"] == 0:  # 新交易日：四柱關卡重新計算，狀態全部重置
            self._levels = {lv: self._fresh_level() for lv in _LEVELS}
        orders: list[Order] = []
        if ctx.pos is not None:
            ex = self._giveback_exit(ctx)
            if ex is not None:
                orders.append(ex)
        # 四柱關卡的根數/翻邊/N型追蹤須每根K線持續更新，與是否持有部位無關（p.141「關卡前後K線根數」
        # 是對盤面的持續觀察）；只在「開新倉」動作上以 ctx.pos 把關。
        signal = None
        for lv_name in _LEVELS:
            lvl_price = df.at[i, lv_name]
            if pd.isna(lvl_price):
                continue
            sig = self._update_level(df, i, self._levels[lv_name], float(lvl_price))
            if sig is not None and signal is None:
                signal = (lv_name, sig)
        if ctx.pos is not None or signal is None:
            return orders or None
        lv_name, (side, zero_price, peak_price) = signal
        # 停損＝構成訊號前的拉回層級2谷點(2)/反彈層級2峰點(2)，而非0點（與 q2-04-01 不同，p.147-150）
        search = self._levels[lv_name]["search"][side]
        stop = search["trough"].price
        self._levels[lv_name]["search"][side] = None  # 完成一次訊號，重新等待下一次翻邊
        entry_price = float(df.at[i, "close"])
        # 一般情況下點數控制在 stop_points_cap 以內；重大事件（p.152–153）允許放寬，不受此上限
        if not p.major_event_stop and abs(entry_price - stop) > p.stop_points_cap:
            stop = entry_price - p.stop_points_cap if side == Side.LONG else entry_price + p.stop_points_cap
        name = f"四柱突破({lv_name})" if side == Side.LONG else f"四柱跌破({lv_name})"
        orders.append(Order.enter(side, stop=stop, reason=name, level=lv_name, zero=zero_price, peak=peak_price))
        return orders
