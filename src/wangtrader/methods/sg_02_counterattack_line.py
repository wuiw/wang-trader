"""sg-02 逆襲線（逆襲組合）買訊／空訊（讀書會整理，書外方法）。

規格文件：methods/讀書會/sg-02-逆襲線.md
規格整理：extracted/study-group/newmethods/逆襲線.md

來源：作者原文 2017-02-09（截圖見 2021-02-18 助教貼文 post 1359240967757147 第 4 張圖）：
  「逆襲線，一黑一紅，低點差距在1點以內，黑K跌點在7點以上，紅K漲點在5點以上，高點相當，典型絕地反攻。
   可以當作停利看待，如果要當作訊號，宜在極端位置，例如今天。」
  貼文：「它通常作為停利之用，作為訊號，宜在當天極端位置」。

訊號（第 i−1 根＝前根、第 i 根＝訊號根）：
  買訊（作者原文）：前根黑K、訊號根紅K；兩根低點差 ≤ low_tol（1 點）；黑K跌點 ≥ first_move（7）、
    紅K漲點 ≥ second_move（5）→ 訊號根收盤買進（進場價位原文未規定，收盤進場為推論）。
  空訊（鏡像，2020-04-24 post 1121690624845517 學員整理、助教確認「OK」）：前根紅K 漲 ≥7、訊號根黑K 跌 ≥5、
    兩根高點「同高 或 差距1點」。enable_short 控制，預設開啟。
  漲跌點基準 move_basis（原文未明，助教回覆內容缺失 → 參數）：
    "close_diff"（預設）：該根收盤 − 前一根收盤（該根為當日首根時用平盤）；
    "body"：該根實體（收盤 − 開盤）。
  「高點相當」（作者原文，無數值）：high_match_tol，預設 None（不檢查）；給數值時多方要求兩根高點差 ≤ 該值，
    空方鏡像為兩根低點差。
  極端位置 extreme_mode（作者：「作為訊號，宜在當天極端位置」，未給判定方式 → 參數）：
    "session"（預設）：組合的低點（空方為高點）即當下盤中最低（最高），容差 extreme_tol（0 點）；
    "prev_close"：組合低點距平盤 ≥ extreme_from_prev_close（40 點，借 q3 極端位置的距平盤門檻，推論）；
    "both"：兩者皆須成立；"none"：不檢查（助教實例也有非極端處「逆襲線搶反彈」）。
停損：助教 2020-07-30（post 1198108710537041）「建議停損抓20點」「K棒本身沒有很大(逆襲線), 則將停損放大到20點」
  → stop_mode="fixed"（預設）：進場價 ∓ stop_points（20）。
  stop_mode="structure"（SG_SPEC 通則，推論）：組合極端點（兩根最低／最高）；距離超過 stop_points 改用 q2-01
  均線訊號停損法（多＝收盤 −(10＋個位數)、空＝收盤 ＋(20−個位數)，個位數 0 時 20 點）。
出場：原文未規定；不設停利，持有至停損、反向訊號（引擎先平倉再反手；即作者說的「遇到這種組合得考慮平倉」）或收盤。

週期：不限。所有門檻以點數表示。
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from wangtrader.core import Context, Order, Side, Strategy

METHOD_ID = "sg-02"

MOVE_BASES = ("close_diff", "body")
EXTREME_MODES = ("session", "prev_close", "both", "none")
STOP_MODES = ("fixed", "structure")


@dataclass
class Params:
    low_tol: float = 1.0  # 低點差距在1點以內（作者原文；空方高點「同高 或 差距1點」助教 2020-04-26）
    first_move: float = 7.0  # 黑K跌點在7點以上（作者原文；空方為紅K漲 7 以上，助教確認）
    second_move: float = 5.0  # 紅K漲點在5點以上（作者原文；空方為黑K跌 5 以上，助教確認）
    move_basis: str = "close_diff"  # 漲跌點基準（原文未明）："close_diff" 或 "body"
    high_match_tol: float | None = None  # 「高點相當」（作者原文，無數值）；None 不檢查
    enable_short: bool = True  # 空方鏡像（學員整理、助教確認 2020-04-26）
    extreme_mode: str = "session"  # 「宜在當天極端位置」（作者原文，判定方式推論）
    extreme_tol: float = 0.0  # session 模式：組合低點距當下盤中最低的容差（推論）
    extreme_from_prev_close: float = 40.0  # prev_close 模式：組合低點距平盤門檻（推論，借 q3 極端位置 40 點）
    stop_mode: str = "fixed"  # "fixed"＝助教 20 點；"structure"＝組合極端點（SG_SPEC 通則，推論）
    stop_points: float = 20.0  # 助教「建議停損抓20點」（2020-07-30）
    stop_min_offset: float = 10.0  # 均線訊號停損法固定部分（q2-01 p.13）
    stop_integer_points: float = 20.0  # 均線訊號停損法整數價位固定點數（q2-01 p.13）

    def __post_init__(self) -> None:
        if self.move_basis not in MOVE_BASES:
            raise ValueError(f"move_basis 須為 {MOVE_BASES}")
        if self.extreme_mode not in EXTREME_MODES:
            raise ValueError(f"extreme_mode 須為 {EXTREME_MODES}")
        if self.stop_mode not in STOP_MODES:
            raise ValueError(f"stop_mode 須為 {STOP_MODES}")


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


class CounterattackLine(Strategy):
    method_id = METHOD_ID

    def __init__(self, **kw) -> None:
        self.p = Params(**kw)

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        if self.p.move_basis == "body":
            df["move"] = df["close"] - df["open"]
        else:
            # 與前一根收盤差；當日首根用平盤（prev_close，不可信時為 NaN → 不成立）
            prev = df["close"].shift(1).where(df["bar_no"] > 0, df["prev_close"])
            df["move"] = df["close"] - prev
        return df

    def _extreme_ok(self, df: pd.DataFrame, i: int, side: Side, pair_ext: float) -> bool:
        p = self.p
        if p.extreme_mode == "none":
            return True
        ok_s = ok_p = True
        if p.extreme_mode in ("session", "both"):
            if side == Side.LONG:
                ok_s = pair_ext <= df.at[i, "sess_low"] + p.extreme_tol
            else:
                ok_s = pair_ext >= df.at[i, "sess_high"] - p.extreme_tol
        if p.extreme_mode in ("prev_close", "both"):
            pc = df.at[i, "prev_close"]
            if pd.isna(pc):
                ok_p = False
            elif side == Side.LONG:
                ok_p = pc - pair_ext >= p.extreme_from_prev_close
            else:
                ok_p = pair_ext - pc >= p.extreme_from_prev_close
        return bool(ok_s and ok_p)

    def detect(self, df: pd.DataFrame, i: int) -> tuple[Side, float] | None:
        """回傳 (方向, 組合極端點)；不成立回傳 None。"""
        p = self.p
        if i < 1 or df.at[i - 1, "session"] != df.at[i, "session"]:
            return None
        a, b = df.loc[i - 1], df.loc[i]
        ma, mb = a["move"], b["move"]
        if ma != ma or mb != mb:
            return None
        a_black, a_red = a["close"] < a["open"], a["close"] > a["open"]
        b_black, b_red = b["close"] < b["open"], b["close"] > b["open"]
        # 買訊：一黑一紅、低點差 ≤1、黑跌 ≥7、紅漲 ≥5
        if (
            a_black and b_red
            and abs(b["low"] - a["low"]) <= p.low_tol
            and -ma >= p.first_move and mb >= p.second_move
            and (p.high_match_tol is None or abs(b["high"] - a["high"]) <= p.high_match_tol)
        ):
            ext = float(min(a["low"], b["low"]))
            if self._extreme_ok(df, i, Side.LONG, ext):
                return Side.LONG, ext
        # 空訊（鏡像）：一紅一黑、高點差 ≤1、紅漲 ≥7、黑跌 ≥5
        if (
            p.enable_short
            and a_red and b_black
            and abs(b["high"] - a["high"]) <= p.low_tol
            and ma >= p.first_move and -mb >= p.second_move
            and (p.high_match_tol is None or abs(b["low"] - a["low"]) <= p.high_match_tol)
        ):
            ext = float(max(a["high"], b["high"]))
            if self._extreme_ok(df, i, Side.SHORT, ext):
                return Side.SHORT, ext
        return None

    def on_bar(self, ctx: Context):
        p, df, i = self.p, ctx.df, ctx.i
        hit = self.detect(df, i)
        if hit is None:
            return None
        side, ext = hit
        entry = float(df.at[i, "close"])
        if p.stop_mode == "fixed":
            stop = entry - p.stop_points if side == Side.LONG else entry + p.stop_points
        else:
            stop = ext
            if abs(entry - stop) > p.stop_points:
                stop = _digit_stop(side, entry, p.stop_min_offset, p.stop_integer_points)
        name = "逆襲線買訊" if side == Side.LONG else "逆襲線空訊"
        return [Order.enter(side, stop=float(stop), reason=name)]
