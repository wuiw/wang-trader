# 台指期參數自動換算：實作規範（給 agent）

背景與問題清單：`methods/參數依賴盤點/README.md`（總表）與 `q2.md`、`q3.md`、`gq.md`、`sg.md`（明細）。
**只做台指期**，其他市場（S&P 500 等）先不管。

## 目標

回測時，所有「價格點數」門檻自動依台指期當時價位換算，並成為預設；原始（書中固定點數）只作對照。
換算公式：`值 × 當時價位 ÷ 該方法訂定時的台指價位`。當時價位沿用 `scripts/run_scaled.py` 的月切段做法
（每月第一根K棒開盤，因果、不偷看未來），不改成逐日。

## 分工（每個 agent 只改自己負責的檔案）

### 甲：縮放基礎設施（只有甲可以改 `scripts/point_params.py`、`scripts/run_scaled.py`、`scripts/compare_params.py`、`scripts/run_combined.py`）
1. `REF_PRICE` 由「每本書一個」擴充為「每個方法可各自設定」：新增 `REF_PRICE_BY_METHOD: dict[模組名, float]` 與函式
   `ref_price(name) -> float`（先查方法、再依前綴 q2/q3/gq/sg 回退）；`run_scaled.py`、`compare_params.py` 改用此函式。
2. 登記 sg_02～sg_08 的點數欄位與各自參考價（依 `sg.md` 建議；同一方法內停損三欄位用同一參考價）。
3. 從 POINT_PARAMS 移除最小跳動類（台指一跳 1 點，不隨價位放大）：q2_01／q2_02 的 `trail_breach_points`、`range_breach_points`，
   q2_03_01／q2_03_02 的 `ladder_ignore_diff`，q3_04 `tolerance_points`，q3_03 `retrace_trigger`。
4. 補登 gq_03_01／gq_03_03／gq_03_04 的 `profit_target`。q3_11 `strike_step` 是台指選擇權的交易所履約價間距（實際合約規格），
   **不縮放**，在 point_params 註解說明。
5. 乙、丙完成後會回報新增的點數欄位，由協調者轉給你登記；你先完成 1～4。
6. 跑 `uv run pytest -q` 全過。不要跑 run_individual／run_scaled 全體（由協調者最後統一跑）。
7. 回報：改了什麼、各 sg 參考價與依據、移除／新增的欄位清單。

### 乙：q2 模組（只改 `src/wangtrader/methods/q2_*.py`、`tests/test_q2_*.py`、`methods/期貨奇績2/` 對應文件 §12）
### 丙：q3 模組（只改 `src/wangtrader/methods/q3_*.py`、`tests/test_q3_*.py`、`methods/期貨奇績3/` 對應文件 §12）

乙、丙的工作：
1. **寫死的點數改成參數**，預設值＝原本寫死的值（預設行為不變）：
   - q2_06_02 `_ma_signal_stop()`、q2_06_03 `_digit_stop()` 的 10／20 → 比照 q2_06_04 用 `stop_min_offset`、`stop_integer_points`。
   - q2_03_02 time_stop「無輸贏」寫死為獲利＝0 → 參數（例：`time_stop_flat_points`，預設 0，行為不變）。
   - q3_04 反手停損 `p.stop_points or 20.0` → 參數。
   - 明細檔中其他「寫死點數」項目一併處理。
2. **B 類（原文以時間描述的根數）**：新增分鐘版參數（例：`max_wait_minutes`），用K線 time 欄計算經過分鐘（參考 q3_02/q3_07 的
   `_elapsed_minutes`），失敗時退回根數。預設值取「原文的時間意義」：原文明寫分鐘或以 1 分K 敘述者，照換（10 根 1 分K＝10 分鐘）；
   原文是推論借用、沒有時間依據者，**保留根數參數為預設**、分鐘版預設 None，並在文件 §12 註明。每一項都要在文件 §12 寫清楚取捨與依據。
3. **V 類**（只有 q2_05_02 `min_volume` 1500 口）：乙新增可選的相對量模式（例：`min_volume_mode="absolute"|"relative"`，
   relative＝近 N 個交易日同一 bar_no 平均量的倍數，只用過去資料），預設維持 absolute（照書）；並在文件 §12 說明為何無法從書中
   直接換算、相對量倍數的建議值與依據（可統計資料中 1500 口在當年代與現在的相對位置，若無當年資料就寫明）。
4. 新增的點數參數**不要自己改 point_params**，在回報中列出「需登記的點數欄位」。
5. 每個改動都要有測試；`uv run pytest -q` 全過。預設行為變動（B 類改分鐘造成結果不同）要在回報中逐項列出。
6. 不要跑 run_individual／run_scaled 全體；可以用 `scripts/compare_params.py` 比較單一參數。

## 共通

全部繁體中文；不寫讀書會成員姓名；不 commit；不派子 agent；不改 core/（發現需要改 core 請回報）。
