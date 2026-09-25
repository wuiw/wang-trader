# 程式規範（給寫方法模組的 agent）

目標：把 `methods/` 下每個已確認的操作方法寫成**獨立的 Python 模組**，**不區隔操作週期**。

## 環境

- 專案：`/home/wuiw/finance/wang-trader`，uv 管理。跑測試：`uv run pytest -q tests/test_<你的模組>.py`
- 共用核心（**只能用，不要改**；發現核心 bug 請在回報中說明）：
  - `src/wangtrader/core/bars.py`：`prepare()` 產生的欄位：`session, bar_no, prev_close(平盤), prev_high, prev_low, sess_open, sess_high(當下盤中最高), sess_low, time`；`is_extreme_position()` 等
  - `src/wangtrader/core/indicators.py`：`sma, rsi, kd, sar`
  - `src/wangtrader/core/pivots.py`：`find_pivots(df, level)`、`last_confirmed()`（峰谷點要等右側 level 根走完才確認，**只能用已確認的**）
  - `src/wangtrader/core/engine.py`：`Strategy`、`Context`、`Order.enter / enter_limit / exit`、`Side`、`run()`；成交規則見檔頭說明
  - `src/wangtrader/core/exits.py`：`ladder_exit, ma_exit, sar_exit, retrace_exit`
- **範本：`src/wangtrader/methods/q3_01_double_red_black.py` 與 `tests/test_q3_01.py`，先完整讀過再動手，照同樣結構寫。**

## 每個方法

1. 規格來源：`methods/<書>/<id>-*.md`，特別是 §3 訊號定義、§4 進場、§5 停損、§6 出場、§7 過濾、§11 YAML、§12 待確認事項。
   需要時可查 `extracted/pages/` 原文。
2. 檔案：`src/wangtrader/methods/<id 用底線>_<英文 slug>.py`，例：`q3_02_v_reversal.py`、`q2_06_03_rsi_divergence.py`。
3. **獨立**：不得 import 其他方法模組；只 import `wangtrader.core` 與標準庫/pandas/numpy。
   需要核心沒有的工具（例如 PVT 階梯、N 型結構、層級2 變形峰谷），寫在自己的模組裡（私有函式）。
4. **不區隔週期**：程式不得出現任何 K 線週期常數（1 分、5 分……）。所有門檻用「點數」或「根數」參數表示，
   預設值取書中數字。書中以「時鐘時間」表示的規則（如 12:30 後不做、收盤前 30 分鐘）做成可選參數，預設 `None`（關閉）。
   需要大週期的方法（q2-04-01 跨週期 KD）：用參數 `htf_bars: int`（幾根小週期 K 線合成一根大週期），在模組內
   因果地合成，**只能用已完成的大週期 K 線**。
5. 結構：
   - 模組 docstring：方法名、書/章/頁、規格文件路徑、條列訊號/進場/停損/出場/過濾規則並附頁碼（照範本）。
   - `METHOD_ID = "q3-02"`
   - `@dataclass class Params`：所有門檻與開關，註解附頁碼。
   - `Strategy` 子類別：`prepare()` 算指標欄位、`on_bar()` 產生訂單；可拆出 `detect()` 方便測試。
   - `intraday`：當沖方法 True；波段方法（q3-11）False。
6. **推論規則**：規格文件標「（推論）」的規則（例如只寫了多方、空方靠鏡像），用參數開關控制並在註解標明「推論」。
   鏡像的空方/多方規則預設開啟；其他推測性規則預設關閉。原文沒有的規則不要自己發明。
7. **不偷看未來**：第 i 根只能用 0..i 的資料；峰谷點只用已確認的。
8. 註解與 docstring 用繁體中文，簡潔，對齊範本的密度。

## 測試

`tests/test_<模組名>.py`，用 `tests/helpers.py` 的 `make_bars(rows, prev_day=...)` 手工組 K 線：
- 每個方向（多/空）至少一個「訊號成立」測試，檢查 side、reason、進場價、停損價。
- §7 每條過濾規則至少一個「應該被過濾」的測試。
- 有特殊出場/反手/補進場規則的，至少各一個測試。
- 全部通過才算完成。

## 不要做

- 不要修改 `core/`、其他人的模組或測試、`methods/` 的文件。不要 commit。不要再派子 agent。

## 回報

簡短列出：產出檔案、實作了哪些規則、**無法實作或需人工決定的地方**（規則模糊、數值缺失、原文矛盾），
以及測試結果（通過數）。
