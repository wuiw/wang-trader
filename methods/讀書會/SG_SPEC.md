# 讀書會書外方法（sg-*）寫程式與回測規範（給 agent）

目標：把讀書會整理出、可程式化的書外新方法，寫成獨立模組 `sg_0N_*.py`，寫方法文件並回測。
先完整讀 `CODING_SPEC.md`（通用規範，全部適用），以及範本 `src/wangtrader/methods/sg_01_rsi_blunt_quick.py`、
`tests/test_sg_01.py`、`methods/讀書會/sg-01-RSI鈍化簡化訊號.md`。

## 規格來源

- `extracted/study-group/newmethods/<方法>.md`（逐篇整理：定義、進場、停損、出場、爭議、圖例、實例）
- `extracted/study-group/讀書會總整理.md` 第 1 節
- 原貼文：`extracted/study-group/md/<社團>-<YYYY-MM>.md`（用 post_id 搜尋），附圖在 `reference/study-group/`。
  **定義的關鍵數值要親自用 Read 開原圖或原文核對**，不要只照整理檔。
- 文件與程式都不要寫讀書會成員的姓名（寫「作者原文」「助教說明」「學員整理」等來源類型即可）。

## 規則取捨

1. 原文（或作者／助教明確說法）有寫的規則：照寫，預設開啟，註解附 post_id 與日期。
2. 原文沒寫、但為了能回測必須補的（常見：停損、出場）：用參數做，註解標「推論」。預設值：
   - 停損：訊號結構的極端點（例如首根低點）；距離超過 20 點改用 q2-01 均線訊號停損法
     （多＝收盤−(10＋個位數)、空＝收盤＋(20−個位數)、個位數 0 為 20 點），公式寫在自己模組內（照 sg-01）。
     原文若已規定停損（例如內困、凹洞的固定 20 點），用原文。
   - 出場：原文沒寫就不設停利，持有到停損、反向訊號或收盤（同 sg-01）。
3. 說法有爭議或數值未定的：做成參數，預設取「最有根據」的說法，另一種說法用參數可切換，文件寫清楚。
4. 不要自己發明原文沒有的濾網。時間窗一律用分鐘（依 K 線 time 欄計算），不要寫死根數或週期。

## 產出

- `src/wangtrader/methods/sg_0N_<英文slug>.py`（METHOD_ID = "sg-0N"），不 import 其他方法模組。
- `tests/test_sg_0N.py`：多空各一個成立測試＋每條過濾至少一個測試＋時間窗／遮蔽等邊界。`uv run pytest -q tests/test_sg_0N.py` 全過，
  最後也跑一次全部 `uv run pytest -q`。
- `methods/讀書會/sg-0N-<中文名>.md`：照 sg-01 文件格式（frontmatter、原文、訊號定義、停損／出場（標推論）、回測、特性）。
- 回測：`uv run python scripts/compare_params.py --method <模組名> --param <參數>=<值1>,<值2>`，
  挑一個「有爭議或推論」的參數比較兩個值（例如時間窗、門檻、方向說法）。**只看「原始」列**：縮放版要等協調者在
  `scripts/point_params.py` 登記點數欄位後才正確，你不要改 `scripts/point_params.py`、`scripts/run_scaled.py`，
  也不要跑 `run_individual.py`／`run_scaled.py`（會覆寫全體結果）。
  另外用與 sg-01 文件相同的方式，檢查出場原因分布、年度、多空、前 10 大獲利占比，寫進文件「特性」。

## 不要做

不要改 core/、其他方法模組與測試、methods/ 裡其他文件、scripts/。不要 commit。不要派子 agent。

## 回報（繁體中文）

1. 產出檔案。
2. 實作的規則（每條標原文／推論），以及無法實作或需人工決定的地方。
3. **需要登記到 point_params 的點數欄位清單**（Params 中哪些欄位是點數、應依價位縮放）。
4. 原始版回測表（1/3/5 分K：筆數、勝率、淨點數、PF、最大回撤）與特性摘要。
5. 測試通過數。
