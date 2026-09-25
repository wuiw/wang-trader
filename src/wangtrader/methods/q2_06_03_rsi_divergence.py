"""q2-06-03 RSI 背離訊號（《期貨奇績2》第六章，p.220–227）。

規格文件：methods/期貨奇績2/q2-06-03-RSI背離訊號.md

訊號（p.220）：
  背離向下（空，A/B 皆指價格波峰）：
    C1 A＝前波峰位，對應 RSI(5) 須突破嚴重超買 90 以上。
    C2 之後 RSI 跌破 50 以下（可反覆穿越），但不能跌破超賣區 20。
    C3 拉回後須形成一個層級 2 谷點。
    C4 價格再度突破 A、創當下新高（B），但 B 對應 RSI 不再穿越 90
       （若又衝上 90 以上，視為新的 A，重新計算，屬 C4 的自然延伸；B 形成後、訊號前若再創更高的高點
       仍以最高點為 B，若此時 RSI 達 90 則同樣改為新的 A）。
    C5 （推論，原文列買進版本，此為鏡像）B 之後 RSI 再度向下跌破 50 時，即為放空訊號。
  背離向上（多，鏡像相同邏輯）：A/B 皆為價格波谷，RSI 門檻改為跌破 10 以下、
    RSI 上緣不得超過 80、訊號為 RSI 再度向上突破 50。
  D4 A、B 兩端點時間距離（根數）須 <= max_gap_bars（預設 30，p.227）；B 形成後等待 RSI 穿越 50 的
     時間不計入（書中限制的是兩端點距離）。

進場（p.220）：訊號成立當根即以收盤價進場，無需等待拉回。

停損（p.226）：書中取「0 位法」與「端點極端值法」中距離較近者，且原則上 <= stop_points（預設 20）；
  「0 位法」原文僅提及概念、未展開換算方式，本模組**未實作**（見模組尾端待確認事項），
  僅實作「端點極端值法」＝以 B 點價位為停損；若其距離超過 stop_points，改以「訊號價 ± stop_points」
  的點數法近似取代未展開的 0 位法（推論，非原文明文規定）。

出場：書中未見固定停利規則，僅靠停損與收盤（intraday）強制平倉。

過濾：
  F1 A、B 時間距離 > max_gap_bars → 忽略（p.227）
  F2 A、B 之間 RSI 跌破 os_breach=20（空方）／突破 ob_breach=80（多方）→ 忽略（p.220，推論延伸 D3）
  F3 B 對應 RSI 仍 >= 90（空方）／<= 10（多方）→ 視為新的 A，重新計算（p.220，C4 的自然延伸）

週期：不限。所有門檻以點數／根數表示。
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from wangtrader.core import Context, Order, Side, Strategy
from wangtrader.core.indicators import rsi as rsi_indicator
from wangtrader.core.pivots import Pivot, find_pivots

METHOD_ID = "q2-06-03"


@dataclass
class Params:
    rsi_period: int = 5
    rsi_method: str = "wilder"
    ob_extreme: float = 90.0  # 嚴重超買門檻（p.220）
    os_extreme: float = 10.0  # 嚴重超賣門檻（p.220）
    mid: float = 50.0  # 進場穿越線（p.220）
    os_breach: float = 20.0  # 空方背離途中 RSI 不可跌破（p.220）
    ob_breach: float = 80.0  # 多方背離途中 RSI 不可突破（p.220）
    pivot_level: int = 2  # 層級 2 轉折點（p.220）
    max_gap_bars: int = 30  # 兩端點時間距離上限，書中「30 根 K 線」（p.227）
    stop_points: float = 20.0  # 停損點數上限（p.226）


@dataclass
class _Track:
    """背離端點追蹤狀態（單一方向）。phase: 0 等待 A，1 等待中線穿越＋層級2樞紐並偵測 B，2 已有 B，等待再次穿越中線進場。"""

    phase: int = 0
    a_i: int = -1
    a_price: float = 0.0
    crossed_mid: bool = False
    pivot_i: int = -1
    pivot_price: float = 0.0
    b_i: int = -1
    b_price: float = 0.0

    def reset(self) -> None:
        self.phase = 0
        self.a_i = self.pivot_i = self.b_i = -1
        self.a_price = self.pivot_price = self.b_price = 0.0
        self.crossed_mid = False


class RsiDivergence(Strategy):
    method_id = METHOD_ID

    def __init__(self, **kw) -> None:
        self.p = Params(**kw)
        self._short: dict[int, _Track] = {}
        self._long: dict[int, _Track] = {}

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["rsi"] = rsi_indicator(df["close"], self.p.rsi_period, self.p.rsi_method)
        self._pivots = find_pivots(df, self.p.pivot_level)
        return df

    def _pivot_after(self, kind: str, after_i: int, i: int) -> Pivot | None:
        for pv in self._pivots:
            if pv.kind == kind and pv.index > after_i and pv.confirm <= i:
                return pv
        return None

    def _step(self, df: pd.DataFrame, i: int, tr: _Track, side: Side) -> tuple[int, float, int, float] | None:
        p = self.p
        rsi_i = df.at[i, "rsi"]
        if rsi_i != rsi_i:  # NaN，指標未就緒
            return None
        if side == Side.SHORT:
            extreme, breach, pivot_kind = p.ob_extreme, p.os_breach, "trough"
            ext_price_i = df.at[i, "high"]
        else:
            extreme, breach, pivot_kind = p.os_extreme, p.ob_breach, "peak"
            ext_price_i = df.at[i, "low"]

        # D4：兩端點時間距離逾上限 → 放棄本輪（B 已形成者以 B 的位置計，等待進場的時間不計）
        if tr.phase == 1 and i - tr.a_i > p.max_gap_bars:
            tr.reset()

        if tr.phase == 0:
            hit_extreme = rsi_i >= extreme if side == Side.SHORT else rsi_i <= extreme
            if hit_extreme:
                better = ext_price_i > tr.a_price if side == Side.SHORT else (tr.a_i < 0 or ext_price_i < tr.a_price)
                if tr.a_i < 0 or better:
                    tr.a_i, tr.a_price = i, ext_price_i
            elif tr.a_i >= 0:
                tr.phase = 1
            return None

        if tr.phase == 1:
            # F3：B 尚未確定前，若又衝出更極端的峰（谷）且再度觸及嚴重超買（賣），視為新的 A
            made_new_extreme = ext_price_i > tr.a_price if side == Side.SHORT else ext_price_i < tr.a_price
            hit_extreme_again = rsi_i >= extreme if side == Side.SHORT else rsi_i <= extreme
            if made_new_extreme and hit_extreme_again:
                tr.a_i, tr.a_price = i, ext_price_i
                tr.crossed_mid, tr.pivot_i = False, -1
                return None
            # F2：兩端點之間 RSI 觸及對側門檻 → 放棄本輪
            breached = rsi_i < breach if side == Side.SHORT else rsi_i > breach
            if breached:
                tr.reset()
                return None
            crossed = rsi_i < p.mid if side == Side.SHORT else rsi_i > p.mid
            if crossed:
                tr.crossed_mid = True
            if tr.crossed_mid and tr.pivot_i < 0:
                piv = self._pivot_after(pivot_kind, tr.a_i, i)
                if piv is not None:
                    tr.pivot_i, tr.pivot_price = piv.index, piv.price
            if tr.crossed_mid and tr.pivot_i >= 0 and made_new_extreme and not hit_extreme_again:
                tr.b_i, tr.b_price = i, ext_price_i
                tr.phase = 2
            return None

        # phase == 2：B 已形成，等待再度穿越中線進場；期間若再創更極端價位，B 隨之更新，
        # 若 RSI 再度觸及嚴重超買（賣）則不再是背離 → 該點改為新的 A
        more_extreme = ext_price_i > tr.b_price if side == Side.SHORT else ext_price_i < tr.b_price
        hit_extreme_again = rsi_i >= extreme if side == Side.SHORT else rsi_i <= extreme
        if hit_extreme_again:
            tr.reset()
            tr.a_i, tr.a_price = i, ext_price_i
            return None
        if more_extreme:
            if i - tr.a_i > p.max_gap_bars:  # 新的 B 距 A 已逾時效
                tr.reset()
                return None
            tr.b_i, tr.b_price = i, ext_price_i
        fire = rsi_i < p.mid if side == Side.SHORT else rsi_i > p.mid
        if fire:
            out = (tr.a_i, tr.a_price, tr.b_i, tr.b_price)
            tr.reset()
            return out
        return None

    def on_bar(self, ctx: Context):
        p, df, i = self.p, ctx.df, ctx.i
        sess = df.at[i, "session"]
        tr_s = self._short.setdefault(sess, _Track())
        tr_l = self._long.setdefault(sess, _Track())

        hit_short = self._step(df, i, tr_s, Side.SHORT)
        hit_long = self._step(df, i, tr_l, Side.LONG)
        hit = hit_short or hit_long
        if hit is None:
            return None
        side = Side.SHORT if hit_short is not None else Side.LONG
        a_i, a_price, b_i, b_price = hit
        entry = float(df.at[i, "close"])
        stop = b_price
        if abs(entry - stop) > p.stop_points:
            stop = entry + p.stop_points if side == Side.SHORT else entry - p.stop_points
        name = "RSI背離向下" if side == Side.SHORT else "RSI背離向上"
        return [Order.enter(side, stop=stop, reason=name, a_i=a_i, a_price=a_price, b_i=b_i, b_price=b_price)]
