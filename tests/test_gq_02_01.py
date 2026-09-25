import pytest
from helpers import make_bars

from wangtrader.core import Side, run
from wangtrader.methods.gq_02_01_rsi_falling_momentum_reversal import RsiFallingMomentumReversal

# 測試用參數：season_period/year_period 縮小並用 trend_lookback=8（比較8根之前）
# 取代原文60/240日季線年線，讓「季線年線皆朝上」在少量K線內可驗證，同時不受短期拉回影響
# （近似真實情境中，短期拉回不太會扭轉季線/年線走勢）；down_run_days 縮小為3。

TREND_KW = dict(season_period=5, year_period=5, trend_lookback=8, down_run_days=3)

# 上升段（0-10，峰值140） + 回檔4根（11-14：136,131,125,118） + 反漲K線（15：118*1.05=123.9）
UP = [100, 104, 108, 112, 116, 120, 124, 128, 132, 136, 140]
DOWN = [136, 131, 125, 118]
RALLY = round(118 * 1.05, 2)


def _rows(extra_after=None):
    rows = [(c, c + 1, c - 1, c) for c in UP + DOWN]
    rows.append((118, RALLY + 1, 117, RALLY))
    if extra_after:
        rows += extra_after
    return rows


def test_signal_fires_on_bull_market_down_run_and_reversal():
    bars = make_bars(_rows())
    res = run(RsiFallingMomentumReversal(**TREND_KW), bars)
    assert len(res.signals) == 1
    sig = res.signals[0]
    assert sig.side == Side.LONG and sig.reason == "RSI連低買點"
    assert sig.price == RALLY
    assert sig.stop == pytest.approx(RALLY * 0.93)  # 預設 stop_pct=0.07


def test_filtered_when_down_run_too_short():
    # 只有1根回檔就反漲，未達 down_run_days=3
    rows = [(c, c + 1, c - 1, c) for c in UP]
    rows.append((136, 137, 130, 131))  # 回檔1根
    rows.append((131, 146, 130, round(131 * 1.05, 2)))  # 反漲>=3%
    bars = make_bars(rows)
    res = run(RsiFallingMomentumReversal(**TREND_KW), bars)
    assert res.signals == []


def test_filtered_when_reversal_too_small():
    rows = [(c, c + 1, c - 1, c) for c in UP + DOWN]
    rows.append((118, 121, 117, 120))  # 反漲僅約1.7%，未達3%
    bars = make_bars(rows)
    res = run(RsiFallingMomentumReversal(**TREND_KW), bars)
    assert res.signals == []


def test_filtered_when_not_bull_market():
    # 較長且較陡的回檔，季線/年線在反漲當根仍是下彎（近似「非多頭市場」）
    decline = [130, 125, 120, 115, 110, 105, 100, 95]
    rows = [(c, c + 1, c - 1, c) for c in decline]
    rows.append((95, 101, 94, round(95 * 1.05, 2)))  # 反漲>=3%，但長期趨勢仍向下
    bars = make_bars(rows)
    res = run(RsiFallingMomentumReversal(season_period=4, year_period=4, trend_lookback=1, down_run_days=3), bars)
    assert res.signals == []


def test_model1_moving_stop_ratchets_up_and_exits():
    # 進場後出現大漲K線（>=4%），停損移到真實低點，且只能上移；之後跌破觸發出場
    extra = [
        (RALLY, RALLY + 1, RALLY - 1, RALLY + 1),           # 小漲，不觸發model1
        (RALLY + 1, round((RALLY + 1) * 1.06, 2), RALLY, round((RALLY + 1) * 1.06, 2)),  # 大漲K線(+6%)，真實低點=RALLY
        (round((RALLY + 1) * 1.06, 2), round((RALLY + 1) * 1.06, 2) + 1, RALLY - 5, RALLY - 5),  # 跌破真實低點，觸發出場
    ]
    bars = make_bars(_rows(extra_after=extra))
    res = run(RsiFallingMomentumReversal(exit_mode="model1", **TREND_KW), bars)
    assert len(res.trades) == 1
    t = res.trades[0]
    assert t.reason_out == "停損"
    assert t.exit_price == RALLY  # 停損＝真實低點（本例即進場K線收盤 RALLY）


def test_model4_window_recomputes_daily():
    # n_window_long=2：停損每根改用「前2根區間最低點」，不限方向（可能突升，也可能因新低而下移）
    extra = [
        (RALLY, RALLY + 5, RALLY + 2, RALLY + 4),  # 區間最低點推升為 117（進場根低點）
        (RALLY + 4, RALLY + 6, RALLY - 10, RALLY + 3),  # 本根新低 113.9 < 前一根停損 117 → 觸發出場
    ]
    bars = make_bars(_rows(extra_after=extra))
    res = run(RsiFallingMomentumReversal(exit_mode="model4", n_window_long=2, **TREND_KW), bars)
    assert len(res.trades) == 1
    t = res.trades[0]
    assert t.reason_out == "停損" and t.exit_price == 117.0  # 停損＝前一根重新計算的區間最低點
