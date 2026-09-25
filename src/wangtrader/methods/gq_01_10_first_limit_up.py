"""gq-01-10 首度漲停買進法（《股技期招》第一章第四節，p.51-61）。

規格文件：methods/股技期招/gq-01-10-首度漲停買進.md

本方法為波段方法（intraday=False，可跨日持有）。**商品限定個股**：「漲停」「近一年最大量」皆為
台股專屬概念，台指期分K上「漲停」幾乎不會被觸發（limit_up_pct 依台指期跳動而言不具意義），
故本方法在台指期分K上大概率不會產生任何訊號，屬照實寫、照實回報，不強行改造成適用台指期的版本。

訊號（多方，p.51）：
  C1 回溯 lookback_days（預設50，p.51）根內沒有出現過「漲停收盤」K線。
  C2 本根K線收盤為漲停（漲幅 ≥ limit_up_pct - limit_up_tol，原文未給容忍誤差，推論預設值）。
進場（p.56）：C1、C2 與 F1-F3 過濾皆通過時，訊號K線收盤進場（原文「開盤2小時內鎖漲停即掛買、最慢
  臨收盤前決定買進」屬盤中細節，日K資料無法還原，簡化為訊號K線收盤進場）。
停損（p.54-58）：主要以進場價向下 primary_stop_pct%（預設7%）為停損。
  反手規則（簡化版，p.58）：若原文所述「量能/型態存疑」情境成立（本模組不完整實作F4/F5之型態判斷，
  見待確認事項），行情停滯且K線收盤跌破訊號K線最低點 → 停損並反手放空；本模組簡化為
  reversal_on_break_signal_low=True 時，只要收盤跌破訊號K最低點即觸發（不限定於存疑情境），
  屬簡化，非嚴格對應原文的觸發條件。
出場：原文未提供固定停利規則（見§6）。可選 exit_mode="channel"（引用 gq-01-12 模式四之N根K線區間
  移動停損停利精神，本模組私有實作，非原文對本法指定的搭配方式，預設關閉）。
過濾：
  F1 訊號當日成交量 ≤ 近 year_bars 根最大量 × max_volume_multiple（預設1.5，p.52）。
  F2/F3 訊號位階距最近一個 trough_pivot_level 層級波谷 ≤ max_from_trough_pct%（預設20，p.52,58）。
  F4「爆量且漲停價數度開開關關」、F5「量形如山谷交迭」：皆為原文對盤中/量能型態的模糊描述，日K
     OHLCV 資料無法量化重建開關次數或型態，本模組**未實作**，於此明確標註（見待確認事項）。

待確認事項：
  - F4、F5 無法從日K OHLCV 資料重建，未實作，回測時這兩類「出貨煙幕彈」案例不會被過濾掉。
  - 反手規則簡化為單純跌破訊號K最低點即觸發，未複刻原文「僅限存疑案例」的限定條件。
  - exit_mode="channel" 為可選出場機制，非原文對本法指定的搭配（原文未指定）。
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from wangtrader.core import Context, Order, Side, Strategy
from wangtrader.core.pivots import Pivot, confirmed_before, find_pivots

METHOD_ID = "gq-01-10"


@dataclass
class Params:
    lookback_days: int = 50  # C1（p.51）
    limit_up_pct: float = 7.0  # 漲停幅度（原文年代個股漲跌幅7%；依商品/年代調整；台指期分K基本不會觸發）
    limit_up_tol: float = 0.3  # 判斷「漲停」的容忍誤差%（原文未定量，推論，避免資料誤差誤判）
    year_bars: int = 240  # F1：近一年交易日數估算（原文未定量，以一年約240個交易日估算，推論）
    max_volume_multiple: float = 1.5  # F1（p.52）
    trough_pivot_level: int = 1  # F2/F3：波谷層級（原文未指定，推論）
    max_from_trough_pct: float = 20.0  # F2/F3（p.52,58）
    primary_stop_pct: float = 7.0  # 主要停損（p.54-58）
    reversal_on_break_signal_low: bool = False  # 簡化版反手規則（p.58，見檔頭說明）；原文僅限存疑案例，簡化版非原文規則，預設關閉
    exit_mode: str = "none"  # "none"｜"channel"（可選，引用 gq-01-12 模式四精神，非原文指定）
    exit_channel_n: int = 10  # channel 出場視窗根數（引用 gq-01-12 模式四範例值，非原文對本法指定）


class FirstLimitUp(Strategy):
    method_id = METHOD_ID
    intraday = False  # 波段方法，可跨日持有

    def __init__(self, **kw) -> None:
        self.p = Params(**kw)
        self._pivots: list[Pivot] = []

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        p = self.p
        prev_close = df["close"].shift(1)
        rise_pct = (df["close"] - prev_close) / prev_close * 100.0
        df["is_limit_up"] = rise_pct >= (p.limit_up_pct - p.limit_up_tol)
        df["had_limit_up_before"] = (
            df["is_limit_up"].shift(1).rolling(p.lookback_days, min_periods=1).max().fillna(0).astype(bool)
        )
        df["vol_roll_max_prior"] = df["volume"].rolling(p.year_bars, min_periods=1).max().shift(1)
        self._pivots = find_pivots(df, level=p.trough_pivot_level)
        return df

    def _nearest_trough_dist_pct(self, df: pd.DataFrame, i: int) -> float | None:
        troughs = confirmed_before(self._pivots, i - 1, "trough")
        if not troughs:
            return None
        tp = troughs[-1].price
        if tp <= 0:
            return None
        return (float(df.at[i, "close"]) - tp) / tp * 100.0

    def _detect(self, df: pd.DataFrame, i: int) -> bool:
        p = self.p
        b = df.iloc[i]
        if i < 1 or not bool(b["is_limit_up"]) or bool(b["had_limit_up_before"]):
            return False
        vmax = df.at[i, "vol_roll_max_prior"]
        if pd.notna(vmax) and float(b["volume"]) > vmax * p.max_volume_multiple:  # F1
            return False
        dist = self._nearest_trough_dist_pct(df, i)
        if dist is not None and dist > p.max_from_trough_pct:  # F2/F3
            return False
        return True

    def _channel_exit(self, ctx: Context) -> Order | None:
        if self.p.exit_mode != "channel":
            return None
        pos, df, i = ctx.pos, ctx.df, ctx.i
        if pos is None or i <= pos.entry_i:
            return None
        n = self.p.exit_channel_n
        window = df.iloc[max(0, i - n):i]
        if pos.side == Side.LONG:
            lvl = float(window["low"].min())
            if float(df.at[i, "close"]) < lvl:
                return Order.exit("通道出場")
        else:
            lvl = float(window["high"].max())
            if float(df.at[i, "close"]) > lvl:
                return Order.exit("通道出場")
        return None

    def on_bar(self, ctx: Context):
        p, df, i = self.p, ctx.df, ctx.i
        b = df.iloc[i]

        if ctx.pos is not None:
            if ctx.pos.side == Side.LONG and p.reversal_on_break_signal_low and ctx.i > ctx.pos.entry_i:
                sig_low = ctx.pos.meta.get("signal_low")
                if sig_low is not None and float(b["close"]) < sig_low:
                    return [Order.enter(Side.SHORT, stop=None, reason="跌破訊號K最低點反手")]
            ex = self._channel_exit(ctx)
            return [ex] if ex else None

        if not self._detect(df, i):
            return None
        entry = float(b["close"])
        stop = entry * (1 - p.primary_stop_pct / 100.0)
        return [Order.enter(Side.LONG, stop=stop, reason="首度漲停", signal_low=float(b["low"]))]
