"""gq-02-04 KD 買賣點分布（金叉／死叉 3 天濾網）（《股技期招》第二章第四節，p.115–121）。

規格文件：methods/股技期招/gq-02-04-KD黃金死亡交叉三日濾網.md

本方法原文以個股/陸股日線為例。書中「5%或7%」停損為百分比參數，套用於台指期分K回測時
幅度極小、幾乎不會觸發，需另行調高 stop_pct 才有意義。

趨勢判斷（原文「均線多頭排列」/「均線死叉、空頭格局」未指定具體均線週期，本模組以快慢均線
trend_fast/trend_slow（推論預設5/20）交叉近似：fast_ma>slow_ma 視為多頭排列，反之視為空頭）。

訊號（p.115–116, 119–120）：
  多方（金叉買點）：
    C1 多頭排列（fast_ma>slow_ma），僅用金叉找買點。
    C2 D值降至 d_cross_max（預設65）以下所形成的金叉（K上穿D）。
    C3 濾網：金叉距最近已確認波谷（層級 pivot_level，推論預設1）不超過 gap_days_max（預設3）天
       （自最低點起算，不含最低點當天）；若谷點後價格未創新低（近似「橫向游走」，見下方說明）
       則不受此限制（p.115–116）。
    C4（同位階）：與前一次多方進場價相差在 tier_pct（推論預設2%）以內、且前一次尚未停損出場，
       視為同位階訊號，只取第一個（p.116）；前一次已停損出場則解除限制。
    C5（已反彈過多/已下跌過多）、K線品質等軟性/未量化條件，原文未提供可計算門檻，本模組不實作。
  空方（死叉賣點，放空）：C1'–C4' 為多方鏡像，另加：
    C2' K值在 k_cross_min（預設20）以上所形成的死叉（K下穿D）。
    C5' 死叉訊號K線須為黑K（收盤<開盤），紅K不做（p.120）。

進場（p.115–120）：條件成立時，於交叉當根收盤進場。

停損（p.120–121）：
  多方：原文本節未重述（僅放空方向具體說明），本模組多方不設停損以外的規則，
    採用與空方相同的 stop_pct 百分比法作為預設實作（見模組尾端待確認事項；非原文明文規定，
    僅為避免完全無停損機制的權宜作法，可用 long_stop_pct=None 關閉）。
  空方 stop_mode="pct"（預設）：stop_pct（預設7%，書中5%或7%擇一，未言明優先序）。
       stop_mode="peak_tick"：波峰最高點上方一檔（stop_tick，推論預設1.0）。

出場 / 移動停損（p.120）：
  空方 trailing_black_bar=True（預設）：以最近一根「長黑K線」的最高點逐次向下移動停損
    （只能調低不能調高，比照 gq-01-12 模式一之精神），「長黑K線」以 black_bar_pct（推論預設，
    原文僅稱「長黑K線」未量化，沿用 big_bar_pct 概念，預設4%）近似判定。
  多方：原文未規定移動停損/停利規則，本模組不發明。

過濾：見上方 C3/C4/C5' 條件。

週期：不限。d_cross_max/k_cross_min 為KD數值(0-100)，不隨價位縮放；stop_pct/tier_pct/black_bar_pct
  為百分比，不隨價位縮放；gap_days_max/pivot_level/trend_fast/trend_slow 為天數/層級/根數，不隨價位
  縮放；stop_tick 比照 q3_01 慣例不隨價位縮放。本模組沒有「點數」型參數，不需要加入
  scripts/point_params.py 的縮放表。
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from wangtrader.core import Context, Order, Side, Strategy
from wangtrader.core.indicators import kd, sma
from wangtrader.core.pivots import Pivot, confirmed_before, find_pivots

METHOD_ID = "gq-02-04"


@dataclass
class Params:
    trend_fast: int = 5  # 趨勢快線，原文未指定週期，推論預設
    trend_slow: int = 20  # 趨勢慢線，原文未指定週期，推論預設
    kd_n: int = 9
    k_period: int = 3
    d_period: int = 3
    d_cross_max: float = 65.0  # C2，p.115
    k_cross_min: float = 20.0  # C2'，p.119
    pivot_level: int = 1  # 波谷/波峰層級，原文未定量，推論預設1
    gap_days_max: int = 3  # C3/C3'，p.115-116, 119
    tier_pct: float = 0.02  # C4/C4' 同位階容忍度，原文未定量，推論預設2%
    black_k_required: bool = True  # C5'，p.120
    stop_mode: str = "pct"  # "pct"|"peak_tick"（空方）
    stop_pct: float = 0.07  # p.120
    stop_tick: float = 1.0  # stop_mode="peak_tick" 用，推論預設1.0
    long_stop_pct: float | None = None  # 多方停損：原文未規定，預設關閉（可設 0.07 權宜使用）
    trailing_black_bar: bool = True  # 空方移動停損（p.120）
    black_bar_pct: float = 0.04  # 「長黑K線」判定門檻，原文未量化，推論預設


class KdCrossGapFilter(Strategy):
    method_id = METHOD_ID
    intraday = False  # 波段方法（個股日線多日持有）

    def __init__(self, **kw) -> None:
        self.p = Params(**kw)
        self._pivots: list[Pivot] = []
        self._last_entry: dict[Side, tuple[float, bool] | None] = {Side.LONG: None, Side.SHORT: None}

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        p = self.p
        df["fast_ma"] = sma(df["close"], p.trend_fast)
        df["slow_ma"] = sma(df["close"], p.trend_slow)
        kdf = kd(df, n=p.kd_n, k_period=p.k_period, d_period=p.d_period)
        df["k"], df["d"] = kdf["k"], kdf["d"]
        df["pct_chg"] = df["close"].pct_change()
        self._pivots = find_pivots(df, p.pivot_level)
        return df

    def _gap_ok(self, df: pd.DataFrame, i: int, kind: str) -> bool:
        """C3/C3'：距最近已確認波谷/波峰是否在 gap_days_max 內，或谷/峰點後未再創極端（橫向游走近似）。"""
        p = self.p
        pivs = confirmed_before(self._pivots, i, kind)
        if not pivs:
            return False
        piv = pivs[-1]
        if i - piv.index <= p.gap_days_max:
            return True
        seg = df["low" if kind == "trough" else "high"].iloc[piv.index + 1 : i + 1]
        if seg.empty:
            return True
        return bool(seg.min() >= piv.price) if kind == "trough" else bool(seg.max() <= piv.price)

    def _tier_blocked(self, side: Side, price: float) -> bool:
        """C4/C4'：與前次同方向未停損之進場價過近 → 忽略。"""
        state = self._last_entry[side]
        if state is None:
            return False
        last_price, stopped = state
        return (not stopped) and abs(price - last_price) <= self.p.tier_pct * last_price

    def detect(self, df: pd.DataFrame, i: int) -> Side | None:
        p = self.p
        if i < 1:
            return None
        f0, s0 = df.at[i - 1, "fast_ma"], df.at[i - 1, "slow_ma"]
        f1, s1 = df.at[i, "fast_ma"], df.at[i, "slow_ma"]
        k0, d0, k1, d1 = df.at[i - 1, "k"], df.at[i - 1, "d"], df.at[i, "k"], df.at[i, "d"]
        if any(pd.isna(x) for x in (f0, s0, f1, s1, k0, d0, k1, d1)):
            return None
        bull = f1 > s1
        golden = k0 <= d0 and k1 > d1
        death = k0 >= d0 and k1 < d1
        price = float(df.at[i, "close"])
        if bull and golden and d1 <= p.d_cross_max and self._gap_ok(df, i, "trough"):
            if not self._tier_blocked(Side.LONG, price):
                return Side.LONG
            return None
        if (not bull) and death and k1 >= p.k_cross_min and self._gap_ok(df, i, "peak"):
            b = df.iloc[i]
            if p.black_k_required and not (b["close"] < b["open"]):
                return None
            if not self._tier_blocked(Side.SHORT, price):
                return Side.SHORT
        return None

    def _stop(self, df: pd.DataFrame, i: int, side: Side, price: float) -> float | None:
        p = self.p
        if side == Side.LONG:
            return None if p.long_stop_pct is None else price * (1 - p.long_stop_pct)
        if p.stop_mode == "peak_tick":
            piv = confirmed_before(self._pivots, i, "peak")
            if piv:
                return piv[-1].price + p.stop_tick
        return price * (1 + p.stop_pct)

    def _trailing_short_stop(self, ctx: Context) -> None:
        """空方：長黑K線最高點逐次向下移動（只能調低），p.120。"""
        p, df, i, pos = self.p, ctx.df, ctx.i, ctx.pos
        b = df.iloc[i]
        is_black = b["close"] < b["open"]
        big = pd.notna(df.at[i, "pct_chg"]) and df.at[i, "pct_chg"] <= -p.black_bar_pct
        if is_black and big:
            pos.stop = float(b["high"]) if pos.stop is None else min(pos.stop, float(b["high"]))

    def on_bar(self, ctx: Context):
        p, df, i = self.p, ctx.df, ctx.i
        if ctx.stopped is not None:
            self._last_entry[ctx.stopped.side] = (ctx.stopped.entry_price, True)
        if ctx.pos is not None:
            if ctx.pos.side == Side.SHORT and p.trailing_black_bar:
                self._trailing_short_stop(ctx)
            return None
        side = self.detect(df, i)
        if side is None:
            return None
        price = float(df.at[i, "close"])
        self._last_entry[side] = (price, False)
        reason = "KD金叉買點" if side == Side.LONG else "KD死叉賣點"
        return [Order.enter(side, stop=self._stop(df, i, side, price), reason=reason)]
