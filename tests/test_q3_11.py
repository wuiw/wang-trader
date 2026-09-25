import pandas as pd
from helpers import make_bars

from wangtrader.core import Side, run
from wangtrader.core import prepare as core_prepare
from wangtrader.methods.q3_11_option_swing_breakout import OptionSwingBreakout, _LegState

# 測試以小週期參數（ma_period=3, rsi_period=1）取代書中原文的 MA100/RSI(?)，
# 使因果關係在少量K線內即可驗證；rsi_period=1 時 RSI 只反映前一根漲跌方向（漲=100/跌=0），
# 便於精準控制 RSI 是否達到 90/10 極端值門檻。
# 出場測試中 arm_at_strike=False 只驗證各停利機制本身；履約價啟動另有專屬測試。


def test_call_signal_basic():
    rows = [
        (100, 101, 99, 100),
        (100, 103, 99, 102),
        (102, 105, 101, 104),
        (104, 111, 103, 110),  # 突破均線後峰位候選：高點111
        (109, 110, 104, 105),  # 黑K拉回未創新高，RSI已達90門檻 → 峰位確立(111)
        (105, 113, 104, 112),  # 收盤112 > 111 → 買進CALL訊號
    ]
    res = run(OptionSwingBreakout(ma_period=3, rsi_period=1, exit_mode="hold"), make_bars(rows))
    sig = res.signals[0]
    assert sig.side == Side.LONG and sig.reason == "選擇權波段突破-買進CALL"
    assert sig.meta["option_side"] == "CALL" and sig.meta["peak_price"] == 111.0
    assert sig.meta["strike"] == 300.0  # 價平 100（間距 100）往上兩檔
    assert res.trades == []  # exit_mode=hold，部位持有至資料結束，不產生已平倉交易


def test_put_signal_basic():
    rows = [
        (100, 101, 99, 100),
        (100, 101, 97, 98),
        (98, 99, 95, 96),
        (96, 97, 89, 90),   # 跌破均線後谷位候選：低點89
        (91, 96, 90, 95),   # 紅K反彈未創新低，RSI已達10門檻 → 谷位確立(89)
        (95, 96, 84, 85),   # 收盤85 < 89 → 買進PUT訊號
    ]
    res = run(OptionSwingBreakout(ma_period=3, rsi_period=1, exit_mode="hold"), make_bars(rows))
    sig = res.signals[0]
    assert sig.side == Side.SHORT and sig.reason == "選擇權波段突破-買進PUT"
    assert sig.meta["option_side"] == "PUT" and sig.meta["trough_price"] == 89.0


def test_c4_pullback_below_origin_invalidates():
    rows = [
        (100, 101, 99, 100),
        (100, 103, 99, 102),
        (102, 105, 101, 104),
        (104, 111, 103, 110),
        (109, 110, 104, 105),  # 峰位確立(111)，origin=99
        (105, 106, 95, 100),   # 拉回跌破origin(99) → 取消觀察
        (100, 113, 99, 112),   # 收盤112雖突破舊峰位111，但已取消觀察，不應觸發訊號
    ]
    res = run(OptionSwingBreakout(ma_period=3, rsi_period=1, exit_mode="hold"), make_bars(rows))
    assert res.signals == []


def test_c4_applies_before_peak_confirmed_too():
    """尚未確認峰位時跌破起漲谷點，也取消本段觀察（須等重新突破均線）。"""
    rows = [
        (100, 101, 99, 100),
        (100, 103, 99, 102),
        (102, 105, 101, 104),  # 向上穿越，origin=99
        (104, 106, 103, 105),
        (105, 105, 95, 96),    # 跌破 origin → 取消
    ]
    strat = OptionSwingBreakout(ma_period=3, rsi_period=1, exit_mode="hold")
    run(strat, make_bars(rows))
    assert strat._call is None


def test_c5_pullback_too_long_invalidates():
    rows = [
        (100, 101, 99, 100),
        (100, 103, 99, 102),
        (102, 105, 101, 104),
        (104, 111, 103, 110),
        (109, 110, 104, 105),  # 峰位確立，拉回開始
        (105, 108, 104, 106),  # 拖延第1根
        (106, 108, 103, 105),  # 拖延第2根
        (105, 113, 103, 112),  # 拖延已超過 max_pullback_bars(2) → 取消觀察，即使收盤112>111也不觸發
    ]
    res = run(OptionSwingBreakout(ma_period=3, rsi_period=1, exit_mode="hold", max_pullback_bars=2), make_bars(rows))
    assert res.signals == []


def test_late_entry_second_breakout_in_same_leg():
    """同一段上升行情中，先前突破未進場也可在下一次突破再度形成訊號（對應書中「補進場」，p.249）。"""
    rows = [
        (100, 101, 99, 100),
        (100, 103, 99, 102),
        (102, 105, 101, 104),
        (104, 111, 103, 110),
        (109, 110, 104, 105),
        (105, 113, 104, 112),  # 第一次突破訊號（峰位111）
        (112, 125, 111, 120),  # 續創新高
        (120, 122, 115, 117),  # 黑K拉回，新峰位125確立
        (117, 131, 116, 130),  # 再次突破125 → 第二次CALL訊號
    ]
    res = run(OptionSwingBreakout(ma_period=3, rsi_period=1, exit_mode="hold"), make_bars(rows))
    peaks = [s.meta["peak_price"] for s in res.signals]
    assert peaks == [111.0, 125.0]


def test_put_leg_tracked_while_call_leg_alive():
    """對開（p.260-261）：CALL 腿追蹤中價格收盤跌破均線，PUT 腿須同時開始追蹤並能產生訊號。"""
    rows = [
        (100, 101, 99, 100),
        (100, 103, 99, 102),
        (102, 105, 101, 104),  # 向上穿越，CALL 腿 origin=99
        (104, 106, 103, 103),  # 黑K但創新高 → 候選 106
        (103, 104, 100, 101),  # 收盤跌破均線 → PUT 腿 origin=106；CALL 峰位確立 106
        (101, 102, 97, 98),    # CALL 腿跌破 origin 取消；PUT 候選谷位 97
        (98, 101, 98, 100),    # 紅K未創新低 → 谷位確立 97
        (100, 101, 94, 95),    # 收盤 95 < 97 → 買進PUT訊號
    ]
    res = run(OptionSwingBreakout(ma_period=3, rsi_period=1, exit_mode="hold"), make_bars(rows))
    assert len(res.signals) == 1
    assert res.signals[0].side == Side.SHORT and res.signals[0].meta["trough_price"] == 97.0


def test_exit_ma10():
    rows = [
        (100, 101, 99, 100),
        (100, 103, 99, 102),
        (102, 105, 101, 104),
        (104, 111, 103, 110),
        (109, 110, 104, 105),
        (105, 113, 104, 112),  # 進場 112
        (112, 116, 111, 115),
        (115, 116, 99, 100),   # 收盤跌破MA10 → 均線停利
    ]
    res = run(OptionSwingBreakout(ma_period=3, rsi_period=1, ma10_period=2, exit_mode="ma10",
                                  arm_at_strike=False), make_bars(rows))
    t = res.trades[0]
    assert t.reason_out == "均線停利" and t.exit_price == 100 and t.pnl == -12


def test_ma10_exit_armed_only_after_reaching_strike():
    """MA10 移動停利須等標的觸及所買選擇權履約價（價外轉價平）才啟動（p.258-259）。"""
    rows = [
        (100, 101, 99, 100),
        (100, 103, 99, 102),
        (102, 105, 101, 104),
        (104, 111, 103, 110),
        (109, 110, 104, 105),
        (105, 113, 104, 112),  # 進場 112：價平 110、價外二檔履約價 130（間距 10）
        (112, 116, 111, 115),
        (115, 116, 99, 100),   # 收盤跌破MA10，但尚未觸及 130 → 不出場
        (100, 135, 99, 133),   # 觸及 130 → 啟動 MA10 停利
        (133, 134, 120, 121),  # 收盤跌破 MA10(2)=127 → 均線停利
    ]
    res = run(OptionSwingBreakout(ma_period=3, rsi_period=1, ma10_period=2, exit_mode="ma10",
                                  strike_step=10, otm_steps=2), make_bars(rows))
    sig = res.signals[0]
    assert sig.meta["strike"] == 130.0 and sig.meta["arm_target"] == 18.0
    t = res.trades[0]
    assert t.reason_out == "均線停利" and t.exit_i == 9 and t.exit_price == 121


def test_exit_retrace_100():
    rows = [
        (100, 101, 99, 100),
        (100, 103, 99, 102),
        (102, 105, 101, 104),
        (104, 111, 103, 110),
        (109, 110, 104, 105),
        (105, 113, 104, 112),   # 進場 112
        (112, 130, 111, 128),   # 創高130
        (128, 129, 120, 124),   # 回落6點（>=retrace_points=5） → 折返停利
    ]
    res = run(OptionSwingBreakout(ma_period=3, rsi_period=1, exit_mode="retrace", retrace_points=5,
                                  arm_at_strike=False), make_bars(rows))
    t = res.trades[0]
    assert t.reason_out == "創高折返停利" and t.exit_price == 124 and t.pnl == 12


def test_retrace_exit_not_armed_before_strike():
    """折返停利同樣須先觸及履約價（p.252「買權進入價內階段，則準備獲利出場」）。"""
    rows = [
        (100, 101, 99, 100),
        (100, 103, 99, 102),
        (102, 105, 101, 104),
        (104, 111, 103, 110),
        (109, 110, 104, 105),
        (105, 113, 104, 112),   # 進場 112，履約價 130
        (112, 125, 111, 123),   # 創高 125，未達 130
        (123, 124, 110, 112),   # 回落 13 點，但停利尚未啟動 → 不出場
        (112, 132, 111, 131),   # 觸及 130 → 啟動
        (131, 132, 120, 121),   # 回落 11 點 >= 5 → 折返停利
    ]
    res = run(OptionSwingBreakout(ma_period=3, rsi_period=1, exit_mode="retrace", retrace_points=5,
                                  strike_step=10, otm_steps=2), make_bars(rows))
    t = res.trades[0]
    assert t.reason_out == "創高折返停利" and t.exit_i == 9 and t.exit_price == 121


def test_exit_prev_day_low():
    rows_day1 = [
        (100, 101, 99, 100),
        (100, 103, 99, 102),
        (102, 105, 101, 104),
        (104, 111, 103, 110),
        (109, 110, 104, 105),
        (105, 113, 104, 112),  # 進場 112
    ]
    rows_day2 = [
        (112, 113, 95, 96),  # 跌破前一天最低點(99) → 停利出場
    ]
    day1 = make_bars(rows_day1, start="2024-01-02 08:45")
    day2 = make_bars(rows_day2, start="2024-01-03 08:45")
    bars = pd.concat([day1, day2])
    res = run(OptionSwingBreakout(ma_period=3, rsi_period=1, exit_mode="prev_day", arm_at_strike=False), bars)
    t = res.trades[0]
    assert t.reason_out == "跌破前一天低點停利" and t.exit_price == 96 and t.pnl == -16


def test_c6_requires_signal_bar_closes_on_correct_side_of_ma100():
    """C6 新增規則（p.256，圖11-8）：K線收盤突破峰位水平線，但當下仍位於MA100之下，不算完成步驟
    的買進訊號；須等到真正收盤站上均線的那一根才算數。以白箱方式直接呼叫 `_step_call`、人為指定
    MA 值，隔離出這條規則本身（有機價格走勢很難同時控制「突破峰位」與「MA相對位置」兩個條件）。"""
    rows = [
        (100, 101, 99, 100),
        (100, 103, 99, 102),
        (102, 105, 101, 104),
        (104, 111, 103, 110),
        (109, 110, 104, 105),
        (105, 113, 104, 112),  # B：收盤112突破峰位111
        (112, 115, 111, 113),  # 下一根：收盤113同樣突破峰位111
    ]
    strat = OptionSwingBreakout(ma_period=3, rsi_period=1)
    df = strat.prepare(core_prepare(make_bars(rows)))
    strat._call = _LegState(origin=99.0, cand=111.0, cand_i=3, rsi_hit=True, confirmed=111.0, pullback_start=4)

    df.loc[5, "ma"] = 120.0  # 人為設定：B棒收盤112雖突破峰位111，但仍在MA100(120)之下
    order = strat._step_call(df, 5)
    assert order is None
    assert strat._call is not None and strat._call.confirmed == 111.0  # 追蹤狀態不變，繼續等待

    df.loc[6, "ma"] = 108.0  # 下一根：收盤113同樣突破峰位，且此時已收在MA100(108)之上 -> 真正訊號
    order2 = strat._step_call(df, 6)
    assert order2 is not None and order2.side == Side.LONG and order2.meta["peak_price"] == 111.0


def test_c6p_requires_signal_bar_closes_on_correct_side_of_ma100():
    """C6' 鏡像：PUT情境同樣要求訊號K線收盤須已跌破MA100。"""
    rows = [
        (100, 101, 99, 100),
        (100, 101, 97, 98),
        (98, 99, 95, 96),
        (96, 97, 89, 90),
        (91, 96, 90, 95),
        (95, 96, 84, 85),  # B：收盤85跌破谷位89
        (85, 86, 82, 83),  # 下一根：收盤83同樣跌破谷位89
    ]
    strat = OptionSwingBreakout(ma_period=3, rsi_period=1)
    df = strat.prepare(core_prepare(make_bars(rows)))
    strat._put = _LegState(origin=101.0, cand=89.0, cand_i=3, rsi_hit=True, confirmed=89.0, pullback_start=4)

    df.loc[5, "ma"] = 80.0  # 人為設定：B棒收盤85雖跌破谷位89，但仍在MA100(80)之上
    order = strat._step_put(df, 5)
    assert order is None
    assert strat._put is not None and strat._put.confirmed == 89.0

    df.loc[6, "ma"] = 90.0  # 下一根：收盤83同樣跌破谷位，且已跌破MA100(90) -> 真正訊號
    order2 = strat._step_put(df, 6)
    assert order2 is not None and order2.side == Side.SHORT and order2.meta["trough_price"] == 89.0


def test_exit_fixed_pct():
    """機制4：固定比例平倉（p.257「賺50%或100%出場」）。本模組以「觸及履約價後再前進
    arm_target*fixed_profit_ratio 點」近似。"""
    rows = [
        (100, 101, 99, 100),
        (100, 103, 99, 102),
        (102, 105, 101, 104),
        (104, 111, 103, 110),
        (109, 110, 104, 105),
        (105, 113, 104, 112),  # 進場112，履約價130，arm_target=18
        (112, 132, 111, 131),  # 觸及130（arm_target達成）
        (131, 149, 130, 148),  # 再前進18點（130+18=148）-> 達成 100% -> 固定比例停利
    ]
    res = run(OptionSwingBreakout(ma_period=3, rsi_period=1, exit_mode="fixed_pct",
                                  fixed_profit_ratio=1.0, strike_step=10, otm_steps=2), make_bars(rows))
    sig = res.signals[0]
    assert sig.meta["arm_target"] == 18.0
    t = res.trades[0]
    assert t.reason_out == "固定比例停利(100%)" and t.exit_i == 7 and t.exit_price == 148
