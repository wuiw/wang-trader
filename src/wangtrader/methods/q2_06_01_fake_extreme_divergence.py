"""q2-06-01 假性創新高 / 假性創新低背離（假面峰谷背離）（《期貨奇績2》第六章，p.190–202）。

規格文件：methods/期貨奇績2/q2-06-01-假性創新高創新低背離.md

訊號（p.191）：完全不用指標，只比較 K 線影線極端值與收盤價是否同步創新高（低）。
  放空（背離向下）：
    C1 行情先走出波段峰點 A（當下盤中最高K線），A 所在前波區域的最高收盤為 B。
    C2 後續 K 線影線 C 突破 A，創當下行情新高。
    C3 本波（由 A 之後的拉回低點起算，到 C 為止）的最高收盤卻比 B 低，即收盤未同步創新高
       → C 為假性創新高峰點（p.191 圖6-3：「本波的最高收盤價D卻低於B」；D 是 C 前一根，非後一根）。
       本波已有收盤 ≥ B 者，C 是正常同步創新高，不是假性峰點。
    C4 以 C 的最低點畫水平濾網。
    C5 濾網形成後若又有 K 線高點創出比 C 更高的位置 → C 失效，以新高K線重新判定。
    C6 後續 K 線收盤跌破濾網 → 背離放空訊號。
  買進（背離向上）：鏡像規則 C1'–C6'（p.196, 199）。
  例外（3.3，p.195）：濾網未破前，若本波又出現收盤回到（或超過）B，
    視為「打平不算假突破」，放棄本次背離訊號尋找（原文舉「一般高」例，本模組以「回到或超過」實作）。

進場（p.191, 196）：收盤跌破（突破）濾網時進場；若距假性峰（谷）點（停損參考價）超過
  stop_points，先忽略，等拉回使距離縮小到 stop_points 以內再掛限價補進場，max_wait 根內
  未成交即放棄（書中未給明確等待根數，比照 q3-01 p.20 設參數，屬推論預設值）。
停損（p.194, 196）：放空以假性峰點的最高點（影線）為停損；買進以假性谷點的最低點為停損；
  點數上限 stop_points（預設 20）。
過濾：
  F1 盤中高低震幅（含跳空：以昨收與盤中高低點的最大距離衡量，p.194「包括跳空至盤中高低點」、
    p.197「連同跳空」）須 > min_swing_points（預設 40）才算極端位置，否則不做（p.194, 197）。書中另有「跳空夠大可放寬」與「跳空過小、
    震幅<25 更嚴格」兩則未給出可計算公式的個案（p.194, 197），本模組未實作，維持單一門檻。
  F2 濾網未破前，收盤回到（或超過）前波區域最高（最低）收盤 → 放棄本次訊號尋找（p.195）。
  F3/C5 濾網形成後又出現更高（低）的影線 → 原峰（谷）點失效，須重新尋找（p.191）。
  F4 訊號距停損位置 > stop_points，先忽略，等待折返縮小距離後再進場（p.194, 196）。
出場：書中未明確說明本方法的出場、停利或反手規則，本模組不實作，僅在停損觸發或
  （intraday）收盤時出場。

週期：不限。所有門檻以點數／根數表示。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import pandas as pd

from wangtrader.core import Context, Order, Side, Strategy

METHOD_ID = "q2-06-01"


def _trade_minutes(df: pd.DataFrame) -> pd.Series:
    """累計交易分鐘（供「原文以時間描述」的分鐘版參數用）：同一交易日內取相鄰K線 time 差；交易日第一根
    只計一根K線長（沿用之前最近一次的日內時間差，無則 0），不含休市時間，跨日計時與根數語意一致。
    只用當下及之前的時間戳；time 非時間戳時全為 NaN（呼叫端退回根數）。"""
    t = df["time"] if "time" in df.columns else None
    if t is None or not pd.api.types.is_datetime64_any_dtype(t):
        return pd.Series(float("nan"), index=df.index)
    step = t.diff().dt.total_seconds() / 60.0
    if "session" in df.columns:
        step = step.where(df["session"].eq(df["session"].shift()))
    return step.fillna(step.ffill()).fillna(0.0).cumsum()


def _elapsed(df: pd.DataFrame, a: int, b: int, minutes: float | None, bars: float | None) -> tuple[float, float | None]:
    """第 a 根到第 b 根的經過量與上限：minutes 有設且有交易分鐘欄（trade_min）時回傳（經過分鐘, minutes），
    否則退回（經過根數, bars）。"""
    if minutes is not None and "trade_min" in df.columns:
        m = df.at[b, "trade_min"] - df.at[a, "trade_min"]
        if m == m:
            return float(m), minutes
    return float(b - a), bars


def _wait_bars(df: pd.DataFrame, i: int, minutes: float | None, bars: int) -> int:
    """補進場等待根數：minutes 有設且有交易分鐘欄時，依本根K線長（與前一根的交易分鐘差）換算成根數
    （無條件進位、至少 1）；否則用 bars。"""
    if minutes is not None and "trade_min" in df.columns and i > 0:
        step = df.at[i, "trade_min"] - df.at[i - 1, "trade_min"]
        if step == step and step > 0:
            return max(1, math.ceil(minutes / step - 1e-9))
    return bars


@dataclass
class Params:
    min_swing_points: float = 40.0    # F1（p.194, 197），極端位置的最小盤中幅度
    stop_points: float = 20.0         # 停損（風控）點數上限（p.194, 196）
    max_wait: int = 10                # 補進場等待根數（原文未給明確根數，推論比照 q3-01 p.20）
    max_wait_minutes: float | None = None  # 補進場等待分鐘（推論值無時間依據，預設 None＝用 max_wait 根）


@dataclass
class _SideState:
    ext_i: int | None = None         # 當下盤中極端（空：最高；多：最低）所在 K 線
    peak: int | None = None          # 已確立的假性峰（谷）點 K 線 index
    level: float | None = None       # 濾網價位（假性峰谷點的最低/最高點）
    bound: float | None = None       # 停損參考價位（假性峰谷點的最高/最低影線）
    ref_close: float | None = None   # B：前波最高（低）收盤，供 3.3「打平放棄」比較


@dataclass
class _SessionState:
    start_i: int = 0
    hi: _SideState = field(default_factory=_SideState)  # 空方（假性創新高）
    lo: _SideState = field(default_factory=_SideState)  # 多方（假性創新低）


def _swing(df: pd.DataFrame, i: int) -> float:
    """盤中高低震幅，含跳空（p.194）：昨收與盤中高低點一併納入。"""
    hi, lo, pc = df.at[i, "sess_high"], df.at[i, "sess_low"], df.at[i, "prev_close"]
    if pd.notna(pc):
        hi, lo = max(hi, pc), min(lo, pc)
    return float(hi - lo)


def _track_side(s: _SideState, df: pd.DataFrame, i: int, start_i: int, p: Params, *, is_short: bool):
    """更新單一方向的假性峰谷背離狀態，觸發訊號時回傳 (level, bound)，否則 None。"""
    bar_no = i - start_i
    high_, low_, close_ = df.at[i, "high"], df.at[i, "low"], df.at[i, "close"]
    closes = df["close"]
    if is_short:
        new_extreme = bar_no == 0 or high_ > df.at[i - 1, "sess_high"]
        near, far, wick = low_, high_, high_
        far_col, agg, worse = "low", max, (lambda a, b: a < b)  # worse(a,b)：a 比 b 差（收盤未創新高）
    else:
        new_extreme = bar_no == 0 or low_ < df.at[i - 1, "sess_low"]
        near, far, wick = high_, low_, low_
        far_col, agg, worse = "high", min, (lambda a, b: a > b)

    # 1. 已有假性峰（谷）點濾網：檢查失效 / 打平放棄 / 收盤突破
    if s.peak is not None:
        if new_extreme and worse(s.bound, wick):
            s.peak = None  # C5：新高（低）超越假性峰（谷）點本身 → 失效，本根當作新的 C 重新判定
        else:
            if worse(close_, s.level):  # C6：收盤跌破（突破）濾網
                level, bound = s.level, s.bound
                s.peak = None
                return (level, bound)
            if not worse(close_, s.ref_close):
                s.peak = None  # F2/3.3：本波收盤回到（或超過）B → 打平，放棄本次訊號尋找
            return None

    if not new_extreme:
        return None
    prev_ext_i, s.ext_i = s.ext_i, i
    if bar_no == 0 or prev_ext_i is None:
        return None
    # 2. 本根 C 創新高（低）：以「本波」（前一極端 A 之後的拉回低（高）點起算）最高（低）收盤與
    #    前波最高（低）收盤 B 比較（p.191 圖6-3、p.195）
    if i - prev_ext_i >= 2:
        seg = df[far_col].iloc[prev_ext_i + 1:i].to_numpy()
        trough_i = prev_ext_i + 1 + int(seg.argmin() if is_short else seg.argmax())
        ref = agg(closes.iloc[start_i:trough_i + 1])
        wave_best = agg(closes.iloc[trough_i + 1:i + 1])
    else:  # 緊接前一極端，無拉回段：以前面全部收盤為 B
        ref = agg(closes.iloc[start_i:i])
        wave_best = close_
    if worse(wave_best, ref) and _swing(df, i) > p.min_swing_points:
        s.peak, s.level, s.bound, s.ref_close = i, float(near), float(far), float(ref)
    return None


class FakeExtremeDivergence(Strategy):
    method_id = METHOD_ID

    def __init__(self, **kw) -> None:
        self.p = Params(**kw)
        self._st: dict[int, _SessionState] = {}

    def _state(self, sess: int, i: int) -> _SessionState:
        if sess not in self._st:
            self._st[sess] = _SessionState(start_i=i)
        return self._st[sess]

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["trade_min"] = _trade_minutes(df)
        return df

    def on_bar(self, ctx: Context):
        p, df, i = self.p, ctx.df, ctx.i
        sess = int(df.at[i, "session"])
        st = self._state(sess, i)

        short_sig = _track_side(st.hi, df, i, st.start_i, p, is_short=True)
        long_sig = _track_side(st.lo, df, i, st.start_i, p, is_short=False)

        if ctx.pos is not None:
            return None  # 書中未定義專屬停利，持倉時只等停損／收盤平倉

        close_ = df.at[i, "close"]
        orders: list[Order] = []
        for side, sig in ((Side.SHORT, short_sig), (Side.LONG, long_sig)):
            if sig is None:
                continue
            level, stop = sig
            reason = "假性創新高背離" if side == Side.SHORT else "假性創新低背離"
            if abs(close_ - stop) <= p.stop_points:
                orders.append(Order.enter(side, stop=stop, reason=reason, filter_level=level))
            else:
                # F4：距停損 > stop_points，先忽略，等拉回縮小距離後掛限價補進場
                limit = stop + p.stop_points * int(side)
                orders.append(Order.enter_limit(side, limit=limit, expire=_wait_bars(df, i, p.max_wait_minutes, p.max_wait),
                                                 stop=stop, reason=reason + "(補進場)", filter_level=level))
        return orders or None
