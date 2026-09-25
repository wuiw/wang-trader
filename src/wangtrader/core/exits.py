"""共用的出場／移動停利工具（書中多個方法共用的機制）。

每個函式在 `on_bar` 裡呼叫：傳入 ctx，回傳 `Order.exit(...)` 或 None。
狀態存在 `ctx.pos.meta`，所以同一個方法可以組合使用。
"""

from __future__ import annotations

from .engine import Context, Order, Side


def _reached(ctx: Context, target: float) -> bool:
    """獲利目標是否已達成（以持倉期間最有利價計），且不在進場當根。"""
    pos = ctx.pos
    return pos is not None and ctx.i > pos.entry_i and pos.max_profit() >= target


def ladder_exit(ctx: Context, target: float) -> Order | None:
    """階梯出場（q3-01 p.35）：達獲利目標後，每出現一根創新高（多）/新低（空）K 線，
    取「該根與前一根」的最低點（多）/最高點（空）中較有利者作為移動停利；收盤觸及即出場。"""
    pos = ctx.pos
    if pos is None or not _reached(ctx, target):
        return None
    b, p = ctx.bar(0), ctx.bar(1)
    key = "ladder"
    if pos.side == Side.LONG:
        if b["high"] >= pos.best:  # 本根創新高
            lvl = max(b["low"], p["low"])
            pos.meta[key] = max(pos.meta.get(key, lvl), lvl)
        if key in pos.meta and b["close"] <= pos.meta[key] and b["high"] < pos.best:
            return Order.exit("階梯出場")
    else:
        if b["low"] <= pos.best:
            lvl = min(b["high"], p["high"])
            pos.meta[key] = min(pos.meta.get(key, lvl), lvl)
        if key in pos.meta and b["close"] >= pos.meta[key] and b["low"] > pos.best:
            return Order.exit("階梯出場")
    return None


def ma_exit(ctx: Context, ma_col: str, target: float, shadow_points: float | None = None) -> Order | None:
    """均線移動停利（q3-01 p.33）：達獲利目標後的隔根起，收盤跌破（多）/突破（空）均線即出場；
    shadow_points 有值時，影線越過均線達該點數也出場。"""
    pos = ctx.pos
    if pos is None:
        return None
    if "ma_armed" not in pos.meta:
        if _reached(ctx, target):
            pos.meta["ma_armed"] = ctx.i  # 從下一根開始
        return None
    if ctx.i <= pos.meta["ma_armed"]:
        return None
    b = ctx.bar()
    ma = b[ma_col]
    if ma != ma:  # NaN
        return None
    if pos.side == Side.LONG:
        if b["close"] < ma or (shadow_points is not None and ma - b["low"] >= shadow_points):
            return Order.exit("均線停利")
    else:
        if b["close"] > ma or (shadow_points is not None and b["high"] - ma >= shadow_points):
            return Order.exit("均線停利")
    return None


def sar_exit(ctx: Context, target: float, sar_col: str = "sar", trend_col: str = "sar_trend") -> Order | None:
    """SAR 移動停利（q3-01 p.32）：達獲利目標後以 SAR 追蹤，收盤越過才出場。
    只有影線越過時，把當時的 SAR 價位水平延伸作為停利線，直到 SAR 重新回到持倉方向。"""
    pos = ctx.pos
    if pos is None or not _reached(ctx, target):
        return None
    b = ctx.bar()
    want = 1 if pos.side == Side.LONG else -1
    if b[trend_col] == want:
        level = b[sar_col]
        pos.meta.pop("sar_hold", None)
    else:
        level = pos.meta.setdefault("sar_hold", ctx.bar(1)[sar_col])
    if level != level:
        return None
    if (b["close"] <= level) if pos.side == Side.LONG else (b["close"] >= level):
        return Order.exit("SAR停利")
    return None


def retrace_exit(ctx: Context, trigger: float, keep: float) -> Order | None:
    """折返停利：最大獲利曾達 trigger 點後，獲利回落到 keep 點（含）以下即以收盤出場。
    例：trigger=15, keep=0 表示「獲利超過 15 點後折返回進場價就出場」。"""
    pos = ctx.pos
    if pos is None or not _reached(ctx, trigger):
        return None
    if pos.profit(ctx.bar()["close"]) <= keep:
        return Order.exit("折返停利")
    return None
