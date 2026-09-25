"""q2-06-02 一分鐘 KD 背離訊號（《期貨奇績2》第六章 背離訊號總整理，p.203–217）。

規格文件：methods/期貨奇績2/q2-06-02-KD背離訊號.md

訊號（p.203）：
  背離向下（放空）：
    C1 前波峰位對應 D 值 > d_overbought（預設80）且形成死亡交叉（P1）。
    C2 價格拉回，K 值曾跌破50（拉回段 K 值最低點 < 50）但全程不低於 k_extreme（預設20），並形成黃金交叉。
    C3 價格再度突破前波峰位創新高時，D 值不再超過 d_overbought（黃金交叉後至第二次死叉為止 D 值皆 ≤ 80），
       K 值也低於 P1 當時的 K 值。
    C4 此時出現死亡交叉，即為放空訊號。
    C5 兩個死亡交叉中間只能夾一個黃金交叉，多一次交叉即視為無效（本模組實作：wait_death 階段
       中再出現黃金交叉即判定違反 C5，整輪作廢重新尋找 P1；死亡交叉若不滿足 C3 亦視為失敗，
       但若該死叉本身 D>80 可另作新 P1，屬因果延伸解讀，見模組末待確認事項）。
  背離向上（買進）：C1'–C5' 鏡像規則（p.203, 207）。
進場（p.203, 207, 212）：
  再次出現死叉（放空）／金叉（買進）之當根即進場；若該根 K 線方向不符（死叉卻是紅K、
  金叉卻是黑K），順延至隨後第一根方向正確的 K 線進場，逾 confirm_wait 根仍未出現則放棄
  （書中未給明確等待根數，比照 q3-01 p.20 設參數，屬推論預設值）。
  可選加開 MA8／SAR 濾網（p.212）：require_ma_or_sar=True 時，進場根還須收盤站上/跌破 MA8
  或穿越 SAR，預設關閉（書中僅以「可搭配」描述，非硬性規則）。
跨日規則（p.213）：背離兩端點跨日時，開盤跳空 < gap_carry_points（預設10）視為無縫接軌，
  延用前一日尾盤狀態；跳空 ≥ 門檻則重新起算（不延續前一日的 P1／待確認狀態）。
停損（p.209「依背離低點(B)為停損」）：stop_mode 三選一：
  "endpoint"：背離端點 B＝第二個端點（本次訊號創新高/新低的極端價，即當下盤中最高/最低），非前波峰谷位 P1。
  "ma_signal"：比照第一章均線訊號停損法（q2-01 p.13）：
    多＝收盤−(10+收盤個位數)；空＝收盤+(10+收盤個位數)。
  "combined"（預設，原文明確：p.209「取兩者較低者」為多單、鏡像取較高者為空單）：
    多＝min(endpoint, ma_signal)；空＝max(endpoint, ma_signal)。
  若進場距停損 > stop_points（預設20），先忽略，等拉回縮小距離後掛限價補進場。
出場／反手（p.209）：書中未提供背離成功後的一般停利規則，僅提供失敗時的反手停損：
  多單進場後最大獲利未達 reversal_bounce_points（預設20點）即再度收盤跌破背離端點（B，
  即本次訊號用來認定新低的價位）→ 停損並反手放空，新停損＝該波反彈最高點（倒N型結構的 0 點；
  書中只說「將新的停損位置設好」，屬推論）。
  空單鏡像（mirror_reversal，預設開啟，屬推論）。本模組以「跌破/突破背離端點且未達反彈門檻」
  簡化 123 步驟倒N型/正N型判斷，未另外實作通用 N 型結構偵測（見待確認事項）。
過濾：
  F1 端點之間出現超過一次反向交叉，訊號無效（C5，p.205, 207–208）。
  F2 端點 D 值未達嚴格門檻（P1 需 >80／<20），未達標即使價格創新高/低也不構成訊號（p.203）。
  F3 交叉當根 K 線方向不符，順延至後續方向正確 K 線（p.207）。
  F4 跨日跳空 ≥ gap_carry_points，不延用前一日狀態（p.213）。

週期：不限。所有門檻以點數／根數表示。KD 採自訂界限 KD 指標（沿用核心 `indicators.kd`）。
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from wangtrader.core import Context, Order, Side, Strategy
from wangtrader.core.indicators import kd, sar, sma

METHOD_ID = "q2-06-02"


@dataclass
class Params:
    d_overbought: float = 80.0    # C1/C3（p.203），D 值超買門檻
    d_oversold: float = 20.0      # C1'/C3'（p.203），D 值超賣門檻
    k_mid: float = 50.0           # C2（p.203），拉回/反彈時 K 值須跌破/突破的中線
    k_extreme: float = 20.0       # C2（p.203），拉回不能低於／反彈不能高於 100-k_extreme
    kd_n: int = 9
    kd_k_period: int = 3
    kd_d_period: int = 3
    confirm_wait: int = 10        # F3：等待方向正確K線的根數上限（原文未給明確根數，推論）
    require_ma_or_sar: bool = False  # p.212：可選加開 MA8／SAR 濾網，預設關閉（原文為建議非硬性）
    ma_period: int = 8
    gap_carry_points: float = 10.0   # F4（p.213）
    stop_points: float = 20.0
    max_wait: int = 10            # 補進場等待根數（原文未給明確根數，推論比照 q3-01 p.20）
    stop_mode: str = "combined"   # "endpoint" | "ma_signal" | "combined"（p.209 原文機制）
    reversal_bounce_points: float = 20.0  # p.209：反彈未達此點數即視為背離失敗
    mirror_reversal: bool = True  # 空單反手規則為鏡像推論，預設開啟


@dataclass
class _Chain:
    phase: str = "idle"  # idle -> wait_gold -> wait_death
    p1_bar: int | None = None
    p1_price: float | None = None
    p1_k: float | None = None
    confirm_bar: int | None = None
    confirm_level: float | None = None  # 停損端點 B
    confirm_b: float | None = None      # 背離端點 B（本次訊號新高/新低的極端價）
    k_seen: float | None = None         # 拉回（反彈）段 K 值極值：空＝最低、多＝最高（C2）
    d_seen: float | None = None         # 黃金（死亡）交叉後 D 值極值：空＝最高、多＝最低（C3）


def _cross(df: pd.DataFrame, i: int) -> str | None:
    if i == 0:
        return None
    pk, pd_ = df.at[i - 1, "k"], df.at[i - 1, "d"]
    k_, d_ = df.at[i, "k"], df.at[i, "d"]
    if pk != pk or pd_ != pd_ or k_ != k_ or d_ != d_:  # NaN
        return None
    if pk <= pd_ and k_ > d_:
        return "gold"
    if pk >= pd_ and k_ < d_:
        return "death"
    return None


def _ma_signal_stop(close: float, side: Side) -> float:
    """比照 q2-01 均線訊號停損法（p.13）：收盤 ∓ (10 + 個位數)。"""
    ones = int(round(abs(close))) % 10
    offset = 10 + ones
    return close - offset if side == Side.LONG else close + offset


def _track_side(chain: _Chain, df: pd.DataFrame, i: int, p: Params, *, is_short: bool):
    """更新單一方向（空頭死叉鏈／多頭金叉鏈）狀態，成立訊號時回傳 (level, b_ref)。"""
    cross = _cross(df, i)
    d_, k_, close_ = df.at[i, "d"], df.at[i, "k"], df.at[i, "close"]
    ext_col = "sess_high" if is_short else "sess_low"
    beyond = (lambda a, b: a > b) if is_short else (lambda a, b: a < b)
    own_cross = "death" if is_short else "gold"
    other_cross = "gold" if is_short else "death"
    p1_trigger = (d_ > p.d_overbought) if is_short else (d_ < p.d_oversold)
    pullback_ok = (p.k_extreme <= k_ < p.k_mid) if is_short else ((100 - p.k_mid) < k_ <= (100 - p.k_extreme))

    if chain.confirm_bar is not None:
        if i - chain.confirm_bar > p.confirm_wait:
            chain.confirm_bar = None
            return None
        is_dir_bar = (df.at[i, "close"] < df.at[i, "open"]) if is_short else (df.at[i, "close"] > df.at[i, "open"])
        if is_dir_bar:
            level, b_ref = chain.confirm_level, chain.confirm_b
            chain.confirm_bar = None
            return (level, b_ref)
        return None

    if chain.phase == "idle":
        if cross == own_cross and p1_trigger:
            chain.phase, chain.p1_bar, chain.p1_price, chain.p1_k = "wait_gold", i, df.at[i, ext_col], k_
            chain.k_seen = k_
        return None

    if chain.phase == "wait_gold":
        chain.k_seen = min(chain.k_seen, k_) if is_short else max(chain.k_seen, k_)
        if (k_ < p.k_extreme) if is_short else (k_ > 100 - p.k_extreme):  # C2：拉回不能低於20（反彈不能高於80）
            chain.phase, chain.p1_bar = "idle", None
            return None
        if cross == own_cross:  # 又一次同向交叉，尚未出現反向交叉即更新P1
            if p1_trigger:
                chain.p1_bar, chain.p1_price, chain.p1_k, chain.k_seen = i, df.at[i, ext_col], k_, k_
            else:
                chain.phase, chain.p1_bar = "idle", None
            return None
        if cross == other_cross:
            crossed_mid = (chain.k_seen < p.k_mid) if is_short else (chain.k_seen > 100 - p.k_mid)
            if crossed_mid:  # C2：拉回段 K 值曾跌破（突破）50
                chain.phase, chain.d_seen = "wait_death", d_
            else:
                chain.phase, chain.p1_bar = "idle", None
        return None

    # chain.phase == "wait_death"：等待第二次同向交叉（own_cross）確認訊號
    chain.d_seen = max(chain.d_seen, d_) if is_short else min(chain.d_seen, d_)
    if cross == other_cross:  # C5：中間又夾了第二次反向交叉，違規，整輪作廢
        chain.phase, chain.p1_bar = "idle", None
        return None
    if cross == own_cross:
        b_price = df.at[i, ext_col]  # 第二端點 B＝本次創新高（低）的極端價
        new_extreme = beyond(b_price, chain.p1_price)
        d_ok = (chain.d_seen <= p.d_overbought) if is_short else (chain.d_seen >= p.d_oversold)  # C3：D 不再過80
        k_ok = (k_ < chain.p1_k) if is_short else (k_ > chain.p1_k)
        if new_extreme and d_ok and k_ok:
            level = b_ref = float(b_price)
            chain.phase, chain.p1_bar = "idle", None
            is_dir_bar = (close_ < df.at[i, "open"]) if is_short else (close_ > df.at[i, "open"])
            if is_dir_bar:
                return (level, b_ref)
            chain.confirm_bar, chain.confirm_level, chain.confirm_b = i, level, b_ref
            return None
        if p1_trigger:  # 本次死叉不合格，但其本身可另作新的P1
            chain.p1_bar, chain.p1_price, chain.p1_k, chain.k_seen = i, df.at[i, ext_col], k_, k_
            chain.phase = "wait_gold"
        else:
            chain.phase, chain.p1_bar = "idle", None
    return None


class KdDivergence(Strategy):
    method_id = METHOD_ID

    def __init__(self, **kw) -> None:
        self.p = Params(**kw)
        self._hi = _Chain()
        self._lo = _Chain()

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        kdf = kd(df, n=self.p.kd_n, k_period=self.p.kd_k_period, d_period=self.p.kd_d_period)
        df["k"], df["d"] = kdf["k"], kdf["d"]
        df["ma8"] = sma(df["close"], self.p.ma_period)
        s = sar(df)
        df["sar"], df["sar_trend"] = s["sar"], s["trend"]
        return df

    def _quality_ok(self, df: pd.DataFrame, i: int, side: Side) -> bool:
        if not self.p.require_ma_or_sar:
            return True
        b = df.iloc[i]
        if side == Side.LONG:
            return bool(b["close"] > b["ma8"] or (b["sar_trend"] == 1 and b["close"] > b["sar"]))
        return bool(b["close"] < b["ma8"] or (b["sar_trend"] == -1 and b["close"] < b["sar"]))

    def _stop(self, close: float, level: float, side: Side) -> float:
        ma = _ma_signal_stop(close, side)
        if self.p.stop_mode == "endpoint":
            return level
        if self.p.stop_mode == "ma_signal":
            return ma
        return min(level, ma) if side == Side.LONG else max(level, ma)

    def on_bar(self, ctx: Context):
        p, df, i = self.p, ctx.df, ctx.i
        bar_no = df.at[i, "bar_no"]
        if bar_no == 0:
            prevc = df.at[i, "prev_close"]
            gap_big = pd.isna(prevc) or abs(df.at[i, "open"] - prevc) >= p.gap_carry_points
            if gap_big:
                self._hi, self._lo = _Chain(), _Chain()

        short_sig = _track_side(self._hi, df, i, p, is_short=True)
        long_sig = _track_side(self._lo, df, i, p, is_short=False)

        if ctx.pos is not None:
            return self._check_reversal(ctx)

        close_ = df.at[i, "close"]
        orders: list[Order] = []
        for side, sig in ((Side.SHORT, short_sig), (Side.LONG, long_sig)):
            if sig is None:
                continue
            level, b_ref = sig
            if not self._quality_ok(df, i, side):
                continue
            stop = self._stop(close_, level, side)
            reason = "KD背離向下" if side == Side.SHORT else "KD背離向上"
            if abs(close_ - stop) <= p.stop_points:
                orders.append(Order.enter(side, stop=stop, reason=reason, b_ref=b_ref))
            else:
                limit = stop + p.stop_points * int(side)
                orders.append(Order.enter_limit(side, limit=limit, expire=p.max_wait, stop=stop,
                                                 reason=reason + "(補進場)", b_ref=b_ref))
        return orders or None

    def _check_reversal(self, ctx: Context):
        pos = ctx.pos
        if pos.side == Side.SHORT and not self.p.mirror_reversal:
            return None
        b_ref = pos.meta.get("b_ref")
        if b_ref is None:
            return None
        bounce = pos.max_profit()
        if bounce >= self.p.reversal_bounce_points:
            return None
        b = ctx.bar()
        broke = (b["close"] < b_ref) if pos.side == Side.LONG else (b["close"] > b_ref)
        if not broke:
            return None
        new_side = Side.SHORT if pos.side == Side.LONG else Side.LONG
        new_stop = pos.best  # 反手單停損＝該波反彈（回檔）極值，即倒N型/正N型的 0 點（推論）
        reason = "倒N型反手" if pos.side == Side.LONG else "正N型反手"
        return [Order.enter(new_side, stop=new_stop, reason=reason)]
