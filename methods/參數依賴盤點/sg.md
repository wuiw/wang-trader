# 參數依賴盤點：讀書會書外方法 sg_*（8 個模組、68 個參數）

依 `methods/參數依賴盤點/SPEC.md` 盤點。資料來源：`all_params.tsv`、`src/wangtrader/methods/sg_*.py`、
`methods/讀書會/sg-*.md`、`methods/讀書會/SG_SPEC.md`、`scripts/point_params.py`；
sg-03、sg-04、sg-08 的圖例報價列已親自開 `reference/study-group/` 原圖核對。

## 共同背景

- 全部是台指期分K（1／3／5 分）當沖方法，規則由作者貼文、助教說明或學員整理而來，**各方法訂定年代不同**，
  價位從約 9500 到約 21500 都有。
- 目前 `REF_PRICE` 只有一個 `"sg": 17000`（依 sg-01 訂的），`POINT_PARAMS` 只登記了 sg_01。
  若把 17000 套到全部 sg，sg-02（9500）、sg-05（10000）會縮放不足，sg-04（21500）會縮放過頭。
  **建議改為每個方法各自的參考價**（見檔尾建議表）。
- **均線訊號停損法三參數**（`stop_points` 上限 20、`stop_min_offset` 10、`stop_integer_points` 20）：
  除 sg-02（助教 20 點）、sg-04、sg-05（原文 20 點）外，其餘是 SG_SPEC 通則借自《期貨奇績2》q2-01（約 8500）的推論值。
  三者在程式中互相銜接（停損距離超過 `stop_points` 才改用 `10＋個位數`／`20−個位數`，個位數 0 時 `stop_integer_points`），
  **同一方法內三者應用同一個參考價縮放**，否則「20 點上限」與「整數價位 20 點」會不一致。
- `_digit_stop` 的「個位數」（0～9）取自價格本身，不會被縮放：縮放後的公式變成 `10k＋個位數`，
  個位數部分的相對比重會隨價位變小。這是公式本身的價位依賴，不是參數，僅記錄。
- 2～4 萬點下（以 3 萬點為例）各方法的縮放倍數約 1.4～3.2 倍。

以下表格只列 P／T／V／B／C／X 類；N、I、B0 合併一列。

---

## sg-01 RSI 鈍化簡化買訊／空訊（`sg_01_rsi_blunt_quick`）

年代：2021-04（學員整理），台指期約 16500～17500 → 參考價 **17000**（已是現行 `REF_PRICE["sg"]`）。

| 參數 | 預設值 | 類別 | 作用 | POINT_PARAMS | 3 萬點下的實際影響 | 建議換算 |
|---|---|---|---|---|---|---|
| stop_points | 20.0 | P | 停損上限（推論）：首根極端點距離超過即改用均線訊號停損法 | 已登記 | 未縮放時 20 點約 0.07%，大部分訊號改走均線停損法 | × 價 ÷ 17000（≈35） |
| stop_min_offset | 10.0 | P | 均線訊號停損法固定部分 | 已登記 | 同上 | 同上 |
| stop_integer_points | 20.0 | P | 整數價位固定點數 | 已登記 | 同上 | 同上 |
| window_minutes | 10.0 | B | 首根後的有效時間窗（原文 1 分K 十根／5 分K 三根） | — | 已換成分鐘，不受週期影響 | 已處理；5 分K 原文約 15 分 |
| 其餘 | rsi_period 5、rsi_method、ob_extreme 90、os_extreme 10 | N/I | — | — | 不需換算 | — |

問題清單：無漏登。原文 1 分K 十根與 5 分K 三根分別是 10 與 15 分，單一 `window_minutes` 只能擇一。

## sg-02 逆襲線買訊／空訊（`sg_02_counterattack_line`）

年代：作者原文 **2017-02-09**，圖例當天低點約 9505 → 訊號門檻參考價 **9500**；
助教「停損抓 20 點」是 2020-07-30（台指期約 12500），「空方高點差 1 點」是 2020-04。

| 參數 | 預設值 | 類別 | 作用 | POINT_PARAMS | 3 萬點下的實際影響 | 建議換算 |
|---|---|---|---|---|---|---|
| first_move | 7.0 | P | 前根黑K跌 ≥7 點（原文） | **未登記** | 相對幅度只剩原來的約 1/3，組合過度容易成立 | × 價 ÷ 9500（≈22） |
| second_move | 5.0 | P | 訊號根紅K漲 ≥5 點（原文） | **未登記** | 同上 | × 價 ÷ 9500（≈16） |
| low_tol | 1.0 | T | 兩根低點差 ≤1 點（原文「1 點以內」、助教「同高或差 1 點」） | —（T 類） | 價位越高，兩根低點剛好差 ≤1 點越難，訊號變少 | 以 tick 計（台指 1）；若認為是價位誤差，可另開縮放開關 |
| high_match_tol | None | P | 「高點相當」容差（原文無數值） | **未登記** | 關閉；開啟時為點數 | × 價 ÷ 9500 |
| extreme_tol | 0.0 | P | session 模式距盤中極值容差（推論） | **未登記** | 0 縮放後仍 0，目前無影響 | × 價 ÷ 9500 |
| extreme_from_prev_close | 40.0 | P | prev_close 模式距平盤門檻（推論，借 q3 的 40 點） | **未登記** | 非預設模式；未縮放時 40 點幾乎天天成立 | × 價 ÷ 10000（借 q3 的參考價） |
| stop_points | 20.0 | P | fixed 模式固定停損（助教 2020-07） | **未登記** | 20 點約 0.07%，停損過窄；原文件回測勝率僅一成多 | × 價 ÷ 12500（助教年代）；若只能一個參考價則用 9500 |
| stop_min_offset | 10.0 | P | structure 模式均線訊號停損法 | **未登記** | 同上 | 與 stop_points 同參考價 |
| stop_integer_points | 20.0 | P | 同上 | **未登記** | 同上 | 同上 |
| 其餘 | move_basis、enable_short、extreme_mode、stop_mode | N | — | — | 不需換算 | — |

問題清單：
- `first_move`／`second_move` 未登記且為 2017 年（約 9500）的點數，是本組相對失真最大的訊號門檻之一。
- `low_tol` 是「同價」容差，依 SPEC 屬 T 類不縮放，但價位上升讓「差 1 點以內」越來越難成立，訊號數會下降。
- 門檻 7／5 點也依週期：原文實例幾乎都是 1 分K，套到 3、5 分K 相對 K 線更小（原文件已觀察到週期越大品質越差）。
- 同一方法混有三個年代（2017 訊號、2020 停損、q3 的 40 點），單一參考價無法同時正確。

## sg-03 平盤 KD 買訊／空訊（`sg_03_flat_kd`）

年代：作者貼文 2025-12-08；但 5 張圖中 4 張是 2023-04～06 的圖例（報價列 1120418 約 15900、1120511 約 15520、
1120607 約 16750），只有 1 張是 2025-11-20（約 27400）。訊號本身沒有點數門檻；點數參數只有推論的停損（比照 sg-01）
→ 參考價建議 **17000**（跟推論來源 sg-01 一致）。

| 參數 | 預設值 | 類別 | 作用 | POINT_PARAMS | 3 萬點下的實際影響 | 建議換算 |
|---|---|---|---|---|---|---|
| stop_points | 20.0 | P | 停損上限（推論，比照 sg-01） | **未登記** | 大部分訊號結構極端點超過 20 點，改走均線停損法（約 10～20 點），停損過窄 | × 價 ÷ 17000（≈35） |
| stop_min_offset | 10.0 | P | 均線訊號停損法 | **未登記** | 同上 | 同上 |
| stop_integer_points | 20.0 | P | 同上 | **未登記** | 同上 | 同上 |
| 其餘 | kd_n/k_period/d_period 9/3/3、oversold 20、overbought 80、zone_bar、flat_mode | N/I | — | — | 不需換算 | — |

問題清單：只有停損三參數需登記；原文件停損筆數約九成，與停損過窄一致。

## sg-04 凹洞買訊／空訊（`sg_04_dent`）

年代：作者原文 2025-06-03；兩張定義圖為 2025-05-15（1140515，約 21750）、2025-05-20（1140520，約 21540）
→ 參考價 **21500**。20 點停損與 20 點承接都是作者在這個價位寫的。

| 參數 | 預設值 | 類別 | 作用 | POINT_PARAMS | 3 萬點下的實際影響 | 建議換算 |
|---|---|---|---|---|---|---|
| stop_points | 20.0 | P | 直接進場的固定停損（原文） | **未登記** | 相對原文偏窄約 30%（4 萬點時約一半） | × 價 ÷ 21500（≈28） |
| wait_offset | 20.0 | P | 幅度過大時於 B 低點＋20 點承接（原文） | **未登記** | 預設不觸發（large_bar_points=None）；開啟時承接價偏近 | × 價 ÷ 21500 |
| large_bar_points | None | P | 「幅度過大」門檻（原文無數值） | **未登記** | 關閉；開啟後為點數 | × 價 ÷ 21500；None 維持 None |
| max_wait_minutes | None | B | B 距 A 時間上限（推論，已用分鐘） | — | 關閉 | 已以分鐘表示 |
| 其餘 | ma_period 10、pivot_level 1、large_bar_mode、wait_bars 1 | N/B0 | — | — | 不需換算 | — |

問題清單：
- 本組中最接近現價的一個，縮放影響最小；但若 17000 套用在本法會變成放大 1.76 倍（過頭約 27%）。
- 承接停損固定在 B 低點（＝承接價外 `wait_offset`），縮放 `wait_offset` 時停損一起放大。

## sg-05 內困買訊／空訊（`sg_05_inside_box`）

年代：學員筆記 2019-08、助教說明 2018-03～2018-11；圖例約 9450～10730 → 參考價 **10000**。
（2021-04-20 那一例在約 17200，但該例被助教撤回，不作為依據。）

| 參數 | 預設值 | 類別 | 作用 | POINT_PARAMS | 3 萬點下的實際影響 | 建議換算 |
|---|---|---|---|---|---|---|
| max_first_range | 10.0 | P | 首根高低差 ≤10 點；同時限制被框K的區間 | **未登記** | **訊號幾乎消失**：原文件回測 3、5 分K 為 0 筆，1 分K 約一年半 25 筆 | × 價 ÷ 10000（≈30） |
| near_extreme_points | 10.0 | P | 首根距盤中極值 ≤10 點 | **未登記** | 同上，第二個讓訊號消失的門檻 | × 價 ÷ 10000（≈30） |
| stop_points | 20.0 | P | 固定停損（助教 2018-11，放大版不變） | **未登記** | 停損過窄 | × 價 ÷ 10000（≈60） |
| 其餘 | min_boxed_bars 3、max_boxed_bars 5、enable_short | B0/N | — | — | 不需換算 | — |

問題清單：
- `max_first_range` 與 `near_extreme_points` 是全部 sg 中最典型的「訊號消失」參數（即 SPEC 範例）。
- 助教「放大版」（首根約 15～21 點）表示原作者在 1 萬點時就已經依行情放寬，門檻本身也依波動度。
- 門檻亦依週期（原文以 1 分K 為主），3、5 分K 首根 10 點本來就少。

## sg-06 首K收紅買訊／首K收黑空訊（`sg_06_first_bar_color`）

年代：原出處是作者在「期跡2讀書會」的舊文，資料中沒有；助教 2021-11-16 給過 2013-06 部落格連結，
但同一連結 2020-03 被標為「骰子法」，是否為本法定義不確定（見 `extracted/study-group/newmethods/首K收紅收黑.md`）。
若採部落格年代，2013 年中台指約 8000（概估，資料中沒有報價可核對）；助教的停損說明與實例是 2021-05～2022-12（約 17000）。
→ 建議參考價 **17000**（目前有數值的規則都出自 2021 年的助教說明）；若日後確認 2013 為原始定義，再改約 8000。

| 參數 | 預設值 | 類別 | 作用 | POINT_PARAMS | 3 萬點下的實際影響 | 建議換算 |
|---|---|---|---|---|---|---|
| gap_points | 0.0 | P | 跳空門檻（原文未給，0＝任何跳空） | **未登記** | 0 縮放後仍 0，目前無影響；設值後為點數 | × 價 ÷ 17000 |
| stop_offset | 1.0 | T | 停損＝首K低點下 1 點（助教 2021-07-28，「成交在 51 時砍掉」） | —（T 類） | 1 點＝1 檔，語意正確 | 以 tick 計，不縮放 |
| max_stop_points | None | P | 停損距離上限（推論，預設關閉） | **未登記** | 關閉 | × 價 ÷ 17000；None 維持 None |
| stop_min_offset | 10.0 | P | 開啟 max_stop_points 時的均線訊號停損法 | **未登記** | 預設用不到 | 與 max_stop_points 同參考價 |
| stop_integer_points | 20.0 | P | 同上 | **未登記** | 預設用不到 | 同上 |
| breakout_window_minutes | None | B | breakout 模式等待時窗（已用分鐘） | — | 關閉 | 已以分鐘表示 |
| 其餘 | entry_mode、cancel_on_recover | N | — | — | 不需換算 | — |

問題清單：
- 預設下沒有會失真的點數參數（停損用首K極端點＋1 檔）；但首K幅度在 2～4 萬點下動輒數十～上百點，停損距離本身隨價位放大，屬規則特性。
- 參考價年代不確定（2013 或 2021），目前因 `gap_points=0`、`max_stop_points=None` 而不影響結果。

## sg-07 跳空百點買訊／空訊（`sg_07_gap_hundred`）

年代：助教說明與實例 2021-03～2021-06（例：「昨天收盤 17090，今天開盤 17190」），方法文件記為 2021 年約 **16000**
→ 參考價 16000（實例 16000～17200，也可取 16500）。原始定義在作者《交易訊號》，不在資料中。

| 參數 | 預設值 | 類別 | 作用 | POINT_PARAMS | 3 萬點下的實際影響 | 建議換算 |
|---|---|---|---|---|---|---|
| gap_threshold | 100.0 | P | 開盤－昨日日盤收盤 ≥100 點（助教） | **未登記** | **條件幾乎天天成立**：回測 311 日中 210 日跳空 ≥100；2021 年 100 點＝0.63%，3 萬點下等於 0.33% | × 價 ÷ 16000（≈190） |
| stop_points | 20.0 | P | 停損上限（推論）：首根另一端超過即改均線停損法 | **未登記** | 助教實例「收盤到高點約 40 點」，20 點上限使多數單改走均線停損法 | × 價 ÷ 16000（≈38） |
| stop_min_offset | 10.0 | P | 均線訊號停損法 | **未登記** | 同上 | 同上 |
| stop_integer_points | 20.0 | P | 同上 | **未登記** | 同上 | 同上 |
| window_minutes | None | B | 首根後有效時窗（推論，已用分鐘） | — | 關閉 | 已以分鐘表示 |
| 其餘 | direction、unmasked、first_only | N | — | — | 不需換算 | — |

問題清單：
- `gap_threshold` 是「明顯變寬」的代表：訊號從偶發事件變成幾乎每天。
- 「昨日日盤收盤」基準與台指期有夜盤（2017-05 起）的交易制度有關，換到 24 小時商品需重新定義跳空。

## sg-08 擴量買訊／空訊（`sg_08_volume_expansion`）

年代：助教說明 2023-10-06（附圖為小型台指 5 分K，報價約 16540）、2023-07-07 → 參考價 **16500**。

| 參數 | 預設值 | 類別 | 作用 | POINT_PARAMS | 3 萬點下的實際影響 | 建議換算 |
|---|---|---|---|---|---|---|
| base_volume | 2000.0 | V | 前一根量 ≤2000 口時用「差額」規則（助教，大台 5 分） | —（不可縮放） | 依大台 2023 年的量能水準；量能隨年代、合約規格變動，資料期間 1、3 分K 幾乎達不到 | 改為相對量（例如近 N 日同時段均量的倍數或百分位），或依商品另訂 |
| volume_increase | 2000.0 | V | 擴量K比前一根多 >2000 口 | —（不可縮放） | 同上；5 分K 一年半只有 26 筆，16 筆落在 09:00 現貨開盤那根 | 同上 |
| stop_points | 20.0 | P | 停損上限（推論，比照 sg-01） | **未登記** | 停損過窄 | × 價 ÷ 16500（≈36） |
| stop_min_offset | 10.0 | P | 均線訊號停損法 | **未登記** | 同上 | 同上 |
| stop_integer_points | 20.0 | P | 同上 | **未登記** | 同上 | 同上 |
| 其餘 | high_prev_ratio 3.0、require_color_pattern | I/N | — | — | 不需換算 | — |

問題清單：
- 口數門檻是固定量（V），且綁「大台、5 分K」：換成 1、3 分K、小台或其他市場都會失真；`base_volume` 與 `volume_increase`
  的「差額」規則與 `high_prev_ratio` 的「倍數」規則在 2000 口處切換，量能水準改變時切換點也跟著失真。
- 附圖實際是小台，助教文字說大台，量能基準本身有落差（資料中無法確認）。

---

## 建議登記（供協調者參考，本盤點不改 `scripts/`）

| 模組 | 建議參考價 | 依據 | 應登記 POINT_PARAMS 的欄位 |
|---|---|---|---|
| sg_01_rsi_blunt_quick | 17000 | 2021-04 | （已登記）stop_points、stop_min_offset、stop_integer_points |
| sg_02_counterattack_line | 9500（停損三參數若可分開：12500） | 2017-02 原文圖例 9505；停損 2020-07 | first_move、second_move、high_match_tol、extreme_tol、extreme_from_prev_close、stop_points、stop_min_offset、stop_integer_points |
| sg_03_flat_kd | 17000 | 停損為比照 sg-01 的推論；圖例 2023 約 15500～16800 | stop_points、stop_min_offset、stop_integer_points |
| sg_04_dent | 21500 | 2025-05 圖例 21540～21750 | stop_points、wait_offset、large_bar_points |
| sg_05_inside_box | 10000 | 2018～2019 圖例 9450～10730 | max_first_range、near_extreme_points、stop_points |
| sg_06_first_bar_color | 17000（若確認 2013 部落格為定義則約 8000） | 2021 助教說明 | gap_points、max_stop_points、stop_min_offset、stop_integer_points |
| sg_07_gap_hundred | 16000 | 2021 助教實例 16000～17200 | gap_threshold、stop_points、stop_min_offset、stop_integer_points |
| sg_08_volume_expansion | 16500 | 2023-10 圖例約 16540 | stop_points、stop_min_offset、stop_integer_points |

不登記：sg_02 `low_tol`、sg_06 `stop_offset`（T 類，以 tick 計）；sg_08 `base_volume`、`volume_increase`（V 類）。
實作上需要讓 `REF_PRICE` 支援「每個方法一個參考價」（現在只有書別 `"sg"` 一個鍵）。

## 本組小結（sg，68 個參數）

| 類別 | 數量 |
|---|---|
| P 價格點數 | 31 |
| T 最小跳動 | 2 |
| V 成交量 | 2 |
| B 根數（原文以時間描述，本組皆已改用分鐘） | 4 |
| B0 根數（型態本身） | 3 |
| C 時鐘時間 | 0 |
| I 指標數值／倍數 | 5 |
| N 期數／層級／模式 | 21 |
| X 其他 | 0 |

**已登記 POINT_PARAMS（3）**：sg_01 stop_points、stop_min_offset、stop_integer_points。

**漏登 POINT_PARAMS（28）**：
- sg_02：first_move、second_move、high_match_tol、extreme_tol、extreme_from_prev_close、stop_points、stop_min_offset、stop_integer_points
- sg_03：stop_points、stop_min_offset、stop_integer_points
- sg_04：stop_points、wait_offset、large_bar_points
- sg_05：max_first_range、near_extreme_points、stop_points
- sg_06：gap_points、max_stop_points、stop_min_offset、stop_integer_points
- sg_07：gap_threshold、stop_points、stop_min_offset、stop_integer_points
- sg_08：stop_points、stop_min_offset、stop_integer_points

（其中預設 None 但開啟後為點數：sg_02 high_match_tol、sg_04 large_bar_points、sg_06 max_stop_points；
預設 0、縮放不變：sg_02 extreme_tol、sg_06 gap_points。）

**V 類（2）**：sg_08 base_volume、volume_increase。

**B 類（4，皆已以分鐘實作）**：sg_01 window_minutes、sg_04 max_wait_minutes、sg_06 breakout_window_minutes、sg_07 window_minutes。

**C 類**：無。

**T 類（2）**：sg_02 low_tol、sg_06 stop_offset。

**本組最會讓規則失真的參數**：sg_05 `max_first_range`／`near_extreme_points`（訊號消失）、sg_07 `gap_threshold`（幾乎天天成立）、
sg_02 `first_move`／`second_move`（2017 年 9500 點的門檻，過度容易成立）、各方法的 20 點停損上限（停損過窄，停損率 80～90%）、
sg_08 口數門檻（固定量，綁大台 5 分K）。
