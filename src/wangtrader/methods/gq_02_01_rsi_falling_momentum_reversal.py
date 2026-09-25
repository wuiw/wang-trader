"""gq-02-01 RSI 連續下跌慣性改變買點（《股技期招》第二章第一節，p.91–98）。

規格文件：methods/股技期招/gq-02-01-RSI連續下跌慣性改變買點.md

本方法原文以個股日線為例（p.91）。書中門檻「反漲3%」「停損7%」皆為百分比參數，套用於
台指期分K回測時漲跌幅度極小、幾乎不會觸發，需另行調高 reversal_pct / stop_pct 才有意義。
RSI 週期原文未指定，依專案 core.indicators.rsi 慣用預設 5（wilder）沿用，屬推論預設值。

訊號（p.92）：
  C1 多頭市場：季線、年線皆朝上。原文未定量「朝上」的判斷方式，本模組以
     「季線/年線現值 > trend_lookback 根之前的值」近似（trend_lookback 為推論參數，預設1）。
  C2 自波峰回檔以來，RSI 連續遞減（今日 < 昨日）達 down_run_days（預設6，含）天以上。
  C3 出現一根漲幅 >= reversal_pct（預設3%）的反漲K線，使 RSI 由跌轉漲（扭轉下跌慣性）。
進場（p.92；p.99 推論依據，全章一致做法）：C1+C2+C3 成立時，於反漲K線收盤進場（推論）。

停損（p.94, 96）：
  method_1（預設）：最大 stop_pct（預設7%），停損 = 進場價 * (1 - stop_pct)。
  method_2（水平支撐/下影線）：原文以「重要水平支撐最低點」「下影線下方一檔」為停損，
    需人工辨識水平支撐位置，非可由K線資料通用規則推導，本模組未實作（見模組尾端待確認事項）。

出場：原文未規定固定停利（p.94：本節僅提及可搭配「四種移動停損停利模式」之名稱，未展開規則）。
  依任務指示，文件引用 gq-01-12（出場停損模式）之出場時於本模組私有實作；exit_mode 參數
  預設 "none"（不啟用，只靠停損出場，忠於本節「原文未規定」的描述），可選擇性開啟：
    "model1"：大漲K線（漲幅 >= big_bar_pct，預設4%，gq-01-12 p.85）真實低點（K線低點與
      前一根收盤孰低）為移動停損，僅逐次上移，不下修。
    "model2"：層級 pivot_level（預設2，gq-01-12 p.86）低轉折點為移動停損，僅能調高不能調低。
    "model4"：前 n_window_long 根（預設10，gq-01-12 p.88）區間最低點，每根K線重新計算，
      不限方向（可能因新K線加入使停損「突升」，亦可能下移，原文特別容許此現象）。
  model3（二根K線區間、需搭配「無遮蔽」定義，見 gq-01-11 C5）因「無遮蔽」定義在移動停損情境下
  語意不明確、原文本節亦未展開，故不實作，避免自行發明規則。

過濾：原文僅列出「頭部風險」「籌碼凌亂」等軟性提醒（p.95–96：「切入仍須特別小心」「彈升空間
  不宜看多」），非明確排除條件，本模組不做成硬性 filter，避免自行發明數值化門檻。

週期：不限。stop_pct/reversal_pct/big_bar_pct 為百分比，不隨價位縮放；season_period/year_period/
  down_run_days/pivot_level/n_window_long/trend_lookback 為根數/層級，同樣不隨價位縮放；
  本模組沒有「點數」型參數，不需要加入 scripts/point_params.py 的縮放表。
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from wangtrader.core import Context, Order, Side, Strategy
from wangtrader.core.indicators import rsi, sma
from wangtrader.core.pivots import Pivot, find_pivots, last_confirmed

METHOD_ID = "gq-02-01"


@dataclass
class Params:
    rsi_period: int = 5  # RSI週期，原文未指定，依專案慣用預設5（推論）
    rsi_method: str = "wilder"
    season_period: int = 60  # 季線，依台股慣例60日（原文僅稱「季線」，推論標明）
    year_period: int = 240  # 年線，依台股慣例240日（推論標明）
    trend_lookback: int = 1  # C1：判斷季線/年線「朝上」的比較根數，原文未定量，推論預設值
    down_run_days: int = 6  # C2：RSI連續遞減天數門檻（含），p.92
    reversal_pct: float = 0.03  # C3：反漲K線漲幅門檻，p.92
    stop_pct: float = 0.07  # 停損：最大7%，p.94
    exit_mode: str = "none"  # "none"|"model1"|"model2"|"model4"（見模組docstring，比照gq-01-12）
    big_bar_pct: float = 0.04  # model1：大漲/跌K線門檻，gq-01-12 p.85
    pivot_level: int = 2  # model2：轉折點層級，gq-01-12 p.86
    n_window_long: int = 10  # model4：區間根數（書中多方範例10），gq-01-12 p.88


class RsiFallingMomentumReversal(Strategy):
    method_id = METHOD_ID
    intraday = False  # 波段方法（原書為個股日線多日持有），比照 q3-11 設 False

    def __init__(self, **kw) -> None:
        self.p = Params(**kw)
        self._pivots: list[Pivot] = []

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        p = self.p
        df["rsi"] = rsi(df["close"], p.rsi_period, p.rsi_method)
        df["season_ma"] = sma(df["close"], p.season_period)
        df["year_ma"] = sma(df["close"], p.year_period)
        df["pct_chg"] = df["close"].pct_change()
        if p.exit_mode == "model2":
            self._pivots = find_pivots(df, p.pivot_level)
        return df

    def _bull_market(self, df: pd.DataFrame, i: int) -> bool:
        """C1：季線、年線皆朝上（近似：現值 > trend_lookback 根之前的值，p.92）。"""
        p = self.p
        j = i - p.trend_lookback
        if j < 0:
            return False
        s0, s1 = df.at[i, "season_ma"], df.at[j, "season_ma"]
        y0, y1 = df.at[i, "year_ma"], df.at[j, "year_ma"]
        if pd.isna(s0) or pd.isna(s1) or pd.isna(y0) or pd.isna(y1):
            return False
        return bool(s0 > s1 and y0 > y1)

    def _down_run(self, df: pd.DataFrame, end_i: int) -> int:
        """回傳以 end_i 結尾、RSI 連續遞減（今日<昨日）的天數（步數）。"""
        rsi_s = df["rsi"]
        n = 0
        k = end_i
        while k > 0 and pd.notna(rsi_s.iat[k]) and pd.notna(rsi_s.iat[k - 1]) and rsi_s.iat[k] < rsi_s.iat[k - 1]:
            n += 1
            k -= 1
        return n

    def detect(self, df: pd.DataFrame, i: int) -> float | None:
        """第 i 根收盤時 C1+C2+C3 是否成立，回傳進場價（收盤價）。"""
        p = self.p
        if i < 1 or pd.isna(df.at[i, "rsi"]) or pd.isna(df.at[i - 1, "rsi"]):
            return None
        if not self._bull_market(df, i):
            return None
        if self._down_run(df, i - 1) < p.down_run_days:
            return None
        if not (df.at[i, "rsi"] > df.at[i - 1, "rsi"]):
            return None
        if not (df.at[i, "pct_chg"] >= p.reversal_pct):
            return None
        return float(df.at[i, "close"])

    def _apply_moving_stop(self, ctx: Context) -> None:
        """依 exit_mode 更新 ctx.pos.stop（下一根起生效，由引擎內建的停損機制觸發出場）。"""
        p, df, i, pos = self.p, ctx.df, ctx.i, ctx.pos
        if p.exit_mode == "model1":
            if df.at[i, "pct_chg"] >= p.big_bar_pct:  # 大漲K線（gq-01-12 p.85）
                prev_close = df.at[i - 1, "close"] if i > 0 else df.at[i, "low"]
                real_low = min(df.at[i, "low"], prev_close)
                pos.stop = real_low if pos.stop is None else max(pos.stop, real_low)
        elif p.exit_mode == "model2":
            piv = last_confirmed(self._pivots, i, "trough")
            if piv is not None:
                pos.stop = piv.price if pos.stop is None else max(pos.stop, piv.price)  # 只能調高
        elif p.exit_mode == "model4":
            lo = max(0, i - p.n_window_long + 1)
            pos.stop = float(df["low"].iloc[lo : i + 1].min())  # 每日重新計算，可能突升（原文容許）

    def on_bar(self, ctx: Context):
        p, df, i = self.p, ctx.df, ctx.i
        if ctx.pos is not None:
            if p.exit_mode != "none":
                self._apply_moving_stop(ctx)
            return None
        price = self.detect(df, i)
        if price is None:
            return None
        stop = price * (1 - p.stop_pct)
        return [Order.enter(Side.LONG, stop=stop, reason="RSI連低買點")]
