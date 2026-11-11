# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""Paper, packing, page plan and part drawing."""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pymupdf

from . import config
from .clef import ACC_GLYPH, CLEF_BOTTOM
from .config import AMB_SP, PAPER, SYSTEM_GAP_FACTOR, composer_surname
from .console import _warn
from .lines import line_labels, put_smallcaps
from .model import Strip
from .reflow import find_prefixes, reflow, reflow_caps
from .turnplan import Boundary, plan_turns
from .strips import (
    REH_PAD, ambitus_width, anchor, bar_mark, bar_x, pitches, reh_boxes, rest_boxes,
)
from .typography import (
    CROP_MARK, CUT_DASHES, FILL_COST, MIN_LAST_LINES, PAGE_COST, REPAGE_FILL, REST_TURN_MIN,
    SHORT_LAST, TURN_BAD, TURN_HARD, TURN_MOVE, assemble_text, cut_words, flap_guides, put_text, sheet_guides,
    text_len,
)


# =============================================================================
# Packing and rendering
# =============================================================================
MARGIN = 42.5        # pt (15 mm), default margin (tests)
TITLE_BAND = 85.0    # pt, page 1
RUN_HEAD = 22.0      # pt, later pages


GROUP_REFLOW_PAGES = 1.5  # group re-flow, pages=auto: page budget / pages without re-flow
SYSTEM_GAP_LAST = 2.0     # the same on a last page with room to spare


def mm2pt(v: float) -> float:
    return float(v) * 72.0 / 25.4


def page_box(opts: dict, pi: int, duplex: bool) -> tuple[float, float, float, float]:
    """page_box -> (left, right, top, bottom) margins in pt for page index pi
    (0 = page 1, a recto). Double-sided: the spine margin (left on a recto,
    right on a verso) gains `gutter`/2 and the outer margin loses it, so
    the text width, and with it the staff size, is the same on every page.
    With `binding` (0.8.4) the outer margin stays `margin_side` and the spine
    margin is `binding` mm wider: room for a punch or a comb binding."""
    side = mm2pt(opts.get("margin_side", 15.0))
    bind = mm2pt(opts.get("binding") or 0.0) if duplex else 0.0
    g = mm2pt(opts.get("gutter", 0.0)) / 2 if duplex else 0.0
    inner, outer = (side + bind, side) if bind else (side + g, side - g)
    left, right = (inner, outer) if pi % 2 == 0 else (outer, inner)
    return left, right, mm2pt(opts.get("margin_top", 15.0)), mm2pt(opts.get("margin_bottom", 15.0))


def usable_width(opts: dict, pw: float) -> float:
    """usable_width -> text width (pt) of a page of width pw. The staff is
    sized as for a bound part: `binding` is taken unless duplex is off, so a
    part of 1 or 2 pages (single-sided, no spine) keeps its staff size."""
    bind = 0.0 if opts.get("duplex", "auto") == "off" else mm2pt(opts.get("binding") or 0.0)
    return pw - 2 * mm2pt(opts.get("margin_side", 15.0)) - bind


def is_duplex(opts: dict, npages: int) -> bool:
    d = opts.get("duplex", "auto")
    return d == "on" or (d == "auto" and npages > 2)


def pack(strips: list[Strip], dpi: int, opts: dict
         ) -> list[list[tuple[Strip, float]]]:
    """pack -> pages of (strip, y of the strip image top, pt within the
    content area). Strips follow at constant pitch (see pitches); a strip
    that does not fit goes to the next page. Free space stays at the
    bottom of the page. A last page with fewer than MIN_LAST_LINES lines
    takes lines from the pages before it (largest lines-per-page limit
    that gives it enough), with the same page count."""
    pages = _pack(strips, dpi, opts, None)
    n, total = len(pages), len(strips)
    need = min(MIN_LAST_LINES, total // n) if n > 1 else 0
    if n > 1 and len(pages[-1]) < need:
        for cap in range(max(len(p) for p in pages) - 1, -(-total // n) - 1, -1):
            alt = _pack(strips, dpi, opts, cap)
            if len(alt) == n and len(alt[-1]) >= need:
                return alt
    return pages


def _pack(strips: list[Strip], dpi: int, opts: dict, cap: int | None
          ) -> list[list[tuple[Strip, float]]]:
    """Greedy packing; cap = most lines per page (None: no limit)."""
    _, ph = PAPER[opts["paper"]]
    k = 72.0 / dpi * (opts.get("scale") or 1.0)
    pit = pitches(strips, opts)
    _, _, mt, mb = page_box(opts, 0, False)
    avail1 = ph - mt - mb - (RUN_HEAD if opts.get("_no_band") else TITLE_BAND)
    availn = ph - mt - mb - RUN_HEAD
    pages: list[list[tuple[Strip, float]]] = [[]]
    y_top = 0.0
    for i, s in enumerate(strips):
        avail = avail1 if len(pages) == 1 else availn
        if pages[-1]:
            y_top += pit[i - 1] * k
            y_img = y_top - s.staff_top * k
            if y_img + s.img.shape[0] * k > avail or (cap and len(pages[-1]) >= cap):
                pages.append([])
        if not pages[-1]:
            y_img = 0.0
            y_top = s.staff_top * k
        pages[-1].append((s, y_img))
    return pages


def turns(npages: int) -> int:
    """Page turns of a part printed as facing pages (1-2: 0, 3-4: 1)."""
    return max(0, (npages - 1) // 2)


def choose_layout(strips: list[Strip], dpi: int, opts: dict
                  ) -> tuple[float, float, int]:
    """choose_layout -> (scale, gap, pages). DESIGN.md §5.2:
    fewest page turns first (a smaller staff and 2 pages is better than a
    larger staff and 3 pages), then the largest staff (down to
    `min_staff_mm`), then the widest gap from `gap` down to `gap_min`.
    `page_count` (when set) is a hard target instead of the turn rule."""
    smax = fit_scale(strips, dpi, opts)
    h_px = 4.0 * strips[0].sp       # one staff (a part may have two staves)

    def mm(sc: float) -> float:
        return h_px * 72.0 / dpi * sc * 25.4 / 72.0

    scales = [smax]
    while mm(scales[-1] - 0.02) >= opts["min_staff_mm"] and scales[-1] - 0.02 > 0.3:
        scales.append(scales[-1] - 0.02)
    gaps = list(np.arange(opts["gap"], opts["gap_min"] - 1e-9, -0.25)) or [opts["gap"]]

    def npages(sc: float, g: float) -> int:
        # content pages (a title page adds none: the first turn is before
        # the music, DESIGN.md §5.4)
        return len(layout_pages(strips, dpi, {**opts, "scale": sc, "gap": float(g)})[0])

    target = opts.get("page_count")
    if target:
        for sc in scales:
            for g in gaps:
                n = npages(sc, g)
                if n <= target:
                    return sc, float(g), n
        sc, g = scales[-1], gaps[-1]
        return sc, float(g), npages(sc, g)
    if opts["paper"] in config.SIZE_FIRST:
        # ledger (0.3.0-dev.36; operator request 2026-10-27): the staff is as large as
        # the page width and max_staff_mm allow; pages and turns follow
        sc = scales[0]
        best = turns(npages(sc, gaps[-1]))
    else:
        best = min(turns(npages(sc, gaps[-1])) for sc in scales)
        sc = next(sc for sc in scales if turns(npages(sc, gaps[-1])) == best)
    for g in gaps:
        n = npages(sc, g)
        if turns(n) == best:
            return sc, float(g), n
    return sc, float(gaps[-1]), npages(sc, gaps[-1])


def choose_reflow(strips: list[Strip], dpi: int, opts: dict, pre: list | None = None,
                  floor_scale: float | None = None
                  ) -> tuple[float, float, int, list[Strip]]:
    """choose_reflow -> (scale, gap, content pages, lines) for a re-flowed
    part. Same order as choose_layout (fewest page turns, then the largest
    staff, then the widest gap), with the staff up to `max_staff_mm`: the
    line length follows the staff size, never shorter than needed.
    pre: find_prefixes(strips) when the caller has it. floor_scale: the
    smallest scale tried, when lower than `min_staff_mm` gives (a page
    budget below the size of the source lines must still find a layout)."""
    pw, _ = PAPER[opts["paper"]]
    usable = usable_width(opts, pw)
    sp = strips[0].sp
    pre = find_prefixes(strips) if pre is None else pre
    cap_px = reflow_caps(strips, pre)
    s_hi = min(opts["max_staff_mm"] * dpi / (4 * sp * 25.4),
               usable * dpi / 72.0 / max(cap_px, 1.0))
    floor = opts["min_staff_mm"] * dpi / (4 * sp * 25.4)
    if floor_scale is not None:
        floor = min(floor, floor_scale)
    scales = [s_hi]
    while scales[-1] * 0.97 >= floor and len(scales) < 60:
        scales.append(scales[-1] * 0.97)
    gaps = list(np.arange(opts["gap"], opts["gap_min"] - 1e-9, -0.25)) or [opts["gap"]]
    cache: dict[float, list[Strip]] = {}

    def lines(sc: float) -> list[Strip]:
        if sc not in cache:
            k = 72.0 / dpi * sc
            cache[sc] = reflow(strips, 0.98 * usable / k, pre)
        return cache[sc]

    def npages(sc: float, g: float) -> int:
        return len(layout_pages(lines(sc), dpi, {**opts, "scale": sc, "gap": float(g)})[0])

    target = opts.get("page_count")
    if target:                        # the largest staff that fits N pages
        for sc in scales:
            for g in gaps:
                if npages(sc, g) <= target:
                    return sc, float(g), npages(sc, g), lines(sc)
        sc, g = scales[-1], gaps[-1]
        return sc, float(g), npages(sc, g), lines(sc)
    # re-flow is chosen for size: the largest staff (max_staff_mm, or what
    # the widest uncut piece allows); the page count follows. Among gaps,
    # the widest with the fewest page turns at that size.
    sc = scales[0]
    best = min(turns(npages(sc, g)) for g in gaps)
    for g in gaps:
        if turns(npages(sc, g)) == best:
            return sc, float(g), npages(sc, g), lines(sc)
    return sc, float(gaps[-1]), npages(sc, gaps[-1]), lines(sc)


def fit_scale(strips: list[Strip], dpi: int, opts: dict) -> float:
    """Largest scale <= opts.scale whose widest strip fits the page width."""
    pw, _ = PAPER[opts["paper"]]
    usable = usable_width(opts, pw)
    widest = max(s.img.shape[1] for s in strips) * 72.0 / dpi
    # ceiling: `scale` when set, else the size that gives max_staff_mm
    cap = opts.get("scale") or (opts.get("max_staff_mm", 8.0) * dpi
                                / (4 * strips[0].sp * 25.4))
    return min(cap, usable / widest)


LARGE = {"letter": ((792.0, 1224.0), "11x17"),      # Letter -> 11x17 (ledger)
         "a4": ((841.89, 1190.55), "A3")}           # A4 -> A3 (exact sqrt 2)


def large_path(src: Path, paper: str) -> Path:
    """large_path -> the file of the large-print copy of src: <stem>-11x17.pdf (Letter),
    <stem>-A3.pdf (A4)."""
    return src.with_name(f"{src.stem}-{LARGE[paper][1]}.pdf")


def large_copies(fn: Path, opts: dict) -> dict:
    """large_copies -> the large-print files of the part just rendered (LAST_RENDER), for its
    `built` record: {"large": file} and, when the part has fold-outs, {"large_flaps": file}: the
    flap file of the tape route at the large size, one flap per sheet (0.8.36; the large copy of
    the part file has no flaps). {} when `large` is off or the paper has no larger sheet."""
    if opts.get("large") != "on" or opts["paper"] not in LARGE:
        return {}
    cl = opts.get("cutline", "dotted")
    out = {"large": large_copy(fn, opts["paper"], cl).name}
    if LAST_RENDER.get("flaps"):
        out["large_flaps"] = large_copy(fn.with_name(LAST_RENDER["flaps"]), opts["paper"], cl).name
    return out


def large_copy(src: Path, paper: str, cutline: str = "dotted") -> Path:
    """large_copy -> path of the large-print copy of a part: each page
    scaled to the full width of the larger sheet (Letter -> 11x17, x1.294;
    A4 -> A3, x1.414), at the top of the sheet. Where the scaled page is
    shorter than the sheet (11x17: 14.24 in of 17 in), cutline shows the cut:
    dotted = a dotted line across the sheet (scissors, knife); marks = short
    marks at both side edges (paper cutter); off = nothing."""
    (sw, sh), _ = LARGE[paper]
    pw, ph = PAPER[paper]
    f = sw / pw
    out = large_path(src, paper)
    doc = pymupdf.open(src)
    big = pymupdf.open()
    for pno in range(len(doc)):
        page = big.new_page(width=sw, height=sh)
        page.show_pdf_page(pymupdf.Rect(0, 0, sw, ph * f), doc, pno)
        cut = ph * f
        if sh - cut > 1.0:
            if cutline == "dotted":
                page.draw_line((0, cut), (sw, cut), color=(0.5, 0.5, 0.5), width=0.6,
                               dashes=CUT_DASHES)
            elif cutline == "marks":
                for a, b in ((CROP_MARK[0], CROP_MARK[1]), (sw - CROP_MARK[1], sw - CROP_MARK[0])):
                    page.draw_line((a, cut), (b, cut), color=(0, 0, 0), width=0.5)
    big.save(out, garbage=3, deflate=True)
    return out


LAST_RENDER: dict = {}      # content pages and title page of the last render_part


def edge_rest(strips: list[Strip], j: int) -> int:
    """edge_rest -> the longest multi-bar rest (bars) next to a page turn before line j: a
    rest line on either side, a merged rest that ends line j-1 or one that starts line j."""
    return max([strips[t].rest_src[2].bars for t in (j - 1, j) if strips[t].rest_src is not None]
               + [strips[j - 1].rest_out, strips[j].rest_in])


def rest_turn(strips: list[Strip], j: int) -> bool:
    """A page may turn before line j and the player rests: a multi-bar rest
    (REST_TURN_MIN bars or more) is a whole line, or the end of the last line of
    the page, or the start of the first line of the next. A movement start or a
    rehearsal letter does not count: the player may be playing there."""
    return edge_rest(strips, j) >= REST_TURN_MIN


def line_bars(s: Strip) -> tuple[int, int | None] | None:
    """line_bars -> (first bar, last bar) of a line; the last is None when
    unknown. None when the line has no bar numbers."""
    if s.rest_src is not None:
        run = s.rest_src[2]
        if run.first is None:
            return None
        return run.first, run.first + run.bars - 1
    if s.bar_nums:
        return int(s.bar_nums[0]), int(s.bar_nums[-1])
    if s.bar_no is not None:
        return int(s.bar_no), None
    return None


def line_spans(strips: list[Strip]) -> list[tuple[int, int | None] | None]:
    """line_spans -> (first bar, last bar) of every line. A line cut by re-flow has no list of bar
    numbers, so its last bar is the one before the first bar of the next line (not across a
    movement start, where the numbers begin again)."""
    spans = [line_bars(s) for s in strips]
    for i, sp in enumerate(spans[:-1]):
        nxt = spans[i + 1]
        if sp and sp[1] is None and nxt and nxt[0] > sp[0] and not strips[i + 1].movement:
            spans[i] = (sp[0], nxt[0] - 1)
    return spans


def prefix_notes(strips: list[Strip], pre) -> list[str]:
    """prefix_notes -> text lines for the build (0.8.32): the lines that took the clef and key of a
    neighbour by the structure match (pre.borrowed) and the music lines that stay whole for lack of
    one (they hold the staff re-flow can reach), each with its bar numbers."""
    spans = line_spans(strips)

    def where(i: int) -> str:
        sp = spans[i]
        return f"line {i + 1}" if not sp or sp[1] is None else f"bar {sp[0]}" if sp[0] == sp[1] else f"bars {sp[0]}-{sp[1]}"
    out = [f"prefix borrowed: {where(i)} take the clef and key of {where(k)} "
           "(the scan differs, the key signature agrees)" for i, k in sorted(getattr(pre, "borrowed", {}).items())]
    return out + [f"no clef and key to copy: {where(i)} stay one piece (re-flow cannot make the staff larger than this line allows)"
                  for i, s_ in enumerate(strips)
                  if pre[i] is None and s_.rest_src is None and s_.ends_at_bar and len(s_.bars_x) >= 2]


def lines_sig(strips: list[Strip]) -> str:
    """lines_sig -> a short hash of the bar span of every line. The pins that `pages --move` saves
    (page ends kept for a move) hold for these lines only; when a build makes other lines, the
    pins are dropped (0.8.39)."""
    return hashlib.sha1(repr(line_spans(strips)).encode()).hexdigest()[:12]


def page_limits(strips: list[Strip], opts: dict) -> tuple[list[int], list[int], list[str]]:
    """page_limits -> (breaks, pins, warnings): the lines before which a page must end, for the
    manual breaks (`breaks`, warnings for those that end no line) and for the pins of
    `pages --move` (`_pins`: valid for these lines, set by the caller; a pin that ends no line
    is left out without a warning)."""
    breaks, warn = break_lines(strips, opts.get("breaks") or [])
    pins, _ = break_lines(strips, opts.get("_pins") or [])
    return breaks, sorted(set(pins) - set(breaks)), warn


def break_lines(strips: list[Strip], bars: list[int]) -> tuple[list[int], list[str]]:
    """break_lines -> (j list, warnings): a page break before line j for each
    bar N in `bars` ("break after bar N"). Lines are fixed, so N must be the
    last bar of a line; else a warning names the line ends near N."""
    out, warn = [], []
    spans = line_spans(strips)
    for n in sorted({int(b) for b in bars or []}):
        hit = next((i for i, sp in enumerate(spans) if sp and sp[1] == n), None)
        if hit is not None:
            if hit + 1 < len(strips):
                out.append(hit + 1)
            else:
                warn.append(f"break after bar {n}: the last line of the part (ignored)")
            continue
        ends = [sp[1] for sp in spans if sp and sp[1] is not None]
        near = sorted(ends, key=lambda e: (abs(e - n), e))[:4]
        inside = any(sp and sp[1] is not None and sp[0] <= n < sp[1] for sp in spans)
        warn.append(f"break after bar {n}: " + (
            "bar is inside a line (lines are not cut)" if inside else "no line ends at that bar")
            + (f"; line ends near it: {', '.join(str(e) for e in sorted(near))}" if near else ""))
    return sorted(set(out)), warn


def good_turn(strips: list[Strip], j: int) -> bool:
    """A page may turn before line j: a movement starts there, the line
    opens with a rehearsal letter (a new section, after a repeat), or a
    multi-bar rest stands on either side (the player turns while resting)."""
    s = strips[j]
    if s.movement or s.rest_src is not None or strips[j - 1].rest_src is not None \
       or strips[j - 1].rest_out or s.rest_in:
        return True
    return any(mx <= s.staff_x0 + 3 * s.sp for mx, _ in s.marks)


def page_lines(strips: list[Strip], pit: list[float], k: float, i: int, j: int,
               free: float | None = None) -> list[tuple[Strip, float]]:
    """page_lines -> (strip, y) pairs of lines i..j-1 on one page, y relative to
    the first line. free: the spare height of a last page (pt); a group score
    spreads it between its systems, up to SYSTEM_GAP_LAST."""
    extra = 0.0
    if free is not None and j - i > 1 and len(strips[i].staff_labels) > 1:
        s0 = strips[i]
        n_st = len(s0.staff_labels)
        inner = ((s0.staff_bottom - s0.staff_top) - n_st * 4 * s0.sp) / (n_st - 1)
        extra = max(0.0, min(free / (j - i - 1),
                             (SYSTEM_GAP_LAST - SYSTEM_GAP_FACTOR) * inner * k))
    page, y_top = [], 0.0
    for t in range(i, j):
        s = strips[t]
        if t == i:
            y_top = s.staff_top * k
            page.append((s, 0.0))
        else:
            y_top += pit[t - 1] * k + extra
            page.append((s, y_top - s.staff_top * k))
    return page


def plan_pages(strips: list[Strip], dpi: int, opts: dict, title_page: bool
               ) -> tuple[list[list[tuple[Strip, float]]], int]:
    """plan_pages -> (pages of (strip, y), bad turns): page breaks chosen over the
    whole part at once (dynamic programming, not first-fit), so a turn
    falls at a section boundary where possible (DESIGN.md §5.4): a turn
    follows each recto (physical page 1, 3, 5, ...; page 1 is a title page
    when title_page) when printed double-sided. A section that fits on two
    pages then starts on a verso and needs no turn. Costs: TURN_BAD per
    turn not at good_turn, PAGE_COST per page, SHORT_LAST, FILL_COST."""
    n = len(strips)
    _, ph = PAPER[opts["paper"]]
    k = 72.0 / dpi * (opts.get("scale") or 1.0)
    pit = pitches(strips, opts)
    _, _, mt, mb = page_box(opts, 0, False)
    band = RUN_HEAD if (title_page or opts.get("_no_band")) else TITLE_BAND
    avail1 = ph - mt - mb - band
    availn = ph - mt - mb - RUN_HEAD
    cum = [0.0]
    for v in pit:
        cum.append(cum[-1] + v)
    duplex = opts.get("duplex", "auto") != "off"
    rest_rule = opts.get("turns", "any") == "rest"
    logo_on = logo_wanted(opts)
    logo_need = logo_room(ph, page_box(opts, 0, False)[3])

    def turn_cost(t: int) -> float:          # cost of a turn before line t
        if not rest_rule:
            return 0.0 if good_turn(strips, t) else TURN_BAD
        if rest_turn(strips, t):
            return 0.0
        return TURN_MOVE if strips[t].movement else TURN_HARD
    fill_cost = REPAGE_FILL if rest_rule else FILL_COST
    forced = sorted(f for f in set(opts.get("_breaks") or []) if 0 < f < n)

    def height(i: int, j: int) -> float:        # lines i..j-1 on one page (pt)
        last = strips[j - 1]
        return (strips[i].staff_top + (cum[j - 1] - cum[i]) - last.staff_top
                + last.img.shape[0]) * k

    first_phys = 2 if title_page else 1
    INF = float("inf")
    # best[c][j]: cost of lines 0..j-1 on content pages 0..c-1
    # at most 2 pages more than first-fit (more never saves a turn)
    maxp = min(n, len(_pack(strips, dpi, {**opts, "_no_band": title_page or opts.get("_no_band")},
                            None)) + (4 if rest_rule else 2) + len(forced))
    best = [dict() for _ in range(maxp + 1)]
    back: list[dict] = [dict() for _ in range(maxp + 1)]
    best[0][0] = 0.0
    total_best, end_c = INF, None
    for c in range(maxp):
        avail = avail1 if c == 0 else availn
        for i, cost in list(best[c].items()):
            fj = next((f for f in forced if f > i), None)   # a manual break ends a page here
            for j in range(i + 1, n + 1):
                h = height(i, j)
                if h > avail and j > i + 1:
                    break
                cc = cost + PAGE_COST
                if j == n and logo_on and avail - h < logo_need:
                    cc += LOGO_COST          # no room for the logo under the last line
                if j < n:
                    cc += fill_cost * max(0.0, 1.0 - h / avail) ** 2
                    phys = first_phys + c
                    if phys % 2 == 1 or not duplex:
                        cc += turn_cost(j)
                if cc < best[c + 1].get(j, INF):
                    best[c + 1][j] = cc
                    back[c + 1][j] = i
                if fj is not None and j >= fj:
                    break
        if n in best[c + 1]:
            last_i = back[c + 1][n]
            tot = best[c + 1][n]
            if c > 0 and n - last_i < min(MIN_LAST_LINES, n // (c + 1)):
                tot += SHORT_LAST
            if tot < total_best:
                total_best, end_c = tot, c + 1
        if not best[c + 1]:
            break
    # pages from the back pointers, then y of each line as in _pack
    cuts, j, c = [], n, end_c
    while c > 0:
        i = back[c][j]
        cuts.append((i, j))
        j, c = i, c - 1
    pages = []
    cuts = list(reversed(cuts))
    for c, (i, j) in enumerate(cuts):
        # last page of a group score with room to spare: systems further
        # apart, up to SYSTEM_GAP_LAST (operator request 2026-10-24: "the whole page
        # is available")
        free = None
        if c == len(cuts) - 1:
            free = (avail1 if c == 0 else availn) - height(i, j)
        pages.append(page_lines(strips, pit, k, i, j, free))
    bad, j = 0, 0
    for c, pg in enumerate(pages[:-1]):
        j += len(pg)
        if ((first_phys + c) % 2 == 1 or not duplex) and turn_cost(j) >= (
                TURN_HARD if rest_rule else TURN_BAD):
            bad += 1
    return pages, bad


TRIM_PT = 36.0         # 1/2 in cut off the free edge of a fold-out flap


def fold_sides(opts: dict) -> tuple:
    """fold_sides -> the sides fold-outs may take: the key `foldside` (right, left,
    auto = either, the cheaper one; right on a tie)."""
    return {"left": ("left",), "auto": ("right", "left")}.get(opts.get("foldside", "right"), ("right",))


def folds_wanted(opts: dict) -> bool:
    """The planner of turnplan (spreads, fold-outs) runs for double-sided parts
    with `foldouts: on`; single-sided print has a turn after every page."""
    return opts.get("foldouts", "off") == "on" and opts.get("duplex", "auto") != "off"


def plan_faces(strips: list[Strip], dpi: int, opts: dict, title_page: bool):
    """plan_faces -> (pages, Plan): the faces of a part (content pages; a flap
    is a face) with page breaks and fold-outs chosen by turnplan for the whole
    part at once (DESIGN.md §5.7). pages: (strip, y) pairs per face, in
    reading order."""
    n = len(strips)
    _, ph = PAPER[opts["paper"]]
    k = 72.0 / dpi * (opts.get("scale") or 1.0)
    pit = pitches(strips, opts)
    _, _, mt, mb = page_box(opts, 0, False)
    band = RUN_HEAD if (title_page or opts.get("_no_band")) else TITLE_BAND
    avail1 = ph - mt - mb - band
    availn = ph - mt - mb - RUN_HEAD
    cum = [0.0]
    for v in pit:
        cum.append(cum[-1] + v)

    def height(i: int, j: int) -> float:        # lines i..j-1 on one page (pt)
        last = strips[j - 1]
        return (strips[i].staff_top + (cum[j - 1] - cum[i]) - last.staff_top
                + last.img.shape[0]) * k

    bounds = [Boundary()] + [
        Boundary(rest_bars=edge_rest(strips, j), movement=bool(strips[j].movement))
        for j in range(1, n)]
    plan = plan_turns(n, height, availn, bounds, avail_first=avail1, title_page=title_page,
                      allow_fold=opts["paper"] in LARGE, forced=tuple(opts.get("_breaks") or []),
                      fold_sides=fold_sides(opts))
    flat = [pg for g in plan.groups for pg in g.pages]
    pages = []
    for c, (i, j) in enumerate(flat):
        free = (avail1 if c == 0 else availn) - height(i, j) if c == len(flat) - 1 else None
        pages.append(page_lines(strips, pit, k, i, j, free))
    return pages, plan


def page_report(strips: list[Strip], dpi: int, opts: dict) -> list[dict]:
    """page_report -> one row per face of the part as it would be laid out now (no drawing): page
    (the printed label), i and j (its lines i..j-1), first and last bar, systems, free (the spare
    height at the foot, in systems of the page: its tallest line pitch), turn (the turn after it: the dict of turn_list, or None),
    role (normal, bound, flap), manual (a manual break ends the page), pin (a pin of `pages --move`
    ends it, 0.8.39)."""
    breaks, pins, _ = page_limits(strips, opts)
    o = {**opts, "_breaks": sorted(set(breaks) | set(pins))}
    if folds_wanted(o):
        pages, title_page, plan = layout_plan(strips, dpi, o)
        flat = [pg for g in plan.groups for pg in g.pages]
        faces, _ = build_faces(plan, pages, title_page)
        labels = [f["label"] for f in faces]
        roles = [f["role"] for f in faces]
        tmap = {t["page"]: t for t in plan_turn_list(strips, plan, faces, breaks)}
    else:
        pages, title_page = layout_pages(strips, dpi, o)
        flat, j0 = [], 0
        for pg in pages:
            flat.append((j0, j0 + len(pg)))
            j0 += len(pg)
        labels = [f"{c + 1}/{len(pages)}" for c in range(len(pages))]
        roles = ["normal"] * len(pages)
        tmap = {t["page"]: t for t in turn_list(strips, pages, title_page, o, breaks)}
    _, ph = PAPER[o["paper"]]
    k = 72.0 / dpi * (o.get("scale") or 1.0)
    pit = pitches(strips, o)
    _, _, mt, mb = page_box(o, 0, False)
    avail = [ph - mt - mb - (RUN_HEAD if title_page else TITLE_BAND)] + [ph - mt - mb - RUN_HEAD] * (len(flat) - 1)
    spans = line_spans(strips)
    out = []
    for c, (i, j) in enumerate(flat):
        used = (strips[i].staff_top + sum(pit[i:j - 1]) - strips[j - 1].staff_top + strips[j - 1].img.shape[0]) * k
        out.append({"page": labels[c], "i": i, "j": j, "systems": j - i,
                    "first": spans[i][0] if spans[i] else None,
                    "last": (spans[j - 1][1] if spans[j - 1] and spans[j - 1][1] is not None
                             else (spans[j][0] - 1 if j < len(spans) and spans[j] else None)),
                    "free": max(0.0, (avail[c] - used) / (max(pit[i:max(j - 1, i + 1)] or [1.0]) * k)),
                    "turn": tmap.get(labels[c]),
                    "role": roles[c], "manual": j in breaks, "pin": j in pins})
    return out


def layout_plan(strips: list[Strip], dpi: int, opts: dict):
    """layout_plan -> (pages, title page?, Plan): plan_faces with and without a
    title page (title_page auto, 3+ pages); the cheaper plan wins, a tie keeps
    the title page (the music then starts on a spread)."""
    pages, plan = plan_faces(strips, dpi, opts, False)
    if opts.get("title_page", "auto") == "auto" and len(pages) >= 3:
        tp, tplan = plan_faces(strips, dpi, opts, True)
        if len(tp) >= 3 and tplan.cost <= plan.cost:
            return tp, True, tplan
    return pages, False, plan


def layout_pages(strips: list[Strip], dpi: int, opts: dict
                 ) -> tuple[list[list[tuple[Strip, float]]], bool]:
    """layout_pages -> (content pages, title page?). DESIGN.md §5.4: page
    breaks by plan_pages, with and without a title page (title_page auto,
    double-sided, 3+ content pages); fewer bad turns, then fewer pages
    win; a tie keeps the title page (the music starts on a spread)."""
    if folds_wanted(opts):
        pages, title_page, _ = layout_plan(strips, dpi, opts)
        return pages, title_page
    pages, bad = plan_pages(strips, dpi, opts, False)
    if opts.get("title_page", "auto") == "auto" and opts.get("duplex", "auto") != "off" \
       and len(pages) >= 3:
        tp, tbad = plan_pages(strips, dpi, opts, True)
        if len(tp) >= 3 and (tbad, len(tp)) <= (bad, len(pages)):
            return tp, True
    return pages, False


AMB_HEAD = 0.8         # ambitus notehead size, share of a normal head (cue size)
CLEF_LINE = {"G": 2, "C": 3, "F": 4}


def draw_ambitus(page: pymupdf.Page, x: float, base: float, clef: str, lo: int,
                 hi: int, lo_alt: int = 0, hi_alt: int = 0, sp: float = AMB_SP) -> None:
    """draw_ambitus: a small staff (bottom line at base) with the clef and
    the lowest and highest notes as black noteheads without stems, stacked
    in one column at 80 % size (cue size), ledger lines as needed.
    lo, hi: diatonic numbers. lo_alt, hi_alt: +1 sharp, -1 flat, 0 none;
    an accidental (80 % size) stands left of the heads. Accidentals less
    than a sixth apart stand in two columns (upper nearer the heads) and
    the head column moves right, inside the same width."""
    w = ambitus_width(sp)
    lw = max(0.35, 0.12 * sp)
    for i in range(5):
        y = base - i * sp
        page.draw_line((x, y), (x + w, y), color=(0, 0, 0), width=lw)
    fam = clef[0]
    line = 2 if clef == "G8" else (int(clef[1]) if clef[1:].isdigit() else CLEF_LINE.get(fam, 2))
    glyph = "\ue052" if clef == "G8" else {"G": "\ue050", "C": "\ue05c",
                                            "F": "\ue062"}.get(fam, "\ue050")
    put_text(page, (x + 0.3 * sp, base - (line - 1) * sp), glyph, "music", 4 * sp)
    bottom = CLEF_BOTTOM.get(clef, 30)
    head = "\ue0a4"                                  # noteheadBlack, no stem
    hsize = AMB_HEAD * 4 * sp                        # 80 % of the staff's notehead
    hw = text_len(head, "music", hsize)
    acc = {lo: lo_alt, hi: hi_alt} if lo != hi else {lo: lo_alt or hi_alt}
    stagger = bool(lo_alt and hi_alt and 0 < hi - lo < 6)
    xh = x + (5.5 if stagger else 4.6) * sp          # both notes in one column
    xs = {lo: xh, hi: xh}
    if hi - lo == 1:                                 # a second: the upper head
        xs[hi] = xh + hw                             # moves right, as in a chord
    for d in (lo, hi):
        step = d - bottom
        y = base - step * sp / 2
        for ls in list(range(-2, step - 1, -2)) + list(range(10, step + 1, 2)):
            yl = base - ls * sp / 2
            page.draw_line((xs[d] - 0.3 * sp, yl), (xs[d] + hw + 0.3 * sp, yl),
                           color=(0, 0, 0), width=lw * 1.4)
        put_text(page, (xs[d], y), head, "music", hsize)
    xa = xh - 0.2 * sp
    for d in ((hi,) if lo == hi else (hi, lo)):      # upper accidental nearer the heads
        a_ = acc.get(d, 0)
        if not a_:
            continue
        g_ = ACC_GLYPH[a_]
        aw = text_len(g_, "music", hsize)
        put_text(page, (xa - aw, base - (d - bottom) * sp / 2), g_, "music", hsize)
        if stagger:
            xa -= aw + 0.1 * sp


# The logo is optional. The setting is PARTITOR_LOGO (a PNG file); without it, the file
# the caller found in the library location (opts["_logo_file"], set by build; library is
# above this module). Neither: no logo, no room kept.
LOGO_TITLE_H = 64.0     # pt, on a title page
LOGO_TITLE_Y = 0.76     # title page: logo centre, share of the page height (balances the title block)
LOGO_LAST_H = 44.0      # pt, on the back page (centred above the folio)
LOGO_LAST_MIN_H = 28.0  # pt, smaller than this the wordmark is not legible: logo left out
LOGO_GAP = 4.0          # pt, between the last line and the logo
LOGO_FOLIO_GAP = 10.0   # pt, between the logo and the folio
LOGO_COST = 20.0        # plan_pages: the last page has no room for the logo (less than PAGE_COST)
FOLIO_SIZE = 9.5        # pt
_LOGO_WARNED: list[bool] = []


def folio_base(ph: float, mb: float) -> float:
    """folio_base -> baseline (pt from the top) of the folio, in the bottom margin."""
    return ph - mb + min(18.0, mb - 6.0)


def folio_top(ph: float, mb: float) -> float:
    """folio_top -> top of the folio's digits (pt from the top of the page)."""
    return folio_base(ph, mb) - 0.7 * FOLIO_SIZE


def logo_room(ph: float, mb: float) -> float:
    """logo_room -> height the music area must leave free on the last page for
    the logo above the folio, beyond the bottom margin (pt, 0 when the margin holds it)."""
    return max(0.0, LOGO_LAST_MIN_H + LOGO_GAP + LOGO_FOLIO_GAP - (folio_top(ph, mb) - (ph - mb)))


def _logo_setting(opts: dict | None) -> str | None:
    """_logo_setting -> the logo file as set: PARTITOR_LOGO wins, then
    opts["_logo_file"] (the library file); None when neither is set."""
    return os.environ.get("PARTITOR_LOGO") or (opts or {}).get("_logo_file") or None


def _logo_label(opts: dict | None) -> str:
    return "PARTITOR_LOGO file" if os.environ.get("PARTITOR_LOGO") else "library logo"


def logo_path(opts: dict | None = None) -> Path | None:
    """logo_path -> the logo PNG file (see _logo_setting); None when nothing is
    set or the file is missing."""
    v = _logo_setting(opts)
    return Path(v) if v and Path(v).is_file() else None


def logo_wanted(opts: dict) -> bool:
    """logo_wanted -> True when pages carry a logo: a logo is set (even when the
    file is missing: put_logo then warns once) and the layout key `logo` is not off."""
    return opts.get("logo", "on") == "on" and bool(_logo_setting(opts))


def logo_width(h: float, opts: dict | None = None) -> float | None:
    """logo_width -> width in pt of the logo at height h; None when missing or
    not a readable image."""
    path = logo_path(opts)
    if path is None:
        return None
    try:
        pix = pymupdf.Pixmap(str(path))
    except Exception:                       # noqa: BLE001  (mupdf raises its own error classes)
        return None
    return h * pix.width / pix.height


def put_logo(page: pymupdf.Page, x: float, y: float, h: float, align: str = "left",
             opts: dict | None = None) -> float:
    """put_logo -> width of the logo drawn (0.0 when the file is missing or not
    a readable image, with one warning per run). Top-left at (x, y), height h pt;
    align "right" takes x as the right edge, "centre" as the centre line."""
    path = logo_path(opts)
    w = logo_width(h, opts) if path is not None else None
    if w is None:
        if not _LOGO_WARNED:
            _LOGO_WARNED.append(True)
            what = "not found" if path is None else "is not a readable image"
            _warn(f"logo: {_logo_label(opts)} {what}: {_logo_setting(opts)} (pages are drawn without it)")
        return 0.0
    x0 = x - w if align == "right" else (x - w / 2 if align == "centre" else x)
    page.insert_image(pymupdf.Rect(x0, y, x0 + w, y + h), filename=str(path))
    return w


def _title_page(page: pymupdf.Page, name: str, meta: dict, box: tuple,
                logo: bool = False, opts: dict | None = None) -> None:
    """Title page (DESIGN.md §5.4): title, subtitle, part name, composer,
    members of a group, centred in the upper third."""
    pw, ph = page.rect.width, page.rect.height
    ml, mr, mt, _ = box
    cx = (ml + pw - mr) / 2

    def centre(text: str, size: float, y: float, kind: str) -> None:
        put_text(page, (cx - text_len(text, kind, size) / 2, y), text, kind, size)
    y = mt + ph * 0.22
    if meta.get("title"):
        centre(meta["title"], 28, y, "regular")
        y += 30
    if meta.get("subtitle"):
        centre(meta["subtitle"], 16, y, "italic")
        y += 24
    if meta.get("composer"):
        centre(meta["composer"], 15, y + 8, "regular")
        y += 30
    y += 40
    centre(name, 24, y, "bold")
    if meta.get("members"):
        centre(meta["members"], 12, y + 24, "italic")
    if meta.get("ambitus"):
        sp_ = AMB_SP * 1.15
        draw_ambitus(page, cx - ambitus_width(sp_) / 2, y + 48, *meta["ambitus"], sp=sp_)
    if logo:                                  # centred, towards the bottom (balances the title block)
        put_logo(page, cx, ph * LOGO_TITLE_Y - LOGO_TITLE_H / 2, LOGO_TITLE_H, "centre", opts)


def turn_list(strips: list[Strip], pages: list, title_page: bool, opts: dict,
              breaks: list[int] | None = None) -> list[dict]:
    """turn_list -> one dict per page turn (after each recto; every page when
    single-sided): pdf_page (the page before the turn, 1-based in the PDF), page
    (its printed number, "26/30": the one the player reads),
    bar (last bar before the turn, None if unknown), next_bar, rest (bars of
    the multi-bar rest beside the turn; 0 if none), ok (the player rests or
    a movement or rehearsal letter starts: good_turn), resting (rest_turn),
    manual (a page break set by `breaks`)."""
    duplex = opts.get("duplex", "auto") != "off"
    first_phys = 2 if title_page else 1
    out, j = [], 0
    for c, pg in enumerate(pages[:-1]):
        j += len(pg)
        phys = first_phys + c
        if not (phys % 2 == 1 or not duplex):
            continue
        a, b = line_bars(strips[j - 1]), line_bars(strips[j])
        rest = edge_rest(strips, j)
        out.append({"pdf_page": phys, "page": f"{c + 1}/{len(pages)}",
                    "bar": a[1] if a and a[1] is not None else None,
                    "next_bar": b[0] if b else None, "rest": rest,
                    "ok": good_turn(strips, j), "resting": rest_turn(strips, j),
                    "movement": bool(strips[j].movement) and not rest_turn(strips, j),
                    "manual": j in (breaks or [])})
    return out


@dataclass(frozen=True)
class Face:
    """Where and how one content page is drawn. x0, width: the face on its
    sheet (pt; a ledger fold-out sheet holds two faces); ml, mr: margins
    inside the face; title_band: page 1 of a part with no title page;
    head_right: running head at the right (a recto); folio: the page label;
    last: the back page (the logo goes here)."""
    x0: float
    width: float
    height: float
    ml: float
    mr: float
    mt: float
    mb: float
    title_band: bool
    head_right: bool
    folio: str
    last: bool


def draw_face(page: pymupdf.Page, pg: list, strips: list[Strip], name: str, meta: dict,
              opts: dict, k: float, left_ink: float, f: Face) -> None:
    """draw_face: one content page: title band or running head, folio, the
    lines of pg ((strip, y) pairs) and, on the back page, the logo."""
    ph, mt, mb = f.height, f.mt, f.mb
    L, R = f.x0 + f.ml, f.x0 + f.width - f.mr         # text area (x)
    if f.title_band:
        # Title band. insert_text draws at a baseline and never drops
        # text (insert_textbox drops text that does not fit its box).
        cx = (L + R) / 2

        def centre(text: str, size: float, base: float, kind: str) -> None:
            put_text(page, (cx - text_len(text, kind, size) / 2, base), text, kind, size)
        if meta.get("title"):
            centre(meta["title"], 21, mt + 18, "regular")
        if meta.get("subtitle"):
            centre(meta["subtitle"], 13, mt + 38, "italic")
        put_text(page, (L, mt + 66), name, "bold", 16)
        if meta.get("ambitus") and not any(s_.ambitus_marks for s_ in strips):
            # no room in the first-line indent: beside the part name
            draw_ambitus(page, L + text_len(name, "bold", 16) + 14,
                         mt + 66 - 5.5 + 2 * AMB_SP, *meta["ambitus"])
        if meta.get("composer"):
            w = text_len(meta["composer"], "regular", 12)
            put_text(page, (R - w, mt + 66), meta["composer"], "regular", 12)
        if meta.get("members"):
            put_text(page, (L, mt + 80), meta["members"], "italic", 10)
        top = mt + TITLE_BAND
    else:
        # interior pages: short composer — title — part
        short = meta.get("composer_short") or composer_surname(meta.get("composer", ""))
        head = " — ".join(x for x in (short, meta.get("title", ""), name) if x)
        if f.head_right:                      # recto: head at the outer (right)
            w = text_len(head, "italic", 9.5)
            put_text(page, (R - w, mt + 4), head, "italic", 9.5)
        else:                                 # verso or single-sided: left
            put_text(page, (L, mt + 4), head, "italic", 9.5)
        top = mt + RUN_HEAD
    w = text_len(f.folio, "regular", FOLIO_SIZE)
    put_text(page, ((L + R - w) / 2, folio_base(ph, mb)), f.folio, "regular", FOLIO_SIZE)
    for s, y in pg:
        hpx, wpx = s.img.shape
        x = L + (left_ink - anchor(s)) * k
        rect = pymupdf.Rect(x, top + y, x + wpx * k, top + y + hpx * k)
        if s.bar_no is not None:
            # bar number above the staff start, clear of the clef
            base, _, _ = bar_mark(s)
            put_text(page, (x + bar_x(s) * k, top + y + base * k), str(s.bar_no),
                     "italic", s.bar_size * s.sp * k)
        for bx0, btop, bx1, bbot, letter, fs, bl in reh_boxes(s):
            r = pymupdf.Rect(x + bx0 * k, top + y + btop * k,
                             x + bx1 * k, top + y + bbot * k)
            page.draw_rect(r, color=(0, 0, 0), width=max(0.6, 0.12 * s.sp * k))
            put_text(page, (x + (bx0 + REH_PAD * s.sp) * k, top + y + bl * k),
                     letter, "bold", fs * k)
        for rb in rest_boxes(s):
            put_text(page, (x + rb[0] * k, top + y + rb[3] * k), rb[5], rb[6], rb[4] * k)
        for xl_, bot_, clef_, lo_, hi_, *alt_ in s.ambitus_marks:
            draw_ambitus(page, x + xl_ * k, top + y + bot_ * k, clef_, lo_, hi_,
                         *alt_, sp=s.sp * k)
        for t_, x1_, base_, fs_, caps_ in line_labels(s):
            if caps_:
                put_smallcaps(page, x + x1_ * k, top + y + base_ * k, t_, fs_ * k)
            else:
                put_text(page, (x + x1_ * k - text_len(t_, "regular", fs_ * k),
                                top + y + base_ * k), t_, "regular", fs_ * k)
        if s.bracket:
            # group score: a bracket joins the staves (engraver practice)
            bx = x + (s.staff_x0 - 1.0 * s.sp) * k
            y0 = top + y + s.staff_top * k
            y1 = top + y + s.staff_bottom * k
            lw = 0.45 * s.sp * k
            page.draw_line((bx, y0 - 0.3 * s.sp * k), (bx, y1 + 0.3 * s.sp * k),
                           color=(0, 0, 0), width=lw)
            for yy, d in ((y0 - 0.3 * s.sp * k, -1), (y1 + 0.3 * s.sp * k, 1)):
                page.draw_line((bx - lw / 2, yy), (bx + 0.9 * s.sp * k, yy + d * 0.5 * s.sp * k),
                               color=(0, 0, 0), width=0.18 * s.sp * k)
        # grey + alpha: paper is transparent, so a nested strip never
        # hides ink of the strip above it
        ga = np.empty((hpx, wpx, 2), np.uint8)
        ga[..., 0] = 0
        ga[..., 1] = np.where(s.img, 255, 0)
        pix = pymupdf.Pixmap(pymupdf.csGRAY, wpx, hpx, ga.tobytes(), True)
        page.insert_image(rect, pixmap=pix)
    if f.last and logo_wanted(opts):
        # back page: logo centred above the folio, in the room left under
        # the last line (plan_pages leaves room where it can)
        s_, y_ = pg[-1]
        free = folio_top(ph, mb) - LOGO_FOLIO_GAP - (top + y_ + s_.img.shape[0] * k)
        lh = min(LOGO_LAST_H, free - LOGO_GAP)
        if lh >= LOGO_LAST_MIN_H:
            put_logo(page, (L + R) / 2, folio_top(ph, mb) - LOGO_FOLIO_GAP - lh, lh,
                     "centre", opts)
        elif logo_path(opts) is not None:
            _warn(f"{name}: no room for the logo on the back page (page {f.folio.split('/')[0]}); left out")


def plan_turn_list(strips: list[Strip], plan, faces: list[dict], breaks: list[int]) -> list[dict]:
    """plan_turn_list -> one dict per turn of a turnplan Plan, in the form of
    turn_list (pdf_page = the page before the turn, 1-based in the book; a
    fold-out counts as its bound face). cls: the turn class."""
    out, j = [], 0
    for gi, g in enumerate(plan.groups[:-1]):
        j = g.turn.before
        last = [f for f in faces if f["group"] == gi and f["role"] != "flap"][-1]
        a, b = line_bars(strips[j - 1]), line_bars(strips[j])
        c = g.turn.cls
        out.append({"pdf_page": last["book"], "page": last["label"],
                    "bar": a[1] if a and a[1] is not None else None,
                    "next_bar": b[0] if b else None, "rest": g.turn.bars,
                    "ok": c in ("rest", "rest1", "attacca"), "resting": c in ("rest", "rest1"),
                    "movement": c == "attacca", "manual": j in (breaks or []),
                    "cls": c, "fold": g.fold})
    return out


def flap_margins(opts: dict, width: float, flap_width: float) -> tuple[float, float]:
    """flap_margins -> (fold-side margin, free-edge margin) in pt of a flap face
    that must hold the same text width as the other faces. The free edge is
    trimmed, so the text area is what is left of the trimmed panel."""
    side = mm2pt(opts.get("margin_side", 15.0))
    floor = mm2pt(config.MIN_MARGIN_MM)
    text = usable_width(opts, width)
    ml = side
    mr = flap_width - text - ml
    if mr < floor:
        mr = floor
        ml = flap_width - text - mr
        if ml < floor:
            _warn("fold-out flap: the text is too wide for the trimmed flap; lower binding "
                  "or margin_side")
            ml = floor
    return ml, mr


def build_faces(plan, pages: list, title_page: bool) -> tuple[list[dict], int]:
    """build_faces -> (faces, leaves): the faces of a turnplan Plan in reading order (a flap is a
    face), each with its group, role (normal, bound, flap), leaf, book page, sheet and printed
    label ("7", "7a", "6b"). leaves: the number of leaves (the denominator of a label). pages:
    what render_plan draws on each face, in the same order (anything for a report)."""
    faces, leaf, idx = [], 0, 0
    for gi, g in enumerate(plan.groups):
        order = ("flap", "bound", "normal") if g.fold and g.side == "left" else \
                ("normal", "bound", "flap") if g.fold else ("normal", "normal")
        for fi in range(g.faces):
            role = order[fi]
            if role != "flap":
                leaf += 1
            faces.append({"group": gi, "role": role, "leaf": leaf, "page": pages[idx], "idx": idx,
                          "book": leaf + (1 if title_page else 0), "sheet": None, "side": g.side})
            idx += 1
    for gi, g in enumerate(plan.groups):         # a left flap precedes its verso: same leaf number
        if g.fold and g.side == "left":
            fl = next(f for f in faces if f["group"] == gi and f["role"] == "flap")
            fl["leaf"] = next(f for f in faces if f["group"] == gi and f["role"] == "bound")["leaf"]
    total = leaf
    for gi, g in enumerate(plan.groups):
        if not g.fold:
            continue
        for f in faces:
            if f["group"] == gi and f["role"] in ("bound", "flap"):
                f["sheet"] = gi
        if g.side == "left":                     # the sheet's other side: the previous recto
            prev = [f for f in faces if f["group"] == gi - 1 and f["role"] != "flap"]
            if prev and prev[-1]["sheet"] is None:
                prev[-1]["sheet"] = gi
        else:                                    # the verso of the next group
            nxt = next((f for f in faces if f["group"] == gi + 1 and f["role"] == "normal"), None)
            if nxt is not None and nxt["sheet"] is None:
                nxt["sheet"] = gi
    for f in faces:
        if f["role"] == "normal":
            f["label"] = f"{f['leaf']}/{total}"
        elif f["side"] == "left":
            f["label"] = f"{f['leaf']}{'a' if f['role'] == 'flap' else 'b'}/{total}"
        else:
            f["label"] = f"{f['leaf']}{'a' if f['role'] == 'bound' else 'b'}/{total}"
    return faces, total


def render_plan(name: str, strips: list[Strip], meta: dict, dpi: int, opts: dict,
                out: Path, pages: list, title_page: bool, plan, breaks: list[int]) -> int:
    """render_plan -> physical page count of the part PDF. The part of a plan
    with fold-outs (DESIGN.md §5.7): out holds every leaf as Letter pages
    except the flaps. A fold-out has two ways to be made, and both files are
    written: <out>-foldout-sheets.pdf holds one ledger sheet (two pages: front
    and back) per fold-out, to replace the two part pages of its leaf; and
    <out>-foldout-flaps.pdf holds each flap on a Letter page, to cut and tape to
    its page. A sheet is one leaf with a flap on its outer edge.
    Right fold-out (verso, recto, flap): the front of the sheet is the recto and
    the flap, its back the verso of the next group. Left fold-out (flap, verso,
    recto): one side is the flap and the verso, the other the last recto of the
    previous group. Page numbers count leaves: the recto is 7a and the flap 7b
    (right); the flap 6a and the verso 6b (left). The flap is trimmed 1/2 in at
    its free edge and folds forward over its page. <out>-assemble.txt says how to
    print the files and how each fold-out is made."""
    pw, ph = PAPER[opts["paper"]]
    cl = opts.get("cutline", "dotted")
    k = 72.0 / dpi * (opts.get("scale") or 1.0)
    left_ink = max(anchor(s) for s in strips)
    faces, total = build_faces(plan, pages, title_page)
    LAST_RENDER["turns"] = plan_turn_list(strips, plan, faces, breaks)
    nfaces = len(faces)

    def face_for(f: dict, x0: float, width: float, ml: float, mr: float, mt: float, mb: float,
                 head_right: bool) -> Face:
        return Face(x0=x0, width=width, height=ph, ml=ml, mr=mr, mt=mt, mb=mb,
                    title_band=(f["idx"] == 0 and not title_page), head_right=head_right,
                    folio=f["label"], last=(f["idx"] == nfaces - 1 and f["role"] != "flap"))

    def put(sheet: pymupdf.Page, f: dict, x0: float, width: float | None = None,
            margins: tuple | None = None) -> None:
        """Draw face f on a sheet page: a leaf face at x0 with its own margins, or a flap."""
        ml, mr, mt, mb = page_box(opts, f["book"] - 1, True)
        if margins is not None:
            ml, mr = margins
        draw_face(sheet, f["page"], strips, name, meta, opts, k, left_ink,
                  face_for(f, x0, pw if width is None else width, ml, mr, mt, mb, f["book"] % 2 == 1))

    doc = pymupdf.open()
    if title_page:
        page = doc.new_page(width=pw, height=ph)
        _title_page(page, name, meta, page_box(opts, 0, True), logo_wanted(opts), opts)
    for f in faces:
        if f["role"] == "flap":                  # a flap is on a sheet or in the flaps file
            continue
        page = doc.new_page(width=pw, height=ph)
        put(page, f, 0.0)
        f["pdf"] = len(doc)
    if plan.folds and len(doc) % 2:
        doc.new_page(width=pw, height=ph)          # a blank back: the leaves print in pairs
    doc.save(out, garbage=3, deflate=True)
    foldout = None
    if plan.folds:
        foldout = out.with_name(out.stem + FOLDOUT_TAIL)
        places = sheet_places(faces, plan, title_page)
        sheets = pymupdf.open()
        flap_w = pw - TRIM_PT
        fm, em = flap_margins(opts, pw, flap_w)        # fold side, free edge
        mt = page_box(opts, 0, True)[2]
        for gi, g in enumerate(plan.groups):
            if not g.fold:
                continue
            sno = places[gi]["sheet"]
            hint = (f"Sheet {sno} of {len(places)}. Print double-sided, flip on the short edge. "
                    f"Bind {places[gi]['where']}.")
            fb = next(f for f in faces if f["group"] == gi and f["role"] == "bound")
            ff = next(f for f in faces if f["group"] == gi and f["role"] == "flap")
            other = next((f for f in faces if f["sheet"] == gi and f["role"] == "normal"), None)
            left = g.side == "left"
            # a page object is only valid until the next page is added: draw each page at once
            front = sheets.new_page(width=2 * pw, height=ph)
            if left:                 # flap | verso (spine at the right edge)
                put(front, ff, TRIM_PT, flap_w, (em, fm))
                put(front, fb, pw)
                sheet_guides(front, pw, ph, TRIM_PT, mt,
                              f"{name}: fold-out {ff['leaf']}a / {fb['leaf']}b. {cut_words(cl, 'left')}, "
                              f"fold at the middle, flap forward over {fb['leaf']}b.", hint, cutline=cl)
            else:                    # recto (spine at the left edge) | flap
                put(front, fb, 0.0)
                put(front, ff, pw, flap_w, (fm, em))
                sheet_guides(front, pw, ph, 2 * pw - TRIM_PT, mt,
                              f"{name}: fold-out {fb['leaf']}a / {fb['leaf']}b. {cut_words(cl, 'right')}, "
                              f"fold at the middle, flap forward over {fb['leaf']}a.", hint, cutline=cl)
            back = sheets.new_page(width=2 * pw, height=ph)
            if other is not None:    # left: previous recto | flap outside; right: flap outside | next verso
                put(back, other, 0.0 if left else pw)
            sheet_guides(back, pw, ph, 2 * pw - TRIM_PT if left else TRIM_PT, mt,
                          "Back of the sheet (outside of the flap: blank). Cut and fold on the front lines.",
                          hint, lines=False)
        sheets.save(foldout, garbage=3, deflate=True)
        flaps_pdf = out.with_name(out.stem + FLAPS_TAIL)
        flaps = pymupdf.open()
        for gi, g in enumerate(plan.groups):       # one Letter page per flap, for the tape route
            if not g.fold:
                continue
            ff = next(f for f in faces if f["group"] == gi and f["role"] == "flap")
            left = g.side == "left"
            pl = places[gi]
            pg = flaps.new_page(width=pw, height=ph)
            if left:                 # the flap's fold edge is the right edge of the page
                put(pg, ff, TRIM_PT, flap_w, (em, fm))
            else:                    # the fold edge is the left edge of the page
                put(pg, ff, 0.0, flap_w, (fm, em))
            flap_guides(pg, TRIM_PT if left else flap_w, pw if left else 0.0, ph, mt,
                         f"{name}: flap {ff['label']}. {cut_words(cl)}.",
                         f"Flap {pl['sheet']} of {len(places)}. Print on one side only. Tape the "
                         f"{'right' if left else 'left'} edge of this page to the {pl['edge']} edge of "
                         f"page {pl['bound_label']}.", cutline=cl)
        flaps.save(flaps_pdf, garbage=3, deflate=True)
        assemble = out.with_name(out.stem + ASSEMBLE_TAIL)
        assemble.write_text(assemble_text(name, out.name, foldout.name, flaps_pdf.name,
                                          *paper_words(opts["paper"], pw, ph), places, len(doc), cl,
                                          large_words(out, flaps_pdf, opts)), encoding="utf-8")
    LAST_RENDER.update(content=nfaces, title_page=title_page, foldouts=plan.folds,
                       foldout=foldout.name if foldout else None,
                       flaps=flaps_pdf.name if foldout else None,
                       assemble=assemble.name if foldout else None)
    return len(doc)


def paper_words(paper: str, pw: float, ph: float) -> tuple[str, str]:
    """paper_words -> (part paper, sheet paper) as the assembly text names them."""
    if paper == "letter":
        return "Letter paper (8.5 x 11 in)", "ledger paper (17 x 11 in)"
    if paper == "a4":
        return "A4 paper", "A3 paper (420 x 297 mm)"
    return "the part paper", f"paper {2 * pw / 72:.1f} x {ph / 72:.1f} in"


def large_words(out: Path, flaps: Path, opts: dict) -> tuple | None:
    """large_words -> the `large` argument of assemble_text (0.8.36), None when no large copy
    is made: the two large files, the large paper as named, the 1/2 in trim at the large size,
    and whether a blank strip at the foot is cut off (Letter on 11x17; A4 fills A3)."""
    paper = opts["paper"]
    if opts.get("large") != "on" or paper not in LARGE:
        return None
    sheet = {"letter": "11 x 17 in paper", "a4": "A3 paper"}.get(paper, "the large paper")
    trim = 0.5 * LARGE[paper][0][0] / PAPER[paper][0]
    return (large_path(out, paper).name, large_path(flaps, paper).name, sheet, trim,
            LARGE[paper][0][1] - PAPER[paper][1] * LARGE[paper][0][0] / PAPER[paper][0] > 1.0)


FOLDOUT_TAIL = "-foldout-sheets.pdf"      # <part>.pdf -> <part>-foldout-sheets.pdf
FLAPS_TAIL = "-foldout-flaps.pdf"         # <part>.pdf -> <part>-foldout-flaps.pdf
ASSEMBLE_TAIL = "-assemble.txt"           # <part>.pdf -> <part>-assemble.txt


def sheet_text(paper: str, folds: int) -> str:
    """sheet_text -> what the fold-outs of an option mean for the printer, or ''."""
    if not folds:
        return ""
    big = {"letter": "17 x 11 in", "a4": "A3"}.get(paper, "double width")
    return (f"{folds} fold-out sheet{'s' if folds != 1 else ''} ({big}), or {folds} Letter "
            f"flap{'s' if folds != 1 else ''} to tape")


def sheet_places(faces: list[dict], plan, title_page: bool) -> dict:
    """sheet_places -> {group index: place} for each fold-out, in book order. place:
    sheet (number), leaves (the leaf numbers the sheet replaces), pdf (the part
    file pages the sheet replaces, 1-based), labels (their page labels), where
    (text), bound_label (page the flap is taped to), edge (of that page: left or
    right)."""
    out = {}
    for gi, g in enumerate(plan.groups):
        if not g.fold:
            continue
        mine = [f for f in faces if f["sheet"] == gi and f["role"] != "flap"]
        mine.sort(key=lambda f: f["pdf"])
        fb = next(f for f in faces if f["group"] == gi and f["role"] == "bound")
        pdf = [f["pdf"] for f in mine]
        out[gi] = {"sheet": len(out) + 1, "leaves": sorted({f["leaf"] for f in mine}), "pdf": pdf,
                   "labels": [f["label"] for f in mine], "bound_label": fb["label"], "bound_pdf": fb["pdf"],
                   "edge": "left" if g.side == "left" else "right",
                   "where": ("in place of page" + ("s " if len(pdf) > 1 else " ")
                             + " and ".join(str(x) for x in pdf) + " of the part file")}
    return out


def render_part(name: str, strips: list[Strip], meta: dict, dpi: int,
                opts: dict, out: Path) -> int:
    """render_part -> physical page count. Writes out (PDF). meta: title,
    subtitle, composer, members (group score: its parts, top to bottom)."""
    pw, ph = PAPER[opts["paper"]]
    k = 72.0 / dpi * (opts.get("scale") or 1.0)
    breaks, pins, bwarn = page_limits(strips, opts)
    for w_ in bwarn:
        _warn(f"{name}: {w_}")
    opts = {**opts, "_breaks": sorted(set(breaks) | set(pins))}
    if folds_wanted(opts):
        pages, title_page, plan = layout_plan(strips, dpi, opts)
        return render_plan(name, strips, meta, dpi, opts, out, pages, title_page, plan, breaks)
    pages, title_page = layout_pages(strips, dpi, opts)
    LAST_RENDER["turns"] = turn_list(strips, pages, title_page, opts, breaks)
    doc = pymupdf.open()
    n = len(pages)
    duplex = title_page or is_duplex(opts, n)
    left_ink = max(anchor(s) for s in strips)    # widest ink left of the alignment line
    if title_page:
        page = doc.new_page(width=pw, height=ph)
        _title_page(page, name, meta, page_box(opts, 0, duplex), logo_wanted(opts), opts)
    for ci, pg in enumerate(pages):
        phys = ci + (1 if title_page else 0)
        page = doc.new_page(width=pw, height=ph)
        ml, mr, mt, mb = page_box(opts, phys, duplex)
        draw_face(page, pg, strips, name, meta, opts, k, left_ink,
                  Face(x0=0.0, width=pw, height=ph, ml=ml, mr=mr, mt=mt, mb=mb,
                       title_band=(ci == 0 and not title_page),
                       head_right=bool(duplex and phys % 2 == 0),
                       folio=f"{ci + 1}/{n}", last=(ci == n - 1)))
    doc.save(out, garbage=3, deflate=True)
    LAST_RENDER.update(content=n, title_page=title_page, foldouts=0, foldout=None, flaps=None, assemble=None)
    return n + (1 if title_page else 0)
