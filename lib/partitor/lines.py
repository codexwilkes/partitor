# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""Line fitting, labels, multi-bar rests and saved lines files."""
from __future__ import annotations

import dataclasses
import gzip
import os
import pickle
from dataclasses import replace as dc_replace
from pathlib import Path

import cv2
import numpy as np
import pymupdf

from . import VERSION
from .config import file_part_name
from .mapping import _NUMERALS
from .model import RestRun, Strip
from .reflow import (MERGE_EDGE_SP, REST_BAR_SP, _diverge, _single, _x0, draw_hbar,
                     find_prefixes, rest_bar_block)
from .strips import anchor
from .typography import put_text, text_len


# =============================================================================
# Line width, indent, labels (engraved-part look)
# =============================================================================
INDENT_MIN_SP = 4.0     # a first line this much shorter is indented, not stretched
INDENT_MAX = 0.15       # largest first-line indent, share of the line width
RAGGED_LAST = 0.6       # a movement's last line below this share of the width stays short
NAME_SP = (2.0, 1.2)    # part name in the indent: largest, smallest size (sp)
LABEL_SP = 1.5          # group staff label size (sp)


def pad_left(s: Strip, n: int) -> Strip:
    """pad_left -> strip with n blank columns at the left, kept as indent."""
    if n <= 0:
        return s
    pw = ((0, 0), (n, 0))
    return dc_replace(
        s, img=np.pad(s.img, pw), hdr=np.pad(s.hdr, pw),
        num_mask=None if s.num_mask is None else np.pad(s.num_mask, pw),
        staff_x0=s.staff_x0 + n, indent=s.indent + n,
        marks=[(mx + n, t) for mx, t in s.marks],
        bars_x=[b + n for b in s.bars_x],
        rest_label=None if s.rest_label is None else (s.rest_label[0] + n, s.rest_label[1]),
        rest_labels=[(cx + n, *rest) for cx, *rest in s.rest_labels])


def staff_end(s: Strip) -> int:
    """Last column (img) where 3 of the 5 lines of the top staff have ink."""
    hits = np.zeros(s.img.shape[1], np.int16)
    for kk in range(5):
        y = int(round(s.staff_top + kk * s.sp))
        band = s.img[max(0, y - 1):y + 2]
        if band.size:
            hits += band.any(axis=0)
    cols = np.flatnonzero(hits >= 3)
    return int(cols.max()) if cols.size else s.img.shape[1] - 1


def justify(s: Strip, target: int) -> Strip:
    """justify -> the line stretched so its staff is target px long (from
    the staff start). Space is added only in blank gaps between glyphs
    (columns with staff lines only, 0.25 sp or wider), the same amount in
    each gap, after the clef; engraved glyphs are never stretched, and the gap
    inside a final barline or a double bar (barlines on both sides, under 1 sp)
    stays as it is. A
    multi-bar rest line is drawn again at the width."""
    if s.rest_src is not None:
        src, cw, run = s.rest_src
        r = make_rest_strip(s, src, cw, run, {"bar_raise": s.bar_raise,
                                              "bar_size": s.bar_size,
                                              "rest_bar": s.rest_bar},
                            staff_len=target)
        r = dc_replace(r, bracket=s.bracket)     # drawn again: keep the group bracket
        return pad_left(dc_replace(r, name_label=s.name_label), s.indent) if s.indent else r
    sp = s.sp
    end = staff_end(s)
    extra = target - (end - s.staff_x0)
    if extra < 0.3 * sp:
        return s
    x0 = s.staff_x0 + int(4.5 * sp)
    x1 = end - int(0.3 * sp)
    if x1 <= x0:
        return s
    rows = s.img[:, x0:x1].mean(axis=1) > 0.6            # staff line rows
    if s.rest_labels:                    # a merged rest's H-bar can cover most of the line: take the rows
        sl = staff_lines(s)              # from the staff lines, not from the ink
        if sl:
            rows = np.zeros(s.img.shape[0], bool)
            for ln in sl:
                for c in ln:
                    rows[int(round(c))] = True
    rows = cv2.dilate(rows.astype(np.uint8)[:, None], np.ones((5, 1), np.uint8))[:, 0] > 0
    ink = s.img & ~rows[:, None]
    # text (lyrics, titles) lies outside the staff band: a gap between its
    # letters is no gap; widen that ink by 0.7 sp each side
    b0 = max(0, int(s.staff_top - 1.5 * sp))
    b1 = min(s.img.shape[0], int(s.staff_bottom + 1.5 * sp))
    outer = ink.copy()
    outer[b0:b1] = False
    k_ = np.ones((1, 2 * int(0.7 * sp) + 1), np.uint8)
    outer = cv2.dilate(outer.astype(np.uint8), k_) > 0
    other = ink[b0:b1].any(axis=0) | outer.any(axis=0)
    elig = np.zeros(s.img.shape[1], bool)
    elig[x0:x1] = ~other[x0:x1]
    d = np.diff(np.concatenate(([0], elig.astype(np.int8), [0])))
    runs = [(a, b) for a, b in zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1))
            if b - a >= max(2, int(0.25 * sp))]
    # a gap that closes a barline cluster (thin + thick final barline, double bar) is not a gap:
    # staff-height ink stands on both sides and the gap is narrower than 1 sp
    t0, t1 = int(s.staff_top), int(s.staff_top + 4 * sp) + 1
    bar = lambda xs: any(0 <= x < s.img.shape[1] and s.img[t0:t1, x].mean() > 0.9 for x in xs)
    # (the edge column of a thick line is often only partly inked: look 3 columns in)
    runs = [(a, b) for a, b in runs
            if not (b - a < sp and bar(range(a - 3, a)) and bar(range(b, b + 4)))]
    hspans = _hbar_spans(s)               # the H-bars of merged rests take most of the extra space
    if not runs and not hspans:
        return s
    counts = np.ones(s.img.shape[1], np.int64)
    if not hspans:
        base, rem = divmod(int(extra), len(runs))
        for j, (a, b) in enumerate(runs):
            counts[(a + b) // 2] += base + (1 if j < rem else 0)
    else:
        points = [((a + b) // 2, 1) for a, b in runs] + [((a + b) // 2, HBAR_WEIGHT) for a, b in hspans]
        total = sum(w for _, w in points)
        done = 0
        for x_, w in sorted(points):
            counts[x_] += round(int(extra) * (done + w) / total) - round(int(extra) * done / total)
            done += w
    start = np.cumsum(counts) - counts                   # new x of each old column

    def centre(cx: float) -> float:                      # a count stays on the middle of its H-bar
        for a, b in hspans:
            if a <= cx < b:
                return (start[a] + start[b - 1] + counts[b - 1]) / 2.0
        return float(start[min(int(cx), len(start) - 1)])
    rp = lambda m: None if m is None else np.repeat(m, counts, axis=1)
    return dc_replace(
        s, img=rp(s.img), hdr=rp(s.hdr), num_mask=rp(s.num_mask),
        marks=[(int(start[min(mx, len(start) - 1)]), t) for mx, t in s.marks],
        bars_x=[int(start[min(b, len(start) - 1)]) for b in s.bars_x],
        rest_labels=[(centre(cx), *rest) for cx, *rest in s.rest_labels])


HBAR_WEIGHT = 3         # justify: an H-bar takes this many shares of the extra space, a blank gap one


def _hbar_spans(s: Strip) -> list[tuple[int, int]]:
    """_hbar_spans -> [(first column, end)] of the H-bar under each merged rest count of the
    line, read from the image (columns where the band around the middle line of the top staff
    is solid)."""
    sp = s.sp
    mid = int(round(s.staff_top + 2 * sp))
    band = s.img[max(0, mid - int(0.4 * sp)):mid + int(0.4 * sp) + 1].all(axis=0)
    out = []
    for cx in sorted({int(c) for c, *_ in s.rest_labels}):
        if not 0 <= cx < len(band) or not band[cx]:
            continue
        a = b = cx
        while a > 0 and band[a - 1]:
            a -= 1
        while b + 1 < len(band) and band[b + 1]:
            b += 1
        if (a, b + 1) not in out:
            out.append((a, b + 1))
    return out


def short_name(name: str, custom: str | None = None) -> str:
    """Abbreviation for a group staff label: words of 5+ letters cut to 3
    and a full stop; numbers, roman numerals and short words kept
    ('Basso Trombone grosso' -> 'Bas. Tro. gro.'). custom: the operator's
    short form of this part (`set ID "Part:short=..."`, 0.8.30); it replaces
    the rule."""
    if custom:
        return custom
    out = []
    for w in name.split():
        if len(w) >= 5 and w.isalpha() and w.lower() not in _NUMERALS:
            out.append(w[:3] + ".")
        else:
            out.append(w)
    return " ".join(out)


def line_labels(s: Strip) -> list[tuple[str, float, float, float, bool]]:
    """line_labels -> [(text, right x, baseline, size, small caps)] in strip
    px: the part name in the indent of the first line, or the label of
    each group staff, right-aligned 1 sp before the staff start and
    centred on the staff."""
    out = []
    xr = s.staff_x0 - (2.0 if s.bracket else 1.0) * s.sp     # clear of the bracket
    room = xr - (anchor(s) + 0.5 * s.sp)
    if s.name_label and room > 0:
        fs = NAME_SP[0] * s.sp
        w = smallcaps_len(s.name_label, fs)
        if w > room:
            fs *= room / w
        if fs >= NAME_SP[1] * s.sp:
            mid = (s.staff_top + s.staff_bottom) / 2
            out.append((s.name_label, xr, mid + 0.33 * fs, fs, True))
    for name, t, b in s.staff_labels:
        fs = LABEL_SP * s.sp
        out.append((name, xr, (t + b) / 2 + 0.35 * fs, fs, False))
    for name, t, b in s.name_labels:        # full name, left of the ambitus (0.8.29)
        fs = LABEL_SP * s.sp
        out.append((name, xr - (AMB_W_SP + 1.0) * s.sp, (t + b) / 2 + 0.35 * fs, fs, False))
    return out


def _smallcaps_runs(text: str, size: float) -> list[tuple[str, float]]:
    return [(ch.upper(), size * (0.78 if ch.islower() else 1.0)) for ch in text]


def smallcaps_len(text: str, size: float) -> float:
    return sum(text_len(ch, "regular", fs) for ch, fs in _smallcaps_runs(text, size))


def put_smallcaps(page: pymupdf.Page, x_right: float, base: float, text: str,
                  size: float) -> None:
    """Small caps from EB Garamond Regular (capitals at 78 % for lower
    case), right-aligned at x_right."""
    x = x_right - smallcaps_len(text, size)
    for ch, fs in _smallcaps_runs(text, size):
        put_text(page, (x, base), ch, "regular", fs)
        x += text_len(ch, "regular", fs)


AMB_W_SP = 8.0          # ambitus width in staff spaces (ambitus_width / sp)


def label_column(strips: list[Strip], sp: float, amb_map: dict | None = None,
                 short_map: dict | None = None) -> int:
    """label_column -> width (px) of the label column finish_lines puts left of
    the lines of a group (short staff names; the ambitus of each staff on
    the first line needs AMB_W_SP + 3 sp); 0 when no line has labels. short_map:
    {part: the operator's short form}."""
    if not any(s.staff_labels for s in strips):
        return 0
    size = LABEL_SP * sp
    shorts = {n: short_name(n, (short_map or {}).get(n)) for s in strips for n, *_ in s.staff_labels}
    col = int(max(text_len(v, "regular", size) for v in shorts.values()) + 3.0 * sp)
    if amb_map and any(amb_map.values()):
        # the first line shows each staff's ambitus instead of its name
        col = max(col, int((AMB_W_SP + 3.0) * sp))
    return col


def group_name_indent(s: Strip, room: int, target: int, amb_map: dict | None) -> int:
    """group_name_indent -> px of first-line indent that holds the full staff
    names left of the ambitus of a group; 0 when there is no room. room: how
    much shorter the first line is than the longest line. The ambitus stays
    (operator request 2026-10-25); the names are added only when the line is
    short enough by their width (and INDENT_MIN_SP) and the indent stays within
    INDENT_MAX of the line (0.8.29)."""
    if not s.staff_labels or not amb_map or not any(amb_map.get(n) for n, *_ in s.staff_labels):
        return 0
    size = LABEL_SP * s.sp
    need = int(max(text_len(n, "regular", size) for n, *_ in s.staff_labels) + 1.5 * s.sp)
    if room < max(need, int(INDENT_MIN_SP * s.sp)) or need > INDENT_MAX * target:
        return 0
    return need


def finish_lines(strips: list[Strip], name: str, group: bool,
                 amb: tuple | None = None, amb_map: dict | None = None,
                 short_map: dict | None = None) -> list[Strip]:
    """finish_lines -> the lines of one part or group at one width: the
    longest staff sets it; other lines are justified (a movement's short
    last line stays short). A first line shorter by INDENT_MIN_SP or more
    is right-aligned (indented) with the part name in small caps. Group
    lines: when the staves differ from line to line, every staff is
    labelled (short names) in an indent; else the first line has the full
    names. amb (a part) / amb_map (a group: part -> ambitus): the ambitus
    takes the place of the name on the first line, as engravers set it
    (operator request 2026-10-25); the first line is indented for it when there is
    room (else the ambitus stays beside the part name in the heading)."""
    if not strips:
        return strips
    sp = strips[0].sp
    ends = [staff_end(s) - s.staff_x0 for s in strips if s.rest_src is None]
    target = max(ends) if ends else max(s.img.shape[1] - s.staff_x0 for s in strips)
    out: list[Strip] = []
    for i, s in enumerate(strips):
        length = staff_end(s) - s.staff_x0
        last_of_mvt = i + 1 == len(strips) or strips[i + 1].movement
        amb_w = (AMB_W_SP + 1.5) * sp
        if i == 0 and not group and s.rest_src is None and amb \
           and target - length >= amb_w:
            # the ambitus in the first-line indent, in place of the name
            ind = int(min(max(target - length, amb_w), INDENT_MAX * target))
            if 0 < target - ind - length < 0.3 * sp:
                ind = target - length
            s = pad_left(justify(s, target - ind), ind)
            s = dc_replace(s, ambitus_marks=[(int(s.staff_x0 - 1.0 * sp - AMB_W_SP * sp),
                                              int(round(s.staff_bottom)), *amb)])
        elif i == 0 and not group and s.rest_src is None \
           and target - length >= INDENT_MIN_SP * sp:
            # engraved first line: indented by room for the name (at least
            # the source indent, at most INDENT_MAX of the width), the rest
            # justified
            want = smallcaps_len(name, NAME_SP[0] * sp) + 2.0 * sp
            ind = int(min(max(target - length, want), INDENT_MAX * target))
            if 0 < target - ind - length < 0.3 * sp:   # too little left to justify
                ind = target - length
            s = dc_replace(pad_left(justify(s, target - ind), ind), name_label=name)
        elif i == 0 and group and s.rest_src is None and \
                (ind := group_name_indent(s, target - length, target, amb_map)):
            # room: the full names in the indent, left of the ambitus
            s = dc_replace(pad_left(justify(s, target - ind), ind),
                           name_labels=[lb for lb in s.staff_labels if (amb_map or {}).get(lb[0])])
        elif s.rest_src is not None or not (last_of_mvt and length < RAGGED_LAST * target):
            s = justify(s, target)
        out.append(s)
    if group and any(s.staff_labels for s in out):
        # one label column on every line (else the lines with names would
        # stick out at the right): short names, full names on the first
        # line where they fit the column
        size = LABEL_SP * sp
        shorts = {n: short_name(n, (short_map or {}).get(n)) for s in out for n, *_ in s.staff_labels}
        col_w = max(text_len(v, "regular", size) for v in shorts.values())
        col = label_column(out, sp, amb_map, short_map)
        fin = []
        for j, s in enumerate(out):
            names, marks = [], []
            p_ = pad_left(s, col)
            for n, t, b in s.staff_labels:
                a_ = (amb_map or {}).get(n) if j == 0 else None
                if a_:
                    xl = p_.staff_x0 - (2.0 if p_.bracket else 1.0) * sp - AMB_W_SP * sp
                    marks.append((int(xl), int(round(b)), *a_))
                    continue
                full_fits = text_len(n, "regular", size) <= col_w
                names.append((n if (j == 0 and full_fits) else shorts[n], t, b))
            fin.append(dc_replace(p_, staff_labels=names, ambitus_marks=marks))
        out = fin
    return out


# =============================================================================
# Multi-bar rests
# =============================================================================
REST_ONE_SP = 12.0      # width of a one-bar rest measure


def make_rest_strip(tpl: Strip, src: Strip | None, cw: int, run: RestRun,
                    opts: dict, staff_len: int | None = None) -> Strip:
    """make_rest_strip -> one line with a multi-bar rest: clef and key
    signature copied from src (columns 0..cw; none when src is None), an
    H-bar with the bar count above it (one bar: a whole rest), and a
    barline. Staff lines as in tpl (a part's nearest line)."""
    sp = tpl.sp
    top = int(round(3.5 * sp))
    if run.header is not None:                     # movement title above
        himg, hdx, hgap = run.header
        top = max(top, himg.shape[0] + max(hgap, int(round(3.5 * sp))))
    h4 = int(round(4 * sp))
    h = top + h4 + int(round(2.5 * sp))
    wr = int(round((REST_BAR_SP if run.bars > 1 else REST_ONE_SP) * sp))
    th = max(1, int(round(0.1 * sp)))
    if src is None or cw <= 0 or not _single(src):
        src, cw = None, 0
    x_staff = max(0, src.staff_x0) if src is not None else 0
    if staff_len is not None:                      # line width of the part
        wr = max(int(6 * sp), staff_len + x_staff - cw + 1)   # staff_len: to the last column
    img = np.zeros((h, cw + wr), bool)
    col = np.zeros(h, bool)
    if src is not None:
        clean = src.img & ~src.hdr
        if src.num_mask is not None:
            clean &= ~src.num_mask
        r0 = src.staff_top - top                   # src row of img row 0
        a0, a1 = max(0, r0), min(src.img.shape[0], r0 + h)
        img[a0 - r0:a1 - r0, :cw] = clean[a0:a1, :cw]
        col = img[:, cw - 1].copy()                # the prefix ends in a blank gap:
    if not col[top:top + h4 + 1].any():            # staff lines only
        for kk in range(5):
            y = top + int(round(kk * sp))
            col[y:y + th] = True
    img[:, cw:] |= col[:, None]
    x0, x1 = cw, cw + wr
    style = opts.get("rest_bar", tpl.rest_bar)
    if run.bars > 1:                               # H-bar on the middle line
        draw_hbar(img, top, x0 + int(2 * sp), x1 - int(2 * sp), sp, style)   # across the measure (engraving)
    else:                                          # whole rest: hangs from the 2nd line
        c = (x0 + x1) // 2
        y = top + int(round(sp))
        img[y:y + int(round(0.5 * sp)), c - int(0.6 * sp):c + int(0.6 * sp)] = True
    bw = max(2, int(round(0.16 * sp)))
    img[top:top + h4 + 1, x1 - bw:x1] = True       # closing barline
    hdr = np.zeros_like(img)
    if run.header is not None:
        hx = max(0, x_staff + hdx)
        if hx + himg.shape[1] > img.shape[1]:      # a long title widens the line
            pad = hx + himg.shape[1] - img.shape[1]
            img = np.pad(img, ((0, 0), (0, pad)))
            hdr = np.pad(hdr, ((0, 0), (0, pad)))
        y1 = top - max(hgap, int(round(3.5 * sp)))
        hdr[y1 - himg.shape[0]:y1, hx:hx + himg.shape[1]] = himg
        img |= hdr
    return Strip(img, x_staff, top, top + h4, sp, hdr,
                 None if run.movement or run.first is None else run.first,
                 opts.get("bar_raise", 1.0), opts.get("bar_size", 2.0),
                 rest_bar=style,
                 movement=run.movement,
                 rest_label=((x0 + x1) / 2, str(run.bars)) if run.bars > 1 else None,
                 rest_src=(src, cw, run))


def fill_rests(items: list, opts: dict) -> list[Strip]:
    """fill_rests -> strips of one part with each run of RestRun items
    (systems without the part's staff) made one multi-bar rest line; a
    movement start begins a new run. The clef and key come from the
    part's line before the run (after it, for a run at the start)."""
    real = [x for x in items if isinstance(x, Strip)]
    if not real:
        return []
    if not any(isinstance(x, RestRun) for x in items):
        return real
    pre = find_prefixes(real)
    where = {id(x): i for i, x in enumerate(real)}
    out: list[Strip] = []
    run: RestRun | None = None
    run_at = 0

    def flush(k_next: int) -> None:
        nonlocal run
        if run is None:
            return
        before = [x for x in items[:run_at] if isinstance(x, Strip)]
        after = [x for x in items[k_next:] if isinstance(x, Strip)]
        tpl = before[-1] if before else after[0]
        ti = where[id(tpl)]
        p = pre[ti]
        src, cw = (real[p[1]], pre[p[1]][0]) if p else (None, 0)
        if p is None and _single(tpl):
            # no prefix for the line (one line in its movement): borrow the
            # nearest line's clef and key if this line starts the same way
            for j in sorted(range(len(real)), key=lambda j: abs(j - ti)):
                q = pre[j]
                if q is None:
                    continue
                d_, c_ = real[q[1]], pre[q[1]][0]
                if _diverge(tpl, d_) >= (c_ - _x0(d_)) - 0.5 * tpl.sp:
                    src, cw = d_, c_
                    break
        out.append(make_rest_strip(tpl, src, cw, run, opts))
        run = None

    for k, x in enumerate(items):
        if isinstance(x, RestRun):
            if run is not None and not x.movement:
                run.bars += x.bars
            else:
                flush(k)
                run, run_at = RestRun(x.bars, x.first, x.movement, x.header), k
        else:
            flush(k)
            out.append(x)
    flush(len(items))
    return out


# =============================================================================
# Bars of rests inside a line, merged (0.8.11)
# =============================================================================
MERGE_MIN_BARS = 2      # a run of this many rest-only bars becomes one multi-bar rest


def staff_lines(s: Strip) -> list[list[float]]:
    """staff_lines -> per staff of a line (top first) the rows of its five
    lines, read from the image: a row with ink over most of the staff is a
    staff line; five lines one sp apart make a staff."""
    sp = s.sp
    x1 = staff_end(s)
    x0 = _x0(s) + int(2 * sp)
    if x1 - x0 < 6 * sp:
        return []
    frac = s.img[:, x0:x1].mean(axis=1)
    rows = np.flatnonzero(frac >= 0.6)
    if not rows.size:
        return []
    cents, cur = [], [int(rows[0])]
    for r in rows[1:]:
        if r - cur[-1] <= 1:
            cur.append(int(r))
        else:
            cents.append(sum(cur) / len(cur))
            cur = [int(r)]
    cents.append(sum(cur) / len(cur))
    out, k = [], 0
    while k + 4 < len(cents):
        seg = cents[k:k + 5]
        if all(abs((b - a) - sp) <= 0.25 * sp for a, b in zip(seg, seg[1:])):
            out.append(seg)
            k += 5
        else:
            k += 1
    return out


def _only_measure_rests(s: Strip, lines: list[list[float]], xa: int, xb: int) -> bool:
    """True when columns xa..xb of the line hold, on every staff, one filled
    rest block (a whole or half rest) and nothing else but staff lines. Any
    other ink (note, stem, rest of another length, dot, text, a number) makes
    it False: a bar is merged only when this is certain."""
    sp = s.sp
    tops = [int(round(ln[0])) for ln in lines]
    if xb - xa < 2 * sp or not tops:
        return False
    for m in (s.num_mask, s.hdr):
        if m is not None and m[:, xa:xb].any():
            return False
    reg = s.img[:, xa:xb].copy()
    y0, y1 = tops[0], min(reg.shape[0], tops[-1] + int(round(4 * sp)) + 1)
    bar_cols = reg[y0:y1].mean(axis=0) >= 0.85       # a barline (thick, double) crosses all staves
    inked = reg.mean(axis=1)
    reg[inked >= 0.95] = False                 # staff lines run across the bar
    for ln in lines:                           # (a line may break around a rest: clear its rows)
        for c in ln:
            reg[max(0, int(round(c)) - 1):int(round(c)) + 2] = False
    reg[:, bar_cols] = False
    th = max(1, int(round(0.3 * sp)))
    near = np.zeros(reg.shape[0], bool)
    for t in tops:                             # rows of each staff, with the edge of a line
        near[max(0, t - th):min(len(near), t + int(round(4 * sp)) + th + 1)] = True
    if reg[~near].any():                       # ink above, below or between the staves
        return False
    for t in tops:
        y0, y1 = max(0, t - th), min(reg.shape[0], t + int(round(4 * sp)) + th + 1)
        part = reg[y0:y1]
        if not part.any():
            return False
        n, lab, stats, _ = cv2.connectedComponentsWithStats(part.astype(np.uint8), connectivity=8)
        if n != 2:                             # background and one block
            return False
        w, h, area = (int(stats[1, cv2.CC_STAT_WIDTH]), int(stats[1, cv2.CC_STAT_HEIGHT]),
                      int(stats[1, cv2.CC_STAT_AREA]))
        if not (0.8 * sp <= w <= 2.2 * sp and 0.25 * sp <= h <= 0.75 * sp
                and area >= 0.85 * w * h):
            return False
    return True


def rest_only_bars(s: Strip, pre_x: int | None) -> list[bool]:
    """rest_only_bars -> per bar of a line: True when it holds only measure rests on every
    staff (see _only_measure_rests). pre_x: where the music of bar 0 starts (None: bar 0 is
    never judged). [] for a line that is not read: a rest line, no final barline, no staff."""
    if s.rest_src is not None or not s.ends_at_bar or not s.bars_x:
        return []
    lines = staff_lines(s)
    if not lines or abs(lines[0][0] - s.staff_top) > max(2, int(0.2 * s.sp)):   # (the line centre is off by a pixel)
        return []
    e = int(MERGE_EDGE_SP * s.sp)
    ok = []
    for b, bx in enumerate(s.bars_x):
        if b == 0:
            xa = pre_x
            lo = 0
        else:
            xa = s.bars_x[b - 1] + e
            lo = s.bars_x[b - 1] - int(1.5 * s.sp)
        if xa is None or any(lo <= mx < bx for mx, _ in s.marks):
            ok.append(False)
            continue
        ok.append(_only_measure_rests(s, lines, xa, bx - e))
    return ok


ONE_BAR_START_SP = 16.0     # a line with no barline is read from here (clef and key are before it)


def _one_bar_rest(s: Strip) -> bool:
    """_one_bar_rest -> True when a line with no barline of its own holds, after its clef and
    key, one filled rest block on each staff and nothing else: one bar of rests."""
    lines = staff_lines(s)
    if not lines or abs(lines[0][0] - s.staff_top) > max(2, int(0.2 * s.sp)):
        return False
    xa = _x0(s) + int(ONE_BAR_START_SP * s.sp)
    xb = staff_end(s) - int(MERGE_EDGE_SP * s.sp)
    return xb - xa > 6 * s.sp and not any(mx >= xa for mx, _ in s.marks) \
        and _only_measure_rests(s, lines, xa, xb)


def _runs_of(ok: list[bool]) -> list[tuple[int, int]]:
    """_runs_of -> [(first, last)] of the runs of MERGE_MIN_BARS or more True values."""
    runs, b = [], 0
    while b < len(ok):
        if not ok[b]:
            b += 1
            continue
        z = b
        while z + 1 < len(ok) and ok[z + 1]:
            z += 1
        if z - b + 1 >= MERGE_MIN_BARS:
            runs.append((b, z))
        b = z + 1
    return runs


def rest_bar_runs(s: Strip, pre_x: int | None) -> list[tuple[int, int]]:
    """rest_bar_runs -> [(first bar, last bar)] runs of MERGE_MIN_BARS or more
    bars of a line that hold only measure rests on every staff. pre_x: where
    the music of bar 0 starts (None: bar 0 is never merged)."""
    return _runs_of(rest_only_bars(s, pre_x))


def merge_rest_bars(strips: list[Strip], opts: dict, pre: list | None = None) -> list[Strip]:
    """merge_rest_bars -> the lines with each run of bars that hold only
    measure rests on every staff made one multi-bar rest (an H-bar on each
    staff, the count above the top staff). `rests: keep` leaves the lines
    alone. Never a bar with a note, a mark or a number. A line that is only
    rests has its own treatment (RestRun); lines that cannot be cut are kept."""
    if opts.get("rests", "compress") != "compress":
        return strips
    pre = find_prefixes(strips) if pre is None else pre
    out = []
    for i, s in enumerate(strips):
        pre_x = pre[i][0] if pre[i] is not None else None
        if not s.bars_x and s.rest_src is None and _one_bar_rest(s):
            out.append(dc_replace(s, rest_in=1, rest_out=1))        # a line with no barline: one bar of rests
            continue
        ok = rest_only_bars(s, pre_x)
        runs = _runs_of(ok)
        last = len(s.bars_x) - 1
        edge = {}
        lead = next((n for n, v in enumerate(ok) if not v), len(ok))        # rest-only bars at the start
        trail = next((n for n, v in enumerate(reversed(ok)) if not v), len(ok))     # and at the end
        if lead:                             # merged or not (a single bar, or too narrow to save): a rest
            edge["rest_in"] = lead           # at the edge of the line, for the page turn
        if trail:
            edge["rest_out"] = trail
        made = []
        for b0, b1 in reversed(runs):
            s2 = _merge_run(s, b0, b1, pre_x or 0)
            if s2 is not s:                  # made: the run is a rest at the line edge when it starts or ends it
                made.append((b0, b1))
                if b0 == 0:
                    edge["rest_in"] = b1 - b0 + 1
                if b1 == last:
                    edge["rest_out"] = b1 - b0 + 1
            s = s2
        if ok:                               # the bars that are left, each with its bars of rest
            counts, b = [], 0
            while b <= last:
                run = next(((x, z) for x, z in made if x == b), None)
                counts.append(run[1] - run[0] + 1 if run else (1 if ok[b] else 0))
                b = run[1] + 1 if run else b + 1
            edge["rest_counts"] = counts
        out.append(dc_replace(s, **edge) if edge else s)
    return out


def _merge_run(s: Strip, b0: int, b1: int, pre_x: int) -> Strip:
    """_merge_run -> the line with bars b0..b1 (a run found by rest_bar_runs)
    made one measure."""
    sp = s.sp
    e = int(MERGE_EDGE_SP * sp)
    xa = pre_x if b0 == 0 else s.bars_x[b0 - 1] + e
    xb = s.bars_x[b1] - e
    tops = [int(round(ln[0])) for ln in staff_lines(s)]
    block = rest_bar_block(s.img, xa, xb, tops, sp, s.rest_bar)
    if block is None:
        return s
    orig = xb - xa
    w = block.shape[1]
    h = s.img.shape[0]

    def splice(m: np.ndarray | None, fill: np.ndarray | None) -> np.ndarray | None:
        if m is None:
            return None
        return np.concatenate([m[:, :xa], np.zeros((h, w), bool) if fill is None else fill,
                               m[:, xb:]], axis=1)
    delta = w - orig
    img = splice(s.img, block)
    inner = set(range(b0, b1))                    # barlines inside the run go
    bars_x = [x if k < b0 else x + delta for k, x in enumerate(s.bars_x) if k not in inner]
    # the merged bar keeps the number of its first bar
    nums = [n for k, n in enumerate(s.bar_nums) if not (b0 < k <= b1)]
    marks = [(mx if mx < xa else mx + delta, t) for mx, t in s.marks]
    labels = [(cx if cx < xa else cx + delta, *rest) for cx, *rest in s.rest_labels]
    labels += [(xa + w / 2.0, str(b1 - b0 + 1), t - s.staff_top) for t in tops]     # a count above each staff
    labels.sort()
    return dc_replace(s, img=img, hdr=splice(s.hdr, None), num_mask=splice(s.num_mask, None),
                      bars_x=bars_x, bar_nums=nums, marks=marks, rest_labels=labels)


# =============================================================================
# Cached lines (0.3.0-dev.37, `repage`)
# =============================================================================
# A build keeps the finished lines of each part (after finish_lines: justified,
# indented, labelled) in <item>/lines/<part>.lines. `repage` loads them and
# plans the page breaks again; nothing is analysed or built again. The file is
# a gzip pickle read by a restricted unpickler (numpy arrays and the Strip and
# RestRun classes only). LINES_FORMAT changes with the fields of Strip.
LINES_FORMAT = 1
# Fields added to Strip after the format shipped, with their defaults: a file
# written before the field loads (the lines have none of it); any other
# difference in the fields still means "rebuild the part".
_FIELD_DEFAULTS = {"name_labels": list, "rest_labels": list, "rest_in": int, "rest_out": int, "rest_counts": list,
                   "rest_bar": lambda: "engraved"}
_NP_OK = {"_reconstruct", "ndarray", "dtype", "scalar", "_frombuffer"}


class _LinesUnpickler(pickle.Unpickler):
    def find_class(self, module: str, name: str):
        if name in ("Strip", "RestRun") and (module in ("__main__", "partitor", "pt", __name__)
                                             or module.startswith("partitor.")):
            return {"Strip": Strip, "RestRun": RestRun}[name]
        if module.split(".")[0] == "numpy" and name in _NP_OK:
            return super().find_class(module, name)
        if module == "builtins" and name in ("set", "frozenset", "slice", "complex"):
            return super().find_class(module, name)
        raise pickle.UnpicklingError(f"not allowed in a lines file: {module}.{name}")


def lines_path(lines_dir: Path, name: str) -> Path:
    return lines_dir / f"{file_part_name(name)}.lines"


def strip_fields() -> list[str]:
    return sorted(f.name for f in dataclasses.fields(Strip))


def save_lines(path: Path, name: str, dpi: int, meta: dict, opts: dict,
               strips: list[Strip], plan: dict | None = None) -> None:
    """save_lines: write the finished lines of one part (atomic). The source
    image of a rest line is dropped (the line is not drawn again). plan: the
    lines before re-flow as `partitor plan` needs them (partplan.Source.to_dict)."""
    slim = [dc_replace(s, rest_src=(None, 0, s.rest_src[2])) if s.rest_src is not None else s
            for s in strips]
    payload = {"format": LINES_FORMAT, "fields": strip_fields(), "version": VERSION,
               "name": name, "dpi": dpi, "meta": dict(meta),
               "opts": {k: v for k, v in opts.items() if not k.startswith("_")},
               "strips": slim, **({"plan": plan} if plan else {})}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with gzip.open(tmp, "wb", compresslevel=3) as f:
        pickle.dump(payload, f, protocol=pickle.HIGHEST_PROTOCOL)
    os.replace(tmp, path)


def load_lines(path: Path) -> dict:
    """load_lines -> the payload of save_lines. Raises ValueError (what is
    wrong) for a missing, damaged or foreign file."""
    if not path.is_file():
        raise ValueError(f"no saved lines ({path.name}): rebuild the part once")
    try:
        with gzip.open(path, "rb") as f:
            d = _LinesUnpickler(f).load()
    except (OSError, EOFError, pickle.UnpicklingError, AttributeError, ValueError) as e:
        raise ValueError(f"saved lines cannot be read ({path.name}: {e}): rebuild the part")
    cur = strip_fields()
    fields = d.get("fields") if isinstance(d, dict) else None
    missing = [f for f in cur if isinstance(fields, list) and f not in fields]
    if not isinstance(d, dict) or d.get("format") != LINES_FORMAT or not isinstance(fields, list) \
       or any(f not in cur for f in fields) or any(f not in _FIELD_DEFAULTS for f in missing):
        raise ValueError(f"saved lines are from another partitor ({d.get('version', '?') if isinstance(d, dict) else '?'} "
                         f"{path.name}): rebuild the part")
    for s in d.get("strips", []):                  # a file from before the field: the default
        for f in missing:
            s.__dict__.setdefault(f, _FIELD_DEFAULTS[f]())
    return d


def count_bad_turns(turns_: list[dict], opts: dict) -> int:
    """Turns where the player is playing (turns=rest), or where no section
    starts and no rest stands (turns=any)."""
    if opts.get("turns", "any") == "rest":
        return sum(1 for t in turns_ if not t["resting"] and not t.get("movement"))
    return sum(1 for t in turns_ if not t["ok"])


def turn_where(t: dict) -> str:
    """turn_where -> where a page turn is, as the player reads it: "page 26/30, before bar 45".
    The page is the printed number; the PDF page when a saved turn has none."""
    page = t.get("page") or f"(PDF page {t['pdf_page']})"
    if t.get("next_bar") is not None:
        return f"page {page}, before bar {t['next_bar']}"
    if t.get("bar") is not None:
        return f"page {page}, after bar {t['bar']}"
    return f"page {page}"


def turn_text(t: dict) -> str:
    """One page turn as a line for the report."""
    why = (f"rest {t['rest']} bars" if t["resting"] else
           "movement start, no rest: check that it is not attacca" if t.get("movement") else
           "section start (player may be playing)" if t["ok"] else "PLAYING")
    return f"{turn_where(t)}  {why}" + \
        ("  [manual break]" if t["manual"] else "")
