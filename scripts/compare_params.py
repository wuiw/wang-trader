"""同一方法、不同參數值的回測對照（用來以回測判定讀書會勘誤／書中模糊規則）。

對每個參數值各跑兩種版本：
  - 原始：書中固定點數（同 run_individual.py）
  - 縮放：點數門檻依當月價位等比例放大（同 run_scaled.py）
不修改方法模組預設值；參數以建構子 kwargs 注入。cost 預設 0。

用法：
  uv run python scripts/compare_params.py --method q3_05_break_three_high_low \
      --param max_signal_delay=3,4 [--tf 1,3,5] [--out results/params/q3_05_max_signal_delay.csv]
"""

from __future__ import annotations

import argparse
import ast
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_individual as RI  # noqa: E402
import run_scaled as RS  # noqa: E402


def _variant(base: type, key: str, value):
    """回傳一個把 key 預設改成 value 的子類別（仍可被 scaled_kwargs 的其他欄位覆寫）。"""

    class V(base):  # type: ignore[misc, valid-type]
        def __init__(self, **kw):
            kw.setdefault(key, value)
            super().__init__(**kw)

    V.__name__ = V.__qualname__ = f"{base.__name__}_{key}_{value}"
    return V


def _job(args):
    mode, name, key, value, tf = args
    base = RI.strategy_classes()[name]
    patched = {name: _variant(base, key, value)}
    mod = RI if mode == "原始" else RS
    mod.strategy_classes = lambda: patched  # 子行程內替換，不影響其他工作
    if mode == "原始":
        row, _ = RI.one((name, tf, 0.0))
    else:
        row, _ = RS.one((name, tf, 0.0, RS.DEFAULT_WARMUP_DAYS, None))
    return {"mode": mode, key: value, **row}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--method", required=True)
    ap.add_argument("--param", required=True, help="key=v1,v2,...")
    ap.add_argument("--tf", default="1,3,5")
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    key, vals = a.param.split("=", 1)
    values = [ast.literal_eval(v) for v in vals.split(",")]
    jobs = [(mode, a.method, key, v, int(tf)) for mode in ("原始", "縮放") for v in values for tf in a.tf.split(",")]
    with ProcessPoolExecutor() as ex:
        rows = list(ex.map(_job, jobs))
    df = pd.DataFrame(rows)
    cols = ["mode", key, "tf", "trades", "win_rate", "net_points", "avg_net", "profit_factor", "max_drawdown"]
    df = df[[c for c in cols if c in df.columns] + (["error"] if "error" in df.columns else [])]
    out = Path(a.out) if a.out else ROOT / "results" / "params" / f"{a.method}_{key}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    with pd.option_context("display.width", 200, "display.max_columns", 20):
        print(df.sort_values(["mode", "tf", key]).to_string(index=False, float_format=lambda x: f"{x:.3f}"))
    print(f"→ {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
