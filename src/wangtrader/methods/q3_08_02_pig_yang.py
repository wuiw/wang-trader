"""q3-08-02 均線順向策略—豬陽訊號（《期貨奇績3》第八章，p.177, 182-187）。

規格文件：methods/期貨奇績3/q3-08-02-豬陽訊號.md

訊號（p.177）：在 MA10 確立的順向趨勢中，以「黑K接紅K」（買）或「紅K接黑K」（賣）的兩根反轉
K棒組合，取代等待突破/跌破前高前低的完整流程：
  多方（豬陽買訊）：
    L1 行情已收盤站上MA10，且持續未再跌破（多方趨勢持續中）。
    L2 均線之上出現一根黑K線（A棒），其下影線完全在MA10之上（不下探至均線之下）。
    L3 緊接下一根K線（B棒）收紅，且收盤突破A棒最高點。
    L4 此時MA10方向朝上。
    L5 B棒須為「突破均線後最高的一根K線」（創新高），否則即使外觀符合也不成立。
  空方（豬陽空訊，鏡像）：
    S1-S3 同上鏡像；S4 此時MA10方向朝下（p.177-178，原文於p.177末「(3)當」中斷，p.178
    「產生這種豬陽空訊時，均線必須朝下…」已確認，與買訊鏡像一致，非推論）；S5 B棒須為「跌破
    均線後最低的一根K線」（p.178、p.182圖8-29）。
  L6/S6（p.179-180，圖8-26、圖8-27）：認定「突破/跌破均線後最高/最低K線」的比較基準時，若
    這次突破/跌破均線前，均線另一側（下方/上方）連續收盤不足3根，比較基準不重置，沿用更早、
    已有連續3根K線在該側時的比較基準（往前找上一次「真正」的突破/跌破）；足3根才是新的比較
    起點。實作：`ext_up`／`ext_down` 只在「上一段反向連續根數 >= 3」（或本方向首次出現）時才
    重置為本根高/低點，否則延續舊基準並持續累計 max/min（見 `prepare()` 主迴圈 `run_len`）。
進場：B棒收盤價進場（p.177）。
停損：延用均線順向策略基準 20 點：停損＝B棒收盤 ∓ stop_points（圖8-31 的「20點停損位置」畫在
  訊號K收盤外 20 點；書中本節未另訂新規則）。「延用」同時包含均線順向策略 §5 的「大K線」但書：
  若B棒自身收盤到反方向極端點（低/高）距離已超過 stop_points，20 點停損無法涵蓋該極端點，
  改為等拉回/反彈到「極端點 ∓ stop_points」再補進場、停損設在該極端點（large_bar_mode="wait"，
  預設，同 q3-08-01，p.162-163）；或 "midpoint" 直接進場、停損設於B棒實體中點（p.174 圖8-20）。
出場（p.184-186）：折返15點停利（use_retrace，本模組私有實作，同 q3-08-01）；及「五黑遇首紅／
  五紅遇首黑」平倉（use_five_reversal，本模組私有簡化實作，完整定義見 q3-06，本模組不 import，
  獨立重寫且省略 C2b 回溯總長度例外，見§docstring下方）。
過濾：
  F2 訊號K線收盤離均線轉折點 < turn_dist_min（預設10）→ 忽略（p.182，與均線順向策略相同）。
  F4 跳空延續開盤（轉折點在前一交易日）時，距開盤後最低/最高點 > carryover_open_dist_max
     （預設60）→ 忽略（p.184-185）。
  F1（訊號K線須為突破/跌破均線後最高/最低K線）已內建於訊號偵測本身（L5/S5）。
  strict_distance=False 可關閉 F2/F4（海外商品，p.164 同均線順向策略慣例延伸）。
不做／無法實作（見模組末待確認事項）：
  F3 均線走平/反覆穿梭時訊號可靠度低：書中僅提供定性判斷方法（觀察數根影線是否觸及均線），
     未給量化門檻，為避免自行發明規則，本模組不實作此濾網。
  F5 跳空幅度過大/大K線/無折返換手時的自我檢核：書中明白指出「非量化規則，屬判斷框架」
     （p.187），不適合寫成程式判斷式，本模組不實作。
  逆向極端訊號反手：本方法（q3-08-02）文件本身的「出場/停利」一節未提及此規則（與 q3-08-01
     不同，該規則僅明文見於 q3-08-01），故本模組不套用，避免套用未載於本文件的規則。

週期：不限。所有門檻以點數／根數表示。
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from wangtrader.core import Context, Order, Side, Strategy
from wangtrader.core.indicators import sma

METHOD_ID = "q3-08-02"


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
    ma_period: int = 10  # MA10（p.177）
    stop_points: float = 20.0  # 停損點數（延用均線順向策略，圖8-31）
    large_bar_mode: str = "wait"  # 「大K線」處理（延用均線順向策略 p.162-163）："wait"（補進場，預設）| "midpoint"
    max_wait: int = 10  # 補進場等待根數（延用均線順向策略慣例）
    max_wait_minutes: float | None = None  # 補進場有效分鐘數；None＝用 max_wait 根數（預設）。原文未寫時間，見規格文件 §12
    turn_dist_min: float = 10.0  # F2（p.182）
    carryover_open_dist_max: float = 60.0  # F4（p.184-185）
    strict_distance: bool = True  # False：關閉F2/F4（海外商品）
    use_retrace: bool = True  # 折返停利（p.184-185）
    retrace_arm: float = 15.0
    retrace_points: float = 15.0
    use_five_reversal: bool = True  # 「五黑遇首紅／五紅遇首黑」平倉（p.185-186）
    five_min_bars: int = 5  # q3-06 C1
    five_min_points: float = 40.0  # q3-06 C2（不含C2b回溯總長度例外，簡化）
    five_wick_max: float = 5.0  # q3-06 C7


class PigYang(Strategy):
    method_id = METHOD_ID

    def __init__(self, **kw) -> None:
        self.p = Params(**kw)

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["ma"] = sma(df["close"], self.p.ma_period)

        n = len(df)
        close = df["close"].to_numpy(float)
        open_ = df["open"].to_numpy(float)
        high = df["high"].to_numpy(float)
        low = df["low"].to_numpy(float)
        ma = df["ma"].to_numpy(float)
        sess = df["session"].to_numpy()

        sig_side = [0] * n
        turn_price = [float("nan")] * n
        turn_sess_col = [-1] * n

        state: str | None = None  # None | 'up' | 'down'：目前收盤在均線哪一側
        run_len = 0  # 目前這一側已連續收盤幾根（含本根），供L6/S6判斷「另一側是否滿3根」
        ext_up = float("nan")  # L5 比較基準：「突破均線後最高K線」的基準（見L6，未必每次穿越都重置）
        ext_down = float("nan")  # S5 比較基準（鏡像）
        turn_p = float("nan")  # 供F2/F4：最近一次穿越均線的位置（不受L6/S6的3根規則影響）
        turn_sess = -1

        for i in range(n):
            if i == 0 or ma[i] != ma[i]:
                continue
            c, m = close[i], ma[i]
            pc, pm = close[i - 1], ma[i - 1]
            # 收盤穿越均線 → 趨勢轉折起點；均線剛可用的第一根依收盤在均線哪一側初始化
            new_up = state != "up" and c > m and (state is not None or pm != pm or pc <= pm)
            new_down = state != "down" and c < m and (state is not None or pm != pm or pc >= pm)
            if new_up:
                turn_p, turn_sess = c, df.at[i, "session"]
                # L6（p.179-180）：僅當跌破均線前已有連續 >=3 根收盤在均線下方，才是「真正」的突破，
                # 比較基準重置為本根高點；否則視為雜訊，沿用更早、已滿3根時建立的舊基準
                genuine = state == "down" and run_len >= 3
                if state is None or genuine or ext_up != ext_up:
                    ext_up = high[i]
                else:
                    ext_up = max(ext_up, high[i])
                state, run_len = "up", 1
                continue
            if new_down:
                turn_p, turn_sess = c, df.at[i, "session"]
                genuine = state == "up" and run_len >= 3  # S6（鏡像）
                if state is None or genuine or ext_down != ext_down:
                    ext_down = low[i]
                else:
                    ext_down = min(ext_down, low[i])
                state, run_len = "down", 1
                continue
            if state is None:
                continue
            run_len += 1

            if state == "up":
                prev_ext = ext_up
                ext_up = max(ext_up, high[i])
                a, b = i - 1, i
                if (
                    sess[a] == sess[b]
                    and close[a] < open_[a] and low[a] > ma[a]  # L2：黑K，下影線在MA之上
                    and close[b] > open_[b] and close[b] > high[a]  # L3：紅K收盤突破A高點
                    and m > pm  # L4：均線朝上
                    and high[b] > prev_ext  # L5：B為突破均線後最高K線（依L6基準）
                ):
                    sig_side[i] = 1
                    turn_price[i] = turn_p
                    turn_sess_col[i] = turn_sess
            else:  # state == "down"
                prev_ext = ext_down
                ext_down = min(ext_down, low[i])
                a, b = i - 1, i
                if (
                    sess[a] == sess[b]
                    and close[a] > open_[a] and high[a] < ma[a]  # S2：紅K，上影線在MA之下
                    and close[b] < open_[b] and close[b] < low[a]  # S3：黑K收盤跌破A低點
                    and m < pm  # S4：均線朝下（p.177-178，非推論）
                    and low[b] < prev_ext  # S5：B為跌破均線後最低K線（依S6基準）
                ):
                    sig_side[i] = -1
                    turn_price[i] = turn_p
                    turn_sess_col[i] = turn_sess

        df["sig_side"] = sig_side
        df["turn_price"] = turn_price
        df["turn_sess"] = turn_sess_col
        return df

    def _passes_filters(self, df: pd.DataFrame, i: int, side: Side) -> bool:
        p = self.p
        if not p.strict_distance:
            return True
        b = df.iloc[i]
        if b["turn_sess"] != b["session"]:  # F4：跳空延續開盤（轉折點在前一交易日）
            # p.184「訊號K線離開盤後最低點超過60點以上宜忽略」：多看開盤後最低點、空看最高點
            ref = b["sess_low"] if side == Side.LONG else b["sess_high"]
            return abs(b["close"] - ref) <= p.carryover_open_dist_max
        dist = abs(b["close"] - b["turn_price"])
        return dist >= p.turn_dist_min  # F2

    def _reached(self, ctx: Context, target: float) -> bool:
        pos = ctx.pos
        return pos is not None and ctx.i > pos.entry_i and pos.max_profit() >= target

    def _retrace_exit(self, ctx: Context) -> Order | None:
        p = self.p
        if not self._reached(ctx, p.retrace_arm):
            return None
        pos = ctx.pos
        if pos.max_profit() - pos.profit(ctx.bar()["close"]) >= p.retrace_points:
            return Order.exit("折返停利")
        return None

    def on_bar(self, ctx: Context):
        p, df, i = self.p, ctx.df, ctx.i

        if ctx.pos is not None:
            if p.use_retrace:
                ex = self._retrace_exit(ctx)
                if ex:
                    return [ex]
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
        side = Side.LONG if side_code == 1 else Side.SHORT
        if not self._passes_filters(df, i, side):
            return None
        b = df.iloc[i]
        ext = float(b["low"]) if side == Side.LONG else float(b["high"])
        c = float(b["close"])
        name = "豬陽買訊" if side == Side.LONG else "豬陽空訊"
        # 停損＝收盤 ∓ stop_points（圖8-31）。大K線（延用均線順向策略，p.162-163）：B棒收盤到反方向
        # 極端點距離已超過 stop_points，20 點停損無法涵蓋該極端點 → 等拉回/反彈到「極端點 ∓ 20」
        # 再補進場、停損設在極端點；或 midpoint 模式直接進場、停損設在實體中點（p.174 圖8-20）。
        if abs(c - ext) <= p.stop_points:
            stop = c - p.stop_points if side == Side.LONG else c + p.stop_points
            return [Order.enter(side, stop=stop, reason=name)]
        if p.large_bar_mode == "midpoint":
            mid = (float(b["open"]) + c) / 2.0
            return [Order.enter(side, stop=mid, reason=name + "(大K線)")]
        limit = ext + p.stop_points * int(side)  # 多：低點+20；空：高點-20
        return [Order.enter_limit(side, limit=limit, expire=_wait_bars(df, i, p), stop=ext, reason=name + "(補進場)")]


def _five_reversal_exhaustion(
    df: pd.DataFrame, i: int, min_bars: int = 5, min_points: float = 40.0, wick_max: float = 5.0
) -> int:
    """（本模組私有）簡化版「連五黑遇首紅／連五紅遇首黑」偵測，僅用於既有部位出場參考（q3-06）。
    回傳 1：第 i 根為連續 >=min_bars 根紅K（幅度>=min_points）後首根不創新高的黑K（五紅遇首黑，
    多單出場參考）；-1：鏡像（五黑遇首紅，空單出場參考）；0：不成立。
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
