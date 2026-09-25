"""gq-04-02 尋峰谷模式——DMI 石筍現象（《股技期招》第四章第二節，p.176–191）。

規格文件：methods/股技期招/gq-04-02-DMI石筍現象.md

core/indicators.py 沒有 DMI，本模組私有實作標準 Wilder DMI（+DI/-DI，14日平滑，書中未規定
週期參數，採業界標準慣用值，可由 Params.dmi_period 調整）。

訊號：
### 放空（+DI 石筍，p.176、184）
  C1 +DI 從 <=25 一路推升穿越 short_threshold（週/日線40；台指期分時40，見 Params）。
     「一路推升」：推升期間原則上不可下彎；允許下彎但須同時滿足「持續小於 down_bar_tolerance
     （書中3）根K線」且「該K線仍收紅」，否則本輪追蹤作廢，須等 +DI 再次回到<=25 才重新開始
     （p.176、186）。
  C2 其後K線收盤跌破前一根K線最低點，即為放空訊號（p.176、184）。
  例外 exception_5bar（p.176–178、191）：C1 成立前，價格已連續出現 >= five_bar_n（5）根紅K，
     此後 +DI 下彎收黑但未跌破前一根最低點時，仍可成立訊號，條件為該黑K收盤落在前一根紅K實體
     一半之下（p.176–177）；書中另有「爆量K線可豁免此限制」之附加條件（p.178），因「爆量」原文
     未定量，本模組不實作該附加豁免，僅保留主要的「實體一半」判定。
### 買進（-DI 石筍，鏡像，p.180、184）
  C1' -DI 從 <=25 一路推升穿越 long_threshold（週/日線35；台指期分時40）。
  C2' 其後K線收盤突破前一根K線最高點。
  例外（鏡像，p.176–177原文僅明述放空方向，買進方向為推論延伸，已標註「推論」）：連續5根黑K後
     首根收紅但未過前一根最高點，收盤須落在前一根黑K實體一半之上。

進場：C2／C2'（或例外條件）之K線收盤時進場。
時效濾網（p.181–182、185–186）：
  週/日線：訊號距峰谷不超過 max_bars_from_extreme（3）天，且幅度不超過峰谷值的 max_pct_from_extreme
    （15%，可設 None 停用）。
  台指期分時：兩處原文標準不一致——p.185「不超過4根K線為佳」；p.186「10根K線內完成，距最高點
    不超過3根為佳」。依規範取前者（p.185）數字為預設，可自行改用後者：max_bars_from_extreme=4，
    max_pct_from_extreme=None（分時未提及幅度濾網）。
停損（p.182, 184）：stop_mode="recent_extreme"（預設，最近波峰/波谷 ± stop_tick，書中「上下一檔」
  週日線、「1~3檔」分時，本模組化簡為單一 stop_tick 參數，預設1）或 "pct"（固定7%，週/日線適用）。
出場（p.184）：exit_mode="none"（預設，週/日線原文未明確說明）；台指期1分鐘超短線可選
  "points"（固定點數，書中20~30點，points_target 預設25為區間中點，推論值）或
  "rsi5"（RSI(5)：多單於RSI過70後下彎出場，空單於RSI破30後上勾出場，rsi_period 預設5，明確數字）。
過濾／反手（§7）：
  F1　指標未從25以下重新拉升（高檔鈍化）→ 不適用，由狀態機（armed/valid）自然滿足。
  F2　訊號拖延過久 → 見時效濾網。
  F3　訊號距峰谷幅度超過15%（週/日線）→ 見時效濾網。
  反手／橫盤突破反手（p.182–184, 202）：需要「窄幅橫盤且時間夠長」的型態辨識，原文未給可程式化
    的量化門檻，本模組不實作反手機制（見待確認事項）。

本方法多空皆可，實作為對稱鏡像（買進方向的「五根同色K例外」為推論延伸，預設開啟，符合
CODING_SPEC「鏡像規則預設開啟」原則）。
週期：不限。所有門檻以根數／百分比表示；分時與週/日線的差異僅在於預設參數不同，程式本身
不判斷時鐘週期。
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from wangtrader.core import Context, Order, Side, Strategy
from wangtrader.core.indicators import rsi

METHOD_ID = "gq-04-02"


def _dmi(df: pd.DataFrame, period: int) -> tuple[pd.Series, pd.Series]:
    """Wilder DMI：回傳 (+DI, -DI)，0-100。"""
    h, l, c = df["high"], df["low"], df["close"]
    up = h.diff()
    down = -l.diff()
    plus_dm = up.where((up > down) & (up > 0), 0.0)
    minus_dm = down.where((down > up) & (down > 0), 0.0)
    prev_c = c.shift(1)
    tr = pd.concat([h - l, (h - prev_c).abs(), (l - prev_c).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1 / period, adjust=False, min_periods=period).mean() / atr
    minus_di = 100 * minus_dm.ewm(alpha=1 / period, adjust=False, min_periods=period).mean() / atr
    return plus_di, minus_di


@dataclass
class Params:
    dmi_period: int = 14  # 業界標準值，原文未規定
    base_level: float = 25.0  # 起升點門檻（p.176、184、186，明確數字）
    short_threshold: float = 40.0  # +DI 見頂臨界點（週/日線/分時皆40，p.176、184）
    long_threshold: float = 35.0  # -DI 見底臨界點（週/日線35；台指期分時可設40，見docstring）
    down_bar_tolerance: int = 3  # 「一路推升」容許的下彎根數上限（不含），明確數字（p.176、186）
    five_bar_n: int = 5  # 五根同色K例外門檻，明確數字（p.176-177、191）
    mirror_long_exception: bool = True  # 買進方向例外為推論延伸，預設開啟（CODING_SPEC規則6）
    max_bars_from_extreme: int = 3  # 時效濾網（週/日線3天，明確數字；分時可設4或10，見docstring）
    max_pct_from_extreme: float | None = 15.0  # 時效濾網（週/日線15%，明確數字；分時未提及，設None）
    stop_mode: str = "recent_extreme"  # "recent_extreme" | "pct"
    stop_tick: float = 1.0  # 週/日線「上方一檔」；分時「1~3檔」化簡為單一參數
    stop_pct: float = 7.0  # 明確數字（p.182）
    exit_mode: str = "none"  # "none" | "points" | "rsi5"（後兩者為台指期分時超短線用，p.184）
    points_target: float = 25.0  # exit_mode="points"，書中20~30點，取中點為推論預設值
    rsi_period: int = 5  # exit_mode="rsi5"，明確數字（p.184）
    rsi_overbought: float = 70.0
    rsi_oversold: float = 30.0


@dataclass
class _Track:
    armed: bool = False  # 曾touch<=base_level，正在追蹤一路推升
    down_streak: int = 0
    valid: bool = True
    crossed: bool = False  # 本輪是否已越過臨界點
    extreme_i: int | None = None  # 越過臨界點後、目前最有利方向的峰/谷位置（用於時效與停損）


class DmiStalagmite(Strategy):
    method_id = METHOD_ID
    intraday = False

    def __init__(self, **kw) -> None:
        self.p = Params(**kw)
        self._short = _Track()
        self._long = _Track()
        self._run_color: str | None = None
        self._run_len: int = 0

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["plus_di"], df["minus_di"] = _dmi(df, self.p.dmi_period)
        if self.p.exit_mode == "rsi5":
            df["rsi5"] = rsi(df["close"], self.p.rsi_period)
        return df

    def _update_track(self, tr: _Track, di: float, di_prev: float, is_up_color: bool) -> None:
        """更新單一方向（+DI 或 -DI）的一路推升狀態（p.176、186）。"""
        p = self.p
        if di <= p.base_level:
            tr.armed, tr.down_streak, tr.valid, tr.crossed, tr.extreme_i = True, 0, True, False, None
            return
        if not tr.armed:
            return
        if di < di_prev and not is_up_color:  # 收黑的下彎才累計次數；收紅的下彎不限次數皆容忍（p.176、186）
            tr.down_streak += 1
            if tr.down_streak >= p.down_bar_tolerance:
                tr.valid = False
        else:
            tr.down_streak = 0

    def _timing_ok(self, df: pd.DataFrame, extreme_i: int, i: int, extreme_price: float) -> bool:
        p = self.p
        if i - extreme_i > p.max_bars_from_extreme:
            return False
        if p.max_pct_from_extreme is not None and extreme_price != 0:
            if abs(df.at[i, "close"] - extreme_price) / abs(extreme_price) * 100 > p.max_pct_from_extreme:
                return False
        return True

    def _exit(self, ctx: Context) -> Order | None:
        p, pos, b = self.p, ctx.pos, ctx.bar()
        if pos is None or ctx.i <= pos.entry_i:
            return None
        if p.exit_mode == "points":
            if pos.side == Side.LONG and pos.profit(b["close"]) >= p.points_target:
                return Order.exit("固定點數停利")
            if pos.side == Side.SHORT and pos.profit(b["close"]) >= p.points_target:
                return Order.exit("固定點數停利")
        elif p.exit_mode == "rsi5":
            rv, rv_p = b["rsi5"], ctx.bar(1)["rsi5"]
            if pd.isna(rv) or pd.isna(rv_p):
                return None
            if pos.side == Side.LONG and rv_p >= p.rsi_overbought and rv < rv_p:
                return Order.exit("RSI(5)過70下彎出場")
            if pos.side == Side.SHORT and rv_p <= p.rsi_oversold and rv > rv_p:
                return Order.exit("RSI(5)破30上勾出場")
        return None

    def on_bar(self, ctx: Context):
        p, df, i = self.p, ctx.df, ctx.i
        b = df.iloc[i]
        order = None

        prev_run_color, prev_run_len = self._run_color, self._run_len
        color = "red" if b["close"] > b["open"] else "black" if b["close"] < b["open"] else None

        if i >= 1:
            a = df.iloc[i - 1]
            plus_di, plus_di_p = b["plus_di"], a["plus_di"]
            minus_di, minus_di_p = b["minus_di"], a["minus_di"]
            if not (plus_di != plus_di or minus_di != minus_di):
                self._update_track(self._short, plus_di, plus_di_p, color == "red")
                self._update_track(self._long, minus_di, minus_di_p, color == "black")

                # C1：一路推升越過臨界點
                if self._short.valid and not self._short.crossed and plus_di >= p.short_threshold:
                    self._short.crossed, self._short.extreme_i = True, i
                elif self._short.crossed and self._short.valid:
                    if b["high"] >= df.at[self._short.extreme_i, "high"]:
                        self._short.extreme_i = i  # 峰位隨創新高更新

                if self._long.valid and not self._long.crossed and minus_di >= p.long_threshold:
                    self._long.crossed, self._long.extreme_i = True, i
                elif self._long.crossed and self._long.valid:
                    if b["low"] <= df.at[self._long.extreme_i, "low"]:
                        self._long.extreme_i = i

                # C2：放空 — 收盤跌破前一根最低點
                if self._short.crossed and self._short.valid and order is None:
                    extreme_price = df.at[self._short.extreme_i, "high"]
                    if self._timing_ok(df, self._short.extreme_i, i, extreme_price):
                        broke_low = b["close"] < a["low"]
                        exception = (color == "black" and prev_run_color == "red"
                                     and prev_run_len >= p.five_bar_n
                                     and b["close"] < (a["open"] + a["close"]) / 2)
                        if broke_low or exception:
                            stop = (extreme_price + p.stop_tick if p.stop_mode == "recent_extreme"
                                    else float(b["close"]) * (1 + p.stop_pct / 100))
                            reason = "DMI石筍放空" + ("(五紅例外)" if exception and not broke_low else "")
                            order = Order.enter(Side.SHORT, stop=stop, reason=reason)
                            self._short = _Track()

                # C2'：買進 — 收盤突破前一根最高點
                if order is None and self._long.crossed and self._long.valid:
                    extreme_price = df.at[self._long.extreme_i, "low"]
                    if self._timing_ok(df, self._long.extreme_i, i, extreme_price):
                        broke_high = b["close"] > a["high"]
                        exception = (p.mirror_long_exception and color == "red" and prev_run_color == "black"
                                     and prev_run_len >= p.five_bar_n
                                     and b["close"] > (a["open"] + a["close"]) / 2)
                        if broke_high or exception:
                            stop = (extreme_price - p.stop_tick if p.stop_mode == "recent_extreme"
                                    else float(b["close"]) * (1 - p.stop_pct / 100))
                            reason = "DMI石筍買進" + ("(五黑例外)" if exception and not broke_high else "")
                            order = Order.enter(Side.LONG, stop=stop, reason=reason)
                            self._long = _Track()

        # 更新同色K連續根數狀態（供下一根的五色例外判斷使用）
        if color == prev_run_color:
            self._run_len = prev_run_len + 1
        else:
            self._run_color, self._run_len = color, (1 if color else 0)

        orders: list[Order] = []
        if ctx.pos is not None:
            ex = self._exit(ctx)
            if ex is not None:
                orders.append(ex)
        if order is not None and (ctx.pos is None or ctx.pos.side != order.side):
            orders.append(order)
        return orders or None
