# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""Re-flow of strips: move ink from one system into the previous one."""
from __future__ import annotations

from dataclasses import replace as dc_replace

import cv2
import numpy as np

from .model import Strip


# =============================================================================
# Re-flow (DESIGN.md §4.2 item 2): offered when the print is small
# =============================================================================
REFLOW_MAX_PREFIX_SP = 12.0     # clef + key signature: never wider than this
REFLOW_SAME_SP = 1.2            # lines equal this far past the gap (sp) look like one structure (a longer key)
REFLOW_CLEAR_SP = 2.5           # but a blank this wide after the gap ends the key signature


def _x0(s: Strip) -> int:
    """Staff start in the strip image; a scan's staff can start left of the
    crop (negative staff_x0)."""
    return max(0, s.staff_x0)


def _single(s: Strip) -> bool:
    return abs((s.staff_bottom - s.staff_top) - 4 * s.sp) <= 0.8 * s.sp


def _band(s: Strip) -> np.ndarray:
    """Own ink around the staff (1.5 sp above and below), staff lines
    removed, rows relative to the top line; header text and a system
    barline at the staff start excluded."""
    sp = s.sp
    h = int((s.staff_bottom - s.staff_top) + 3 * sp)
    r0 = int(round(s.staff_top - 1.5 * sp))
    img = s.img & ~s.hdr
    out = np.zeros((h, img.shape[1]), bool)
    a0, a1 = max(0, r0), min(img.shape[0], r0 + h)
    out[a0 - r0:a1 - r0] = img[a0:a1]
    # system barline left of the clef: ink over the whole staff height
    # (measured before the staff lines go)
    x0 = _x0(s)
    t, b = int(1.5 * sp), int(1.5 * sp + (s.staff_bottom - s.staff_top))
    hit = [x for x in range(max(0, x0 - int(0.3 * sp)), min(out.shape[1], x0 + int(0.6 * sp)))
           if out[t:b, x:x + 3].any(axis=1).mean() > 0.6]   # scans: slanted, broken
    # staff lines: long horizontal runs (also on a skewed scan), and their
    # antialiased edges
    u8 = out.astype(np.uint8)
    lines = cv2.morphologyEx(u8, cv2.MORPH_OPEN,
                             np.ones((1, max(3, int(2 * sp))), np.uint8))
    lines = cv2.dilate(lines, np.ones((5, 1), np.uint8)) > 0
    out &= ~lines
    # what is left of a slanted staff line: strokes under 3 px high
    out = cv2.morphologyEx(out.astype(np.uint8), cv2.MORPH_OPEN,
                           np.ones((3, 1), np.uint8)) > 0
    for x in hit:
        out[:, x:x + 3] = False
    return out


def _diverge(a: Strip, b: Strip) -> float:
    """Distance (px, from the staff start) where the music of two lines of
    the same part stops being identical: clef and key signature are the
    same on every line, the first note is not."""
    A, B = _band(a), _band(b)
    h = min(A.shape[0], B.shape[0])
    ax, bx = _x0(a), _x0(b)
    L = int(min(A.shape[1] - ax, B.shape[1] - bx, REFLOW_MAX_PREFIX_SP * 1.6 * a.sp))
    if L <= 0 or h <= 0:
        return 0.0
    sp = a.sp
    m = int(round(0.4 * sp))                 # scans: clefs move a few px
    A = A[:h, ax:ax + L]
    v = max(2, int(round(0.2 * sp)))        # rows +-v
    Bf = np.zeros((h + 2 * v, L + 2 * m), bool)  # B padded: rows +-v, cols +-m
    seg = B[:h, max(0, bx - m):bx + L + m]
    c0 = m - (bx - max(0, bx - m))
    Bf[v:v + h, c0:c0 + seg.shape[1]] = seg
    if A.size == 0 or not Bf.any():
        return 0.0
    t_ = max(5, int(round(0.3 * sp)) | 1)    # +-3 px at 400 dpi; a pitch step is 0.5 sp
    k = np.ones((t_, t_), np.uint8)
    dA = cv2.dilate(A.astype(np.uint8), k) > 0
    w0 = min(L, int(3 * sp))                 # the clef decides the shift
    best, shift = None, (v, m)
    for dy in range(2 * v + 1):
        for dx in range(2 * m + 1):
            Bc = Bf[dy:dy + h, dx:dx + L]
            e = int((A[:, :w0] ^ Bc[:, :w0]).sum())
            if best is None or e < best:
                best, shift = e, (dy, dx)
    B = Bf[shift[0]:shift[0] + h, shift[1]:shift[1] + L]
    dB = cv2.dilate(B.astype(np.uint8), k) > 0
    mis = ((A & ~dB) | (B & ~dA)).sum(axis=0).astype(float)
    win = max(2, int(round(sp)))
    run = np.convolve(mis, np.ones(win), mode="full")[:len(mis) + win - 1]
    hit = np.flatnonzero(run >= 0.3 * sp * sp)   # a hollow note: ~0.5 sp^2
    if not hit.size:
        return float(L)
    j = max(0, int(hit[0]) - win + 1)        # window start
    first = np.flatnonzero(mis[j:j + win] > 0)
    return float(j + (first[0] if first.size else 0))


def _prefix_candidates(s_: Strip, d: float) -> list[float]:
    """Possible prefix ends (px from the staff start) of one line: the start
    of each blank gap (0.3 sp) past the clef, before the line differs from
    the others (d). With no gap at all (time signature touching the clef),
    the point where the line differs."""
    sp = s_.sp
    band = _band(s_)
    cols = band[:, _x0(s_):_x0(s_) + int(d)].any(axis=0)
    gap = max(2, int(0.3 * sp))
    lo, hi = 2.5 * sp, REFLOW_MAX_PREFIX_SP * sp
    out: list[float] = []
    run = 0
    for x in range(len(cols)):
        run = run + 1 if not cols[x] else 0
        if run == gap and x - gap + 1 >= int(lo):
            c = x - gap + 1 + int(0.15 * sp)
            if c <= hi:
                out.append(float(c))
    if not out and lo <= d - 1 <= hi:
        out.append(d - 1)
    return out


def _next_ink(s_: Strip, x: int) -> int:
    """First ink column (px from the staff start) at or after x."""
    band = _band(s_)
    cols = band[:, _x0(s_) + x:].any(axis=0)
    nz = np.flatnonzero(cols)
    return x + int(nz[0]) if nz.size else x + len(cols)


def _staff_set(s: Strip) -> tuple:
    """Names of the staves of a group line (() for a part): lines with
    other staves never share a prefix or a line."""
    return tuple(n for n, _, _ in s.staff_labels) if len(s.staff_labels) > 1 else ()


def _staff_offs(s: Strip) -> tuple:
    """Row of each group staff below the top staff line."""
    return tuple(int(t - s.staff_top) for _, t, _ in s.staff_labels) if len(s.staff_labels) > 1 else ()


def _same_stack(a: Strip, b: Strip) -> bool:
    """Same staves at the same distances (within 0.07 sp): pieces of the two
    lines can stand side by side with their staff lines joined."""
    if _staff_set(a) != _staff_set(b):
        return False
    tol = max(1.0, 0.07 * a.sp)
    return all(abs(x - y) <= tol for x, y in zip(_staff_offs(a), _staff_offs(b)))


def _group_view(s: Strip) -> Strip:
    """_group_view -> a one-staff Strip for the prefix search: the ink around
    each staff of a group line (2 sp above and below), all put on one staff
    (OR). A gap that is blank in the view is blank on every staff; lines
    differ in the view when they differ on any staff."""
    if len(s.staff_labels) < 2:
        return s
    pad = int(round(2 * s.sp))
    h = int(s.staff_labels[0][2] - s.staff_labels[0][1]) + 2 * pad
    img = np.zeros((h, s.img.shape[1]), bool)
    hdr = np.zeros_like(img)
    num = np.zeros_like(img)
    for k, (_, t, b) in enumerate(s.staff_labels):
        a0 = int(t) - pad
        r0, r1 = max(0, a0), min(s.img.shape[0], a0 + h)
        sl = slice(r0 - a0, r1 - a0)
        # the staves' own ink only: the first one keeps the header
        img[sl] |= s.img[r0:r1]
        if k == 0:
            hdr[sl] |= s.hdr[r0:r1]
        if s.num_mask is not None:
            num[sl] |= s.num_mask[r0:r1]
    st = dc_replace(s, img=img, hdr=hdr, num_mask=num if num.any() else None,
                    staff_top=pad, staff_bottom=pad + int(s.staff_labels[0][2] - s.staff_labels[0][1]),
                    staff_labels=[], bracket=False)
    return st


def find_prefixes(strips: list[Strip]) -> list[tuple[int, int] | None]:
    """find_prefixes -> per strip (start, donor) or None.
    start: x (img) where the music of the line's first bar starts; donor:
    the strip whose columns 0..its start are the clef + key signature copied
    to the front of a continuation line. None: the line is never cut.

    Clef and key signature are the same on every line of a movement; the
    first notes are not. The prefix ends at a blank gap (0.3 sp) that at
    least half of the movement's lines (2 or more) have at the same x
    (0.4 sp), the last such gap. A line takes it only when its music
    differs right after the gap (else its key signature can be longer);
    a movement's first line (time signature, range marks) is exempt. A
    line with no such gap (a note close to the clef) keeps its own clef
    in its first bar and borrows the copy from a line of the movement
    that is identical up to that line's prefix. One-line movements give None.
    Group lines (several staves, 0.3.0-dev.34) are searched in a one-staff
    view of all their staves (_group_view); a movement is also split where
    the staves of the lines change, and a line borrows a prefix only from a
    line with the same staves at the same distances."""
    out: list[tuple[int, int] | None] = [None] * len(strips)
    owns: dict[int, int] = {}          # line -> its own prefix end (img px from the staff start)
    orig = strips
    strips = [_group_view(s_) for s_ in orig]
    segs: list[list[int]] = []
    for i, s_ in enumerate(orig):
        if not segs or s_.movement or _staff_set(s_) != _staff_set(orig[segs[-1][-1]]):
            segs.append([i])
        else:
            segs[-1].append(i)
    for seg in segs:
        cand = [i for i in seg if _single(strips[i])]
        if len(cand) < 2:
            continue
        sp = strips[cand[0]].sp
        tol = 0.4 * sp
        cs, dd, f0 = {}, {}, {}
        for i in cand:
            # compared with the 6 nearest lines of the movement (enough for a
            # median; all pairs cost minutes on a long piece)
            near = sorted((j for j in cand if j != i), key=lambda j: abs(j - i))[:6]
            dd[i] = float(np.median([_diverge(strips[i], strips[j]) for j in near]))
            f0[i] = _next_ink(strips[i], 0)   # clef start: steadier than the staff start on scans
            cs[i] = [c - f0[i] for c in _prefix_candidates(strips[i], dd[i])]
        core = [i for i in cand if not strips[i].movement]
        if len(core) < 2:
            core = cand
        need = max(2, (len(core) + 1) // 2)
        allc = sorted({round(x) for i in core for x in cs[i]})
        common = [x for x in allc
                  if sum(any(abs(x - y) <= tol for y in cs[j]) for j in core) >= need]
        if not common:
            continue
        own: dict[int, int] = {}
        for i in cand:
            # the highest common gap this line has (a line may lack the top
            # one: a time signature or a note in another place)
            for X in sorted(common, reverse=True):
                near = [y for y in cs[i] if abs(y - X) <= tol]
                if near:
                    break
            else:
                continue
            y = int(min(near, key=lambda v: abs(v - X)) + f0[i])
            nxt = _next_ink(strips[i], y)
            if not strips[i].movement and dd[i] > nxt + REFLOW_SAME_SP * sp \
               and nxt - y < REFLOW_CLEAR_SP * sp:
                continue                      # same music after the gap: too short
            own[i] = y
        if not own:
            continue
        owns.update(own)
        for i in cand:
            if i in own:
                out[i] = (_x0(strips[i]) + own[i], i)
                continue
            # nearest line with its own prefix that matches this one up to it
            for k in sorted(own, key=lambda k: abs(k - i)):
                if _same_stack(orig[i], orig[k]) \
                   and _diverge(strips[i], strips[k]) >= own[k] - 0.5 * sp:
                    out[i] = (0, k)
                    break
    # A line that stands alone in its segment (a multi-bar rest line on each
    # side splits the movement): it borrows from a line of the same movement
    # with the same staves, by the same test.
    mv, m = [], 0
    for s_ in orig:
        m += 1 if s_.movement else 0
        mv.append(m)
    for i, s_ in enumerate(orig):
        if out[i] is not None or s_.rest_src is not None or not _single(strips[i]):
            continue
        for k in sorted(owns, key=lambda k: abs(k - i)):
            if mv[k] == mv[i] and _same_stack(orig[i], orig[k]) \
               and _diverge(strips[i], strips[k]) >= owns[k] - 0.5 * s_.sp:
                out[i] = (0, k)
                break
    return out


def _break_lines(widths: list[float], pre: float, W: float) -> list[int]:
    """Balanced line breaks: bar widths, prefix width, line width -> the
    index of the first bar of each line. Minimises the squared slack of
    every line but the last (a single bar wider than a line stands alone)."""
    n = len(widths)
    best = [0.0] + [float("inf")] * n
    prev = [0] * (n + 1)
    for j in range(1, n + 1):
        tot = pre
        for i in range(j, 0, -1):
            tot += widths[i - 1]
            if tot > W and i < j:
                break
            cost = 0.0 if j == n else (max(0.0, W - tot)) ** 2
            if best[i - 1] + cost < best[j]:
                best[j] = best[i - 1] + cost
                prev[j] = i - 1
    starts, j = [], n
    while j > 0:
        starts.append(prev[j])
        j = prev[j]
    return sorted(starts)


def _compose(pieces: list[tuple[Strip, int, int, bool]]) -> tuple[np.ndarray, np.ndarray, int]:
    """Join crops of strips side by side, aligned on the top staff line.
    pieces: (strip, x0, x1, keep header). -> (img, hdr, staff_top row)."""
    above = max(p[0].staff_top for p in pieces)
    below = max(p[0].img.shape[0] - p[0].staff_top for p in pieces)
    width = sum(p[2] - p[1] for p in pieces)
    img = np.zeros((above + below, width), bool)
    hdr = np.zeros_like(img)
    x = 0
    for s_, x0, x1, keep in pieces:
        y = above - s_.staff_top
        src, hsrc = s_.img, s_.hdr
        if s_.num_mask is not None:          # printed numbers: wrong place once re-flowed
            src, hsrc = src & ~s_.num_mask, hsrc & ~s_.num_mask
        part = src[:, x0:x1]
        hpart = hsrc[:, x0:x1]
        if not keep:
            part = part & ~hpart
            hpart = np.zeros_like(hpart)
        img[y:y + part.shape[0], x:x + part.shape[1]] |= part
        hdr[y:y + part.shape[0], x:x + part.shape[1]] |= hpart
        x += x1 - x0
    return img, hdr, above


def reflow(strips: list[Strip], W: float, pre: list | None = None) -> list[Strip]:
    """reflow -> new lines no wider than W (px, where possible), cut only
    at barlines. A continuation line starts with a copy of the clef and key
    signature of its source line (header text not copied). Lines that
    cannot be cut safely (no prefix found, not ending at a barline, two
    staves) stay whole. A movement always starts a new line; bars of two
    source lines join only when their prefixes are the same."""
    pre = find_prefixes(strips) if pre is None else pre
    bw = lambda s_: max(1, int(0.2 * s_.sp))         # barline width kept left
    units: list[list] = []        # runs of bars that may share lines
    for i, s_ in enumerate(strips):
        cut = pre[i] is not None and s_.ends_at_bar and len(s_.bars_x) >= 2
        cw = lambda j: pre[pre[j][1]][0]                # copy width of line j
        if not cut:
            units.append([("whole", i)])
            continue
        # a line with a borrowed prefix keeps its own clef in its first
        # bar: that bar must start a line
        same = (units and units[-1][0][0] == "bar" and not s_.movement
                and pre[i][0] > 0)
        if same:
            j = units[-1][-1][1]
            dj, di = pre[j][1], pre[i][1]
            if abs((cw(j) - _x0(strips[dj])) - (cw(i) - _x0(strips[di]))) > 0.5 * s_.sp \
               or _diverge(_group_view(strips[dj]), _group_view(strips[di])) \
               < (cw(i) - _x0(strips[di])) - 0.5 * s_.sp \
               or not _same_stack(strips[j], s_):
                same = False
        if not same:
            units.append([])
        for b in range(len(s_.bars_x)):
            units[-1].append(("bar", i, b))
    out: list[Strip] = []
    for unit in units:
        if unit[0][0] == "whole":
            out.append(strips[unit[0][1]])
            continue
        bars = [(t[1], t[2]) for t in unit]

        def span(i, b):
            s_ = strips[i]
            x0 = pre[i][0] if b == 0 else s_.bars_x[b - 1] + bw(s_)
            if b == len(s_.bars_x) - 1:              # line end: whole final/repeat barline
                return x0, s_.img.shape[1]
            x1 = min(s_.img.shape[1], s_.bars_x[b] + bw(s_))
            return x0, x1
        widths = [span(i, b)[1] - span(i, b)[0] for i, b in bars]
        i0 = bars[0][0]
        starts = _break_lines(widths, pre[pre[i0][1]][0], W)
        for k, a in enumerate(starts):
            z = starts[k + 1] if k + 1 < len(starts) else len(bars)
            i, b = bars[a]
            s_ = strips[i]
            if b == 0:                               # real start: own clef, header
                pieces = [(s_, 0, pre[i][0], True)] if pre[i][0] > 0 else []
            else:                                    # continuation: copied clef + key
                k_ = pre[i][1]
                pieces = [(strips[k_], 0, pre[k_][0], False)]
            for ii, bb in bars[a:z]:
                x0, x1 = span(ii, bb)
                pieces.append((strips[ii], x0, x1, True))
            img, hdr, top = _compose(pieces)
            # rehearsal marks move with their bars: a mark stands at the
            # barline before its bar (or the line start for bar 0); a copied
            # prefix carries none
            marks, x = [], 0
            for n_, (ps, x0, x1, keep) in enumerate(pieces):
                lo = x0 - 2 * bw(ps) if n_ > 0 else 0
                hi = x1 - 2 * bw(ps)
                if n_ > 0 or keep:
                    for mx, t in ps.marks:
                        if (lo <= mx < hi) and not (n_ == 0 and mx >= x1):
                            marks.append((x + max(0, mx - x0), t))
                x += x1 - x0
            if b < len(s_.bar_nums):
                num = s_.bar_nums[b]
            elif s_.bar_no is not None:
                num = s_.bar_no + b
            else:
                num = None
            first_of_mvt = s_.movement and b == 0
            show = None if (first_of_mvt or num is None or num < 1) else num
            line = Strip(img, s_.staff_x0, top, top + (s_.staff_bottom - s_.staff_top),
                         s_.sp, hdr, show, s_.bar_raise, s_.bar_size,
                         marks=sorted(set(marks)), movement=first_of_mvt,
                         bracket=s_.bracket,
                         staff_labels=[(n, t - s_.staff_top + top, b - s_.staff_top + top)
                                       for n, t, b in s_.staff_labels])
            out.append(line)
    return out


def whole_reason(s_: Strip, p) -> str:
    """whole_reason -> why re-flow keeps a line whole ('' when it is cut)."""
    if s_.rest_src is not None:
        return "multi-bar rest"
    if not s_.ends_at_bar:
        gap = f" (last barline {s_.end_gap_sp:.1f} sp before the staff end)" if s_.end_gap_sp >= 0 else ""
        return s_.bars_why or "the line does not end at a barline" + gap
    if len(s_.bars_x) < 2:
        return s_.bars_why or "one bar"
    if p is None:
        return "no clef and key prefix found"
    return ""


def reflow_report(strips: list[Strip], pre: list) -> str:
    """reflow_report -> one text line for the build: how many lines can be
    cut, the reasons for the others, and the widest line that stays whole
    (it sets the largest staff re-flow can reach)."""
    why = [whole_reason(s_, pre[i]) for i, s_ in enumerate(strips)]
    whole = [i for i, w in enumerate(why) if w]
    kinds: dict[str, int] = {}
    for i in whole:
        kinds[why[i]] = kinds.get(why[i], 0) + 1
    txt = f"re-flow: {len(strips) - len(whole)} of {len(strips)} lines can be cut"
    if not whole:
        return txt
    txt += "; whole: " + ", ".join(f"{n} {k}" for k, n in sorted(kinds.items(), key=lambda t: -t[1]))
    sp = strips[0].sp
    w = max((i for i in whole if strips[i].rest_src is None),
            key=lambda i: strips[i].img.shape[1], default=None)
    if w is not None:
        txt += (f"; widest whole line {strips[w].img.shape[1] / sp:.0f} sp "
                f"(line {w + 1}: {why[w]})")
    return txt


def reflow_caps(strips: list[Strip], pre: list | None = None) -> float:
    """Widest piece that can never be cut (px): a whole line that stays
    whole, or prefix + the widest bar. The line width may not be smaller."""
    pre = find_prefixes(strips) if pre is None else pre
    widest = 0.0
    for i, s_ in enumerate(strips):
        if pre[i] is None or not s_.ends_at_bar or len(s_.bars_x) < 2:
            widest = max(widest, s_.img.shape[1])
        else:
            edges = [pre[i][0]] + s_.bars_x
            copy = pre[pre[i][1]][0]
            widest = max(widest, pre[i][0] + edges[1] - edges[0],
                         copy + max(b - a for a, b in zip(edges[1:], edges[2:])))
    return widest
