# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""Page loop and preview: analyse_one, iter_pages, preview_page."""
from __future__ import annotations

import html
import re
from pathlib import Path

import cv2
import numpy as np
import pymupdf

from .bars import edit_barlines
from .config import D_BARNUM, D_EDGE, D_NOISE, D_NOMUSIC, NOISE_WARN_FRAC, OWN_HEADER_BASE
from .console import _fail, _ok, _progress, _progress_end, _skip, _warn
from .model import PageResult, Staff
from .ownership import analyse_page


# =============================================================================
# Score analysis (page by page)
# =============================================================================
def parse_pages(spec: str | None, count: int) -> list[int]:
    """parse_pages 'A-B' | 'A' | None -> zero-based page list."""
    if not spec:
        return list(range(count))
    m = re.fullmatch(r"\s*(\d+)\s*(?:-\s*(\d+))?\s*", spec)
    if not m:
        raise ValueError(f"bad page range: {spec}")
    a = int(m.group(1))
    b = int(m.group(2) or a)
    if not (1 <= a <= b <= count):
        raise ValueError(f"page range {spec} outside 1-{count}")
    return list(range(a - 1, b))


def analyse_one(doc: "pymupdf.Document", pno: int, dpi: int, nsys: int, ocr: bool = True,
                bar_edits: dict | None = None) -> tuple[PageResult, list[dict]]:
    """analyse_one -> (PageResult, system records) of one page.

    nsys: the number of systems on the pages before (only a base for the
    global system index; nothing reads it across pages, so a worker that
    analyses a page alone passes 0 (detect with workers and build do). The
    index is only a key inside one page (barlines, repeats, system window,
    owner code OWN_HEADER_BASE + index); the records and ids use the place of
    the system on its page (p3.s2). bar_edits ({system id: [edit]},
    bar_edits_by_system): the operator's corrections are applied to the
    barlines of those systems (build)."""
    res = analyse_page(doc[pno], pno, dpi, nsys, ocr=ocr)
    for j, grp in enumerate(res.systems):
        eds = (bar_edits or {}).get(f"p{pno + 1}.s{j + 1}")
        if not eds:
            continue
        sy = grp[0].system
        bl, rp, mn, nt = edit_barlines(eds, res.barlines.get(sy, []),
                                       min(s.x0 for s in grp),
                                       res.repeats.get(sy), res.mensur.get(sy))
        res.barlines[sy] = bl
        if sy in res.repeats:
            res.repeats[sy] = [tuple(r) for r in rp]
        if sy in res.mensur:
            res.mensur[sy] = mn
        for t in nt:
            _warn(f"bars:  {t}")
    recs = []
    for j, grp in enumerate(res.systems):
        recs.append({"id": f"p{pno + 1}.s{j + 1}", "page": pno,
                     "staves": [s.idx for s in grp],
                     "labels": [s.label for s in grp],
                     "clefs": [s.clef for s in grp],
                     "braces": [s.brace for s in grp],
                     "steps": [list(s.steps) if s.steps else None for s in grp],
                     "nbars": len(res.barlines.get(grp[0].system, [])),
                     "anchors": [(sum(1 for b in res.barlines.get(grp[0].system, []) if b < x), n, st)
                                 for x, n, st in res.anchors.get(grp[0].system, [])],
                     "restart": grp[0].system in res.restart,
                     "widths": bar_widths(res, grp),
                     "geom": {"h": int(res.shape[0]),
                              "staves": [[int(st.x0), int(st.top), int(st.bottom)]
                                         for st in grp]},
                     "repeats": [list(r) for r in res.repeats.get(grp[0].system, [])]})
    return res, recs


def iter_pages(pdf: Path, dpi: int, pages: list[int], ocr: bool = True,
               bar_edits: dict | None = None):
    """iter_pages -> yields (PageResult, system records of that page).

    One page at a time, in this process: the caller uses the owner image,
    then drops it. Callers: `pieces` (200 dpi, no OCR) and `detect` with one
    job. `detect` with more jobs and `build` use analyse_one in workers."""
    doc = pymupdf.open(pdf)
    nsys = 0
    for k, pno in enumerate(pages):
        _progress(f"page {pno + 1} ({k + 1}/{len(pages)}): analysing")
        res, recs = analyse_one(doc, pno, dpi, nsys, ocr=ocr, bar_edits=bar_edits)
        nsys += len(res.systems)
        _progress_end()
        yield res, recs


def bar_widths(res: PageResult, grp: list[Staff]) -> list[float]:
    """bar_widths -> width of each bar of a system in staff spaces, from the
    system start (clef, key and time signature included in bar 1) to each
    barline. One value per counted bar."""
    edges = [min(s.x0 for s in grp)] + res.barlines.get(grp[0].system, [])
    return [round((b - a) / res.sp, 2) for a, b in zip(edges, edges[1:])]


def check_page(res: PageResult) -> None:
    """Gate and summary line for one page (prints results)."""
    pid = f"page {res.page + 1}"
    for g in res.gate:
        _fail(f"gate: {pid}  ({g})")
    if not res.music:
        if not res.gate:
            _skip(f"{pid}: no music")
        return
    noise = res.discard.get(D_NOISE, 0)
    if res.ink_px and noise > NOISE_WARN_FRAC * res.ink_px:
        _warn(f"noise: {pid}  ({noise} px removed, "
              f"{100.0 * noise / res.ink_px:.1f}% of ink)")
    disc = sum(v for k, v in res.discard.items() if k != D_NOMUSIC)
    _ok(f"{pid}:  {len(res.staves)} staves  {len(res.systems)} systems  "
        f"sp={res.sp:.1f}px  skew={res.skew:+.1f}°  dewarp={res.dewarp:.0f}px  "
        f"discard={disc}px  review={len(res.review)}")


# =============================================================================
# Preview
# =============================================================================
PALETTE = [(31, 119, 180), (214, 39, 40), (44, 160, 44), (148, 103, 189),
           (255, 127, 14), (23, 190, 207), (140, 86, 75), (227, 119, 194)]


def preview_page(res: PageResult, recs: list[dict], pdir: Path) -> str:
    """preview_page -> HTML section; writes page-NN.png. Colours: one per
    staff, brown = system header, grey = discard (lighter = noise/edge),
    red box = review, red band = safety gate failure."""
    h, w = res.shape
    img = np.full((h, w, 3), 255, np.uint8)
    o = res.owner
    for i in range(len(res.staves)):
        img[o == i] = PALETTE[i % len(PALETTE)][::-1]
    img[o >= OWN_HEADER_BASE] = (60, 90, 120)
    img[(o <= -2) & (o >= D_BARNUM)] = (190, 190, 190)
    img[(o == D_NOISE) | (o == D_EDGE)] = (225, 225, 225)
    for (x, y, cw, ch, why) in res.review:
        cv2.rectangle(img, (x - 6, y - 6), (x + cw + 6, y + ch + 6), (0, 0, 255), 4)
    for (x, y, cw, ch) in res.gate_boxes:
        ov = img.copy()
        cv2.rectangle(ov, (x, y), (x + cw, y + ch), (0, 0, 255), -1)
        img = cv2.addWeighted(ov, 0.25, img, 0.75, 0)
    for st in res.staves:
        tag = f"{st.idx + 1} {st.clef}"
        cv2.putText(img, tag, (max(0, st.x0 - int(4 * res.sp)), int(st.lines[3])),
                    cv2.FONT_HERSHEY_SIMPLEX, res.sp / 14, (0, 0, 0),
                    max(1, int(res.sp / 10)))
    f = PROOF_H / h
    small = cv2.resize(img, (int(w * f), 1400), interpolation=cv2.INTER_AREA)
    name = f"page-{res.page + 1:02d}.png"
    cv2.imwrite(str(pdir / name), small)
    desc = ", ".join(f"{r['id']}: {len(r['staves'])} staves" for r in recs) or "no music"
    rows = "".join(
        f"<li class=g>gate: {html.escape(g)}</li>" for g in res.gate) + "".join(
        f"<li>{html.escape(why)} at x={x}, y={y}</li>" for (x, y, _, _, why) in res.review)
    lbl = "".join(f"<li class=l>staff {s.idx + 1}: {html.escape(s.label)}</li>"
                  for s in res.staves if s.label)
    title = f" — {html.escape(res.title)}" if res.title else ""
    return (f"<section><h2>Page {res.page + 1}{title}</h2><p>{desc}</p>"
            f"<ul>{rows}{lbl}</ul><img src='{name}'></section>")


def write_preview_index(pdir: Path, items: list[str], pdfname: str) -> Path:
    idx = pdir / "index.html"
    idx.write_text(
        "<!doctype html><meta charset='utf-8'><title>partitor preview</title>"
        "<style>body{font:14px sans-serif;margin:16px}img{max-width:100%;"
        "border:1px solid #ccc}section{margin-bottom:32px}"
        "li{color:#c00}li.l{color:#555}li.g{font-weight:bold}</style>"
        f"<h1>{html.escape(pdfname)}</h1><p>Colour = staff number on page "
        "(with clef). Brown = system header (copied to every part). Grey = "
        "discarded (light grey = noise / page edge). Red box = check by eye. "
        "Red band = safety gate failure.</p>" + "".join(items), encoding="utf-8")
    return idx


PROOF_H = 1400        # preview page height (px); a constant, nothing sets it
