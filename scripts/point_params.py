"""點數門檻縮放參數表（供 `scripts/run_scaled.py` 使用）。

背景：書中點數門檻（20 點停損、40 點極端位置…）是在《期貨奇績2》（q2_*，約台指期 8,500 點）
與《期貨奇績3》（q3_*，約台指期 10,000 點）的年代訂的；本專案回測期間台指期約 22,000→48,000 點。
本檔案只做「欄位分類」，**不修改任何方法模組**，也不改變預設值本身。

分類規則：
  - 會被列進 POINT_PARAMS[method] 的欄位＝「點數」（價格距離：停損、目標、濾網幅度、跳空、
    影線容忍值、折返/回檔點數、與平盤/前高低/均線的距離門檻…），套用等比例縮放
    （乘以 當時價位 / REF_PRICE[書]）。
  - 不列入的欄位＝根數(bars)、K線根數計數(min_run/five_min_bars等)、轉折層級(pivot_level)、
    MA/RSI/KD 週期、RSI/KD 數值本身（0-100 尺度，如 70/30、d_overbought）、比例(ratio)、
    成交量(口數)、布林開關、字串模式(mode/exit_mode)、時間(time)、次數上限(int count)等，
    這些不隨價格水位縮放。
  - dataclass 內的巢狀 helper class（如 `_Pivot`、`_SideState`、`_SessionState`、`_Chain`、
    `_Track`、`_NTrack`、`_LegState`）是策略內部執行時狀態，不是使用者參數，不在此列出。

有疑慮／邊界案例（已列入縮放，但語意上可能不是單純「價位距離」，縮放後行為需留意）：
  - q2_01.trail_breach_points (1.0)、q3_04.tolerance_points (1.0)：
    這兩個是「容忍雜訊」的極小點數門檻（判斷觸價確認、判斷兩根漲跌點數是否視為相等），
    語意上比較像「可接受誤差」而非「隨價位變化的目標距離」。是否該縮放見仁見智；
    本表選擇仍列入縮放（其定義仍是「兩個價格之間的點數差」，隨價位等比例放大有一定道理），
    但縮放後可能從 1 點變成 3~5 點，等於放寬雜訊容忍度，需在報告中特別說明。
  - q2_04_01.second_signal_min_profit、q2_03_02.max_drift_from_breakout：
    預設皆為 None（功能關閉），縮放時维持 None（見 run_scaled.py 的縮放邏輯：None 不縮放，
    只縮放非 None 的數值型點數欄位）。
  - q3_10.diff_threshold：這是「RSI 值」的差距（RSI 是 0-100 尺度指標，不是價格），**不縮放**，
    不列入下表；讀者若誤以為所有 "*_threshold" 都是點數，此為反例。
  - q2_05_02.min_volume：成交量（口數），**不縮放**。
  - q3_11（波段方法）多數濾網以 RSI/MA 為主，點數欄位只有 retrace_points 一個。

REF_PRICE：兩本書訂定門檻時的大致台指期水位，用來計算縮放倍數
  （倍數 = 當時實際開盤價 / REF_PRICE[書]）。
"""

from __future__ import annotations

REF_PRICE: dict[str, float] = {
    "q2": 8500.0,
    "q3": 10000.0,
}


POINT_PARAMS: dict[str, list[str]] = {
    "q2_01_ma_three_step": [
        "stop_min_offset",
        "stop_integer_points",
        "big_bar_points",
        "max_dev_from_break",
        "max_dev_from_prev_close",
        "min_bar_points",
        "profit_target",
        "trail_points",
        "trail_breach_points",  # 見檔頭「有疑慮」說明：極小容忍值，縮放後語意需留意
        "time_stop_min_profit",
    ],
    "q2_03_01_pvt_n_type": [
        "ladder_ignore_diff",
        "stop_min_offset",
        "stop_integer_points",
        "stop_max_risk",
        "max_pattern_points",
        "max_dev_from_ladder",
        "max_drift_from_breakout",
        "giveback_points",
    ],
    "q2_03_02_pvt_rsi": [
        "ladder_ignore_diff",
        "break_points",
        "retrace_points",
        "max_drift_from_breakout",  # 預設 None，維持 None；非 None 時才縮放
        "stop_min_offset",
        "stop_integer_points",
        "stop_max_risk",
        "giveback_points",
        "breakeven_arm_points",
    ],
    "q2_04_01_cross_kd_n_type": [
        "max_signal_points",
        "pullback_stop_max",
        "retrace_points",
        "second_signal_min_profit",  # 預設 None，維持 None；非 None 時才縮放
    ],
    "q2_04_02_four_pillars": [
        "retrace_points",
    ],
    "q2_05_01_extreme_three_soldiers": [
        "min_range",
        "max_range",
        "stop_max",
        "retrace_target",
        "ladder_target",
    ],
    "q2_05_02_extreme_max_volume": [
        "min_swing_points",
        "stop_points",
        # min_volume 為成交量(口數)，不縮放
    ],
    "q2_06_01_fake_extreme_divergence": [
        "min_swing_points",
        "stop_points",
    ],
    "q2_06_02_kd_divergence": [
        "gap_carry_points",
        "stop_points",
        "reversal_bounce_points",
        # d_overbought/d_oversold/k_mid/k_extreme 為 KD(0-100)數值，不縮放
    ],
    "q2_06_03_rsi_divergence": [
        "stop_points",
        # ob_extreme/os_extreme/mid/os_breach/ob_breach 為 RSI(0-100)數值，不縮放
    ],
    "q2_06_04_rsi_blunt_n_shape": [
        "stop_points",
        "seamless_gap_points",
        "min_valid_gap_points",
        "stop_min_offset",
        "stop_integer_points",
        # ob_extreme/os_extreme 為 RSI(0-100)數值，不縮放
    ],
    "q3_01_double_red_black": [
        "stop_points",
        "extreme_range",
        "extreme_from_prev_close",
        "min_pattern_points",
        "profit_target",
    ],
    "q3_02_v_reversal": [
        "stop_points",
        "large_bar_threshold",  # 預設 30.0（非 None），照常縮放
        "extreme_range",
        "extreme_from_prev_close",
        "profit_target",
    ],
    "q3_03_mother_child": [
        "stop_points",
        "extreme_range",
        "extreme_from_prev_close",
        "profit_target",
    ],
    "q3_04_tit_for_tat": [
        "tolerance_points",  # 見檔頭「有疑慮」說明：極小容忍值，縮放後語意需留意
        "stop_points",  # float | None，預設 20.0（非 None），照常縮放；None 維持 None
        "profit_target", "extreme_range", "extreme_from_prev_close"],
    "q3_05_break_three_high_low": [
        "stop_points",
        "immediate_distance",
        "ignore_beyond",
        "reversal_profit_threshold",
    ],
    "q3_06_five_in_a_row_reversal": [
        "min_points",
        "shadow_max_points",
        "stop_points",
        # shadow_max_ratio 為比例，不縮放；min_run/stale_bars 為根數，不縮放
    ],
    "q3_07_opening_bar": [
        "gap_threshold",
        "shadow_max",
        "stop_points",
        "profit_trigger",
    ],
    "q3_08_01_ma_breakout": [
        "stop_points",
        "turn_dist_min",
        "turn_dist_max",
        "carryover_open_dist_max",
        "swing_dist_max",
        "extreme_range",
        "extreme_from_prev_close",
        "retrace_arm",
        "retrace_points", "gap_open_range_max"],
    "q3_08_02_pig_yang": [
        "stop_points",
        "turn_dist_min",
        "carryover_open_dist_max",
        "retrace_arm",
        "retrace_points",
        "five_min_points",
        "five_wick_max",
    ],
    "q3_09_01_ma_dragonfly": [
        "stop_points",
        "large_bar_threshold",
        "min_turn_dist",
        "extreme_range",
        "extreme_from_prev_close",
        "five_min_points",
        "five_wick_max",
    ],
    "q3_09_02_flat_dragonfly": [
        "touch_extreme_points",
        "giant_bar_points",
        "stop_points",
        "early_exit_profit",
        "retrace_trigger",
        "reverse_max_distance",
        "no_reverse_profit",
    ],
    "q3_10_rsi_diff": [
        "extreme_range",
        "extreme_from_prev_close",
        "gap_merge_points",
        "stop_points",
        "max_risk",
        "profit_confirm",
        "reverse_max_from_flat",
        # diff_threshold 是 RSI 值差距（0-100 尺度），不是點數，不縮放
    ],
    "q3_11_option_swing_breakout": [
        "retrace_points",
        # rsi_extreme_high/low、rsi_near_tol 為 RSI(0-100)數值，不縮放；
        # max_pullback_bars 為根數，不縮放。波段方法（intraday=False），見 run_scaled.py 說明。
    ],
}
