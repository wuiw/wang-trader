"""gq-01-01 大陽線／大陰線移動出場（《股技期招》第一章，p.1–4）。

規格文件：methods/股技期招/gq-01-01-大K線移動出場.md

本節**不含進場規則**（文件§4「原文未規定。本節只講持有部位期間的移動出場技巧」），
只提供「已持有部位」時的移動停損／出場技巧，須另行搭配其他方法的進場訊號（如 gq-01-04～gq-01-06）。
因此本模組只提供出場函式 `big_bar_trail_exit()` 與一個**沒有進場邏輯**的 `Strategy` 包裝
（`on_bar()` 只在已有部位時呼叫出場函式，絕不會自行產生 `Order.enter`）；直接用 `run()`
回測本模組永遠不會有任何交易。測試以手動建立 `Context`／`Position` 驗證出場邏輯，
無法單獨對本模組做完整回測（見模組末待確認事項與任務回報）。

訊號 / 出場水準定義（p.1–4）：
  多方 C1–C4：行情上升過程中出現一根「大陽線」→ 以其**最低點**做為移動出場水準；
    後續再出現更新的大陽線，水準墊高（只朝有利方向調整，p.2）。
  空方 C1'–C4'（鏡像）：行情下跌過程中出現一根「大陰線」（或跳空黑K線且跌幅≥4%）
    → 以其**最高點**做為移動出場（回補）水準；後續再出現更新的大陰線／達標跳空黑K線，
    水準下移（p.3–4）。
出場（p.2–4）：K線**收盤**跌破（多）／突破（空）目前的移動出場水準即出場；
  出場水準本身即是停損防守線（§5），無另外的停利規則。
過濾（p.2–4）：
  F1 大陰線認定門檻＝長黑K線，或跳空黑K線且跌幅≥4%；未達標黑K不納入計算。
     「大陽線」原文未給出對應的量化門檻（僅稱「光頭陽線／中陽線」），本模組以
     **原文未定量，預設值為推論**：與大陰線跳空黑K的4%門檻對稱，取同一 `big_bar_pct`
     判定「大陽線」＝紅K實體漲幅（相對開盤）≥ big_bar_pct%；「大陰線」則為
     黑K實體跌幅（相對開盤）≥ big_bar_pct%，**或**跳空開低且跌幅（相對前一根收盤）
     ≥ big_bar_pct%（此為原文明訂的4%替代條件，非推論）。
  F2 低檔盤旋、高檔盤旋、交投冷淡時期出現的短小K線，不構成大陽線／大陰線（p.2–3，推論）：
     已內建於「實體漲跌幅須達 big_bar_pct%」的門檻本身，短小K線自然不會達標，
     不另外實作獨立的「盤旋期」判斷（book 未提供可程式化的盤整定義）。

週期：不限。big_bar_pct 為百分比參數，不隨週期或商品縮放；不涉及任何點數門檻。
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from wangtrader.core import Context, Order, Side, Strategy

METHOD_ID = "gq-01-01"


@dataclass
class Params:
    big_bar_pct: float = 4.0  # 大陽線/大陰線判定門檻（%）。大陰線跳空替代條件原文明訂4%（p.4）；
    # 大陽線門檻與大陰線「長黑K線」本身的量化門檻原文皆未定量，本模組鏡像沿用同一數值
    # （原文未定量，預設值為推論，保守取與跳空替代條件相同之4%）。


def _is_big_up(b: pd.Series, pct: float) -> bool:
    """大陽線（推論門檻）：紅K，實體漲幅（相對開盤）≥ pct%（p.1–2）。"""
    o, c = float(b["open"]), float(b["close"])
    if c <= o or o == 0:
        return False
    return (c - o) / abs(o) * 100.0 >= pct


def _is_big_down(b: pd.Series, prev_close: float, pct: float) -> bool:
    """大陰線：黑K，實體跌幅（相對開盤）≥ pct%（推論門檻），或跳空開低且跌幅（相對前一根
    收盤）≥ pct%（p.4，原文明訂之替代條件）。"""
    o, c = float(b["open"]), float(b["close"])
    if c >= o or o == 0:
        return False
    if (o - c) / abs(o) * 100.0 >= pct:
        return True
    if prev_close == prev_close and o < prev_close:  # prev_close 非 NaN 且跳空開低
        return (prev_close - c) / abs(prev_close) * 100.0 >= pct
    return False


def big_bar_trail_exit(ctx: Context, big_bar_pct: float = 4.0) -> Order | None:
    """已持有部位期間的移動出場（p.2–4）：多方以最近一根大陽線最低點、空方以最近一根大陰線
    （或達標跳空黑K）最高點為出場水準，只朝有利方向更新；K線收盤觸及即出場。
    狀態存於 `ctx.pos.meta["big_bar_stop"]`，可與其他出場邏輯並存於同一部位。"""
    pos = ctx.pos
    if pos is None:
        return None
    b = ctx.bar()
    key = "big_bar_stop"
    if pos.side == Side.LONG:
        if _is_big_up(b, big_bar_pct):
            lvl = float(b["low"])
            pos.meta[key] = max(pos.meta.get(key, lvl), lvl)
        stop = pos.meta.get(key)
        if stop is not None and float(b["close"]) < stop:
            return Order.exit("大陽線出場")
    else:
        prev_close = float(b["prev_close"]) if "prev_close" in b.index else float("nan")
        if _is_big_down(b, prev_close, big_bar_pct):
            lvl = float(b["high"])
            pos.meta[key] = min(pos.meta.get(key, lvl), lvl)
        stop = pos.meta.get(key)
        if stop is not None and float(b["close"]) > stop:
            return Order.exit("大陰線出場")
    return None


class BigBarTrailExit(Strategy):
    """本節不含進場規則，`on_bar` 只在已有部位時提供移動出場；不會自行進場（見模組docstring）。"""

    method_id = METHOD_ID
    intraday = False  # 波段用出場技巧，非當沖方法（p.2–4 範例為日線波段）

    def __init__(self, **kw) -> None:
        self.p = Params(**kw)

    def on_bar(self, ctx: Context):
        if ctx.pos is None:
            return None
        ex = big_bar_trail_exit(ctx, self.p.big_bar_pct)
        return [ex] if ex is not None else None
