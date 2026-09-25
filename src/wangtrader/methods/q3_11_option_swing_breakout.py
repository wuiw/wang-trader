"""q3-11 以選擇權進行波段操作（MA100 + RSI極端值 + 峰谷突破）（《期貨奇績3》第十一章，p.245–261）。

規格文件：methods/期貨奇績3/q3-11-選擇權波段突破.md

本方法為波段方法（intraday=False），程式只產生「標的」的多空方向訊號（對應買進CALL／PUT）與出場，
不模擬選擇權報價；履約價只用來決定停利機制何時啟動（見出場），不做權利金運算。

訊號（p.246–253）：以 MA(ma_period)（原文MA100，相當於日線10日均線）分多空趨勢：
  買進CALL：
    C1 價格收盤由MA下方向上穿越MA → 開始追蹤一段「CALL 腿」，起漲谷位 origin＝穿越前價格在
       MA 下方期間的最低點（p.248-249「不能跌到創新低點」＝突破均線前的起始谷點）。
    C2 有效峰位：連續推升遇黑K不再創新高的拉回，且本段追蹤（穿越均線或上一次訊號之後）的推升
       過程 RSI 曾觸及 rsi_extreme_high（或極接近，容許 rsi_near_tol，p.255）→ 以推升最高點為
       峰位（C3 水平線）。遇黑K拉回時若 RSI 尚未觸及門檻，峰位不成立，繼續向上尋找（p.253）。
    C4 拉回不可跌破 origin（任何階段，含尚未確認峰位時），且峰位確認後拉回持續不可超過
       max_pullback_bars；違反任一者 → 取消本段觀察（C5），須等價格再次向上穿越MA才重新追蹤
       （p.249「取消觀察，重新等待突破均線」）。
    C6 K線收盤重新突破峰位水平線 → 買進CALL訊號；訊號後同段行情繼續追蹤下一個峰位（p.249
       「D點突破C高…如果在C沒有進場，最慢在D補進場」）。
  買進PUT：對稱鏡像（C1'–C6'）。
  兩側各自獨立追蹤：持有 CALL 腿時價格若收盤跌破MA，亦同時開始追蹤 PUT 腿（p.260-261「對開」：
  買進賣權之後又出現買進買權訊號，兩邊訊號都成立）。核心引擎為單一部位，反向訊號會反手平掉既有
  部位，無法真正同時持有兩腳，此為核心限制。
進場（p.247, 249）：C6/C6' 收盤確認當下進場。進場工具（p.245, 247）：價外 otm_steps 檔（預設 2）
  的CALL／PUT，履約價以 strike_step（預設100，書中範例 9663→9900 CALL、10845→10600 PUT）推算，
  記在 meta（strike）。
停損（p.260–261）：選擇權買方不另設停損，最大風險為已付權利金（stop=None）。
出場（exit_mode，p.258–260，四法並列，書中未定優先序）：
  arm_at_strike=True（預設）：標的價格觸及所買選擇權履約價、使價外部位轉為價平之後，才啟動停利
  （p.258「抵達10600，使得原先的價外二檔賣權變成價平，此時啟動突破MA10做為移動停利」；p.259
  「抵達9900…接著若啟動跌破MA10做為停利」；p.252「使得買權進入價內階段，則準備獲利出場」）。
  未觸及履約價前不出場（書中持有到結算，權利金即損失上限；本模組無結算日，持有至反向訊號反手或
  資料結束）。
  "ma10"：以 MA(ma10_period) 移動停利，多單收盤跌破／空單收盤突破即出場（p.258-259）。
  "retrace"：創新高（CALL）/新低（PUT）後回落/反彈達 retrace_points 停利（p.258-259）。
  "prev_day"：收盤跌破（CALL）/突破（PUT）前一交易日低／高點停利（沿用 core.bars 的 prev_high/prev_low）。
  "hold"：不主動出場（近似留倉至結算，本模組無結算日資訊，以「持有至資料結束」近似）。

週期：不限（書中原文以30分鐘K線為例，本模組以 ma_period/rsi_period 等參數表示，不寫死週期）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd

from wangtrader.core import Context, Order, Side, Strategy
from wangtrader.core.exits import ma_exit
from wangtrader.core.indicators import rsi, sma

METHOD_ID = "q3-11"


@dataclass
class Params:
    ma_period: int = 100  # p.246，趨勢分界（書中亦可調整為MA120/MA200）
    rsi_period: int = 5  # 原文未指定 RSI 參數，採核心預設值（推論）
    rsi_extreme_high: float = 90.0  # p.246-247
    rsi_extreme_low: float = 10.0  # p.246-247
    rsi_near_tol: float = 1.0  # p.255，RSI極接近門檻亦視為達成（如89.41）
    max_pullback_bars: int = 20  # C5：書中以「天」描述（約1天內佳、逾10天過久），本參數為根數近似值，
    #                              需依實際週期調整
    ma10_period: int = 10  # p.258，MA10移動停利
    retrace_points: float = 100.0  # p.258-259，創高低反彈折返停利
    exit_mode: str = "ma10"  # "ma10" | "retrace" | "prev_day" | "hold"，書中四法並列未定優先序
    arm_at_strike: bool = True  # 觸及履約價（價外轉價平）後才啟動停利（p.252, 258-259）
    strike_step: float = 100.0  # 履約價間距（書中範例皆為 100 點）
    otm_steps: int = 2  # 價外檔數（p.245, 258-259「價外二檔」；0＝價平）


@dataclass
class _LegState:
    origin: float  # 起漲谷位（CALL）／起跌峰位（PUT）
    cand: float  # 目前候選峰位／谷位價
    cand_i: int
    rsi_hit: bool = False  # 本段追蹤的推升／下殺過程中 RSI 是否曾觸及門檻（p.253）
    confirmed: float | None = None  # 已確認之峰位／谷位水平線
    pullback_start: int | None = None


class OptionSwingBreakout(Strategy):
    method_id = METHOD_ID
    intraday = False  # 波段方法，可跨日持有

    def __init__(self, **kw) -> None:
        self.p = Params(**kw)
        self._call: _LegState | None = None
        self._put: _LegState | None = None
        self._regime: int | None = None  # 1：收盤在MA上；-1：在MA下；None：未知
        self._below_low: float | None = None  # 價格在MA下方期間的最低點（下次向上穿越的 origin）
        self._above_high: float | None = None  # 價格在MA上方期間的最高點（下次向下穿越的 origin）

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["ma"] = sma(df["close"], self.p.ma_period)
        df["ma10"] = sma(df["close"], self.p.ma10_period)
        df["rsi"] = rsi(df["close"], self.p.rsi_period)
        return df

    # ---------- 履約價與停利啟動 ----------
    def _strike(self, entry: float, side: Side) -> float:
        """價外 otm_steps 檔的履約價：以最接近進場價的履約價為價平，再往價外推 otm_steps 檔。"""
        step = self.p.strike_step
        atm = math.floor(entry / step + 0.5) * step
        return atm + self.p.otm_steps * step * int(side)

    def _arm_target(self, entry: float, side: Side) -> float:
        """停利啟動所需的順向獲利點數（標的觸及履約價＝價外轉價平，p.258-259）。"""
        if not self.p.arm_at_strike:
            return 0.0
        return max(0.0, (self._strike(entry, side) - entry) * int(side))

    # ---------- 腿的逐根推進 ----------
    def _step_call(self, df: pd.DataFrame, i: int) -> Order | None:
        p, b, st = self.p, df.iloc[i], self._call
        if b["low"] < st.origin:  # C4：跌破起漲谷點 → 取消觀察，等待重新突破均線（p.249）
            self._call = None
            return None
        rv = b["rsi"]
        black = b["close"] < b["open"]
        if st.confirmed is None:
            new_high = b["high"] >= st.cand
            if new_high:
                st.cand, st.cand_i = float(b["high"]), i
            if not pd.isna(rv) and rv >= p.rsi_extreme_high - p.rsi_near_tol:
                st.rsi_hit = True
            if black and not new_high and st.rsi_hit:  # 遇黑K不再創新高的拉回 + RSI 曾觸及（p.253）
                st.confirmed, st.pullback_start = st.cand, i
            return None  # RSI 未觸及門檻 → 峰位不成立，繼續向上尋找
        if (i - st.pullback_start) > p.max_pullback_bars:  # C5：拉回拖太久
            self._call = None
            return None
        if b["close"] > st.confirmed:  # C6：收盤突破峰位水平線
            line = st.confirmed
            self._call = _LegState(origin=st.origin, cand=max(line, float(b["high"])), cand_i=i)
            entry = float(b["close"])
            strike = self._strike(entry, Side.LONG)
            return Order.enter(
                Side.LONG, stop=None, reason="選擇權波段突破-買進CALL",
                option_side="CALL", strike=strike, strike_hint=f"價外{p.otm_steps}檔 {strike:.0f} CALL，儘量跨月OP",
                peak_price=line, arm_target=self._arm_target(entry, Side.LONG),
            )
        return None

    def _step_put(self, df: pd.DataFrame, i: int) -> Order | None:
        p, b, st = self.p, df.iloc[i], self._put
        if b["high"] > st.origin:  # C4'：反彈突破起跌峰點 → 取消觀察
            self._put = None
            return None
        rv = b["rsi"]
        red = b["close"] > b["open"]
        if st.confirmed is None:
            new_low = b["low"] <= st.cand
            if new_low:
                st.cand, st.cand_i = float(b["low"]), i
            if not pd.isna(rv) and rv <= p.rsi_extreme_low + p.rsi_near_tol:
                st.rsi_hit = True
            if red and not new_low and st.rsi_hit:  # 遇紅K不再創新低的反彈 + RSI 曾觸及（p.253）
                st.confirmed, st.pullback_start = st.cand, i
            return None
        if (i - st.pullback_start) > p.max_pullback_bars:  # C5'
            self._put = None
            return None
        if b["close"] < st.confirmed:  # C6'：收盤跌破谷位水平線
            line = st.confirmed
            self._put = _LegState(origin=st.origin, cand=min(line, float(b["low"])), cand_i=i)
            entry = float(b["close"])
            strike = self._strike(entry, Side.SHORT)
            return Order.enter(
                Side.SHORT, stop=None, reason="選擇權波段突破-買進PUT",
                option_side="PUT", strike=strike, strike_hint=f"價外{p.otm_steps}檔 {strike:.0f} PUT，儘量跨月OP",
                trough_price=line, arm_target=self._arm_target(entry, Side.SHORT),
            )
        return None

    # ---------- 出場 ----------
    def _check_exit(self, ctx: Context) -> Order | None:
        p, pos, b = self.p, ctx.pos, ctx.df.iloc[ctx.i]
        if p.exit_mode == "hold" or ctx.i <= pos.entry_i:
            return None
        target = float(pos.meta.get("arm_target", 0.0))
        if p.exit_mode == "ma10":
            return ma_exit(ctx, "ma10", target)  # 達 target（觸及履約價）後隔根起以 MA10 追蹤
        if pos.max_profit() < target:  # 未觸及履約價（仍為價外）→ 停利尚未啟動
            return None
        if p.exit_mode == "retrace":
            if pos.side == Side.LONG and (pos.best - b["close"]) >= p.retrace_points:
                return Order.exit("創高折返停利")
            if pos.side == Side.SHORT and (b["close"] - pos.best) >= p.retrace_points:
                return Order.exit("創低反彈停利")
            return None
        if p.exit_mode == "prev_day":
            if pos.side == Side.LONG and not pd.isna(b["prev_low"]) and b["close"] < b["prev_low"]:
                return Order.exit("跌破前一天低點停利")
            if pos.side == Side.SHORT and not pd.isna(b["prev_high"]) and b["close"] > b["prev_high"]:
                return Order.exit("突破前一天高點停利")
            return None
        return None

    # ---------- 主流程 ----------
    def on_bar(self, ctx: Context):
        df, i = ctx.df, ctx.i
        b = df.iloc[i]
        orders: list[Order] = []

        if ctx.pos is not None:
            ex = self._check_exit(ctx)
            if ex:
                orders.append(ex)

        # 均線側別與穿越偵測（C1／C1'）：只用收盤與當根之前累積的極值
        lo, hi = float(b["low"]), float(b["high"])
        ma = b["ma"]
        regime = self._regime
        if ma != ma:  # 均線尚未可用：兩側極值都先累積
            self._below_low = lo if self._below_low is None else min(self._below_low, lo)
            self._above_high = hi if self._above_high is None else max(self._above_high, hi)
        elif b["close"] > ma and regime != 1:
            origin = lo if self._below_low is None else min(self._below_low, lo)
            if self._call is None:
                self._call = _LegState(origin=origin, cand=hi, cand_i=i)
            regime, self._above_high, self._below_low = 1, hi, None
        elif b["close"] < ma and regime != -1:
            origin = hi if self._above_high is None else max(self._above_high, hi)
            if self._put is None:
                self._put = _LegState(origin=origin, cand=lo, cand_i=i)
            regime, self._below_low, self._above_high = -1, lo, None
        elif regime == 1:
            self._above_high = hi if self._above_high is None else max(self._above_high, hi)
        elif regime == -1:
            self._below_low = lo if self._below_low is None else min(self._below_low, lo)
        else:
            self._below_low = lo if self._below_low is None else min(self._below_low, lo)
            self._above_high = hi if self._above_high is None else max(self._above_high, hi)
        self._regime = regime

        # 兩側腿各自推進（對開：互不牽制，p.260-261）
        if self._call is not None:
            od = self._step_call(df, i)
            if od:
                orders.append(od)
        if self._put is not None:
            od = self._step_put(df, i)
            if od:
                orders.append(od)
        return orders or None
