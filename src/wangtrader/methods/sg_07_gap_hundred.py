"""sg-07 跳空百點買訊／空訊（讀書會整理，書外方法；原始定義在作者《交易訊號》上冊，不在本專案書籍內）。

規格文件：methods/讀書會/sg-07-跳空百點.md
逐篇整理：extracted/study-group/newmethods/跳空百點.md

「開盤首根」以 `prepare()` 的 `bar_no == 0` 判斷，不假設任何週期；時間窗以 K 線 time 欄計算分鐘。

訊號：
  跳空：今日開盤（sess_open）− 平盤（prev_close，昨日日盤收盤）的絕對值 ≥ gap_threshold（100）。
    助教：「就開盤跳空100點即可」（2021-05-15，post 941980469948048）；「昨天收盤17090，今天開盤17190，
    剛好100點」（2021-06-08，post 956672441812184）；「沒有百點跳空 昨天收盤319, 今天開盤225」
    （2021-04-21，post 927795674699861）；「平盤是昨天日盤收盤」「請看"日線"的收盤」（2021-05-24，post 947695349376560）。
  空訊：首根之後某根收盤跌破「首根至前一根」所有K線最低點（無遮蔽）→ 當根收盤放空。
  買訊：鏡像，收盤突破「首根至前一根」所有K線最高點。
    助教：「要跌破無遮蔽才成立」（2021-04-06，post 918608962285199）；首根本身收黑不算
    （2021-03-10 post 902532930559469 助教修正；2021-12-16 post 1078403152972445 圖分列「A.首K收黑空訊」
    「B.百點跳空空訊」）。
  方向（爭議，參數 direction）：
    "fade"（預設）：開高只做空、開低只做多（反向回補缺口）——多數助教實例
      （2021-05-14、2021-10-01、2021-12-16、2022-11-03、2023-11-01 等）。
    "follow"：開高只做多、開低只做空（順向）——作者 2020-09-16 舊文「跳空百點過高買訊」
      （助教 2021-03-12 post 903615807117848 _03 轉貼截圖）與部分實例。
    "both"：不限方向，哪邊先成立做哪邊（學員整理的結論，推論）。
  first_only（推論，預設 True）：每個交易日只取第一次成立的訊號。
  window_minutes（推論，預設 None＝不限）：訊號須在首根之後幾分鐘內成立。
停損（推論，原文未規定）：首根另一端（空＝首根最高、多＝首根最低；助教 2023-11-01 圖「訊號K收盤到高點，
  大概40點」）；距離超過 stop_points（20）改用 q2-01 均線訊號停損法（多＝收盤 −(10＋個位數)、
  空＝收盤 ＋(20−個位數)，個位數 0 時 20 點）。
出場：原文未規定；不設停利，持有至停損、反向訊號（引擎先平倉再反手）或收盤。
未實作：20 點內補進場、1 分提早切入、選擇權進場、「突兀感」判斷（皆為主觀或依賴其他訊號）。

週期：不限。所有門檻以點數／分鐘表示。
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from wangtrader.core import Context, Order, Side, Strategy

METHOD_ID = "sg-07"

DIRECTIONS = ("fade", "follow", "both")


@dataclass
class Params:
    gap_threshold: float = 100.0  # 開盤 − 昨日日盤收盤 ≥100 點（剛好 100 算成立；助教 2021-05-15、06-08、04-21）
    direction: str = "fade"  # "fade" 反向（多數實例）／"follow" 順向（作者 2020-09-16 舊文）／"both" 不限（推論）
    unmasked: bool = True  # 收盤須越過首根至前一根的極值（無遮蔽，助教 2021-04-06）；False 只比首根高低點
    first_only: bool = True  # 每日只取第一次成立（推論）；False＝每次新的突破／跌破都成立（持同向部位時引擎忽略）
    window_minutes: float | None = None  # 首根之後幾分鐘內有效（推論；原文未規定，None＝整個交易日）
    stop_points: float = 20.0  # 停損上限（推論，SG_SPEC 預設）
    stop_min_offset: float = 10.0  # 均線訊號停損法固定部分（q2-01 p.13）
    stop_integer_points: float = 20.0  # 均線訊號停損法整數價位固定點數（q2-01 p.13）

    def __post_init__(self) -> None:
        if self.direction not in DIRECTIONS:
            raise ValueError(f"direction 必須是 {DIRECTIONS} 之一")


def _digit_stop(side: Side, close_price: float, min_offset: float, integer_points: float) -> float:
    """均線訊號停損法（q2-01 p.13–14）：多＝收盤 −(10 + 個位數)；空＝收盤 +(20 − 個位數)；個位數 0 時固定點數。"""
    digit = int(round(close_price)) % 10
    if digit == 0:
        pts = integer_points
    elif side == Side.LONG:
        pts = min_offset + digit
    else:
        pts = 2 * min_offset - digit
    return close_price - pts if side == Side.LONG else close_price + pts


def _elapsed_minutes(df: pd.DataFrame, a: int, b: int) -> float:
    try:
        return (df.at[b, "time"] - df.at[a, "time"]).total_seconds() / 60.0
    except (AttributeError, TypeError, KeyError):
        return float(b - a)


class GapHundred(Strategy):
    method_id = METHOD_ID

    def __init__(self, **kw) -> None:
        self.p = Params(**kw)
        self._first_i: int | None = None  # 當日首根 index（跳空成立時才記錄）
        self._gap_up: bool = False
        self._done: set[Side] = set()  # 當日已成立過的方向（first_only 用）

    def allowed(self, gap_up: bool) -> set[Side]:
        d = self.p.direction
        if d == "both":
            return {Side.LONG, Side.SHORT}
        fade = Side.SHORT if gap_up else Side.LONG
        if d == "fade":
            return {fade}
        return {Side.LONG if fade == Side.SHORT else Side.SHORT}

    def detect(self, df: pd.DataFrame, i: int) -> tuple[Side, float] | None:
        """第 i 根收盤時判斷；回傳 (方向, 首根另一端價位)。會更新當日狀態。"""
        p = self.p
        if df.at[i, "bar_no"] == 0:
            self._first_i, self._done = None, set()
            pc = df.at[i, "prev_close"]
            if pd.isna(pc):
                return None
            gap = df.at[i, "open"] - pc
            if abs(gap) >= p.gap_threshold:
                self._first_i, self._gap_up = i, gap > 0
            return None
        f = self._first_i
        if f is None or df.at[i, "session"] != df.at[f, "session"]:
            return None
        if p.window_minutes is not None and _elapsed_minutes(df, f, i) > p.window_minutes:
            return None
        if p.first_only and self._done:
            return None
        close = df.at[i, "close"]
        pcl = df.at[i - 1, "close"]
        if p.unmasked:  # 無遮蔽：比首根至前一根的極值（上一根收盤必在其內，成立即為新的突破）
            hi, lo = df["high"].iloc[f:i].max(), df["low"].iloc[f:i].min()
        else:  # 只比首根高低點：須是本根才越過（上一根收盤未越過）
            hi, lo = df.at[f, "high"], df.at[f, "low"]
        ok = self.allowed(self._gap_up)
        if Side.LONG in ok and close > hi and pcl <= hi:
            self._done.add(Side.LONG)
            return Side.LONG, float(df.at[f, "low"])
        if Side.SHORT in ok and close < lo and pcl >= lo:
            self._done.add(Side.SHORT)
            return Side.SHORT, float(df.at[f, "high"])
        return None

    def on_bar(self, ctx: Context):
        p, df, i = self.p, ctx.df, ctx.i
        hit = self.detect(df, i)
        if hit is None:
            return None
        side, ref = hit
        entry = float(df.at[i, "close"])
        stop = ref
        if abs(entry - stop) > p.stop_points:
            stop = _digit_stop(side, entry, p.stop_min_offset, p.stop_integer_points)
        name = "跳空百點買訊" if side == Side.LONG else "跳空百點空訊"
        return [Order.enter(side, stop=float(stop), reason=name, gap_up=self._gap_up)]
