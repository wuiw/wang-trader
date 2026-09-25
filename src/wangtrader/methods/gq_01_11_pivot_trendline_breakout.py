"""gq-01-11 高低轉折點趨勢線突破/跌破訊號（《股技期招》第一章第五節，p.62-82）。

規格文件：methods/股技期招/gq-01-11-轉折點趨勢線突破訊號.md

本方法為波段方法（intraday=False，可跨日持有；書中兼有台指期5分K與個股日K範例，河流圖／均線
交叉判斷多空的效果相同，本模組以均線交叉實作，河流圖為其視覺化等效版本，不另外實作）。

訊號（p.62-65）：
  多方：C1 快慢均線（fast_period/slow_period）金叉界定多頭。C2 取最近兩個依序遞減的層級
    pivot_level（預設2）高轉折點連線畫下降趨勢線；找不到兩個遞減峰點時不成立。C3 K線收盤突破此
    下降趨勢線（線性內插/外插至當根索引）。C4 同時收盤突破前2根K線最高點。
  空方（鏡像）：C1' 死叉界定空頭；C2' 最近兩個依序遞增的層級2低轉折點連線畫上升趨勢線；C3' 收盤
    跌破此上升趨勢線；C4' 同時收盤跌破前2根K線最低點。
  C5 品質再確認（require_ma_confirm，預設開啟，p.67,77,80）：訊號K線收盤未站上快均線（多）／未
    跌破快均線（空）時，不直接進場，改為等待後續某根K線（P點）收盤站上（跌破）快均線，且P點之前
    （不含訊號K本身）沒有任何一根K線的高點高於P點收盤（多）／低點低於P點收盤（空）（「無遮蔽」）
    才進場（本模組以「訊號K之後每根bar追蹤區間極值」實作，見程式）。
  C6 K線品質（reject_bad_candle，預設開啟，p.78-79）：訊號K線若為小星線（實體 < body_min_pct%）
    或上影線（多）／下影線（空）超過實體長度，不直接評估C5，改為等待後續K線收盤突破（多）／跌破
    （空）訊號K線高（低）點，且須在 confirm_max_wait 根內、價格未偏離訊號K收盤超過
    confirm_max_drift_pct%，逾時或偏離過遠則放棄該訊號（C6與C5為兩個獨立的等待佇列，簡化為不鏈式
    疊加：C6等待中的確認K線一旦成立即直接進場，不再另外檢查C5）。
進場：C1-C4（及C5/C6視情況）皆滿足之當根K線收盤進場。
停損（stop_mode，二擇一以上，原文未強制指定優先序，p.65-66,68-70,79-80）：
  "pivot"（預設）：最近一個層級 pivot_level 反向轉折點；找不到則退回 fixed_points（台指期常用30點，
    p.68-70）。"fixed"：一律固定 fixed_points。"pct"：收盤價 ∓ stop_pct%（日線個股版，7%，p.65,79）。
  巨大K線覆寫（big_candle_mid_override，預設開啟，p.66,72）：訊號K線振幅（高-低）≥
  big_candle_range_points（點數，需依商品縮放）時，一律以訊號K線中點（(高+低)/2）為停損，覆蓋
  stop_mode之選擇。
出場：原文未給出統一停利規則（見§6）。可選 exit_mode="ladder"（沿用核心 core.exits.ladder_exit，
  p.79建議之一）｜"channel"（N根K線區間出場，呼應「K線慣性操作」之突破幾天高（低），本模組私有
  實作）｜"none"（預設，不主動停利）。
過濾：
  F1 已由C2/C2'的「找不到兩個遞減/遞增轉折點」自然涵蓋（無法連線則不成立訊號）。
  F4 距收盤不到1小時可忽略（bars_before_close_ignore，原文為當沖情境下的可選忽略，非強制規則，
     且與週期綁定，本模組預設 None 關閉，不強加）。

待確認事項：
  - 河流圖未另外實作，以均線交叉視為等效（原文亦說明兩者效果相同）。
  - C5、C6 皆為「等待確認」機制，原文未說明兩者同時不成立時如何疊加，本模組簡化為互斥的獨立分支
    （C6優先於C5檢查），詳見上方說明。
  - stop_mode 的"pivot"在轉折點未產生時，原文以「圖上標記的停損位置」表示、未說明計算方式（p.69待
    確認事項1），本模組退回 fixed_points 作為明確可執行的替代，屬簡化。
  - big_candle_range_points 為點數門檻，需依商品價位縮放（見 scripts/point_params.py 建議加入）。
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from wangtrader.core import Context, Order, Side, Strategy
from wangtrader.core.exits import ladder_exit
from wangtrader.core.indicators import sma
from wangtrader.core.pivots import Pivot, confirmed_before, find_pivots

METHOD_ID = "gq-01-11"


def _trendline_value(p1: Pivot, p2: Pivot, x: int) -> float:
    """兩轉折點 p1(較早)、p2(較晚) 連線，回傳在索引 x 處的內插/外插值。"""
    if p2.index == p1.index:
        return p2.price
    slope = (p2.price - p1.price) / (p2.index - p1.index)
    return p1.price + slope * (x - p1.index)


@dataclass
class Params:
    fast_period: int = 20  # 快均線（河流圖最短均線之等效），p.67「站上最短均線」
    slow_period: int = 50  # 慢均線，判斷多空交叉用（p.68 MA300/180；p.76 EMA20/50，本模組簡化為單一組）
    pivot_level: int = 2  # 層級2轉折點（p.64-65）
    require_ma_confirm: bool = True  # C5（p.67,77,80）
    reject_bad_candle: bool = True  # C6（p.78-79）
    body_min_pct: float = 1.0  # C6：小星線門檻，實體 < 收盤價此百分比（原文未定量，推論）
    confirm_max_wait: int = 10  # C6 等待確認K線的最長根數（原文未定量，推論）
    confirm_max_drift_pct: float = 5.0  # C6 偏離訊號K收盤超過此百分比則放棄（原文未定量，推論）
    stop_mode: str = "pivot"  # "pivot"｜"fixed"｜"pct"
    fixed_points: float = 30.0  # stop_mode="fixed" 或 pivot 找不到轉折點時的退回值（p.68-70）
    stop_pct: float = 7.0  # stop_mode="pct"（p.65,79）
    big_candle_mid_override: bool = True  # 巨大K線以中點為停損（p.66,72）
    big_candle_range_points: float = 60.0  # 判斷「巨大K線」的振幅門檻（點數，需依商品縮放，原文未給
    #                                         明確數字，推論預設值，比照台指期範例的較大波動幅度）
    exit_mode: str = "none"  # "none"｜"ladder"｜"channel"
    exit_channel_n: int = 10  # exit_mode="channel" 用視窗根數
    ladder_target: float = 30.0  # exit_mode="ladder" 的獲利目標點數（原文未指定，推論，需依商品縮放）


class PivotTrendlineBreakout(Strategy):
    method_id = METHOD_ID
    intraday = False  # 波段方法，可跨日持有

    def __init__(self, **kw) -> None:
        self.p = Params(**kw)
        self._pivots: list[Pivot] = []
        self._ma_watch: dict | None = None  # {'side':.., 'sig_i':.., 'ext':..}  C5 等待中
        self._confirm_watch: dict | None = None  # {'side':.., 'level':.., 'sig_close':.., 'start':..}  C6 等待中

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        p = self.p
        df["fast"] = sma(df["close"], p.fast_period)
        df["slow"] = sma(df["close"], p.slow_period)
        sign = (df["fast"] - df["slow"]).apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
        df["regime"] = sign.replace(0, float("nan")).ffill()
        self._pivots = find_pivots(df, level=p.pivot_level)
        return df

    # ---------- 趨勢線與突破 ----------
    def _trend_break(self, df: pd.DataFrame, i: int, side: Side) -> bool:
        kind = "peak" if side == Side.LONG else "trough"
        pts = [pv for pv in confirmed_before(self._pivots, i - 1, kind)]
        pts.sort(key=lambda pv: pv.index)
        for k in range(len(pts) - 1, 0, -1):
            p2, p1 = pts[k], pts[k - 1]
            desc = p2.price < p1.price if side == Side.LONG else p2.price > p1.price
            if desc:
                line_val = _trendline_value(p1, p2, i)
                close = float(df.at[i, "close"])
                return close > line_val if side == Side.LONG else close < line_val
        return False

    def _break_two_bar(self, df: pd.DataFrame, i: int, side: Side) -> bool:
        if i < 2:
            return False
        close = float(df.at[i, "close"])
        if side == Side.LONG:
            return close > max(float(df.at[i - 1, "high"]), float(df.at[i - 2, "high"]))
        return close < min(float(df.at[i - 1, "low"]), float(df.at[i - 2, "low"]))

    def _detect(self, df: pd.DataFrame, i: int) -> Side | None:
        regime = df.at[i, "regime"]
        if pd.isna(regime) or i < 2:
            return None
        if regime == 1 and self._trend_break(df, i, Side.LONG) and self._break_two_bar(df, i, Side.LONG):
            return Side.LONG
        if regime == -1 and self._trend_break(df, i, Side.SHORT) and self._break_two_bar(df, i, Side.SHORT):
            return Side.SHORT
        return None

    # ---------- 品質過濾 C6：小星線/長影線 ----------
    def _bad_candle(self, b: pd.Series, side: Side) -> bool:
        p = self.p
        body = abs(float(b["close"]) - float(b["open"]))
        if float(b["close"]) > 0 and body < float(b["close"]) * (p.body_min_pct / 100.0):
            return True
        if side == Side.LONG:
            upper = float(b["high"]) - max(float(b["open"]), float(b["close"]))
            return upper > body
        lower = min(float(b["open"]), float(b["close"])) - float(b["low"])
        return lower > body

    # ---------- 停損 ----------
    def _stop(self, df: pd.DataFrame, i: int, side: Side, entry: float) -> float:
        p = self.p
        b = df.iloc[i]
        rng = float(b["high"]) - float(b["low"])
        if p.big_candle_mid_override and rng >= p.big_candle_range_points:
            return (float(b["high"]) + float(b["low"])) / 2.0
        if p.stop_mode == "pct":
            return entry * (1 - p.stop_pct / 100.0) if side == Side.LONG else entry * (1 + p.stop_pct / 100.0)
        if p.stop_mode == "fixed":
            return entry - p.fixed_points if side == Side.LONG else entry + p.fixed_points
        # "pivot"（預設）
        kind = "trough" if side == Side.LONG else "peak"
        pts = confirmed_before(self._pivots, i - 1, kind)
        if pts:
            return pts[-1].price
        return entry - p.fixed_points if side == Side.LONG else entry + p.fixed_points

    # ---------- 出場 ----------
    def _run_exit(self, ctx: Context) -> Order | None:
        p = self.p
        if p.exit_mode == "ladder":
            return ladder_exit(ctx, p.ladder_target)
        if p.exit_mode == "channel":
            pos, df, i = ctx.pos, ctx.df, ctx.i
            if i <= pos.entry_i:
                return None
            window = df.iloc[max(0, i - p.exit_channel_n):i]
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
        orders: list[Order] = []

        if ctx.pos is not None:
            ex = self._run_exit(ctx)
            return [ex] if ex else None

        # C6 等待中：確認K線收盤突破/跌破訊號K線高低點，且未逾時、未偏離過遠
        if self._confirm_watch is not None:
            w = self._confirm_watch
            age = i - w["start"]
            close = float(b["close"])
            drift_ok = abs(close - w["sig_close"]) <= w["sig_close"] * (p.confirm_max_drift_pct / 100.0)
            if age > p.confirm_max_wait or not drift_ok:
                self._confirm_watch = None
            else:
                hit = close > w["level"] if w["side"] == Side.LONG else close < w["level"]
                if hit:
                    side = w["side"]
                    self._confirm_watch = None
                    entry = close
                    orders.append(Order.enter(side, stop=self._stop(df, i, side, entry), reason="轉折趨勢線突破(確認)"))

        # C5 等待中：收盤重新站上/跌破快均線，且期間無遮蔽
        if not orders and self._ma_watch is not None:
            w = self._ma_watch
            fast = b["fast"]
            if pd.notna(fast):
                close = float(b["close"])
                ok = (close > fast) if w["side"] == Side.LONG else (close < fast)
                # 無遮蔽：自訊號K線至P點（不含P點本身）沒有任何一根K線的高點高於P點收盤（多，空鏡像）
                unshaded = (w["ext"] is None or
                            (w["ext"] <= close if w["side"] == Side.LONG else w["ext"] >= close))
                if ok and unshaded:
                    side = w["side"]
                    self._ma_watch = None
                    entry = close
                    orders.append(Order.enter(side, stop=self._stop(df, i, side, entry), reason="轉折趨勢線突破(無遮蔽確認)"))
                else:
                    if w["side"] == Side.LONG:
                        w["ext"] = float(b["high"]) if w["ext"] is None else max(w["ext"], float(b["high"]))
                    else:
                        w["ext"] = float(b["low"]) if w["ext"] is None else min(w["ext"], float(b["low"]))

        if orders:
            return orders

        side = self._detect(df, i)
        if side is None:
            return None

        if p.reject_bad_candle and self._bad_candle(b, side):
            level = float(b["high"]) if side == Side.LONG else float(b["low"])
            self._confirm_watch = {"side": side, "level": level, "sig_close": float(b["close"]), "start": i}
            return None

        fast = b["fast"]
        confirmed = pd.notna(fast) and ((float(b["close"]) > fast) if side == Side.LONG else (float(b["close"]) < fast))
        if p.require_ma_confirm and not confirmed:
            # 無遮蔽追蹤起點含訊號K本身（p.67「自訊號K線至P點之間」）
            ext = float(b["high"]) if side == Side.LONG else float(b["low"])
            self._ma_watch = {"side": side, "ext": ext}
            return None

        entry = float(b["close"])
        return [Order.enter(side, stop=self._stop(df, i, side, entry), reason="轉折趨勢線突破")]
