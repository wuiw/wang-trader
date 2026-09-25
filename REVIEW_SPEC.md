# 設計審查規範（給審查 agent）

目標：審查整個專案的設計與實作，找出**會讓結果錯誤或誤導**的問題，確認後**直接修正**。

## 專案結構

- 書頁擷取：`extracted/pages/`（逐字原文）、`extracted/figures/`
- 方法規格：`methods/<書>/<id>-*.md`（第 3–7、11 節為規則；`methods/問題彙整.md` 為已裁決事項）
- 程式：`src/wangtrader/core/`（bars、indicators、pivots、engine、exits）、`src/wangtrader/methods/`（24 個獨立模組）
- 測試：`tests/`（`uv run pytest -q`）
- 資料：`scripts/build_bars.py` → `data/tx_day_{1,3,5}min.parquet`（台指期日盤，來源 `../tick-db`）
- 回測：`scripts/run_individual.py`（單獨）、`scripts/run_scaled.py` + `scripts/point_params.py`（點數門檻按價位縮放）、
  `scripts/run_combined.py`（合併：投組疊加、單一部位先到先做、共識確認；前半段挑方法、後半段評估）
- 既有規範：`CODING_SPEC.md`（每個方法獨立模組、不綁週期、不偷看未來）、`results/ANALYSIS_SPEC.md`
- 使用者要求：不計滑價、稅金、手續費；方法彼此獨立；不區隔週期。

## 審查重點（依你負責的範圍）

1. **正確性**：與規格文件／原文不符的邏輯；多空不對稱；邊界條件（開盤第一根、跨日、session 最後一根）。
2. **偷看未來（look-ahead）**：用到第 i 根之後的資料、未確認的峰谷點、用整日資料算盤中值。
3. **成交假設**：進出場價格是否可實現（例如用收盤判斷卻以更好的價格成交、同根先後順序）。
4. **績效計算與統計**：指標計算、樣本內外切分、合併邏輯是否有偏誤或錯誤。
5. **資料**：時區換算、session 切分、缺漏日處理、K 棒合成對齊。
6. **設計層面**：違反 CODING_SPEC 的地方（方法間 import、寫死週期）、重複或矛盾的實作。

## 修正規則

- 確認是問題才修；每個修正都要有理由（引用規格頁碼或程式行號）。
- 只改你負責範圍內的檔案；發現範圍外的問題就回報，不要改。
- 修 bug 要加回歸測試；`uv run pytest -q` 必須全過。
- 不要為了績效調參數，不要改書中規則的預設值（除非預設值本身與規格不符）。
- 不要 commit，不要再派子 agent。

## 回報（繁體中文）

1. 發現的問題清單：嚴重度（高／中／低）、檔案:行號、問題、是否已修、修法。
2. 未修但需要注意的問題（範圍外或需要使用者決定）。
3. 測試結果。
