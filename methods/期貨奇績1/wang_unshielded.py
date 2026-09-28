"""wang_unshielded.afl 的 Python 逐行移植（僅供解說，不是 src/wangtrader 的正式方法模組）。

用法：
    uv run python "methods/期貨奇績1/wang_unshielded.py"

功能：
1. alma_afl()：忠實移植 AFL 的 ALMA 函式（連同它的疑點一起移植，不修正）。
2. wang_afl()：忠實移植 AFL 的 WANG 狀態機迴圈，每一行都附上對應的 AFL 原文。
3. 產生示意圖（SVG，不依賴 matplotlib）到 img/：
   - 合成資料的空單／多單訊號示意圖（資料跑過同一個 wang_afl()，確認訊號確實在該根觸發）。
   - data/tx_day_5min.parquet 真實資料挑兩天畫圖。
4. 印出全期間訊號數量統計，並把訊號清單寫到 wang_unshielded_signals.csv。
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
IMG = HERE / "img"
DATA = ROOT / "data" / "tx_day_5min.parquet"


# ---------------------------------------------------------------------------
# ALMA（AFL: function ALMA(priceField, windowSize, sigma, Offset)）
# ---------------------------------------------------------------------------
def alma_afl(price: np.ndarray, window: int, sigma: float, offset: float) -> np.ndarray:
    n = len(price)
    m = math.floor(offset * (window - 1))          # m = floor(Offset * (windowSize - 1));
    s = window / sigma                              # s = windowSize / sigma;
    w = np.zeros(window)                            # w = 0;（w[0] 保持 0）
    w_sum = 0.0                                     # wSum = 0;
    for i in range(1, window):                      # for(i = 1; i < windowSize; i++)
        w[i] = math.exp(-((i - m) * (i - m)) / (s * s))  # 分母 s*s（標準 ALMA 為 2*s*s）
        w_sum += w[i]
    for i in range(1, window):                      # for(i = 1; i < windowSize; i++)
        w[i] = w[i] / w_sum                         #     w[i] = w[i] / wSum;
    out = np.full(n, np.nan)                        # outalma = Null;
    for j in range(n):                              # for(j = 0; j < BarCount; j++)
        if j < window:                              # if(j < windowSize) outalma[j] = Null;
            continue
        al_sum = 0.0
        for i in range(1, window):                  # for(i = 1; i < windowSize; i++)
            al_sum += price[j - (window - 1 - i)] * w[i]
        out[j] = al_sum
    return out


# ---------------------------------------------------------------------------
# WANG 狀態機（AFL: _SECTION_BEGIN("WANG")）
# ---------------------------------------------------------------------------
def wang_afl(time_num: np.ndarray, O, H, L, C) -> dict:
    """回傳 short/long 訊號陣列，另附畫圖用的追蹤資料（AFL 沒有、不影響邏輯）。"""
    n = len(C)
    short = np.zeros(n, dtype=int)
    long_ = np.zeros(n, dtype=int)
    # 畫圖用追蹤：檢查訊號當下的無遮蔽線、最高K低點、最低K高點、最高/最低K位置
    tr = {k: np.full(n, np.nan) for k in
          ("line_s", "hl", "line_l", "lh", "hi_bar", "lo_bar", "is_reset")}

    hh = 0.0          # current_WANG_highest_high = 0;
    hl = 0.0          # current_WANG_highest_low = 0;
    line_s = 0.0      # WANG_unshielded_line_short = 0;
    hi_idx = 0        # current_WANG_highest_index = 0;（AFL 中從未被讀取）
    lh = 0.0          # current_WANG_lowest_high = 0;
    ll = 0.0          # current_WANG_lowest_low = 0;
    line_l = 0.0      # WANG_unshielded_line_long = 0;
    lo_idx = 0        # current_WANG_lowest_index = 0;（AFL 中從未被讀取）
    reset_flag = False  # reset_flag = False;
    hi_bar = lo_bar = -1  # 追蹤用：重設時也更新（AFL 的 *_index 在重設時不更新）

    for i in range(2, n):                                   # for(i = 2; i < BarCount; i++)
        short[i] = 0                                        # normal_WANG_entry_point_short[i] = 0;
        long_[i] = 0                                        # normal_WANG_entry_point_long[i] = 0;
        if i == 0 or time_num[i - 1] > time_num[i] or reset_flag:
            reset_flag = False                              # reset_flag = False;
            hh, hl, line_s = H[i], L[i], L[i]               # highest_high/low, line_short
            lh, ll, line_l = H[i], L[i], H[i]               # lowest_high/low, line_long
            hi_bar = lo_bar = i
            tr["is_reset"][i] = 1
        else:
            if H[i] > hh:                                   # if( High[i] > current_WANG_highest_high )
                hh, hl, line_s, hi_idx = H[i], L[i], L[i], i
                hi_bar = i
            elif H[i] == hh and L[i] > hl:                  # else if( High == hh AND Low > hl )
                hh, hl, line_s, hi_idx = H[i], L[i], L[i], i
                hi_bar = i

            if L[i] < ll:                                   # if( Low[i] < current_WANG_lowest_low )
                lh, ll, line_l, lo_idx = H[i], L[i], H[i], i
                lo_bar = i
            elif L[i] == ll and H[i] < lh:                  # else if( Low == ll AND High < lh )
                lh, ll, line_l, lo_idx = H[i], L[i], H[i], i
                lo_bar = i

            tr["line_s"][i], tr["hl"][i] = line_s, hl       # 追蹤：檢查當下的值
            if (C[i] < line_s and                           # Close[i] < WANG_unshielded_line_short AND
                    H[i] < hl and                           # High[i] < current_WANG_highest_low AND
                    C[i] < O[i] and                         # Close[i] < Open[i] AND
                    O[i] - C[i] > C[i] - L[i]):             # Open[i] - Close[i] > Close[i] - Low[i]
                short[i] = 1
                lh, ll, line_l, lo_idx = H[i], L[i], H[i], i  # 把「最低K」設成訊號K
                lo_bar = i
                reset_flag = True
            elif L[i] < line_s:                             # else if( Low[i] < line_short )
                line_s = L[i]

            tr["line_l"][i], tr["lh"][i] = line_l, lh
            if (C[i] > line_l and                           # Close[i] > WANG_unshielded_line_long AND
                    L[i] > lh and                           # Low[i] > current_WANG_lowest_high AND
                    O[i] < C[i] and                         # Open[i] < Close[i] AND
                    C[i] - O[i] > H[i] - C[i]):             # Close[i] - Open[i] > High[i] - Close[i]
                long_[i] = 1
                hh, hl, line_s, hi_idx = H[i], L[i], L[i], i  # 把「最高K」設成訊號K
                hi_bar = i
                reset_flag = True
            elif H[i] > line_l:                             # else if( High[i] > line_long )
                line_l = H[i]
        tr["hi_bar"][i], tr["lo_bar"][i] = hi_bar, lo_bar
    return {"short": short, "long": long_, **tr}


# ---------------------------------------------------------------------------
# SVG K 線圖（手寫，不依賴 matplotlib）
# ---------------------------------------------------------------------------
UP, DOWN, INK, MUTED, GRID = "#d0312d", "#1a8f4c", "#222", "#666", "#e4e4e4"
LINE_S, LINE_L, HILITE = "#1f5fbf", "#b8651a", "#fff4c2"
FONT = "Noto Sans CJK TC, PingFang TC, Microsoft JhengHei, sans-serif"


class Svg:
    def __init__(self, bars, width, height, pad=(60, 30, 60, 70), title="", xlabels=None):
        self.b = bars  # list of (O,H,L,C)
        self.W, self.H = width, height
        self.pl, self.pt, self.pr, self.pb = pad
        lo = min(x[2] for x in bars)
        hi = max(x[1] for x in bars)
        span = hi - lo
        self.lo, self.hi = lo - span * 0.12, hi + span * 0.12
        self.step = (width - self.pl - self.pr) / len(bars)
        self.items: list[str] = []
        self.title = title
        self.xlabels = xlabels or {}

    def x(self, i):
        return self.pl + self.step * (i + 0.5)

    def y(self, p):
        return self.pt + (self.hi - p) / (self.hi - self.lo) * (self.H - self.pt - self.pb)

    def add(self, s):
        self.items.append(s)

    def highlight(self, i, color=HILITE):
        self.add(f'<rect x="{self.x(i) - self.step / 2:.1f}" y="{self.pt}" width="{self.step:.1f}" '
                 f'height="{self.H - self.pt - self.pb}" fill="{color}"/>')

    def hline(self, i0, i1, p, color, dash="", width=1.5, label=None, anchor="start", dy=-4):
        x0, x1 = self.x(i0) - self.step * 0.45, self.x(i1) + self.step * 0.45
        d = f' stroke-dasharray="{dash}"' if dash else ""
        self.add(f'<line x1="{x0:.1f}" y1="{self.y(p):.1f}" x2="{x1:.1f}" y2="{self.y(p):.1f}" '
                 f'stroke="{color}" stroke-width="{width}"{d}/>')
        if label:
            tx = x0 if anchor == "start" else x1
            self.text(tx, self.y(p) + dy, label, color, anchor=anchor)

    def step_line(self, idx, vals, color, width=2):
        pts = []
        for i, v in zip(idx, vals):
            if np.isnan(v):
                continue
            pts.append((self.x(i) - self.step / 2, self.y(v)))
            pts.append((self.x(i) + self.step / 2, self.y(v)))
        if pts:
            d = " ".join(f"{a:.1f},{b:.1f}" for a, b in pts)
            self.add(f'<polyline points="{d}" fill="none" stroke="{color}" stroke-width="{width}"/>')

    def text(self, x, y, s, color=INK, size=13, anchor="start", weight="normal"):
        self.add(f'<text x="{x:.1f}" y="{y:.1f}" fill="{color}" font-size="{size}" '
                 f'text-anchor="{anchor}" font-weight="{weight}">{s}</text>')

    def marker(self, i, kind):
        o, h, l, c = self.b[i]
        cx = self.x(i)
        if kind == "short":
            y0 = self.y(h) - 8
            self.add(f'<polygon points="{cx - 7:.1f},{y0 - 12:.1f} {cx + 7:.1f},{y0 - 12:.1f} '
                     f'{cx:.1f},{y0:.1f}" fill="{DOWN}"/>')
        else:
            y0 = self.y(l) + 8
            self.add(f'<polygon points="{cx - 7:.1f},{y0 + 12:.1f} {cx + 7:.1f},{y0 + 12:.1f} '
                     f'{cx:.1f},{y0:.1f}" fill="{UP}"/>')

    def candles(self):
        out = []
        bw = max(self.step * 0.6, 2)
        for i, (o, h, l, c) in enumerate(self.b):
            col = UP if c > o else DOWN if c < o else INK
            cx = self.x(i)
            out.append(f'<line x1="{cx:.1f}" y1="{self.y(h):.1f}" x2="{cx:.1f}" y2="{self.y(l):.1f}" '
                       f'stroke="{col}" stroke-width="1.2"/>')
            top, bot = self.y(max(o, c)), self.y(min(o, c))
            fill = "#fff" if c > o else col
            out.append(f'<rect x="{cx - bw / 2:.1f}" y="{top:.1f}" width="{bw:.1f}" '
                       f'height="{max(bot - top, 1):.1f}" fill="{fill}" stroke="{col}" stroke-width="1.2"/>')
        return out

    def render(self, path: Path, grid_step=None):
        g = []
        if grid_step:
            p = math.ceil(self.lo / grid_step) * grid_step
            while p < self.hi:
                g.append(f'<line x1="{self.pl}" y1="{self.y(p):.1f}" x2="{self.W - self.pr}" '
                         f'y2="{self.y(p):.1f}" stroke="{GRID}"/>')
                g.append(f'<text x="{self.pl - 6}" y="{self.y(p) + 4:.1f}" fill="{MUTED}" font-size="11" '
                         f'text-anchor="end">{p:g}</text>')
                p += grid_step
        for i, s in self.xlabels.items():
            g.append(f'<text x="{self.x(i):.1f}" y="{self.H - self.pb + 16}" fill="{MUTED}" '
                     f'font-size="11" text-anchor="middle">{s}</text>')
        head = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.W}" height="{self.H}" '
                f'viewBox="0 0 {self.W} {self.H}" font-family="{FONT}">'
                f'<rect width="100%" height="100%" fill="#ffffff"/>'
                f'<clipPath id="plot"><rect x="{self.pl}" y="{self.pt}" width="{self.W - self.pl - self.pr}" '
                f'height="{self.H - self.pt - self.pb}"/></clipPath>')
        title = (f'<text x="{self.W / 2}" y="20" font-size="15" font-weight="bold" fill="{INK}" '
                 f'text-anchor="middle">{self.title}</text>') if self.title else ""
        # 背景標示先畫，K 線再畫，最後畫線與文字
        bg = [s for s in self.items if s.startswith("<rect")]
        fg = [s for s in self.items if not s.startswith("<rect")]
        body = head + title + "".join(g) + "".join(bg) + "".join(self.candles()) + "".join(fg) + "</svg>"
        path.write_text(body, encoding="utf-8")


# ---------------------------------------------------------------------------
# 示意圖（合成資料）
# ---------------------------------------------------------------------------
SHORT_DEMO = [  # (O, H, L, C)
    (100, 102, 98, 101),     # 0 當日第一根（重設）
    (101, 106, 100, 105),    # 1
    (105, 110, 104, 107),    # 2 最高 K，低點 104 = 無遮蔽線起點
    (107, 108, 103, 104),    # 3 低點 103 → 線下移
    (104, 106, 101, 105),    # 4 低點 101 → 線下移
    (103.5, 103.8, 101.5, 102),  # 5 收盤 102 被 K4 的低點 101 遮蔽（只差條件①）
    (102, 103, 98, 98.5),    # 6 訊號 K：四條件全成立
    (98.5, 99.5, 97, 97.5),  # 7 重設（reset_flag）
]


def mirror(bars, axis=200):
    return [(axis - o, axis - l, axis - h, axis - c) for o, h, l, c in bars]


def run_demo(bars):
    arr = np.array(bars, dtype=float)
    tn = np.array([84500 + 500 * k for k in range(len(bars))])  # 同一天（不觸發換日重設）
    tn = np.concatenate([[134000, 134500], tn])  # 前面墊兩根前一日 K，讓 i=0 成為換日第一根
    pad = np.array([[99, 100, 98, 99], [99, 100, 98, 99]], dtype=float)
    arr = np.vstack([pad, arr])
    res = wang_afl(tn, arr[:, 0], arr[:, 1], arr[:, 2], arr[:, 3])
    return {k: v[2:] for k, v in res.items()}


def demo_short():
    res = run_demo(SHORT_DEMO)
    assert res["short"].tolist() == [0, 0, 0, 0, 0, 0, 1, 0], res["short"]
    assert res["long"].sum() == 0
    b = SHORT_DEMO
    s = Svg(b, 900, 520, pad=(50, 40, 250, 60), title="空單訊號示意（合成資料，已跑過移植程式確認第 6 根觸發）",
            xlabels={i: f"K{i}" for i in range(len(b))})
    s.highlight(2, "#fde2e2")
    s.highlight(6, HILITE)
    s.hline(2, 7, 104, MUTED, dash="5,4", label="104", anchor="end", dy=-5)
    # 無遮蔽線：檢查當下的值（K3 起）
    idx = list(range(3, 7))
    s.step_line(idx, res["line_s"][3:7], LINE_S, width=2.5)
    s.text(s.x(3) - 30, s.y(99.6), "藍線＝無遮蔽線（空）", LINE_S, size=12)
    s.text(s.x(3) - 30, s.y(99.6) + 16, "逐根下移 104→103→101", LINE_S, size=12)
    s.text(s.x(2), s.y(110) - 10, "最高K", UP, anchor="middle", weight="bold")
    s.text(s.x(0), s.y(102) - 10, "每日第一根：重設", MUTED, anchor="middle", size=11)
    s.text(s.x(5) + 8, s.y(106.6), "收 102 被 K4 低點 101", MUTED, anchor="middle", size=11)
    s.text(s.x(5) + 8, s.y(106.6) + 14, "遮蔽 → 不成立", MUTED, anchor="middle", size=11)
    s.marker(6, "short")
    s.text(s.x(7), s.y(99.5) - 10, "下一根重設", MUTED, anchor="middle", size=11)
    x0 = 900 - 240
    s.text(x0, 70, "K6 訊號四條件", INK, weight="bold")
    for k, line in enumerate([
        "① 收 98.5 &lt; 無遮蔽線 101",
        "② 高 103 &lt; 最高K低點 104",
        "③ 收 98.5 &lt; 開 102（黑K）",
        "④ 實體 3.5 &gt; 下影線 0.5",
        "",
        "K5：②③④ 成立，① 不成立",
        "（收 102 ≥ 線 101）",
        "",
        "觸發後：最低K 設為 K6，",
        "reset_flag=True，K7 全部重設",
        "",
        "灰虛線＝最高K(K2)低點 104",
        "＝current_WANG_highest_low",
        "（條件②門檻，不隨後續K移動）",
    ]):
        s.text(x0, 95 + 22 * k, line, INK if k < 4 else MUTED, size=12)
    s.render(IMG / "q1-unshielded-short-demo.svg", grid_step=2)


def demo_long():
    b = mirror(SHORT_DEMO)
    res = run_demo(b)
    assert res["long"].tolist() == [0, 0, 0, 0, 0, 0, 1, 0], res["long"]
    assert res["short"].sum() == 0
    s = Svg(b, 900, 520, pad=(50, 40, 250, 60), title="多單訊號示意（合成資料，空單圖的上下鏡像）",
            xlabels={i: f"K{i}" for i in range(len(b))})
    s.highlight(2, "#dff3e6")
    s.highlight(6, HILITE)
    s.hline(2, 7, 96, MUTED, dash="5,4", label="96", anchor="end", dy=15)
    s.step_line(list(range(3, 7)), res["line_l"][3:7], LINE_L, width=2.5)
    s.text(s.x(3) - 30, s.y(100.4) - 16, "橙線＝無遮蔽線（多）", LINE_L, size=12)
    s.text(s.x(3) - 30, s.y(100.4), "逐根上移 96→97→99", LINE_L, size=12)
    s.text(s.x(2), s.y(90) + 22, "最低K", DOWN, anchor="middle", weight="bold")
    s.text(s.x(0), s.y(98) + 22, "每日第一根：重設", MUTED, anchor="middle", size=11)
    s.text(s.x(5) + 8, s.y(93.4), "收 98 被 K4 高點 99", MUTED, anchor="middle", size=11)
    s.text(s.x(5) + 8, s.y(93.4) + 14, "遮蔽 → 不成立", MUTED, anchor="middle", size=11)
    s.marker(6, "long")
    s.text(s.x(7), s.y(100.5) + 22, "下一根重設", MUTED, anchor="middle", size=11)
    x0 = 900 - 240
    s.text(x0, 70, "K6 訊號四條件", INK, weight="bold")
    for k, line in enumerate([
        "① 收 101.5 &gt; 無遮蔽線 99",
        "② 低 97 &gt; 最低K高點 96",
        "③ 收 101.5 &gt; 開 98（紅K）",
        "④ 實體 3.5 &gt; 上影線 0.5",
        "",
        "K5：②③④ 成立，① 不成立",
        "（收 98 ≤ 線 99）",
        "",
        "觸發後：最高K 設為 K6，",
        "reset_flag=True，K7 全部重設",
        "",
        "灰虛線＝最低K(K2)高點 96",
        "＝current_WANG_lowest_high",
        "（條件②門檻，不隨後續K移動）",
    ]):
        s.text(x0, 95 + 22 * k, line, INK if k < 4 else MUTED, size=12)
    s.render(IMG / "q1-unshielded-long-demo.svg", grid_step=2)


# ---------------------------------------------------------------------------
# 真實資料
# ---------------------------------------------------------------------------
def load():
    df = pd.read_parquet(DATA)
    tn = (df.index.hour * 10000 + df.index.minute * 100 + df.index.second).to_numpy()
    O, H, L, C = (df[c].to_numpy(float) for c in ("open", "high", "low", "close"))
    res = wang_afl(tn, O, H, L, C)
    price = (H + L + 2 * (O + C)) / 6                # price = ((High + Low) + 2 * (Open + Close)) / 6;
    df["alma_s"] = alma_afl(price, 15, 6, 0.85)      # ALMA_short = ALMA(price, 15, 6, 0.85);
    df["alma_l"] = alma_afl(price, 30, 6, 0.85)      # ALMA_long = ALMA(price, 30, 6, 0.85);
    for k, v in res.items():
        df[k] = v
    df["date"] = df.index.date
    return df


def plot_day(df, day, path):
    d = df[df["date"] == day]
    bars = list(zip(d.open, d.high, d.low, d.close))
    labels = {i: t.strftime("%H:%M") for i, t in enumerate(d.index) if t.minute % 30 == 15 or i == 0}
    s = Svg(bars, 1280, 620, pad=(64, 40, 20, 130),
            title=f"台指期 5 分K {day}：WANG 無遮蔽訊號（移植程式實跑）", xlabels=labels)
    n = len(d)
    for i in range(n):
        if d["short"].iloc[i] or d["long"].iloc[i]:
            s.highlight(i)
    s.step_line(range(n), d["line_s"].to_numpy(), LINE_S, width=1.6)
    s.step_line(range(n), d["line_l"].to_numpy(), LINE_L, width=1.6)
    for col, color in (("alma_s", "#6a5acd"), ("alma_l", "#999")):
        v = d[col].to_numpy()
        pts = " ".join(f"{s.x(i):.1f},{s.y(x):.1f}" for i, x in enumerate(v) if not np.isnan(x))
        s.add(f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="1.2" '
              f'stroke-dasharray="3,3" clip-path="url(#plot)"/>')
    for i in range(n):
        if d["short"].iloc[i]:
            s.marker(i, "short")
        if d["long"].iloc[i]:
            s.marker(i, "long")
        if d["is_reset"].iloc[i] == 1:
            s.add(f'<line x1="{s.x(i) - s.step / 2:.1f}" y1="{s.pt}" x2="{s.x(i) - s.step / 2:.1f}" '
                  f'y2="{s.H - s.pb}" stroke="#bbb" stroke-dasharray="2,3"/>')
    # 圖例
    ly0 = s.H - s.pb + 42
    for k, (color, name, dash) in enumerate([
        (LINE_S, "無遮蔽線（空）＝檢查當下的 WANG_unshielded_line_short", ""),
        (LINE_L, "無遮蔽線（多）＝檢查當下的 WANG_unshielded_line_long", ""),
        ("#6a5acd", "ALMA 15（只畫圖，不參與訊號）", "3,3"),
        ("#999", "ALMA 30（只畫圖，不參與訊號）", "3,3"),
        ("#bbb", "灰色直虛線＝狀態重設（每日第一根／訊號後下一根）", "2,3"),
    ]):
        dd = f' stroke-dasharray="{dash}"' if dash else ""
        lx, ly = (80 if k < 3 else 680), ly0 + 18 * (k % 3)
        s.add(f'<line x1="{lx}" y1="{ly - 4}" x2="{lx + 24}" y2="{ly - 4}" '
              f'stroke="{color}" stroke-width="2"{dd}/>')
        s.text(lx + 30, ly, name, MUTED, size=11)
    s.text(680, ly0 + 36, "▼綠＝空單訊號　▲紅＝多單訊號（黃底為訊號K）", MUTED, size=11)
    lo, hi = s.lo, s.hi
    grid = 10 ** math.floor(math.log10((hi - lo) / 5))
    grid *= 5 if (hi - lo) / grid > 25 else 2 if (hi - lo) / grid > 10 else 1
    s.render(path, grid_step=grid)


def stats(df):
    sig = df[(df["short"] == 1) | (df["long"] == 1)].copy()
    sig["side"] = np.where(sig["short"] == 1, "空", "多")
    days = df["date"].nunique()
    per_day = df.groupby("date")[["short", "long"]].sum()
    per_day["tot"] = per_day.sum(axis=1)
    day_close = df.groupby("date")["close"].last()
    sig["to_close"] = [
        (day_close[d] - c) * (1 if s == "多" else -1) for d, c, s in zip(sig["date"], sig["close"], sig["side"])
    ]
    first_day = df["date"].iloc[0]
    print(f"資料：{df.index[0]} ~ {df.index[-1]}，{len(df)} 根 5 分K，{days} 個交易日")
    print(f"空單訊號 {int(df['short'].sum())} 次，多單訊號 {int(df['long'].sum())} 次，合計 {len(sig)} 次")
    print(f"平均每日 {len(sig) / days:.2f} 次；有訊號的日子 {(per_day['tot'] > 0).sum()} 天；"
          f"單日最多 {per_day['tot'].max()} 次")
    print("每日訊號次數分布：", per_day["tot"].value_counts().sort_index().to_dict())
    print(f"第一個交易日 {first_day} 的訊號（受 line_long 初值 0 影響）：",
          sig[sig["date"] == first_day][["side", "close"]].to_dict("records"))
    both = (df["short"] & df["long"]).sum()
    print(f"同一根同時多空：{both} 次")
    hour = sig.index.strftime("%H").value_counts().sort_index().to_dict()
    print("訊號時段（小時）：", hour)
    last_bar = sig.index.strftime("%H:%M").isin(["13:40"]).sum()
    print(f"最後一根 13:40 的訊號：{last_bar} 次")
    # 參考用描述統計（不是回測：程式本身沒有出場規則）
    for side in ("多", "空"):
        x = sig[sig["side"] == side]["to_close"]
        print(f"[參考] {side}單訊號收盤價→當日收盤 順向點數：平均 {x.mean():.1f}、中位數 {x.median():.1f}、"
              f"為正比例 {(x > 0).mean():.1%}（n={len(x)}）")
    out = sig[["side", "open", "high", "low", "close", "line_s", "hl", "line_l", "lh"]]
    out.to_csv(HERE / "wang_unshielded_signals.csv", encoding="utf-8")
    return sig, per_day


def main():
    IMG.mkdir(exist_ok=True)
    demo_short()
    demo_long()
    df = load()
    sig, per_day = stats(df)
    # 挑兩天：一天有多有空的日子、一天訊號最多的日子（取最近者）
    mixed = per_day[(per_day["short"] > 0) & (per_day["long"] > 0)]
    d1 = mixed.index[-1]
    busiest = per_day[per_day["tot"] == per_day["tot"].max()].index[-1]
    d2 = busiest if busiest != d1 else per_day.sort_values("tot").index[-2]
    for d in (d1, d2):
        plot_day(df, d, IMG / f"q1-unshielded-real-{d}.svg")
        print(f"已畫 {d}：", sig[sig["date"] == d][["side", "open", "high", "low", "close"]]
              .to_string().replace("\n", "\n  "))


if __name__ == "__main__":
    main()
