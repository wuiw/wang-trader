"""gq-03-03 MACD雙金叉反轉買點（《股技期招》第三章第三節，p.147–154）。

規格文件：methods/股技期招/gq-03-03-雙金叉反轉買點.md

私有實作標準 MACD（同 gq-03-01/02）。

訊號（多，p.147）：
  C1 跌勢中DIF與MACD第一次金叉（首次金叉），不直接進場，僅觀望。
  C2 首次金叉後MACD重新死叉向下，DIF「雙腳立足」再度上勾。
  C3 DIF再度與MACD金叉（第二次金叉），此為進場訊號。
  C4 雙金叉須在短期間內出現：正文「拉長超過一個月以上，則非本文介紹的訊號」（p.147）；
     圖3-18圖說另指出「宜在15天內完成」（p.152），兩處門檻不一致。依規範取「正文」數字為預設，
     以30個交易日近似「一個月」（原文未給精確交易日數，此為推論換算），可用
     max_bars_between_crosses 改為15（圖說版本）或其他數值。
  C5 訊號成立當日K線須為陽線；陰線不成立（例外：均線多排時可放寬，原文未定義「均線多排」的
     具體均線組合與判定公式，本模組不實作此例外，見待確認事項）。

實作方式：每一次偵測到的黃金交叉（dif 由 <=慢線 轉為 >慢線），若非本輪追蹤中的第一次金叉，
即視為與「上一次金叉」構成的雙金叉候選（因交叉定義本身保證兩次金叉之間必有一次死叉，即
C2 天生成立）；不論本次候選是否通過 C4/C5，都以本次金叉做為下一次比較的基準（p.148–149
範例：首次金叉觀望→第二次金叉陰線不成立→以第二次金叉為基準的第三次金叉符合條件才進場，
與此設計一致）。

進場（p.147, 150）：第二次金叉當日收盤進場。
停損（p.148）：買進後**K線收盤**跌破進場買進K線之最低點，即停損出場（收盤停損，非盤中觸價，
  故本模組 `stop_on_close = True`）。停損後是否反手：原文未規定，不實作。
出場（p.148）：「跌破一低（前一個低點）出場」或「階梯出場線（作者建議）」，兩者並列。exit_mode
  預設 "prev_low_break"：跌破進場後新形成的第一個確認轉折低點（層級 pivot_level，原文本節未指定
  轉折層級，採書中其他章節「層級2」慣例，推論值）即出場；可選 "ladder"（原文未給利潤門檻，
  profit_target 預設0＝推論值）或 "none"。
過濾（§7）：
  F1　見上（首次金叉僅觀望）。
  F2　見C5（訊號當日須陽線）。
  F3　見C4（雙金叉間隔）。
  F4　0軸過遠：原文「DIF值超過K線價位10倍以上」定義模糊、未附計算範例（p.147，待確認事項），
      無法可靠量化，不實作。
  F5/F6　空頭反轉初期／大M頭剛破頸線：需型態學判斷（M頭辨識），原文未給可程式化的具體規則，
      不實作。

本方法為單向買進訊號，原文未描述空方鏡像（雙死叉）用法，不實作空方。
週期：不限。所有門檻以根數表示。
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from wangtrader.core import Context, Order, Side, Strategy
from wangtrader.core.exits import ladder_exit
from wangtrader.core.pivots import Pivot, find_pivots, last_confirmed

METHOD_ID = "gq-03-03"


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
    max_bars_between_crosses: int = 30  # C4：正文「一個月」的交易日推算值（矛盾另見圖說15天，推論）
    require_red: bool = True  # C5：訊號當日須陽線（必要條件，均線多排例外不實作）
    pivot_level: int = 2  # 「跌破一低」轉折層級，本節未指定，採書中慣例（推論）
    exit_mode: str = "prev_low_break"  # "prev_low_break" | "ladder" | "none"
    profit_target: float = 0.0  # ladder 啟動門檻，原文未規定數值，預設0（推論）


class MacdDoubleGoldenCross(Strategy):
    method_id = METHOD_ID
    intraday = False
    stop_on_close = True  # p.148：K線收盤跌破進場K最低點即停損（收盤停損，非盤中觸價）

    def __init__(self, **kw) -> None:
        self.p = Params(**kw)
        self._prev_cross_i: int | None = None
        self._pivots: list[Pivot] = []

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["dif"], df["macd_line"] = _macd(df["close"], self.p.fast, self.p.slow, self.p.signal)
        self._pivots = find_pivots(df, level=self.p.pivot_level)
        return df

    def _exit(self, ctx: Context) -> Order | None:
        p, pos = self.p, ctx.pos
        if pos is None or ctx.i <= pos.entry_i:
            return None
        if p.exit_mode == "ladder":
            return ladder_exit(ctx, p.profit_target)
        if p.exit_mode == "prev_low_break":
            trough = last_confirmed(self._pivots, ctx.i, "trough")
            if trough is not None and trough.index > pos.entry_i and ctx.bar()["close"] < trough.price:
                return Order.exit("跌破一低")
        return None

    def on_bar(self, ctx: Context):
        p, df, i = self.p, ctx.df, ctx.i
        order = None
        if i >= 1:
            b, a = df.iloc[i], df.iloc[i - 1]
            dif, dif_p = b["dif"], a["dif"]
            m, m_p = b["macd_line"], a["macd_line"]
            if not (dif != dif or m != m):
                if dif_p <= m_p and dif > m:  # 金叉確認
                    if self._prev_cross_i is not None:  # C1：非首次金叉，視為雙金叉候選
                        gap = i - self._prev_cross_i
                        red_ok = (not p.require_red) or (b["close"] > b["open"])
                        if gap <= p.max_bars_between_crosses and red_ok:
                            stop = float(b["low"])
                            order = Order.enter(Side.LONG, stop=stop, reason="MACD雙金叉反轉買點")
                    self._prev_cross_i = i  # 不論本次是否成立，皆做為下一次比較基準

        orders: list[Order] = []
        if ctx.pos is not None:
            ex = self._exit(ctx)
            if ex is not None:
                orders.append(ex)
        if order is not None and (ctx.pos is None or ctx.pos.side != order.side):
            orders.append(order)
        return orders or None
