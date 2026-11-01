# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""Ink ownership, safety gate and barline detection for one page."""
from __future__ import annotations

import re

import cv2
import numpy as np
import pymupdf

from . import config
from .clef import clef_signature, note_steps
from .config import (
    BAND_MARGIN, BARNUM_ZONE_SP, BRACKET_MAX_SP, BRACKET_ZONE_SP, CHAIN_SP, CLOSE_SP,
    DISCARD_NAMES, DUST_AREA_SP2, D_BARNUM, D_BRACKET, D_CONNECTOR, D_EDGE, D_FOOTER, D_HEADER,
    D_LABEL, D_NOISE, D_NOMUSIC, EDGE_LEFT_SP, EDGE_RIGHT_SP, FOOTER_TEXT_SP, GATE_CLASSES,
    GROUP_GAP_SP, LABEL_ABOVE_SP, NOISE_AREA_SP2, OWN_DISCARD, OWN_HEADER_BASE, OWN_NONE,
    PAGE_FOOTER_SP, SP_MAX_PX, SP_MIN_PX, TEXT_ABOVE_FRAC, TEXT_REVIEW_FRAC, THIN_VERTICAL_SP,
)
from .model import PageResult, Staff
from .vision import (
    binarize, clean_label, clean_title, detect_staves, dewarp, estimate_skew, flatten,
    group_systems, is_cue_text, is_footer_text, looks_like_text, ocr_line, read_text,
    render_page, rotate, run_lengths, staff_tracks, text_in_rect,
)


# =============================================================================
# Ownership
# =============================================================================
DOTTED_MIN_SP = 6.0       # least distance from the staff start of a barline known only from


def detect_barlines(owner: np.ndarray, conn: np.ndarray, ink: np.ndarray,
                    staves: list[Staff], idxs: list[int], sp: float,
                    thick: int, dotted_out: list[int] | None = None) -> list[int]:
    """detect_barlines -> x of the barlines in one system (system start
    excluded), left to right. dotted_out (when given) receives the x of the
    barlines found by (D) only: Mensurstriche, drawn in the gaps.

    Evidence: (C) connector pixels in a gap between two staves (barlines
    through the system); (D) a thin column at least 45% ink across a gap,
    with ink in its top and bottom fifth, broken (longest run under 60% of
    the gap: a stem is one stroke and touches one side), at one x in 2+
    gaps (dotted Mensurstriche in scans; with one gap
    only, together with B); (B) a thin column
    of the staff's own ink covering 92% of the staff height, with no ink
    0.25-0.6 sp on both sides inside the staff (a stem has its notehead
    on one side). A position is kept with (C), or (D), or with (B) on at least
    half of the staves (one staff: that staff). Positions within 0.8 sp
    merge (double bars, repeat signs). Nothing within 3.5 sp of the staff
    start counts: that is the clef zone (a C clef has two vertical bars).
    Dotted evidence (D) alone needs 6 sp: the tails of stacked G clefs
    reach into the gaps at one x and look like Mensurstriche (Schein Nun
    p4.s1: a false bar at 3.65 sp counted a bar too many)."""
    pts: list[tuple[float, str]] = []
    sts = [staves[i] for i in idxs]
    x0 = min(s.x0 for s in sts)
    x1 = max(s.x1 for s in sts)
    ngaps = 0
    for gi, (a, b) in enumerate(zip(sts, sts[1:])):
        g0, g1 = int(a.bottom + thick) + 1, int(b.top - thick) - 1
        if g1 <= g0:
            continue
        ngaps += 1
        seg = ink[g0:g1, x0:x1 + 1]
        e = max(1, (g1 - g0) // 5)                 # spans the gap: ink in
        spans = seg[:e].any(axis=0) & seg[-e:].any(axis=0)   # top and bottom fifth
        dot = (seg.mean(axis=0) >= 0.45) & spans
        for c in np.flatnonzero(dot):              # broken, not one stroke
            col = np.concatenate(([0], seg[:, c].astype(np.int8), [0]))
            dd = np.diff(col)
            runs = np.flatnonzero(dd == -1) - np.flatnonzero(dd == 1)
            if runs.max() > 0.6 * (g1 - g0):
                dot[c] = False
        for kind, cols in (("C", conn[g0:g1, x0:x1 + 1].any(axis=0)),
                           (f"D{gi}", dot)):
            d = np.diff(np.concatenate(([0], cols.astype(np.int8), [0])))
            for u, v in zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1)):
                if v - u <= 0.6 * sp:
                    pts.append((x0 + (u + v) / 2.0, kind))
    for i in idxs:
        st = staves[i]
        r0, r1 = int(st.top - thick), int(st.bottom + thick) + 1
        band = owner[r0:r1, st.x0:st.x1 + 1] == i
        cov = band.mean(axis=0)
        cand = cov >= 0.92
        d = np.diff(np.concatenate(([0], cand.astype(np.int8), [0])))
        inner = band.copy()
        for ly in st.lines:                       # interior without lines
            a0 = max(0, int(ly - thick) - r0)
            inner[a0:int(ly + thick) + 1 - r0] = False
        icov = inner.mean(axis=0)
        for u, v in zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1)):
            if v - u > 0.6 * sp:
                continue
            lo1, lo0 = int(u - 0.6 * sp), int(u - 0.25 * sp)
            hi0, hi1 = int(v + 0.25 * sp), int(v + 0.6 * sp)
            sides = [icov[max(0, lo1):max(0, lo0)], icov[hi0:hi1]]
            busy = max((sd.mean() for sd in sides if sd.size), default=1.0)
            if busy < 0.06:                       # clear on both sides
                pts.append((st.x0 + (u + v) / 2.0, f"B{i}"))
    pts.sort()
    clusters: list[list[tuple[float, str]]] = []
    for p in pts:
        if clusters and p[0] - clusters[-1][-1][0] <= 0.8 * sp:
            clusters[-1].append(p)
        else:
            clusters.append([p])
    need_b = 1 if len(idxs) == 1 else max(2, int(np.ceil(0.5 * len(idxs))))
    need_d = min(2, max(1, ngaps))
    out = []
    for cl in clusters:
        has_c = any(t == "C" for _, t in cl)
        nd = len({t for _, t in cl if t.startswith("D")})
        nb = len({t for _, t in cl if t.startswith("B")})
        # dotted gap columns in 2+ gaps (a stem never crosses two gaps at
        # one x); with one gap only, a staff barline must agree
        dotted = nd >= need_d and (ngaps >= 2 or nb >= 1)
        xc = float(np.mean([x for x, _ in cl]))
        only_d = dotted and not has_c and nb < need_b
        if (has_c or dotted or nb >= need_b) and xc > x0 + (DOTTED_MIN_SP if only_d else 3.5) * sp:
            out.append(int(round(xc)))
            if dotted and not has_c and dotted_out is not None:
                dotted_out.append(int(round(xc)))
    return out


def chain_owners(pending: list[int], stats: np.ndarray, lab_owner: np.ndarray,
                 sp: float) -> list[int]:
    """chain_owners -> the components still without owner.

    A pending component takes the owner of the first owned component, in
    order of arrival, that is within 0.5 sp across and CHAIN_SP * sp above
    or below. A component that got an owner can be the neighbour of a later
    one, in the same pass or the next; passes repeat until nothing changes.
    The boxes sit in numpy arrays, so one pending component costs one
    vector test, not a Python loop over every owned component."""
    owned = [c for c in range(1, len(stats)) if 0 <= lab_owner[c] < OWN_HEADER_BASE]
    box = np.zeros((len(owned) + len(pending), 4), np.int64)
    own = np.zeros(len(box), np.int64)
    k = len(owned)
    for i, c in enumerate(owned):
        box[i] = stats[c][:4]
        own[i] = lab_owner[c]
    changed = True
    while changed and pending:
        changed = False
        nxt = []
        for c in pending:
            x, y, cw, ch, _ = stats[c]
            ox, oy = box[:k, 0], box[:k, 1]
            hit = ((ox - 0.5 * sp <= x + cw) & (x - 0.5 * sp <= ox + box[:k, 2])
                   & (np.maximum(oy - (y + ch), y - (oy + box[:k, 3])) <= CHAIN_SP * sp))
            j = int(hit.argmax()) if k else 0
            if k and hit[j]:
                lab_owner[c] = own[j]
                box[k] = stats[c][:4]
                own[k] = own[j]
                k += 1
                changed = True
            else:
                nxt.append(c)
        pending = nxt
    return pending


def group_components(comps: list[int], stats: np.ndarray, sp: float
                     ) -> list[list[int]]:
    """group_components -> lists of components forming one text line.

    Two components join when their row ranges overlap by at least 30% of
    the shorter one and the horizontal gap is below GROUP_GAP_SP."""
    parent = {c: c for c in comps}

    def find(c: int) -> int:
        while parent[c] != c:
            parent[c] = parent[parent[c]]
            c = parent[c]
        return c

    order = sorted(comps, key=lambda c: stats[c][0])
    for i, a in enumerate(order):
        ax, ay, aw, ah, _ = stats[a]
        for b in order[i + 1:]:
            bx, by, bw, bh, _ = stats[b]
            if bx - (ax + aw) > GROUP_GAP_SP * sp:
                break
            ov = min(ay + ah, by + bh) - max(ay, by)
            if ov >= 0.3 * min(ah, bh):
                parent[find(b)] = find(a)
    out: dict[int, list[int]] = {}
    for c in comps:
        out.setdefault(find(c), []).append(c)
    return list(out.values())


def prepare(page: pymupdf.Page, dpi: int
            ) -> tuple[np.ndarray, float, float, int, int, list]:
    """prepare -> (ink, skew, dewarp px, thick, gap, tracks).

    Render, flatten, binarize, deskew, track staves, straighten, and
    binarize again. Tracks are returned in straightened coordinates."""
    grey = flatten(render_page(page, dpi))
    ink = binarize(grey)
    skew = estimate_skew(ink)
    if abs(skew) >= 0.05:
        grey = rotate(grey, skew)
        ink = binarize(grey)
    thick, gap = run_lengths(ink)
    sp = thick + gap
    scale = dpi / 400.0
    if not (SP_MIN_PX * scale <= sp <= SP_MAX_PX * scale):
        return ink, skew, 0.0, thick, gap, []
    h, w = ink.shape
    tracks = staff_tracks(ink, thick, sp)
    grey2, dmax = dewarp(grey, tracks, w, h)
    if dmax > 0:
        ink = binarize(grey2)
        thick, gap = run_lengths(ink)
        tracks = staff_tracks(ink, thick, thick + gap)
    return ink, skew, dmax, thick, gap, tracks


def analyse_page(page: pymupdf.Page, pno: int, dpi: int, sys_base: int,
                 ocr: bool = True) -> PageResult:
    """analyse_page -> PageResult with a complete owner image.

    Every ink pixel gets exactly one owner: a staff index, the header of a
    system (OWN_HEADER_BASE + global system index), or a discard class.
    The safety gate results are in PageResult.gate."""
    ink, skew, dmax, thick, gap, tracks = prepare(page, dpi)
    sp = float(thick + gap)
    h, w = ink.shape
    owner = np.full((h, w), OWN_NONE, np.int32)
    res = PageResult(pno, (h, w), sp, thick, skew, dmax, [], [], owner,
                     ink_px=int(ink.sum()))
    vector_text = abs(skew) < 0.05 and dmax == 0 and bool(page.get_text("words"))

    staves, hmask = (detect_staves(ink, thick, gap, pno) if tracks else ([], None))
    if not staves:
        owner[ink] = D_NOMUSIC
        res.music = False
        if tracks:
            res.gate.append(f"{len(tracks)} staff track(s) but no staff accepted")
        _finish_discard(res)
        return res

    # Safety: every staff track must be an accepted staff.
    # Within 1.6 sp: beams under a dense continuo staff pull a track's
    # centre by about one line (Biber p41: 15 px at sp 14, a false FAIL);
    # a missed staff is always 4 sp or more from any accepted one.
    for t in tracks:
        yc = float(np.mean([c[1][2] for c in t]))
        if not any(abs((s.top + s.bottom) / 2 - yc) < 1.6 * sp for s in staves):
            res.gate.append(f"staff track at y={int(yc)} not accepted as a staff")
            res.gate_boxes.append((0, int(yc - 3 * sp), w, int(6 * sp)))

    systems = group_systems(ink, staves, sp, thick)
    for k, grp in enumerate(systems):
        # one start for all staves of a system (engraved systems start
        # together): the leftmost start within 4 sp of the median (clefs
        # and broken scan lines only push a measured start to the right);
        # a staff more than 4 sp away keeps its own (indent)
        med = float(np.median([st.x0 for st in grp]))
        near = [st.x0 for st in grp if abs(st.x0 - med) <= 4 * sp]
        x_sys = min(near)
        for st in grp:
            st.system = sys_base + k
            if abs(st.x0 - med) <= 4 * sp:
                st.x0 = x_sys
    # systems of a page start at one x: a system starting 1-4 sp right of
    # the others (the clef hid the short line start, Schein Nun p3.s1:
    # clefs misread, brace lost) takes their median start. An indented
    # system (more than 4 sp) keeps its own.
    if len(systems) >= 3:
        starts = [min(st.x0 for st in grp) for grp in systems]
        for k, grp in enumerate(systems):
            others = [x for i, x in enumerate(starts) if i != k]
            med = float(np.median(others))
            if 1.0 * sp < starts[k] - med <= 4 * sp and \
                    sum(abs(x - med) <= sp for x in others) >= 2:
                for st in grp:
                    if abs(st.x0 - starts[k]) <= 4 * sp:
                        st.x0 = int(med)
    res.staves, res.systems = staves, systems

    # 0. whole-component pre-pass on the full ink (before staff lines cut
    #    tall items into pieces): despeckle (noise) and page-edge artefacts
    #    (tall line outside the staff x-range = spine or scan border; item
    #    touching the page border outside every staff band = corner/curl).
    n0, lab0, st0, _ = cv2.connectedComponentsWithStats(ink.astype(np.uint8), connectivity=8)
    sx0 = min(s.x0 for s in staves)
    sx1 = max(s.x1 for s in staves)
    em = max(3, int(0.004 * max(h, w)))
    noise_ids, edge_ids = [], []
    for c in range(1, n0):
        x, y, cw, ch, area = st0[c]
        if area < max(4.0, NOISE_AREA_SP2 * sp * sp):
            noise_ids.append(c)
            continue
        outside = x + cw < sx0 - 1.0 * sp or x > sx1 + 1.0 * sp
        right = x > sx1 + 1.0 * sp      # labels are left; spine pieces right
        if (outside and ch > 0.25 * h) or (right and cw < 0.6 * sp and ch > 0.4 * sp):
            edge_ids.append(c)          # spine / border, or a piece of it
            continue
        touches = x <= em or y <= em or x + cw >= w - em or y + ch >= h - em
        in_band = any(y <= s.bottom + sp and y + ch >= s.top - sp and
                      x <= s.x1 and x + cw >= s.x0 for s in staves)
        if touches and not in_band:
            edge_ids.append(c)
    for ids, code in ((noise_ids, D_NOISE), (edge_ids, D_EDGE)):
        if ids:
            msk = np.isin(lab0, ids)
            owner[msk] = code
            ink = ink & ~msk
    del lab0

    # 1. staff line pixels -> their staff (long horizontal runs in line
    #    rows, only inside the staff's own extent: label text and incipit
    #    staves on the same rows are not staff lines)
    line_px = np.zeros_like(ink)
    for s_i, st in enumerate(staves):
        c0, c1 = max(0, int(st.x0 - 0.3 * sp)), min(w, int(st.x1 + 0.3 * sp) + 1)
        for ly in st.lines:
            r0 = max(0, int(ly - thick))
            r1 = min(h, int(ly + thick) + 1)
            sl = hmask[r0:r1, c0:c1] & ink[r0:r1, c0:c1]
            line_px[r0:r1, c0:c1] |= sl
            owner[r0:r1, c0:c1][sl] = s_i
    rest = ink & ~line_px

    # 1b. connectors: columns solid (or dotted, >= 15% next to a solid
    #     one) across a whole gap between two staves. Removed like staff
    #     lines, so a clef touching a barline is not joined to other staves.
    conn = np.zeros_like(ink)
    for a, b in zip(staves, staves[1:]):
        g0, g1 = int(a.bottom + thick) + 1, int(b.top - thick) - 1
        if g1 <= g0:
            continue
        seg = rest[g0:g1 + 1]
        full = (~seg).sum(axis=0) <= 2
        if not full.any():
            continue
        reach = max(2, thick)
        near = np.convolve(full.astype(np.uint8), np.ones(2 * reach + 1),
                           mode="same") > 0
        full |= near & (seg.mean(axis=0) >= 0.15)
        conn[g0:g1 + 1, full] = seg[:, full]
    rest &= ~conn
    owner[conn] = D_CONNECTOR

    # 2. connected components of remaining ink
    n, labels, stats, _ = cv2.connectedComponentsWithStats(
        rest.astype(np.uint8), connectivity=8)
    lab_owner = np.full(n, OWN_NONE, np.int64)
    bands = [(st.top - BAND_MARGIN * sp, st.bottom + BAND_MARGIN * sp)
             for st in staves]
    split_labels: list[int] = []
    gap_comps: list[int] = []
    label_boxes: dict[int, list[int]] = {}      # staff index -> components

    def is_left_bracket(c: int, x: int, y: int, cw: int, ch: int,
                        left: int, hit: list[int]) -> bool:
        """True for a bracket/brace: starts within 1 sp of the staff start,
        at most BRACKET_MAX_SP wide, and (almost) no ink inside the staff
        interior right of left + 1.5 sp. The last test keeps a clef that
        touches the bracket from being discarded with it."""
        if x > left + 1.0 * sp or cw > BRACKET_MAX_SP * sp:
            return False
        sub = labels[y:y + ch, x:x + cw] == c
        xin = max(0, int(left + 1.5 * sp) - x)
        inner = 0
        for i in hit:
            r0 = max(0, int(staves[i].top) - y)
            r1 = max(0, int(staves[i].bottom) - y + 1)
            inner += int(sub[r0:r1, xin:].sum())
        return inner < 0.5 * sp * sp

    centres = np.array([(st.top + st.bottom) / 2 for st in staves])
    brace_id = 0
    for c in range(1, n):
        x, y, cw, ch, area = stats[c]
        y1 = y + ch - 1
        si = int(np.argmin(np.abs(centres - (y + y1) / 2)))
        near = staves[si]
        if x + cw < near.x0 - 0.3 * sp and \
           near.top - 2.5 * sp <= (y + y1) / 2 <= near.bottom + 1.5 * sp:
            lab_owner[c] = D_LABEL               # instrument label, left
            label_boxes.setdefault(si, []).append(c)
            continue
        hit = [i for i, (b0, b1) in enumerate(bands) if y <= b1 and y1 >= b0]
        if len(hit) == 1:
            lab_owner[c] = hit[0]
        elif len(hit) > 1:
            left = min(staves[i].x0 for i in hit)
            if cw <= THIN_VERTICAL_SP * sp:
                split_labels.append(c)          # barline through staves
            elif is_left_bracket(c, x, y, cw, ch, left, hit):
                lab_owner[c] = D_BRACKET         # bracket / brace at left
                for i in hit:
                    if staves[i].brace < 0:
                        staves[i].brace = brace_id
                brace_id += 1
            else:
                # cross-staff item: staff band holding most of its pixels
                sub = labels[y:y1 + 1, x:x + cw] == c
                cnt = [int(sub[max(0, int(bands[i][0]) - y):
                               max(0, int(bands[i][1]) - y + 1)].sum())
                       for i in hit]
                lab_owner[c] = hit[int(np.argmax(cnt))]
                res.review.append((int(x), int(y), int(cw), int(ch),
                                   "cross-staff"))
        else:
            gap_comps.append(c)

    # 3. gap components: close -> staff, then chain, then text rules
    def dists_box(y: int, y1: int) -> tuple[int | None, float, int | None, float]:
        """Nearest staff above and below a row range, distances in sp."""
        above = [i for i, st in enumerate(staves) if st.bottom < y]
        below = [i for i, st in enumerate(staves) if st.top > y1]
        ia = above[-1] if above else None
        ib = below[0] if below else None
        da = (y - staves[ia].bottom) / sp if ia is not None else np.inf
        db = (staves[ib].top - y1) / sp if ib is not None else np.inf
        return ia, da, ib, db

    # Labels just above a staff start, e.g. "(Tenore II)" (Bärenreiter
    # prints them on reduced systems). Checked before the near-ink rule,
    # because they sit within 1 sp of the staff. Accepted only when the
    # text reads as a bracketed word.
    if ocr:
        cand, cand_staff = [], {}
        for c in range(1, n):
            if lab_owner[c] not in (OWN_NONE,) and not (0 <= lab_owner[c] < len(staves)):
                continue
            x, y, cw, ch, _ = stats[c]
            if ch >= 2.6 * sp:
                continue
            for k, stv in enumerate(staves):
                if stv.top - LABEL_ABOVE_SP * sp <= y + ch - 1 <= stv.top + 0.3 * sp and \
                   y < stv.top - 0.2 * sp and \
                   stv.x0 - 0.5 * sp <= x <= stv.x0 + 16 * sp:
                    cand.append(c)
                    cand_staff[c] = k
                    break
        taken = set()
        for members in group_components(cand, stats, sp):
            gx0 = int(min(stats[c][0] for c in members))
            gy0 = int(min(stats[c][1] for c in members))
            gx1 = int(max(stats[c][0] + stats[c][2] for c in members))
            gy1 = int(max(stats[c][1] + stats[c][3] for c in members))
            ib = cand_staff[members[0]]
            if gx0 > staves[ib].x0 + 6 * sp or gx1 - gx0 < 2 * sp:
                continue
            crop = np.isin(labels[gy0:gy1, gx0:gx1], members)
            txt = read_text(page, (gx0, gy0, gx1, gy1), dpi, crop, vector_text,
                            scale_up=True)
            mb = re.search(r"[\(\[{]\s*([A-Za-zÀ-ÿ]{3}[^\)\]}]*)", txt)
            if mb:
                for c in members:
                    lab_owner[c] = D_LABEL
                    taken.add(c)
                staves[ib].label = staves[ib].label or clean_label(mb.group(1))
        gap_comps = [c for c in gap_comps if c not in taken]

    pending = []
    for c in gap_comps:
        ia, da, ib, db = dists_box(int(stats[c][1]),
                                   int(stats[c][1] + stats[c][3] - 1))
        if min(da, db) <= CLOSE_SP:
            lab_owner[c] = ia if da <= db else ib
        else:
            pending.append(c)

    # chaining: an unresolved component next to an owned one inherits it
    pending = chain_owners(pending, stats, lab_owner, sp)

    # Text lines are decided as a whole (a word is never split).
    groups = group_components(pending, stats, sp)
    heights = []
    rows_in_gap: dict[tuple[int, int], list[dict]] = {}
    for members in groups:
        gx0 = int(min(stats[c][0] for c in members))
        gy0 = int(min(stats[c][1] for c in members))
        gx1 = int(max(stats[c][0] + stats[c][2] for c in members))
        gy1 = int(max(stats[c][1] + stats[c][3] for c in members))
        heights.append(gy1 - gy0)
        ia, da, ib, db = dists_box(gy0, gy1 - 1)
        own = None
        if ia is None:                   # above first staff
            own = (D_HEADER if db > config.TUNE["page_header_sp"]
                   else OWN_HEADER_BASE + staves[ib].system)
        elif ib is None:                                 # below last staff
            own = D_FOOTER if da > PAGE_FOOTER_SP else ia
            # nearer: copyright, publisher, page number, footnote by its
            # text (Schein Nun p1: "(c) 1986 by Baerenreiter" 6.0 sp below)
            # a wide text line nearer, as a footnote ("*) Das Pausenzeichen
            # ...", Schein Nun p8, on the row of the figures)
            if own == ia and ocr and da <= FOOTER_TEXT_SP and gx1 - gx0 >= 8 * sp:
                txt = read_text(page, (gx0, gy0, gx1, gy1), dpi,
                                ink[gy0:gy1, gx0:gx1], vector_text)
                if txt.strip().startswith(("*", "\u2020")) or (
                        is_footer_text(txt) and not txt.strip().isdigit()):
                    own = D_FOOTER
            if own == ia and ocr and da > FOOTER_TEXT_SP:
                txt = read_text(page, (gx0, gy0, gx1, gy1), dpi,
                                ink[gy0:gy1, gx0:gx1], vector_text)
                # digits alone: a page number only beyond 4.5 sp (figures
                # reach about 3.5 sp; Schein Nun page numbers at 5.0 sp)
                if is_footer_text(txt) and (da > 4.5 or not txt.strip().isdigit()):
                    own = D_FOOTER
        if own is not None:
            for c in members:
                lab_owner[c] = own
            continue
        rows_in_gap.setdefault((ia, ib), []).append(
            {"m": members, "box": (gx0, gy0, gx1, gy1), "da": da, "db": db,
             "yc": (gy0 + gy1) / 2.0})
    # Rows of text in one gap (lyric line, figured bass): an item joins a
    # row when its centre is within 0.6 sp of the row's last item or its
    # box overlaps the row's band by half its height (descenders, hyphens:
    # Maria p10 "ja," and "al-le-lu-ja" were split between two staves). A
    # text line (3+ items over a quarter of the staff width) belongs to the
    # staff above (operator request 2026-10-25: a split word is worse than a stray
    # "Cap."); another row of 3+ items unless it sits in the lowest quarter
    # of the gap; single items use TEXT_ABOVE_FRAC.
    text_bands: list[tuple[int, int, int, int, int, int]] = []
    for (ia, ib), items in rows_in_gap.items():
        new_system = staves[ia].system != staves[ib].system
        items.sort(key=lambda it: it["yc"])
        rows: list[list[dict]] = []
        for it in items:
            if rows:
                band0 = min(x["box"][1] for x in rows[-1])
                band1 = max(x["box"][3] for x in rows[-1])
                ih = max(1, it["box"][3] - it["box"][1])
                ov = min(band1, it["box"][3]) - max(band0, it["box"][1])
                if it["yc"] - rows[-1][-1]["yc"] <= 0.6 * sp or ov >= 0.5 * ih:
                    rows[-1].append(it)
                    continue
            rows.append([it])
        swidth = max(1.0, float(staves[ia].x1 - staves[ia].x0))
        for row in rows:
            fr = [it["da"] / max(it["da"] + it["db"], 1e-6) for it in row]
            frac = float(np.median(fr))
            span = max(it["box"][2] for it in row) - min(it["box"][0] for it in row)
            text_line = len(row) >= 3 and span >= 0.25 * swidth
            limit = 0.75 if len(row) >= 3 else TEXT_ABOVE_FRAC
            if text_line or frac < limit:
                own = ia                                  # lyrics, figures
            elif new_system:
                own = OWN_HEADER_BASE + staves[ib].system
            else:
                own = ib
            if len(row) < 3 and not new_system and \
               abs(frac - TEXT_ABOVE_FRAC) < TEXT_REVIEW_FRAC:
                for it in row:
                    gx0, gy0, gx1, gy1 = it["box"]
                    res.review.append((gx0, gy0, gx1 - gx0, gy1 - gy0, "midpoint"))
            for it in row:
                for c in it["m"]:
                    lab_owner[c] = own
            if text_line and own == ia:
                text_bands.append((ia, ib, min(it["box"][0] for it in row),
                                   max(it["box"][2] for it in row),
                                   min(it["box"][1] for it in row),
                                   max(it["box"][3] for it in row)))
    # a syllable of a text line attached earlier to the staff below (its
    # high notes stand close to the line: Maria p11 "al-le-lu" under the
    # Alto went to the Tenore) joins its line: small, inside the band and
    # span, clear of the lower staff
    for ia, ib, bx0, bx1, by0, by1 in text_bands:
        for c in range(1, len(lab_owner)):
            if lab_owner[c] != ib:
                continue
            x, y, cw, ch, _ = stats[c]
            if ch > 2.6 * sp or y + ch > staves[ib].top - 0.3 * sp:
                continue
            if x + cw < bx0 - sp or x > bx1 + sp:
                continue
            if y + ch > by1 + 0.25 * sp or y < by0 - 0.5 * sp:
                continue                    # reaches toward the staff: a note, not a syllable
            ov = min(by1, y + ch) - max(by0, y)
            if ov >= 0.5 * ch:
                lab_owner[c] = ia
    # scan dust: a lone speck given to a system header would be copied into
    # every part (Maria p1). One small component with no text within 1 sp
    # (its own group) is noise; a full stop stays with its word.
    for members in groups:
        if len(members) == 1:
            c = members[0]
            x, y, cw, ch, area = stats[c]
            if lab_owner[c] >= OWN_HEADER_BASE and area < DUST_AREA_SP2 * sp * sp \
               and max(cw, ch) < 0.6 * sp:
                lab_owner[c] = D_NOISE

    def find_composer(title_box: tuple[int, int, int, int]):
        """Composer: a text line above the first staff, below the title,
        in the right half, its right edge at the right end of the staves
        (engraver layout); the lowest such line. -> (members, box) or None."""
        sx_right = max(st.x1 for st in staves)
        cand = []
        for members in groups:
            gx0c = int(min(stats[c][0] for c in members))
            gy0c = int(min(stats[c][1] for c in members))
            gx1c = int(max(stats[c][0] + stats[c][2] for c in members))
            gy1c = int(max(stats[c][1] + stats[c][3] for c in members))
            if gy1c >= staves[0].top or gy0c <= title_box[1] or gx0c < 0.5 * w \
               or abs(gx1c - sx_right) > 3 * sp or gx1c - gx0c < 3 * sp \
               or gy1c - gy0c < 0.8 * sp:
                continue
            cand.append((gy1c, members, (gx0c, gy0c, gx1c, gy1c)))
        if not cand:
            return None
        _, mem_c, box = max(cand, key=lambda t: t[0])
        return mem_c, box

    # Title: the tallest centred text line above the first staff.
    if staves and groups:
        med = float(np.median(heights)) if heights else 0.0
        best = None
        top_line = None              # fallback: topmost centred line
        for members, hh in zip(groups, heights):
            gx0 = int(min(stats[c][0] for c in members))
            gy0 = int(min(stats[c][1] for c in members))
            gx1 = int(max(stats[c][0] + stats[c][2] for c in members))
            gy1 = int(max(stats[c][1] + stats[c][3] for c in members))
            if gy1 >= staves[0].top or hh < 1.0 * sp or \
               gx1 - gx0 < 6 * sp or abs((gx0 + gx1) / 2 - w / 2) > 0.2 * w:
                continue
            if not looks_like_text([stats[c][2] for c in members], max(hh, gy1 - gy0)):
                continue
            if hh >= 0.9 * med and (top_line is None or gy0 < top_line[2][1]):
                top_line = (hh, members, (gx0, gy0, gx1, gy1))
            if hh < 1.4 * med:
                continue
            if best is None or hh > best[0]:
                best = (hh, members, (gx0, gy0, gx1, gy1))
        if best is None and top_line is not None and find_composer(top_line[2]):
            # a title in the same size as other text (Suite 1): the topmost
            # centred line, when a composer line stands below it (a running
            # head on a later page has none)
            best = top_line
        if best is not None:
            gx0, gy0, gx1, gy1 = best[2]
            # the whole title line: other groups on the same row (wide word
            # spacing in large type splits a line into several groups)
            mem = list(best[1])
            for members in groups:
                if members is best[1]:
                    continue
                y0m = int(min(stats[c][1] for c in members))
                y1m = int(max(stats[c][1] + stats[c][3] for c in members))
                if min(y1m, gy1) - max(y0m, gy0) >= 0.5 * (gy1 - gy0):
                    mem += members
                    gx0 = min(gx0, int(min(stats[c][0] for c in members)))
                    gx1 = max(gx1, int(max(stats[c][0] + stats[c][2] for c in members)))
            best = (best[0], mem, (gx0, gy0, gx1, gy1))
            crop = rest[gy0:gy1, gx0:gx1] & np.isin(labels[gy0:gy1, gx0:gx1], best[1])
            res.title = clean_title(read_text(page, best[2], dpi, crop, vector_text))
            found = find_composer((gx0, gy0, gx1, gy1))
            if found:
                mem_c, box = found
                bx0, by0, bx1, by1 = box
                crop_c = rest[by0:by1, bx0:bx1] & np.isin(labels[by0:by1, bx0:bx1], mem_c)
                txt = clean_title(read_text(page, box, dpi, crop_c, vector_text))
                if len(re.findall(r"[A-Za-z]", txt)) >= 3:
                    res.composer = txt

    # 3b. system window: a staff owns no ink wholly left of its system start
    #     (- EDGE_LEFT_SP) or right of the system's widest staff end
    #     (+ EDGE_RIGHT_SP). Left, within BRACKET_ZONE_SP: bracket pieces;
    #     farther: page edge, spine or a neighbour page. A header owns no
    #     lone stroke (group narrower than 1 sp) outside the window. Staff x1
    #     of one staff can be short (broken line ends), so the right limit
    #     is the widest staff of the system.
    win: dict[int, tuple[float, float]] = {}
    for grp in systems:
        win[grp[0].system] = (min(st.x0 for st in grp) - EDGE_LEFT_SP * sp,
                              max(st.x1 for st in grp) + EDGE_RIGHT_SP * sp)

    def outside_win(g: int, x: int, cw: int) -> bool:
        a, b = win[g]
        return x + cw - 1 < a or x > b

    def out_code(g: int, x_right: float) -> int:
        """Discard class for ink left or right of the window."""
        a, _ = win[g]
        return D_BRACKET if a - BRACKET_ZONE_SP * sp <= x_right < a else D_EDGE

    for c in range(1, n):
        o = int(lab_owner[c])
        if 0 <= o < len(staves) and outside_win(staves[o].system, stats[c][0], stats[c][2]):
            lab_owner[c] = out_code(staves[o].system, stats[c][0] + stats[c][2] - 1)
        elif 0 <= o < len(staves) and stats[c][0] > win[staves[o].system][1] - \
                (EDGE_RIGHT_SP - 0.25) * sp and stats[c][4] < 0.6 * sp * sp \
                and max(stats[c][2], stats[c][3]) < 1.0 * sp:
            # a small speck wholly right of the staff end (Maria: dots in a
            # column past the right margin, scan debris); larger marks stay
            lab_owner[c] = D_EDGE
        elif 0 <= o < len(staves):
            # bracket hook: a piece that crosses the system start with only
            # a small part (under 1.5 sp^2) inside it (the top or bottom
            # serif of a bracket, reaching over the clef)
            a_, _ = win[staves[o].system]
            x, y, cw, ch, area = stats[c]
            if x < a_ <= x + cw - 1 and ch < 1.5 * sp:
                inside = int((labels[y:y + ch, int(a_):x + cw] == c).sum())
                if inside < 1.5 * sp * sp:
                    lab_owner[c] = D_BRACKET
    for members in groups:
        o = int(lab_owner[members[0]])
        if o < OWN_HEADER_BASE:
            continue
        gx0 = int(min(stats[c][0] for c in members))
        gx1 = int(max(stats[c][0] + stats[c][2] for c in members))
        if gx1 - gx0 < 1.0 * sp and outside_win(o - OWN_HEADER_BASE, gx0, gx1 - gx0):
            for c in members:
                lab_owner[c] = D_EDGE
    split_edge = {c for c in split_labels
                  if all(outside_win(g, stats[c][0], stats[c][2]) for g in win)}
    for c in split_edge:
        lab_owner[c] = D_EDGE
    split_labels = [c for c in split_labels if c not in split_edge]

    # 4. paint owners
    mask_rest = rest & (labels > 0)
    owner[mask_rest] = lab_owner[labels[mask_rest]].astype(np.int32)
    for c in split_labels:
        x, y, cw, ch, _ = stats[c]
        sub = labels[y:y + ch, x:x + cw] == c
        blk = owner[y:y + ch, x:x + cw]
        blk[sub] = D_CONNECTOR
        for i, st in enumerate(staves):
            r0 = max(y, int(st.top - thick))
            r1 = min(y + ch, int(st.bottom + thick) + 1)
            if r1 > r0:
                s2 = sub[r0 - y:r1 - y]
                blk[r0 - y:r1 - y][s2] = i

    # 4b. system window, pixel level: a component that reaches from the
    #     music into the page edge (spine joined to a slur or a border) is
    #     cut at the window; the part outside is bracket or edge.
    for i, st in enumerate(staves):
        a_, b_ = win[st.system]
        zb = max(0, int(a_ - BRACKET_ZONE_SP * sp))
        for c0, c1, code in ((0, zb, D_EDGE), (zb, max(0, int(a_)), D_BRACKET),
                             (min(w, int(b_) + 1), w, D_EDGE)):
            if c1 > c0:
                blk = owner[:, c0:c1]
                blk[blk == i] = code

    # 5. labels left of staves (OCR or text layer), clef signatures.
    #    Only text-like components (lower than 2.6 sp, narrower than 8 sp,
    #    not a thin line piece, not a dot) are read, so incipit staves and
    #    bracket pieces stay out of the OCR.
    if ocr:
        for si, comps in label_boxes.items():
            textish = [c for c in comps if stats[c][3] < 2.6 * sp and stats[c][2] < 8 * sp
                       and not (stats[c][3] <= 2 * thick + 1 and stats[c][2] >= 1.5 * sp)
                       and stats[c][4] >= 0.03 * sp * sp]   # no line pieces, no dots
            lines_ = group_components(textish, stats, sp)
            lines_.sort(key=lambda m: min(stats[c][1] for c in m))
            parts_txt = []
            for m in lines_[:3]:
                gx0 = int(min(stats[c][0] for c in m))
                gy0 = int(min(stats[c][1] for c in m))
                gx1 = int(max(stats[c][0] + stats[c][2] for c in m))
                gy1 = int(max(stats[c][1] + stats[c][3] for c in m))
                if gx1 - gx0 < 1.2 * sp:
                    continue
                crop = np.isin(labels[gy0:gy1, gx0:gx1], m)
                parts_txt.append(read_text(page, (gx0, gy0, gx1, gy1), dpi, crop,
                                           vector_text, scale_up=True))
            txt = clean_label(" ".join(t for t in parts_txt if t))
            if txt:
                staves[si].label = txt
    # 6. barlines, printed bar numbers (anchors), movement starts
    for k, grp in enumerate(systems):
        g = staves[0].system + k
        idxs = [st.idx for st in grp]
        dotted: list[int] = []
        res.barlines[g] = detect_barlines(owner, conn, ink | conn, staves, idxs, sp,
                                          thick, dotted)
        res.mensur[g] = dotted
        # Mensurstriche: their dashes in the gaps belong to no staff
        # (thin, within 0.6 sp of the barline, centre in a gap)
        for xb in dotted:
            for a, b in zip(grp, grp[1:]):
                for c in range(1, n):
                    x, y, cw, ch, _ = stats[c]
                    if cw > 0.6 * sp or abs(x + cw / 2 - xb) > 0.6 * sp:
                        continue
                    if y < a.bottom - 0.5 * sp or y + ch - 1 > b.top + 0.5 * sp:
                        continue
                    if not (a.bottom < y + ch / 2 < b.top):
                        continue
                    blk = owner[y:y + ch, x:x + cw]
                    sel = (labels[y:y + ch, x:x + cw] == c) & (blk >= 0) & (blk < len(staves))
                    blk[sel] = D_CONNECTOR
        # the system barline in the gaps at the system start: a narrow
        # vertical run (1.5 sp or longer) that a staff owns would hang
        # below its staff in the part (Cesare: through the lyrics)
        sx0 = min(st.x0 for st in grp)
        ca, cb = max(0, int(sx0 - 0.6 * sp)), int(sx0 + 0.6 * sp) + 1
        for a, b in zip(grp, grp[1:]):
            r0, r1 = int(a.bottom + 0.3 * sp), int(b.top - 0.3 * sp)
            if r1 - r0 < 2 * sp:
                continue
            blk = owner[r0:r1, ca:cb]
            own_px = (blk >= 0) & (blk < len(staves))
            for j in range(own_px.shape[1]):
                col = own_px[:, j]
                if not col.any():
                    continue
                # runs of own ink in this column
                d = np.diff(np.concatenate(([0], col.astype(np.int8), [0])))
                for s0, s1 in zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1)):
                    if s1 - s0 >= 1.5 * sp:
                        blk[s0:s1, j] = D_CONNECTOR
        res.anchors[g] = []
        top = grp[0]
        zone_y0, zone_y1 = top.top - BARNUM_ZONE_SP * sp, top.top - 0.2 * sp
        cand = [c for c in range(1, n)
                if stats[c][1] >= zone_y0 and stats[c][1] + stats[c][3] <= zone_y1 + 1
                and 0.7 * sp <= stats[c][3] <= 2.4 * sp and stats[c][2] <= 1.6 * sp   # Maria: 2.05 sp
                and top.x0 - 1.0 * sp <= stats[c][0] <= top.x1]
        cset = set(cand)
        for members in group_components(cand, stats, 0.4 * sp):
            gx0 = int(min(stats[c][0] for c in members))
            gy0 = int(min(stats[c][1] for c in members))
            gx1 = int(max(stats[c][0] + stats[c][2] for c in members))
            gy1 = int(max(stats[c][1] + stats[c][3] for c in members))
            if gx1 - gx0 > 4 * sp or len(members) > 3:
                continue
            # part of a word ("Violin." reads as "io" -> "10"): other ink on
            # the same row within 0.8 sp
            mset = set(members)
            word = False
            for c in range(1, n):
                if c in mset or (c not in cset and stats[c][4] < 0.06 * sp * sp):
                    continue
                x, y, cw, ch, _ = stats[c]
                ov = min(y + ch, gy1) - max(y, gy0)
                hh = gy1 - gy0
                if y > gy0 + 0.2 * hh and y + ch > gy1 + 0.35 * hh:
                    continue        # lower: a cue after a raised number, "35(Alto I)"
                if ov >= 0.5 * (gy1 - gy0) and (gx0 - 0.8 * sp <= x + cw and x <= gx1 + 0.8 * sp) \
                   and ch < 2.6 * sp:
                    word = True
                    break
            if word:
                continue
            txt = ""
            if vector_text:
                txt = text_in_rect(page, (gx0, gy0, gx1, gy1), dpi).strip()
            if not re.fullmatch(r"\d{1,3}", txt) and ocr:
                crop = np.isin(labels[gy0:gy1, gx0:gx1], members)
                txt = ocr_line(crop, digits=True)
            if not re.fullmatch(r"\d{1,3}", txt):
                continue
            xc = (gx0 + gx1) // 2
            bl = res.barlines[g]
            # line-start number: in the first bar and near the staff start
            # (printed above the clef or first note)
            at_start = (not bl or xc < bl[0]) and xc < top.x0 + 7 * sp
            # mid-line numbers are printed every 5 or 10 bars; anything
            # else there is a misread (breath mark, label debris)
            if not at_start and int(txt) % 5 != 0:
                continue
            res.anchors[g].append((xc, int(txt), at_start))
            if not at_start:
                res.num_boxes.setdefault(g, []).append((gx0, gy0, gx1, gy1))
            if at_start:                       # number at the system start:
                for c in members:              # replaced by the part's own
                    x, y, cw, ch, _ = stats[c]
                    blk = owner[y:y + ch, x:x + cw]
                    blk[labels[y:y + ch, x:x + cw] == c] = D_BARNUM
    # repeat signs: a pair of dots, one in staff space 2 and one in space 3,
    # one above the other, next to a barline, on at least half the staves
    for k, grp in enumerate(systems):
        g = staves[0].system + k
        pairs: list[float] = []
        for st in grp:
            i = st.idx
            mids = [(st.lines[1] + st.lines[2]) / 2, (st.lines[2] + st.lines[3]) / 2]
            dots: list[list[float]] = [[], []]
            for c in range(1, n):
                if int(lab_owner[c]) != i:
                    continue
                x, y, cw, ch, area = stats[c]
                if not (0.2 * sp <= cw <= 0.7 * sp and 0.2 * sp <= ch <= 0.7 * sp
                        and abs(cw - ch) <= 0.2 * sp and area >= 0.5 * cw * ch):
                    continue
                yc = y + ch / 2
                for q in (0, 1):
                    if abs(yc - mids[q]) <= 0.3 * sp:
                        dots[q].append(x + cw / 2)
            for xa in dots[0]:
                if any(abs(xa - xb) <= 0.3 * sp for xb in dots[1]):
                    pairs.append(xa)
        need = max(1, int(np.ceil(0.5 * len(grp))))
        bls = list(res.barlines.get(g, []))
        dotted = res.mensur.get(g, [])
        found: dict[tuple[int, str], int] = {}
        hits: list[tuple[float, str]] = []
        for xp in sorted(pairs):
            # the repeat barline: full-height columns 0.35-1.8 sp beside the
            # dots with a thick line (a run of 0.3 sp or more): ":||" or
            # "||:". A thin line alone is an ordinary barline (chord notes
            # in spaces 2 and 3 are not dots); dots on a dotted line are a
            # Mensurstrich.
            best = None
            for side, c0, c1 in (("start", xp - 1.8 * sp, xp - 0.35 * sp),
                                 ("end", xp + 0.35 * sp, xp + 1.8 * sp)):
                c0i = max(0, int(c0))
                for st in grp:
                    band = ink[int(st.top):int(st.bottom) + 1, c0i:int(c1) + 1]
                    if not band.size:
                        continue
                    full = band.mean(axis=0) >= 0.9
                    d = np.diff(np.concatenate(([0], full.astype(np.int8), [0])))
                    runs = list(zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1)))
                    if not any(v - u >= max(2, 0.3 * sp) for u, v in runs):
                        continue
                    u, v = runs[-1] if side == "start" else runs[0]   # line next to the dots
                    xc = float(c0i + (v - 1 if side == "start" else u))
                    if best is None or abs(xc - xp) < abs(best[1] - xp):
                        best = (side, xc)
                    break
            if best is None:
                continue
            side, xc = best
            if any(abs(xc - d) <= 0.6 * sp for d in dotted):
                continue
            hits.append((xc, side))
        # one entry per repeat barline (pairs of all staves agree within 1 sp)
        clusters: list[list[tuple[float, str]]] = []
        for xc, side in sorted(hits):
            if clusters and xc - clusters[-1][-1][0] <= 1.0 * sp and side == clusters[-1][-1][1]:
                clusters[-1].append((xc, side))
            else:
                clusters.append([(xc, side)])
        sys_x0 = min(s_.x0 for s_ in grp)
        reps = []
        for cl in clusters:
            if len(cl) < need:
                continue
            xc = float(np.median([c[0] for c in cl]))
            side = cl[0][1]
            # ':||:' (end and start on one barline): the two dot groups
            # find the thin line on their own side, 1-2 sp apart: one barline
            if not any(abs(b - xc) <= 2.0 * sp for b in bls):
                # a repeat barline the barline rules missed (its dots make
                # the side busy; no line between the staves): it ends a bar.
                # Not a start repeat in the opening clef area (no bar there).
                if side == "end" or xc > sys_x0 + 8 * sp:
                    bls = sorted(bls + [int(round(xc))])
                    res.barlines[g] = bls
            reps.append((xc, side))
        for xc, side in reps:
            on = [j for j, b in enumerate(bls) if abs(b - xc) <= 2.0 * sp]
            idx = on[0] if on else sum(1 for b in bls if b < xc) - 1
            if idx < 0 and side == "end":
                continue                    # an end repeat closes a bar
            found[(idx, side)] = found.get((idx, side), 0) + need
        res.repeats[g] = sorted(kk for kk, cnt in found.items() if cnt >= need)

    # ink of the last staff wholly below PAGE_FOOTER_SP: page-edge lines and
    # curl shadows (Schein Nun p6, p8: lines 14-21 sp down made the strip
    # tall, a large gap in the part)
    last = len(staves) - 1
    yb = int(staves[last].bottom + PAGE_FOOTER_SP * sp)
    if yb < h:
        sub = owner[yb:] == last
        if sub.any():
            nl, lb, sts, _ = cv2.connectedComponentsWithStats(sub.astype(np.uint8), 8)
            touch = set(np.unique(lb[0][lb[0] > 0]).tolist())   # reaches up: keep
            for c in range(1, nl):
                if c not in touch:
                    owner[yb:][lb == c] = D_FOOTER

    # a system end without its barline (page curl, Schein Nun p6.s1): a
    # last segment as wide as a bar is a bar, not a bar cut by the line
    # break (that bar lost its number before)
    for g in sorted({st.system for st in staves}):
        grp = [st for st in staves if st.system == g]
        bls = res.barlines.get(g) or []
        xend = min(st.x1 for st in grp)
        xs = min(st.x0 for st in grp) + 4 * sp          # after clef and key
        if not bls or bls[-1] >= xend - 3 * sp:
            continue
        widths = np.diff([xs] + list(bls))
        if len(widths) and xend - bls[-1] >= 0.75 * float(np.median(widths)):
            res.barlines[g] = list(bls) + [int(xend)]
            res.gate_notes = getattr(res, "gate_notes", []) + [f"system {g}: end barline added"]

    # movement start: page title, or a large header text at a system start
    for members in groups:
        own = int(lab_owner[members[0]])
        if own < OWN_HEADER_BASE:
            continue
        gx0 = int(min(stats[c][0] for c in members))
        gx1 = int(max(stats[c][0] + stats[c][2] for c in members))
        gy0 = int(min(stats[c][1] for c in members))
        gy1 = int(max(stats[c][1] + stats[c][3] for c in members))
        gsys = own - OWN_HEADER_BASE
        first = next(st for st in staves if st.system == gsys)
        if gy1 - gy0 >= 1.3 * sp and gx1 - gx0 >= 4 * sp and gx0 <= first.x0 + 6 * sp:
            # not a movement: a bar number with a voice cue, "35 (Alto I)"
            # (Schein Nun ist das Heil p6: the numbering restarted at 1)
            txt = read_text(page, (gx0, gy0, gx1, gy1), dpi,
                            ink[gy0:gy1, gx0:gx1], vector_text) if ocr else ""
            if not is_cue_text(txt):
                res.restart.add(gsys)
                continue
            # a voice cue is not copied into the parts (operator request 2026-10-25:
            # "35 (Alto I)" stood above the Continuo, with the source bar
            # number beside the part's own)
            sub = owner[gy0:gy1, gx0:gx1]
            sub[np.isin(labels[gy0:gy1, gx0:gx1], members)] = D_LABEL
            if not first.label:
                # the cue names the part of the top staff: a label for the
                # choices (Schein Nun p6.s3 "(Alto I)" was suggested as
                # Bass Trombone)
                t2 = read_text(page, (gx0, gy0, gx1, gy1), dpi,
                               ink[gy0:gy1, gx0:gx1], vector_text, scale_up=True)
                mb = re.search(r"[\(\[{]\s*([A-Za-zÀ-ÿ]{3}[^\)\]}]*)", t2)
                if mb:
                    first.label = clean_label(mb.group(1))
    if res.title and systems:
        res.restart.add(staves[0].system)

    for i, st in enumerate(staves):
        st.clef = clef_signature(owner, line_px, st, i, sp, thick)
        # printed bar numbers and the barlines (with repeat dots and line
        # stubs: Maria p10 a double barline gave E5 and a low note)
        bl_boxes = [(int(x - 1.2 * sp), int(st.top - 6 * sp), int(x + 1.2 * sp),
                     int(st.bottom + 6 * sp)) for x in res.barlines.get(st.system, [])]
        bl_boxes.append((int(st.x1 - 1.5 * sp), int(st.top - 6 * sp), int(st.x1 + sp),
                         int(st.bottom + 6 * sp)))
        r_ = note_steps(owner, line_px, st, i, sp, thick,
                        blank=res.num_boxes.get(st.system, []) + bl_boxes,
                        barxs=res.barlines.get(st.system, []))
        if r_:
            bls_ = res.barlines.get(st.system, [])
            bix = lambda xx: sum(1 for b in bls_ if b < xx)      # bar index in the system
            st.steps = (r_[0], r_[1], r_[3], r_[4], bix(r_[3]), bix(r_[4]))
        else:
            st.steps = None

    _gate_discards(res, ink, thick, sp)
    _finish_discard(res)
    return res


def _gate_discards(res: PageResult, ink: np.ndarray, thick: int, sp: float) -> None:
    """Safety gate: staff-like lines must not be hidden in discarded ink."""
    disc = np.isin(res.owner, GATE_CLASSES)
    if not disc.any():
        return
    tracks = staff_tracks(disc, thick, sp)
    for t in tracks:
        yc = int(np.mean([c[1][2] for c in t]))
        res.gate.append(f"staff-like lines in discarded ink at y={yc}")
        res.gate_boxes.append((0, int(yc - 3 * sp), res.shape[1], int(6 * sp)))


def _finish_discard(res: PageResult) -> None:
    o = res.owner
    for code in DISCARD_NAMES:
        cnt = int((o == code).sum())
        if cnt:
            res.discard[code] = cnt
    if res.discard.get(OWN_DISCARD):
        res.gate.append(f"{res.discard[OWN_DISCARD]} px unclassified discard")
    if (o == OWN_NONE).sum() != o.size - res.ink_px:
        res.gate.append("ink without owner")
