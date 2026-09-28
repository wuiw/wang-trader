# 參數依賴盤點：《股技期招》gq_*（24 個模組、233 個參數）

依 `methods/參數依賴盤點/SPEC.md` 盤點。資料來源：`all_params.tsv`、`src/wangtrader/methods/gq_*.py`、
`methods/股技期招/gq-*.md`、`scripts/point_params.py`。

## 共同背景

- **規則訂定年代與價位**：書中台指期範例集中在民國 97～98 年（2008-05～2009-02），報價約 4300～9400；
  `REF_PRICE["gq"]＝7000`（見 `scripts/point_params.py` 註解）。個股範例則是當年的台股日線（元，非點數）。
- **本書多數方法是「個股日線」方法**（gq-01-01～gq-01-10、gq-02-*、gq-03-*、gq-04-01），
  只有 gq-01-11（台指期 5 分K／個股日線）、gq-04-02（週/日線／台指期 1、5 分）、gq-04-03（日線／台指期 3、5、30 分）
  有台指期分時範例。本專案回測卻把全部 gq 模組放在台指期 1／3／5 分K 上跑（`intraday=False` 波段）。
- 因此本組的主要失真**不是點數**（真正的點數參數只有 7 個），而是：
  1. **百分比門檻（I 類）是依「個股日K」波動訂的**：大K 4%、長紅 3%、跳空 5%、7% 停損等，換到台指期分K
     （2～4 萬點下 1% ≈ 200～400 點）幾乎不會成立或等於沒設。SPEC 將百分比列為「不換算」（與價位無關），
     這點成立，但它們**依商品波動度與 K 線週期**，換週期／換商品時需另訂。
  2. **以「天」描述的根數（B 類）**：20 交易日、季線 60、年線 240、「一個月」30、「不出幾天」10…，
     在 1 分K 上變成 20 分鐘、4 小時，意義完全不同。
  3. **台股制度參數（X 類）**：漲停 7%（2015-06 起台股漲跌幅已改 10%）、平盤下禁空，台指期沒有這些制度。
  4. **「一檔」停損（T 類）**：`stop_tick=1.0`，台指期 1 點＝1 檔正確；個股的一檔隨股價 0.01～5 元變動，ES 為 0.25。
- 目前 2～4 萬點下，以 REF 7000 計的縮放倍數約 **3～6 倍**。

以下每節表格只列 P／T／V／B／C／X 類，以及少數在台指期分K上會明顯失真的 I 類；其餘 N、I、B0 合併為一列。

---

## gq-01-01 大陽線／大陰線移動出場（`gq_01_01_big_bar_trail_exit`）

年代：書（2008～2009）；個股日K；台指約 7000（本法無台指期範例）。

| 參數 | 預設值 | 類別 | 作用 | POINT_PARAMS | 2～4 萬點台指下的實際影響 | 建議換算 |
|---|---|---|---|---|---|---|
| big_bar_pct | 4.0 | I | 大陽／大陰線判定（出場水準的來源） | — | 台指期 1～5 分K 實體 4%（800～1600 點）幾乎不出現，出場水準永遠不會建立 | 百分比不隨價位換算；換到分K需依週期另訂（例如近 N 根實體的百分位或 ATR 倍數） |

問題清單：
- 本模組沒有進場邏輯，單獨回測永遠 0 筆；`big_bar_pct` 在分K上等於關閉出場。

## gq-01-02 轉變線反轉訊號（`gq_01_02_transition_candle`）

年代：書；個股日K；台指約 7000。

| 參數 | 預設值 | 類別 | 作用 | POINT_PARAMS | 實際影響 | 建議換算 |
|---|---|---|---|---|---|---|
| doji_body_max_pct | 0.3 | I（容差%） | 開收「同價」容差 | — | 3 萬點時＝90 點，分K上幾乎每根小K都算十字；本質是「同價」誤差 | 分K宜改用 tick 容差（T 類，台指 1～2 點） |
| no_shadow_max_pct | 0.1 | I（容差%） | 「無影線」容差 | — | 3 萬點時＝30 點，對分K過寬 | 同上，改用 tick |
| long_shadow_min_pct | 2.0 | I | 長影線門檻 | — | 3 萬點時＝600 點，分K上永不成立 → 訊號消失 | 依週期另訂（相對實體倍數或 ATR） |
| 其餘 | uptrend_ma_period 20、vol_ma_period 20、vol_spike_ratio 2.0、require_volume_spike True | N/I | — | — | 不需換算 | — |

問題清單：
- `long_shadow_min_pct` 在台指期分K上讓訊號消失；`doji_body_max_pct`／`no_shadow_max_pct` 則反向過寬。三者都是依個股日K百分比定的推論值。

## gq-01-03 夜星反轉（`gq_01_03_evening_star`）

年代：書；個股日K；台指約 7000。

| 參數 | 預設值 | 類別 | 作用 | POINT_PARAMS | 實際影響 | 建議換算 |
|---|---|---|---|---|---|---|
| high_lookback | 20 | B | C1 近 N 根新高（波段高點附近，推論以日計） | — | 1 分K＝20 分鐘新高，條件大幅放寬 | 改以時間（交易日數或分鐘）描述 |
| rally_lookback | 10 | B | C1 連續大漲回顧 | — | 1 分K＝10 分鐘 | 同上 |
| rally_min_pct | 15.0 | I | C1 累計漲幅 15% | — | 分K 10 根內漲 15% 不可能 → 訊號消失 | 依週期另訂 |
| long_candle_min_pct | 3.0 | I | C2 長紅 | — | 分K不成立 | 依週期另訂 |
| 其餘 | star_max_body_pct 1.0、vol_ma_period 20、vol_spike_ratio 2.0、entry_trigger、check_volume_shrink_filter、vol_shrink_ratio 0.5、shrink_ma_period 10 | N/I | — | — | 不需換算 | — |

問題清單：
- `rally_min_pct`（15%）與 `long_candle_min_pct`（3%）在台指期分K上讓訊號完全消失；lookback 根數以日K設計，換週期意義改變。

## gq-01-04 執帶反轉與反軋買點（`gq_01_04_black_belt_hold`）

年代：書；個股日K；台指約 7000。

| 參數 | 預設值 | 類別 | 作用 | POINT_PARAMS | 實際影響 | 建議換算 |
|---|---|---|---|---|---|---|
| rally_lookback | 10 | B | C1 連續上漲回顧（推論以日計） | — | 1 分K＝10 分鐘 | 改以時間描述 |
| limit_up_pct | None | X（台股制度） | C1 漲停 | — | 關閉；台指期無漲停概念 | 依市場漲跌幅制度另訂（台股現制 10%，書的年代 7%） |
| gap_up_min_pct | 5.0 | I | C2 跳空開高 ≥5%（原文） | — | 分K上不可能（台指期單日跳空 5% 也極少）→ 訊號消失 | 依商品另訂 |
| open_is_high_tolerance_pct／close_is_low_tolerance_pct | 0.1 | I（容差%） | 開盤即最高、收最低的容差 | — | 3 萬點時＝30 點，過寬 | 改用 tick 容差 |
| long_candle_min_pct | 3.0 | I | C1 長紅 | — | 分K不成立 | 依週期另訂 |
| 其餘 | rally_min_pct 10、consecutive_limit_up_min 0、belt_max_gain_pct 1.5、vol_ma_period、vol_spike_ratio | N/I/B0 | — | — | 不需換算 | — |

問題清單：
- `gap_up_min_pct` 5% 與 `long_candle_min_pct` 3% 在台指期分K上讓訊號消失；`limit_up_pct` 是台股制度參數。

## gq-01-05 覆蓋線反轉與反軋買點（`gq_01_05_dark_cloud_cover`）

年代：書；個股日K；台指約 7000。

| 參數 | 預設值 | 類別 | 作用 | POINT_PARAMS | 實際影響 | 建議換算 |
|---|---|---|---|---|---|---|
| high_lookback | 20 | B | C1 高檔區域（日） | — | 1 分K＝20 分鐘 | 改以時間描述 |
| rally_lookback | 10 | B | C1 回顧 | — | 同上 | 同上 |
| long_candle_min_pct | 3.0 | I | C1 長紅 | — | 分K不成立 → 訊號消失 | 依週期另訂 |
| rally_min_pct | 10.0 | I | C1 累計漲幅 | — | 分K不成立 | 依週期另訂 |
| 其餘 | gap_up_max_pct 3.0、vol_ma_period、vol_spike_ratio | N/I | — | — | 不需換算 | — |

問題清單：
- 同 gq-01-04：長紅 3%、累計漲 10% 在分K上不會出現。

## gq-01-06 吞噬線反轉與反軋買點（`gq_01_06_bearish_engulfing`）

年代：書；個股日K；台指約 7000。

| 參數 | 預設值 | 類別 | 作用 | POINT_PARAMS | 實際影響 | 建議換算 |
|---|---|---|---|---|---|---|
| high_lookback | 20 | B | C1 高檔（日） | — | 1 分K＝20 分鐘 | 改以時間描述 |
| rally_lookback | 10 | B | C1 回顧 | — | 同上 | 同上 |
| long_candle_min_pct | 3.0 | I | A 長紅 | — | 分K不成立 | 依週期另訂 |
| rally_min_pct | 10.0 | I | C1 累計漲幅 | — | 分K不成立 | 依週期另訂 |
| 其餘 | engulf_gap_max_pct 3.0、vol_ma_period、vol_spike_ratio | N/I | — | — | 不需換算 | — |

問題清單：
- 同 gq-01-05。

## gq-01-07 下墜線反轉與反軋買點（`gq_01_07_falling_line_reversal`）

年代：書；個股日K；台指約 7000。

| 參數 | 預設值 | 類別 | 作用 | POINT_PARAMS | 實際影響 | 建議換算 |
|---|---|---|---|---|---|---|
| lookback_bars | 60 | B | 找近期最高點判高檔（推論以日計，約一季） | — | 1 分K＝1 小時 | 改以時間描述 |
| long_red_body_pct | 3.0 | I | 長紅判定 | — | 分K不成立 → 訊號消失 | 依週期另訂 |
| far_from_top_pct | 15.0 | I | 跌勢已一段 | — | 分K上 60 根內跌 15% 不可能 | 依週期另訂 |
| 其餘 | near_top_pct 5.0、volume_lookback 20、surge_volume_multiple 2.0、low_volume_multiple 1.2 | N/I | — | — | 不需換算 | — |

問題清單：
- `long_red_body_pct`、`far_from_top_pct` 在分K上讓訊號消失；`near_top_pct` 5% 則在分K上幾乎恆成立（過寬）。

## gq-01-08 K線慣性操作（`gq_01_08_ma_inertia`）

年代：書；個股日K；台指約 7000。

| 參數 | 預設值 | 類別 | 作用 | POINT_PARAMS | 實際影響 | 建議換算 |
|---|---|---|---|---|---|---|
| long_exit_n／short_exit_n | 4 | B | 跌破前 N 日低點出場（原文 1/2/4/8「日」） | — | 1 分K＝4 分鐘區間，出場極快 | 以交易日或分鐘描述 |
| no_short_below_flat | True | X（台股制度） | 平盤下禁空：放空改掛限價等回平盤 | — | 台指期沒有此限制；開著會讓空單大量掛不到或延後成交 | 台指期應設 False；依市場制度另訂 |
| flat_wait_bars | 60 | B | 等回平盤的最長根數（推論） | — | 1 分K＝1 小時、5 分K＝5 小時 | 改用分鐘 |
| 其餘 | fast_period 10、slow_period 20、use_ema | N | — | — | 不需換算 | — |

問題清單：
- `no_short_below_flat=True` 是台股現貨制度，套在台指期上是規則失真（非價位問題）。

## gq-01-09 慣性破壞買訊（`gq_01_09_inertia_break_buy`）

年代：書；個股日K；台指約 7000。

| 參數 | 預設值 | 類別 | 作用 | POINT_PARAMS | 實際影響 | 建議換算 |
|---|---|---|---|---|---|---|
| lookback_days | 20 | B | C1 整理超過 20 個交易日（原文） | — | 1 分K＝20 分鐘，整理條件大幅放寬 | 改以交易日描述（或分鐘＝20×300） |
| big_bar_body_pct | 4.0 | I | C2 大漲K | — | 分K不成立 → 訊號消失 | 依週期另訂 |
| stop_pct | 7.0 | I | 7% 停損 | — | 3 萬點時＝2100 點，等同無停損 | 依商品另訂（7% 源自台股跌停幅度） |
| 其餘 | horizontal_range_pct 20、trend_pivot_level 2、require_ma_breakout、ma_period 20、stop_mode | N/I | — | — | 不需換算 | — |

問題清單：
- `big_bar_body_pct` 4% 讓分K訊號消失；`lookback_days` 以日計卻以根數實作。

## gq-01-10 首度漲停買進（`gq_01_10_first_limit_up`）

年代：書（範例 2007～2008 個股）；個股日線專用；台指約 7000。

| 參數 | 預設值 | 類別 | 作用 | POINT_PARAMS | 實際影響 | 建議換算 |
|---|---|---|---|---|---|---|
| limit_up_pct | 7.0 | X（台股制度） | C2 漲停判定 | — | 書的年代漲跌幅 7%；2015-06 起台股為 10%，用 7% 會把非漲停誤判為漲停；台指期分K永不成立 | 依市場／年代的漲跌幅制度設定 |
| lookback_days | 50 | B | C1 回顧交易日 | — | 1 分K＝50 分鐘 | 以交易日描述 |
| year_bars | 240 | B | F1 近一年最大量 | — | 1 分K＝4 小時 | 以交易日描述 |
| exit_channel_n | 10 | B | channel 出場視窗 | — | 分K＝10 分鐘 | 以交易日描述 |
| 其餘 | limit_up_tol 0.3、max_volume_multiple 1.5、trough_pivot_level、max_from_trough_pct 20、primary_stop_pct 7、reversal_on_break_signal_low、exit_mode | N/I | — | — | 不需換算 | — |

問題清單：
- 商品限定個股；`limit_up_pct` 綁台股制度與年代，在台指期上訊號為 0。

## gq-01-11 轉折點趨勢線突破訊號（`gq_01_11_pivot_trendline_breakout`）

年代：書，台指期 5 分K 範例 970516～970808（2008，約 6900～9400）；REF 7000。

| 參數 | 預設值 | 類別 | 作用 | POINT_PARAMS | 實際影響 | 建議換算 |
|---|---|---|---|---|---|---|
| fixed_points | 30.0 | P | 轉折點過遠時固定停損（p.68-70，原文台指期 30 點） | 已登記 | 未縮放時 3 萬點下只佔 0.1%，停損過窄；縮放後約 90～180 點 | 值 × 當時價 ÷ 7000 |
| big_candle_range_points | 60.0 | P | 巨大K線（改以中點停損）門檻（推論） | 已登記 | 未縮放時分K很容易超過 60 點 → 中點停損過度觸發 | 同上 |
| ladder_target | 30.0 | P | ladder 出場獲利門檻（推論） | 已登記 | 預設 exit_mode="none" 不使用 | 同上 |
| fast_period／slow_period | 20／50 | B | 多空判斷均線；原文為 5 分K 的 MA300（五日）／MA180（三日） | — | 原文本質是「日數」均線，簡化為 20／50 根後在不同週期意義不同 | 依週期換算成對應日數的根數 |
| confirm_max_wait | 10 | B | C6 等確認K最長根數（推論） | — | 隨週期改變時間長度 | 改用分鐘 |
| exit_channel_n | 10 | B | channel 出場視窗 | — | 同上 | 同上 |
| 其餘 | pivot_level 2、require_ma_confirm、reject_bad_candle、body_min_pct 1.0、confirm_max_drift_pct 5.0、stop_mode、stop_pct 7.0、big_candle_mid_override、exit_mode | N/I | — | — | 不需換算 | — |

問題清單：
- `body_min_pct` 1%（3 萬點＝300 點）在分K上幾乎每根都算「小星線」，C6 會大量拒絕訊號或等待確認。
- REF 7000 是 2008 年範例的中間值，範例本身在 4300～9400 間，縮放倍數有 ±30% 的不確定性。

## gq-02-01 RSI 連續下跌慣性改變買點（`gq_02_01_rsi_falling_momentum_reversal`）

年代：書；個股日線；台指約 7000。

| 參數 | 預設值 | 類別 | 作用 | POINT_PARAMS | 實際影響 | 建議換算 |
|---|---|---|---|---|---|---|
| season_period | 60 | B | 季線（60 日） | — | 1 分K＝1 小時均線，已非「季線」 | 依週期換算成 60 交易日的根數 |
| year_period | 240 | B | 年線（240 日） | — | 1 分K＝4 小時 | 同上 |
| n_window_long | 10 | B | model4 區間根數（日） | — | 分K＝10 分鐘 | 以交易日描述 |
| reversal_pct | 0.03 | I | C3 反漲K 漲幅 3% | — | 分K不成立 → 訊號消失 | 依週期另訂 |
| 其餘 | rsi_period 5、rsi_method、trend_lookback 1、down_run_days 6、stop_pct 0.07、exit_mode、big_bar_pct 0.04、pivot_level | N/I/B0 | — | — | 不需換算 | — |

問題清單：
- `reversal_pct` 3% 讓分K訊號消失；季線／年線以根數實作，換週期後不是原意。

## gq-02-02 RSI 低值買點與背離買點（`gq_02_02_rsi_oversold_and_divergence`）

年代：書；個股日線；台指約 7000。

| 參數 | 預設值 | 類別 | 作用 | POINT_PARAMS | 實際影響 | 建議換算 |
|---|---|---|---|---|---|---|
| big_bar_pct | 0.05 | I | C2 大漲K 5% | — | 分K不成立 → 訊號消失 | 依週期另訂 |
| stop_pct | 0.07 | I | 7% 停損 | — | 3 萬點時 2100 點，等同無停損 | 依商品另訂 |
| 其餘 | rsi_period、rsi_method、oversold_level 20、pivot_level、stop_mode | N/I | — | — | 不需換算 | — |

問題清單：
- `big_bar_pct` 5% 讓分K訊號消失。

## gq-02-03 RSI 穿越 80 買點（`gq_02_03_rsi_cross_80`）

年代：書；個股日線（強勢股）；台指約 7000。

| 參數 | 預設值 | 類別 | 作用 | POINT_PARAMS | 實際影響 | 建議換算 |
|---|---|---|---|---|---|---|
| stop_tick | 1.0 | T | 真實低點下一檔停損 | —（T 類不登記） | 台指期 1 點＝1 檔，正確 | 以商品 tick 計（個股依股價級距；ES 0.25） |
| big_bar_pct | 0.05 | I | C3 大漲K 5% | — | 分K不成立 → 訊號消失 | 依週期另訂 |
| 其餘 | rsi_period、rsi_method、upper_threshold 80、mid_threshold 50、enable_cross50、shadow_max_pct None | N/I | — | — | 不需換算 | — |

問題清單：
- `big_bar_pct` 5% 讓分K訊號消失。

## gq-02-04 KD 黃金死亡交叉三日濾網（`gq_02_04_kd_cross_gap_filter`）

年代：書；個股／陸股日線；台指約 7000。

| 參數 | 預設值 | 類別 | 作用 | POINT_PARAMS | 實際影響 | 建議換算 |
|---|---|---|---|---|---|---|
| gap_days_max | 3 | B | C3 三日濾網 | — | 1 分K＝3 分鐘 | 以交易日描述 |
| stop_tick | 1.0 | T | peak_tick 停損（一檔） | — | 台指正確 | 以 tick 計 |
| black_bar_pct | 0.04 | I | 長黑K（空方移動停損） | — | 分K不成立，移動停損失效 | 依週期另訂 |
| 其餘 | trend_fast 5、trend_slow 20、kd 9/3/3、d_cross_max 65、k_cross_min 20、pivot_level、tier_pct 0.02、black_k_required、stop_mode、stop_pct 0.07、long_stop_pct None、trailing_black_bar | N/I | — | — | 不需換算 | — |

問題清單：
- 「三日」以 3 根實作；`tier_pct` 2%（3 萬點＝600 點）在分K上幾乎所有進場都算「同位階」。

## gq-02-05 KD 提前買點－K 值背離收盤過高（`gq_02_05_kd_early_breakout_divergence`）

年代：書；個股日線；台指約 7000。

| 參數 | 預設值 | 類別 | 作用 | POINT_PARAMS | 實際影響 | 建議換算 |
|---|---|---|---|---|---|---|
| stop_tick | 1.0 | T | 真實低點下一檔 | — | 台指正確 | 以 tick 計 |
| 其餘 | trend_fast、trend_slow、kd 9/3/3、k_threshold 50、stop_mode、stop_pct 0.07 | N/I | — | — | 不需換算 | — |

問題清單：無價位問題；`stop_pct` 7% 在台指期上等同無停損（僅 pct 模式）。

## gq-02-06 KD 提前買點－均線多排 K 值轉折向上（`gq_02_06_kd_early_turn_up`）

年代：書；個股日線；台指約 7000。

| 參數 | 預設值 | 類別 | 作用 | POINT_PARAMS | 實際影響 | 建議換算 |
|---|---|---|---|---|---|---|
| stop_tick | 1.0 | T | 真實低點下一檔 | — | 台指正確 | 以 tick 計 |
| 其餘 | trend_fast、trend_slow、kd 9/3/3、k_threshold 50、require_prior_decline、stop_mode、stop_pct 0.07 | N/I | — | — | 不需換算 | — |

問題清單：無價位問題。

## gq-03-01 金叉後低轉折買點（`gq_03_01_macd_n_turn`）

年代：書；個股日線；台指約 7000。

| 參數 | 預設值 | 類別 | 作用 | POINT_PARAMS | 實際影響 | 建議換算 |
|---|---|---|---|---|---|---|
| profit_target | 0.0 | P | ladder 出場啟動獲利門檻（點數，推論） | **未登記** | 預設 0 且 exit_mode="none"，目前無影響；使用者改成非 0 點數時不會被縮放 | 值 × 當時價 ÷ 7000；應登記 |
| stop_tick | 1.0 | T | 期間最低點下一跳 | — | 台指正確 | 以 tick 計 |
| max_bars_since_cross | 10 | B | C4「不出幾天」 | — | 1 分K＝10 分鐘 | 以交易日描述 |
| 其餘 | fast/slow/signal 12/26/9、require_red、max_upper_shadow_ratio 1.0、require_break_prev_high、stop_mode、fixed_stop_pct None、exit_mode | N/I | — | — | 不需換算 | — |

問題清單：
- `profit_target` 為點數卻未登記（opt-in 時漏縮放）。

## gq-03-02 死叉後高轉折賣出訊號（`gq_03_02_macd_reverse_n_turn`）

年代：書；個股、加權指數日線；台指約 7000。

| 參數 | 預設值 | 類別 | 作用 | POINT_PARAMS | 實際影響 | 建議換算 |
|---|---|---|---|---|---|---|
| days_since_cross_max | 20 | B | F1 拖延超過 20 天失效（原文） | — | 1 分K＝20 分鐘 | 以交易日描述 |
| stop_tick | 1.0 | T | 峰頂上方一檔 | — | 台指正確 | 以 tick 計 |
| 其餘 | fast/slow/signal、require_no_immediate_drop、stop_mode、fixed_stop_pct 0.07 | N/I | — | — | 不需換算 | — |

問題清單：「20 天」以根數實作。

## gq-03-03 雙金叉反轉買點（`gq_03_03_macd_double_cross`）

年代：書；個股日線；台指約 7000。

| 參數 | 預設值 | 類別 | 作用 | POINT_PARAMS | 實際影響 | 建議換算 |
|---|---|---|---|---|---|---|
| profit_target | 0.0 | P | ladder 啟動門檻（點數，推論） | **未登記** | 預設 0，目前無影響；改非 0 時漏縮放 | 值 × 當時價 ÷ 7000；應登記 |
| max_bars_between_crosses | 30 | B | C4 兩次金叉間隔「一個月」 | — | 1 分K＝30 分鐘 | 以交易日描述 |
| 其餘 | fast/slow/signal、require_red、pivot_level 2、exit_mode | N | — | — | 不需換算 | — |

問題清單：`profit_target` 漏登；「一個月」以根數實作。

## gq-03-04 DIF 慣性改變（`gq_03_04_dif_streak_reversal`）

年代：書；個股日線；台指約 7000。

| 參數 | 預設值 | 類別 | 作用 | POINT_PARAMS | 實際影響 | 建議換算 |
|---|---|---|---|---|---|---|
| profit_target | 0.0 | P | ladder 啟動門檻（點數，推論） | **未登記** | 預設 0，目前無影響；改非 0 時漏縮放 | 值 × 當時價 ÷ 7000；應登記 |
| min_decline_days | 23 | B | C1 DIF 連跌 23 天（原文，約一個月的慣性） | — | 1 分K＝23 分鐘，慣性意義不同 | 以交易日描述 |
| pct_gain_min | 4.0 | I | C3 漲幅 4% | — | 分K不成立 → 訊號消失 | 依週期另訂 |
| 其餘 | fast/slow/signal、stop_pct 7.0、exit_mode | N/I | — | — | 不需換算 | — |

問題清單：`pct_gain_min` 4% 讓分K訊號消失；`profit_target` 漏登。

## gq-04-01 乖離率買點（`gq_04_01_bias_reversal_buy`）

年代：書；個股日線；台指約 7000。

| 參數 | 預設值 | 類別 | 作用 | POINT_PARAMS | 實際影響 | 建議換算 |
|---|---|---|---|---|---|---|
| near_limit_pct | 8.0 | X（台股制度） | C2b「接近漲停」（推論） | — | **書的年代漲停 7%，8% 永遠達不到**；現制 10% 下才有意義；台指期分K永不成立 | 依漲跌幅制度設定（例如漲停幅度 × 0.8～0.9） |
| search_window | 3 | B | 3 天內找濾網K（原文） | — | 1 分K＝3 分鐘 | 以交易日描述 |
| bias_threshold | -12.0 | I | 10 日乖離 -12% | — | 分K上 10 根乖離 -12% 不可能 → 訊號消失 | 依週期另訂 |
| 其餘 | bias_period 10、require_shadow_ok、close_position_ratio None、require_gain_min None、enable_divergence、stop_mode、stop_pct 7.0 | N/I | — | — | 不需換算 | — |

問題清單：
- `near_limit_pct` 預設 8% 與書的年代（7% 漲停）矛盾；`bias_threshold` 在分K上讓訊號消失。

## gq-04-02 DMI 石筍現象（`gq_04_02_dmi_stalagmite`）

年代：書；個股週/日線與台指期 1、5 分（2008～2009）；REF 7000。

| 參數 | 預設值 | 類別 | 作用 | POINT_PARAMS | 實際影響 | 建議換算 |
|---|---|---|---|---|---|---|
| points_target | 25.0 | P | exit_mode="points" 固定點數出場（書中 20～30 點，台指期 1 分） | 已登記 | 預設 exit_mode="none" 不使用；使用時未縮放 25 點在 3 萬點下過小 | 值 × 當時價 ÷ 7000 |
| stop_tick | 1.0 | T | 峰谷外一檔（書中分時 1～3 檔） | — | 台指正確，但分時原文為 1～3 檔 | 以 tick 計 |
| max_bars_from_extreme | 3 | B | 時效濾網：日/週線 3 天；分時 4 或 10 根 | — | 預設採日線值，套在分K上偏嚴 | 依週期切換（原文已分週期） |
| max_pct_from_extreme | 15.0 | I | 時效濾網：距峰谷 15%（日/週線） | — | 分K上永遠不會超過 → 等於關閉（原文分時未提此濾網） | 分時設 None |
| 其餘 | dmi_period 14、base_level 25、short_threshold 40、long_threshold 35、down_bar_tolerance 3、five_bar_n 5、mirror_long_exception、stop_mode、stop_pct 7、exit_mode、rsi_period 5、rsi_overbought 70、rsi_oversold 30 | N/I/B0 | — | — | 不需換算（`long_threshold` 分時原文為 40，屬週期差異） | — |

問題清單：
- 預設值混用日線版（3 天、15%、-DI 35）與分時版（points 出場），在分K回測時應整組切換成分時值。

## gq-04-03 威廉指標找極端點（`gq_04_03_williams_extreme`）

年代：書；個股日線與台指期 3、5、30 分（範例 2007-12～2008-12，約 4500～8300）；REF 7000。

| 參數 | 預設值 | 類別 | 作用 | POINT_PARAMS | 實際影響 | 建議換算 |
|---|---|---|---|---|---|---|
| no_entry_after | None | C | F6 收盤前半小時不進場（原文當沖） | — | 關閉；若開啟需依交易所收盤時間設定 | 以「收盤前 30 分鐘」相對時間表示 |
| stop_tick | 1.0 | T | 峰谷外一檔（分時原文 1～3 檔） | — | 台指正確 | 以 tick 計 |
| max_dwell_bars | 10 | B | F3 停留超買超賣逾 10「天」（原文限日線） | — | 分K＝10 分鐘，過嚴 | 依週期另訂或改用時間 |
| long_stay_threshold | 20 | B | 長時間停留例外（原文 30 分K 20 根＝10 小時） | — | 預設關閉；開啟時在 1 分K＝20 分鐘 | 改用分鐘（約 600 分） |
| 其餘 | williams_period 50、overbought/oversold 80/90/20/10、max_bars_from_extreme 4、inertia_bars 8、long_stay_exception、stop_mode、stop_pct 7 | N/I/B0 | — | — | 不需換算 | — |

問題清單：
- `max_dwell_bars` 為日線數字，套用在分K上會過早排除訊號；`no_entry_after` 若開啟須依商品收盤時間。

---

## 本組小結（gq，233 個參數）

| 類別 | 數量 |
|---|---|
| P 價格點數 | 7 |
| T 最小跳動 | 8 |
| V 成交量 | 0 |
| B 根數（原文以時間描述） | 31 |
| B0 根數（型態本身） | 7 |
| C 時鐘時間 | 1 |
| I 指標數值／百分比／倍數 | 81 |
| N 期數／層級／模式 | 94 |
| X 其他（台股制度） | 4 |

**已登記 POINT_PARAMS（4 個）**：gq_01_11 `fixed_points`、`big_candle_range_points`、`ladder_target`；gq_04_02 `points_target`。

**漏登 POINT_PARAMS（3 個，皆預設 0.0、ladder 啟動門檻，目前不影響結果，但改成非 0 時不會縮放）**：
gq_03_01 `profit_target`、gq_03_03 `profit_target`、gq_03_04 `profit_target`。

**V 類**：無（gq 的量能條件都是均量倍數，屬 I，本來就是相對量）。

**B 類（31）**：
gq_01_03 high_lookback、rally_lookback；gq_01_04 rally_lookback；gq_01_05 high_lookback、rally_lookback；
gq_01_06 high_lookback、rally_lookback；gq_01_07 lookback_bars；gq_01_08 long_exit_n、short_exit_n、flat_wait_bars；
gq_01_09 lookback_days；gq_01_10 lookback_days、year_bars、exit_channel_n；
gq_01_11 fast_period、slow_period、confirm_max_wait、exit_channel_n；
gq_02_01 season_period、year_period、n_window_long；gq_02_04 gap_days_max；
gq_03_01 max_bars_since_cross；gq_03_02 days_since_cross_max；gq_03_03 max_bars_between_crosses；gq_03_04 min_decline_days；
gq_04_01 search_window；gq_04_02 max_bars_from_extreme；gq_04_03 max_dwell_bars、long_stay_threshold。

**C 類（1）**：gq_04_03 `no_entry_after`。

**T 類（8）**：`stop_tick` 於 gq_02_03、gq_02_04、gq_02_05、gq_02_06、gq_03_01、gq_03_02、gq_04_02、gq_04_03。

**X 類（4，台股制度）**：gq_01_04 `limit_up_pct`、gq_01_08 `no_short_below_flat`、gq_01_10 `limit_up_pct`、gq_04_01 `near_limit_pct`。

**本組最主要的失真來源**：不是點數，而是「個股日K百分比門檻」與「以天計的根數」被原封不動套在台指期分K上。
至少 gq-01-02～gq-01-07、gq-01-09、gq-02-01～gq-02-03、gq-03-04、gq-04-01 共 12 個模組的核心進場條件
（大K 3～5%、累計漲 10～15%、跳空 5%、乖離 -12%）在 1～5 分K 上幾乎不可能成立；7% 停損在 2～4 萬點下
等於 1400～2800 點，實際上沒有停損。這些參數依 SPEC 屬「不隨價位換算」，但若要在分K回測，需依週期另訂（例如以 ATR 或近 N 根分布的百分位表示）。
