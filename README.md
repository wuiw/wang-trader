# wang-trader

把王慶津《期貨奇績2》、《期貨奇績3 勝杯在握》、《股技期招》、《操作進行曲》、《股勝先選》書中的
操作方法，從書頁照片擷取、整理成結構化文件，再寫成獨立的 Python 模組，對台指期（TX）日盤資料做歷史回測。
另收錄讀書會整理出、書中沒有的「書外方法」（sg-*）。

## 目錄結構

```
reference/          書頁照片（.gitignore，不進版控，1.2GB）
extracted/          逐字擷取：pages/（每頁一份 md）、figures/（圖片/SVG）
  study-group/      讀書會原始紀錄（僅存本機，未納入版本控制，見下方「讀書會資料」）
methods/            整理後的方法規格文件（每個方法一份 .md，含機器可讀 YAML 規則）
  期貨奇績2/ 期貨奇績3/ 股技期招/ 操作進行曲/ 股勝先選/    依書分資料夾
  讀書會/            書外方法 sg-*（方法文件＋寫程式規範 SG_SPEC.md）
                     另有 README.md（索引）、操作方法總表.md、五本書進出場快速總覽.md、
                     問題彙整.md、術語表.md
src/wangtrader/
  core/              共用核心：bars（K棒欄位）、indicators（sma/rsi/kd/sar）、
                     pivots（峰谷點）、engine（Strategy/Order/run）、exits（出場函式）
  methods/           每個操作方法一個獨立模組，對應 methods/ 下的規格文件
                     （目前 q2 12、q3 13、gq 24、sg 1，共 50 個）
scripts/             build_bars.py（建資料）、run_individual.py、run_scaled.py、
                     run_combined.py、point_params.py（點數欄位與參考價位）、
                     compare_params.py（同一方法不同參數值對照）、
                     merge_study_digest.py（讀書會紀錄合併統計）
tests/               每個方法模組一份測試（pytest）
results/             回測輸出（.gitignore，不進版控）
data/                回測用 parquet 資料（.gitignore，不進版控）
tools/               輔助工具（如書頁裁切腳本）
```

## 資料流程

```
書頁照片 (reference/)
  → 逐字擷取 extracted/pages/*.md、extracted/figures/  （EXTRACTION_SPEC.md）
  → 整理成方法規格文件 methods/<書>/<id>-*.md            （ORGANIZE_SPEC.md）
  → 寫成 Python 策略模組 src/wangtrader/methods/*.py     （CODING_SPEC.md）
  → scripts/ 回測，輸出 results/
```

## 安裝與執行

```bash
uv sync                      # 安裝依賴
uv run pytest -q             # 跑全部測試

# 建立回測資料（需要 ../tick-db 的 TimescaleDB，內含 txf_ticks 表）
uv run python scripts/build_bars.py

# 回測
uv run python scripts/run_individual.py            # 每個方法單獨跑，1/3/5 分K
uv run python scripts/run_scaled.py                 # 點數門檻依價位等比例縮放版本
uv run python scripts/run_combined.py --source individual   # 多方法合併（投組/單一部位/共識確認）

# 同一方法、不同參數值的對照（原始／依價位縮放 × 1/3/5 分K，輸出 results/params/<方法>_<參數>.csv）
uv run python scripts/compare_params.py --method q3_05_break_three_high_low --param max_signal_delay=3,4
```

- `run_individual.py`／`run_scaled.py` 會自動掃描 `src/wangtrader/methods/` 下所有模組（含 `sg_*`），
  並覆寫 `results/` 下的全體結果。
- `compare_params.py` 以建構子參數注入待比較的值，不改方法模組預設值；用來以回測判定書中模糊規則或
  讀書會勘誤／補充（判定結果記在各方法文件 §12）。只想比較某個參數時用它，不必重跑全體。
- 縮放版的點數欄位與參考價位登記在 `scripts/point_params.py`（`POINT_PARAMS`、`REF_PRICE`：
  q2＝8500、q3＝10000、gq＝7000、sg＝17000）；新方法要先登記點數欄位，縮放版結果才正確。

## 回測假設

- **不計滑價、稅金、手續費**（cost = 0）。
- 僅回測**日盤** 08:45–13:45（台指期 TXFR1 連續月）。
- 以**收盤價**判斷訊號、**收盤成交**；停損則於**盤中觸價**即觸發。
- 書中點數門檻（20 點停損、40 點極端位置等）是在台指期約 8,500～10,000 點的年代訂的，
  本專案回測期間約 22,000→48,000 點，`run_scaled.py` 提供依價位縮放的對照版本。
- 預設值一律取書中（或讀書會原文）數字，不為績效調整；有爭議的規則做成參數，以 `compare_params.py` 回測後在文件記錄結論。
- 每個方法都是獨立模組、不寫死 K 線週期，見 `CODING_SPEC.md`。

## 方法類別

| 代號 | 來源 | 方法文件 | 程式模組 |
|---|---|---|---|
| q2 | 《期貨奇績2》 | `methods/期貨奇績2/`（12 個） | 已完成 |
| q3 | 《期貨奇績3 勝杯在握》 | `methods/期貨奇績3/`（13 個） | 已完成 |
| gq | 《股技期招》 | `methods/股技期招/`（24 個＋共用出場文件） | 已完成 |
| cz | 《操作進行曲》 | `methods/操作進行曲/`（9 個＋共用出場文件） | 尚未撰寫 |
| gs | 《股勝先選》 | `methods/股勝先選/`（12 個） | 尚未撰寫 |
| sg | 讀書會書外方法 | `methods/讀書會/` | sg-01 已完成；sg-02～sg-08 進行中 |

**讀書會書外方法（sg-*）**：讀書會（學員整理、助教／作者說明）提出、書中沒有的規則，獨立成方法，
不併入原書方法模組。可信度低於書中原文，文件會標明來源類型與可信度。寫程式與回測規範見
`methods/讀書會/SG_SPEC.md`（在 `CODING_SPEC.md` 之上另加的規定）。

- sg-01 RSI 鈍化簡化訊號（由 q2-06-04 衍生）：已完成模組、測試、文件。
- sg-02～sg-08（逆襲線、平盤KD、凹洞、內困、首K收紅收黑、跳空百點、擴量）：進行中。

**讀書會補充規則的回測判定**（2026-09-28，詳見各文件 §12）：

- q3-05：讀書會勘誤「最晚第 3 根」 vs. 書中讀法「第 4 根」，4 在 6 組皆較佳，維持 `max_signal_delay=4`。
- q3-10：作者補充「盤中震盪 <40 點忽略」（`min_session_range`），回測沒有一組變好，維持關閉。
- q2-06-02：助教說法「方向K須下跌黑K／上漲紅K」（`dir_bar_needs_change`），影響可忽略，維持關閉。
- q2-06-04：讀書會的鈍化簡化定義屬書外規則，拆成獨立方法 sg-01。

## 讀書會資料

- 讀書會原始紀錄 `extracted/study-group/` 與解析腳本 `scripts/parse_study_group.py` 含成員姓名，
  **只存在本機、不納入版本控制**（不要 `git add`）。
- `scripts/merge_study_digest.py` 合併其中的逐圖紀錄、去重並做台指統計，輸出也寫在 `extracted/study-group/` 下。
- 方法文件與程式一律不寫成員姓名，只寫來源類型（作者原文、助教說明、學員整理）與 post_id、日期。

## 目前狀態

- 五本書的方法規格文件皆已整理完成；q2、q3、gq 的程式模組與測試已完成，cz、gs 尚未寫程式。
- 讀書會書外方法 sg-01 已完成，sg-02～sg-08 進行中。
- 待處理的缺頁／待補拍清單見 `methods/問題彙整.md`。

## 相關文件

- `CODING_SPEC.md`：寫方法模組的規範；`methods/讀書會/SG_SPEC.md`：書外方法 sg-* 的額外規範。
- `REVIEW_SPEC.md`：設計審查規範。
- `extracted/EXTRACTION_SPEC.md`、`extracted/ORGANIZE_SPEC.md`：擷取與整理規範。
- `methods/README.md`：方法索引；`methods/問題彙整.md`：已裁決/待處理問題清單。
- `methods/操作方法總表.md`、`methods/五本書進出場快速總覽.md`：跨書比較與速查。
- `results/ANALYSIS_SPEC.md`：回測分析規範。
- `CLAUDE.md`：給 Claude/agent 在本專案工作的指引。
