"""q3-08-01 均線順向策略（《期貨奇績3》第八章，p.155-175）。

規格文件：methods/期貨奇績3/q3-08-01-均線順向策略.md

訊號（p.155-159）：『突破(均線)－休息(不創新高)－再突破(前高)』：
  多方：某根K線收盤站上MA10（趨勢轉折起點）→ 之後K線持續創新高（攻擊）→ 某根K線高點未能
        創新高，進入「休息」（休息期間所有K線收盤不可跌破MA10，紅黑不拘）→ 以「休息前的最高點」
        （層級1峰點）畫「峰位濾網」（p.157「以C的高點畫水平線當作訊號的濾網」；p.158「B的低點
        就是跌破均線後的第一個谷點」）→ 其後某根K線收盤突破峰位濾網即為買訊。
        峰位濾網只有一次突破機會：只有影線突破、收盤未過視為失敗，該影線高點成為新的攻擊高點，
        須等再次休息形成新峰位（p.156「就得尋找另一次峰位」）；等待期間若收盤先跌破MA10，流程
        失效須重新開始（p.159）。
  空方：與多方鏡像（跌破MA10 → 破新低 → 休息 → 谷位濾網 → 收盤跌破谷位濾網）。
  L7/S7（p.160-161）：休息期間若又形成另一個「較近」的層級1峰（谷）點──即較低的峰點／較高的
        谷點，較容易被突破──濾網改用該較近者，不必等突破原先較高（低）的峰（谷）點；前提仍是自
        第一個峰（谷）點起收盤都未跌破（突破）MA10，否則整個流程失效（圖8-5：A為第一個層級1峰
        點，其後在較低的B形成第二個層級1峰點，只要突破B即成立買訊，不必等突破A）。本模組用
        `find_pivots(level=1)` 找已確認的層級1峰谷點實作，見 `_nearer_pivot`。
  rest_extreme_filter=True（推論，預設關閉）：改以「休息期間K線的最高/最低點」作濾網，對應
        p.172 圖8-17 圖說「E 收盤跌破休息中縮腳點 D 的低點即成空訊，不必等跌破 C 的低點」；
        此讀法與 p.156-158 的定義文字（濾網＝峰位C／谷位B）不一致，預設不採用。
進場（p.156-157, 162-163）：以訊號K線收盤進場，停損＝收盤價 ∓ stop_points（圖8-9、圖8-31
  的「20點停損位置」皆畫在訊號K收盤外 20 點）。訊號K線自身極端點（多：低點／空：高點）距收盤
  > stop_points 屬「大K線」：large_bar_mode="wait"（預設）掛限價等反彈/拉回到「極端點 ∓
  stop_points」再補進場，停損設在該極端點（p.162-163「若要設停損在K線高點，則有28點距離，
  因此可以等反彈離停損點縮小20點以內，再補進場放空」）；"midpoint" 直接進場、停損設在訊號K
  實體中點（p.174 圖8-20「跌點近40點，停損可設在K線中線」）。
出場（p.163, 169, 172）：exit_mode = "retrace"（15點折返移動停利，預設，本模組私有實作因核心
  ladder/ma/sar 皆非「距最高獲利回吐固定點數」語意）| "ma_touch"（均線遵循性停利：持倉期間連續
  未觸及均線逾 ma_touch_minutes 分鐘（p.172 圖8-19「連續超過一個小時以上」，預設 60，以K線時間戳
  計算、不綁週期；設 None 或 time 欄不是時間戳時改用 ma_touch_bars 根）後，首次觸及均線即出場，
  本模組私有實作）| "ladder"|"ma"|"sar"|"none"。
逆向反手（p.169）：持有順向單期間，若出現對立方向的極端位置逆向訊號（頂雙黑/底雙紅，本模組
  私有偵測 `_extreme_reversal_side`，定義同 q3-01 但獨立實作），須立即平倉並反手，沒有例外
  （p.169「必須毫無懸念地平倉並反手」），反手停損＝反手收盤 ± stop_points。
  註：「未達15點、侵入收盤可不反手」只適用於兩個同類型極端訊號之間，不適用於順向單。
過濾：
  F1 訊號K線收盤離「均線轉折點」> turn_dist_max（預設40）→ 忽略（p.162）；若轉折點發生在本交易日
     第一根（跳空造成均線轉折），改以「開盤後高低震幅 ≤ gap_open_range_max（40）」為界限（p.162
     「如果開盤呈現跳空狀態…則依開盤後行情高低震幅40點為觀察界限」）。
  F3 訊號K線收盤離均線轉折點 < turn_dist_min（預設10）→ 忽略（p.168）。
  F4 轉折點在更早的交易日（延續前日趨勢開盤）時，改以「訊號K收盤距開盤後最低點（多）／最高點
     （空）≤ carryover_open_dist_max（60）」判斷（p.184「若訊號K線離開盤後最低點，超過60點以上，
     宜忽略訊號」），不套用 F1/F3。
  F2 距「波段起始峰谷點」（層級 swing_pivot_level，書中「通常層級5以上」）> swing_dist_max
     （預設60）→ 忽略（p.163-164）。波段起點取「本交易日、位於均線轉折點之前、且訊號當下已確認」
     的最後一個峰谷；找不到時不套用此濾網（推論）。
  F5 海外期貨商品不受40/60/10點距離限制（p.164）：以 strict_distance=False 關閉 F1/F2/F3/F4。
不做／無法實作：
  F6 加碼限制（p.167）：引擎僅支援單一部位（同向進場會被忽略、反向才反手），無加碼機制。

週期：不限。所有門檻以點數／根數表示。
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from wangtrader.core import Context, Order, Side, Strategy
from wangtrader.core.bars import is_extreme_position
from wangtrader.core.exits import ladder_exit, ma_exit, sar_exit
from wangtrader.core.indicators import sar, sma
from wangtrader.core.pivots import find_pivots

METHOD_ID = "q3-08-01"


def _wait_bars(df: pd.DataFrame, i: int, p) -> int:
    """補進場有效根數：max_wait_minutes 為 None 時用 max_wait 根；否則把分鐘換成根數——以第 i 根（含）
    以前、同交易日相鄰K線的最小時間差當作K線週期（只用已發生的K線，不寫死週期）；time 欄不是時間戳
    或找不到相鄰K線時退回 max_wait 根。"""
    minutes, fallback = p.max_wait_minutes, p.max_wait
    if minutes is None:
        return fallback
    t, s = df["time"], df["session"]
    step = None
    k = i
    while k > 0 and k > i - 20:
        if s.iat[k] == s.iat[k - 1]:
            try:
                d = (t.iat[k] - t.iat[k - 1]).total_seconds() / 60.0
            except (TypeError, AttributeError):
                return fallback
            if d > 0:
                step = d if step is None else min(step, d)
        k -= 1
    if step is None:
        return fallback
    return max(1, int(minutes / step + 1e-9))


@dataclass
class Params:
    ma_period: int = 10  # MA10（p.157）
    stop_points: float = 20.0  # 停損點數（p.162-165，圖8-9）
    max_wait: int = 10  # 補進場等待根數（書中未載明確切根數，沿用 q3-01 慣例，待確認）
    max_wait_minutes: float | None = None  # 補進場有效分鐘數；None＝用 max_wait 根數（預設）。原文未寫時間，見規格文件 §12
    large_bar_mode: str = "wait"  # "wait"（補進場，預設）| "midpoint"（直接進場，停損設實體中點）
    rest_extreme_filter: bool = False  # 推論：以休息期間極值作濾網（p.172 圖8-17 讀法），預設關閉
    turn_dist_min: float = 10.0  # F3（p.168）
    turn_dist_max: float = 40.0  # F1（p.162）
    gap_open_range_max: float = 40.0  # F1 跳空情境：開盤後高低震幅界限（p.162）
    carryover_open_dist_max: float = 60.0  # F4 延續開盤情境：距開盤後最低/最高點（p.184）
    strict_distance: bool = True  # F5：海外商品可設 False 關閉距離濾網（p.164）
    use_swing_filter: bool = True  # F2 開關
    swing_pivot_level: int = 5  # F2 波段起點峰谷層級（書中「通常層級5以上」，p.163-164）
    swing_dist_max: float = 60.0  # F2（p.163-164）
    reverse_on_opposite_extreme: bool = True  # 遇逆向極端訊號強制平倉反手（p.169）
    extreme_range: float = 30.0  # 逆向極端偵測用（同 q3-01 定義）
    extreme_from_prev_close: float = 40.0
    exit_mode: str = "retrace"  # "retrace"|"ma_touch"|"ladder"|"ma"|"sar"|"none"
    retrace_arm: float = 15.0  # 折返停利：先達此獲利才開始追蹤（p.163圖8-6示範獲利逾30才觸發）
    retrace_points: float = 15.0  # 折返停利：由最高獲利回吐此點數觸價出場（p.163, p.184-185）
    ma_touch_bars: int = 12  # 均線遵循性停利：連續未觸及均線根數門檻（ma_touch_minutes=None 時使用；5分K 12根≈1小時）
    ma_touch_minutes: float | None = 60.0  # 均線遵循性停利：連續未觸及均線的分鐘門檻（p.172 圖8-19「連續超過一個小時以上」）


class MaBreakout(Strategy):
    method_id = METHOD_ID

    def __init__(self, **kw) -> None:
        self.p = Params(**kw)

    # ---------- 準備欄位（因果計算，逐根前進的狀態機） ----------
    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["ma"] = sma(df["close"], self.p.ma_period)
        s = sar(df)
        df["sar"], df["sar_trend"] = s["sar"], s["trend"]

        n = len(df)
        close = df["close"].to_numpy(float)
        high = df["high"].to_numpy(float)
        low = df["low"].to_numpy(float)
        ma = df["ma"].to_numpy(float)
        sess = df["session"].to_numpy()
        bar_no = df["bar_no"].to_numpy()

        sig_side = [0] * n
        turn_price = [float("nan")] * n
        turn_idx = [-1] * n
        signal_ext = [float("nan")] * n  # 訊號K線自身的低點(多)/高點(空)，用於停損
        carryover = [False] * n  # 轉折點是否在更早的交易日（延續前日趨勢開盤，p.184）
        turn_at_open = [False] * n  # 轉折點是否為本交易日第一根（跳空造成均線轉折，p.162）

        state: str | None = None  # None | attack_up | rest_up | attack_down | rest_down
        ext = float("nan")  # 攻擊階段的極值＝休息階段的峰位/谷位濾網
        rest_ext = float("nan")  # 休息期間K線的極值（rest_extreme_filter 用）
        turn_p, turn_i = float("nan"), -1
        top_i = -1  # 目前 ext 對應之層級1峰（谷）點 bar index，供 L7/S7 用

        def mark(i: int, side: int) -> None:
            sig_side[i] = side
            turn_price[i] = turn_p
            turn_idx[i] = turn_i
            signal_ext[i] = low[i] if side == 1 else high[i]
            carryover[i] = sess[turn_i] != sess[i]
            turn_at_open[i] = (not carryover[i]) and bar_no[turn_i] == 0

        pivots1 = find_pivots(df, level=1)  # 層級1峰谷點，供 L7/S7「較近峰谷點」規則使用

        def nearer_pivot(kind: str, better: str, top_i: int, i: int, ext: float) -> float | None:
            """L7/S7（p.160-161）：自本波第一個層級1峰(谷)點 top_i 之後、目前 i 之前，若已確認出現
            「較近」（峰取較低者／谷取較高者，即較容易被突破者）的層級1峰(谷)點，回傳其價位；否則
            回傳 None（沿用原 ext）。"""
            best = None
            for pv in pivots1:
                if pv.kind != kind or pv.index <= top_i or pv.index >= i or pv.confirm > i:
                    continue
                if sess[pv.index] != sess[i]:
                    continue
                if better == "lower" and pv.price >= ext:
                    continue
                if better == "higher" and pv.price <= ext:
                    continue
                best = pv  # pivots1 依 index 遞增排序，留到最後＝最近者
            return best.price if best is not None else None

        for i in range(n):
            if ma[i] != ma[i]:
                continue
            c, m = close[i], ma[i]
            # 收盤穿越均線：趨勢轉折起點（p.156-157, 159）
            if c > m and state in (None, "attack_down", "rest_down"):
                state, ext, turn_p, turn_i = "attack_up", high[i], c, i
                top_i = i
                continue
            if c < m and state in (None, "attack_up", "rest_up"):
                state, ext, turn_p, turn_i = "attack_down", low[i], c, i
                top_i = i
                continue
            if state == "attack_up":
                if high[i] > ext:
                    ext = high[i]
                    top_i = i
                else:  # 高點未創新高 → 休息，濾網＝休息前最高點 ext
                    state, rest_ext = "rest_up", high[i]
            elif state == "rest_up":
                filt = rest_ext if self.p.rest_extreme_filter else ext
                if not self.p.rest_extreme_filter:
                    near = nearer_pivot("peak", "lower", top_i, i, ext)  # L7
                    if near is not None:
                        filt = near
                if c > filt:
                    mark(i, 1)
                    state, ext = "attack_up", max(ext, high[i])
                    top_i = i
                elif high[i] > ext:  # 只有影線突破峰位 → 失敗，另尋下一個峰位（p.156）
                    state, ext = "attack_up", high[i]
                    top_i = i
                else:
                    rest_ext = max(rest_ext, high[i])
            elif state == "attack_down":
                if low[i] < ext:
                    ext = low[i]
                    top_i = i
                else:
                    state, rest_ext = "rest_down", low[i]
            elif state == "rest_down":
                filt = rest_ext if self.p.rest_extreme_filter else ext
                if not self.p.rest_extreme_filter:
                    near = nearer_pivot("trough", "higher", top_i, i, ext)  # S7
                    if near is not None:
                        filt = near
                if c < filt:
                    mark(i, -1)
                    state, ext = "attack_down", min(ext, low[i])
                    top_i = i
                elif low[i] < ext:
                    state, ext = "attack_down", low[i]
                    top_i = i
                else:
                    rest_ext = min(rest_ext, low[i])

        df["sig_side"] = sig_side
        df["turn_price"] = turn_price
        df["turn_i"] = turn_idx
        df["signal_ext"] = signal_ext
        df["carryover"] = carryover
        df["turn_at_open"] = turn_at_open
        self._pivots = find_pivots(df, level=self.p.swing_pivot_level)
        self._sess = sess
        return df

    # ---------- 過濾 ----------
    def _passes_distance_filters(self, df: pd.DataFrame, i: int, side: Side) -> bool:
        p = self.p
        if not p.strict_distance:
            return True
        b = df.iloc[i]
        if b["carryover"]:
            # F4 延續開盤（p.184）：距開盤後最低點（多）／最高點（空）
            ref = b["sess_low"] if side == Side.LONG else b["sess_high"]
            return abs(b["close"] - ref) <= p.carryover_open_dist_max
        dist = abs(b["close"] - b["turn_price"])
        if dist > p.turn_dist_max:  # F1
            if b["turn_at_open"]:  # 跳空造成轉折：改看開盤後高低震幅（p.162）
                return (b["sess_high"] - b["sess_low"]) <= p.gap_open_range_max
            return False
        if dist < p.turn_dist_min:  # F3
            return False
        return True

    def _passes_swing_filter(self, df: pd.DataFrame, i: int, side: Side) -> bool:
        p = self.p
        if not p.strict_distance or not p.use_swing_filter:
            return True
        kind = "trough" if side == Side.LONG else "peak"
        turn_i = int(df.at[i, "turn_i"])
        cands = [
            pv for pv in self._pivots
            if pv.kind == kind and pv.confirm <= i and pv.index <= turn_i and self._sess[pv.index] == self._sess[i]
        ]
        if not cands:
            return True  # 本交易日尚無已確認的波段起點峰谷，不套用（推論）
        return abs(df.at[i, "close"] - cands[-1].price) <= p.swing_dist_max

    # ---------- 出場工具（本模組私有：核心 exits.py 沒有「離峰值回吐固定點數」語意） ----------
    def _reached(self, ctx: Context, target: float) -> bool:
        pos = ctx.pos
        return pos is not None and ctx.i > pos.entry_i and pos.max_profit() >= target

    def _retrace_exit(self, ctx: Context) -> Order | None:
        p = self.p
        if not self._reached(ctx, p.retrace_arm):
            return None
        pos = ctx.pos
        give_back = pos.max_profit() - pos.profit(ctx.bar()["close"])
        if give_back >= p.retrace_points:
            return Order.exit("折返停利")
        return None

    def _ma_touch_exit(self, ctx: Context) -> Order | None:
        """均線遵循性停利（p.172）：持倉期間連續未觸及均線逾 ma_touch_minutes 分鐘（或 ma_touch_bars 根）
        後，首次觸及即出場。未觸及區段＝錨點（最近一次觸及／重設的那根）之後到前一根。"""
        p, pos, i = self.p, ctx.pos, ctx.i
        b = ctx.bar()
        ma = b["ma"]
        key = "untouched_anchor"
        if key not in pos.meta:
            pos.meta[key] = i - 1
        if ma != ma:
            pos.meta[key] = i
            return None
        touched = (b["low"] <= ma) if pos.side == Side.LONG else (b["high"] >= ma)
        if not touched:
            return None
        anchor = pos.meta[key]
        pos.meta[key] = i
        armed = (i - 1) - anchor >= p.ma_touch_bars
        if p.ma_touch_minutes is not None and i - 1 > anchor:
            try:
                mins = (ctx.df.at[i - 1, "time"] - ctx.df.at[anchor, "time"]).total_seconds() / 60.0
                armed = mins >= p.ma_touch_minutes
            except (TypeError, AttributeError):
                pass  # time 欄不是時間戳 → 沿用根數判斷
        elif p.ma_touch_minutes is not None:
            armed = False
        if armed and i > pos.entry_i:
            return Order.exit("均線遵循性停利")
        return None

    def _run_exit(self, ctx: Context) -> Order | None:
        mode = self.p.exit_mode
        if mode == "retrace":
            return self._retrace_exit(ctx)
        if mode == "ma_touch":
            return self._ma_touch_exit(ctx)
        if mode == "ladder":
            return ladder_exit(ctx, self.p.retrace_arm)
        if mode == "ma":
            return ma_exit(ctx, "ma", self.p.retrace_arm)
        if mode == "sar":
            return sar_exit(ctx, self.p.retrace_arm)
        return None

    def on_bar(self, ctx: Context):
        p, df, i = self.p, ctx.df, ctx.i

        if ctx.pos is not None:
            # 逆向極端訊號 → 強制平倉反手（p.169），沒有例外；反手停損＝收盤 ± stop_points
            if p.reverse_on_opposite_extreme:
                rev = _extreme_reversal_side(df, i, p.extreme_range, p.extreme_from_prev_close)
                if rev is not None and rev != ctx.pos.side:
                    c = float(df.at[i, "close"])
                    stop = c + p.stop_points if rev == Side.SHORT else c - p.stop_points
                    return [Order.enter(rev, stop=stop, reason="逆向極端訊號反手")]
            ex = self._run_exit(ctx)
            return [ex] if ex else None

        side_code = df.at[i, "sig_side"]
        if side_code == 0:
            return None
        side = Side.LONG if side_code == 1 else Side.SHORT
        if not self._passes_distance_filters(df, i, side):
            return None
        if not self._passes_swing_filter(df, i, side):
            return None

        b = df.iloc[i]
        ext, c = float(b["signal_ext"]), float(b["close"])
        name = "均線買訊" if side == Side.LONG else "均線空訊"
        if abs(c - ext) <= p.stop_points:
            stop = c - p.stop_points if side == Side.LONG else c + p.stop_points
            return [Order.enter(side, stop=stop, reason=name)]
        # 大K線（p.162-163）
        if p.large_bar_mode == "midpoint":
            mid = (float(b["open"]) + c) / 2.0
            return [Order.enter(side, stop=mid, reason=name + "(大K線)")]
        limit = ext + p.stop_points * int(side)  # 多：低點+20；空：高點-20
        return [Order.enter_limit(side, limit=limit, expire=_wait_bars(df, i, p), stop=ext, reason=name + "(補進場)")]


def _extreme_reversal_side(
    df: pd.DataFrame, i: int, extreme_range: float = 30.0, extreme_from_prev_close: float = 40.0
) -> Side | None:
    """（本模組私有）頂雙黑／底雙紅簡化偵測，僅用於判斷順向單是否須強制反手（p.169）。
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
