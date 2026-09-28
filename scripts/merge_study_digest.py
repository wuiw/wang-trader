"""合併 extracted/study-group/digest/b*.md 第 3 節的 15 欄紀錄表，輸出 CSV 與統計。"""
import csv, re, sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "extracted/study-group"
COLS = ["日期", "市場", "盤別", "週期", "方法", "方向", "進場時間", "進場價", "停損價",
        "出場時間", "出場價", "出場原因", "損益點數", "是否符合規則", "post_id"]

# (方法 id, 關鍵字 regex)；依序比對，一列可命中多個
METHOD_PATTERNS = [
    ("q2-02 SAR", r"SAR"),
    ("q2-03-02 PVT+RSI", r"PVT\s*[+＋與]\s*RSI|PVT結合RSI|q2-03-02"),
    ("q2-03-01 PVT通道", r"PVT(?!\s*[+＋與]\s*RSI)|q2-03-01"),
    ("q2-01 均線", r"均線(買訊|空訊|策略|引出|N)|穿越均線|q2-01"),
    ("q2-04-01 跨週期KD", r"跨週期|15分KD|q2-04-01"),
    ("q2-04-02 四柱", r"四柱|q2-04-02"),
    ("q2-05-01 紅三兵/黑三兵", r"紅三兵|黑三兵|q2-05-01"),
    ("q2-05-02 極端大量/擴量", r"大量|暴量|擴量|q2-05-02"),
    ("q2-06-01 假面背離", r"假面|假性|q2-06-01"),
    ("q2-06-02 KD背離", r"KD\s*(單根)?背離|q2-06-02"),
    ("q2-06-03 RSI背離", r"RSI\s*背離|q2-06-03"),
    ("q2-06-04 RSI鈍化/N字", r"鈍化|RSI\s*N|RSI\s*倒N|q2-06-04"),
    ("q3-01 頂雙黑/底雙紅", r"雙黑|雙紅|q3-01"),
    ("q3-02 V字", r"V字|倒V|q3-02"),
    ("q3-03 母子", r"(頂|底)母子|q3-03"),
    ("q3-04 以牙還牙", r"以牙還牙|q3-04"),
    ("q3-05 過三高/破三低", r"過三高|破三低|q3-05"),
    ("q3-06 連五", r"連五|五黑|五紅|q3-06"),
    ("q3-07 開盤戰法", r"開盤戰法|q3-07"),
    ("q3-08 均線順向/豬陽", r"豬陽|均線順向|q3-08"),
    ("q3-09 蜻蜓點水", r"蜻蜓|q3-09"),
    ("q3-10 RSI差值", r"差值|正差|反差|q3-10"),
    ("q3-11 選擇權", r"選擇權|q3-11"),
    ("gq DMI/威廉", r"DMI|威廉"),
    ("新:內困", r"內困"),
    ("新:逆襲線", r"逆襲"),
    ("新:天雷/地火", r"天雷|地火"),
    ("新:功敗垂成", r"功敗垂成"),
    ("新:三二", r"三二|32(買|空)"),
    ("新:首K收紅/收黑", r"首K收"),
    ("新:跳空百點", r"百點"),
    ("新:平行撐壓", r"平行"),
    ("新:凹洞/平盤KD/量的切入", r"凹洞|平盤KD|量的切入"),
]

NUM = re.compile(r"[-+−－]?\s*\d+(?:\.\d+)?")


# digest 中已逐圖完成、沿用的部分：批次 -> (子節標題關鍵字 或 None=全部, 日期前綴白名單 或 None)
DIGEST_KEEP = {
    "b0": (None, None),
    "b1": ("3.1", ("2018-05", "2018-06", "2018-07")),
    "b2": ("3.0", None),
    "b4": ("3.1", None),
    "b5": (None, None),
}


def _table_rows(text):
    sub = ""
    for line in text.splitlines():
        if line.startswith("#"):
            sub = line
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 16:  # b1 §3.1 多一欄（出場原因後的備註），併入出場原因
            extra = cells.pop(12)
            if extra not in ("—", "-", ""):
                cells[11] = extra if cells[11] in ("—", "-", "") else f"{cells[11]}；{extra}"
        if len(cells) != 15 or not re.match(r"\d{4}-\d{2}", cells[0]):
            continue
        yield sub, dict(zip(COLS, cells))


def rows():
    for f in sorted((ROOT / "digest").glob("b*.md")):
        b = f.stem.split("-")[0]
        if b not in DIGEST_KEEP:
            continue
        need_sub, dates = DIGEST_KEEP[b]
        text = f.read_text(encoding="utf-8")
        sec3 = text[text.index("## 3"):text.index("## 4")] if "## 4" in text else text[text.index("## 3"):]
        for sub, r in _table_rows(sec3):
            if need_sub and need_sub not in sub:
                continue
            if dates and not r["日期"].startswith(dates):
                continue
            yield b, r
    for f in sorted((ROOT / "records").glob("*.md")):
        for _, r in _table_rows(f.read_text(encoding="utf-8")):
            yield f.stem, r


def pnl(r):
    """回傳 (點數或 None, 類型)：類型 = 已實現 / 浮動 / 無。"""
    s = r["損益點數"]
    if s.startswith(("不確定", "—", "-（", "不適用")):
        return None, "無"
    m = NUM.search(s.replace("≈", "").replace("約", ""))
    if not m or s in ("—", "-") or "不確定" in s and not m:
        return None, "無"
    v = float(m.group().replace("−", "-").replace("－", "-").replace(" ", ""))
    if abs(v) >= 1500:  # 誤抓到價位
        return None, "無"
    if s.startswith("負") and v > 0:
        v = -v
    text = s + r["出場價"] + r["出場原因"]
    if "未成交" in text or "未進場" in text:
        return None, "無"
    if any(k in text for k in ("未出場", "未平倉", "浮動", "截至", "未表明", "帳面")):
        return v, "浮動"
    if re.search(r"停損|停利|平倉|出場|反手|達標|收盤", r["出場原因"]):
        return v, "已實現"
    return v, "浮動"


def is_tx(r):
    m = r["市場"]
    return bool(re.search(r"台指|小台|FITX|FIMTX|TXF|MTX", m)) and "加權" not in m


def dedup_key(r, ms):
    price = re.sub(r"[^0-9]", "", r["進場價"])[:5]
    if len(price) >= 4:  # 有進場價：同日同向同價視為同一筆（g2/g3 交叉轉貼）
        return (r["日期"][:10], r["方向"][:1], price, r["進場時間"][:7])
    return (r["日期"][:10], "；".join(ms), r["方向"][:1], r["post_id"])


def main():
    out = ROOT / "records_merged.csv"
    raw = list(rows())
    seen, data = set(), []
    for b, r in raw:
        ms = [mid for mid, pat in METHOD_PATTERNS if re.search(pat, r["方法"])] or ["其他/未分類"]
        k = dedup_key(r, ms)
        if k in seen:
            continue
        seen.add(k)
        data.append((b, r, ms))
    print(f"原始列數 {len(raw)}；去重後 {len(data)}；來源檔數 {len(set(b for b, _, _ in data))}")
    mk = Counter("台指/小台" if is_tx(r) else "其他商品" for _, r, _ in data)
    print(f"市場：{dict(mk)}")
    with out.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["來源"] + COLS + ["方法分類", "損益值", "損益類型", "台指"])
        stat = defaultdict(Counter)
        for b, r, ms in data:
            v, kind = pnl(r)
            w.writerow([b] + [r[c] for c in COLS] + ["；".join(ms), "" if v is None else v, kind,
                                                      "是" if is_tx(r) else "否"])
            if not is_tx(r):
                continue
            for mid in ms:
                st = stat[mid]
                st["筆數"] += 1
                if v is not None:
                    st[kind + "筆"] += 1
                    st[kind + "點"] += v
                    st[kind + ("勝" if v > 0 else "敗" if v < 0 else "平")] += 1
    tx = [(b, r) for b, r, _ in data if is_tx(r)]
    fill = {c: sum(1 for _, r in tx if r[c] not in ("—", "-", "", "不確定")) / len(tx) for c in COLS}
    print("台指列 欄位有值比例：" + "、".join(f"{c}{v:.0%}" for c, v in fill.items()))
    print("（以下僅台指/小台）方法｜列數｜已實現筆(勝/平/敗,點)｜浮動筆(正/平/負,點)")
    for mid, st in sorted(stat.items(), key=lambda x: -x[1]["筆數"]):
        print(f"{mid}｜{st['筆數']}｜{st['已實現筆']}({st['已實現勝']}/{st['已實現平']}/{st['已實現敗']},{st['已實現點']:.0f})"
              f"｜{st['浮動筆']}({st['浮動勝']}/{st['浮動平']}/{st['浮動敗']},{st['浮動點']:.0f})")
    kinds = Counter(pnl(r)[1] for _, r in tx)
    real = [pnl(r)[0] for _, r in tx if pnl(r)[1] == "已實現"]
    print(f"台指 損益類型：{dict(kinds)}；已實現 勝{sum(v > 0 for v in real)} 平{sum(v == 0 for v in real)} "
          f"敗{sum(v < 0 for v in real)} 合計{sum(real):.0f}點")

if __name__ == "__main__":
    main()
