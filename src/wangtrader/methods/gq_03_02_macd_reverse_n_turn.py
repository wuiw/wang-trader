"""gq-03-02 死叉後高轉折賣出訊號（DIF 倒"N"形轉折）（《股技期招》第三章第二節，p.141–146）。

規格文件：methods/股技期招/gq-03-02-死叉後高轉折賣出訊號.md

私有實作標準 MACD（同 gq-03-01：DIF = EMA(fast) - EMA(slow)，慢線 = EMA(DIF, signal)，
書中未規定週期參數，採業界標準慣用值）。

訊號（空，p.141）：
  C1 DIF 由上往下穿越 MACD 慢線，形成死亡交叉。
  C2 死叉後行情沒有立即下跌，反而橫向整理甚至反漲：以 DIF 因價格上漲而上勾（今值 > 前值）表現。
  C3 DIF 上勾過程中並未穿越慢線（未形成金叉）。
  C4 DIF 其後重新下彎（今值 < 前值），形成倒"N"字形，此高轉折點即為賣出訊號（p.141）。
  F1 此高轉折須發生在死叉後不久；拖延超過 20 天以上，非有效訊號（p.144，明確數字）。
進場（p.141–143）：倒N確認當根收盤放空。原文特別提醒不宜在死叉當下直接進場（本模組本就只在
  倒N轉折確認時出單，天生符合此提醒）。
停損（p.141, 143–144）：離最近峰頂幅度不大時，設在峰頂（死叉後至訊號K期間的最高點）上方一檔；
  或採 7% 最大停損。書中提及「以死叉前波段最高點停損」效率較差（易被反彈提早觸價），因此本模組
  停損採「死叉後至訊號K期間最高點」而非「死叉前波段高點」，與 p.143-144 建議一致。
出場：原文未明確說明本訊號的停利／出場機制（p.141），不實作任何停利，exit_mode 固定為
  「持有至觸價停損或資料結束」（未提供 ladder 等選項，避免發明原文未規定的停利）。
過濾（§7）：
  F1　見上（days_since_cross_max，預設20，p.144，明確數字）。
  F2　判斷重點：死叉後價格未隨指標下跌，反而橫向或反漲——本模組以「訊號當根收盤 ≥ 死叉當根
      收盤」近似此條件（require_no_immediate_drop，預設開啟，屬對原文情境的具體化落實，非另外
      發明的規則）。

本方法為單向放空訊號，原文未描述多方鏡像用法，不實作多方。
週期：不限。所有門檻以根數／百分比表示。
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from wangtrader.core import Context, Order, Side, Strategy

METHOD_ID = "gq-03-02"


def _ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def _macd(close: pd.Series, fast: int, slow: int, signal: int) -> tuple[pd.Series, pd.Series]:
    dif = _ema(close, fast) - _ema(close, slow)
    macd_line = _ema(dif, signal)
    return dif, macd_line


@dataclass
class Params:
    fast: int = 12
    slow: int = 26
    signal: int = 9
    days_since_cross_max: int = 20  # F1：拖延超過20天非有效訊號（p.144，明確數字）
    require_no_immediate_drop: bool = True  # F2：訊號當根收盤須 >= 死叉當根收盤（p.141 情境具體化）
    stop_tick: float = 1.0  # 峰頂上方一檔（p.141）
    stop_mode: str = "tick"  # "tick" | "pct"
    fixed_stop_pct: float = 0.07  # 7%最大停損（p.141，明確數字）


class MacdDeathCrossHighTurn(Strategy):
    method_id = METHOD_ID
    intraday = False

    def __init__(self, **kw) -> None:
        self.p = Params(**kw)
        self._cross_i: int | None = None
        self._had_up: bool = False
        self._max_high: float | None = None

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["dif"], df["macd_line"] = _macd(df["close"], self.p.fast, self.p.slow, self.p.signal)
        return df

    def _stop(self, entry: float) -> float:
        p = self.p
        if p.stop_mode == "pct":
            return entry * (1 + p.fixed_stop_pct)
        return float(self._max_high) + p.stop_tick

    def on_bar(self, ctx: Context):
        p, df, i = self.p, ctx.df, ctx.i
        if i < 1:
            return None
        b, a = df.iloc[i], df.iloc[i - 1]
        dif, dif_p = b["dif"], a["dif"]
        m, m_p = b["macd_line"], a["macd_line"]
        if dif != dif or m != m:
            return None

        order = None
        if self._cross_i is None:
            if dif_p >= m_p and dif < m:  # 死亡交叉確認
                self._cross_i, self._had_up, self._max_high = i, False, float(b["high"])
        else:
            if dif >= m:  # 金叉：C3失敗，取消追蹤
                self._cross_i = None
            elif i - self._cross_i > p.days_since_cross_max:  # F1
                self._cross_i = None
            else:
                self._max_high = max(self._max_high, float(b["high"]))
                if dif > dif_p:
                    self._had_up = True  # C2
                elif dif < dif_p and self._had_up:  # C4：倒N轉折確認
                    ok = True
                    if p.require_no_immediate_drop and not (b["close"] >= df.at[self._cross_i, "close"]):
                        ok = False
                    if ok:
                        close = float(b["close"])
                        order = Order.enter(Side.SHORT, stop=self._stop(close), reason="死叉後高轉折賣出訊號")
                    self._cross_i = None

        if ctx.pos is not None and order is not None and order.side == ctx.pos.side:
            order = None
        return [order] if order is not None else None
