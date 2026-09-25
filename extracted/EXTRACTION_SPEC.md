# Extraction spec (for extraction agents)

Source: photos of Taiwanese futures-trading books (期貨奇績 2, 期貨奇績 3 勝杯在握, maybe others),
mostly two-page spreads, Traditional Chinese, about day-trading 台指期 (TX) with K 線 / RSI etc.

- Photos (already rotated upright, 2400x1800): `reference/book-jpg/<IMG>.jpg`
- Originals (full res 5712x4284): `reference/book/<IMG>.HEIC`
- Python with PIL + HEIC: `tools/.venv/bin/python`
- Crop / zoom helper (reads full-res HEIC, coordinates in the 2400x1800 JPG pixel space):
  `tools/.venv/bin/python tools/crop.py IMG_8340 x0 y0 x1 y1 out.jpg [--rot 180]`
  **Note:** the Read tool shows the JPG downscaled to 2000x1500 — multiply what you see by 1.2
  to get JPG coordinates. Always Read the crop afterwards to verify it is correct and complete.
  Use crops into the scratchpad to zoom in when text is small/blurry — accuracy matters.
- If a JPG is upside-down/sideways, handle it with `--rot` and note it.

## Output per photo: `extracted/pages/<IMG>.md`

```markdown
---
source: IMG_8340
book: 期貨奇績3 勝杯在握        # from running header; "unknown" if none visible
pages: [18, 19]                 # printed page numbers, left page first
chapter: 第一章 頂底雙紅黑       # from running header
---

## p.18

<full verbatim transcription in Traditional Chinese, paragraphs preserved; keep **bold** where the
book uses bold. Do not summarize, do not translate. Mark illegible chars as [?].>

![圖 1-5](../figures/期貨奇績3-fig-1-5.jpg)

**圖 1-5** <caption verbatim>

> 圖說（figure notes）: what the figure shows — chart type, instrument/date header text,
> every callout/label text verbatim, labelled points (A, B, 1, 2 ...), highlighted bars, lines,
> stop-loss marks, and how they relate to the body text. This must let an LLM that cannot see
> the image understand the figure.

## p.19
...
```

- Transcribe in reading order (left page, then right page). Skip text bleeding through from the
  back side of the paper (faint mirrored text) and the other book lying under the photo.
- If a page is only partially visible or cut off, transcribe what's visible and note `[cut off]`.

## Figures: `extracted/figures/`

File name: `<book-short>-fig-<chapter>-<n>.<ext>` e.g. `期貨奇績3-fig-1-5.jpg`
(book-short = `期貨奇績2`, `期貨奇績3`, …). If a figure has no number, use `<book-short>-p<page>-<k>`.

- **Real chart screenshots** (candlestick charts with price axes, RSI panes, etc.): crop them with
  `tools/crop.py` tightly around the figure (include its frame, exclude caption & body text).
- **Schematic / conceptual diagrams** (hand-drawn-style curves, idealised candle patterns, flow
  diagrams, tables drawn as images), or any figure too distorted/blurred to be useful as a
  photo crop: **redraw as clean SVG** (`.svg`) that faithfully reproduces the structure, labels
  (Traditional Chinese text), colours (red = 紅K/up, black = 黑K/down), and annotations.
  Use `viewBox`, `font-family="sans-serif"`, white background rect. Also keep a crop of the
  original as `<name>.orig.jpg` for reference.
- Tables printed as text → transcribe as Markdown tables in the page file, not images.

## When done

Report back briefly: list of photos processed, book/page ranges covered, figures created
(count, which were SVG), and any problems (unreadable, missing pages, odd orientation).
