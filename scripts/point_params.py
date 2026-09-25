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
    # 《股技期招》台指期範例的 BX003台指期近 報價列（extracted/pages/ 逐字擷取），
    # 涵蓋 2008-05～2009-02（民國97-98年）多個圖例，價位介於約 4300～9400：
    #   IMG_8613: 970516 收9255.00／970808 開7191.00（低點6910.00起漲）
    #   IMG_8614: 970807 收7004.00／970723 開7156.09
    #   IMG_8615: 970522 開8875.00
    #   IMG_8675: 971217 開4630.00
    #   IMG_8676: 980206 開4365.00／980219 開4503.00
    #   IMG_8677: 980112 開4416.00
    #   IMG_8678: 970324 開8898.00／971219 開4680.00
    #   IMG_8712: 980217 開4490.00
    # 這些例子橫跨 2008 年金融海嘯前後，價位落差大（約4300~9400），取一個代表性中間值
    # 7000（10 筆報價的算術平均約6200，但河流圖／轉折趨勢線突破訊號〔gq-01-11，本節點數欄位
    # fixed_points/big_candle_range_points/ladder_target 的例子〕多落在 6900~9400，
    # 故取 7000 做為介於兩群之間的代表值，做法與 q2/q3 一致：只取一個「該書年代大致價位」
    # 的整數代表值，不做逐段擬合）。
    "gq": 7000.0,
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
        "ma_fast_arm_profit",  # ma 出場：獲利達此點數後切換 MA(ma_fast_period)（p.42）
        "range_breach_points",  # range 出場：觸及＝影線超過停利點此點數（p.47「超過1點」）
        "fixed_exit_points",  # fixed 出場：窄幅盤整固定點數出場（p.28）
        "breakeven_arm_points",  # 求不賠：獲利曾達此點數後回進場價出場（p.32-33）；預設非 None，None 時維持 None
        "time_stop_min_profit",
    ],
    "q2_02_sarc": [
        "stop_min_offset",
        "stop_integer_points",
        "max_signal_points",
        "same_dir_min_swing",
        "profit_target",
        "trail_points",
        "trail_breach_points",
        "range_breach_points",
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
        "stop_points_cap",
    ],
    "q2_05_01_extreme_three_soldiers": [
        "min_range",
        "max_range",
        "swing_range",  # C0/F6：近期波段高低點到三兵組合的盤中距離下限（p.161）
        "swing_from_prev_close",  # C0/F6：距平盤替代門檻（p.162）
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
        "swing_points",  # D5：A、B 兩端點幅度下限（p.224）
        # ob_extreme/os_extreme/mid/os_breach/ob_breach 為 RSI(0-100)數值，不縮放
    ],
    "q2_06_04_rsi_blunt_n_shape": [
        "stop_points",
        "seamless_gap_points",
        "min_valid_gap_points",
        "stop_min_offset",
        "stop_integer_points",
        "max_blunt_overshoot",  # C5b/C6b：鈍化續勢訊號突破原極端K線幅度上限（p.238）
        # ob_extreme/os_extreme 為 RSI(0-100)數值，不縮放
    ],
    "q3_01_double_red_black": [
        "stop_points",
        "extreme_range",
        "extreme_from_prev_close",
        "min_pattern_points",
        "profit_target",
        "retrace_step",  # 折返點數停利的扣抵點數（p.28-30）
    ],
    "q3_02_v_reversal": [
        "stop_points",
        "large_bar_threshold",  # 預設 30.0（非 None），照常縮放
        "large_bar_direct_range",  # tier1：反向K實體 > stop_points 且收盤距極端點 ≤ 此值 → 直接進場（p.53）
        "extreme_range",
        "extreme_from_prev_close",
        "profit_target",
        "stall_progress_points",  # 時間停滯出場：max_profit 未達此點數視為無進展（p.62；預設0.0）
    ],
    "q3_03_mother_child": [
        "stop_points",
        "extreme_range",
        "extreme_from_prev_close",
        "profit_target",
        "giveup_distance",  # F6：距母K極端點 ≥ 此值原則上放生不操作（p.73）
        "retrace_trigger",  # 折返平倉的「曾真正獲利」門檻
    ],
    "q3_04_tit_for_tat": [
        "tolerance_points",  # 見檔頭「有疑慮」說明：極小容忍值，縮放後語意需留意
        "stop_points",  # float | None，預設 20.0（非 None），照常縮放；None 維持 None
        "profit_target", "extreme_range", "extreme_from_prev_close",
        "retrace_trigger",  # 折返平倉／反手資格門檻（p.90-91）
    ],
    "q3_05_break_three_high_low": [
        "stop_points",
        "immediate_distance",
        "ignore_beyond",
        "reversal_profit_threshold",
        "retrace_trigger",  # 折返平倉門檻（p.111）
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
        "type34_extreme_points",  # T3-1/T4-1（第三/四型）觸極端門檻（p.206）
        "giant_bar_points",
        "stop_points",
        "early_exit_profit",
        "retrace_trigger",
        "reverse_max_distance",
        "no_reverse_profit",
        "five_min_points",  # 併用 q3-06 五連根出場：C2 幅度門檻
        "five_wick_max",  # 併用 q3-06 五連根出場：C7 影線上限
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
    # ---- 《股技期招》gq_* ----
    # 其餘 22 個 gq_* 模組的 Params 逐一檢查後，沒有價格點數欄位（門檻多為 K 線型態、百分比、
    # RSI/KD/MACD/DMI/威廉指標數值、根數等），不列入本表，縮放版即等於預設版。
    "gq_01_11_pivot_trendline_breakout": [
        "fixed_points",  # 轉折點過遠時改用固定停損（p.68-70）
        "big_candle_range_points",  # 判斷「巨大K線」的振幅門檻
        "ladder_target",  # exit_mode="ladder" 的獲利目標點數
        # stop_pct/confirm_max_drift_pct/body_min_pct 為百分比，不縮放
    ],
    "gq_04_02_dmi_stalagmite": [
        "points_target",  # exit_mode="points"，台指期分時固定點數出場（p.184，書中20~30點）
        # stop_pct 為百分比，不縮放；max_pct_from_extreme 為百分比，不縮放
    ],
}
