# wang-trader

把王慶津《期貨奇績2》、《期貨奇績3 勝杯在握》及新書《股技期招》書中的台指期（TX）操作方法，
從書頁照片擷取、整理成結構化文件，再寫成獨立的 Python 模組，對台指期日盤資料做歷史回測。

## 目錄結構

```
reference/          書頁照片（.gitignore，不進版控，1.2GB）
extracted/          逐字擷取：pages/（每頁一份 md）、figures/（圖片/SVG）
methods/            整理後的方法規格文件（每個方法一份 .md，含機器可讀 YAML 規則）
  期貨奇績2/ 期貨奇績3/    依書分資料夾，另有 README.md（索引）、問題彙整.md、術語表.md
src/wangtrader/
  core/              共用核心：bars（K棒欄位）、indicators（sma/rsi/kd/sar）、
                     pivots（峰谷點）、engine（Strategy/Order/run）、exits（出場函式）
  methods/           每個操作方法一個獨立模組（24 個），對應 methods/ 下的規格文件
scripts/             build_bars.py（建資料）、run_individual.py、run_scaled.py、
                     run_combined.py、point_params.py
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
```

## 回測假設

- **不計滑價、稅金、手續費**（cost = 0）。
- 僅回測**日盤** 08:45–13:45（台指期 TXFR1 連續月）。
- 以**收盤價**判斷訊號、**收盤成交**；停損則於**盤中觸價**即觸發。
- 書中點數門檻（20 點停損、40 點極端位置等）是在台指期約 8,500～10,000 點的年代訂的，
  本專案回測期間約 22,000→48,000 點，`run_scaled.py` 提供依價位縮放的對照版本。
- 每個方法都是獨立模組、不寫死 K 線週期，見 `CODING_SPEC.md`。

## 目前狀態

- 《期貨奇績2》《期貨奇績3》的方法規格文件已整理完成（24 個方法），對應程式模組與測試皆已完成。
- 新書《股技期招》及各書補拍頁的擷取、整理仍進行中。
- 待處理的缺頁／待補拍清單見 `methods/問題彙整.md`。

## 相關文件

- `CODING_SPEC.md`：寫方法模組的規範。
- `REVIEW_SPEC.md`：設計審查規範。
- `extracted/EXTRACTION_SPEC.md`、`extracted/ORGANIZE_SPEC.md`：擷取與整理規範。
- `methods/README.md`：方法索引；`methods/問題彙整.md`：已裁決/待處理問題清單。
- `results/ANALYSIS_SPEC.md`：回測分析規範。
- `CLAUDE.md`：給 Claude/agent 在本專案工作的指引。
