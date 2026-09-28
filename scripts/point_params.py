"""點數門檻縮放參數表（供 `scripts/run_scaled.py` 使用）。

背景：書中點數門檻（20 點停損、40 點極端位置…）是在《期貨奇績2》（q2_*，約台指期 8,500 點）
與《期貨奇績3》（q3_*，約台指期 10,000 點）的年代訂的；本專案回測期間台指期約 22,000→48,000 點。
本檔案只做「欄位分類」，**不修改任何方法模組**，也不改變預設值本身。

分類規則：
  - 會被列進 POINT_PARAMS[method] 的欄位＝「點數」（價格距離：停損、目標、濾網幅度、跳空、
    影線容忍值、折返/回檔點數、與平盤/前高低/均線的距離門檻…），套用等比例縮放
    （乘以 當時價位 / ref_price(方法)）。
  - 不列入的欄位＝根數(bars)、K線根數計數(min_run/five_min_bars等)、轉折層級(pivot_level)、
    MA/RSI/KD 週期、RSI/KD 數值本身（0-100 尺度，如 70/30、d_overbought）、比例(ratio)、
    成交量(口數)、布林開關、字串模式(mode/exit_mode)、時間(time)、次數上限(int count)等，
    這些不隨價格水位縮放。
  - dataclass 內的巢狀 helper class（如 `_Pivot`、`_SideState`、`_SessionState`、`_Chain`、
    `_Track`、`_NTrack`、`_LegState`）是策略內部執行時狀態，不是使用者參數，不在此列出。

最小跳動類（T 類，台指期一跳 1 點，不隨價位放大）**不列入**縮放（依
`methods/參數依賴盤點/IMPL_SPEC.md` 甲-3）：
  - q2_01／q2_02 的 trail_breach_points、range_breach_points（觸價確認「超過 1 點」）
  - q2_03_01／q2_03_02 的 ladder_ignore_diff（階梯高低點差距可忽略的點數）
  - q3_04.tolerance_points（兩根漲跌點數視為相等的容忍值）
  - q3_03.retrace_trigger（折返平倉的「曾真正獲利」門檻，以 tick 計）
  - sg_02.low_tol、sg_06.stop_offset（同上，以 tick 計）

有疑慮／邊界案例：
  - q2_04_01.second_signal_min_profit、q2_03_02.max_drift_from_breakout：
    預設皆為 None（功能關閉），縮放時维持 None（見 run_scaled.py 的縮放邏輯：None 不縮放，
    只縮放非 None 的數值型點數欄位）。
  - q3_10.diff_threshold：這是「RSI 值」的差距（RSI 是 0-100 尺度指標，不是價格），**不縮放**，
    不列入下表；讀者若誤以為所有 "*_threshold" 都是點數，此為反例。
  - q2_05_02.min_volume：成交量（口數），**不縮放**。
  - q3_11（波段方法）多數濾網以 RSI/MA 為主，點數欄位只有 retrace_points 一個。

  - q3_11.strike_step（履約價間距 100）：是台指選擇權的交易所履約價間距（實際合約規格），
    不是作者訂的門檻，**不縮放**，不列入下表。

參考價：縮放倍數 = 當時實際開盤價 / ref_price(方法)。
  - REF_PRICE：每本書（前綴 q2/q3/gq/sg）一個預設參考價。
  - REF_PRICE_BY_METHOD：個別方法的參考價（訂定年代與書／群組預設不同時），優先於 REF_PRICE。
  - ref_price(name)：先查 REF_PRICE_BY_METHOD[name]，再依前綴回退到 REF_PRICE。
  同一方法內所有點數欄位共用同一參考價（例如均線訊號停損法三欄位 stop_points／stop_min_offset／
  stop_integer_points 互相銜接，不可分開縮放）。
"""

from __future__ import annotations

REF_PRICE: dict[str, float] = {
    "q2": 8500.0,
    # 讀書會書外方法（sg_*）：以規則提出當時的台指期水位為準（sg-01：2021-04 約 16,500～17,500，取 17000）
    "sg": 17000.0,
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


# 讀書會書外方法 sg_* 訂定年代各不相同（約 9500～21500），依 methods/參數依賴盤點/sg.md 建議各自設定。
REF_PRICE_BY_METHOD: dict[str, float] = {
    # 2021-04 學員整理，台指期約 16500～17500（與 REF_PRICE["sg"] 相同，明列以免誤會）
    "sg_01_rsi_blunt_quick": 17000.0,
    # 作者原文 2017-02-09，圖例當天低點約 9505。停損三欄位出自助教 2020-07（約 12500）、
    # extreme_from_prev_close 借 q3 的 40 點（約 10000），但同一方法只能一個參考價，
    # 依 sg.md「若只能一個參考價則用 9500」取 9500（訊號門檻 first_move/second_move 的年代）。
    "sg_02_counterattack_line": 9500.0,
    # 訊號無點數門檻；停損三欄位是比照 sg-01 的推論 → 跟推論來源一致取 17000
    # （圖例 2023-04～06 約 15500～16750）。
    "sg_03_flat_kd": 17000.0,
    # 作者原文 2025-06-03，定義圖 2025-05-15 約 21750、2025-05-20 約 21540。
    "sg_04_dent": 21500.0,
    # 學員筆記 2019-08、助教說明 2018-03～11，圖例約 9450～10730。
    "sg_05_inside_box": 10000.0,
    # 有數值的規則出自 2021 年助教說明（約 17000）；若日後確認 2013 部落格為原始定義，再改約 8000。
    "sg_06_first_bar_color": 17000.0,
    # 助教說明與實例 2021-03～06（例：昨收 17090、今開 17190），方法文件記約 16000。
    "sg_07_gap_hundred": 16000.0,
    # 助教說明 2023-10-06（附圖報價約 16540）、2023-07-07。
    "sg_08_volume_expansion": 16500.0,
}

_PREFIXES = ("q2", "q3", "gq", "sg")


def ref_price(name: str) -> float:
    """回傳方法 name（模組名，如 "sg_04_dent"）的縮放參考價：先查 REF_PRICE_BY_METHOD，
    再依前綴 q2/q3/gq/sg 回退到 REF_PRICE。無法辨識前綴時拋出 KeyError（不默默套用錯誤價位）。"""
    if name in REF_PRICE_BY_METHOD:
        return REF_PRICE_BY_METHOD[name]
    for pre in _PREFIXES:
        if name.startswith(pre):
            return REF_PRICE[pre]
    raise KeyError(f"無法決定 {name!r} 的參考價：不在 REF_PRICE_BY_METHOD，且前綴不是 {_PREFIXES}")


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
        # trail_breach_points、range_breach_points 為最小跳動（T 類），不縮放
        "ma_fast_arm_profit",  # ma 出場：獲利達此點數後切換 MA(ma_fast_period)（p.42）
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
        # trail_breach_points、range_breach_points 為最小跳動（T 類），不縮放
        "time_stop_min_profit",
    ],
    "q2_03_01_pvt_n_type": [
        # ladder_ignore_diff 為最小跳動（T 類），不縮放
        "stop_min_offset",
        "stop_integer_points",
        "stop_max_risk",
        "max_pattern_points",
        "max_dev_from_ladder",
        "max_drift_from_breakout",
        "giveback_points",
    ],
    "q2_03_02_pvt_rsi": [
        # ladder_ignore_diff 為最小跳動（T 類），不縮放
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
    "sg_01_rsi_blunt_quick": [
        "stop_points",
        "stop_min_offset",
        "stop_integer_points",
        # window_minutes 為時間、ob/os_extreme 為 RSI 數值，不縮放
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
        # retrace_trigger 為最小跳動（T 類），不縮放
    ],
    "q3_04_tit_for_tat": [
        # tolerance_points 為最小跳動（T 類），不縮放
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
        "min_session_range",  # 預設 None 時不縮放
        # diff_threshold 是 RSI 值差距（0-100 尺度），不是點數，不縮放
    ],
    "q3_11_option_swing_breakout": [
        "retrace_points",
        # rsi_extreme_high/low、rsi_near_tol 為 RSI(0-100)數值，不縮放；
        # max_pullback_bars 為根數，不縮放。波段方法（intraday=False），見 run_scaled.py 說明。
        # strike_step 是台指選擇權交易所的履約價間距（實際合約規格，非作者門檻），不縮放。
    ],
    # ---- 《股技期招》gq_* ----
    # 其餘 19 個 gq_* 模組的 Params 逐一檢查後，沒有價格點數欄位（門檻多為 K 線型態、百分比、
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
    # gq_03_*：exit_mode="ladder" 的啟動獲利門檻（點數，原文未規定，預設 0＝推論）；
    # 預設 0 縮放後仍 0，改成非 0 時才有縮放效果。stop_tick 為最小跳動（T 類），不縮放。
    "gq_03_01_macd_n_turn": ["profit_target"],
    "gq_03_03_macd_double_cross": ["profit_target"],
    "gq_03_04_dif_streak_reversal": ["profit_target"],
    # ---- 讀書會書外方法 sg_*（參考價見 REF_PRICE_BY_METHOD；同一方法共用一個參考價）----
    "sg_02_counterattack_line": [
        "first_move",
        "second_move",
        "high_match_tol",  # 預設 None，維持 None
        "extreme_tol",  # 預設 0，縮放後仍 0
        "extreme_from_prev_close",  # 借 q3 的 40 點（約 10000），同方法一律用 9500
        "stop_points",
        "stop_min_offset",
        "stop_integer_points",
        # low_tol 為最小跳動（T 類），不縮放
    ],
    "sg_03_flat_kd": [
        "stop_points",
        "stop_min_offset",
        "stop_integer_points",
    ],
    "sg_04_dent": [
        "stop_points",
        "wait_offset",
        "large_bar_points",  # 預設 None，維持 None
        # max_wait_minutes 為時間，不縮放
    ],
    "sg_05_inside_box": [
        "max_first_range",
        "near_extreme_points",
        "stop_points",
    ],
    "sg_06_first_bar_color": [
        "gap_points",  # 預設 0，縮放後仍 0
        "max_stop_points",  # 預設 None，維持 None
        "stop_min_offset",
        "stop_integer_points",
        # stop_offset 為最小跳動（T 類），不縮放；breakout_window_minutes 為時間
    ],
    "sg_07_gap_hundred": [
        "gap_threshold",
        "stop_points",
        "stop_min_offset",
        "stop_integer_points",
    ],
    "sg_08_volume_expansion": [
        "stop_points",
        "stop_min_offset",
        "stop_integer_points",
        # base_volume、volume_increase 為成交量（口數，V 類），不縮放
    ],
}
