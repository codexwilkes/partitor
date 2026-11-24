# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""Cues in the lines of a part (docs/DESIGN.md §13): the bar of a rest that
holds the last bar of a cue is split so that the cue's barline falls on a barline
of the part (respan), and the cue is drawn above the staff (draw_cue)."""
from __future__ import annotations

from dataclasses import dataclass, replace as dc_replace

import cv2
import numpy as np

from .cues import CueError, CueImg, CueSpec, crop_cue, cue_size, join_cues, split_rest
from .lines import rest_only_bars, staff_end, staff_lines
from .model import Strip
from .reflow import REST_BAR_SP, draw_hbar
from .strips import bar_mark, bar_x, reh_boxes, rest_box

CUE_BAR_MIN_SP = 4.0              # least width of the bar under a cue, sp (a narrow cue still meets the barline)
SINGLE_BAR_SP = 10.0              # width of a whole-rest bar made by a split, sp


@dataclass
class Bar:
    """A bar as the line shows it: `count` bars of rest when it is a merged rest."""
    first: int | None    # number of its first bar
    count: int           # bars it stands for (1: a bar)
    x0: int              # left edge: the music start, or the barline before it
    x1: int              # its right barline (column)
    rest: bool           # holds only rests (or nothing the program can read as notes)
    certain: bool = True # False: the rest test could not confirm it (a faint scan); the cue is placed on the operator's word


def shown_bars(s: Strip, music_x: int) -> list[Bar]:
    """line_bars -> the bars of a line as shown. A line that is only a rest
    (rest_src) is one bar. music_x: where the music of the first bar starts."""
    if s.rest_src is not None:
        run = s.rest_src[2]
        bw = max(2, int(round(0.16 * s.sp)))
        return [Bar(s.bar_no if s.bar_no is not None else run.first, int(run.bars), music_x,
                    staff_end(s) - bw, True)]
    flags = rest_only_bars(s, music_x, need_end=False, text_ok=True)    # also a bar with a printed word, or in a line merge did not read
    out = []
    for k, bx in enumerate(s.bars_x):
        n = s.bar_nums[k] if k < len(s.bar_nums) else None
        c = s.rest_counts[k] if k < len(s.rest_counts) else 0
        if c <= 0 and k < len(flags) and flags[k]:
            c = 1
        x0 = music_x if k == 0 else int(s.bars_x[k - 1])
        sure = True
        if c <= 0 and not _plays(s, x0, int(bx)):      # nothing that looks like a note or a stem
            c, sure = 1, False
        out.append(Bar(n, max(c, 1), x0, int(bx), c > 0, sure))
    return out


def _plays(s: Strip, xa: int, xb: int) -> bool:
    """_plays -> True when the bar xa..xb has ink that reads as a note: some column has ink in
    two or more of the four spaces of a staff filled by it (0.4 of the space height), which a stem or a head on a line has and a
    rest (one block in one space) does not. Text above or below a staff (a printed voice
    name) is outside the spaces and does not count. The staff lines are taken out
    with a fringe, so the faint lines of a poor scan are not ink."""
    sp = s.sp
    tops = _tops(s)
    e = int(0.8 * sp)
    a, b = xa + e, xb - e
    if b - a < 2 * sp:
        return False
    k = max(1, int(0.2 * sp))
    reg = s.img[:, a:b]
    y0, y1 = max(0, tops[0] - int(0.3 * sp)), min(reg.shape[0], tops[-1] + int(4.3 * sp))
    bar_cols = reg[y0:y1].mean(axis=0) >= 0.85                       # a barline crosses every space
    for t in tops:                                                   # staff by staff: rests of two staves can stand one over the other
        edges = [t + int(round(q * sp)) for q in range(5)]
        count = np.zeros(reg.shape[1], int)
        for q in range(4):                                           # the 4 spaces
            band = reg[edges[q] + k + 1:edges[q + 1] - k]
            count += band.sum(axis=0) >= 0.4 * band.shape[0]            # filled, not the fringe of a wavy line
        if ((count >= 2) & ~bar_cols).any():
            return True
    return False


def find_bar(bars: list[Bar], number: int) -> int | None:
    """find_bar -> the index of the bar of the line that holds bar `number`, or None."""
    for i, b in enumerate(bars):
        if b.first is not None and b.first <= number < b.first + b.count:
            return i
    return None


def _tops(s: Strip) -> list[int]:
    t = [int(round(ln[0])) for ln in staff_lines(s)]
    return t or [int(s.staff_top)]


def respan(s: Strip, bars: list[Bar], i1: int, i2: int, first: int, last: int,
           cue: CueImg | None = None, scale: float = 0.0) -> Strip:
    """respan -> the line with its shown bars i1..i2 (all rests) made into [rest before][bars
    first..last][rest after]: each piece one bar of its own (an H-bar with its count when it
    holds 2 or more bars, else a whole rest), the counts adding up to the original. The piece
    of the cue is as wide as the cue (at `scale`, target px per source px), so the barlines
    of the part and of the cue meet; a printed word between the staves stays where it was.
    CueError: a bar is not a rest, or there is text or a title over the rest."""
    b1, b2 = bars[i1], bars[i2]
    if not all(b.rest for b in bars[i1:i2 + 1]):
        raise CueError(f"bar {first}: the part plays here")
    sp = s.sp
    tops = _tops(s)
    x0, x1 = b1.x0, b2.x1
    lo, hi = tops[0] - int(0.5 * sp), tops[-1] + int(4.5 * sp)
    if s.img[:lo, x0:x1].any() or s.img[hi:, x0:x1].any() or s.hdr[:, x0:x1].any():
        raise CueError(f"bar {first}: there is text or a title over this rest")
    pieces = split_rest(b1.first, b2.first + b2.count - b1.first, first, last)
    style = s.rest_bar
    bw = max(2, int(round(0.16 * sp)))
    h = s.img.shape[0]
    ink = s.img[:, x0:x1].sum(axis=0)                            # staff lines only: the columns with least ink,
    col = s.img[:, x0 + np.argsort(ink, kind="stable")[:5]].any(axis=1)   # not one inside the scan's own H-bar
    blocks, widths = [], []
    for kind, f0, n in pieces:
        if kind == "cue" and cue is not None:
            w = max(int(CUE_BAR_MIN_SP * sp), cue.width_px(scale) - 1)   # the cue's last column is its barline
        else:
            w = int((REST_BAR_SP if n > 1 else SINGLE_BAR_SP) * sp)
        blk = np.repeat(col[:, None], w, axis=1)
        for t in tops:
            if n > 1:
                draw_hbar(blk, t, int(2 * sp), w - int(2 * sp), sp, style)
            else:
                c = w // 2
                y = t + int(round(sp))
                blk[y:y + int(round(0.5 * sp)), c - int(0.6 * sp):c + int(0.6 * sp)] = True
        blocks.append(blk)
        widths.append(w)
    parts, xs = [], []                                           # barline x (new coords) between pieces
    x = x0
    for k, blk in enumerate(blocks):
        parts.append(blk)
        x += blk.shape[1]
        if k < len(blocks) - 1:
            line = np.repeat(col[:, None], bw, axis=1)
            line[tops[0]:tops[-1] + int(4 * sp) + 1] = True
            parts.append(line)
            xs.append(x)
            x += bw
    new_w = x - x0
    delta = new_w - (x1 - x0)
    region = np.concatenate(parts, axis=1)
    band = np.zeros(h, bool)                                     # the rows of the staves (and a margin)
    for t in tops:
        band[max(0, t - int(0.3 * sp)):t + int(4.3 * sp) + 1] = True
    keep = min(new_w, x1 - x0)
    region[~band, :keep] = s.img[~band, x0:x0 + keep]            # a word between the staves stays at its place

    def splice(m: np.ndarray | None, fill: np.ndarray | None) -> np.ndarray | None:
        if m is None:
            return None
        mid = np.zeros((h, new_w), bool) if fill is None else fill
        return np.concatenate([m[:, :x0], mid, m[:, x1:]], axis=1)
    img = splice(s.img, region)
    sh = lambda v: v if v < x0 else v + delta
    if s.rest_src is None:
        bars_x = list(s.bars_x[:i1]) + xs + [b2.x1 + delta] + [sh(v) for v in s.bars_x[i2 + 1:]]
        nums = list(s.bar_nums[:i1]) + [p[1] for p in pieces] + list(s.bar_nums[i2 + 1:])
        counts = list(s.rest_counts[:i1]) + [p[2] for p in pieces] + list(s.rest_counts[i2 + 1:])
        if len(counts) != len(bars_x):                           # a line merge did not read: counts of what we know
            counts = [c.count if c.rest else 0 for c in bars[:i1]] + [p[2] for p in pieces] + \
                [c.count if c.rest else 0 for c in bars[i2 + 1:]]
    else:
        bars_x = xs + [b2.x1 + delta]
        nums = [p[1] for p in pieces]
        counts = [p[2] for p in pieces]
    labels = [(sh(cx), *rest) for cx, *rest in s.rest_labels if not x0 <= cx < x1]
    x = x0
    for (kind, f0, n), w in zip(pieces, widths):
        if n > 1:
            labels += [(x + w / 2.0, str(n), t - int(s.staff_top)) for t in tops]
        x += w + bw
    labels.sort()
    lead = 0
    for c in counts:
        if c <= 0:
            break
        lead += c
    trail = 0
    for c in reversed(counts):
        if c <= 0:
            break
        trail += c
    end = staff_end(s) + delta
    return dc_replace(
        s, img=img, hdr=splice(s.hdr, None), num_mask=splice(s.num_mask, None), bars_x=bars_x,
        bar_nums=nums, rest_counts=counts, rest_labels=labels, rest_label=None, rest_src=None,
        marks=[(sh(mx), t) for mx, t in s.marks], rest_in=lead, rest_out=trail, ends_at_bar=True,
        end_gap_sp=(end - bars_x[-1]) / sp)


CUE_CLEAR_SP = 1.0      # least clear space between a cue and the staff (or the ink above it), sp
CUE_LABEL_SP = 1.5      # size of the voice name above a cue, sp of the part
CUE_INK_MIN = 60        # a pixel of the scaled cue is ink from this grey value (0-255): thin lines stay


def pad_top(s: Strip, n: int) -> Strip:
    """pad_top -> the line with n blank rows above it (everything that holds a row moves down)."""
    if n <= 0:
        return s
    pw = ((n, 0), (0, 0))
    return dc_replace(
        s, img=np.pad(s.img, pw), hdr=np.pad(s.hdr, pw),
        num_mask=None if s.num_mask is None else np.pad(s.num_mask, pw),
        staff_top=s.staff_top + n, staff_bottom=s.staff_bottom + n,
        staff_labels=[(a, t + n, b + n) for a, t, b in s.staff_labels],
        name_labels=[(a, t + n, b + n) for a, t, b in s.name_labels],
        ambitus_marks=[(x, bot + n, *rest) for x, bot, *rest in s.ambitus_marks],
        cue_labels=[(x, b + n, f, t) for x, b, f, t in s.cue_labels],
        cue_boxes=[(x0, y0 + n, x1, y1 + n) for x0, y0, x1, y1 in s.cue_boxes])


def _count_boxes(s: Strip) -> list[tuple]:
    """_count_boxes -> the boxes of the counts of multi-bar rests above the top staff (a count a
    pixel or two off the first line is still the top staff's)."""
    labels = [lb for lb in s.rest_labels if len(lb) < 3 or lb[2] <= 0.5 * s.sp]
    return [b for b in (rest_box(s), *(rest_box(s, lb) for lb in labels)) if b]


def _no_specks(m: np.ndarray, sp: float) -> np.ndarray:
    """_no_specks -> the ink of m without pieces smaller than 0.1 sp squared (dust of a scan)."""
    if not m.any():
        return m
    n, lab, st, _ = cv2.connectedComponentsWithStats(m.astype(np.uint8), connectivity=8)
    small = [j for j in range(1, n) if st[j, cv2.CC_STAT_AREA] < 0.1 * sp * sp]
    return m & ~np.isin(lab, small) if small else m


HEAD_MIN_SP = 0.9                 # a stem has a head or a beam at one end that is this wide (sp); a stroke of a sharp or flat has none
PART_ABOVE_SP = 0.6               # a line of the part: ink this far above the staff or more is not a stem


def _wide(reg: np.ndarray, lines: np.ndarray, cx: float, ra: int, rb: int) -> int:
    """_wide -> the width (px) of the run of columns with ink (staff lines left out) in the rows
    ra to rb that holds column cx: a head or a beam at the end of a stem is wide, a stroke is not."""
    cols = (reg[max(0, ra):rb] & ~lines[max(0, ra):rb, None]).any(axis=0)
    c = int(round(cx))
    if not cols[c]:
        c = next((x for x in (c - 1, c + 1) if 0 <= x < cols.size and cols[x]), -1)
        if c < 0:
            return 0
    lo = hi = c
    while lo > 0 and cols[lo - 1]:
        lo -= 1
    while hi + 1 < cols.size and cols[hi + 1]:
        hi += 1
    return hi - lo + 1


def note_xs(img: np.ndarray, staff_top: float, sp: float, x0: int, x1: int,
            skip: tuple = (), above: float = 3.0) -> list[float]:
    """note_xs -> the columns of the heads of the notes with a stem between columns x0 and x1,
    from the left. A stem is a run of ink of 2.2 sp or more in the height of a staff (a gap of up to
    0.2 sp, where a staff line was); a barline (columns within 0.6 sp of those in `skip`; a thick
    final barline too) is not one, two stems less than 0.8 sp apart are one note (a chord), and a rest has no stem. The head is read at the end of the stem that has more ink
    beside it. Notes without a stem (a whole note) are not found. above: how far above the staff
    (sp) ink is read; a line of the part is read from 0.6 sp, so that a rehearsal letter or a
    word over the staff is not a stem. A stroke with no head or beam
    at either end (ink 0.9 sp wide) is the stroke of a sharp, flat or natural, not a note."""
    top = max(0, int(staff_top - above * sp))
    bot = min(img.shape[0], int(staff_top + 7 * sp))
    reg = img[top:bot, x0:x1]
    if reg.size == 0:
        return []
    lines = reg.mean(axis=1) > 0.7                         # the rows of the staff lines
    need = int(2.2 * sp)
    gap = max(2, int(0.2 * sp))
    stems = []
    for c in range(reg.shape[1]):
        if any(abs(x0 + c - b) <= max(2, 0.6 * sp) for b in skip):
            continue
        col = reg[:, c] | lines
        best = run = idle = 0
        first = start = 0
        for r in range(col.shape[0]):
            if col[r]:
                if run == 0:
                    start = r
                run += 1
                idle = 0
                if run > best:
                    best, first = run, start
            elif run:
                idle += 1
                run += 1
                if idle > gap:
                    run = 0
        if best >= need and reg[first:first + best, c].sum() >= 0.6 * best:
            stems.append((c, first, first + best))
    groups: list[tuple[float, int, int]] = []
    k = 0
    while k < len(stems):
        j = k
        while j + 1 < len(stems) and stems[j + 1][0] <= stems[j][0] + 1:
            j += 1
        groups.append(((stems[k][0] + stems[j][0]) / 2.0, min(s[1] for s in stems[k:j + 1]), max(s[2] for s in stems[k:j + 1])))
        k = j + 1
    out: list[float] = []
    sign_x = -1e9                                          # where the last stroke of an accidental stands
    h = max(2, int(0.9 * sp))
    for cx, ya, yb in groups:
        if not any(_wide(reg, lines, cx, ra, rb) >= HEAD_MIN_SP * sp for ra, rb in ((ya, ya + h), (yb - h, yb))):
            sign_x = cx
            continue
        reach = int(1.6 * sp)
        a, b = max(0, int(cx - reach), int(sign_x + 0.6 * sp) if cx - sign_x < 2.2 * sp else 0), min(reg.shape[1], int(cx + reach) + 1)
        best_ink, best_x = -1, cx
        for ra, rb in ((ya, ya + h), (yb - h, yb)):
            blob = reg[max(0, ra):rb, a:b] & ~lines[max(0, ra):rb, None]
            xs = np.flatnonzero(blob.any(axis=0))
            side = int(blob.sum())
            if xs.size and side > best_ink:
                w = blob.sum(axis=0).astype(float)
                best_ink, best_x = side, a + float((w * np.arange(w.size)).sum() / w.sum())
        if not out or x0 + best_x - out[-1] >= 0.8 * sp:
            out.append(x0 + best_x)
    return out


def scaled_cue(cue: CueImg, scale: float, fit_from: int | None = None,
               widths: list[int] | None = None, split: tuple[int, int] | None = None) -> np.ndarray:
    """scaled_cue -> the cue as a grey picture at `scale`. fit_from, widths: the bars of
    the cue from index fit_from on are given the widths (px, barline to barline) of the
    bars of the part under them; the height stays at the scale, so the notes are squashed
    or stretched sideways. split: (column of the cue, px): the first of these bars is scaled in
    two pieces, the columns before the column to the px asked and the rest to what is left of the
    width, so that a note of the cue stands over a note of the part."""
    g = cue.img.astype(np.uint8) * 255
    if not widths or fit_from is None or fit_from >= len(cue.bars):
        return cv2.resize(g, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    h = max(1, int(round(g.shape[0] * scale)))
    edges = [0] + [b + 1 for b in cue.bars]                        # the columns that end each bar (its barline too)
    parts = [(g[:, :edges[fit_from]], max(1, int(round(edges[fit_from] * scale))))]
    for k in range(fit_from, len(cue.bars)):
        w = widths[k - fit_from] if k - fit_from < len(widths) else int(round((edges[k + 1] - edges[k]) * scale))
        if split is not None and k == fit_from and edges[k] < split[0] < edges[k + 1] and 0 < split[1] < w:
            parts.append((g[:, edges[k]:split[0]], split[1]))
            parts.append((g[:, split[0]:edges[k + 1]], w - split[1]))
        else:
            parts.append((g[:, edges[k]:edges[k + 1]], max(1, w)))
    return np.concatenate([cv2.resize(p, (w, h), interpolation=cv2.INTER_AREA) for p, w in parts], axis=1)


def draw_cue(s: Strip, cue: CueImg, start_x: int, scale: float, label: str = "",
             fit_from: int | None = None, widths: list[int] | None = None,
             split: tuple[int, int] | None = None) -> tuple[Strip, list[str]]:
    """draw_cue -> (the line with the cue drawn above its top staff, warnings). The
    first bar of the cue starts on column start_x (the barline of the part);
    the clef may hang to the left of it. The cue sits CUE_CLEAR_SP above the staff
    and above any ink in its columns; the label goes just above its first bar after
    the clef. The rows are added at the top when there is no room. CueError: the
    cue would start left of the line. fit_from, widths, split: see scaled_cue."""
    sp = s.sp
    g = scaled_cue(cue, scale, fit_from, widths, split)
    ink = g >= CUE_INK_MIN
    ax = int(start_x) - int(round(cue.clef_px * scale))
    if ax < 0:
        raise CueError("the cue does not fit: it would start left of the system")
    h_c, w_c = ink.shape
    cols = _no_specks(s.img[:, ax:ax + w_c] & ~s.hdr[:, ax:ax + w_c], sp)
    rows = np.flatnonzero(cols[:int(s.staff_top - 0.3 * sp)].any(axis=1)) if cols.size else np.array([], int)   # (not the thickness of the top line)
    clear = int(round(CUE_CLEAR_SP * sp))
    bottom = int(s.staff_top) - clear
    warns = []
    if rows.size and rows.min() - clear < bottom:
        bottom = int(rows.min()) - clear
        warns.append("the cue stands above ink of the part (its clef hangs over the end of the bar before): "
                     "remove the clef or the cue if it looks wrong")
    for rx0, rtop, rx1, *_ in reh_boxes(s):     # a rehearsal letter stays on the system: the cue stands above it
        if rx1 > ax and rx0 < ax + w_c:
            bottom = min(bottom, int(rtop) - clear)
    if s.bar_no is not None:                    # so does the bar number of the system
        _, ntop, nw = bar_mark(s)
        if bar_x(s) + nw > ax and bar_x(s) < ax + w_c:
            bottom = min(bottom, int(ntop) - clear)
    for rb in _count_boxes(s):                  # the count of a multi-bar rest (its digits are taller than the box)
        if rb[2] > ax and rb[0] < ax + w_c:
            bottom = min(bottom, int(min(rb[1], rb[3] - 0.75 * rb[4])) - clear)
    fs = CUE_LABEL_SP * sp
    label_h = int(round(1.3 * fs)) if label else 0
    top = bottom - h_c - label_h
    if top < 0:
        s = pad_top(s, -top)
        bottom -= top
        top = 0
    out = s.img.copy()
    y0 = bottom - h_c
    out[y0:bottom, ax:ax + w_c] |= ink[:, :out.shape[1] - ax]
    labels = list(s.cue_labels)
    if label:
        labels.append((ax + cue.clef_px * scale, y0 - 0.35 * fs, fs, label))
    return dc_replace(s, img=out, cue_labels=labels,
                      cue_boxes=[*s.cue_boxes, (ax, y0 - label_h, ax + w_c, bottom)]), warns


def source_pieces(items: list, first: int, last: int, src: str) -> list[tuple[Strip, int, int, int, int]]:
    """source_pieces -> [(line, k1, k2, n1, n2)] of the source part (`items`: its Strip or
    RestRun per system): the bars first..last, each run of consecutive bars of one line
    as one piece; k: index of the bar in the line (bars_x), n: its number. A bar number
    that stands twice (a bar cut by a line break) is read where it first stands.
    CueError: a bar is not in the lines of the source (it rests there)."""
    got: dict[int, tuple[Strip, int]] = {}
    for s in items:
        if not isinstance(s, Strip):
            continue
        for k, n in enumerate(s.bar_nums):
            if first <= n <= last and n not in got and k < len(s.bars_x):
                got[n] = (s, k)
    for n in range(first, last + 1):
        if n not in got:
            raise CueError(f"{src} has no music in bar {n} (it rests there, or the bar is not in the score)")
        s = got[n][0]
        if len(s.bar_nums) - len(s.bars_x) > (0 if s.ends_at_bar else 1):
            raise CueError(f"{src}: the system of bar {s.bar_no} has more bar numbers than barlines (a false "
                           "barline?): the bar numbers cannot be trusted; check it with partitor bars")
    out: list[list] = []
    for n in range(first, last + 1):
        s, k = got[n]
        if out and out[-1][0] is s and out[-1][2] == k - 1:
            out[-1][2], out[-1][4] = k, n
        else:
            out.append([s, k, k, n, n])
    return [tuple(p) for p in out]


def cue_image(where: dict, n1: int, n2: int, clef: bool) -> CueImg:
    """cue_image -> the cue of the bars n1..n2 of the source: one crop for each stretch of
    one line of the source, joined. where: bar number -> (source line, bar in it, music start)."""
    crops, n = [], n1
    while n <= n2:
        src, k, mx = where[n]
        e = n
        while e + 1 <= n2 and where[e + 1][0] is src and where[e + 1][1] == where[e][1] + 1:
            e += 1
        crops.append(crop_cue(src, k, where[e][1], mx or 0, clef and not crops))
        n = e + 1
    return join_cues(crops)


def apply_cues(strips: list[Strip], starts: list[int | None], specs: list[CueSpec],
               sources: dict[str, tuple[list, dict]], target: str) -> tuple[list[Strip], list[str]]:
    """apply_cues -> (the lines with the bars of each cue split off, warnings). The cue
    itself is drawn later (draw_cues, once the lines have their final width). specs:
    the cues of the part `target`; sources: name -> (its Strip or RestRun per system,
    {id(line): where its music starts}); starts: where the music starts in each line of
    the part. A cue that cannot be placed is left out and named in a warning; it never
    stops the build."""
    warns: list[str] = []
    for spec in specs:
        work = list(strips)
        unsure: list[int] = []
        try:
            if not spec.src:                                   # a text mark: a word at a bar
                work = _text_mark(work, starts, spec, target)
                strips = work
                continue
            items, music = sources[spec.src]
            label = spec.src if spec.label is None else spec.label
            where: dict[int, tuple[Strip, int, int | None]] = {}      # bar number -> (source line, bar in it, its music start)
            for src, k1, k2, n1, n2 in source_pieces(items, spec.first, spec.last, spec.src):
                if len(src.staff_labels) > 1:
                    raise CueError(f"{spec.src} has several staves; a cue takes one")
                mx = music.get(id(src))
                if mx is None and (spec.clef or k1 == 0):
                    raise CueError(f"the clef of {spec.src} in bar {n1} was not found")
                for n in range(n1, n2 + 1):
                    where[n] = (src, k1 + (n - n1), mx)
            # the line of the part that holds each bar; a piece never crosses a line of the part
            anchor = spec.anchor if spec.anchor is not None else None
            if anchor is not None and not spec.first <= anchor <= spec.last:
                raise CueError(f"anchor {anchor} is not in the bars {spec.first}-{spec.last}")
            runs: list[list] = []
            for n in range(spec.first, spec.last + 1):
                t = next((t for t, s in enumerate(work)
                          if find_bar(shown_bars(s, starts[t] or 0), n) is not None), None)
                if t is None:
                    raise CueError(f"bar {n} is not in the systems of {target} (a system with more bar numbers than "
                                   "barlines has none: see partitor bars)")
                if runs and runs[-1][0] == t:
                    runs[-1][2] = n
                else:
                    runs.append([t, n, n])
            for t, m1, m2 in runs:
                bars = shown_bars(work[t], starts[t] or 0)
                a = m2 + 1                                      # the anchor: from here the cue is not matched to the part
                if anchor is not None and m1 <= anchor <= m2:
                    a = anchor
                elif anchor is None or anchor < m1:
                    a = next((n for n in range(m1, m2 + 1) if not bars[find_bar(bars, n)].rest), m2 + 1)
                for n in range(m1, a):                          # the bars the cue covers must rest: they become one rest
                    bar = bars[find_bar(bars, n)]
                    if not bar.rest:
                        raise CueError(f"bar {n}: {target} plays here; a cue needs rests before its anchor")
                    if not bar.certain and n not in unsure:
                        unsure.append(n)
                img = cue_image(where, m1, m2, spec.clef)
                scale = cue_size(spec) * work[t].sp / where[m1][0].sp
                if a > m1:
                    pre = img if a > m2 else cue_image(where, m1, a - 1, spec.clef)
                    s2 = respan(work[t], bars, find_bar(bars, m1), find_bar(bars, a - 1), m1, a - 1, pre, scale)
                else:
                    s2 = work[t]
                pre_w = (starts[t] or 0) - int(s2.staff_x0)
                if spec.align and a > m2:
                    warns.append(f"cue {spec.src} {spec.first}-{spec.last} in {target}: align={spec.align}: "
                                 f"{target} plays in none of these bars; the cue stands where it falls")
                work[t] = dc_replace(s2, cue_todo=[*s2.cue_todo, (img, scale, m1, label, pre_w,
                                                         a - m1 if (spec.fit or spec.sync) and a <= m2 else None,
                                                         spec.sync,
                                                         (a - m1, spec.align) if spec.align and a <= m2 else None)])
        except CueError as e:
            warns.append(f"cue {spec.src} {spec.first}-{spec.last} in {target}: {e}; the cue is left out")
            continue
        if unsure:
            warns.append(f"cue {spec.src} {spec.first}-{spec.last} in {target}: could not confirm that {target} "
                         f"rests in bar {', '.join(str(x) for x in unsure)} (a faint scan): placed on your word, "
                         "check the proof")
        strips = work
    return strips, warns


def pad_cue(cue: CueImg, k: int, extra: int) -> CueImg:
    """pad_cue -> the cue with `extra` columns of bare staff put in bar k, just before its
    barline: the bar gets longer, the notes keep their shape and place, and the bars after it
    move to the right."""
    top, h4 = int(cue.staff_row), int(4 * cue.sp)
    e = int(cue.bars[k])
    ins = e
    while ins > 0 and cue.img[top:top + h4 + 1, ins - 1].mean() > 0.9:      # a thick or double barline
        ins -= 1
    x0 = int(cue.bars[k - 1]) + 1 if k > 0 else int(cue.clef_px)
    ink = cue.img[:, x0:max(x0 + 1, ins)].sum(axis=0)
    col = cue.img[:, x0 + np.argsort(ink, kind="stable")[:5]].any(axis=1)  # the staff lines only
    img = np.concatenate([cue.img[:, :ins], np.repeat(col[:, None], extra, axis=1), cue.img[:, ins:]], axis=1)
    bars = tuple(int(b) + (extra if j >= k else 0) for j, b in enumerate(cue.bars))
    return dc_replace(cue, img=img, bars=bars)


def fill_bar(s: Strip, cue: CueImg, scale: float, number: int, ax: int) -> CueImg:
    """fill_bar -> the cue, its bars under the rest piece that starts at bar `number` (column ax)
    padded when that piece is wider than they are, so that the barline of the cue falls on the
    barline of the part (justify may have widened the piece: a line with no other room)."""
    i = s.bar_nums.index(number) if number in s.bar_nums else -1
    n = s.rest_counts[i] if 0 <= i < len(s.rest_counts) else 0
    if n <= 0 or i >= len(s.bars_x) or n > len(cue.bars):
        return cue
    have = int(s.bars_x[i]) - ax
    want = int(np.ceil((cue.bars[n - 1] + 1 - cue.clef_px) * scale))
    if have - want < 2:
        return cue
    return pad_cue(cue, n - 1, int(round((have - want) / scale)))


def draw_cues(strips: list[Strip]) -> tuple[list[Strip], list[str]]:
    """draw_cues -> (the lines with their cues drawn, warnings): the cues apply_cues
    noted, at the final geometry (after justify and indent)."""
    out, warns = [], []
    for s in strips:
        todo, s = s.cue_todo, dc_replace(s, cue_todo=[])
        for img, scale, number, label, pre_w, fit_from, sync, align in todo:
            i = s.bar_nums.index(number) if number in s.bar_nums else 0
            ax = int(s.bars_x[i - 1]) if i > 0 and s.bars_x else int(s.staff_x0) + pre_w
            try:
                if img is None:
                    s = draw_label(s, ax, label)
                    continue
                img = fill_bar(s, img, scale, number, ax)
                widths = fit_widths(s, number, len(img.bars), fit_from, ax) if fit_from is not None else None
                split = None
                if sync and widths:
                    split, why = sync_split(s, img, number, fit_from, widths, sync)
                    if why:
                        warns.append(f"cue {label} bar {number}: sync={sync}: {why}; the bar is fitted without it")
                start = ax
                if fit_from is None and not (i >= 0 and i < len(s.rest_counts) and s.rest_counts[i] > 0):
                    # a cue over bars the part plays: its clef must not hang out to the left of the staff
                    start = max(ax, int(s.staff_x0) + int(round(img.clef_px * scale)) + 2)
                if align:
                    start, why = align_start(s, img, number, align[0], align[1], scale, start, ax)
                    if why:
                        warns.append(f"cue {label} bar {number}: align={align[1]}: {why}; the cue stands where it falls")
                s, w = draw_cue(s, img, start, scale, label, fit_from, widths, split)
                warns += [f"cue {label} bar {number}: {x}" for x in w]
            except CueError as e:
                warns.append(f"cue {label} bar {number}: {e}; the cue is left out")
        out.append(s)
    return out, warns


def cue_notes(cue: CueImg, k: int) -> list[float]:
    """cue_notes -> the columns of the notes with a stem in bar k of the cue (from 0). The first bar
    starts after the clef and the key (`clef_px`), whose strokes are not notes."""
    edges = [0] + [b + 1 for b in cue.bars]
    x0 = edges[k] if k > 0 else min(int(cue.clef_px), edges[1] - 1)
    return note_xs(cue.img, cue.staff_row, cue.sp, x0, edges[k + 1], tuple(cue.bars))


def align_start(s: Strip, cue: CueImg, number: int, k: int, n: int, scale: float,
                start: int, ax: int) -> tuple[int, str]:
    """align_start -> (the column for the first barline of the cue, "") such that the n-th note with
    a stem of its bar k (counted from the left, as for `sync_split`) stands over the first note with a
    stem of the part in the bar under it, or (start, why) when that cannot be done: the cue keeps
    its size and spacing and only moves sideways. It does not move left of the clef's room at the start
    of the staff, nor right of the end of the line. ax: the left barline of the part's first
    bar of the cue."""
    edges = [0] + [b + 1 for b in cue.bars]
    if k + 1 >= len(edges):
        return start, "the bar of the cue is not there"
    mine = cue_notes(cue, k)
    if len(mine) < n:
        return start, f"the bar of the cue has {len(mine)} note(s) with a stem"
    num = number + k
    if num not in s.bar_nums:
        return start, "the bar of the part is not a bar of its own here"
    j = s.bar_nums.index(num)
    if j >= len(s.bars_x):
        return start, "the bar of the part has no barline after it"
    left, right = (int(s.bars_x[j - 1]) if j > 0 else ax), int(s.bars_x[j])
    theirs = note_xs(s.img & ~s.hdr, s.staff_top, s.sp, left + 1, right, (left, right), PART_ABOVE_SP)
    if not theirs:
        return start, "the part has no note with a stem in its bar"
    new = int(round(theirs[0] - mine[n - 1] * scale + cue.clef_px * scale))
    if new < int(s.staff_x0) + int(round(cue.clef_px * scale)) + 2:
        return start, "the note of the cue stands too far left of the note of the part: the cue would start left of the staff"
    if new - int(round(cue.clef_px * scale)) + int(round(cue.img.shape[1] * scale)) > s.img.shape[1]:
        return start, "the cue would reach past the end of the line"
    return new, ""


def sync_split(s: Strip, cue: CueImg, number: int, fit_from: int, widths: list[int],
               sync: int) -> tuple[tuple[int, int] | None, str]:
    """sync_split -> ((column of the cue, px), "") or (None, why): the sync-th note with a stem of
    the first fitted bar of the cue, and how far from the left barline of the bar of the part
    under it the first note of the part (on its top staff) stands, for `scaled_cue`."""
    edges = [0] + [b + 1 for b in cue.bars]
    mine = cue_notes(cue, fit_from)
    if len(mine) < sync:
        return None, f"the bar of the cue has {len(mine)} note(s) with a stem"
    n = number + fit_from
    if n not in s.bar_nums:
        return None, "the bar of the part is not a bar of its own here"
    j = s.bar_nums.index(n)
    if j == 0 or j >= len(s.bars_x):
        return None, "the bar of the part has no barline before it"
    left, right = int(s.bars_x[j - 1]), int(s.bars_x[j])
    theirs = note_xs(s.img & ~s.hdr, s.staff_top, s.sp, left + 1, right, (left, right), PART_ABOVE_SP)
    if not theirs:
        return None, "the part has no note with a stem in its bar"
    wl = int(round(theirs[0] - (left + 1)))
    if not 0 < wl < widths[0]:
        return None, "the note of the part is too near an edge of its bar"
    return (int(round(mine[sync - 1])), wl), ""


def fit_widths(s: Strip, number: int, nbars: int, fit_from: int, ax: int) -> list[int]:
    """fit_widths -> the widths (px, barline to barline) of the bars of the part under the
    bars of a cue from index fit_from on: the cue has `nbars` bars from bar `number`, the first
    at column ax. It stops at the first bar of the cue that is not a bar of its own in
    this line (the cue goes on at its own width)."""
    out: list[int] = []
    for k in range(fit_from, nbars):
        n = number + k
        if n not in s.bar_nums:
            break
        j = s.bar_nums.index(n)
        if j >= len(s.bars_x) or (s.rest_counts[j:j + 1] and s.rest_counts[j] > 1):
            break
        left = s.bars_x[j - 1] if j > 0 else ax
        out.append(int(s.bars_x[j] - left))
    return out


def _text_mark(work: list[Strip], starts: list[int | None], spec: CueSpec, target: str) -> list[Strip]:
    """_text_mark -> the lines with a word noted at the start of bar spec.first: a rest that
    holds the bar is split so that the bar starts at a barline."""
    n = spec.first
    t = next((t for t, s in enumerate(work)
              if find_bar(shown_bars(s, starts[t] or 0), n) is not None), None)
    if t is None:
        raise CueError(f"bar {n} is not in the systems of {target}")
    bars = shown_bars(work[t], starts[t] or 0)
    i = find_bar(bars, n)
    s2 = work[t]
    if bars[i].rest and (s2.rest_src is not None or bars[i].count > 1):
        s2 = respan(s2, bars, i, i, n, n)
    pre_w = (starts[t] or 0) - int(s2.staff_x0)
    work[t] = dc_replace(s2, cue_todo=[*s2.cue_todo, (None, 0.0, n, spec.label or "", pre_w, None, None, None)])
    return work


def draw_label(s: Strip, ax: int, text: str) -> Strip:
    """draw_label -> the line with a word above its top staff, from column ax, clear of
    the ink there. The room is added at the top when the line has none."""
    fs = CUE_LABEL_SP * s.sp * 1.15
    width = int(len(text) * 0.6 * fs) + 2
    top_rows = int(s.staff_top - 0.3 * s.sp)
    cols = _no_specks(s.img[:top_rows, ax:ax + width] & ~s.hdr[:top_rows, ax:ax + width], s.sp)
    ink = np.flatnonzero(cols.any(axis=1))
    top_ink = int(ink.min()) if ink.size else int(s.staff_top)
    base = min(int(s.staff_top) - int(CUE_CLEAR_SP * s.sp), top_ink - int(0.5 * s.sp))
    for rb in _count_boxes(s):                  # the count of a multi-bar rest
        if rb[2] > ax and rb[0] < ax + width:
            base = min(base, int(rb[1]) - int(0.5 * s.sp))
    short = int(np.ceil(0.9 * fs)) - base
    if short > 0:
        s = pad_top(s, short)
        base += short
    return dc_replace(s, cue_labels=[*s.cue_labels, (float(ax), float(base), fs, text)])


def guess_music_x(s: Strip) -> int | None:
    """guess_music_x -> where the music of a line starts when find_prefixes has no answer (a
    line that keeps its own clef): the middle of the first blank gap
    after the clef (0.15 sp or more), read from the ink outside the staff lines; None when there is none."""
    sl = staff_lines(s)
    if not sl:
        return None
    sp = s.sp
    rows = np.zeros(s.img.shape[0], bool)
    for ln in sl:
        for c in ln:
            rows[int(round(c))] = True
    k = 2 * max(1, int(0.2 * sp)) + 1                   # the thickness of a staff line and its fringe
    rows = cv2.dilate(rows.astype(np.uint8)[:, None], np.ones((k, 1), np.uint8))[:, 0] > 0
    ink = (s.img & ~rows[:, None] & ~s.hdr)[int(s.staff_top - 0.5 * sp):int(s.staff_bottom + 0.5 * sp)].any(axis=0)
    x0 = int(s.staff_x0 + 1.5 * sp)
    x1 = staff_end(s)
    need = max(2, int(0.15 * sp))
    x = x0
    while x < x1:
        if ink[x]:
            x += 1
            continue
        g = x                                           # a blank gap starts here
        while x < x1 and not ink[x]:
            x += 1
        if x - g >= need and x < x1:
            return (g + x) // 2
    return None
