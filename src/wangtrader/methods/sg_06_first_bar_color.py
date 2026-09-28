"""sg-06 首K收紅買訊／首K收黑空訊（讀書會整理，書外方法；與書中 q3-07 開盤戰法不同）。

規格文件：methods/讀書會/sg-06-首K收紅收黑.md
整理來源：extracted/study-group/newmethods/首K收紅收黑.md（原始定義為作者在期跡2讀書會的舊文，不在資料中；
以下皆為助教轉述與實例）。

訊號（「開盤首根」以 prepare() 的 bar_no == 0 判斷，不綁週期）：
  首K收紅買訊：開盤跳空往下（今開 < 平盤），開盤首根K線收紅（收盤 > 開盤）。
    助教 2021-05-13（post 1419367005077876）「跳空往下首K收紅」；2021-07-28（1473136503034259 留言）
    「第一根是收紅，不是漲」；2021-12-27（1084547515691342 留言）「一般是開跌收紅才是用首K收紅的方式切入」
    → 跳空開高的首根紅K不算。
  首K收黑空訊：鏡像，開盤跳空往上，首根收黑（助教 2021-06-23 post 965724097573685 等實例）。
  不限影線：助教 2021-06-24（965724097573685 留言）「這個不是書本上的開盤戰法」；實例首K影線可長達數十點。
  跳空門檻：原文未給（實例約 50～600 點）→ 參數 gap_points，預設 0（任何跳空皆可）。
進場（說法未定，參數 entry_mode）：
  "close"（預設）：首K收盤確認後以收盤價進場（多數實例的進場價≈首K收盤；原文未明寫，推論）。
  "breakout"：首K之後，某根收盤跌破首K低點（多方：收盤越過首K高點）才進場；助教 2021-06-30
    （post 970315020447926，5 分圖字）「開盤首K收黑, 但收盤未創低, 下殺再收腳記得撤單」。
    cancel_on_recover=True：第一根盤中跌破首K低點但收盤收回（下殺收腳）即撤單（同一句原文）。
    breakout_window_minutes：等待時間窗（原文未給，預設 None＝到收盤）。
停損：多＝首K低點 −1 點、空＝首K高點 ＋1 點（助教 2021-07-28 1473136503034259 留言「停損建議設定低點下面1點」；
  空方為鏡像，推論）。原文已規定停損，故預設不設距離上限；max_stop_points 可選（推論，預設 None），
  距離超過時改用 q2-01 均線訊號停損法（多＝收盤 −(10＋個位數)、空＝收盤 ＋(20−個位數)，個位數 0 時 20 點）。
出場：原文沒有固定規則（助教個人做法：階梯線、連五黑遇首紅、滿足即休息）；不設停利，
  持有至停損或收盤。

週期：不限。所有門檻以點數／分鐘表示。
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from wangtrader.core import Context, Order, Side, Strategy

METHOD_ID = "sg-06"


@dataclass
class Params:
    gap_points: float = 0.0  # 跳空門檻：|今開 − 平盤| ≥ 此值（且 > 0）；原文未給（未定）
    entry_mode: str = "close"  # "close"：首K收盤進場（推論）；"breakout"：後續收盤突破首K低（高）點（2021-06-30）
    cancel_on_recover: bool = True  # breakout：首次盤中破首K低點卻收回（下殺收腳）即撤單（2021-06-30）
    breakout_window_minutes: float | None = None  # breakout 等待時間窗（原文未給；None＝到收盤）
    stop_offset: float = 1.0  # 停損＝首K低點下 1 點（2021-07-28 助教；空方鏡像推論）
    max_stop_points: float | None = None  # 停損距離上限（推論，預設關閉）；超過改用均線訊號停損法
    stop_min_offset: float = 10.0  # 均線訊號停損法固定部分（q2-01 p.13）
    stop_integer_points: float = 20.0  # 均線訊號停損法整數價位固定點數（q2-01 p.13）


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


class FirstBarColor(Strategy):
    method_id = METHOD_ID

    def __init__(self, **kw) -> None:
        self.p = Params(**kw)
        if self.p.entry_mode not in ("close", "breakout"):
            raise ValueError(f"entry_mode 必須是 'close' 或 'breakout'：{self.p.entry_mode!r}")
        self._pending: tuple | None = None  # breakout 模式：(session, side, 首根 index)

    def detect(self, df: pd.DataFrame, i: int) -> Side | None:
        """開盤首根（bar_no==0）是否成立：跳空開低收紅 → LONG；跳空開高收黑 → SHORT。"""
        if df.at[i, "bar_no"] != 0:
            return None
        pc = df.at[i, "prev_close"]
        if pd.isna(pc):
            return None
        o, c = df.at[i, "open"], df.at[i, "close"]
        gap = o - pc
        need = max(self.p.gap_points, 0.0)
        if gap < 0 and -gap >= need and c > o:
            return Side.LONG
        if gap > 0 and gap >= need and c < o:
            return Side.SHORT
        return None

    def _order(self, df: pd.DataFrame, i: int, side: Side, first: int) -> Order:
        p = self.p
        entry = float(df.at[i, "close"])
        if side == Side.LONG:
            stop = float(df.at[first, "low"]) - p.stop_offset
        else:
            stop = float(df.at[first, "high"]) + p.stop_offset
        if p.max_stop_points is not None and abs(entry - stop) > p.max_stop_points:
            stop = _digit_stop(side, entry, p.stop_min_offset, p.stop_integer_points)
        name = "首K收紅買訊" if side == Side.LONG else "首K收黑空訊"
        return Order.enter(side, stop=float(stop), reason=name,
                           first_high=float(df.at[first, "high"]), first_low=float(df.at[first, "low"]))

    def on_bar(self, ctx: Context):
        p, df, i = self.p, ctx.df, ctx.i
        sess = df.at[i, "session"]
        side = self.detect(df, i)
        if side is not None:
            if p.entry_mode == "close":
                self._pending = None
                return [self._order(df, i, side, i)]
            self._pending = (sess, side, i)
            return None
        if self._pending is None:
            return None
        psess, pside, first = self._pending
        if psess != sess:
            self._pending = None
            return None
        if p.breakout_window_minutes is not None and _elapsed_minutes(df, first, i) > p.breakout_window_minutes:
            self._pending = None
            return None
        close = df.at[i, "close"]
        if pside == Side.LONG:
            level = df.at[first, "high"]
            if close > level:
                self._pending = None
                return [self._order(df, i, pside, first)]
            if p.cancel_on_recover and df.at[i, "high"] > level:
                self._pending = None  # 盤中越過首K高點但收盤收回 → 撤單
        else:
            level = df.at[first, "low"]
            if close < level:
                self._pending = None
                return [self._order(df, i, pside, first)]
            if p.cancel_on_recover and df.at[i, "low"] < level:
                self._pending = None  # 下殺再收腳 → 撤單
        return None
