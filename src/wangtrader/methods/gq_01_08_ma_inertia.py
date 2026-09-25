"""gq-01-08 K線慣性操作：突破N日高進場／跌破N日低出場（《股技期招》第一章第三節，p.31-41）。

規格文件：methods/股技期招/gq-01-08-K線慣性操作.md

本方法為波段方法（intraday=False，可跨日持有）。書中以個股日K線示範，程式不綁週期，
均線黃金/死亡交叉界定多空、突破前1日高低進場、突破/跌破前N日高低出場，天期N原文明言可依
商品特性與個人風險承受度彈性調整（1/2/4/8日皆可，見§2），本模組將N做成參數，不自動切換。

訊號（p.32-39）：
  多方：C1 快均線（fast_period）與慢均線（slow_period）黃金交叉界定多頭；C2 收盤突破前一根K線
    最高點 → 買進（未持倉時）。
  空方（鏡像）：C1' 死亡交叉界定空頭；C2' 收盤跌破前一根K線最低點 → 放空訊號；台股平盤以下禁空
    （p.38），本模組以 no_short_below_flat 參數化：訊號當根收盤即為「隔日平盤」參考價，實際放空
    須等後續某根K線價格觸及該參考價（以上）才成交，採核心限價單機制模擬（flat_wait_bars 內未觸價
    即放棄）；台指期分K無此限制，可將此參數設 False 直接進場。
出場（p.32-39）：多方收盤跌破前 long_exit_n 日區間最低點；空方收盤突破前 short_exit_n 日區間最高點
  （皆不含當根，即「前N日」）。停損：原文未另立獨立停損規則，出場條件本身兼具停損停利功能（p.35）。
過濾：F1 台股平盤下禁空（見上）。F2（作者提醒，非強制規則）出場天期過短易受盤整刷洗，僅供使用者
  選參考，不另立自動判斷邏輯。

均線可用簡單平均或EMA（p.35,39-40，原文皆可，本模組以 use_ema 開關，預設簡單平均）。

待確認事項：
  - N 值（long_exit_n / short_exit_n）原文列出多組候選值、未給單一建議值，本模組預設 4（取書中示範
    區間中段），使用者應依商品/週期自行覆寫，非原文指定的最佳解。
  - 「隔日平盤以上才可放空」以限價單模擬（限價＝訊號當根收盤），與原文逐筆盤中判斷仍有近似成分。
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from wangtrader.core import Context, Order, Side, Strategy
from wangtrader.core.indicators import sma

METHOD_ID = "gq-01-08"


@dataclass
class Params:
    fast_period: int = 10  # 快均線，MA10（p.35）
    slow_period: int = 20  # 慢均線，MA20（p.35；亦可用MA20/MA60，自行調整）
    use_ema: bool = False  # 均線計算基礎：簡單平均(False)或EMA(True)皆可（p.35,39-40）
    long_exit_n: int = 4  # 多方出場：跌破前N日區間低點，N常見1/2/4/8（p.32-37），預設取中段值
    short_exit_n: int = 4  # 空方回補：突破前N日區間高點，N常見1/2/8（p.38-39），預設取中段值
    no_short_below_flat: bool = True  # 台股平盤下禁空（p.38）；台指期分K可設 False
    flat_wait_bars: int = 60  # 等待價格觸及平盤以上的最長根數（原文未規定，推論預設值）


class MaInertia(Strategy):
    method_id = METHOD_ID
    intraday = False  # 波段方法，可跨日持有

    def __init__(self, **kw) -> None:
        self.p = Params(**kw)

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        p = self.p
        if p.use_ema:
            df["fast"] = df["close"].ewm(span=p.fast_period, adjust=False, min_periods=p.fast_period).mean()
            df["slow"] = df["close"].ewm(span=p.slow_period, adjust=False, min_periods=p.slow_period).mean()
        else:
            df["fast"] = sma(df["close"], p.fast_period)
            df["slow"] = sma(df["close"], p.slow_period)
        sign = (df["fast"] - df["slow"]).apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
        df["regime"] = sign.replace(0, float("nan")).ffill()
        df["exit_low_n"] = df["low"].rolling(p.long_exit_n, min_periods=p.long_exit_n).min().shift(1)
        df["exit_high_n"] = df["high"].rolling(p.short_exit_n, min_periods=p.short_exit_n).max().shift(1)
        return df

    def _exit(self, ctx: Context) -> Order | None:
        pos, df, i = ctx.pos, ctx.df, ctx.i
        if pos is None or ctx.i <= pos.entry_i:
            return None
        b = df.iloc[i]
        if pos.side == Side.LONG:
            lvl = b["exit_low_n"]
            if pd.notna(lvl) and b["close"] < lvl:
                return Order.exit("跌破N日低點出場")
        else:
            lvl = b["exit_high_n"]
            if pd.notna(lvl) and b["close"] > lvl:
                return Order.exit("突破N日高點回補")
        return None

    def on_bar(self, ctx: Context):
        p, df, i = self.p, ctx.df, ctx.i
        if i < 1:
            return None
        b, prev = df.iloc[i], df.iloc[i - 1]
        regime = b["regime"]

        if ctx.pos is not None:
            ex = self._exit(ctx)
            return [ex] if ex else None

        if pd.isna(regime):
            return None

        if regime == 1 and b["close"] > prev["high"]:
            return [Order.enter(Side.LONG, stop=None, reason="K線慣性買進")]

        if regime == -1 and b["close"] < prev["low"]:
            if not p.no_short_below_flat:
                return [Order.enter(Side.SHORT, stop=None, reason="K線慣性放空")]
            flat = float(b["close"])  # 隔日平盤參考價＝訊號當根收盤
            return [Order.enter_limit(Side.SHORT, limit=flat, expire=p.flat_wait_bars, stop=None,
                                       reason="K線慣性放空(等平盤)")]
        return None
