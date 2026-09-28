# 交接說明（2026-09-28，移到運算力較強的新機器；同日更新進度）

給接手的人與 Claude：本專案的背景、規範見 `CLAUDE.md`、`README.md`、`CODING_SPEC.md`。
這份文件記錄交接當下的進度、未完成的工作與還原步驟。回覆、文件一律繁體中文。

## 1. 還原步驟

程式碼在 git（origin main）。**不在 git 裡的資料**另外打包成
`~/finance/wang-trader-handover-20260928.tar`（舊機器上），內容：

| 路徑 | 大小 | 用途 |
|---|---|---|
| `data/` | 8 MB | 台指期日盤 1/3/5 分K（2024-05-09～2026-09-24，575 個交易日），回測必備；可由 `../tick-db/kbars_1min.csv` 重建（見下） |
| `results/` | 11 MB | 既有回測結果（`.gitignore` 排除） |
| `extracted/study-group/`、`scripts/parse_study_group.py` | 10 MB | 讀書會整理，**含成員姓名，不可進 git**（已列入 `.gitignore`） |
| `reference/` | 4.6 GB | 書頁照片（HEIC／jpg）、讀書會原始圖片與 zip |

```bash
git clone <repo> wang-trader && cd wang-trader
tar -xf /path/to/wang-trader-handover-20260928.tar     # 解到專案根目錄，還原上表各目錄
uv sync                                                 # Python 3.13 + uv
uv run pytest -q                                        # 2026-09-28 為 547 passed
```

### 1.1 由 tick-db 重建 `data/`

來源是同層 `../tick-db/kbars_1min.csv`（TXFR1 連續月 1 分K；`../tick-db/.env` 有資料庫帳密，不要讀出或印出）。
**這個檔案的時間欄＝台北時間＋16 小時**，而且標的是該根 K 棒的收盤時刻。換算步驟：

1. 時間減 16 小時得台北時間，再減 1 分鐘，改標成該根的開盤時刻。
2. 只取日盤 08:45～13:44（並排除週六、日的零星髒資料）。
3. 結算日（每月第三個週三，外加 2026-02-23 順延結算日）13:30 收盤，刪除 13:30 以後的 K 棒。
4. 輸出 `data/tx_day_1min.csv`（欄位 `time,open,high,low,close,volume,ticks`，ticks 填 0），
   再用 `scripts/build_bars.py` 合成 1/3/5 分K parquet（剔除根數不足的交易日、標記平盤／昨高低無效日）。

```bash
uv run python scripts/kbars_to_day_csv.py    # ../tick-db/kbars_1min.csv → data/tx_day_1min.csv
uv run python scripts/build_bars.py          # → data/tx_day_{1,3,5}min.parquet
```

2026-09-28 驗證：重建出的 `tx_day_1min.csv` 與原檔逐位元組相同，三個 parquet 與原檔 `DataFrame.equals` 皆為 True
（1 分K 172,080 根、3 分K 57,360 根、5 分K 34,416 根；原始 580 日，剔除 5 日後保留 575 日）。

## 2. 目前狀態

- 方法：q2 12、q3 13、gq 24（另 gq-01-12 只有文件）、sg 8 個模組；cz 10、gs 12 只有文件（需要個股資料，未寫程式）。
- 分類：`methods/方法分類.md`（是否用於期貨；判斷方向或找進出點）。
- 參數盤點：`methods/參數依賴盤點/README.md`（621 個參數依價位／最小跳動／成交量／週期／時鐘分類與問題清單）。
- **資料時區已更正（已完成）**：原本 `data/` 把 kbars 的檔案時間直接當台北時間，實際抓到的是夜盤 16:45～21:44；
  已重建為正確的日盤 08:45～13:44，期間 2024-05-09～2026-09-24，575 個交易日。舊資料（2025-03-14 起、311／305 日）的回測數字全部作廢。
- **回測結果（已完成，取代舊的全體回測）**：以新資料重跑，整理成三份文件：
  - `methods/奇績2-3回測整理.md`：q2／q3，點數 ×2（結果 `results/individual`、`results/scaled`）。
  - `methods/股技期招回測整理.md`：gq，點數 ×2.857（`results/*_gq`）。
  - `methods/讀書會回測整理.md`：sg-01～08，點數依各方法參考價換算到 20,000 點（`results/*_sg`）。
  - 舊的 `results/回測報告.md`（2026-09-25）與 `results/combined` 已不再使用；`run_combined.py` 尚未用新資料重跑。
- 方向驗證：
  - 狀態型（`methods/方向判斷驗證/狀態型.md`）已用新資料重跑：EMA 類（河流全排列、河流 EMA55 換位、EMA30/55）
    三個週期、60 分與到收盤都通過保守檢定，最穩；MA20/50、MA30 位置、SAR、MA10/20 到收盤也通過；
    舊版第 1 名 gq-01-11 5 日／3 日均線退步（只剩 60 分通過，前半段幾乎沒效果）。效果都只有數 bp。
  - 無遮蔽原則與 PVT 通道：`methods/方向判斷驗證/無遮蔽與PVT.md`、`scripts/direction_unshielded_pvt.py`（新資料）。
  - 事件型未完成（見第 3 節）。
- 其他新增：`methods/期貨奇績1/`（無遮蔽法則 AFL 解說）、`tools/tradingview/`（無遮蔽＋PVT 通道 Pine Script）。

## 3. 未完成的工作

### 3.1 台指期參數自動換算（規範：`methods/參數依賴盤點/IMPL_SPEC.md`）

- 甲（縮放基礎設施）**已完成**：`scripts/point_params.py` 每方法參考價 `REF_PRICE_BY_METHOD`＋`ref_price()`、
  sg_02～08 點數欄位登記、移除 8 個最小跳動欄位、補登 gq_03 `profit_target`；`run_scaled.py`／`compare_params.py` 改用 `ref_price()`。
- **point_params 補登記已完成**：q2_06_02 `stop_min_offset`／`stop_integer_points`、q2_03_02 `time_stop_flat_points`、
  q3_04 `reversal_stop_points` 已登記（用各自方法的參考價）。
- 乙（q2 模組）已完成部分（程式＋測試）：
  - 分鐘版參數：q2_01／q2_02 `range_minutes`（**預設 15／20，會改變 3/5 分K 結果**）、`time_stop_minutes`（預設關）；
    q2_03_01 `max_minutes_from_breakout`（**預設 60**）；q2_04_01 `htf_minutes`（**預設 15**）；多個模組 `max_wait_minutes`（預設關）；
    q2_06_02 `confirm_wait_minutes`（預設關）。
  - 寫死點數改參數：q2_06_02 `stop_min_offset`／`stop_integer_points`；q2_03_02 `time_stop_flat_points`（預設 0，行為不變）。
  - **未做**：q2_06_03 `_digit_stop()` 的 10／20 改參數；q2_05_02 相對量模式；q2 各方法文件 §12 的取捨說明。
- 丙（q3 模組）已完成部分（程式＋測試）：
  - 分鐘版參數：q3_01～05、q3_08_01、q3_08_02、q3_09_01 `max_wait_minutes`（預設關）；q3_06 `stale_minutes`（預設關）；
    q3_08_01 `ma_touch_minutes`（**預設 60，會改變結果**）；q3_09_01 `min_trend_minutes`、`region_min_minutes`（預設關）；
    q3_11 `max_pullback_days`（預設關）。
  - 寫死點數改參數：q3_04 `reversal_stop_points`。
  - **未做**：q3 各方法文件 §12 的取捨說明；逐項核對 `q3.md` 其他「寫死點數」項目。
- 接手步驟：`git diff 54edcdc -- src tests` 檢視乙丙的改動是否符合 IMPL_SPEC，補完未做項目與文件 §12，
  `uv run pytest -q` 全過。

### 3.2 回測後續

- 全體回測已由三份整理文件取代（見第 2 節）。補完 3.1 的未做項目後，只需重跑受影響的方法；
  單一參數比較用 `scripts/compare_params.py`，不要跑 `run_individual.py`／`run_scaled.py`（會覆寫全體結果）。
- 各 sg 方法文件 §4／§5 的舊數字已加註作廢，最新結果以 `methods/讀書會回測整理.md` 為準；
  若要把新數字寫回各 sg 文件，需另外用 `compare_params.py` 以新資料重跑。
- q2-06-02、q3-05、q3-10 文件 §12 的讀書會補充判定（`results/params/`）也是舊資料時期跑的，結論是否改變尚未重驗。
- `run_combined.py`（多方法合併）尚未用新資料重跑。

### 3.3 方向驗證

- 事件型（`scripts/direction_events.py`）**中途停止**：腳本已寫但尚未跑完、沒有報告。依 `methods/方向判斷驗證/SPEC.md`
  完成：q2/q3/sg 全部與 gq_01_11、gq_04_02、gq_04_03 的訊號，原始＋縮放，1/3/5 分K，報告寫到 `methods/方向判斷驗證/事件型.md`。
  注意：狀態型報告指出 SPEC 的逐根置換檢定對重疊樣本太寬鬆，改以循環平移或按交易日群集的檢定為準。
- 狀態型已用新資料重跑（`scripts/direction_state.py`，約 3 分鐘）；3.1 的換算改動若影響方向工具，需再重跑。
- 之後的第二步：把有效的方向工具／訊號當濾網，檢驗能否改善其他方法（使用者要求以回測證明）。

### 3.4 其他待辦

- sg-08 擴量：3／5 分K 的交易多半在開盤前 20 分鐘（見 `methods/讀書會回測整理.md` §5），是否排除開盤時段待使用者決定。
- sg-07 跳空百點 `gap_threshold`（100 點）在參數盤點中「311 日中 210 日成立」是舊資料數字，待以新資料重算。
- cz、gs 方法需個股日K（部分需法人買賣超、當沖比率）資料才能寫程式與回測；gq 股票方法目前套在台指分K 回測，結果不代表原方法。
- S&P 500 等其他市場：使用者指示**先不管，專注台指期**。

## 4. 工作規範提醒（使用者偏好）

- 需要使用者決定時一次只問一題，用純文字選擇題（題號＋a/b/c），不要用 AskUserQuestion。
- 除非使用者要求，不要 commit；讀書會資料與成員姓名不進 git。
- 規則有爭議時用回測判定（`scripts/compare_params.py`），不為績效改書中預設；書外規則拆成獨立 sg 方法。
- 回報前親自核實（看原圖／原文），不要亂報。
