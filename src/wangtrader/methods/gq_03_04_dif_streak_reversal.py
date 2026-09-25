"""gq-03-04 DIF連續下跌慣性改變買點（《股技期招》第三章第四節，p.155–163）。

規格文件：methods/股技期招/gq-03-04-DIF慣性改變.md

私有實作標準 MACD（同 gq-03-01/02/03）。

訊號（多，p.155）：
  C1 DIF值連續下跌（今值皆小於前值）達 min_decline_days（原文23個交易日以上，明確數字）以上，
     與價格當天漲跌無關。
  C2 DIF出現止跌上勾轉折（今值 > 前值）。
  C3 轉折當根K線須為紅K線，且漲幅（相對前一天收盤）超過 pct_gain_min（原文4%，明確數字）。
進場（p.155–156）：轉折當根本身即進場K線，收盤確認即進場。
停損（p.156–159）：固定 stop_pct（原文7%，明確數字，多篇範例一致）。停損後是否反手：原文未規定。
出場（p.156–160）：原文列舉三種依據，並列無優先序：
  1.「階梯出場線」（未給利潤啟動門檻，exit_mode="ladder"，profit_target 預設0＝推論值，opt-in）。
  2.「觀察K線是否出現反轉K線組合」——原文未定義具體K線組合，無法程式化，不實作。
  3. 特定範例明確提出的觸發規則：「收盤價跌破前一天最低點，即出場」（p.160，明確規則）——
     exit_mode="prev_day_low"（預設），使用 core.bars 的 prev_low（即前一交易日最低點）。
持有期間依訊號出現的價格位階（季線年線金叉初期/高檔區/頂點反轉4成內/跌勢末期）決定長短線策略，
  屬敘述性建議、非可程式化的「不做」規則，不實作（p.155）。
過濾（§7）：
  F1　見C1（min_decline_days，明確數字23）。
  F2　「自頂點大幅回檔超過3成才出現訊號，宜短打」為操作建議，非「不做」規則，不實作為過濾。
  F3　基本面判斷，無法程式化，不實作。

本方法為單向買進訊號，原文未描述空方鏡像（DIF連續上漲慣性改變賣點）用法，不實作空方。
週期：不限。所有門檻以根數／百分比表示。
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from wangtrader.core import Context, Order, Side, Strategy
from wangtrader.core.exits import ladder_exit

METHOD_ID = "gq-03-04"


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
    min_decline_days: int = 23  # C1，明確數字（p.155, 161）
    pct_gain_min: float = 4.0  # C3，明確百分比（p.155）
    stop_pct: float = 7.0  # 明確百分比（p.156-159）
    exit_mode: str = "prev_day_low"  # "prev_day_low" | "ladder" | "none"
    profit_target: float = 0.0  # ladder 啟動門檻，原文未規定數值，預設0（推論）


class DifStreakReversal(Strategy):
    method_id = METHOD_ID
    intraday = False

    def __init__(self, **kw) -> None:
        self.p = Params(**kw)
        self._decline_run = 0

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["dif"], df["macd_line"] = _macd(df["close"], self.p.fast, self.p.slow, self.p.signal)
        return df

    def _exit(self, ctx: Context) -> Order | None:
        p, pos, b = self.p, ctx.pos, ctx.bar()
        if pos is None or ctx.i <= pos.entry_i:
            return None
        if p.exit_mode == "ladder":
            return ladder_exit(ctx, p.profit_target)
        if p.exit_mode == "prev_day_low" and not pd.isna(b["prev_low"]) and b["close"] < b["prev_low"]:
            return Order.exit("跌破前一天低點")
        return None

    def on_bar(self, ctx: Context):
        p, df, i = self.p, ctx.df, ctx.i
        order = None
        if i >= 1:
            b = df.iloc[i]
            dif, dif_p = b["dif"], df.at[i - 1, "dif"]
            if not (dif != dif or dif_p != dif_p):
                if dif > dif_p:  # C2：止跌上勾
                    if self._decline_run >= p.min_decline_days:  # C1
                        prev_close = b["prev_close"]
                        is_red = b["close"] > b["open"]
                        gain_ok = (not pd.isna(prev_close) and prev_close > 0
                                   and (b["close"] - prev_close) / prev_close * 100 > p.pct_gain_min)
                        if is_red and gain_ok:  # C3
                            entry = float(b["close"])
                            order = Order.enter(Side.LONG, stop=entry * (1 - p.stop_pct / 100),
                                                 reason="DIF連續下跌慣性改變買點")
                    self._decline_run = 0
                elif dif < dif_p:
                    self._decline_run += 1
                else:
                    self._decline_run = 0

        orders: list[Order] = []
        if ctx.pos is not None:
            ex = self._exit(ctx)
            if ex is not None:
                orders.append(ex)
        if order is not None and (ctx.pos is None or ctx.pos.side != order.side):
            orders.append(order)
        return orders or None
