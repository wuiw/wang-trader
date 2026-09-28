# CLAUDE.md

本專案將王慶津期貨書籍的操作方法擷取、整理並寫成 Python 模組回測台指期。給在此專案工作的
Claude / agent 的指引：

## 溝通

- 回覆、文件、commit message 一律使用**繁體中文**。
- 需要使用者裁決時，**一次只問一題**，用純文字選擇題（題號＋a/b/c），等回答後再問下一題。

## 程式規範

- 每個操作方法是**獨立模組**（`src/wangtrader/methods/`），不得 import 其他方法模組；
  不得寫死 K 線週期常數；不得使用未來資料或未確認的峰谷點。
  詳見 `CODING_SPEC.md`；設計審查依 `REVIEW_SPEC.md`。
- 讀書會書外方法（sg-*，`methods/讀書會/`、`src/wangtrader/methods/sg_*.py`）另依
  `methods/讀書會/SG_SPEC.md`；書外規則不要併入原書方法模組，要拆成獨立 sg 方法。
- 回測**不計滑價、稅金、手續費**（cost = 0），不要為了績效調整書中規則的預設值。
- 有爭議的規則（讀書會勘誤、書中模糊處）做成參數，用
  `uv run python scripts/compare_params.py --method <模組名> --param <參數>=<值1>,<值2>` 回測判定，
  結論寫進該方法文件 §12（輸出在 `results/params/`）。只比較單一參數時不要跑
  `run_individual.py`／`run_scaled.py`（會覆寫全體結果）。新方法的點數欄位要登記到
  `scripts/point_params.py`，縮放版才正確。

## 擷取與整理（書頁照片相關工作）

- 依 `extracted/EXTRACTION_SPEC.md`（逐字擷取）與 `extracted/ORGANIZE_SPEC.md`（整理成方法文件）進行。
- **空白頁背面透印的文字不是內容**，不要當成該頁文字抄錄。
- 缺頁就標明缺頁，**不要腦補**缺頁內容或臆測書中規則。
- **回報前必須親自用 Read 工具看過照片核實**內容，不可只憑檔名、頁碼推測或憑印象回報頁碼/頁數。

## 其他規則

- 不要讀出、印出 `../tick-db/.env` 或任何憑證/密碼內容。
- 讀書會原始資料 `extracted/study-group/` 與 `scripts/parse_study_group.py` 含成員姓名，
  **不進 git**（不要 `git add`）；文件、程式、commit message 都不要寫成員姓名，只寫來源類型
  （作者原文、助教說明、學員整理）與 post_id、日期。
- 除非使用者明確要求，**不要 commit**，也不要再派子 agent。
- 測試指令：`uv run pytest -q`（改完任何方法模組都要跑過）。
