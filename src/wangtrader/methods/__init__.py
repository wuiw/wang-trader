"""每個操作方法一個獨立模組。模組之間互不 import，只依賴 `wangtrader.core`。

每個模組提供：
  METHOD_ID          對應 methods/ 下的規格文件 id
  Params             dataclass，所有門檻（點數／根數），不綁定 K 線週期
  <Strategy 子類別>   可丟給 `wangtrader.core.run(strategy, df)` 執行
"""
