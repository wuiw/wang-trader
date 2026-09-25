"""q3-09-02 平盤蜻蜓點水（買訊／空訊）（《期貨奇績3》第九章，p.205–225）。

規格文件：methods/期貨奇績3/q3-09-02-平盤蜻蜓點水.md

訊號（p.205, 208–209）：以「平盤」（昨日收盤＝prev_close）取代均線作基準，屬逆向（反轉）訊號：
  買訊：觸及平盤前行情在平盤上方且距平盤 ≥ touch_extreme_points（C1）；
        僅一根黑K收盤跌破平盤（C2，非連續兩根以上，detect() 內以「前一根仍在平盤同側」確保）；
        隔一根紅K收盤重新站上平盤，該紅K收盤即為訊號成立點（C3）。
  空訊：對稱（C1'–C3'，鏡像）。
進場（p.208–209）：訊號成立K線收盤價進場；波動過大（超大K線，F2）一律放棄不進場。
停損（p.208, 214, 217, 219–221）：進場價 ± stop_points（20，原文未指明明確基準點，採進場價，見回報）。
出場：
  提前出場（p.217）：獲利未達 15 點，價格即折返跌破（買訊）/突破（空訊）「進場K線本身」影線 → 立即出場。
  折返出場（p.215）：獲利曾達 15 點後回落到進場價（含）以下 → 平倉（retrace_exit）。
  停損後反手（p.214–215, 217, 221）：量「盤中極端點」到停損（反手）點的距離：多單被停損時看
    當日盤中最高點（p.215 圖9-25「從盤中最高極端點 A 到跌破平盤最低點 D 距離 105 點」）、空單被
    停損時看當日盤中最低點（p.215 圖9-24「測量 D 點離盤中最低極端點 A 是否在 60 點內」；p.221
    圖9-36「盤中最低點至 C 收盤距離達 90 點」）。距離 ≤ reverse_max_distance(60) → 反手；> 60 →
    僅停損；若原倉獲利曾達 no_reverse_profit(15) 則不反手。反手部位本身不再具備二次反手資格
    （規格書僅示範單次反手，見 `_maybe_reverse` 內註解）。
過濾：
  F1 跌破／突破平盤非單一根K線 → 由 detect() 要求訊號K線前一根仍在平盤同側 內建保證。
  F2 訊號K線波動過大（giant_bar_points，預設60）→ 忽略，不進場（p.216）。
  F3 訊號位置不合理（買訊收盤較接近當日最高、空訊較接近當日最低）→ 忽略（p.216；以距兩端孰近判定，屬推論）。
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
    touch_extreme_points: float = 20.0  # C1/C1'，p.208, 221
    giant_bar_points: float = 60.0  # F2，p.216
    max_flat_touches: int = 1  # F4，訊號前允許影線觸及平盤的次數（門檻為推論），p.219, 224
    stop_points: float = 20.0  # p.208, 214, 217, 219-221
    early_exit_profit: float = 15.0  # p.217
    retrace_trigger: float = 15.0  # p.215
    reverse_max_distance: float = 60.0  # p.214-215, 217, 221
    no_reverse_profit: float = 15.0  # p.215


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
            if a["sess_high"] - pc >= p.touch_extreme_points:  # C1
                if self._touches(df, int(b["session"]), pc, i - 1) <= p.max_flat_touches:  # C5/F4
                    if (b["close"] - b["sess_low"]) <= (b["sess_high"] - b["close"]):  # C4/F3：較接近低點
                        if (b["high"] - b["low"]) < p.giant_bar_points:  # F2
                            return Side.LONG, "平盤蜻蜓點水買訊", float(a["low"])
        # 空訊：對稱
        if (
            a["close"] > a["open"] and a["close"] > pc and prev2["close"] <= pc
            and b["close"] < b["open"] and b["close"] < pc
        ):
            if pc - a["sess_low"] >= p.touch_extreme_points:  # C1'
                if self._touches(df, int(b["session"]), pc, i - 1) <= p.max_flat_touches:  # C5'/F4
                    if (b["sess_high"] - b["close"]) <= (b["close"] - b["sess_low"]):  # C4'/F3：較接近高點
                        if (b["high"] - b["low"]) < p.giant_bar_points:  # F2
                            return Side.SHORT, "平盤蜻蜓點水空訊", float(a["high"])
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
            return None

        hit = self.detect(df, i)
        if hit is None:
            return None
        side, reason, touch_extreme = hit
        entry = float(b["close"])
        stop = entry - p.stop_points if side == Side.LONG else entry + p.stop_points
        return [Order.enter(side, stop=stop, reason=reason, dragonfly=True, touch_extreme=touch_extreme)]
