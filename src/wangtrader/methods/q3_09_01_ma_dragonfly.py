"""q3-09-01 均線蜻蜓點水（《期貨奇績3》第九章，p.189-204）。

規格文件：methods/期貨奇績3/q3-09-01-均線蜻蜓點水.md

訊號（p.190-191）：均線（MA10）朝上（或朝下）行進中，A棒單一根K線收盤短暫跌破（或突破）均線，
  只要均線本身方向未因此改變，B棒（緊接下一根）立即收盤收回均線另一側，即為跟隨原趨勢的
  進場訊號：
  多方：C1 均線朝上；C2 A棒黑K收盤跌破MA10；C3 跌破當下均線未走平/反轉向下（以均線自身斜率
    判斷，非以價格是否穿越均線判斷，見下方實作說明）；C4 B棒收紅，收盤重新站上MA10，B棒收盤
    即訊號成立點；C5 訊號發生前價格波段峰點距均線轉折點（均線谷點/上彎中點）>=20點；C6 跌破/
    收回僅涉及A、B恰好2根K線（本模組的訊號定義本身即要求「A棒之後緊接B棒」，故C6「穿越均線
    不超過1根」已內建於此嚴格的2棒相鄰定義中，不另立獨立濾網，見§實作說明）。
  空方：C1'-C6' 為多方鏡像（S4均線朝下為推論，依C3對稱）。
進場（p.190-198）：以B/D棒收盤價進場。若訊號K線本身漲跌幅（|收盤-開盤|）超過
  large_bar_threshold（預設30點，p.198）屬「大K線」：large_bar_mode="wait"（預設）等拉回/反彈到
  「訊號K低點(多)/高點(空) ± stop_points」再補進場，停損設在該極端點（p.198「停損儘量控制在買訊K線
  的最低點，或空訊K線的最高點」）；"midpoint" 直接進場，停損設於該K線實體中點，但距進場價最多
  stop_points（p.198「設在大K線實體中點或直接設20點停損…最大虧損仍控制在20點」）。
停損（p.193, 198）：進場價 ∓ stop_points（預設20，p.193「設好20點停損位置」、p.198「最大虧損仍
  控制在20點」）。
出場（p.191, 193, 195）：僅「五黑遇首紅／五紅遇首黑」平倉（use_five_reversal，本模組私有簡化
  實作，定義同 q3-06，不 import，省略C2b回溯總長度例外）；書中本節未另訂其他停利機制，
  不自行發明（見docstring不做事項）。
過濾：
  F1 均線本波方向持續 <= min_trend_bars（預設3）根 -> 不宜操作（p.199）。
  F2 距離上一次跌破/突破（含未成立的蜻蜓點水）不足 region_min_bars（預設10）根 -> 非本波段
     第一次回測，忽略（p.199）。
  F3/C5 峰谷點距均線轉折點 < min_turn_dist（預設20）-> 忽略（p.192-193, 199, 203-204）。
  F4 當日均線方向反覆翻轉次數超過 max_trend_flips_per_session -> 視為當日均線不具支撐/壓力
     效果，當日忽略所有訊號（p.201-202）。本模組以「當日MA斜率翻轉次數」作為可量化代理指標，
     屬推論近似（書中僅提供定性描述，未給量化門檻），依規範推論規則預設關閉（None），可自行設定
     例如 4 啟用。
  F5 A棒（跌破/突破均線的K線）若同時與其前一根構成逆向極端訊號（頂雙黑/底雙紅，本模組私有
     偵測 `_extreme_reversal_side`）-> 忽略本順向蜻蜓點水訊號，逆向優先（p.200-201，圖9-11）。
  F6 no_entry_after：時間晚於此不做（p.203，書中「距收盤不足1小時」以絕對時間門檻表示，
     預設None關閉，同 q3-01 F5 慣例）。
  F7=C6，已內建於訊號定義，見上方。

不做／無法實作（見模組末待確認事項）：
  停損後是否反手：本節（均線篇）未明文重述，僅第二節「平盤蜻蜓點水」有完整敘述，不可跨小節
     套用，本模組不實作反手。
  折返/移動停利、SAR等：本節未提及，不自行發明，僅提供出場為停損與五黑遇首紅/五紅遇首黑。

週期：不限。所有門檻以點數／根數表示。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time

import pandas as pd

from wangtrader.core import Context, Order, Side, Strategy
from wangtrader.core.bars import is_extreme_position
from wangtrader.core.indicators import sma

METHOD_ID = "q3-09-01"


@dataclass
class Params:
    ma_period: int = 10  # MA10（p.189）
    stop_points: float = 20.0  # p.193, 198
    large_bar_threshold: float = 30.0  # p.198
    large_bar_mode: str = "wait"  # "wait" | "midpoint"
    max_wait: int = 10  # 補進場等待根數（書中未載明確切根數，沿用慣例，待確認）
    min_trend_bars: int = 3  # F1（p.199）
    min_turn_dist: float = 20.0  # F3/C5（p.192-193, 199, 203-204）
    region_min_bars: int = 10  # F2（p.199）
    max_trend_flips_per_session: int | None = None  # F4（推論代理指標，預設關閉，p.201-202）
    skip_on_opposite_extreme: bool = True  # F5（p.200-201）
    extreme_range: float = 30.0
    extreme_from_prev_close: float = 40.0
    no_entry_after: time | None = None  # F6（p.203）
    use_five_reversal: bool = True  # 出場（p.191, 193, 195）
    five_min_bars: int = 5
    five_min_points: float = 40.0
    five_wick_max: float = 5.0


class MaDragonfly(Strategy):
    method_id = METHOD_ID

    def __init__(self, **kw) -> None:
        self.p = Params(**kw)

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        p = self.p
        df = df.copy()
        df["ma"] = sma(df["close"], p.ma_period)

        n = len(df)
        close = df["close"].to_numpy(float)
        open_ = df["open"].to_numpy(float)
        high = df["high"].to_numpy(float)
        low = df["low"].to_numpy(float)
        ma = df["ma"].to_numpy(float)
        sess = df["session"].to_numpy()

        sig_side = [0] * n
        signal_ext = [float("nan")] * n

        trend: int | None = None
        turn_i = -1
        turn_price = float("nan")
        peak = float("nan")
        is_breach_prev = False
        last_breach_i = -10**9
        cur_sess = None
        flips_this_session = 0

        for i in range(n):
            if cur_sess is None or sess[i] != cur_sess:
                cur_sess = sess[i]
                flips_this_session = 0
            if i == 0 or ma[i] != ma[i] or ma[i - 1] != ma[i - 1]:
                is_breach_prev = False
                continue
            cur_dir = 1 if ma[i] > ma[i - 1] else (-1 if ma[i] < ma[i - 1] else trend)
            if cur_dir is None:
                is_breach_prev = False
                continue

            prior_peak = peak
            new_trend = cur_dir != trend
            if new_trend:
                trend = cur_dir
                turn_i = i - 1
                turn_price = ma[i - 1]
                peak = high[i] if trend == 1 else low[i]
                last_breach_i = -10**9
                is_breach_prev = False
                flips_this_session += 1
            else:
                peak = max(peak, high[i]) if trend == 1 else min(peak, low[i])

            if (
                not new_trend
                and is_breach_prev
                and sess[i - 1] == sess[i]
                and (p.max_trend_flips_per_session is None or flips_this_session <= p.max_trend_flips_per_session)
            ):
                a = i - 1
                if trend == 1:
                    pattern_ok = close[a] < open_[a] and close[i] > open_[i] and close[i] > ma[i]
                else:
                    pattern_ok = close[a] > open_[a] and close[i] < open_[i] and close[i] < ma[i]
                if pattern_ok:
                    bars_since_turn = a - turn_i
                    dist = (prior_peak - turn_price) if trend == 1 else (turn_price - prior_peak)
                    gap_ok = (a - last_breach_i) >= p.region_min_bars
                    if bars_since_turn > p.min_trend_bars and dist >= p.min_turn_dist and gap_ok:
                        # F5：逆向極端訊號（如頂雙黑/底雙紅）與 A 棒（跌破/突破均線的那根K線）
                        # 同時成立時，逆向優先，本順向訊號忽略（p.200-201，圖9-11：AB形成頂雙黑，
                        # B同時跌破均線，隔根C收回均線的蜻蜓點水買訊須忽略）。
                        rev = _extreme_reversal_side(df, a, p.extreme_range, p.extreme_from_prev_close)
                        if not (p.skip_on_opposite_extreme and rev is not None and int(rev) != trend):
                            sig_side[i] = trend
                            signal_ext[i] = low[i] if trend == 1 else high[i]

            is_breach_i = (trend == 1 and close[i] < ma[i]) or (trend == -1 and close[i] > ma[i])
            if not new_trend and is_breach_prev:
                last_breach_i = i - 1
            is_breach_prev = is_breach_i

        df["sig_side"] = sig_side
        df["signal_ext"] = signal_ext
        return df

    def on_bar(self, ctx: Context):
        p, df, i = self.p, ctx.df, ctx.i

        if ctx.pos is not None:
            if p.use_five_reversal:
                sig = _five_reversal_exhaustion(df, i, p.five_min_bars, p.five_min_points, p.five_wick_max)
                if sig == 1 and ctx.pos.side == Side.LONG:
                    return [Order.exit("五紅遇首黑")]
                if sig == -1 and ctx.pos.side == Side.SHORT:
                    return [Order.exit("五黑遇首紅")]
            return None

        side_code = df.at[i, "sig_side"]
        if side_code == 0:
            return None
        b = df.iloc[i]
        if p.no_entry_after is not None and hasattr(b["time"], "time") and b["time"].time() > p.no_entry_after:
            return None
        side = Side.LONG if side_code == 1 else Side.SHORT
        ext = float(b["signal_ext"])
        c = float(b["close"])
        name = "均線蜻蜓點水買訊" if side == Side.LONG else "均線蜻蜓點水空訊"
        is_large = abs(c - b["open"]) > p.large_bar_threshold
        if not is_large:
            # 停損 20 點（p.193, 198）：以進場價（訊號K收盤）為基準
            stop = c - p.stop_points if side == Side.LONG else c + p.stop_points
            return [Order.enter(side, stop=stop, reason=name)]
        if p.large_bar_mode == "midpoint":
            # 大K線直接進場：停損設實體中點，但最大虧損仍以 stop_points 為上限（p.198）
            mid = (float(b["open"]) + c) / 2.0
            stop = max(mid, c - p.stop_points) if side == Side.LONG else min(mid, c + p.stop_points)
            return [Order.enter(side, stop=stop, reason=name + "(大K線)")]
        # 大K線補進場：等折返到「極端點 ± stop_points」，停損設在訊號K極端點（p.198）
        limit = ext + p.stop_points * int(side)
        return [Order.enter_limit(side, limit=limit, expire=p.max_wait, stop=ext, reason=name + "(補進場)")]


def _extreme_reversal_side(
    df: pd.DataFrame, i: int, extreme_range: float = 30.0, extreme_from_prev_close: float = 40.0
) -> Side | None:
    """（本模組私有）頂雙黑／底雙紅簡化偵測，僅用於判斷是否與逆向極端訊號衝突（p.200-201，F5）。
    定義與 q3-01 相同但獨立實作，不 import q3-01 模組。"""
    if i < 1:
        return None
    a, b = df.iloc[i - 1], df.iloc[i]
    if a["session"] != b["session"]:
        return None
    if not is_extreme_position(df, i, extreme_range, extreme_from_prev_close):
        return None
    if a["close"] < a["open"] and a["high"] >= a["sess_high"] and b["close"] < b["open"] and b["close"] < a["low"] and b["high"] <= a["high"]:
        return Side.SHORT
    if a["close"] > a["open"] and a["low"] <= a["sess_low"] and b["close"] > b["open"] and b["close"] > a["high"] and b["low"] >= a["low"]:
        return Side.LONG
    return None


def _five_reversal_exhaustion(
    df: pd.DataFrame, i: int, min_bars: int = 5, min_points: float = 40.0, wick_max: float = 5.0
) -> int:
    """（本模組私有）簡化版「連五黑遇首紅／連五紅遇首黑」偵測，僅用於既有部位出場參考（q3-06）。
    回傳 1：五紅遇首黑（多單出場參考）；-1：五黑遇首紅（空單出場參考）；0：不成立。
    簡化：不含 q3-06 C2b「回溯更早連續同色K總長度」的例外規則。"""
    if i < min_bars:
        return 0
    close = df["close"].to_numpy(float)
    open_ = df["open"].to_numpy(float)
    j = i - 1
    if close[j] > open_[j]:
        color = 1
    elif close[j] < open_[j]:
        color = -1
    else:
        return 0
    k = j
    while (
        k - 1 >= 0
        and df.at[k - 1, "session"] == df.at[j, "session"]
        and ((close[k - 1] > open_[k - 1]) if color == 1 else (close[k - 1] < open_[k - 1]))
    ):
        k -= 1
    if j - k + 1 < min_bars:
        return 0
    last, bi = df.iloc[j], df.iloc[i]
    if last["session"] != bi["session"]:
        return 0
    if color == 1:
        rng = last["high"] - df.at[k, "low"]
        if rng < min_points or last["high"] < last["sess_high"]:
            return 0
        wick = last["high"] - max(last["open"], last["close"])
        body = abs(last["close"] - last["open"])
        if wick > wick_max and (body == 0 or wick > body / 5):
            return 0
        if not (bi["close"] < bi["open"]) or bi["high"] > last["high"] or bi["close"] < last["low"]:
            return 0
        return 1
    else:
        rng = df.at[k, "high"] - last["low"]
        if rng < min_points or last["low"] > last["sess_low"]:
            return 0
        wick = min(last["open"], last["close"]) - last["low"]
        body = abs(last["close"] - last["open"])
        if wick > wick_max and (body == 0 or wick > body / 5):
            return 0
        if not (bi["close"] > bi["open"]) or bi["low"] < last["low"] or bi["close"] > last["high"]:
            return 0
        return -1
