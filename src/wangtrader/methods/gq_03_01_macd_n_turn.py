"""gq-03-01 金叉後低轉折買點（DIF "N"形轉折）（《股技期招》第三章第一節，p.135–140）。

規格文件：methods/股技期招/gq-03-01-金叉後低轉折買點.md

core/indicators.py 沒有 MACD，本模組私有實作標準 MACD（EMA12/EMA26/DIF、DIF 的 EMA9 為慢線 MACD，
p.135；書中未指定 12/26/9 這組週期參數，採業界標準慣用值，可由 Params 調整）。

訊號（多，p.136）：
  C1 DIF 由下往上穿越 MACD 慢線，形成黃金交叉。
  C2 金叉後 DIF 出現向下彎（今值 < 前值）。
  C3 DIF 向下彎過程中並未跌破 MACD 慢線（未再度死叉）。
  C4 不出幾天，DIF 又重新上勾（今值 > 前值），形成"N"形轉折，此低轉折點即為買進訊號
     （距金叉幾天內算「不出幾天」，原文未定量，見 Params.max_bars_since_cross）。
  C5 訊號當根K線須為陽線，上影線不宜過長（p.137）。
進場（p.136–137, 139）：N 轉折確認當根收盤進場，原文未規定是否需等收盤，本模組採收盤確認
  （與其餘模組一致，避免偷看未來）。
停損（p.137, 139）：訊號K最低點下方一個跳動點；書中另有「價格破底背離」情境（金叉後價格續創
  新低，但 DIF 未再破底），此時以最低谷點為停損。兩者用同一公式涵蓋：停損＝「金叉後至訊號K
  期間的最低點」下方一跳——非背離情境時該最低點恰為訊號K自身低點，與 p.137 規則等價；背離
  情境時該最低點即為期間內真正的谷底，與 p.139 規則等價。另可選固定百分比停損（原文未指定
  數值，p.137，stop_mode="pct"）。停損後是否反手：原文未規定，不實作。
出場：原文僅提及可用階梯出場線作為風控選項之一（p.137），未給利潤啟動門檻；exit_mode 預設
  "none"（不主動停利，原文未規定的停利不發明），可選 "ladder" 並自行設定 profit_target
  （預設 0，即有獲利即啟動移動停利，為推論值）。
過濾（§7）：
  F1/F2 N 轉折須發生在金叉後不久，行情已推升一段才轉折不宜進場（原文未定量「不出幾天」，
        用 max_bars_since_cross 控制，預設值為推論）。
  F3　訊號當根須陽線（必要條件，require_red 預設開啟）。
  F4　（原文「最好」非必要）上影線不宜過長：max_upper_shadow_ratio，原文未定量，預設值為推論。
  F5　（原文「最好」非必要，預設關閉）宜為大漲K線並突破前一天最高點：require_break_prev_high。

本方法為單向買進訊號，原文未描述空方鏡像用法，不實作空方。
週期：不限。所有門檻以根數／比例表示。
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from wangtrader.core import Context, Order, Side, Strategy
from wangtrader.core.exits import ladder_exit

METHOD_ID = "gq-03-01"


def _ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def _macd(close: pd.Series, fast: int, slow: int, signal: int) -> tuple[pd.Series, pd.Series]:
    """標準 MACD：DIF = EMA(fast) - EMA(slow)；慢線 = EMA(DIF, signal)。回傳 (dif, macd_line)。"""
    dif = _ema(close, fast) - _ema(close, slow)
    macd_line = _ema(dif, signal)
    return dif, macd_line


@dataclass
class Params:
    fast: int = 12  # MACD 快線週期，業界標準值（原文未規定）
    slow: int = 26  # MACD 慢線來源週期，業界標準值（原文未規定）
    signal: int = 9  # DIF 平滑週期（慢線 MACD），業界標準值（原文未規定）
    max_bars_since_cross: int = 10  # C4「不出幾天」原文未定量，預設值為推論
    require_red: bool = True  # C5：訊號K須陽線（必要條件，p.137）
    max_upper_shadow_ratio: float | None = 1.0  # 上影線／實體 比例上限，原文未定量，預設值為推論
    require_break_prev_high: bool = False  # 原文「最好」非必要，預設關閉（p.138）
    stop_tick: float = 1.0  # 停損＝期間最低點下方一跳（p.137, 139）
    stop_mode: str = "tick"  # "tick" | "pct"
    fixed_stop_pct: float | None = None  # stop_mode="pct" 時使用，原文未指定數值（p.137）
    exit_mode: str = "none"  # "none" | "ladder"，原文未給明確停利規則
    profit_target: float = 0.0  # ladder 啟動門檻，原文未規定數值，預設0＝有獲利即啟動（推論）


class MacdGoldenCrossLowTurn(Strategy):
    method_id = METHOD_ID
    intraday = False  # 波段方法，可跨日持有

    def __init__(self, **kw) -> None:
        self.p = Params(**kw)
        self._cross_i: int | None = None  # 目前追蹤中的金叉位置
        self._had_down: bool = False  # 金叉後 DIF 是否已出現向下彎
        self._min_low: float | None = None  # 金叉後至今（含當根）的最低點，供停損使用

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["dif"], df["macd_line"] = _macd(df["close"], self.p.fast, self.p.slow, self.p.signal)
        return df

    def _quality_ok(self, b: pd.Series, a: pd.Series) -> bool:
        p = self.p
        if p.require_red and not (b["close"] > b["open"]):
            return False
        if p.max_upper_shadow_ratio is not None:
            body = abs(b["close"] - b["open"])
            shadow = b["high"] - max(b["open"], b["close"])
            if body > 0 and shadow / body > p.max_upper_shadow_ratio:
                return False
            if body == 0 and shadow > 0:
                return False
        if p.require_break_prev_high and not (b["close"] > a["high"]):
            return False
        return True

    def _stop(self, entry: float) -> float:
        p = self.p
        if p.stop_mode == "pct" and p.fixed_stop_pct is not None:
            return entry * (1 - p.fixed_stop_pct)
        return float(self._min_low) - p.stop_tick

    def on_bar(self, ctx: Context):
        p, df, i = self.p, ctx.df, ctx.i
        if i < 1:
            return None
        b, a = df.iloc[i], df.iloc[i - 1]
        dif, dif_p = b["dif"], a["dif"]
        m, m_p = b["macd_line"], a["macd_line"]
        if dif != dif or m != m:  # NaN：指標尚未可用
            return None

        order = None
        if self._cross_i is None:
            if dif_p <= m_p and dif > m:  # 黃金交叉確認
                self._cross_i, self._had_down, self._min_low = i, False, float(b["low"])
        else:
            if dif <= m:  # 死叉：C3 失敗，取消追蹤
                self._cross_i = None
            elif i - self._cross_i > p.max_bars_since_cross:  # F1/F2：拖延過久
                self._cross_i = None
            else:
                self._min_low = min(self._min_low, float(b["low"]))
                if dif < dif_p:
                    self._had_down = True  # C2
                elif dif > dif_p and self._had_down:  # C4：N 形轉折確認
                    if self._quality_ok(b, a):  # C5
                        close = float(b["close"])
                        order = Order.enter(Side.LONG, stop=self._stop(close), reason="金叉後低轉折買點")
                    self._cross_i = None  # 本次金叉已用畢（成立或因品質不符放棄），須等下一次金叉

        if ctx.pos is not None:
            if order is not None and order.side == ctx.pos.side:
                order = None
            ex = None
            if p.exit_mode == "ladder":
                ex = ladder_exit(ctx, p.profit_target)
            if ex is not None:
                return [ex]
        return [order] if order is not None else None
