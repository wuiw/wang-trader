import pytest
from helpers import make_bars

from wangtrader.core import Side, run
from wangtrader.methods.gq_02_05_kd_early_breakout_divergence import KdEarlyBreakoutDivergence

# 縮小版均線/KD週期（原文未指定均線週期），讓「牛市排列」與KD候選K線可在少量K線內驗證。
KW = dict(trend_fast=5, trend_slow=20, kd_n=9, k_period=3, d_period=3)


def _base_rows():
    """長多頭段(25根) + 回檔段(15根，夾雜1天小反彈)，於idx29形成候選K線（K值<=50且仍下滑，收紅）。"""
    closes = list(range(100, 100 + 3 * 25, 3))
    c = closes[-1]
    for s in (-4, -3, -3, -2, 1, -3, -2, -3, 1, -2, -3, -2, 1, -3, -2):
        c += s
        closes.append(round(c, 2))
    opens = [closes[0] - 1, *closes[:-1]]
    highs = [max(o, cl) + 1 for o, cl in zip(opens, closes)]
    lows = [min(o, cl) - 1 for o, cl in zip(opens, closes)]
    return list(zip(opens, highs, lows, closes))


def test_early_breakout_signal_fires_next_bar():
    rows = _base_rows()[:30]  # idx0-29，idx29為候選K線（收盤161，最高162）
    rows.append((161, 166, 160, 165))  # idx30：收盤165 > 候選最高162 -> 隔天過高買進
    bars = make_bars(rows)
    res = run(KdEarlyBreakoutDivergence(**KW), bars)
    assert len(res.signals) == 1
    sig = res.signals[0]
    assert sig.side == Side.LONG and sig.reason == "KD提前買點(K值背離過高)"
    assert sig.price == 165
    assert sig.stop == 160 - 1.0  # 真實低點=min(low30=160, prevclose29=161)=160，下方一檔


def test_filtered_when_next_bar_does_not_break_high():
    rows = _base_rows()[:30]
    rows.append((161, 162, 157, 158))  # idx30 收盤158 未突破候選最高162
    bars = make_bars(rows)
    res = run(KdEarlyBreakoutDivergence(**KW), bars)
    assert res.signals == []


def test_candidate_expires_after_one_bar_even_if_later_breaks_high():
    rows = _base_rows()[:30]
    rows.append((161, 162, 157, 158))  # idx30 不突破 -> 候選作廢
    rows.append((158, 170, 157, 169))  # idx31 雖突破idx29最高點162，但候選已過期，不應觸發
    bars = make_bars(rows)
    res = run(KdEarlyBreakoutDivergence(**KW), bars)
    assert res.signals == []


def test_candidate_filter_requires_k_below_threshold():
    # F1：純多頭上升段中K值仍在50以上，即使是紅K也不應成立候選
    from wangtrader.core import prepare

    rows = _base_rows()[:30]
    bars = make_bars(rows)
    df = prepare(bars)
    strat = KdEarlyBreakoutDivergence(**KW)
    df = strat.prepare(df)
    assert strat._is_candidate(df, 10) is False  # 上升段中K值仍高
    assert df.at[29, "k"] <= 50  # 候選K線本身確實 <=50（對照組）


def test_bull_filter_blocks_when_not_bull_market():
    from wangtrader.core import prepare

    rows = _base_rows()[:30]
    rows.append((161, 166, 160, 165))
    bars = make_bars(rows)
    df = prepare(bars)
    strat = KdEarlyBreakoutDivergence(**KW)
    df = strat.prepare(df)
    assert strat._bull(df, 30) is True  # 對照組：本例確為牛市排列
    assert strat._bull(df, 3) is False  # 資料不足時（均線尚未就緒）視為非牛市


def test_stop_mode_pct():
    rows = _base_rows()[:30]
    rows.append((161, 166, 160, 165))
    bars = make_bars(rows)
    res = run(KdEarlyBreakoutDivergence(stop_mode="pct", **KW), bars)
    assert res.signals[0].stop == pytest.approx(165 * 0.93)
