import pandas as pd
import pytest
from helpers import make_bars

from wangtrader.core import Side, run
from wangtrader.methods.gq_02_06_kd_early_turn_up import KdEarlyTurnUp

KW = dict(trend_fast=5, trend_slow=20, kd_n=9, k_period=3, d_period=3)


def _rows():
    """長多頭段(25根) + 5根回檔 + 1根反彈：反彈根K值由降轉升(44.37->45.67)，且仍<=50，收陽線，均線仍多排。"""
    base = list(range(100, 100 + 3 * 25, 3))
    c = base[-1]
    decline = []
    for _ in range(5):
        c -= 2.5
        decline.append(round(c, 2))
    c += 6
    decline.append(round(c, 2))
    closes = base + decline
    opens = [closes[0] - 1, *closes[:-1]]
    highs = [max(o, cl) + 1 for o, cl in zip(opens, closes)]
    lows = [min(o, cl) - 1 for o, cl in zip(opens, closes)]
    return list(zip(opens, highs, lows, closes))


def test_signal_fires_on_turn_up_below_50_with_red_bar():
    bars = make_bars(_rows())
    res = run(KdEarlyTurnUp(**KW), bars)
    assert len(res.signals) == 1
    sig = res.signals[0]
    assert sig.side == Side.LONG and sig.reason == "KD提前買點(均線多排K值轉折)"
    assert sig.price == 165.5
    assert sig.stop == pytest.approx(157.5)  # 真實低點min(158.5,159.5)=158.5，下方一檔


def test_stop_mode_pct():
    bars = make_bars(_rows())
    res = run(KdEarlyTurnUp(stop_mode="pct", **KW), bars)
    assert res.signals[0].stop == pytest.approx(165.5 * 0.93)


def _synthetic_df(k_seq, close_seq, open_seq, fast=100.0, slow=90.0):
    """白箱測試用：直接指定 k/fast_ma/slow_ma/open/close 欄位，略過真實K線推導指標的繁瑣建構。"""
    n = len(k_seq)
    return pd.DataFrame({
        "open": open_seq, "close": close_seq,
        "high": [max(o, c) + 1 for o, c in zip(open_seq, close_seq)],
        "low": [min(o, c) - 1 for o, c in zip(open_seq, close_seq)],
        "fast_ma": [fast] * n, "slow_ma": [slow] * n, "k": k_seq,
    })


def test_filtered_when_k_above_threshold_turn():
    # K值轉折發生在50以上，不適用（F1）
    df = _synthetic_df([70, 60, 65], [100, 98, 99], [99, 99, 98])
    strat = KdEarlyTurnUp(**KW)
    assert strat.detect(df, 2) is False


def test_filtered_when_not_bull_market():
    df = _synthetic_df([45, 30, 35], [100, 98, 99], [99, 99, 98], fast=90.0, slow=100.0)
    strat = KdEarlyTurnUp(**KW)
    assert strat.detect(df, 2) is False


def test_filtered_when_bar_is_black():
    # K值確實由降轉升且<=50，但當天收黑（開>收）
    df = _synthetic_df([45, 30, 35], [100, 98, 96], [99, 99, 99])
    strat = KdEarlyTurnUp(**KW)
    assert strat.detect(df, 2) is False


def test_filtered_when_no_prior_decline_before_turn():
    # require_prior_decline=True 時，昨日K值須先仍處於下滑段（k1<=k0）；本例k1>k0，不成立轉折
    df = _synthetic_df([30, 40, 45], [100, 98, 99], [99, 99, 98])
    strat = KdEarlyTurnUp(**KW)
    assert strat.detect(df, 2) is False
    strat2 = KdEarlyTurnUp(require_prior_decline=False, **KW)
    assert strat2.detect(df, 2) is True  # 關閉此推論限制後，僅需今日K高於昨日即成立
