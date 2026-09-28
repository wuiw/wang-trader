# 交接說明（2026-09-28，移到運算力較強的新機器）

給接手的人與 Claude：本專案的背景、規範見 `CLAUDE.md`、`README.md`、`CODING_SPEC.md`。
這份文件記錄交接當下的進度、未完成的工作與還原步驟。回覆、文件一律繁體中文。

## 1. 還原步驟

程式碼在 git（origin main）。**不在 git 裡的資料**另外打包成
`~/finance/wang-trader-handover-20260928.tar`（舊機器上），內容：

| 路徑 | 大小 | 用途 |
|---|---|---|
| `data/` | 8 MB | 台指期日盤 1/3/5 分K（2025-03-14～2026-09-24），回測必備；原始來源是同層 `../tick-db` 的 TimescaleDB（帳密在 `../tick-db/.env`，不要讀出或印出） |
| `results/` | 11 MB | 既有回測結果（`.gitignore` 排除） |
| `extracted/study-group/`、`scripts/parse_study_group.py` | 10 MB | 讀書會整理，**含成員姓名，不可進 git**（已列入 `.gitignore`） |
| `reference/` | 4.6 GB | 書頁照片（HEIC／jpg）、讀書會原始圖片與 zip |

```bash
git clone <repo> wang-trader && cd wang-trader
tar -xf /path/to/wang-trader-handover-20260928.tar     # 解到專案根目錄，還原上表各目錄
uv sync                                                 # Python 3.13 + uv
uv run pytest -q                                        # 交接時 547 passed
```

## 2. 交接時的狀態

- 方法：q2 12、q3 13、gq 24（另 gq-01-12 只有文件）、sg 8 個模組；cz 10、gs 12 只有文件（需要個股資料，未寫程式）。
- 分類：`methods/方法分類.md`（是否用於期貨；判斷方向或找進出點）。
- 參數盤點：`methods/參數依賴盤點/README.md`（621 個參數依價位／最小跳動／成交量／週期／時鐘分類與問題清單）。
- 全體回測 `results/individual|scaled|combined` 與 `results/回測報告.md` 是 **2026-09-25 的舊版**，只含 q2/q3/gq 49 個模組，
  尚未含 sg，也尚未套用下面第 3 節的換算修改。
- 方向驗證：狀態型已完成（`methods/方向判斷驗證/狀態型.md`，結論：慢速均線類工具有小幅方向資訊，
  gq-01-11 3日/5日均線、cz-04-01 河流全排列、cz-03-01 MA10/20、q2-01 MA30 較好，效果僅數 bp）；
  事件型未完成（見第 3 節）。

## 3. 未完成的工作（交接時中斷）

### 3.1 台指期參數自動換算（規範：`methods/參數依賴盤點/IMPL_SPEC.md`）

- 甲（縮放基礎設施）**已完成**：`scripts/point_params.py` 每方法參考價 `REF_PRICE_BY_METHOD`＋`ref_price()`、
  sg_02～08 點數欄位登記、移除 8 個最小跳動欄位、補登 gq_03 `profit_target`；`run_scaled.py`／`compare_params.py` 改用 `ref_price()`。
- 乙（q2 模組）**中途停止**，已完成部分（程式＋測試，測試全過）：
  - 分鐘版參數：q2_01／q2_02 `range_minutes`（**預設 15／20，會改變 3/5 分K 結果**）、`time_stop_minutes`（預設關）；
    q2_03_01 `max_minutes_from_breakout`（**預設 60**）；q2_04_01 `htf_minutes`（**預設 15**）；多個模組 `max_wait_minutes`（預設關）；
    q2_06_02 `confirm_wait_minutes`（預設關）。
  - 寫死點數改參數：q2_06_02 `stop_min_offset`／`stop_integer_points`；q2_03_02 `time_stop_flat_points`（預設 0，行為不變）。
  - **未做**：q2_06_03 `_digit_stop()` 的 10／20 改參數；q2_05_02 相對量模式；q2 各方法文件 §12 的取捨說明。
- 丙（q3 模組）**中途停止**，已完成部分（程式＋測試）：
  - 分鐘版參數：q3_01～05、q3_08_01、q3_08_02、q3_09_01 `max_wait_minutes`（預設關）；q3_06 `stale_minutes`（預設關）；
    q3_08_01 `ma_touch_minutes`（**預設 60，會改變結果**）；q3_09_01 `min_trend_minutes`、`region_min_minutes`（預設關）；
    q3_11 `max_pullback_days`（預設關）。
  - 寫死點數改參數：q3_04 `reversal_stop_points`。
  - **未做**：q3 各方法文件 §12 的取捨說明；逐項核對 `q3.md` 其他「寫死點數」項目。
- **待登記到 point_params**（乙丙新增的點數欄位）：q2_06_02 `stop_min_offset`、`stop_integer_points`；
  q2_03_02 `time_stop_flat_points`；q3_04 `reversal_stop_points`（用各自方法的參考價）。
- 接手步驟：先 `git diff 54edcdc -- src tests` 檢視乙丙的改動是否符合 IMPL_SPEC，補完未做項目與文件 §12，登記上述欄位，
  `uv run pytest -q` 全過。

### 3.2 重跑全體回測（新機器的主要工作）

換算完成後：`uv run python scripts/run_individual.py`、`uv run python scripts/run_scaled.py`、
`uv run python scripts/run_combined.py`（含 sg_*），以**縮放版為預設**更新 `results/回測報告.md`
（原始版只作對照），並把 sg-02～08 的縮放版結果補進各 sg 文件 §4。

### 3.3 方向驗證

- 事件型（`scripts/direction_events.py`）**中途停止**：腳本已寫但尚未跑完、沒有報告。依 `methods/方向判斷驗證/SPEC.md`
  完成：q2/q3/sg 全部與 gq_01_11、gq_04_02、gq_04_03 的訊號，原始＋縮放，1/3/5 分K，報告寫到 `methods/方向判斷驗證/事件型.md`。
  注意：狀態型報告指出 SPEC 的逐根置換檢定對重疊樣本太寬鬆，改以循環平移或按交易日群集的檢定為準。
- 換算改動後，狀態型也要重跑（`scripts/direction_state.py`，約 3 分鐘）。
- 之後的第二步：把有效的方向工具／訊號當濾網，檢驗能否改善其他方法（使用者要求以回測證明）。

### 3.4 其他待辦

- README、方法總表、快速總覽中 sg-02～08 仍標「進行中」，需改為完成並補回測數字。
- sg-08 擴量：26 筆中 16 筆在 09:00 現貨開盤那根，是否排除開盤時段待使用者決定。
- cz、gs 方法需個股日K（部分需法人買賣超、當沖比率）資料才能寫程式與回測；gq 股票方法目前套在台指分K 回測，結果不代表原方法。
- S&P 500 等其他市場：使用者指示**先不管，專注台指期**。

## 4. 工作規範提醒（使用者偏好）

- 需要使用者決定時一次只問一題，用純文字選擇題（題號＋a/b/c），不要用 AskUserQuestion。
- 除非使用者要求，不要 commit；讀書會資料與成員姓名不進 git。
- 規則有爭議時用回測判定（`scripts/compare_params.py`），不為績效改書中預設；書外規則拆成獨立 sg 方法。
- 回報前親自核實（看原圖／原文），不要亂報。
