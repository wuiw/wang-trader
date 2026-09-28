"""sg-08 擴量買訊／空訊（讀書會整理，書外方法；與書中 q2-05-02 極端位置最大量不同）。

規格文件：methods/讀書會/sg-08-擴量買訊空訊.md

來源（期跡奇績讀書會 g3 社團，助教說明；作者原始貼文不在資料內）：
  - 2023-10-06 post 1510250073121082 留言：助教「大台，3623-1523=2100，超過2000口，也是符合定義」
    「擴量超過2000即可」；學員覆述「前一根兩千以下，第二根擴量超過兩千，第三根沒創高就是空訊了。
    如果第一根超過兩千，那這樣要擴量超過三倍才能算訊號」（助教未否認）；助教答適用週期「5分」。
  - 2023-07-07 post 1461438344668922 留言：量符合（1303→3521）仍判「沒有擴量買訊」，理由「擴量買訊是黑黑紅組合」。
  - 2023-10-19/20 同串留言：助教「不是極端低，且訊號K是不創低的紅K才符合」；
    「定義：在盤中『最低點』發生擴量，『隔根』立刻出現不創低的紅K」（隔 3 根才出現不算）。
  - 三倍的算法：2021-02-22 post 892897854856310 學員「前一根是3888要3倍才算11664」（擴量K量 ≥ 前一根×3）。

訊號（第 i 根收盤判定；e＝i−1 為擴量K、e−1 為前一根，三根須同一盤別）：
  買訊：
    1. e 的低點為當下盤中最低點（low[e] ＝ 盤中最低，含與先前低點相等）。
    2. 擴量：前一根量 ≤ base_volume（2000）時，量[e] − 量[e−1] > volume_increase（2000）；
       前一根量 > base_volume 時，量[e] > high_prev_ratio（3）× 量[e−1]。
    3. 黑黑紅：e−1 黑K、e 黑K、i 紅K（require_color_pattern，預設開）。
    4. 隔根不創低：low[i] ≥ low[e]，且必須是緊接的下一根（隔數根才出現不算）。
    → 第 i 根收盤買進。
  空訊：鏡像（盤中最高點擴量，紅紅黑，隔根不創高的黑K）。
停損（推論，原文未規定）：擴量K低點（空＝高點）；距離超過 stop_points（20）時改用 q2-01 均線訊號停損法
  （多＝收盤 −(10＋個位數)、空＝收盤 ＋(20−個位數)，個位數 0 時 20 點）。
出場：原文未規定；不設停利，持有至停損、反向訊號（引擎先平倉再反手）或收盤。

週期：程式不限週期；原文只用於 5 分K。口數門檻不依週期或價位縮放，其他週期使用者需自行調整。
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from wangtrader.core import Context, Order, Side, Strategy

METHOD_ID = "sg-08"


@dataclass
class Params:
    base_volume: float = 2000.0  # 前一根量上限（口），2023-10-06 post 1510250073121082
    volume_increase: float = 2000.0  # 擴量K比前一根多出的口數須 > 此值（同上）
    high_prev_ratio: float = 3.0  # 前一根已 > base_volume 時，擴量K量須 ≥ 前一根 × 此倍數（同上；892897854856310）
    require_color_pattern: bool = True  # 黑黑紅／紅紅黑（2023-07-07 post 1461438344668922）
    stop_points: float = 20.0  # 停損上限（推論，比照 sg-01）
    stop_min_offset: float = 10.0  # 均線訊號停損法固定部分（q2-01 p.13）
    stop_integer_points: float = 20.0  # 均線訊號停損法整數價位固定點數（q2-01 p.13）


def _digit_stop(side: Side, close_price: float, min_offset: float, integer_points: float) -> float:
    """均線訊號停損法（q2-01 p.13–14）：多＝收盤 −(10 + 個位數)；空＝收盤 +(20 − 個位數)；個位數 0 時固定點數。"""
    digit = int(round(close_price)) % 10
    if digit == 0:
        pts = integer_points
    elif side == Side.LONG:
        pts = min_offset + digit
    else:
        pts = 2 * min_offset - digit
    return close_price - pts if side == Side.LONG else close_price + pts


class VolumeExpansion(Strategy):
    method_id = METHOD_ID

    def __init__(self, **kw) -> None:
        self.p = Params(**kw)

    def expanded(self, v_prev: float, v_ext: float) -> bool:
        """擴量判定：前一根 ≤ base_volume 時看增量，否則看倍數。"""
        p = self.p
        if v_prev != v_prev or v_ext != v_ext:
            return False
        if v_prev <= p.base_volume:
            return v_ext - v_prev > p.volume_increase
        return v_ext >= p.high_prev_ratio * v_prev

    def detect(self, df: pd.DataFrame, i: int) -> tuple[Side, float] | None:
        """第 i 根收盤時檢查訊號；回傳 (方向, 擴量K極端價)。"""
        if i < 2:
            return None
        e, b = i - 1, i - 2
        sess = df.at[i, "session"]
        if df.at[e, "session"] != sess or df.at[b, "session"] != sess:
            return None
        if not self.expanded(float(df.at[b, "volume"]), float(df.at[e, "volume"])):
            return None
        o, c = df["open"], df["close"]
        red = lambda k: c.iat[k] > o.iat[k]  # noqa: E731
        black = lambda k: c.iat[k] < o.iat[k]  # noqa: E731
        colors = not self.p.require_color_pattern
        # 買訊：擴量K在盤中最低點，隔根不創低
        if df.at[e, "low"] <= df.at[e, "sess_low"] and df.at[i, "low"] >= df.at[e, "low"]:
            if colors or (black(b) and black(e) and red(i)):
                return Side.LONG, float(df.at[e, "low"])
        # 空訊：擴量K在盤中最高點，隔根不創高
        if df.at[e, "high"] >= df.at[e, "sess_high"] and df.at[i, "high"] <= df.at[e, "high"]:
            if colors or (red(b) and red(e) and black(i)):
                return Side.SHORT, float(df.at[e, "high"])
        return None

    def on_bar(self, ctx: Context):
        p, df, i = self.p, ctx.df, ctx.i
        hit = self.detect(df, i)
        if hit is None:
            return None
        side, ref = hit
        entry = float(df.at[i, "close"])
        stop = ref
        if abs(entry - stop) > p.stop_points:
            stop = _digit_stop(side, entry, p.stop_min_offset, p.stop_integer_points)
        name = "擴量買訊" if side == Side.LONG else "擴量空訊"
        return [Order.enter(side, stop=float(stop), reason=name)]
