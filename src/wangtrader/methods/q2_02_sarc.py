"""q2-02 SAR轉化買賣訊號（《期貨奇績2》第二章，p.67-91；書中章名原文無「C」字，見文件12節）。

規格文件：methods/期貨奇績2/q2-02-SARC轉化買賣訊號.md

與 q2-01（均線三步驟）同樣的「突破→折返→再突破」三步驟骨架，但以 SAR 取代均線：
  - 「突破」改為 SAR 方向翻轉（core.indicators.sar 的翻轉條件本就是「影線觸價」，見該函式；
    因此 sar_trend 連續維持多／空方向，即等同書中「折返過程影線不觸及SAR，觸及即翻轉重新計數」）。
  - 訊號K線收盤仍為 C3 確認條件，「無遮蔽」判斷沿用影線極值（與 q2-01 3.3.3 相同定義）。

訊號（p.67-69）：
  買進三步驟：
    C1 K線影線向上穿越SAR（sar_trend 由空翻多），形成第一個層級2轉折峰點(1)（可為翻轉當根本身，p.68）。
    C2 折返過程所有K線影線皆未觸及SAR（等同 sar_trend 連續維持多方；觸及即翻轉、該次折返失敗須重新計數）。
    C3 其後K線收盤向上突破峰點(1)，且為「無遮蔽」收盤。
  放空三步驟 C1'/C2'/C3'：與買進鏡像（p.67-69，書中已明確列出鏡像敘述，非推論）。

層級2轉折峰谷點：本模組自行實作（不與其他方法模組共用），定義同第一章 q2-01 3.1節。

水平濾網移動上限（p.72-73，3.4）：因遮蔽而需移動峰(谷)濾網時，最初水平線加移動次數以三條為限
  （即 max_pivot_moves=2，最多移動兩次）；超過仍未收盤突破，放棄此候選、重新尋找新的峰(谷)點(1)
  （不影響仍在進行中的 SAR 方向段本身，只是放棄目前追蹤的候選點）。

潛在峰谷點補進場（p.80，3.3）：本模組的簡化三步驟模型（同 q2-01）本就不要求折返段內先出現具體、
  已完成右側確認的點(2)——C2 只檢查「影線未觸及SAR」，C3 的收盤突破即可成立，天然已達成此規則
  「不必等右側正式確認」的效果，無需另立分支（與 q2-01 §4 相同簡化，見該模組 docstring）。

進場（p.67-68）：C3/C3' 成立當根K線收盤進場。書中未見「隔日尾盤延續」的對應敘述（見文件12節待確認），
  本模組不實作跨日延續，亦無收盤前時間濾網。

停損（p.72-73）：與第一章相同公式，本章原文重新明確列出（非鏡像推論）：
  買進 `收盤 − (10 + 收盤個位數)`；放空 `收盤 + (20 − 收盤個位數)`；整數價位（個位數0）兩方向皆固定20點。

出場（p.79, 81-86，6.1-6.5）：反向三步驟訊號成立 → 立即平倉反手（p.70, 74，由引擎反手機制處理）；
  求不賠（breakeven_exit，預設開啟，6.4）：達 profit_target 後獲利回落至進場價（或以下）→ 立即出場
  （書中原文為「宜選擇小賺或小賠一二點平倉」，簡化為與其他章節一致的「回到進場價」，屬簡化詮釋）。
  其餘可擇一（exit_mode）：
    "ladder"（6.1，預設）：達 profit_target 後，收盤與最高（低）點同時創新高（低）才把停利線移到
      「新高 − trail_points」（空方鏡像）；觸及＝盤中跌破停利線達 trail_breach_points 點即出場。
    "sar"（6.3，沿用 core.exits.sar_exit，機制同書中）。
    "range"（6.2）：達 profit_target 後取最近 range_bars(20) 根K線高/低點供隔一根K線作停利參考，
      機制同 q2-01 6.5節（本模組自行複製，不 import q2-01）。
    "none"。
  時間停損（time_stop_bars，預設關閉，p.79 書中約30-60分鐘）：持倉逾此根數仍無明顯獲利，出場。

過濾（p.75-79, 91）：
  F1 (0)到(3)距離 > max_signal_points(50) → 忽略；(0)＝跌破/突破SAR前最近的層級2峰(谷)點（p.75, 77）。
     F4（p.91「幅度過大的N型忽略」）與F1同一原則的重申，書中原文明言，不另立規則。
  F2 同向趨勢中僅取第一個訊號；除非與前一同向訊號之間曾出現 same_dir_min_swing(30) 點以上的單筆擺動
     （以兩訊號間K線高低點範圍量測，屬合理量化詮釋）或三段式反向擺動（後者未實作，見模組末待確認事項；
     只實作可量化的30點子條件，使本濾網最多只會更保守篩掉合規訊號，不會誤放行不合規訊號）。

不區隔週期：無任何 K 線週期常數；所有門檻皆為點數／根數參數。

無法實作／需人工決定：
  - F3（p.76：訊號因反覆重新計數拖延過久，確認時已偏離起漲點約90點且逾1小時）：書中僅以範例呈現，
    未給精確點數/時間門檻，且與F1(50點)、F4（同F1）精神重疊，故不另立獨立規則。
  - F2 例外情形的「三段式反向擺動」子條件未實作（僅實作可量化的30點單筆擺動子條件，見上）。
  - 6.5 每日操作以3次為宜、單趟獲利達30點以上可收工等，屬經驗提醒非可判斷規則，未實作。
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from wangtrader.core import Context, Order, Side, Strategy
from wangtrader.core.exits import retrace_exit, sar_exit
from wangtrader.core.indicators import sar

METHOD_ID = "q2-02"


# ---------- 層級2轉折峰谷點（含變形），本模組私有實作，不與其他方法模組共用 ----------


@dataclass(frozen=True)
class _Pivot:
    index: int
    confirm: int
    price: float
    kind: str  # "peak" | "trough"


_MAX_PLATEAU = 4  # 單峰/雙峰/三峰及最多一根K線的「變形」凹陷之合理上限（原圖缺，屬詮釋，同q2-01/q2-03-01）


def _groups(vals, better) -> list[tuple[int, int]]:
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
    vals = high if kind == "peak" else low
    better = (lambda a, b: a > b) if kind == "peak" else (lambda a, b: a < b)
    out = []
    for s, e in _groups(vals, better):
        v = vals[s]
        left = vals[max(0, s - level):s]
        right = vals[e + 1:e + 1 + level]
        if len(right) < level:
            continue
        if any(not better(v, x) for x in left) or any(not better(v, x) for x in right):
            continue
        out.append(_Pivot(index=e, confirm=e + level, price=float(v), kind=kind))
    return out


def _pivots_by_session(df: pd.DataFrame, level: int) -> tuple[list[_Pivot], list[_Pivot]]:
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
    """個位數停損公式（與第一章均線策略相同，p.72-73；本模組自行複製）：
    多＝收盤−(10+個位數)；空＝收盤+(20−個位數)（非鏡像，p.14/72-73原文明確列出）；整數價位固定 integer_points 點。"""
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
    pivot_level: int = 2  # 層級2轉折點（p.4-5，第一章沿用）
    stop_min_offset: float = 10.0  # 停損公式固定部分（p.72-73）
    stop_integer_points: float = 20.0  # 整數價位固定停損點數（p.72-73）
    max_pivot_moves: int = 2  # 3.4：濾網最多移動次數（含首條共3條線），超過放棄候選（p.72-73）
    max_signal_points: float = 50.0  # F1：(0)到(3)距離上限（p.75, 77）
    same_dir_min_swing: float = 30.0  # F2：同向重複訊號需夾此點數以上單筆擺動才可再進場（p.77-79）
    exit_mode: str = "ladder"  # "ladder" | "sar" | "range" | "none"（6.1-6.3）
    profit_target: float = 20.0  # 初始獲利目標（p.81, 85）
    trail_points: float = 20.0  # ladder：固定點數移動停利的回檔點數（p.81-83）
    trail_breach_points: float = 1.0  # ladder：觸及＝盤中跌破停利線達此點數
    range_bars: int = 20  # range：區間高低點停利所取的K線根數（p.84，本章20根）
    range_breach_points: float = 1.0  # range：觸及＝影線超過停利點此點數
    breakeven_exit: bool = True  # 求不賠：達 profit_target 後回到進場價即出場（p.82，簡化見docstring）
    time_stop_bars: int | None = None  # 持倉逾此根數無明顯輸贏，考慮離場（p.79）；門檻未量化，預設關閉
    time_stop_min_profit: float = 0.0  # 搭配 time_stop_bars：獲利需 < 此值才觸發


class SARC(Strategy):
    method_id = METHOD_ID

    def __init__(self, **kw) -> None:
        self.p = Params(**kw)
        self._peaks_by_confirm: dict[int, list[_Pivot]] = {}
        self._troughs_by_confirm: dict[int, list[_Pivot]] = {}
        self._st: dict[int, dict[str, dict]] = {}
        self._last_signal_i: dict[int, dict[str, int | None]] = {}  # session -> {"LONG":i,"SHORT":i}

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        s = sar(df)
        df["sar"], df["sar_trend"] = s["sar"], s["trend"]
        peaks, troughs = _pivots_by_session(df, self.p.pivot_level)
        self._peaks_by_confirm = _group_by_confirm(peaks)
        self._troughs_by_confirm = _group_by_confirm(troughs)
        return df

    # ---------- 狀態機（每交易日各自獨立） ----------

    def _fresh_side(self) -> dict:
        return {
            "active": False, "break_i": None, "c0": None, "c1": None,
            "phase": "c1", "max_high": None, "move_count": 0,
        }

    def _side_state(self, sess: int) -> dict[str, dict]:
        if sess not in self._st:
            self._st[sess] = {"LONG": self._fresh_side(), "SHORT": self._fresh_side()}
        return self._st[sess]

    def _find_c0(self, side: Side, i: int) -> _Pivot | None:
        """(0)＝跌破/突破SAR前最近的層級2峰(空)/谷(多)點，只用已確認者（p.75, 77）。"""
        pivots = self._troughs_by_confirm if side == Side.LONG else self._peaks_by_confirm
        cand = [p for lst in pivots.values() for p in lst if p.confirm <= i]
        return max(cand, key=lambda p: p.index) if cand else None

    def _step_side(self, side: Side, st: dict, df: pd.DataFrame, i: int):
        """更新單一方向狀態機，訊號成立時回傳 (c1價位, break_i, c0)。"""
        p = self.p
        trend = df.at[i, "sar_trend"]
        if trend == 0:  # 起始未初始化的K線
            return None
        if side == Side.LONG:
            active_now = trend == 1
            pivots_by_confirm, better = self._peaks_by_confirm, (lambda a, b: a > b)
            wick = df.at[i, "high"]
        else:
            active_now = trend == -1
            pivots_by_confirm, better = self._troughs_by_confirm, (lambda a, b: a < b)
            wick = df.at[i, "low"]

        if not active_now:  # 影線觸及SAR、方向翻轉 → 重新計數（p.67）
            if st["active"]:
                st.update(self._fresh_side())
            return None

        if not st["active"]:
            st["active"] = True
            st["break_i"] = i
            st["c0"] = self._find_c0(side, i)
            st["c1"] = None
            st["phase"] = "c1"
            st["max_high"] = wick
            st["move_count"] = 0
            return None  # 此峰(谷)點有時就出現在翻轉當根本身，下一根才可能確認（p.68）

        close = df.at[i, "close"]
        # 無遮蔽判斷（同q2-01 3.3.3）：訊號收盤須高於翻轉以來（至前一根為止）所有K線的最高（低）影線
        unmasked = better(close, st["max_high"])
        st["max_high"] = wick if better(wick, st["max_high"]) else st["max_high"]

        new_pivots = [p for p in pivots_by_confirm.get(i, []) if p.index >= st["break_i"]]
        if st["phase"] == "c1":
            if new_pivots:
                st["c1"] = new_pivots[-1]
                st["phase"] = "c3"
                st["move_count"] = 0
            return None

        # phase == "c3"：折返段出現更極端的峰谷位 → 移動C1，最多 max_pivot_moves 次（3.4，p.72-73）
        better_pivots = [pv for pv in new_pivots if better(pv.price, st["c1"].price)]
        if better_pivots:
            if st["move_count"] >= p.max_pivot_moves:  # 超過移動上限 → 放棄此候選，重新尋找新的(1)
                st["c1"] = None
                st["phase"] = "c1"
                st["move_count"] = 0
                return None
            st["c1"] = better_pivots[-1]
            st["move_count"] += 1

        if better(close, st["c1"].price) and unmasked:
            c1_price, break_i, c0 = st["c1"].price, st["break_i"], st["c0"]
            st["c1"] = None
            st["phase"] = "c1"
            st["move_count"] = 0
            return c1_price, break_i, c0
        return None

    # ---------- 過濾 ----------

    def _passes_filters(self, df: pd.DataFrame, i: int, sess: int, side: Side, close: float, c0: _Pivot | None) -> bool:
        p = self.p
        if c0 is not None and abs(close - c0.price) > p.max_signal_points:  # F1（含F4同一原則）
            return False
        counters = self._last_signal_i.setdefault(sess, {"LONG": None, "SHORT": None})
        side_name = "LONG" if side == Side.LONG else "SHORT"
        last_i = counters[side_name]
        if last_i is not None:  # F2：同向第二個（以後）訊號需夾30點以上單筆擺動才放行
            window = df.iloc[last_i:i + 1]
            swing = float(window["high"].max() - window["low"].min())
            if swing < p.same_dir_min_swing:
                return False
        return True

    # ---------- 出場 ----------

    def _ladder_exit(self, ctx: Context) -> Order | None:
        """固定點數移動停利（p.81-83，6.1）：達獲利目標後，K線「收盤創新高且最高點也創新高」（空方鏡像）
        才把停利線移到「新高 − trail_points」；觸及＝盤中跌破停利線達 trail_breach_points 點即出場。"""
        pos = ctx.pos
        p = self.p
        if pos is None or ctx.i <= pos.entry_i:
            return None
        b = ctx.bar()
        long = pos.side == Side.LONG
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

    def _range_exit(self, ctx: Context) -> Order | None:
        """區間高低點停利（p.84，6.2，機制同 q2-01 6.5節）：達獲利目標後，取最近 range_bars 根K線
        （不含本根）的高/低點供本根作停利參考，逐根重新計算；觸及＝影線超過停利點 range_breach_points 點。"""
        pos, p, df, i = ctx.pos, self.p, ctx.df, ctx.i
        if pos is None or ctx.i <= pos.entry_i or pos.max_profit() < p.profit_target:
            return None
        long = pos.side == Side.LONG
        lo_i = max(pos.entry_i, i - p.range_bars)
        window = df.iloc[lo_i:i]
        if window.empty:
            return None
        lvl = float(window["low"].min()) if long else float(window["high"].max())
        if pos.stop is not None:  # 不可比原始停損更不利（同q2-01 6.5節第3點）
            lvl = max(lvl, pos.stop) if long else min(lvl, pos.stop)
        b = df.iloc[i]
        trigger = lvl - p.range_breach_points if long else lvl + p.range_breach_points
        if (b["low"] <= trigger) if long else (b["high"] >= trigger):
            return Order.exit("區間高低點停利")
        return None

    def _time_stop(self, ctx: Context) -> Order | None:
        pos, p = ctx.pos, self.p
        if pos is None or p.time_stop_bars is None:
            return None
        if ctx.i - pos.entry_i >= p.time_stop_bars and pos.profit(ctx.bar()["close"]) < p.time_stop_min_profit:
            return Order.exit("持倉過久出場")
        return None

    def on_bar(self, ctx: Context):
        p, df, i = self.p, ctx.df, ctx.i
        sess = int(df.at[i, "session"])
        st = self._side_state(sess)
        orders: list[Order] = []

        if ctx.pos is not None:
            ex = None
            if p.breakeven_exit:  # 求不賠，優先於下列所有出場方式（p.82, 6.4）
                ex = retrace_exit(ctx, p.profit_target, 0.0)
            if ex is None:
                ex = {
                    "ladder": self._ladder_exit,
                    "sar": lambda c: sar_exit(c, p.profit_target),
                    "range": self._range_exit,
                    "none": lambda c: None,
                }[p.exit_mode](ctx)
            if ex is None:
                ex = self._time_stop(ctx)
            if ex is not None:
                orders.append(ex)

        long_hit = self._step_side(Side.LONG, st["LONG"], df, i)
        short_hit = self._step_side(Side.SHORT, st["SHORT"], df, i)

        for side, hit, name in ((Side.LONG, long_hit, "SARC買進"), (Side.SHORT, short_hit, "SARC放空")):
            if hit is None:
                continue
            c1_price, break_i, c0 = hit
            close = df.at[i, "close"]
            if not self._passes_filters(df, i, sess, side, close, c0):
                continue
            stop = _digit_stop(side, close, p.stop_min_offset, p.stop_integer_points)
            orders.append(Order.enter(side, stop=stop, reason=name))
            counters = self._last_signal_i.setdefault(sess, {"LONG": None, "SHORT": None})
            side_name, other = ("LONG", "SHORT") if side == Side.LONG else ("SHORT", "LONG")
            counters[side_name] = i
            counters[other] = None  # 反向新一輪趨勢開始，對方的「同向計數」重置

        return orders or None
