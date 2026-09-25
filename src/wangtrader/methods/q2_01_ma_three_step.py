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

停損（p.13）：`收盤 − (10 + 收盤個位數)`（多）；整數價位（個位數0）固定 20 點。
  空方鏡像：`收盤 + (10 + 個位數)`（（推論）書中僅明確給出多方公式，p.13）。

出場（p.30-31, 38-39）：達初始獲利目標 20 點後，
  固定點數移動停利（exit_mode="ladder"）：K線「收盤創新高（高於持倉以來最高收盤）且最高點也創新高」才把停利線
  移到「新高 − trail_points」（空方鏡像）；觸及＝盤中價格跌破停利線達 trail_breach_points（書中「超過1點」）即出場
  （引擎的主動出場一律以當根收盤成交，與其他方法一致；書中為盤中觸價，屬簡化）。
  或 SAR 移動停利（exit_mode="sar"，沿用 core.exits.sar_exit，機制與書中 6.3 節相同）。
  反向三步驟訊號成立 → 立即平倉反手（p.20-21，由引擎的反手機制處理）。

過濾（p.18-19, 23-25）：
  F1 訊號K線漲跌幅 ≥ big_bar_points(15) → 忽略。
  F2 訊號收盤距「本段突破均線那根K線的收盤」> max_dev_from_break(60) → 忽略（p.18）；同一段（仍在均線同側）
     出現第二組三步驟時，起漲點仍是最初突破均線的位置，不是前一個訊號。
  F3 訊號收盤距平盤 > max_dev_from_prev_close(預設60，p.18；p.19另舉90點例，兩數並陳，見待確認事項) → 忽略。
  F4 訊號K線漲跌幅 < min_bar_points(2) → 忽略。
  F5 no_entry_after：晚於此時刻不進場（預設 None 關閉，書中為收盤前30分鐘，p.23）。

不區隔週期：程式無任何 K 線週期常數；所有門檻皆為點數／根數參數。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time

import pandas as pd

from wangtrader.core import Context, Order, Side, Strategy
from wangtrader.core.exits import sar_exit
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


def _digit_stop(side: Side, close_price: float, min_offset: float, integer_points: float) -> float:
    """個位數停損公式（p.13）：停損 = 收盤 -/+ (10 + 個位數)；整數價位固定 integer_points 點。"""
    digit = int(round(close_price)) % 10
    pts = integer_points if digit == 0 else min_offset + digit
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
    exit_mode: str = "ladder"  # "ladder" | "sar" | "none"
    profit_target: float = 20.0  # 初始獲利目標（p.30, 38）
    trail_points: float = 20.0  # 固定點數移動停利的回檔點數（p.30-31）
    trail_breach_points: float = 1.0  # 停利觸及＝盤中跌破停利線達此點數（p.31「超過1點」；整數價位下取≥1點的讀法）
    time_stop_bars: int | None = None  # 持倉逾此根數無明顯獲利，考慮離場（p.22）；門檻未量化，預設關閉
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
        df["ma"] = sma(df["close"], self.p.ma_period)
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

    def _time_stop(self, ctx: Context) -> Order | None:
        pos, p = ctx.pos, self.p
        if pos is None or p.time_stop_bars is None:
            return None
        if ctx.i - pos.entry_i >= p.time_stop_bars and pos.profit(ctx.bar()["close"]) < p.time_stop_min_profit:
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
            if p.exit_mode == "ladder":
                ex = self._ladder_exit(ctx)
            elif p.exit_mode == "sar":
                ex = sar_exit(ctx, p.profit_target)
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
