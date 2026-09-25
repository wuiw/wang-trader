"""q3-05 過三高買訊／破三低空訊（《期貨奇績3》第五章，p.101–117）。

規格文件：methods/期貨奇績3/q3-05-過三高破三低.md

訊號（p.101–103）：
  破三低空訊（空）：行情出現「當下盤中最高K線」後，第一根收盤跌破前1根K線最低點的K線，
    其收盤同時跌破前 lookback（3）根K線區間最低點；自最高K線起算，之前沒有任何K線收盤曾跌破
    前1根最低點（p.101–102）。
  過三高買訊（多）：鏡像，最低K線之後第一次收盤同時突破前1根與前3根區間最高點。
  「前三根」：訊號K之前本交易日須有 3 根K線可比較（p.104「絕對是前面要有三根 K 線，少一根就不算」；
    圖5-3 開盤第一根即最高、第三根跌破前兩根低點不算）。比較區間可含最高K線本身與其之前的K線：
    最高K線當根就跌破前三低亦成立（p.103 圖5-2），一般在最高K線後三根內發生（p.103）。
跳空前提（p.103）：跳高開盤時，過三高須待出現層級1谷點才有效；跳低開盤時，破三低須待層級1峰點
  （層級1峰谷點沿用 core.pivots，level=1，只用已確認者，且左右鄰居須在同一交易日）。
訊號K與極端K的距離上限（p.107）：訊號K須在極端K線（峰／谷點）之後最多 max_signal_delay（4）根
  K線以內出現，超過視為無效。
無遮蔽收盤（p.106）：訊號K的收盤須是自極端K線出現後最低（破三低）／最高（過三高）、未被期間
  內其他K線低點（高點）遮蔽的收盤；若極端K與訊號K之間有任一根K線的低點低於（高點高於）訊號K
  收盤，視為遮蔽，訊號不成立。
進場（p.104–105, p.112–113）：訊號K距極端位置 ≤20點直接進場；20~40點可選「等拉回至距極端點20點內」
  或「直接進場（停損仍20點）」；>40點通常忽略不操作。
停損（p.104–105, p.112–113）：設在極端點（p.113「上漲觸及 A 高點停損」；穿越 stop_tick 即出場），
  但距進場價最多 20 點（直接進場且距離較大時＝進場價 ± 20，p.105「當下進場，停損仍設在 20 點」）。
停損後反手（p.113，圖5-12）：若行情尚未朝訊號方向獲利達15點即觸停損，其後K線收盤創session新高
  （原空單）／新低（原多單），可反手，反手以進場價為基準設20點停損。
既有部位遇反向訊號（p.108–109, 111）：新訊號K與原部位進場訊號K的實體重疊 → 忽略，不平倉反手；
  不重疊 → 視為有效訊號，平倉並反手（交給引擎的預設反手機制處理）。此「重疊須忽略」規則只適用於
  原部位仍持有中的情況（p.111）：若原部位已先行平倉（例如已依15點折返規則出場），後出現的反向訊號
  即使實體侵入也不算重疊，視為全新獨立訊號（本模組只在 ctx.pos 仍為原方向時才套用重疊檢查，天然符合此前提）。
出場（p.111，新增）：折返平倉——獲利曾達 retrace_trigger（15點）後又折返回進場價（含）以下，
  即撤單平倉了結（沿用 core.exits.retrace_exit）。除此之外書中未明確說明本訊號其他的停利／移動
  停損機制，出場來源為：停損、折返平倉、停損後反手（換邊）、實體不重疊時的反向訊號反手，以及收盤強制平倉。

週期：不限（書中以5分鐘K線示範，程式不假設週期）。所有門檻以點數／根數表示。
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from wangtrader.core import Context, Order, Side, Strategy
from wangtrader.core.exits import retrace_exit
from wangtrader.core.pivots import Pivot, confirmed_before, find_pivots

METHOD_ID = "q3-05"


@dataclass
class Params:
    lookback: int = 3  # 前N根比較區間，C2/C3（p.101, p.104-105）
    stop_points: float = 20.0  # 單筆最大風險（p.104-105, p.112-113）
    stop_tick: float = 1.0  # 極端點穿越此點數即停損（p.23「穿越 1 個跳動單位」）
    immediate_distance: float = 20.0  # 距極端 ≤此值直接進場（p.104-105）
    ignore_beyond: float = 40.0  # 距極端 >此值通常忽略（p.112-113）
    far_entry_mode: str = "pullback"  # 20~40點區間："pullback" 等拉回 | "direct" 直接進場 | "ignore"
    max_wait: int = 10  # 補進場等待根數（書中未給明確數字，沿用範本慣例）
    reversal_profit_threshold: float = 15.0  # 停損反手資格門檻：未達此獲利觸停損才可反手（p.113）
    require_pivot_after_gap: bool = True  # 跳空前提（p.103），原文明文規則，預設開啟
    pivot_level: int = 1  # 層級1峰谷點（p.103）
    max_signal_delay: int = 4  # C4：訊號K須在極端K後最多此根數以內（p.107）
    retrace_trigger: float = 15.0  # 折返平倉門檻（p.111）


class BreakThreeHighLow(Strategy):
    method_id = METHOD_ID

    def __init__(self, **kw) -> None:
        self.p = Params(**kw)
        self._state: dict[int, dict] = {}
        self._reversal_watch: dict[int, Side] = {}
        self._pivots: list[Pivot] = []

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        lv = self.p.pivot_level
        sess = df["session"].to_numpy()
        # 峰谷點的左右鄰居須在同一交易日（不跨日比較）
        self._pivots = [pv for pv in find_pivots(df, level=lv)
                        if sess[pv.index - lv] == sess[pv.index] == sess[pv.index + lv]]
        return df

    # ---------- 極端狀態追蹤（每根都跑，不受持倉影響） ----------

    def _track_pre(self, df: pd.DataFrame, i: int) -> dict:
        """偵測前：只更新「目前為止」的極端值，供本根判斷 C1 用。"""
        sess = int(df.at[i, "session"])
        st = self._state.setdefault(sess, {"h_idx": None, "h_val": None, "h_valid": True,
                                            "l_idx": None, "l_val": None, "l_valid": True})
        b = df.iloc[i]
        if st["h_idx"] is None or b["high"] >= st["h_val"]:
            st["h_idx"], st["h_val"], st["h_valid"] = i, float(b["high"]), True
        if st["l_idx"] is None or b["low"] <= st["l_val"]:
            st["l_idx"], st["l_val"], st["l_valid"] = i, float(b["low"]), True
        return st

    def _track_post(self, df: pd.DataFrame, i: int, st: dict) -> None:
        """偵測後：消耗「首次跌破/突破前一根」的有效性，供下一根使用（自極端K線當根起算）。"""
        if i < 1 or df.at[i, "session"] != df.at[i - 1, "session"]:
            return
        b = df.iloc[i]
        if b["close"] < df.at[i - 1, "low"]:
            st["h_valid"] = False
        if b["close"] > df.at[i - 1, "high"]:
            st["l_valid"] = False

    def _has_pivot(self, df: pd.DataFrame, i: int, sess: int, kind: str) -> bool:
        cps = confirmed_before(self._pivots, i, kind)
        return any(df.at[p.index, "session"] == sess for p in cps)

    # ---------- 訊號偵測 ----------

    @staticmethod
    def _is_masked(df: pd.DataFrame, extreme_idx: int, i: int, close: float, side: Side) -> bool:
        """C5：極端K與訊號K之間，是否有K線的低點更低（破三低）/高點更高（過三高），遮蔽了訊號K的收盤（p.106）。"""
        if i <= extreme_idx + 1:
            return False
        window = df.iloc[extreme_idx + 1 : i]
        if side == Side.SHORT:
            return bool((window["low"] < close).any())
        return bool((window["high"] > close).any())

    def detect(self, df: pd.DataFrame, i: int, st: dict) -> tuple[Side, float, int] | None:
        """判斷第 i 根是否成立 C1-C5（不含跳空前提與距離過濾）。回傳 (方向, 極端價, 極端K索引)。"""
        n = self.p.lookback
        if i < n or df.at[i, "bar_no"] < n:  # 本交易日內前面要有 n 根K線可比較（p.104）
            return None
        b, p1 = df.iloc[i], df.iloc[i - 1]
        window_low = df["low"].iloc[i - n:i].min()
        window_high = df["high"].iloc[i - n:i].max()
        if (st["h_idx"] is not None and st["h_valid"]
                and b["close"] < p1["low"] and b["close"] < window_low):
            h_idx = st["h_idx"]
            if i - h_idx <= self.p.max_signal_delay and not self._is_masked(df, h_idx, i, float(b["close"]), Side.SHORT):
                return Side.SHORT, st["h_val"], h_idx
            return None
        if (st["l_idx"] is not None and st["l_valid"]
                and b["close"] > p1["high"] and b["close"] > window_high):
            l_idx = st["l_idx"]
            if i - l_idx <= self.p.max_signal_delay and not self._is_masked(df, l_idx, i, float(b["close"]), Side.LONG):
                return Side.LONG, st["l_val"], l_idx
            return None
        return None

    def _stop(self, side: Side, entry: float, ext: float) -> float:
        """停損＝極端點外 stop_tick，但距進場價最多 stop_points（p.105, 113）。"""
        p = self.p
        if side == Side.LONG:
            return max(ext - p.stop_tick, entry - p.stop_points)
        return min(ext + p.stop_tick, entry + p.stop_points)

    def _entry_orders(self, side: Side, close: float, ext: float, reason: str) -> list[Order]:
        p = self.p
        sgn = int(side)
        dist = abs(close - ext)
        if dist > p.ignore_beyond:
            return []
        if dist <= p.immediate_distance:
            return [Order.enter(side, stop=self._stop(side, close, ext), reason=reason)]
        if p.far_entry_mode == "direct":
            return [Order.enter(side, stop=self._stop(side, close, ext), reason=reason + "(直接進場)")]
        if p.far_entry_mode == "pullback":
            limit = ext + p.immediate_distance * sgn
            return [Order.enter_limit(side, limit=limit, expire=p.max_wait, stop=self._stop(side, limit, ext),
                                      reason=reason + "(補進場)")]
        return []  # far_entry_mode == "ignore"

    def on_bar(self, ctx: Context):
        p, df, i = self.p, ctx.df, ctx.i
        sess = int(df.at[i, "session"])
        b = df.iloc[i]
        st = self._track_pre(df, i)
        result: list[Order] | None = None

        # 0. 折返平倉（p.111）：獲利曾達 retrace_trigger 後又折返回進場價 → 撤單平倉
        if ctx.pos is not None:
            ex = retrace_exit(ctx, p.retrace_trigger, 0.0)
            if ex is not None:
                self._track_post(df, i, st)
                return [ex]

        # 1. 停損：判斷是否具備反手資格（未達15點獲利即觸停損）
        if ctx.stopped is not None:
            t = ctx.stopped
            reached = False
            if t.exit_i > t.entry_i + 1:
                seg = df.iloc[t.entry_i + 1:t.exit_i]
                if t.side == Side.LONG:
                    reached = (seg["high"].max() - t.entry_price) >= p.reversal_profit_threshold
                else:
                    reached = (t.entry_price - seg["low"].min()) >= p.reversal_profit_threshold
            if not reached:
                self._reversal_watch[sess] = Side.SHORT if t.side == Side.LONG else Side.LONG
            else:
                self._reversal_watch.pop(sess, None)

        # 2. 反手觸發：收盤創session新高/新低
        watch = self._reversal_watch.get(sess)
        if result is None and watch is not None and ctx.pos is None and i >= 1:
            if watch == Side.LONG and b["close"] > df.at[i - 1, "sess_high"]:
                self._reversal_watch.pop(sess, None)
                result = [Order.enter(Side.LONG, stop=b["close"] - p.stop_points, reason="停損反手")]
            elif watch == Side.SHORT and b["close"] < df.at[i - 1, "sess_low"]:
                self._reversal_watch.pop(sess, None)
                result = [Order.enter(Side.SHORT, stop=b["close"] + p.stop_points, reason="停損反手")]

        # 3. 一般訊號（過三高／破三低）
        if result is None:
            hit = self.detect(df, i, st)
            if hit is not None:
                side, ext, _h_idx = hit
                name = "破三低" if side == Side.SHORT else "過三高"
                ok = True
                if p.require_pivot_after_gap and pd.notna(b["prev_close"]):
                    gap_up = b["sess_open"] > b["prev_close"]
                    gap_down = b["sess_open"] < b["prev_close"]
                    if side == Side.LONG and gap_up and not self._has_pivot(df, i, sess, "trough"):
                        ok = False
                    if side == Side.SHORT and gap_down and not self._has_pivot(df, i, sess, "peak"):
                        ok = False
                if ok:
                    orders = self._entry_orders(side, float(b["close"]), ext, name)
                    if orders:
                        body_lo = float(min(b["open"], b["close"]))
                        body_hi = float(max(b["open"], b["close"]))
                        for od in orders:
                            od.meta["body_low"] = body_lo
                            od.meta["body_high"] = body_hi
                        # F4：既有反向部位時，檢查與原部位訊號K實體是否重疊
                        if ctx.pos is not None and ctx.pos.side != side:
                            plo, phi = ctx.pos.meta.get("body_low"), ctx.pos.meta.get("body_high")
                            if plo is not None and not (body_hi < plo or phi < body_lo):
                                orders = None  # 實體重疊，忽略本次反向訊號
                        result = orders

        self._track_post(df, i, st)
        return result
