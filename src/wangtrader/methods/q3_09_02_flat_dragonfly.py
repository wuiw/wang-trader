"""q3-09-02 平盤蜻蜓點水（買訊／空訊）（《期貨奇績3》第九章，p.205–225）。

規格文件：methods/期貨奇績3/q3-09-02-平盤蜻蜓點水.md

訊號（p.205–209）：以「平盤」（昨日收盤＝prev_close）取代均線作基準；書中依觸及平盤前的路徑分
  四種類型（p.206-207，圖9-17），本模組全部實作，共用前提：僅一根K線收盤跌破/突破平盤（C2/C2'，
  非連續兩根以上，detect() 內以「前一根仍在平盤同側」確保）、隔一根K線收盤立即收回平盤另一側
  （C3/C3'）：
  第一型（買）／第二型（空）：逆向反轉訊號，觸及平盤前行情「整段」在平盤該側且距平盤 ≥
    touch_extreme_points（C1/C1'，可調 40 點取更嚴格門檻，p.212），且訊號K線收盤須落在當日極端
    位置附近（C4/C4'：買訊較接近當日低點、空訊較接近當日高點）。
  第三型（拉回買進）／第四型（反彈再空）：既有趨勢中的回測/試探續勢訊號，不要求當日極端位置
    （T3-4/T4-4，p.222圖9-38）；前提改為「訊號前行情原在平盤另一側，已直接攻過平盤達
    type34_extreme_points 點以上」（T3-1/T4-1，p.206）。本模組以「當日開盤即在平盤另一側」
    （sess_open，對照圖9-20/9-21皆為跳空開在對側後才攻過平盤）判定「行情原在平盤之下/之上」，
    避免與第一/二型既有案例中開盤附近極短暫觸及平盤的雜訊混淆，見 `detect()`。第三/四型不建議
    套用 40 點門檻（p.212），故獨立參數 type34_extreme_points（預設20，與 touch_extreme_points
    互不影響）。
  滬深300期指等海外商品可將距平盤門檻縮小為10大點（p.213），屬既有參數可調整範圍，非另立規則。
進場（p.208–209）：訊號成立K線收盤價進場；波動過大（超大K線，F2）一律放棄不進場。
停損（p.208, 214, 217, 219–221）：進場價 ± stop_points（20，原文未指明明確基準點，採進場價，見回報）。
出場：
  提前出場（p.217）：獲利未達 15 點，價格即折返跌破（買訊）/突破（空訊）「進場K線本身」影線 → 立即出場。
  折返出場（p.215）：獲利曾達 15 點後回落到進場價（含）以下 → 平倉（retrace_exit）。
  五黑遇首紅／五紅遇首黑（p.222，圖9-37，use_five_reversal，預設開啟）：比照均線蜻蜓點水
    （q3-09-01）引用同一出場參考，本模組獨立重寫（不 import），定義同 q3-06，簡化省略 C2b
    回溯總長度例外。
  停損後反手（p.214–215, 217, 221）：量「盤中極端點」到停損（反手）點的距離：多單被停損時看
    當日盤中最高點（p.215 圖9-25「從盤中最高極端點 A 到跌破平盤最低點 D 距離 105 點」）、空單被
    停損時看當日盤中最低點（p.215 圖9-24「測量 D 點離盤中最低極端點 A 是否在 60 點內」；p.221
    圖9-36「盤中最低點至 C 收盤距離達 90 點」）。距離 ≤ reverse_max_distance(60) → 反手；> 60 →
    僅停損；若原倉獲利曾達 no_reverse_profit(15) 則不反手。反手部位本身不再具備二次反手資格
    （規格書僅示範單次反手，見 `_maybe_reverse` 內註解）。第三/四型訊號的反手規則書中未另訂，
    與第一/二型一併適用同一套規則（未載明差異不另立特例）。
過濾：
  F1 跌破／突破平盤非單一根K線 → 由 detect() 要求訊號K線前一根仍在平盤同側 內建保證。
  F2 訊號K線波動過大（giant_bar_points，預設60）→ 忽略，不進場（p.216）。
  F3 訊號位置不合理（買訊收盤較接近當日最高、空訊較接近當日最低）→ 忽略（p.216；以距兩端孰近判定，
     屬推論）；此濾網僅適用第一/二型，第三/四型依定義不套用（p.222）。
  F4 訊號前，影線觸及平盤次數 > max_flat_touches → 忽略，缺乏獨特性（p.219、224；門檻數值為推論）。
  F5 與相反方向逆向訊號衝突（如頂雙黑）→ 本模組獨立，無法取得其他方法之訊號，未實作，見回報（p.220–221）。
  F6 反手距離 > 60 點 → 僅停損不反手（同上出場段落）。

週期：不限。所有門檻以點數表示。
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from wangtrader.core import Context, Order, Side, Strategy
from wangtrader.core.exits import retrace_exit

METHOD_ID = "q3-09-02"


@dataclass
class Params:
    touch_extreme_points: float = 20.0  # C1/C1'（第一/二型），p.208, 221；可調40點取更嚴格門檻（p.212）
    type34_extreme_points: float = 20.0  # T3-1/T4-1（第三/四型），p.206；書中不建議套用40點（p.212）
    giant_bar_points: float = 60.0  # F2，p.216
    max_flat_touches: int = 1  # F4，訊號前允許影線觸及平盤的次數（門檻為推論），p.219, 224
    stop_points: float = 20.0  # p.208, 214, 217, 219-221
    early_exit_profit: float = 15.0  # p.217
    retrace_trigger: float = 15.0  # p.215
    reverse_max_distance: float = 60.0  # p.214-215, 217, 221
    no_reverse_profit: float = 15.0  # p.215
    use_five_reversal: bool = True  # 「五黑遇首紅／五紅遇首黑」出場（p.222）
    five_min_bars: int = 5  # q3-06 C1
    five_min_points: float = 40.0  # q3-06 C2（不含C2b回溯總長度例外，簡化）
    five_wick_max: float = 5.0  # q3-06 C7


class FlatDragonfly(Strategy):
    method_id = METHOD_ID

    def __init__(self, **kw) -> None:
        self.p = Params(**kw)

    @staticmethod
    def _touches(df: pd.DataFrame, sess: int, pc: float, before_i: int) -> int:
        """統計訊號A棒之前（不含A）本交易日已有多少根K線影線觸及平盤。"""
        n = 0
        for k in range(before_i - 1, -1, -1):
            row = df.iloc[k]
            if row["session"] != sess:
                break
            if row["low"] <= pc <= row["high"]:
                n += 1
        return n

    def detect(self, df: pd.DataFrame, i: int) -> tuple[Side, str, float] | None:
        """第 i 根收盤是否成立訊號。回傳 (方向, reason, A棒極端價[供反手距離判斷])。"""
        if i < 2:
            return None
        p = self.p
        prev2, a, b = df.iloc[i - 2], df.iloc[i - 1], df.iloc[i]
        if prev2["session"] != b["session"] or a["session"] != b["session"]:
            return None
        pc = b["prev_close"]
        if pd.isna(pc):
            return None
        # 買訊：a 為僅一根黑K跌破平盤（前一根 prev2 仍在平盤之上）
        if (
            a["close"] < a["open"] and a["close"] < pc and prev2["close"] >= pc
            and b["close"] > b["open"] and b["close"] > pc
        ):
            if self._touches(df, int(b["session"]), pc, i - 1) <= p.max_flat_touches:  # C5/F4
                if (b["high"] - b["low"]) < p.giant_bar_points:  # F2
                    near_low = (b["close"] - b["sess_low"]) <= (b["sess_high"] - b["close"])  # C4/F3
                    if a["sess_high"] - pc >= p.touch_extreme_points and near_low:  # 第一型
                        return Side.LONG, "平盤蜻蜓點水買訊", float(a["low"])
                    # 第三型（拉回買進，p.206-207）：訊號前行情原在平盤之下（開盤即在平盤下方），
                    # 已直接攻過平盤達 type34_extreme_points 以上；不要求近當日極端位置（T3-4）
                    if (
                        b["sess_open"] < pc
                        and a["sess_high"] - pc >= p.type34_extreme_points
                    ):
                        return Side.LONG, "平盤蜻蜓點水拉回買訊", float(a["low"])
        # 空訊：對稱
        if (
            a["close"] > a["open"] and a["close"] > pc and prev2["close"] <= pc
            and b["close"] < b["open"] and b["close"] < pc
        ):
            if self._touches(df, int(b["session"]), pc, i - 1) <= p.max_flat_touches:  # C5'/F4
                if (b["high"] - b["low"]) < p.giant_bar_points:  # F2
                    near_high = (b["sess_high"] - b["close"]) <= (b["close"] - b["sess_low"])  # C4'/F3
                    if pc - a["sess_low"] >= p.touch_extreme_points and near_high:  # 第二型
                        return Side.SHORT, "平盤蜻蜓點水空訊", float(a["high"])
                    # 第四型（反彈再空，鏡像T3-4）：訊號前行情原在平盤之上（開盤即在平盤上方），
                    # 已直接跌破平盤達 type34_extreme_points 以上；不要求近當日極端位置
                    if (
                        b["sess_open"] > pc
                        and pc - a["sess_low"] >= p.type34_extreme_points
                    ):
                        return Side.SHORT, "平盤蜻蜓點水反彈空訊", float(a["high"])
        return None

    def _maybe_reverse(self, ctx: Context) -> list[Order] | None:
        p, df, i = self.p, ctx.df, ctx.i
        t = ctx.stopped
        if not t.meta.get("dragonfly"):
            return None  # 反手部位本身不再具備二次反手資格（見下）
        if t.side == Side.LONG:
            favorable = df["high"].iloc[t.entry_i + 1 : i + 1].max() if i > t.entry_i else t.entry_price
            profit = favorable - t.entry_price
            extreme = df.at[i, "sess_high"]  # 盤中最高極端點（p.215 圖9-25：A 到 D）
        else:
            favorable = df["low"].iloc[t.entry_i + 1 : i + 1].min() if i > t.entry_i else t.entry_price
            profit = t.entry_price - favorable
            extreme = df.at[i, "sess_low"]  # 盤中最低極端點（p.215 圖9-24：D 離 A；p.221 圖9-36）
        if profit >= p.no_reverse_profit:  # 已獲利達15點以上，不反手（p.215）
            return None
        dist = abs(t.exit_price - extreme)
        if dist > p.reverse_max_distance:  # F6：極端點到反手點超過 60 點，僅停損
            return None
        new_side = Side.SHORT if t.side == Side.LONG else Side.LONG
        new_stop = t.exit_price - p.stop_points if new_side == Side.LONG else t.exit_price + p.stop_points
        # 反手部位不帶 dragonfly 標記：規格書（p.214-215, 217, 221）僅示範「原訊號停損後反手一次」，
        # 未描述反手部位再次停損後可以連環反手（修 bug 前曾單日連環反手停損 5 次）。
        return [Order.enter(new_side, stop=new_stop, reason="平盤蜻蜓點水反手")]

    def on_bar(self, ctx: Context):
        p, df, i = self.p, ctx.df, ctx.i
        b = df.iloc[i]

        if ctx.stopped is not None and ctx.pos is None:
            rev = self._maybe_reverse(ctx)
            if rev:
                return rev

        if ctx.pos is not None:
            pos = ctx.pos
            entry_bar = df.iloc[pos.entry_i]
            # 提前出場：未達15點又跌破/突破進場K線本身的影線
            if pos.max_profit() < p.early_exit_profit and ctx.i > pos.entry_i:
                if pos.side == Side.LONG and b["close"] < entry_bar["low"]:
                    return [Order.exit("未達15點提前出場")]
                if pos.side == Side.SHORT and b["close"] > entry_bar["high"]:
                    return [Order.exit("未達15點提前出場")]
            # 折返出場：獲利曾達15點後回落到進場價
            ex = retrace_exit(ctx, p.retrace_trigger, 0.0)
            if ex:
                return [ex]
            # 五黑遇首紅／五紅遇首黑出場（p.222，選項，預設開啟）
            if p.use_five_reversal:
                sig = _five_reversal_exhaustion(df, i, p.five_min_bars, p.five_min_points, p.five_wick_max)
                if sig == 1 and pos.side == Side.LONG:
                    return [Order.exit("五紅遇首黑")]
                if sig == -1 and pos.side == Side.SHORT:
                    return [Order.exit("五黑遇首紅")]
            return None

        hit = self.detect(df, i)
        if hit is None:
            return None
        side, reason, touch_extreme = hit
        entry = float(b["close"])
        stop = entry - p.stop_points if side == Side.LONG else entry + p.stop_points
        return [Order.enter(side, stop=stop, reason=reason, dragonfly=True, touch_extreme=touch_extreme)]


def _five_reversal_exhaustion(
    df: pd.DataFrame, i: int, min_bars: int = 5, min_points: float = 40.0, wick_max: float = 5.0
) -> int:
    """（本模組私有）簡化版「連五黑遇首紅／連五紅遇首黑」偵測，僅用於既有部位出場參考（q3-06，p.222）。
    回傳 1：五紅遇首黑（多單出場參考）；-1：五黑遇首紅（空單出場參考）；0：不成立。
    簡化：不含 q3-06 C2b「回溯更早連續同色K總長度」的例外規則。定義同 q3-08-02／q3-09-01
    之同名私有函式，不 import，各模組獨立重寫。"""
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
