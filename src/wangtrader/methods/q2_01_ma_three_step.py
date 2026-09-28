"""q2-01 均線三步驟買賣訊號（《期貨奇績2》第一章，p.1-39）。

規格文件：methods/期貨奇績2/q2-01-一分鐘穿越均線買賣策略.md
（書名雖稱「一分鐘」，本模組不綁定任何週期，所有門檻以點數／根數表示。）

訊號（p.3-4, 12, 16-17）：
  多方三步驟：
    C1  收盤突破均線，於均線上方形成第一個層級2轉折峰位。
    C2  折返段所有K線收盤皆不跌破均線（視為支撐）；折返段出現更高峰位時，C1 移到新峰位（p.12-13）；
        折返段中任一根收盤跌破均線 → 整段重新計數（p.12）。
    C3  收盤再度突破 C1 峰位，且須「無遮蔽」：訊號K線收盤高於「突破均線以來至前一根為止所有K線的最高點」
        （p.17：「高於標示1至標示3前一根之間任何一根K線最高點」，即只有影線突破峰位的K線也會遮蔽後續訊號）。
  空方三步驟 C1'/C2'/C3'：與多方鏡像（p.4，書中已明確列出鏡像敘述，非推論）。

層級2轉折峰谷點（p.4-5）：本模組自行實作（不與其他方法模組共用），
  支援單峰/雙峰/三峰（等高相鄰）與「變形」（中間夾一根較低K線）；峰谷點只用已右側 level 根確認者。

進場（p.3-4, 23）：C3/C3' 成立當根收盤進場；
  「隔日尾盤訊號延續」：訊號因收盤前時間濾網被忽略，若隔日開盤第一根與昨日最後一根有重疊（無真空缺口），
  沿用昨日訊號方向與停損，於隔日開盤第一根進場（p.23，簡化為以該根收盤價成交，因引擎進場一律採收盤價）。

停損（p.13-14）：買進 `收盤 − (10 + 收盤個位數)`；放空 `收盤 + (20 − 收盤個位數)`
  （p.14 原文明確列出，非鏡像推論；例：7665→7680、7701→7720、8636→8650）。個位數0時兩方向皆固定 20 點。

出場（p.28-51, 6.1-6.7）：反向三步驟訊號成立 → 立即平倉反手（p.20-21，由引擎的反手機制處理）；
  求不賠（breakeven_arm_points，預設15點，6.7）：獲利曾達此點數後跌破/漲破（回到）進場價 → 立即出場，
  優先於下列所有 exit_mode（書中明言不必等移動停利或停損觸發，p.32-33）。
  其餘擇一（exit_mode）：
    "ladder"（6.2，預設）：達初始獲利目標 profit_target(20) 後，K線「收盤創新高且最高點也創新高」（空方鏡像）
      才把停利線移到「新高 − trail_points」；觸及＝盤中價格跌破停利線達 trail_breach_points（書中「超過1點」）
      即出場（引擎的主動出場一律以當根收盤成交，書中為盤中觸價，屬簡化）。
    "sar"（6.3，沿用 core.exits.sar_exit，機制同書中）。
    "ma"（6.4）：達 profit_target 後先用 MA(ma_period) 為停利線；獲利達 ma_fast_arm_profit(50) 點後
      改用參數較小的 MA(ma_fast_period=10)；收盤突破/跌破所用均線即出場。
    "range"（6.5）：達 profit_target 後取最近 range_bars(15) 根K線高/低點供隔一根K線作停利參考，
      逐根重新計算；不可比原始停損更不利；觸及＝影線超過停利點 range_breach_points(1) 點即出場。
      區間預設以分鐘計（range_minutes=15，書中以 1 分K 描述「15 根」＝15 分鐘），取最近
      range_minutes 交易分鐘內的K線；range_minutes=None 或 time 非時間戳時退回 range_bars 根。
    "fixed"（6.6）：窄幅盤整適用，達 fixed_exit_points(10) 點固定獲利即出場，不用移動停利。
  時間停損（time_stop_bars／time_stop_minutes，預設皆關閉，p.22 書中為60根／約1小時）：持倉逾此根數
  （或分鐘，兩者皆設時以分鐘為準）仍無明顯獲利，出場。

過濾（p.18-19, 23-25）：
  F1 訊號K線漲跌幅 ≥ big_bar_points(15) → 忽略。
  F2 訊號收盤距「本段突破均線那根K線的收盤」> max_dev_from_break(60) → 忽略（p.18）；同一段（仍在均線同側）
     出現第二組三步驟時，起漲點仍是最初突破均線的位置，不是前一個訊號。
  F3 訊號收盤距平盤 > max_dev_from_prev_close(60, p.18) → 忽略（p.19圖1-17之90點僅為示範數值，非另訂門檻，已查原文確認）。
  F4 訊號K線漲跌幅 < min_bar_points(2) → 忽略。
  F5 no_entry_after：晚於此時刻不進場（預設 None 關閉，書中為收盤前30分鐘，p.23）。

不區隔週期：程式無任何 K 線週期常數；所有門檻皆為點數／根數參數。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time

import pandas as pd

from wangtrader.core import Context, Order, Side, Strategy
from wangtrader.core.exits import retrace_exit, sar_exit
from wangtrader.core.indicators import sar, sma

METHOD_ID = "q2-01"


# ---------- 層級2峰谷點（含變形），本模組私有實作，不與其他方法模組共用 ----------


@dataclass(frozen=True)
class _Pivot:
    index: int  # 峰谷所在K線（同高/低群組取最後一根）
    confirm: int  # 確認的K線（index + level）
    price: float
    kind: str  # "peak" | "trough"


_MAX_PLATEAU = 4  # 涵蓋單峰/雙峰/三峰及最多一根K線的「變形」凹陷（原圖1-2/1-3缺圖，依文字描述之合理上限，屬詮釋）


def _groups(vals, better) -> list[tuple[int, int]]:
    """把等高（低）相鄰、或夾一根較低K線的「變形」群組切出來，回傳 [(start,end)...]。"""
    n = len(vals)
    out = []
    j = 0
    while j < n:
        end = j
        dip_used = False
        k = j + 1
        while k < n and (k - j) < _MAX_PLATEAU:
            if vals[k] == vals[j]:
                end = k
                k += 1
            elif not dip_used and better(vals[j], vals[k]) and k + 1 < n and vals[k + 1] == vals[j]:
                dip_used = True
                end = k + 1
                k += 2
            else:
                break
        out.append((j, end))
        j = end + 1
    return out


def _find_level_pivots(high, low, level: int, kind: str) -> list[_Pivot]:
    """在單一交易日內找層級 level 的峰／谷點（含變形）。"""
    vals = high if kind == "peak" else low
    better = (lambda a, b: a > b) if kind == "peak" else (lambda a, b: a < b)
    out = []
    for s, e in _groups(vals, better):
        v = vals[s]
        left = vals[max(0, s - level):s]
        right = vals[e + 1:e + 1 + level]
        if len(right) < level:
            continue
        if any(not better(v, x) for x in left):
            continue
        if any(not better(v, x) for x in right):
            continue
        out.append(_Pivot(index=e, confirm=e + level, price=float(v), kind=kind))
    return out


def _pivots_by_session(df: pd.DataFrame, level: int) -> tuple[list[_Pivot], list[_Pivot]]:
    """全表峰谷點，逐交易日獨立計算（避免跨日誤判），index 為全表位置。"""
    peaks: list[_Pivot] = []
    troughs: list[_Pivot] = []
    for _, g in df.groupby("session", sort=False):
        off = g.index[0]
        h = g["high"].to_numpy(float)
        lo = g["low"].to_numpy(float)
        for p in _find_level_pivots(h, lo, level, "peak"):
            peaks.append(_Pivot(p.index + off, p.confirm + off, p.price, "peak"))
        for p in _find_level_pivots(h, lo, level, "trough"):
            troughs.append(_Pivot(p.index + off, p.confirm + off, p.price, "trough"))
    return peaks, troughs


def _group_by_confirm(pivots: list[_Pivot]) -> dict[int, list[_Pivot]]:
    out: dict[int, list[_Pivot]] = {}
    for p in pivots:
        out.setdefault(p.confirm, []).append(p)
    return out


def _trade_minutes(df: pd.DataFrame) -> pd.Series:
    """累計交易分鐘（供「原文以時間描述」的分鐘版參數用）：同一交易日內取相鄰K線 time 差；交易日第一根
    只計一根K線長（沿用之前最近一次的日內時間差，無則 0），不含休市時間，跨日計時與根數語意一致。
    只用當下及之前的時間戳；time 非時間戳時全為 NaN（呼叫端退回根數）。"""
    t = df["time"] if "time" in df.columns else None
    if t is None or not pd.api.types.is_datetime64_any_dtype(t):
        return pd.Series(float("nan"), index=df.index)
    step = t.diff().dt.total_seconds() / 60.0
    if "session" in df.columns:
        step = step.where(df["session"].eq(df["session"].shift()))
    return step.fillna(step.ffill()).fillna(0.0).cumsum()


def _elapsed(df: pd.DataFrame, a: int, b: int, minutes: float | None, bars: float | None) -> tuple[float, float | None]:
    """第 a 根到第 b 根的經過量與上限：minutes 有設且有交易分鐘欄（trade_min）時回傳（經過分鐘, minutes），
    否則退回（經過根數, bars）。"""
    if minutes is not None and "trade_min" in df.columns:
        m = df.at[b, "trade_min"] - df.at[a, "trade_min"]
        if m == m:
            return float(m), minutes
    return float(b - a), bars


def _digit_stop(side: Side, close_price: float, min_offset: float, integer_points: float) -> float:
    """個位數停損公式（p.13-14）：多＝收盤−(10+個位數)；空＝收盤+(20−個位數)（非鏡像，p.14原文明確列出）；
    整數價位（個位數0）兩方向皆固定 integer_points 點。"""
    digit = int(round(close_price)) % 10
    if digit == 0:
        pts = integer_points
    elif side == Side.LONG:
        pts = min_offset + digit
    else:
        pts = integer_points - digit
    return close_price - pts if side == Side.LONG else close_price + pts


@dataclass
class Params:
    ma_period: int = 30  # 均線週期，書中 MA30（p.2）
    pivot_level: int = 2  # 層級2轉折點（p.4-5）
    stop_min_offset: float = 10.0  # 停損公式固定部分（p.13）
    stop_integer_points: float = 20.0  # 整數價位固定停損點數（p.13）
    big_bar_points: float = 15.0  # F1：訊號K線漲跌幅上限（p.18）
    max_dev_from_break: float = 60.0  # F2：距均線起漲/跌位置上限（p.18）
    max_dev_from_prev_close: float = 60.0  # F3：距平盤上限（p.18正文60點；p.19舉例90點，見docstring）
    min_bar_points: float = 2.0  # F4：訊號K線漲跌幅下限（p.24-25）
    no_entry_after: time | None = None  # F5：晚於此時刻不進場（書中收盤前30分鐘，p.23），預設關閉
    carry_over_to_next_open: bool = True  # 隔日尾盤訊號延續進場（p.23）
    exit_mode: str = "ladder"  # "ladder" | "sar" | "ma" | "range" | "fixed" | "none"（p.28-51, 6.1-6.6）
    profit_target: float = 20.0  # 初始獲利目標（p.30, 38）
    trail_points: float = 20.0  # ladder：固定點數移動停利的回檔點數（p.30-31）
    trail_breach_points: float = 1.0  # ladder：觸及＝盤中跌破停利線達此點數（p.31「超過1點」）
    ma_fast_period: int = 10  # ma：獲利擴大後改用的較小均線週期（p.42，MA10）
    ma_fast_arm_profit: float = 50.0  # ma：獲利達此點數後由 MA(ma_period) 切換為 MA(ma_fast_period)（p.42）
    range_bars: int = 15  # range：區間高低點停利所取的K線根數（p.46-49，預設15）；range_minutes=None 時使用
    range_minutes: float | None = 15.0  # range：區間改以分鐘計（書中 1 分K「15 根」＝15 分鐘）；None 用 range_bars
    range_breach_points: float = 1.0  # range：觸及＝影線超過停利點此點數（p.47「超過1點」）
    fixed_exit_points: float = 10.0  # fixed：窄幅盤整固定點數出場（p.28，書中舉例10點）
    breakeven_arm_points: float | None = 15.0  # 求不賠：獲利曾達此點數後回到進場價即出場，優先於 exit_mode（p.32-33, 6.7）
    time_stop_bars: int | None = None  # 持倉逾此根數無明顯獲利，考慮離場（p.22）；門檻未量化，預設關閉
    time_stop_minutes: float | None = None  # 同上改以分鐘計（書中約1小時＝60），設定時優先於 time_stop_bars；預設關閉
    time_stop_min_profit: float = 0.0  # 搭配 time_stop_bars：獲利需 < 此值才觸發


class MAThreeStep(Strategy):
    method_id = METHOD_ID

    def __init__(self, **kw) -> None:
        self.p = Params(**kw)
        self._peaks_by_confirm: dict[int, list[_Pivot]] = {}
        self._troughs_by_confirm: dict[int, list[_Pivot]] = {}
        self._st: dict[int, dict[str, dict]] = {}
        self._pending_carry: dict | None = None  # {"side","stop","session"}

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["trade_min"] = _trade_minutes(df)
        df["ma"] = sma(df["close"], self.p.ma_period)
        df["ma_fast"] = sma(df["close"], self.p.ma_fast_period)
        s = sar(df)
        df["sar"], df["sar_trend"] = s["sar"], s["trend"]
        peaks, troughs = _pivots_by_session(df, self.p.pivot_level)
        self._peaks_by_confirm = _group_by_confirm(peaks)
        self._troughs_by_confirm = _group_by_confirm(troughs)
        return df

    # ---------- 狀態機 ----------

    def _fresh_side(self) -> dict:
        # break_i：本段突破均線的K線；max_high：突破以來至前一根為止的最高點（多；空方為最低點），供無遮蔽判斷
        return {"active": False, "break_i": None, "c1": None, "phase": "c1", "max_high": None}

    def _side_state(self, sess: int) -> dict[str, dict]:
        if sess not in self._st:
            self._st[sess] = {"LONG": self._fresh_side(), "SHORT": self._fresh_side()}
        return self._st[sess]

    def _step_side(self, side: Side, st: dict, df: pd.DataFrame, i: int) -> tuple[float, int] | None:
        """更新單一方向的三步驟狀態機，訊號成立時回傳 (c1_price, break_i)。"""
        close = df.at[i, "close"]
        ma = df.at[i, "ma"]
        if ma != ma:  # NaN
            return None
        if side == Side.LONG:
            above = close > ma
            pivots_by_confirm, better = self._peaks_by_confirm, (lambda a, b: a > b)
            wick = df.at[i, "high"]
        else:
            above = close < ma
            pivots_by_confirm, better = self._troughs_by_confirm, (lambda a, b: a < b)
            wick = df.at[i, "low"]

        if not above:
            if st["active"]:
                st.update(self._fresh_side())
            return None

        if not st["active"]:
            st["active"] = True
            st["break_i"] = i
            st["c1"] = None
            st["phase"] = "c1"
            st["max_high"] = wick
            return None

        # 無遮蔽判斷（p.17）：訊號收盤須高於突破均線以來（至前一根為止）所有K線的最高點；判斷完再納入本根
        unmasked = better(close, st["max_high"])
        st["max_high"] = wick if better(wick, st["max_high"]) else st["max_high"]

        new_pivots = [p for p in pivots_by_confirm.get(i, []) if p.index >= st["break_i"]]
        if st["phase"] == "c1":
            if new_pivots:
                st["c1"] = new_pivots[-1]
                st["phase"] = "c3"
            return None

        # phase == "c3"：折返段出現更高（低）峰谷位 → 移動 C1（p.12-13）
        better_pivots = [p for p in new_pivots if better(p.price, st["c1"].price)]
        if better_pivots:
            st["c1"] = better_pivots[-1]

        if better(close, st["c1"].price) and unmasked:
            c1_price, break_i = st["c1"].price, st["break_i"]
            # 訊號成立後，於同一段（仍在均線上/下方）繼續尋找下一組三步驟（每日訊號可多次，p.25）；
            # 起漲點（break_i）與最高點紀錄不重設：F2 仍以最初突破均線處計算（p.18），無遮蔽仍看全段。
            st["c1"] = None
            st["phase"] = "c1"
            return c1_price, break_i
        return None

    # ---------- 進出場 ----------

    def _stop(self, side: Side, close_price: float) -> float:
        return _digit_stop(side, close_price, self.p.stop_min_offset, self.p.stop_integer_points)

    def _ladder_exit(self, ctx: Context) -> Order | None:
        """固定點數移動停利（p.30-31）：達獲利目標後，K線「收盤創新高且最高點也創新高」才把停利線
        移到「新高 − trail_points」（空方鏡像）；觸及＝盤中跌破停利線達 trail_breach_points，當根收盤出場。"""
        pos = ctx.pos
        p = self.p
        if pos is None or ctx.i <= pos.entry_i:
            return None
        b = ctx.bar()
        long = pos.side == Side.LONG
        # 持倉以來的最高（低）收盤與最高（低）點，初始為進場K線
        if "hc" not in pos.meta:
            e = ctx.df.iloc[pos.entry_i]
            pos.meta["hc"], pos.meta["hh"] = float(e["close"]), float(e["high"] if long else e["low"])
        hc, hh = pos.meta["hc"], pos.meta["hh"]
        if long:
            new_high = b["close"] > hc and b["high"] > hh
            pos.meta["hc"], pos.meta["hh"] = max(hc, b["close"]), max(hh, b["high"])
        else:
            new_high = b["close"] < hc and b["low"] < hh
            pos.meta["hc"], pos.meta["hh"] = min(hc, b["close"]), min(hh, b["low"])
        if pos.max_profit() < p.profit_target:
            return None
        key = "trail"
        if new_high:
            lvl = (b["high"] - p.trail_points) if long else (b["low"] + p.trail_points)
            pos.meta[key] = (max if long else min)(pos.meta.get(key, lvl), lvl)
        if key not in pos.meta:
            return None
        trigger = pos.meta[key] - p.trail_breach_points if long else pos.meta[key] + p.trail_breach_points
        if (b["low"] <= trigger) if long else (b["high"] >= trigger):
            return Order.exit("固定點數移動停利")
        return None

    def _ma_tier_exit(self, ctx: Context) -> Order | None:
        """均線移動停利（p.42-45，6.4）：達獲利目標後先用 MA(ma_period) 為停利線；
        獲利達 ma_fast_arm_profit 點後改用較小參數 MA(ma_fast_period)；收盤突破/跌破所用均線即出場。"""
        pos, p = ctx.pos, self.p
        if pos is None or ctx.i <= pos.entry_i or pos.max_profit() < p.profit_target:
            return None
        col = "ma_fast" if pos.max_profit() >= p.ma_fast_arm_profit else "ma"
        b = ctx.bar()
        ma = b[col]
        if ma != ma:  # NaN
            return None
        if pos.side == Side.LONG and b["close"] < ma:
            return Order.exit("均線停利")
        if pos.side == Side.SHORT and b["close"] > ma:
            return Order.exit("均線停利")
        return None

    def _range_exit(self, ctx: Context) -> Order | None:
        """區間高低點停利（p.46-51，6.5）：達獲利目標後，取最近 range_bars 根K線（不含本根）的高/低點
        供本根作停利參考，逐根重新計算；不可比原始停損更不利；觸及＝影線超過停利點 range_breach_points 點。"""
        pos, p, df, i = ctx.pos, self.p, ctx.df, ctx.i
        if pos is None or ctx.i <= pos.entry_i or pos.max_profit() < p.profit_target:
            return None
        long = pos.side == Side.LONG
        if _elapsed(df, i, i, p.range_minutes, None)[1] is not None:
            lo_i = i  # 分鐘版：取距本根 range_minutes 交易分鐘以內的K線（不早於進場K線）
            while lo_i > pos.entry_i and _elapsed(df, lo_i - 1, i, p.range_minutes, None)[0] <= p.range_minutes:
                lo_i -= 1
        else:
            lo_i = max(pos.entry_i, i - p.range_bars)
        window = df.iloc[lo_i:i]
        if window.empty:
            return None
        lvl = float(window["low"].min()) if long else float(window["high"].max())
        if pos.stop is not None:  # 不可比原始停損更不利（p.48）
            lvl = max(lvl, pos.stop) if long else min(lvl, pos.stop)
        b = df.iloc[i]
        trigger = lvl - p.range_breach_points if long else lvl + p.range_breach_points
        if (b["low"] <= trigger) if long else (b["high"] >= trigger):
            return Order.exit("區間高低點停利")
        return None

    def _fixed_points_exit(self, ctx: Context) -> Order | None:
        """固定點數出場（p.28，6.6）：窄幅盤整適用，達 fixed_exit_points 點即出場，不用移動停利。"""
        pos, p = ctx.pos, self.p
        if pos is None or ctx.i <= pos.entry_i:
            return None
        if pos.profit(ctx.bar()["close"]) >= p.fixed_exit_points:
            return Order.exit("固定點數出場")
        return None

    def _time_stop(self, ctx: Context) -> Order | None:
        pos, p = ctx.pos, self.p
        if pos is None or (p.time_stop_bars is None and p.time_stop_minutes is None):
            return None
        held, lim = _elapsed(ctx.df, pos.entry_i, ctx.i, p.time_stop_minutes, p.time_stop_bars)
        if lim is None:
            return None
        if held >= lim and pos.profit(ctx.bar()["close"]) < p.time_stop_min_profit:
            return Order.exit("持倉過久出場")
        return None

    def _passes_filters(self, df: pd.DataFrame, i: int, c1_price: float, break_i: int) -> bool:
        p = self.p
        b = df.iloc[i]
        bar_pts = abs(b["close"] - b["open"])
        if bar_pts >= p.big_bar_points:  # F1
            return False
        if bar_pts < p.min_bar_points:  # F4
            return False
        if abs(b["close"] - df.at[break_i, "close"]) > p.max_dev_from_break:  # F2
            return False
        pc = b["prev_close"]
        if pd.notna(pc) and abs(b["close"] - pc) > p.max_dev_from_prev_close:  # F3
            return False
        return True

    def on_bar(self, ctx: Context):
        p, df, i = self.p, ctx.df, ctx.i
        sess = df.at[i, "session"]
        st = self._side_state(sess)
        orders: list[Order] = []

        # 隔日尾盤訊號延續進場（p.23）：本交易日第一根，檢查與昨日尾盤有無重疊
        if p.carry_over_to_next_open and self._pending_carry is not None and df.at[i, "bar_no"] == 0:
            carry = self._pending_carry
            self._pending_carry = None
            prev = df.iloc[i - 1] if i > 0 else None
            if prev is not None and df.at[i, "low"] <= prev["high"] and df.at[i, "high"] >= prev["low"]:
                orders.append(Order.enter(carry["side"], stop=carry["stop"], reason="隔日延續進場"))

        # 出場（若持倉）
        if ctx.pos is not None:
            ex = None
            if p.breakeven_arm_points is not None:  # 求不賠，優先於下列所有出場方式（p.32-33, 6.7）
                ex = retrace_exit(ctx, p.breakeven_arm_points, 0.0)
            if ex is None:
                ex = {
                    "ladder": self._ladder_exit,
                    "sar": lambda c: sar_exit(c, p.profit_target),
                    "ma": self._ma_tier_exit,
                    "range": self._range_exit,
                    "fixed": self._fixed_points_exit,
                    "none": lambda c: None,
                }[p.exit_mode](ctx)
            if ex is None:
                ex = self._time_stop(ctx)
            if ex is not None:
                orders.append(ex)

        long_hit = self._step_side(Side.LONG, st["LONG"], df, i)
        short_hit = self._step_side(Side.SHORT, st["SHORT"], df, i)

        for side, hit, name in ((Side.LONG, long_hit, "均線三步驟買進"), (Side.SHORT, short_hit, "均線三步驟放空")):
            if hit is None:
                continue
            c1_price, break_i = hit
            close = df.at[i, "close"]
            if not self._passes_filters(df, i, c1_price, break_i):
                continue
            if p.no_entry_after is not None and hasattr(df.at[i, "time"], "time") and df.at[i, "time"].time() > p.no_entry_after:
                stop = self._stop(side, close)
                if p.carry_over_to_next_open:
                    self._pending_carry = {"side": side, "stop": stop, "session": sess}
                continue
            stop = self._stop(side, close)
            orders.append(Order.enter(side, stop=stop, reason=name))

        return orders or None
