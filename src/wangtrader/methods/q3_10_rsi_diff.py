"""q3-10 RSI差值訊號（正差買訊／負差空訊）（《期貨奇績3》第十章，p.227–241）。

規格文件：methods/期貨奇績3/q3-10-RSI差值訊號.md

訊號（p.227）：
  空方（負差空訊）：本根或前一根為（截至目前）盤中最高K線（該K線之RSI須為本波段「由升轉降」
    的真正相對高點），下一根RSI值 ≤ 高點RSI − diff_threshold → 該根收盤放空。
  多方（正差買訊）：對稱，最低K線＋RSI「由降轉升」轉折，下一根RSI值 ≥ 低點RSI + diff_threshold → 買進。
進場（p.229–231）：訊號確立當根收盤立即進場。
停損（p.229–231；主管補充澄清 p.233）：訊號K（RSI極端K線）極端價 ± stop_points（20）；
  若因訊號K本身波動過大，使「進場價到停損價」距離 > max_risk（40）→ 忽略該訊號（p.233）。
出場／確認（p.233, 235–236）：
  「已確認」（兩種等價判準，滿足其一即可）：曾順向推進達 profit_confirm（15）點（p.233）；或
  K線收盤已突破（多）/跌破（空）訊號K線本身的最高/最低點（p.236「曾出現K線收盤超過訊號K線的
  最高點…只能進行停損，不能再反手」）。已確認之後：
    - 若折返回到進場價（訊號K收盤，含）以下 → 撤單平倉（p.233, 236「拉回亦得在A的進場點撤單平倉」）。
    - 若反轉觸及停損，只停損，不可反手（p.236）。
  未確認：
    - K線收盤反向突破「訊號前的相對高點（空訊）／相對低點（買訊）」濾網線 → 不必等觸及 20 點
      停損，當根收盤即停損原單並反手（p.235「在 C 的收盤突破 A 高點時，反手追買」；p.240–241）；
      若是盤中先觸及停損，也須該根收盤突破濾網線才反手。
    - 反手位置距平盤（prev_close）> reverse_max_from_flat（100）→ 僅停損，不反手（p.236）。
    - 反手部位本身不再帶訊號資訊，不做連環反手（書中僅示範單次）；其出場沿用 15 點確認後折返平倉。
過濾：
  F1 開盤第一根K線不可作為訊號判斷依據（p.228）。
  F2 RSI 極值須為「由升轉降／由降轉升」的真正轉折點，非途中臨時放大（簡化判定：極端K線RSI嚴格高於/
     低於其前一根；前後值相同（持平）不算，p.230-231, 234）。
  F3 極端位置：盤中震幅 ≥ extreme_range(30) 或距平盤 ≥ extreme_from_prev_close(40)（沿用
     is_extreme_position）；跳空 ≤ gap_merge_points(10) 時可併入前一日區間計算（p.227-228, 237）。
  F4 訊號K線本身波動過大，導致停損恐逾 max_risk（40）→ 忽略（p.233）。
  F5 no_entry_after：時間晚於此不做新倉（時間性規則，預設關閉）。
  F6 同日同側已有未獲利交易 → 不再進場（p.233，作者提醒；預設開啟）。

週期：不限。所有門檻以點數表示。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time

import pandas as pd

from wangtrader.core import Context, Order, Side, Strategy
from wangtrader.core.bars import is_extreme_position
from wangtrader.core.indicators import rsi

METHOD_ID = "q3-10"


@dataclass
class Params:
    rsi_period: int = 5  # 原文未指定 RSI 參數，採核心預設值（推論）
    diff_threshold: float = 20.0  # p.227
    extreme_range: float = 30.0  # p.227
    extreme_from_prev_close: float = 40.0  # p.227
    gap_merge_points: float = 10.0  # p.237，跳空 <= 此值可併入前一日區間
    stop_points: float = 20.0  # p.229-231
    max_risk: float = 40.0  # F4，p.233（主管澄清：進場價到停損價距離上限）
    profit_confirm: float = 15.0  # 主管澄清：達此獲利即「已確認」，p.232-233, 236
    reverse_max_from_flat: float = 100.0  # p.236
    no_entry_after: time | None = None  # F5，時間性規則，預設關閉
    no_repeat_after_loss: bool = True  # F6，p.233 作者提醒


class RsiDiffSignal(Strategy):
    method_id = METHOD_ID

    def __init__(self, **kw) -> None:
        self.p = Params(**kw)

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["rsi"] = rsi(df["close"], self.p.rsi_period)
        return df

    def _extreme_ok(self, df: pd.DataFrame, i: int) -> bool:
        p = self.p
        b = df.iloc[i]
        if is_extreme_position(df, i, p.extreme_range, p.extreme_from_prev_close):
            return True
        pc, ph, pl = b["prev_close"], b["prev_high"], b["prev_low"]
        if pd.isna(pc) or pd.isna(ph) or pd.isna(pl):
            return False
        if abs(b["sess_open"] - pc) > p.gap_merge_points:
            return False
        rng = max(b["sess_high"], ph) - min(b["sess_low"], pl)
        return rng >= p.extreme_range

    def detect(self, df: pd.DataFrame, i: int) -> tuple[Side, float, str] | None:
        """回傳 (方向, 訊號K極端價, reason)。"""
        if i < 1:
            return None
        p = self.p
        a, b = df.iloc[i - 1], df.iloc[i]
        if a["session"] != b["session"] or a["bar_no"] == 0 or b["bar_no"] == 0:  # F1
            return None
        ra, rb = a["rsi"], b["rsi"]
        if pd.isna(ra) or pd.isna(rb):
            return None
        prev_rsi = df.at[i - 2, "rsi"] if i >= 2 and df.at[i - 2, "session"] == a["session"] else None
        # F2 簡化判定：a 的 RSI 須高於（低於）前一根；前後值相同時只有收盤仍在上漲（下跌）才算「進行中」
        # （p.234：收盤相同造成 RSI 持平者不算），RSI 飽和在 100/0 但收盤續漲續跌者仍視為進行中。
        if prev_rsi is None or pd.isna(prev_rsi):
            rising_ok = falling_ok = True
        else:
            prev_close = df.at[i - 2, "close"]
            rising_ok = ra > prev_rsi or (ra == prev_rsi and a["close"] > prev_close)
            falling_ok = ra < prev_rsi or (ra == prev_rsi and a["close"] < prev_close)
        # 空方：a（或b）為當下盤中最高K線，RSI由升轉降，隔根重挫 >= diff_threshold
        if a["high"] >= a["sess_high"] or b["high"] >= b["sess_high"]:
            if rising_ok and ra - rb >= p.diff_threshold and self._extreme_ok(df, i):
                return Side.SHORT, float(b["sess_high"]), "RSI負差空訊"
        # 多方：對稱
        if a["low"] <= a["sess_low"] or b["low"] <= b["sess_low"]:
            if falling_ok and rb - ra >= p.diff_threshold and self._extreme_ok(df, i):
                return Side.LONG, float(b["sess_low"]), "RSI正差買訊"
        return None

    def _update_confirmed(self, ctx: Context) -> bool:
        """訊號是否已「延續確認」（p.233, 236）：曾順向獲利達 profit_confirm，或K線收盤已突破（多）/
        跌破（空）訊號K線自身的極端點。狀態記在 pos.meta["confirmed"]，只用本根及之前的資料。"""
        pos = ctx.pos
        if pos.meta.get("confirmed"):
            return True
        if ctx.i <= pos.entry_i:
            return False
        c = ctx.bar()["close"]
        sig_high, sig_low = pos.meta.get("sig_high"), pos.meta.get("sig_low")
        beyond = False
        if sig_high is not None and sig_low is not None:
            beyond = (c > sig_high) if pos.side == Side.LONG else (c < sig_low)
        if beyond or pos.max_profit() >= self.p.profit_confirm:
            pos.meta["confirmed"] = True
            return True
        return False

    def _reverse_order(self, ctx: Context, old_side: Side, ext: float) -> list[Order] | None:
        """未確認訊號的反手單（p.235–236）：反手位置距平盤 > reverse_max_from_flat 則不反手。"""
        p, df, i = self.p, ctx.df, ctx.i
        pc = df.at[i, "prev_close"]
        c = float(df.at[i, "close"])
        dist = abs(c - pc) if not pd.isna(pc) else 0.0
        if dist > p.reverse_max_from_flat:  # 距平盤過遠，僅停損
            return None
        new_side = Side.SHORT if old_side == Side.LONG else Side.LONG
        new_stop = ext - p.stop_points * int(new_side)
        return [Order.enter(new_side, stop=new_stop, reason="RSI差值反手")]

    def _maybe_reverse(self, ctx: Context) -> list[Order] | None:
        """本根盤中被停損：若訊號尚未確認、且本根收盤反向突破濾網線，停損後反手（p.235）。"""
        p, df, i = self.p, ctx.df, ctx.i
        t = ctx.stopped
        ext = t.meta.get("ext_price")
        if ext is None or t.meta.get("confirmed"):
            return None
        # 停損當根盤中若已先順向推進達 profit_confirm，視為已確認（保守：不反手）
        if t.side == Side.LONG:
            profit = df.at[i, "high"] - t.entry_price
        else:
            profit = t.entry_price - df.at[i, "low"]
        if profit >= p.profit_confirm:
            return None
        c = df.at[i, "close"]
        broke = (c > ext) if t.side == Side.SHORT else (c < ext)
        if not broke:
            return None
        return self._reverse_order(ctx, t.side, ext)

    def on_bar(self, ctx: Context):
        p, df, i = self.p, ctx.df, ctx.i
        sess = df.at[i, "session"]

        if ctx.stopped is not None and ctx.pos is None:
            rev = self._maybe_reverse(ctx)
            if rev:
                return rev

        if ctx.pos is not None:
            pos = ctx.pos
            b = ctx.bar()
            if self._update_confirmed(ctx):
                # 已確認：折返回進場價（含）以下 → 撤單平倉，不反手（p.233, 236）
                if ctx.i > pos.entry_i and pos.profit(b["close"]) <= 0:
                    return [Order.exit("折返停利")]
                return None
            # 未確認：收盤反向突破訊號前的相對高/低點（濾網線）→ 不等停損，當根停損並反手（p.235）
            ext = pos.meta.get("ext_price")
            if ext is not None and ctx.i > pos.entry_i:
                broke = (b["close"] > ext) if pos.side == Side.SHORT else (b["close"] < ext)
                if broke:
                    return self._reverse_order(ctx, pos.side, float(ext))
            return None

        hit = self.detect(df, i)
        if hit is None:
            return None
        side, ext, reason = hit
        b = df.iloc[i]
        stop = ext + p.stop_points if side == Side.SHORT else ext - p.stop_points
        if abs(float(b["close"]) - stop) > p.max_risk:  # F4
            return None
        if p.no_entry_after is not None and hasattr(b["time"], "time") and b["time"].time() > p.no_entry_after:
            return None  # F5
        if p.no_repeat_after_loss:  # F6
            for t in ctx.trades:
                if df.at[t.entry_i, "session"] == sess and t.side == side and t.pnl <= 0:
                    return None
        return [Order.enter(side, stop=stop, reason=reason, ext_price=ext,
                            sig_high=float(b["high"]), sig_low=float(b["low"]))]
