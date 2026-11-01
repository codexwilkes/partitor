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
from .reflow import _diverge, _single, _x0, find_prefixes
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
        rest_label=None if s.rest_label is None else (s.rest_label[0] + n, s.rest_label[1]))


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
    each gap, after the clef; engraved glyphs are never stretched. A
    multi-bar rest line is drawn again at the width."""
    if s.rest_src is not None:
        src, cw, run = s.rest_src
        r = make_rest_strip(s, src, cw, run, {"bar_raise": s.bar_raise,
                                              "bar_size": s.bar_size},
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
    if not runs:
        return s
    counts = np.ones(s.img.shape[1], np.int64)
    base, rem = divmod(int(extra), len(runs))
    for j, (a, b) in enumerate(runs):
        counts[(a + b) // 2] += base + (1 if j < rem else 0)
    start = np.cumsum(counts) - counts                   # new x of each old column
    rp = lambda m: None if m is None else np.repeat(m, counts, axis=1)
    return dc_replace(
        s, img=rp(s.img), hdr=rp(s.hdr), num_mask=rp(s.num_mask),
        marks=[(int(start[min(mx, len(start) - 1)]), t) for mx, t in s.marks],
        bars_x=[int(start[min(b, len(start) - 1)]) for b in s.bars_x])


def short_name(name: str) -> str:
    """Abbreviation for a group staff label: words of 5+ letters cut to 3
    and a full stop; numbers, roman numerals and short words kept
    ('Basso Trombone grosso' -> 'Bas. Tro. gro.')."""
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


def finish_lines(strips: list[Strip], name: str, group: bool,
                 amb: tuple | None = None, amb_map: dict | None = None) -> list[Strip]:
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
        elif s.rest_src is not None or not (last_of_mvt and length < RAGGED_LAST * target):
            s = justify(s, target)
        out.append(s)
    if group and any(s.staff_labels for s in out):
        # one label column on every line (else the lines with names would
        # stick out at the right): short names, full names on the first
        # line where they fit the column
        size = LABEL_SP * sp
        shorts = {n: short_name(n) for s in out for n, *_ in s.staff_labels}
        col_w = max(text_len(v, "regular", size) for v in shorts.values())
        col = int(col_w + 3.0 * sp)
        if amb_map and any(amb_map.values()):
            # the first line shows each staff's ambitus instead of its name
            col = max(col, int((AMB_W_SP + 3.0) * sp))
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
REST_BAR_SP = 26.0      # width of a multi-bar rest (H-bar) measure
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
    mid = top + int(round(2 * sp))
    if run.bars > 1:                               # H-bar on the middle line
        a, b = x0 + int(2 * sp), x1 - int(2 * sp)  # across the measure (engraving)
        img[mid - int(0.45 * sp):mid + int(0.45 * sp) + 1, a:b] = True
        # brackets at both ends: full staff height, 0.5 sp thick (operator request
        # 2026-10-24, twice: 0.3 sp from line 2 to 4 was not seen)
        sw = max(4, int(round(0.5 * sp)))
        for xx in (a, b - sw):
            img[top:top + h4 + th, xx:xx + sw] = True
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
# Cached lines (0.3.0-dev.37, `repage`)
# =============================================================================
# A build keeps the finished lines of each part (after finish_lines: justified,
# indented, labelled) in <item>/lines/<part>.lines. `repage` loads them and
# plans the page breaks again; nothing is analysed or built again. The file is
# a gzip pickle read by a restricted unpickler (numpy arrays and the Strip and
# RestRun classes only). LINES_FORMAT changes with the fields of Strip.
LINES_FORMAT = 1
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
               strips: list[Strip]) -> None:
    """save_lines: write the finished lines of one part (atomic). The source
    image of a rest line is dropped (the line is not drawn again)."""
    slim = [dc_replace(s, rest_src=(None, 0, s.rest_src[2])) if s.rest_src is not None else s
            for s in strips]
    payload = {"format": LINES_FORMAT, "fields": strip_fields(), "version": VERSION,
               "name": name, "dpi": dpi, "meta": dict(meta),
               "opts": {k: v for k, v in opts.items() if not k.startswith("_")},
               "strips": slim}
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
    if not isinstance(d, dict) or d.get("format") != LINES_FORMAT \
       or d.get("fields") != strip_fields():
        raise ValueError(f"saved lines are from another partitor ({d.get('version', '?')} "
                         f"{path.name}): rebuild the part")
    return d


def count_bad_turns(turns_: list[dict], opts: dict) -> int:
    """Turns where the player is playing (turns=rest), or where no section
    starts and no rest stands (turns=any)."""
    if opts.get("turns", "any") == "rest":
        return sum(1 for t in turns_ if not t["resting"] and not t.get("movement"))
    return sum(1 for t in turns_ if not t["ok"])


def turn_text(t: dict) -> str:
    """One page turn as a line for the report."""
    bar = f"bar {t['bar']}" if t["bar"] is not None else "bar ?"
    nxt = f" -> {t['next_bar']}" if t["next_bar"] is not None else ""
    why = (f"rest {t['rest']} bars" if t["resting"] else
           "movement start, no rest: check that it is not attacca" if t.get("movement") else
           "section start (player may be playing)" if t["ok"] else "PLAYING")
    return f"PDF page {t['pdf_page']}: after {bar}{nxt}  {why}" + \
        ("  [manual break]" if t["manual"] else "")
