# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""Re-flow of strips: move ink from one system into the previous one."""
from __future__ import annotations

import itertools
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
REFLOW_STACK_SP = 0.3           # a line borrows a prefix from a line whose staves lie this close (sp); the copy is moved to fit
REFLOW_AGREE_CLEF_SP = 2.4      # structure match (0.8.32): the clef is not compared (a scan blots it); the key signature after it is
REFLOW_AGREE_TAIL_SP = 0.8      # ... up to this far past the donor's prefix end
REFLOW_AGREE_MAX_SP2 = 0.8      # mismatch on any one staff, sp^2: equal keys on blotchy scans <= 0.65, an accidental missing or added >= 0.84
REFLOW_AGREE_INK = 0.4          # and the smaller ink of the two lines over the larger: equal keys >= 0.64, an accidental missing <= 0.04


def _x0(s: Strip) -> int:
    """Staff start in the strip image; a scan's staff can start left of the
    crop (negative staff_x0)."""
    return max(0, s.staff_x0)


def _single(s: Strip) -> bool:
    return abs((s.staff_bottom - s.staff_top) - 4 * s.sp) <= 0.8 * s.sp


# find_prefixes compares each line with its neighbours many times; while it runs, the band of a
# line is made once (0.8.34). id(strip) -> (strip, band); the strip is kept, so no id is reused.
_BAND_MEMO: dict = {}


def _band(s: Strip) -> np.ndarray:
    """_band -> _band_now(s); inside find_prefixes, made once per strip (read-only array)."""
    if not _BAND_MEMO.get("on"):
        return _band_now(s)
    hit = _BAND_MEMO.get(id(s))
    if hit is not None and hit[0] is s:
        return hit[1]
    out = _band_now(s)
    out.flags.writeable = False
    _BAND_MEMO[id(s)] = (s, out)
    return out


def _band_now(s: Strip) -> np.ndarray:
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


def _aligned_bands(a: Strip, b: Strip, cap_px: float):
    """_aligned_bands -> (A, B, k) or None: the own ink (_band) of two lines over the
    first L px from the staff start (L at most cap_px), B moved onto A by the clef
    (scans: clefs move a few px); k is the dilation kernel (about 0.3 sp). None:
    nothing to compare."""
    A, B = _band(a), _band(b)
    h = min(A.shape[0], B.shape[0])
    ax, bx = _x0(a), _x0(b)
    L = int(min(A.shape[1] - ax, B.shape[1] - bx, cap_px))
    if L <= 0 or h <= 0:
        return None
    sp = a.sp
    m = int(round(0.4 * sp))                 # scans: clefs move a few px
    A = A[:h, ax:ax + L]
    v = max(2, int(round(0.2 * sp)))        # rows +-v
    Bf = np.zeros((h + 2 * v, L + 2 * m), bool)  # B padded: rows +-v, cols +-m
    seg = B[:h, max(0, bx - m):bx + L + m]
    c0 = m - (bx - max(0, bx - m))
    Bf[v:v + h, c0:c0 + seg.shape[1]] = seg
    if A.size == 0 or not Bf.any():
        return None
    t_ = max(5, int(round(0.3 * sp)) | 1)    # +-3 px at 400 dpi; a pitch step is 0.5 sp
    k = np.ones((t_, t_), np.uint8)
    w0 = min(L, int(3 * sp))                 # the clef decides the shift
    best, shift = None, (v, m)
    for dy in range(2 * v + 1):
        for dx in range(2 * m + 1):
            Bc = Bf[dy:dy + h, dx:dx + L]
            e = int((A[:, :w0] ^ Bc[:, :w0]).sum())
            if best is None or e < best:
                best, shift = e, (dy, dx)
    return A, Bf[shift[0]:shift[0] + h, shift[1]:shift[1] + L], k


def _diverge(a: Strip, b: Strip) -> float:
    """Distance (px, from the staff start) where the music of two lines of
    the same part stops being identical: clef and key signature are the
    same on every line, the first note is not."""
    got = _aligned_bands(a, b, REFLOW_MAX_PREFIX_SP * 1.6 * a.sp)
    if got is None:
        return 0.0
    A, B, k = got
    sp = a.sp
    L = A.shape[1]
    dA = cv2.dilate(A.astype(np.uint8), k) > 0
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


def _same_stack(a: Strip, b: Strip, tol_sp: float = 0.07) -> bool:
    """Same staves at the same distances (within tol_sp, 0.07 sp unless said):
    pieces of the two lines can stand side by side with their staff lines
    joined."""
    if _staff_set(a) != _staff_set(b):
        return False
    tol = max(1.0, tol_sp * a.sp)
    return all(abs(x - y) <= tol for x, y in zip(_staff_offs(a), _staff_offs(b)))


def _restack(donor: Strip, target: Strip) -> Strip:
    """_restack -> the donor with each staff of a group moved up or down to the
    row it has in target (the lines of one scan lie a few px apart), so that
    the copied clef and key meet the music of target with the staff lines
    joined. The donor itself when the two stacks are the same already."""
    if _same_stack(donor, target):
        return donor
    h = donor.img.shape[0]
    lab = donor.staff_labels
    cuts = [0] + [(lab[m - 1][2] + lab[m][1]) // 2 for m in range(1, len(lab))] + [h]
    move = [t_ - d_ for t_, d_ in zip(_staff_offs(target), _staff_offs(donor))]

    def shift(a):
        out = np.zeros_like(a)
        for m, dy in enumerate(move):
            r0, r1 = int(cuts[m]), int(cuts[m + 1])
            a0, a1 = max(0, r0 + dy), min(h, r1 + dy)
            if a1 > a0:
                out[a0:a1] = a[a0 - dy:a1 - dy]
        return out
    num = None if donor.num_mask is None else shift(donor.num_mask)
    return dc_replace(donor, img=shift(donor.img), hdr=shift(donor.hdr), num_mask=num)


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


def _staff_view(s: Strip, m: int) -> Strip:
    """_staff_view -> a one-staff Strip of staff m of a group line (the ink around
    that staff, 2 sp above and below); the line itself when it has one staff."""
    if len(s.staff_labels) < 2:
        return s
    pad = int(round(2 * s.sp))
    _, t, b = s.staff_labels[m]
    h = int(b - t) + 2 * pad
    a0 = int(t) - pad
    r0, r1 = max(0, a0), min(s.img.shape[0], a0 + h)

    def cut(a):
        out = np.zeros((h, s.img.shape[1]), bool)
        out[r0 - a0:r1 - a0] = a[r0:r1]
        return out
    return dc_replace(s, img=cut(s.img), hdr=cut(s.hdr), num_mask=None, staff_top=pad,
                      staff_bottom=pad + int(b - t), staff_labels=[], bracket=False)


def _prefix_agrees(a: Strip, b: Strip, plen: float) -> bool:
    """_prefix_agrees -> True when the key signature of line a is that of line b, staff
    by staff, although the pixels of the clef are not (a faded or dotted scan blots the
    clef, so the exact test of _diverge stops after a few px). The ink between
    REFLOW_AGREE_CLEF_SP and the donor's prefix end plen (plus a tail) is compared,
    within the tolerance of _aligned_bands (about 0.3 sp). On every staff the mismatch
    must stay under REFLOW_AGREE_MAX_SP2 (sp^2) and the two lines must hold about the
    same amount of ink (REFLOW_AGREE_INK): an accidental missing or added fails both. The
    same staves are needed on both lines. Fitted on two faded scans (tests, DESIGN.md §4.2)."""
    if len(a.staff_labels) != len(b.staff_labels):
        return False
    sp = a.sp
    x0 = int(REFLOW_AGREE_CLEF_SP * sp)
    for m in range(max(1, len(a.staff_labels))):
        got = _aligned_bands(_staff_view(a, m), _staff_view(b, m), plen + REFLOW_AGREE_TAIL_SP * sp)
        if got is None or got[0].shape[1] <= x0:
            return False
        A, B, k = got
        dA, dB = cv2.dilate(A.astype(np.uint8), k) > 0, cv2.dilate(B.astype(np.uint8), k) > 0
        mis = ((A & ~dB) | (B & ~dA))[:, x0:].sum() / (sp * sp)
        ia, ib = int(A[:, x0:].sum()), int(B[:, x0:].sum())
        if mis > REFLOW_AGREE_MAX_SP2 or min(ia, ib) < REFLOW_AGREE_INK * max(ia, ib):
            return False
    return True


class _Prefixes(list):
    """The result of find_prefixes. borrowed: {line: donor line} for the lines that
    took the prefix of a donor by the structure match (_prefix_agrees)."""
    borrowed: dict


def find_prefixes(strips: list[Strip]) -> _Prefixes:
    """find_prefixes -> _find_prefixes(strips), with the band of each line made once
    (_BAND_MEMO; the same result, 0.8.34)."""
    _BAND_MEMO.clear()
    _BAND_MEMO["on"] = True
    try:
        return _find_prefixes(strips)
    finally:
        _BAND_MEMO.clear()


def _find_prefixes(strips: list[Strip]) -> _Prefixes:
    """_find_prefixes -> per strip (start, donor) or None.
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
    line with the same staves at distances within REFLOW_STACK_SP (0.3 sp);
    reflow() moves the copy to the rows of the line that takes it."""
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
                if _same_stack(orig[i], orig[k], REFLOW_STACK_SP) \
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
            if mv[k] == mv[i] and _same_stack(orig[i], orig[k], REFLOW_STACK_SP) \
               and _diverge(strips[i], strips[k]) >= owns[k] - 0.5 * s_.sp:
                out[i] = (0, k)
                break
    # Structure match (0.8.32): a line whose clef is blotted (faded or dotted scan) has no
    # prefix gap and does not match any line pixel for pixel. It takes the prefix of the
    # nearest lines of its own segment (same staves, no rest line between) when its key
    # signature agrees with every one of the two nearest, staff by staff. A key change,
    # or a donor that disagrees, leaves the line whole (the build and `plan` say so).
    segof = {i: n for n, seg in enumerate(segs) for i in seg}
    res = _Prefixes(out)
    res.borrowed = {}
    for i, s_ in enumerate(orig):
        if out[i] is not None or s_.rest_src is not None or not _single(strips[i]):
            continue
        donors = [k for k in sorted(owns, key=lambda k: abs(k - i))
                  if segof[k] == segof[i] and _same_stack(s_, orig[k], REFLOW_STACK_SP)][:2]
        if donors and all(_prefix_agrees(s_, orig[k], owns[k]) for k in donors):
            res[i] = (0, donors[0])
            res.borrowed[i] = donors[0]
    return res


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


# =============================================================================
# Multi-bar rest measure drawn over a span of a line
# =============================================================================
REST_BAR_SP = 26.0      # width of a multi-bar rest (H-bar) measure
# H-bar look (layout key `rest_bar`): (bar thickness sp, serif thickness sp, first and last staff
# line the serif spans (0 = top line, 4 = bottom line), least serif width px). `engraved` follows
# Bravura's restHBar (SMuFL): a thick bar, thin serifs from line 2 to line 4.
REST_BAR_STYLES = {"engraved": (1.0, 0.16, 1, 3, 2),
                   "bold": (1.0, 0.35, 0, 4, 3),
                   "heavy": (0.9, 0.5, 0, 4, 4)}       # the look of 0.8.11 to 0.8.30
REST_BAR_DEFAULT = "engraved"
MERGE_EDGE_SP = 0.8     # clear of the barlines (sp)
MERGE_SAVE_SP = 3.0     # a merge must save this much width (sp)
MERGE_MIN_SP = 8.0      # narrowest merged measure (sp)


def draw_hbar(img: np.ndarray, top: int, a: int, b: int, sp: float, style: str = REST_BAR_DEFAULT) -> None:
    """draw_hbar -> nothing; draws in img the H-bar of one staff from column a to
    column b: the bar on the middle line, a serif at each end. top: the row of the
    top line. style: a key of REST_BAR_STYLES (an unknown one draws the default)."""
    bt, st, k0, k1, least = REST_BAR_STYLES.get(style) or REST_BAR_STYLES[REST_BAR_DEFAULT]
    th = max(1, int(round(0.1 * sp)))
    mid = top + int(round(2 * sp))
    half = int(bt / 2 * sp)
    img[max(0, mid - half):mid + half + 1, a:b] = True
    sw = max(least, int(round(st * sp)))
    for xx in (a, b - sw):
        img[top + int(round(k0 * sp)):top + int(round(k1 * sp)) + th, xx:xx + sw] = True


def rest_bar_block(img: np.ndarray, xa: int, xb: int, tops: list[int], sp: float,
                   style: str = REST_BAR_DEFAULT) -> np.ndarray | None:
    """rest_bar_block -> the columns of one multi-bar rest measure (an H-bar on
    each staff, serifs at both ends, see draw_hbar) that replace img[:, xa:xb], or
    None when the measure would save less than MERGE_SAVE_SP. The staff lines come
    from the column of img near xa. tops: the row of the top line of each staff."""
    orig = xb - xa
    w = int(max(MERGE_MIN_SP * sp, min(REST_BAR_SP * sp, 0.85 * orig)))
    if orig - w < MERGE_SAVE_SP * sp:
        return None
    col = img[:, min(xb - 1, xa + int(sp))].copy()      # staff lines only
    block = np.repeat(col[:, None], w, axis=1)
    for t in tops:
        draw_hbar(block, t, int(2 * sp), w - int(2 * sp), sp, style)
    return block


def _starts_with_rest(s: Strip) -> bool:
    """_starts_with_rest -> True when the first bar of a line is a merged multi-bar
    rest. The left bracket of its H-bar stands at the end of the line's prefix
    (find_prefixes puts the gap after it), so the prefix is not a clean clef and
    key: copied to another line, it brings the bracket."""
    return bool(s.rest_labels) and bool(s.rest_counts) and s.rest_counts[0] > 1


def _join_rests(img: np.ndarray, hdr: np.ndarray, marks: list, labels: list,
                bars: list[tuple[int, int, int, int]], sp: float, top: int, bw: int,
                skip_first: bool, style: str = REST_BAR_DEFAULT) -> tuple[np.ndarray, np.ndarray, list, list]:
    """_join_rests -> (img, hdr, marks, labels) of a re-flowed line where each
    run of bars that hold only rests, and that come from two or more source
    lines, is one multi-bar rest: the two multi-bar rests that touch where two
    source lines meet ("2" and "6") become one ("8"). Runs inside one source line
    were merged already (merge_rest_bars). bars: per bar of the line (x0, x1,
    bars of rest it holds (0: it has notes), source line); x0 is where the
    bar starts, after its left barline; x1 is after its right barline. top: the
    row of the top staff line. skip_first: the first bar has its own clef; a run
    that starts there stays as it is. A run with no multi-bar rest among its bars
    (the staff rows are unknown) or with no saving stays as it is."""
    e = int(MERGE_EDGE_SP * sp)
    runs, cur = [], []
    for k, b in enumerate(bars):
        if b[2] > 0:
            cur.append(k)
        else:
            runs.append(cur)
            cur = []
    runs.append(cur)
    for run in reversed(runs):
        if len(run) < 2 or len({bars[k][3] for k in run}) < 2 or (skip_first and run[0] == 0):
            continue
        x0, x1 = bars[run[0]][0], bars[run[-1]][1]
        rows = sorted({r for cx, _, r in labels if x0 <= cx < x1})
        xa = x0 if run[0] == 0 else x0 - bw + e         # clear of the barline before the run
        xb = x1 - bw - e                                # and of the barline after it
        if not rows or xb <= xa:
            continue
        block = rest_bar_block(img, xa, xb, [int(round(top + r)) for r in rows], sp, style)
        if block is None:
            continue
        w, delta = block.shape[1], block.shape[1] - (xb - xa)
        n = sum(bars[k][2] for k in run)
        img = np.concatenate([img[:, :xa], block, img[:, xb:]], axis=1)
        hdr = np.concatenate([hdr[:, :xa], np.zeros((hdr.shape[0], w), bool), hdr[:, xb:]], axis=1)
        marks = [(mx if mx < xa else mx + delta, t) for mx, t in marks]
        labels = [(cx if cx < xa else cx + delta, *rest) for cx, *rest in labels if not xa <= cx < xb]
        labels += [(xa + w / 2.0, str(n), r) for r in rows]
        labels.sort()
    return img, hdr, marks, labels


def reflow(strips: list[Strip], W: float, pre: list | None = None) -> list[Strip]:
    """reflow -> new lines no wider than W (px, where possible), cut only
    at barlines. A continuation line starts with a copy of the clef and key
    signature of its source line (header text not copied). Lines that
    cannot be cut safely (no prefix found, not ending at a barline, two
    staves) stay whole. A movement always starts a new line; bars of two
    source lines join only when their prefixes are the same."""
    pre = find_prefixes(strips) if pre is None else pre
    bw = lambda s_: max(1, int(0.2 * s_.sp))         # barline width kept left
    donors: dict[int, int] = {}

    def donor(j: int) -> int:
        """The line whose clef and key a continuation of line j copies: the
        donor of find_prefixes, unless that line starts with a multi-bar rest
        (its prefix holds the left bracket of the H-bar). Then the nearest line of
        the same movement and staves with its own prefix and no such rest."""
        if j not in donors:
            k = pre[j][1]
            if _starts_with_rest(strips[k]):
                sp_ = strips[k].sp
                for q in sorted((q for q in range(len(strips)) if pre[q] is not None and pre[q][1] == q
                                 and not _starts_with_rest(strips[q])), key=lambda q: abs(q - j)):
                    lo, hi = min(q, j), max(q, j)
                    if any(strips[m].movement for m in range(lo + 1, hi + 1)):
                        break                            # a movement lies between: nothing nearer is the same
                    if _same_stack(strips[q], strips[k], REFLOW_STACK_SP) \
                       and _diverge(_group_view(strips[q]), _group_view(strips[k])) \
                       >= (pre[q][0] - _x0(strips[q])) - 0.5 * sp_:
                        k = q
                        break
            donors[j] = k
        return donors[j]
    units: list[list] = []        # runs of bars that may share lines
    for i, s_ in enumerate(strips):
        cut = pre[i] is not None and s_.ends_at_bar and len(s_.bars_x) >= 2
        cw = lambda j: pre[donor(j)][0]                 # copy width of line j
        if not cut:
            units.append([("whole", i)])
            continue
        # a line with a borrowed prefix keeps its own clef in its first
        # bar: that bar must start a line
        same = (units and units[-1][0][0] == "bar" and not s_.movement
                and pre[i][0] > 0)
        if same:
            j = units[-1][-1][1]
            dj, di = donor(j), donor(i)
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
                return x0, max(x0, s_.img.shape[1])
            x1 = min(s_.img.shape[1], s_.bars_x[b] + bw(s_))
            return x0, max(x0, x1)       # a barline inside the prefix: a bar with no width, not a negative one
        widths = [span(i, b)[1] - span(i, b)[0] for i, b in bars]
        i0 = bars[0][0]
        starts = _break_lines(widths, pre[donor(i0)][0], W)
        for k, a in enumerate(starts):
            z = starts[k + 1] if k + 1 < len(starts) else len(bars)
            i, b = bars[a]
            s_ = strips[i]
            if b == 0:                               # real start: own clef, header
                pieces = [(s_, 0, pre[i][0], True)] if pre[i][0] > 0 else []
            else:                                    # continuation: copied clef + key
                k_ = donor(i)
                pieces = [(_restack(strips[k_], s_), 0, pre[k_][0], False)]
            for ii, bb in bars[a:z]:
                x0, x1 = span(ii, bb)
                pieces.append((strips[ii], x0, x1, True))
            img, hdr, top = _compose(pieces)
            # rehearsal marks move with their bars: a mark stands at the
            # barline before its bar (or the line start for bar 0); a copied
            # prefix carries none
            marks, labels, x = [], [], 0
            for n_, (ps, x0, x1, keep) in enumerate(pieces):
                lo = x0 - 2 * bw(ps) if n_ > 0 else 0
                hi = x1 - 2 * bw(ps)
                if n_ > 0 or keep:
                    for mx, t in ps.marks:
                        if (lo <= mx < hi) and not (n_ == 0 and mx >= x1):
                            marks.append((x + max(0, mx - x0), t))
                    for cx, *rest in ps.rest_labels:     # the count of a merged rest moves with its bar
                        if x0 <= cx < x1:
                            labels.append((x + cx - x0, *rest))
                x += x1 - x0
            rc = [strips[ii].rest_counts[bb] if bb < len(strips[ii].rest_counts) else 0
                  for ii, bb in bars[a:z]]          # a rest at the start and at the end of the line
            xs = list(itertools.accumulate((p[2] - p[1] for p in pieces), initial=0))
            n_pre = len(pieces) - len(rc)
            img, hdr, marks, labels = _join_rests(
                img, hdr, marks, labels,
                [(xs[n_pre + k], xs[n_pre + k + 1], c, bars[a + k][0]) for k, c in enumerate(rc)],
                s_.sp, top, bw(s_), skip_first=(b == 0), style=s_.rest_bar)
            if b < len(s_.bar_nums):
                num = s_.bar_nums[b]
            elif s_.bar_no is not None:
                num = s_.bar_no + b
            else:
                num = None
            first_of_mvt = s_.movement and b == 0
            show = None if (first_of_mvt or num is None or num < 1) else num
            r_in = sum(itertools.takewhile(lambda v: v > 0, rc))
            r_out = sum(itertools.takewhile(lambda v: v > 0, reversed(rc)))
            line = Strip(img, s_.staff_x0, top, top + (s_.staff_bottom - s_.staff_top),
                         s_.sp, hdr, show, s_.bar_raise, s_.bar_size,
                         rest_bar=s_.rest_bar,
                         marks=sorted(set(marks)), rest_labels=sorted(labels),
                         rest_in=r_in, rest_out=r_out,
                         movement=first_of_mvt,
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
