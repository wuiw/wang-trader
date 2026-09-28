"""q2-05-02 極端位置最大量（《期貨奇績2》第五章 逆向訊號，p.173–183）。

規格文件：methods/期貨奇績2/q2-05-02-極端位置最大量.md

訊號（p.173）：
  極端高點最大量（放空濾網）：某根 K 線的高點為當下盤中最高點，且成交量為當下盤中最大量
    （已剔除開盤第一根，C1）→ 以其低點為濾網，後續 K 線收盤無遮蔽跌破濾網即為放空訊號（C5/C6）。
  極端低點最大量（買進濾網）：鏡像，以其高點為濾網，收盤無遮蔽突破即為買進訊號（C1'）。
  濾網資格會被後續更高/更低 K 線立即取代（C3），若新高（低）K 線本身量未同創最大量，
  則當下沒有候選、需重新等待「新極端位置＋新最大量」同時成立的 K 線（C3/F4）。
  濾網建立後 max_filter_bars 根內須出現無遮蔽突破，否則失效（C6/F5）；若行情始終盤整在
  濾網 K 線高低範圍內（內包走勢）則不受根數限制（C7），但只要有影線越出範圍且未收盤突破，
  立即喪失此例外、視同逾時失效（F6）。
進場（p.175–176, 179–180）：訊號 K 線收盤進場；若收盤與停損位置（濾網 K 線本身的另一端）
  距離 > stop_points，先忽略，等拉回使距離縮小到 stop_points 以內再掛限價補進場，
  max_wait 根內未成交即放棄（書中未給明確等待根數，比照 q3-01 p.20 設參數，屬推論預設值）。
停損（p.173, p.175, p.179）：空單＝濾網 K 線（極端高點最大量 K 線）高點；
  多單＝濾網 K 線（極端低點最大量 K 線）低點；點數上限 stop_points（預設 20）。
過濾：
  F1 成交量 < min_volume（預設 1500 口）不列入候選（p.174）。
  F2 開盤第一根 K 線成交量不參與最大量評選（p.173, p.175）。
  F3/C4 濾網 K 線與盤中相對高低點的幅度（本模組以候選成立當下的 sess_high-sess_low 衡量，
    為原文「相對高低點距離」的具體化解讀，見待確認事項）≤ min_swing_points（預設 30）忽略。
  C3/F4 後續更高/更低 K 線出現，原濾網立即失效，需重新尋找同時創極端＋最大量的 K 線。
  F5/C6 濾網逾 max_filter_bars（預設 15 根）未出現無遮蔽突破，濾網失效，除非屬內包走勢（C7）。
  F6 僅影線觸及濾網、收盤未突破，不算訊號；若已脫離內包範圍，立即喪失根數限制特權。
  F7 訊號距停損位置 > stop_points：先忽略，等待折返縮小距離後再進場（掛限價補進場）。
出場：書中本節未針對本方法定義專屬停利機制（原文明確：「書中未明確說明」），本模組不實作
  停利，僅在停損觸發或（intraday）收盤時出場。

週期：不限。所有門檻以點數／根數表示；成交量門檻（口數）與 K 線週期無關，直接作為參數，
使用者需依自己使用的週期/商品調整（書中原用 1 分鐘 K 線、門檻 1500 口）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import pandas as pd

from wangtrader.core import Context, Order, Side, Strategy

METHOD_ID = "q2-05-02"


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
    min_volume: float = 1500.0        # F1（p.174），成交量門檻（口數）
    min_swing_points: float = 30.0    # C4/F3（p.174, 175），幅度門檻
    max_filter_bars: int = 15         # C6（p.176），濾網時效根數
    stop_points: float = 20.0         # 停損（風控）點數上限（p.175, 179）
    max_wait: int = 10                # 補進場等待根數（原文未給明確根數，推論比照 q3-01 p.20）
    max_wait_minutes: float | None = None  # 補進場等待分鐘（推論值無時間依據，預設 None＝用 max_wait 根）


@dataclass
class _SideState:
    bar: int | None = None        # 濾網 K 線 index（None＝目前無候選）
    level: float | None = None    # 濾網價位（空：候選K線低點；多：候選K線高點）
    bound: float | None = None    # 停損參考價位（空：候選K線高點；多：候選K線低點）
    inside: bool = True           # C7：是否仍維持「內包走勢」（尚無影線越出濾網K線高低範圍）


@dataclass
class _SessionState:
    vm: float = 0.0  # 當下盤中最大量（已剔除開盤第一根）
    hi: _SideState = field(default_factory=_SideState)  # 空方濾網（極端高點最大量）
    lo: _SideState = field(default_factory=_SideState)  # 多方濾網（極端低點最大量）


def _track_side(s: _SideState, df: pd.DataFrame, i: int, vm_prev: float, p: Params, *, is_short: bool):
    """更新單一方向（空/多）的濾網狀態，第 i 根收盤時觸發則回傳 (level, bound)，否則 None。"""
    bar_no = df.at[i, "bar_no"]
    if is_short:
        ext_col, near, far = "sess_high", df.at[i, "low"], df.at[i, "high"]
        prev_ext = df.at[i - 1, "sess_high"] if bar_no > 0 else None
        new_extreme = bar_no == 0 or df.at[i, "sess_high"] > prev_ext
    else:
        ext_col, near, far = "sess_low", df.at[i, "high"], df.at[i, "low"]
        prev_ext = df.at[i - 1, "sess_low"] if bar_no > 0 else None
        new_extreme = bar_no == 0 or df.at[i, "sess_low"] < prev_ext

    if new_extreme:
        s.bar = None  # C3：新的極端出現，舊濾網立即失效
        if bar_no > 0:  # F2：開盤第一根不參與最大量評選、也不參與候選資格
            swing = df.at[i, "sess_high"] - df.at[i, "sess_low"]
            vol_i = df.at[i, "volume"]
            if vol_i >= vm_prev and vol_i >= p.min_volume and swing > p.min_swing_points:
                s.bar, s.level, s.bound, s.inside = i, float(near), float(far), True
        return None

    if s.bar is None:
        return None

    age = i - s.bar
    close_ = df.at[i, "close"]
    breached = (close_ < s.level) if is_short else (close_ > s.level)
    if breached:
        ok = age <= p.max_filter_bars or s.inside  # C6 / C7
        level, bound = s.level, s.bound
        s.bar = None
        return (level, bound) if ok else None  # 逾時未破例外則直接失效（F5），不成立訊號

    poked = (df.at[i, "low"] < s.level) if is_short else (df.at[i, "high"] > s.level)
    if poked:
        s.inside = False  # F6：僅影線觸及濾網、收盤未突破 → 喪失內包走勢的免時效特權
    if age > p.max_filter_bars and not s.inside:
        s.bar = None  # F5：逾時且非內包走勢 → 濾網失效
    return None


class ExtremeMaxVolume(Strategy):
    method_id = METHOD_ID

    def __init__(self, **kw) -> None:
        self.p = Params(**kw)
        self._st: dict[int, _SessionState] = {}

    def _state(self, sess: int) -> _SessionState:
        return self._st.setdefault(sess, _SessionState())

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["trade_min"] = _trade_minutes(df)
        return df

    def on_bar(self, ctx: Context):
        p, df, i = self.p, ctx.df, ctx.i
        sess = int(df.at[i, "session"])
        st = self._state(sess)
        bar_no = df.at[i, "bar_no"]
        vm_prev = st.vm

        short_sig = _track_side(st.hi, df, i, vm_prev, p, is_short=True)
        long_sig = _track_side(st.lo, df, i, vm_prev, p, is_short=False)

        if bar_no > 0:  # F2：開盤第一根不列入最大量統計
            st.vm = max(st.vm, df.at[i, "volume"])

        if ctx.pos is not None:
            return None  # 未定義專屬停利，持倉時只等停損／收盤平倉

        close_ = df.at[i, "close"]
        orders: list[Order] = []
        for side, sig in ((Side.SHORT, short_sig), (Side.LONG, long_sig)):
            if sig is None:
                continue
            level, stop = sig
            reason = "極端位置最大量" + ("(空)" if side == Side.SHORT else "(多)")
            if abs(close_ - stop) <= p.stop_points:
                orders.append(Order.enter(side, stop=stop, reason=reason, filter_level=level))
            else:
                # F7：距停損 > stop_points，先忽略，等拉回縮小距離後掛限價補進場
                limit = stop + p.stop_points * int(side)
                orders.append(Order.enter_limit(side, limit=limit, expire=_wait_bars(df, i, p.max_wait_minutes, p.max_wait),
                                                 stop=stop, reason=reason + "(補進場)", filter_level=level))
        return orders or None
