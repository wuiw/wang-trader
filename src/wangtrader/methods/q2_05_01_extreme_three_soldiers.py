"""q2-05-01 極端位置紅三兵與黑三兵（《期貨奇績2》第五章逆向訊號，p.157–171）。

規格文件：methods/期貨奇績2/q2-05-01-極端位置紅三兵黑三兵.md

訊號（p.157–158）：
  紅三兵（多）：第一根紅K最低點為層級2轉折谷點且為當下盤中最低點、第一根收盤上漲；
    第二根收盤>第一根、第三根收盤>第二根，三根皆為上漲K線（不得平盤/十字線）；
    第一根最低點須為三根中最低。
  黑三兵（空）：與紅三兵鏡射（第一根黑K最高點為層級2轉折峰點且為當下盤中最高點……）。
  C0/C0' 極端位置前提（p.161）：由近期波段高（低）點到三兵組合最低（高）點的盤中高低距離須超過
    30 點，未達門檻者即使三兵三根K線本身完全符合定義，也不能作為訊號使用；此測量對象與 C4/C4'
    幅度濾網（三兵組合本身10～30點）不同，不可混用。本模組以 `core.bars.is_extreme_position()`
    （第一根K線為止，含跳空以平盤起算，p.162「以昨收起算」）實作，等同 q3-01「極端位置」定義。
進場（p.157–159, 163）：幅度（第一根極端點到三兵另一端）在 min_range～max_range 點之間才有效；
  進場價距停損（第一根極端點）≤ stop_max 點 → 第三根收盤立刻進場；
  距離較大 → 掛限價等拉回到「極端點 ± stop_max」，max_wait 根內未成交即失效。
停損（p.157–158）：紅三兵第一根最低點 / 黑三兵第一根最高點。
過濾：
  F1 任一根收平盤或十字線 → 不符合定義（以 close!=open 隱含達成，p.157–158）
  F2 第一根極端點非當下盤中最低/最高點 → 不算訊號（p.164）
  F3 幅度 < min_range → 無效（p.157–158）
  F4 幅度 > max_range → 宜忽略（skip_when_over_max_range=True）或等拉回/反彈補進場（預設，p.157–158）
  F5 同方向訊號被停損後，同型態訊號本交易日不再使用（p.163）
  F6/C0 由近期波段高（低）點到三兵組合的盤中高低距離未超過30點 → 不符合極端位置前提，不得使用（p.161）
出場：exit_mode = "retrace"（獲利超過15點後折返進場點出場，p.171）
  | "ladder"（p.171 圖5-20「預設初始獲利20點後啟動折返20點停利」：最大獲利達 ladder_target 後，
    自最有利價回落達 ladder_target 即出場，停利點隨新高逐階上移）| "none"。
層級2轉折點採不嚴格比較（允許相鄰K線等低/等高）：p.162「三根黑K線的低點都是一樣的，這是允許的」。
  書中兩種出場描述並存、未言明何時分別適用，見模組末待確認事項。

週期：不限，1 分鐘 K 線為書中範例，門檻皆以點數表示。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd

from wangtrader.core import Context, Order, Side, Strategy
from wangtrader.core.bars import is_extreme_position
from wangtrader.core.exits import retrace_exit
from wangtrader.core.pivots import Pivot, find_pivots

METHOD_ID = "q2-05-01"


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
    level: int = 2  # 峰谷點層級（p.157，層級2轉折點）
    min_range: float = 10.0  # C4/C4'：幅度下限，<此點數無效訊號（p.157–158）
    max_range: float = 30.0  # C4/C4'：幅度上限，>此點數宜忽略或等拉回/反彈（p.157–158）
    swing_range: float = 30.0  # C0/F6：極端位置前提，近期波段高低點到三兵組合的盤中距離下限（p.161）
    swing_from_prev_close: float = 40.0  # C0/F6：距平盤替代門檻（p.162「以昨收起算」）
    skip_when_over_max_range: bool = False  # 幅度超過上限時：False=補進場等拉回；True=直接忽略（書中(a)(b)並列，見12）
    stop_max: float = 20.0  # 停損控制上限，亦作補進場之目標距離（p.157–158, 163）
    max_wait: int = 10  # 補進場等待根數（書中未給明確數字，比照 q3-01 慣例預設，見12）
    max_wait_minutes: float | None = None  # 補進場等待分鐘（推論值無時間依據，預設 None＝用 max_wait 根）
    stopped_no_repeat: bool = True  # F5：同方向訊號被停損後本交易日不再使用（p.163）
    exit_mode: str = "retrace"  # "retrace" | "ladder" | "none"
    retrace_target: float = 15.0  # 折返停利：獲利超過15點後折返進場點出場（p.171）
    ladder_target: float = 20.0  # 階梯式移動停利：初始獲利20點後啟動（p.171）


class ExtremeThreeSoldiers(Strategy):
    method_id = METHOD_ID

    def __init__(self, **kw) -> None:
        self.p = Params(**kw)
        self._pivots: list[Pivot] = []
        self._stopped_sides: dict[int, set[Side]] = {}

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["trade_min"] = _trade_minutes(df)
        self._pivots = find_pivots(df, level=self.p.level, strict=False)  # 允許等低/等高（p.162）
        return df

    def _pivot_at(self, idx: int, kind: str, as_of: int) -> Pivot | None:
        for pv in self._pivots:
            if pv.index == idx and pv.kind == kind and pv.confirm <= as_of:
                return pv
        return None

    def detect(self, df: pd.DataFrame, i: int) -> tuple[Side, float, float] | None:
        """第 i 根收盤時是否成立紅三兵/黑三兵，回傳 (方向, 停損極端價, 幅度)。"""
        if i < 2:
            return None
        a, b, c = df.iloc[i - 2], df.iloc[i - 1], df.iloc[i]
        if not (a["session"] == b["session"] == c["session"]):
            return None
        # 紅三兵（多）：C1-C3
        if (
            a["close"] > a["open"] and b["close"] > b["open"] and c["close"] > c["open"]
            and b["close"] > a["close"] and c["close"] > b["close"]
            and a["low"] <= b["low"] and a["low"] <= c["low"]
        ):
            pv = self._pivot_at(i - 2, "trough", i)
            if pv is not None and a["low"] == df.at[i, "sess_low"]:
                # F6/C0：近期波段高點到第一根紅K最低點的盤中距離須超過30點（p.161，以a所在K線為準）
                if is_extreme_position(df, i - 2, self.p.swing_range, self.p.swing_from_prev_close):
                    amp = max(a["high"], b["high"], c["high"]) - a["low"]
                    return Side.LONG, float(a["low"]), float(amp)
        # 黑三兵（空）：C1'-C3'
        if (
            a["close"] < a["open"] and b["close"] < b["open"] and c["close"] < c["open"]
            and b["close"] < a["close"] and c["close"] < b["close"]
            and a["high"] >= b["high"] and a["high"] >= c["high"]
        ):
            pv = self._pivot_at(i - 2, "peak", i)
            if pv is not None and a["high"] == df.at[i, "sess_high"]:
                # F6/C0'：近期波段低點到第一根黑K最高點的盤中距離須超過30點（p.161，鏡射）
                if is_extreme_position(df, i - 2, self.p.swing_range, self.p.swing_from_prev_close):
                    amp = a["high"] - min(a["low"], b["low"], c["low"])
                    return Side.SHORT, float(a["high"]), float(amp)
        return None

    def _ladder_exit(self, ctx: Context) -> Order | None:
        """階梯式移動停利（p.171 圖5-20）：最大獲利達 ladder_target 後啟動，自最有利價回落達 ladder_target 即出場。"""
        pos, t = ctx.pos, self.p.ladder_target
        if pos is None or ctx.i <= pos.entry_i or pos.max_profit() < t:
            return None
        if pos.max_profit() - pos.profit(ctx.bar()["close"]) >= t:
            return Order.exit("階梯式移動停利")
        return None

    def on_bar(self, ctx: Context):
        p, df, i = self.p, ctx.df, ctx.i
        sess = df.at[i, "session"]
        if ctx.stopped is not None:
            self._stopped_sides.setdefault(sess, set()).add(ctx.stopped.side)
        if ctx.pos is not None:
            ex = {
                "retrace": lambda: retrace_exit(ctx, p.retrace_target, 0.0),
                "ladder": lambda: self._ladder_exit(ctx),
                "none": lambda: None,
            }[p.exit_mode]()
            return [ex] if ex else None
        hit = self.detect(df, i)
        if hit is None:
            return None
        side, ext, amp = hit
        # F3
        if amp < p.min_range:
            return None
        # F5
        if p.stopped_no_repeat and side in self._stopped_sides.get(sess, set()):
            return None
        name = "紅三兵" if side == Side.LONG else "黑三兵"
        c = df.iloc[i]
        limit = ext + p.stop_max * int(side)
        # F4：幅度超過上限
        if amp > p.max_range:
            if p.skip_when_over_max_range:
                return None
            return [Order.enter_limit(side, limit=limit, expire=_wait_bars(df, i, p.max_wait_minutes, p.max_wait),
                                       stop=ext, reason=name + "(補進場)", extreme=ext)]
        if abs(c["close"] - ext) <= p.stop_max:
            return [Order.enter(side, stop=ext, reason=name, extreme=ext)]
        return [Order.enter_limit(side, limit=limit, expire=_wait_bars(df, i, p.max_wait_minutes, p.max_wait),
                                   stop=ext, reason=name + "(補進場)", extreme=ext)]
