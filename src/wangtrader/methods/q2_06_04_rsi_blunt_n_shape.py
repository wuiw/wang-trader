"""q2-06-04 RSI 鈍化 N 型／倒 N 型訊號（《期貨奇績2》第六章，p.234–249）。

規格文件：methods/期貨奇績2/q2-06-04-RSI鈍化N型倒N型訊號.md

核心概念（p.234）：RSI(5) 觸及嚴重超買 90 以上（超賣 10 以下）後，不等第二個背離端點，
改用層級 2 峰谷構成的正 N 型（買）／倒 N 型（空）123 步驟判斷進出場。
同一個觸發點之後有兩條路（p.235）：反轉（自峰位走倒 N 型→空訊）或鈍化續勢（拉回形成谷點後
向上走 N 型→買訊），「讓價格外形引導我們判斷」；以下以「超買側」（RSI ≥ 90）敘述，超賣側鏡像。

訊號（p.234–237, 241）：
  觸發：RSI(5) 觸及 90 以上，取該段（RSI 連續 ≥ 90 期間）最高點 A 為觀察起點（trig）。
  倒 N 型反轉（空）：A →(1) 自 A 拉回形成的層級 2 谷點 p1（谷點形成前若出現更低谷點，(1)隨之下移）
    →(2) 反彈（不得回到 A 的高度，p.235）→(3) 收盤「無遮蔽」跌破 (1)（低於 p1 及 p1 之後所有K線低點）
    → 放空訊號，停損參考 A。
  鈍化續勢 N 型（多）：0＝p1 →(1) p1 之後的層級 2 峰點 k（取最高者）→(2) 拉回不破 0，
    含同低即作廢（C4b，p.235「谷點2必須高於C」、p.238「(2)不可與(0)同低」）
    →(3) 收盤「無遮蔽」突破 (1)、且過 A 峰點（p.237「向上走 N 型過 A 峰點」），
    且突破幅度距 A 不超過 max_blunt_overshoot（預設20點，C5b/C6b，p.238「不宜追價」）→ 買進訊號，停損參考 0。
  兩者並存，先成立者為訊號（p.245）；反彈已達 A 的高度時，倒 N 型的可能性排除（p.235）。
  命名：無鈍化（直接反轉，3.1(a)/3.2(a)）reason 為「RSI倒N型／RSI正N型」；鈍化（續勢，3.1(b)/3.2(b)）
    reason 為「RSI鈍化正N型／RSI鈍化倒N型」，區分「無鈍化」（只需破自身峰谷點）與「鈍化」
    （須同時過原觸發K線高低點）兩種不同嚴格程度的路徑（★依 p.233、238 補拍頁修正，見文件12節）。
  觸發點接續（p.235 圖6-57 B）：(1) 峰點 k 形成期間 RSI 又觸及 90 以上，且其後出現層級 2 谷點時，
    k 成為新的觀察起點 A'（原 p1 成為續勢 N 型的 0，k 為其 (1)、新谷點為其 (2)），同時觀察自 A' 的倒 N 型。
  峰點位移（p.241）：拉回谷點形成前，A 可向上位移，以 pivot_shift_max（1）次為限、且須在
    pivot_shift_window_bars（5）根內；超出者本輪作廢（若當根 RSI 仍 ≥ 90 則以該根重新起算）。
    拉回谷點已形成後，A 不再位移（此時更高的峰即為續勢 N 型的 (1)）。
  超賣側（RSI ≤ 10）：全部鏡像（正 N 型反轉買訊；先出現反彈峰點後再破底者只能數向下倒 N 型，p.241）。

進場（p.234）：訊號當根收盤進場。
停損（p.234：「可以取最高點 A 為停損位置，或照均線買賣策略的停損設置，亦可比較兩者取較高者，
  但仍宜控制停損點數在 20 點以內」）：stop_mode = "trig"（結構起點：倒N型＝A、N型＝0）
  | "ma_signal"（第一章個位數公式：多 收盤−(10+個位數)、空 收盤+(20−個位數)）| "combined"（取兩者較遠者）；
  距離超過 stop_points（20）時改用 ma_signal（該公式必在 20 點內）。
出場：書中未見固定停利規則；反手規則見下。

訊號衝突／換手（p.242–243、245–246）：
  - 「RSI 再度觸及對側極端區並走出同類型 N 型訊號，立即平倉反手」：與引擎「持有反向部位時收到
    進場單即先平倉再進場」一致，不需額外程式碼。
  - 「N 型／倒 N 型訊號與 RSI 背離訊號同波段內只取先出現者」：跨方法規則，本模組無法實作。

過濾：
  F1 拉回未形成層級 2 轉折點前，不得認列 N 型／倒 N 型（p.237；以「須有已確認 p1」為前提天然滿足）。
  F2 訊號因濾網延遲過久（書中以 1 分鐘 K 線描述「逾 1 小時」，換算 max_delay_bars，預設 60）才完成 → 忽略（p.240）。
  F3 峰點位移限制（p.241），見上。
  F4 觀察期間 RSI 穿過對側極端區 → 本輪作廢（p.236「自超買區發動的放空訊號位置，其 RSI 數值不能已經穿過嚴重超賣區」）。
  F5（推論）開盤跳空規則（p.243–244）：預設關閉（gap_filter=False）；開啟後，
     跳空 < seamless_gap_points（10）時，與跳空方向相反的 N 型／倒 N 型訊號忽略；
     跳空 < min_valid_gap_points（30）且不屬無縫接軌，亦忽略（p.243）。
  F6（推論）no_entry_after：臨近收盤忽略（p.237 圖 6-59），書中為「臨近收盤」的時鐘描述，
     做成可選參數，預設 None（關閉）。
  F7/C4b 鈍化續勢結構拉回(2)與起始0點同低（同高）甚至更低（更高）→ 續勢作廢（p.238 圖6-60，含相等）。
  F8/C5b/C6b 鈍化訊號突破（跌破）原極端K線幅度超過 max_blunt_overshoot（預設20點）→ 不宜追價，忽略（p.238）。

  （讀書會的「鈍化簡化定義」為書外規則，已拆成獨立模組 sg_01_rsi_blunt_quick.py，不在本模組。）

週期：不限。所有門檻以點數／根數表示。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time

import pandas as pd

from wangtrader.core import Context, Order, Side, Strategy
from wangtrader.core.indicators import rsi as rsi_indicator
from wangtrader.core.pivots import Pivot, find_pivots

METHOD_ID = "q2-06-04"


@dataclass
class Params:
    rsi_period: int = 5
    rsi_method: str = "wilder"
    ob_extreme: float = 90.0  # 嚴重超買門檻（p.234）
    os_extreme: float = 10.0  # 嚴重超賣門檻（p.236）
    pivot_level: int = 2  # 層級 2 轉折點（p.235）
    max_delay_bars: int = 60  # 訊號延遲上限，書中「逾 1 小時」換算（p.240）
    pivot_shift_max: int = 1  # 觸發峰谷在拉回轉折點形成前允許位移次數（p.241）
    pivot_shift_window_bars: int = 5  # 位移須於此根數內完成（p.241）
    continuation: bool = True  # 鈍化續勢 N 型／倒 N 型訊號（p.235, 237, 241）
    stop_mode: str = "trig"  # "trig" | "ma_signal" | "combined"（p.234）
    stop_points: float = 20.0  # 停損上限（p.234「宜控制停損點數在 20 點以內」），超過改用 ma_signal
    stop_min_offset: float = 10.0  # 均線訊號停損法固定部分（q2-01 p.13）
    stop_integer_points: float = 20.0  # 均線訊號停損法整數價位固定點數（q2-01 p.13）
    max_blunt_overshoot: float = 20.0  # C5b/C6b：鈍化續勢訊號突破原極端K線幅度上限（p.238）
    gap_filter: bool = False  # F5，預設關閉（推論）
    seamless_gap_points: float = 10.0  # 無縫接軌門檻（p.244）
    min_valid_gap_points: float = 30.0  # 有效起點跳空門檻（p.243）
    no_entry_after: time | None = None  # F6，預設關閉（推論）


@dataclass
class _NTrack:
    """單一側（超買側 track=SHORT／超賣側 track=LONG）的觀察狀態。
    phase：0 等待觸發；1 已觸發等待拉回轉折點 p1；2 p1 已確立，同時觀察反轉與續勢結構。"""

    phase: int = 0
    trig_i: int = -1
    trig_price: float = 0.0
    shift_count: int = 0
    p1_i: int = -1  # 反轉結構的 (1)（超買側＝拉回谷點）
    p1_price: float = 0.0
    k_i: int = -1  # p1 之後的反向轉折（超買側＝反彈峰點），續勢 N 型的 (1)
    k_price: float = 0.0
    zero_i: int = -1  # 觸發點接續後，續勢結構的 0（原 p1）
    zero_price: float = 0.0
    hit_after_p1: bool = False  # p1 形成後 RSI 是否再觸及極端區（k 是否能成為新觸發點）
    rev_off: bool = False  # 反轉結構已排除（反彈達觸發峰位）
    cont_off: bool = False  # 續勢結構已作廢（(2) 越過 0）

    def reset(self) -> None:
        self.__init__()


def _digit_stop(side: Side, close_price: float, min_offset: float, integer_points: float) -> float:
    """均線訊號停損法（q2-01 p.13–14）：多＝收盤 −(10 + 個位數)；空＝收盤 +(20 − 個位數)；
    個位數 0 時固定 integer_points（p.14 例：7665→7680、8636→8650）。"""
    digit = int(round(close_price)) % 10
    if digit == 0:
        pts = integer_points
    elif side == Side.LONG:
        pts = min_offset + digit
    else:
        pts = 2 * min_offset - digit
    return close_price - pts if side == Side.LONG else close_price + pts


class RsiBluntNShape(Strategy):
    method_id = METHOD_ID

    def __init__(self, **kw) -> None:
        self.p = Params(**kw)
        self._short: dict[int, _NTrack] = {}
        self._long: dict[int, _NTrack] = {}

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["rsi"] = rsi_indicator(df["close"], self.p.rsi_period, self.p.rsi_method)
        self._pivots = find_pivots(df, self.p.pivot_level)
        return df

    def _pivots_after(self, kind: str, after_i: int, i: int) -> list[Pivot]:
        return [pv for pv in self._pivots if pv.kind == kind and pv.index > after_i and pv.confirm <= i]

    def _gap_blocked(self, df: pd.DataFrame, trig_i: int, side: Side) -> bool:
        """F5（推論，簡化）：以整個交易日的開盤跳空判斷是否忽略。原文另有「開盤15分鐘內觸及」
        的時鐘描述，因 RSI(n) 至少需 n 根才會有值、與本規則天然衝突，本模組簡化為只看跳空點數。"""
        p = self.p
        if not p.gap_filter:
            return False
        pc = df.at[trig_i, "prev_close"]
        if pd.isna(pc):
            return False
        gap = df.at[trig_i, "sess_open"] - pc
        if abs(gap) < p.seamless_gap_points:
            # 無縫接軌：僅與跳空方向一致的訊號可行，逆跳空方向的 N 型/倒 N 型訊號忽略（p.244）
            if (side == Side.SHORT and gap >= 0) or (side == Side.LONG and gap <= 0):
                return True
            return False
        return abs(gap) < p.min_valid_gap_points

    def _step(self, df: pd.DataFrame, i: int, tr: _NTrack, track: Side) -> tuple[Side, str, float, int] | None:
        """推進單一側狀態機；成立時回傳 (訊號方向, 種類 "rev"/"cont", 停損參考價, 觸發K線)。
        track=SHORT：超買側（RSI ≥ 90，反轉＝倒N型空訊、續勢＝N型買訊）；track=LONG：鏡像。"""
        p = self.p
        rsi_i = df.at[i, "rsi"]
        if rsi_i != rsi_i:
            return None
        sh = track == Side.SHORT
        hi, lo, close = df.at[i, "high"], df.at[i, "low"], df.at[i, "close"]
        ext_i = hi if sh else lo  # 觸發方向的極端價
        hit = rsi_i >= p.ob_extreme if sh else rsi_i <= p.os_extreme
        opp_hit = rsi_i <= p.os_extreme if sh else rsi_i >= p.ob_extreme
        beyond = (lambda a, b: a > b) if sh else (lambda a, b: a < b)  # a 比 b 更朝觸發方向
        beyond_eq = (lambda a, b: a >= b) if sh else (lambda a, b: a <= b)  # 含同值（C4b「同低甚至更低」）
        p1_kind, k_kind = ("trough", "peak") if sh else ("peak", "trough")
        rev_side, cont_side = (Side.SHORT, Side.LONG) if sh else (Side.LONG, Side.SHORT)
        col_far, col_near = ("low", "high") if sh else ("high", "low")  # far=反轉突破方向的影線, near=觸發方向的影線

        if tr.phase == 0:
            if hit:
                if tr.trig_i < 0 or beyond(ext_i, tr.trig_price):
                    tr.trig_i, tr.trig_price = i, ext_i
            elif tr.trig_i >= 0:
                tr.phase = 1
                tr.shift_count = 0
            return None

        if opp_hit:  # F4：RSI 穿過對側極端區，本輪作廢（p.236）
            tr.reset()
            return None
        if i - tr.trig_i > p.max_delay_bars:  # F2：延遲過久
            tr.reset()
            return None

        if tr.phase == 1:
            if beyond(ext_i, tr.trig_price):  # 峰點位移（p.241）：拉回轉折點形成前，限一次且須在 5 根內
                if tr.shift_count >= p.pivot_shift_max or i - tr.trig_i > p.pivot_shift_window_bars:
                    tr.reset()
                    if hit:
                        tr.trig_i, tr.trig_price = i, ext_i  # 當根仍在極端區：以本根重新起算
                    return None
                tr.trig_i, tr.trig_price = i, ext_i
                tr.shift_count += 1
                return None
            pivs = self._pivots_after(p1_kind, tr.trig_i, i)
            if pivs:
                pv = pivs[0]
                tr.phase, tr.p1_i, tr.p1_price = 2, pv.index, pv.price
                tr.k_i, tr.zero_i = -1, -1
                tr.hit_after_p1 = tr.rev_off = tr.cont_off = False
            return None

        # ---- phase 2：p1 已確立 ----
        if hit:
            tr.hit_after_p1 = True
        if tr.k_i < 0:  # 反彈轉折尚未出現：(1) 可再往觸發的反方向移動（更低的谷點）
            for pv in self._pivots_after(p1_kind, tr.p1_i, i):
                if beyond(tr.p1_price, pv.price):
                    tr.p1_i, tr.p1_price = pv.index, pv.price
        # 反彈已達觸發峰位 → 倒 N 型可能性排除（p.235）
        if not beyond(tr.trig_price, ext_i):
            tr.rev_off = True

        # (a) 反轉訊號：收盤無遮蔽跌破（突破）(1)
        if not tr.rev_off:
            ref = tr.p1_price
            if i - 1 > tr.p1_i:
                seg = df[col_far].iloc[tr.p1_i + 1:i]
                ref = min(ref, seg.min()) if sh else max(ref, seg.max())
            if beyond(ref, close):
                out = (rev_side, "rev", tr.trig_price, tr.trig_i)
                tr.reset()
                return out

        # (b) 反彈轉折 k（續勢 N 型的 (1)，取最高／最低者）
        for pv in self._pivots_after(k_kind, tr.p1_i, i):
            if tr.k_i < 0 or beyond(pv.price, tr.k_price):
                tr.k_i, tr.k_price = pv.index, pv.price

        # (c) 觸發點接續（p.235 圖6-57 B）：k 形成期間 RSI 再觸及極端區，且 k 之後出現新的拉回轉折
        if tr.k_i >= 0 and tr.hit_after_p1:
            nxt = self._pivots_after(p1_kind, tr.k_i, i)
            if nxt:
                pv = nxt[0]
                tr.zero_i, tr.zero_price = tr.p1_i, tr.p1_price
                tr.trig_i, tr.trig_price = tr.k_i, tr.k_price
                tr.p1_i, tr.p1_price = pv.index, pv.price
                tr.k_i, tr.hit_after_p1 = -1, False
                tr.rev_off = tr.cont_off = False
                tr.shift_count = 0
                if beyond(tr.zero_price, tr.p1_price):  # 新拉回越過續勢 N 型的 0 → 續勢作廢
                    tr.cont_off = True

        # (d) 續勢訊號（p.235, 237, 241）：0 →(1) →(2) 不越過 0 →(3) 收盤無遮蔽突破 (1) 且過觸發峰位
        if p.continuation and not tr.cont_off:
            if tr.zero_i >= 0:
                n0_price, n1_i, n1_price = tr.zero_price, tr.trig_i, tr.trig_price
            elif tr.k_i >= 0:
                n0_price, n1_i, n1_price = tr.p1_price, tr.k_i, tr.k_price
            else:
                n0_price, n1_i, n1_price = None, -1, 0.0
            if n1_i >= 0:
                pull = df[col_far].iloc[n1_i + 1:i + 1]
                # C4b（p.238圖6-60）：拉回(2)不可與起始0點同低（同高）甚至更低（更高），含相等
                if len(pull) and beyond_eq(n0_price, pull.min() if sh else pull.max()):
                    tr.cont_off = True  # (2) 越過或觸及 0（p.235「谷點2必須高於C」；p.238「(2)不可與(0)同低」）
                else:
                    ref = max(n1_price, tr.trig_price) if sh else min(n1_price, tr.trig_price)
                    if i - 1 > n1_i:
                        seg = df[col_near].iloc[n1_i + 1:i]
                        ref = max(ref, seg.max()) if sh else min(ref, seg.min())
                    # C5b/C6b（p.238）：突破（跌破）原極端K線幅度不宜超過約20點，過遠不宜追價
                    overshoot = abs(close - tr.trig_price)
                    if beyond(close, ref) and overshoot <= p.max_blunt_overshoot:
                        out = (cont_side, "cont", float(n0_price), tr.trig_i)
                        tr.reset()
                        return out
        if tr.rev_off and tr.cont_off:
            tr.reset()
        return None

    def _stop(self, side: Side, close: float, ref: float) -> float:
        p = self.p
        ma = _digit_stop(side, close, p.stop_min_offset, p.stop_integer_points)
        if p.stop_mode == "trig":
            stop = ref
        elif p.stop_mode == "ma_signal":
            stop = ma
        else:  # combined：取兩者較遠者（p.234「比較兩者取較高者」，空單；多單鏡像）
            stop = max(ref, ma) if side == Side.SHORT else min(ref, ma)
        if abs(close - stop) > p.stop_points:  # 「宜控制停損點數在 20 點以內」→ 改用均線訊號停損法
            stop = ma
        return float(stop)

    def on_bar(self, ctx: Context):
        p, df, i = self.p, ctx.df, ctx.i
        sess = df.at[i, "session"]
        tr_s = self._short.setdefault(sess, _NTrack())
        tr_l = self._long.setdefault(sess, _NTrack())

        hit_short = self._step(df, i, tr_s, Side.SHORT)
        hit_long = self._step(df, i, tr_l, Side.LONG)
        hit = hit_short if hit_short is not None else hit_long
        if hit is None:
            return None
        side, kind, ref, trig_i = hit

        # F6：臨近收盤忽略
        b = df.iloc[i]
        if p.no_entry_after is not None and hasattr(b["time"], "time") and b["time"].time() > p.no_entry_after:
            return None
        # F5：開盤跳空規則
        if self._gap_blocked(df, trig_i, side):
            return None

        entry = float(df.at[i, "close"])
        stop = self._stop(side, entry, float(ref))
        if kind == "rev":  # 無鈍化（直接反轉）：只需突破/跌破N型/倒N型自身峰谷點（3.1(a)/3.2(a)，p.233-234）
            name = "RSI倒N型" if side == Side.SHORT else "RSI正N型"
        else:  # 鈍化（續勢）：須同時突破/跌破自身峰谷點與原觸發極端K線（3.1(b)/3.2(b)，p.233,238）
            name = "RSI鈍化正N型" if side == Side.LONG else "RSI鈍化倒N型"
        return [Order.enter(side, stop=stop, reason=name, trig_i=trig_i, ref_price=float(ref))]
