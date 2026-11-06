# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""Strip build, group strips, bar marks and rehearsal boxes."""
from __future__ import annotations

import cv2
import numpy as np

from .config import AMB_SP, HEADER_CLEAR_SP, PART_LAYOUT_KEY, SYSTEM_CLEAR_SP, SYSTEM_GAP_FACTOR
from .model import PageResult, Strip
from .typography import _font, text_len

# The last barline found is the line's end when it lies within this many staff
# spaces of the staff end. A final or repeat barline (thin + thick) is found at
# its middle, up to 2.2 sp before the end (a 2.0 limit missed them).
BAR_END_SP = 2.5


def make_strip(res: PageResult, st_idx: list[int], header_owner: int,
               darker: bool = False, bar_no: int | None = None,
               marks: list | None = None, movement: bool = False) -> Strip:
    """make_strip -> Strip for staves st_idx (one part) plus system header.

    The header is shifted to sit above this staff at the same offset it had
    above the system's top staff, and moved up if it would touch own ink.
    darker: dilate the ink by 1 px."""
    o = res.owner
    sp = res.sp
    own = np.isin(o, st_idx)
    sts = [res.staves[i] for i in st_idx]
    ys, xs = np.nonzero(own)
    y0, y1 = int(ys.min()), int(ys.max())
    x0, x1 = int(xs.min()), int(xs.max())
    hdr = o == header_owner
    # printed mid-line bar numbers: own ink of the top staff or header ink
    inbox = np.zeros(o.shape, bool)
    for bx0, by0, bx1, by1 in res.num_boxes.get(sts[0].system, []):
        inbox[by0:by1 + 1, bx0:bx1 + 1] = True
    n_own = inbox[ys, xs]
    hy = hx = None
    n_hdr = None
    if hdr.any():
        hy, hx = np.nonzero(hdr)
        n_hdr = inbox[hy, hx]
    top_staff = min((s for s in res.staves if s.system == sts[0].system),
                    key=lambda s: s.top)
    shift = int(round(sts[0].top - top_staff.top))
    if hy is not None and shift > 0:
        hy = hy + shift
        hb = int(hy.max())
        cols = slice(int(hx.min()), int(hx.max()) + 1)
        sub = own[:, cols]
        rows = np.flatnonzero(sub.any(axis=1))
        own_top = int(rows.min()) if rows.size else y0
        need = own_top - int(0.5 * sp)
        if hb > need:
            hy = hy - (hb - need)
    if hy is not None:
        # a header never starts left of the music: the staves keep the
        # left margin and the header text moves right
        if int(hx.min()) < x0:
            hx = hx + (x0 - int(hx.min()))
        y0 = min(y0, int(hy.min()))
        x1 = max(x1, int(hx.max()))
    pad = 1 if darker else 0
    canvas = np.zeros((y1 - y0 + 1 + 2 * pad, x1 - x0 + 1 + 2 * pad), bool)
    hcanvas = np.zeros_like(canvas)
    canvas[ys - y0 + pad, xs - x0 + pad] = True
    ncanvas = np.zeros_like(canvas)
    ncanvas[ys[n_own] - y0 + pad, xs[n_own] - x0 + pad] = True
    if hy is not None:
        canvas[hy - y0 + pad, hx - x0 + pad] = True
        hcanvas[hy - y0 + pad, hx - x0 + pad] = True
        ncanvas[hy[n_hdr] - y0 + pad, hx[n_hdr] - x0 + pad] = True
    if darker:
        k = np.ones((3, 3), np.uint8)
        canvas = cv2.dilate(canvas.astype(np.uint8), k) > 0
        hcanvas = cv2.dilate(hcanvas.astype(np.uint8), k) > 0
        ncanvas = cv2.dilate(ncanvas.astype(np.uint8), k) > 0
    return Strip(canvas, min(s.x0 for s in sts) - x0 + pad,
                 int(round(sts[0].top)) - y0 + pad,
                 int(round(sts[-1].bottom)) - y0 + pad, sp, hcanvas, bar_no,
                 marks=[(int(mx) - x0 + pad, t) for mx, t in (marks or [])],
                 movement=movement, num_mask=ncanvas if ncanvas.any() else None)


GROUP_BAR_COVER = 0.85   # a barline stroke covers this share of a staff's height
GROUP_BAR_SP = 0.5       # search window around a system barline, staff spaces


def group_bars(res: PageResult, idx: list[int], gsys: int, nums: list
               ) -> tuple[list[int], list[int], str]:
    """group_bars -> (x of the barlines common to all staves idx, the
    number of the bar that ends at each, why not).

    A system barline is common when every staff of the group has its own
    ink through the full staff height at that x (a Mensurstrich, a misread
    barline or a bar edit made without ink gives no stroke on a staff, so
    nobody cuts there). nums: the system's number per bar; a bar that
    holds dropped barlines keeps the number of its first bar. why: text
    for the re-flow report when no barline is left or the numbers cannot
    follow the merged bars (then no cut at all)."""
    allb = res.barlines.get(gsys, [])
    sp, thick = res.sp, res.thick
    w = max(1, int(round(GROUP_BAR_SP * sp)))
    kept: list[int] = []
    bad = ""
    for k, bx in enumerate(allb):
        for i in idx:
            st = res.staves[i]
            r0, r1 = max(0, int(st.top - thick)), int(st.bottom + thick) + 1
            band = res.owner[r0:r1, max(0, bx - w):bx + w + 1] == i
            if not band.size or band.mean(axis=0).max() < GROUP_BAR_COVER:
                bad = f"barline {k + 1} is not on every staff"
                break
        else:
            kept.append(k)
    if not kept:
        return [], [], bad or "no barline in the system"
    numbers: list[int] = []
    if nums:
        if len(nums) != len(allb) and len(kept) != len(allb):
            return [], [], "bar numbers do not match the barlines"
        if len(nums) == len(allb):
            numbers = [int(nums[(kept[j - 1] + 1) if j else 0]) for j in range(len(kept))]
    return [int(allb[k]) for k in kept], numbers, ""


def own_group_gap(lay: dict, name: str, opts: dict) -> float | None:
    """own_group_gap -> `group_gap` (sp) of a part or group: its own value in
    layout.parts, else the item's (a command-line value is in opts); None =
    the source distance between the staves."""
    own = (((lay.get("layout") or {}).get(PART_LAYOUT_KEY) or {}).get(name) or {})
    v = own.get("group_gap", opts.get("group_gap"))
    return None if v is None else float(v)


def group_strip(res: PageResult, sys_staves: list[int], runs: list[tuple[str, list[int]]],
                header_owner: int, darker: bool = False, bar_no: int | None = None,
                marks: list | None = None, movement: bool = False,
                nums: list | None = None, gap_sp: float | None = None,
                labels: bool = True) -> Strip:
    """group_strip -> one line of a group score: the staves of its parts
    (runs: (part, staff indices), score order), stacked at the source's
    staff distance. Staves of other parts between them leave no space
    (operator request 2026-10-24: Alto, then Tenor I, as if adjacent). The distance
    grows only where ink would come closer than 0.5 sp. Labels per part.
    gap_sp (0.3.0-dev.36, `group_gap`): the space between one staff's bottom
    line and the next staff's top line, in staff spaces, instead of the
    source distance (operator request 2026-10-27: the white between the staves may
    shrink); the 0.5 sp ink guard stays. labels=False: a part on two staves
    (no label column, not a group line)."""
    sp = res.sp
    idx_all = [i for _, ix in runs for i in ix]
    pos = {st: k for k, st in enumerate(sys_staves)}

    def bars(st: Strip, off: int) -> Strip:
        # barlines common to all staves, in strip coordinates (re-flow);
        # off: strip x minus page x
        bx, nn, why = group_bars(res, idx_all, res.staves[idx_all[0]].system, nums or [])
        st.bars_x = [int(b + off) for b in bx]
        st.bar_nums = nn
        end = max(res.staves[i].x1 for i in idx_all) + off
        st.ends_at_bar = bool(st.bars_x) and end - st.bars_x[-1] <= BAR_END_SP * sp
        st.end_gap_sp = (end - st.bars_x[-1]) / sp if st.bars_x else -1.0
        st.bars_why = why or ("" if st.ends_at_bar else "the line does not end at a barline")
        return st

    contiguous = all(pos[b] - pos[a] == 1 for a, b in zip(idx_all, idx_all[1:]))
    if contiguous and gap_sp is None:
        stp = make_strip(res, idx_all, header_owner, darker, bar_no=bar_no, marks=marks,
                         movement=movement)
        t0 = res.staves[idx_all[0]].top
        for name, ix in runs:
            stp.staff_labels.append((name, int(round(res.staves[ix[0]].top - t0)) + stp.staff_top,
                                     int(round(res.staves[ix[0]].bottom - t0)) + stp.staff_top))
        return bars(stp, stp.staff_x0 - min(res.staves[i].x0 for i in idx_all))
    # source distance from one staff to the next (top line to top line)
    tops = [res.staves[i].top for i in sys_staves]
    step = float(np.median(np.diff(tops))) if len(tops) > 1 else 12 * sp
    subs = []
    for k, (name, ix) in enumerate(runs):
        sub = make_strip(res, ix, header_owner if k == 0 else -999, darker,
                         bar_no=bar_no if k == 0 else None,
                         marks=marks if k == 0 else None, movement=movement)
        ox = min(res.staves[i].x0 for i in ix) - sub.staff_x0     # page x of column 0
        subs.append((name, ix, sub, ox))
    left = min(ox for *_, ox in subs)
    width = max(ox - left + sub.img.shape[1] for _, _, sub, ox in subs)
    # vertical place of each sub strip (row of its img top in the canvas)
    ys, prev = [], None
    for name, ix, sub, ox in subs:
        if prev is None:
            ys.append(0)
        else:
            pname, pix, psub, py = prev
            if gap_sp is not None:
                want = py + psub.staff_bottom + int(round(gap_sp * sp)) - sub.staff_top
            else:
                want = py + psub.staff_top + (res.staves[ix[0]].top - res.staves[pix[-1]].top
                                              if pos[ix[0]] - pos[pix[-1]] == 1 else
                                              (psub.staff_bottom - psub.staff_top) + step
                                              - 4 * sp) - sub.staff_top
            # no closer than 0.5 sp, ink to ink, column by column
            pc = psub.img.any(axis=0)
            pb = np.full(width, -10 ** 9)
            cols = np.flatnonzero(pc)
            last = psub.img.shape[0] - 1 - np.argmax(psub.img[::-1, cols], axis=0)
            pb[cols + prev_ox - left] = last + py
            nc = np.flatnonzero(sub.img.any(axis=0))
            first = np.argmax(sub.img[:, nc], axis=0)
            nt = np.full(width, 10 ** 9)
            nt[nc + ox - left] = first
            need = int(np.max(pb - nt)) + int(0.5 * sp) if nc.size and cols.size else want
            ys.append(int(round(max(want, need))))
        prev = (name, ix, sub, ys[-1])
        prev_ox = ox
    h = max(y + sub.img.shape[0] for y, (_, _, sub, _) in zip(ys, subs))
    img = np.zeros((h, width), bool)
    hdr = np.zeros_like(img)
    num = np.zeros_like(img)
    labels_ = []
    for y, (name, ix, sub, ox) in zip(ys, subs):
        x = ox - left
        sl = (slice(y, y + sub.img.shape[0]), slice(x, x + sub.img.shape[1]))
        img[sl] |= sub.img
        hdr[sl] |= sub.hdr
        if sub.num_mask is not None:
            num[sl] |= sub.num_mask
        labels_.append((name, y + sub.staff_top, y + sub.staff_top + int(round(4 * sp))))
    first_sub, last_sub = subs[0][2], subs[-1][2]
    out = Strip(img, subs[0][3] - left + first_sub.staff_x0, first_sub.staff_top,
                ys[-1] + last_sub.staff_bottom, sp, hdr, bar_no,
                marks=[(mx + subs[0][3] - left, t) for mx, t in first_sub.marks],
                movement=movement, num_mask=num if num.any() else None)
    out.staff_labels = labels_ if labels else []
    return bars(out, -left)


def profile(img: np.ndarray, staff_x0: int, nbins: int, bin_px: float
            ) -> tuple[np.ndarray, np.ndarray]:
    """Top and bottom ink row per x-bin, bins measured from staff_x0."""
    top = np.full(nbins, np.inf)
    bot = np.full(nbins, -np.inf)
    h = img.shape[0]
    xs = np.flatnonzero(img.any(axis=0))
    if not xs.size:
        return top, bot
    first = img[:, xs].argmax(axis=0)
    last = h - 1 - img[::-1, xs].argmax(axis=0)
    bins = ((xs - staff_x0) / bin_px).astype(int) + nbins // 2   # int(): toward 0
    ok = (bins >= 0) & (bins < nbins)
    np.minimum.at(top, bins[ok], first[ok].astype(float))
    np.maximum.at(bot, bins[ok], last[ok].astype(float))
    return top, bot


def profiles(s: Strip, nbins: int, bin_px: float
             ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """profiles -> (top of own ink, top of header ink, bottom of all ink).

    A strip with a bar number reserves its box (see bar_mark), like header
    ink."""
    a = anchor(s)
    t_own, _ = profile(s.img & ~s.hdr, a, nbins, bin_px)
    t_hdr, _ = profile(s.hdr, a, nbins, bin_px)
    _, bot = profile(s.img, a, nbins, bin_px)
    boxes = [(x0, top, x1) for x0, top, x1, *_ in reh_boxes(s)]
    boxes.extend(rb[:3] for rb in rest_boxes(s))
    if s.bar_no is not None:
        _, top, wpx = bar_mark(s)
        c0 = bar_x(s)
        boxes.append((c0, top, c0 + wpx))
    for x0, top, x1 in boxes:
        b0 = max(0, int((x0 - a) / bin_px) + nbins // 2)
        b1 = min(nbins, int(np.ceil((x1 - a) / bin_px)) + nbins // 2 + 1)
        t_hdr[b0:b1] = np.minimum(t_hdr[b0:b1], top)
    return t_own, t_hdr, bot


def rest_text(n: str) -> tuple[str, str, float, float]:
    """rest_text -> (text, font kind, size in sp, baseline above the top
    line in sp) for a multi-bar rest count: Bravura time-signature digits
    (U+E080..E089, 2 sp tall, centred on the baseline; em = 4 sp), else
    SemiBold Garamond."""
    if _font("music")[1]:
        return "".join(chr(0xE080 + int(d)) for d in n), "music", 4.0, 1.5
    return n, "bold", 2.6, 0.8


def rest_box(s: Strip, label: tuple | None = None) -> tuple[float, float, float, float, float, str, str] | None:
    """rest_box -> (x0, top, x1, baseline, font size, text, font kind) of
    the multi-bar rest count, centred above the H-bar, in strip px; None
    without one. label: (x, text) of one count (default: the line's own)."""
    label = label or s.rest_label
    if not label:
        return None
    cx, n = label
    t, kind, size, raise_ = rest_text(n)
    fs = size * s.sp
    w = text_len(t, kind, fs)
    base = s.staff_top - raise_ * s.sp
    top = base - (1.0 * s.sp if kind == "music" else 0.72 * fs)
    return (cx - w / 2, top, cx + w / 2, base, fs, t, kind)


def rest_boxes(s: Strip) -> list[tuple[float, float, float, float, float, str, str]]:
    """rest_boxes -> the rest_box of every count of a line: the line's own
    (a line that is only a rest) and those of merged bars inside it."""
    return [b for b in (rest_box(s), *(rest_box(s, lb) for lb in s.rest_labels)) if b]


REH_SIZE = 2.6        # rehearsal letter size, staff spaces
REH_PAD = 0.3         # box padding, staff spaces


def reh_boxes(s: Strip) -> list[tuple[float, float, float, float, str, float, float]]:
    """reh_boxes -> [(x0, top, x1, bottom, letter, font size, baseline)] in
    strip px: a boxed bold letter at the start of its bar, above the staff
    and clear of the ink below it (like a bar number)."""
    out = []
    pad = REH_PAD * s.sp
    for mx, t in s.marks:
        fs = REH_SIZE * s.sp
        tw = text_len(t, "bold", fs)
        x0 = float(mx) + (0.0 if mx <= s.staff_x0 + 2 else 0.3 * s.sp)
        x1 = x0 + tw + 2 * pad
        cols = s.img[:, max(0, int(x0)):int(x1) + 1]
        rows = np.flatnonzero(cols.any(axis=1)) if cols.size else np.array([])
        ink_top = float(rows.min()) if rows.size else float(s.staff_top)
        bottom = min(s.staff_top - s.bar_raise * s.sp, ink_top - 0.4 * s.sp)
        top = bottom - 0.72 * fs - 2 * pad
        out.append((x0, top, x1, bottom, t, fs, bottom - pad))
    return out


def bar_x(s: Strip) -> float:
    """Left edge of the bar number: the staff start, or right of a
    rehearsal letter that also stands at the line start."""
    x = float(max(0, s.staff_x0))
    for x0, _, x1, *_ in reh_boxes(s):
        if x0 <= s.staff_x0 + 2:
            x = max(x, x1 + 0.4 * s.sp)
    return x


BAR_CLEAR_SP = 0.5    # bar number above the clef / first ink by this


def bar_mark(s: Strip) -> tuple[float, float, float]:
    """bar_mark -> (baseline row, top row, width px) of the bar number in
    strip coordinates. Left edge at the staff start (above the clef, as
    engravers set it). Baseline at least bar_raise sp above the top line and
    BAR_CLEAR_SP above any ink in the number's columns (clef, header text)."""
    size = s.bar_size * s.sp
    wpx = text_len(str(s.bar_no), "italic", size)
    c0 = int(bar_x(s))
    cols = s.img[:, c0:int(c0 + wpx) + 2]
    rows = np.flatnonzero(cols.any(axis=1))
    ink_top = float(rows.min()) if rows.size else float(s.staff_top)
    base = min(s.staff_top - s.bar_raise * s.sp, ink_top - BAR_CLEAR_SP * s.sp)
    return base, base - 0.72 * size, wpx


def set_bar_geometry(stp: Strip, res: PageResult, idx: list[int], gsys: int,
                     nums: list) -> None:
    """Barlines of the strip's system in strip coordinates, the number of
    each bar, and whether the line ends at a barline."""
    sx = min(res.staves[i].x0 for i in idx)
    off = stp.staff_x0 - sx
    stp.bars_x = [int(b + off) for b in res.barlines.get(gsys, [])]
    stp.bar_nums = [int(n) for n in nums]
    end = max(res.staves[i].x1 for i in idx) + off
    # a repeat or final barline (thin + thick) is found at its middle
    stp.ends_at_bar = bool(stp.bars_x) and end - stp.bars_x[-1] <= BAR_END_SP * res.sp
    stp.end_gap_sp = (end - stp.bars_x[-1]) / res.sp if stp.bars_x else -1.0


def anchor(s: Strip) -> int:
    """Alignment line of a strip (px in img): the staff start, less the
    indent. Every line of a part puts this column at the left margin."""
    return s.staff_x0 - s.indent


def _profiles_cached(s: Strip, nbins: int) -> tuple:
    if getattr(s, "_prof", None) is None:
        s._prof = profiles(s, nbins, s.sp)          # type: ignore[attr-defined]
    return s._prof                                   # type: ignore[attr-defined]


def pitches(strips: list[Strip], opts: dict) -> list[float]:
    """pitches -> staff-top to staff-top distance (source px) after each
    strip: the constant pitch (staff height + `gap` staff spaces), larger
    only where ink of two strips would come closer than `clearance`
    (header ink: HEADER_CLEAR_SP). Constant leading, so the eye can predict
    where the next line is."""
    nb = 400
    out = []
    for a, b in zip(strips, strips[1:]):
        base = (a.staff_bottom - a.staff_top) + opts["gap"] * a.sp
        clear = opts["clearance"]
        n_st = len(a.staff_labels)
        if n_st > 1:
            # a group score: systems apart by more than their staves (operator request
            # 2026-10-24: two systems almost touched). 1.5 x the space
            # between the staves of the system, at least `gap`; ink 3 sp apart
            inner = ((a.staff_bottom - a.staff_top) - n_st * 4 * a.sp) / (n_st - 1)
            base = (a.staff_bottom - a.staff_top) + max(opts["gap"] * a.sp,
                                                        SYSTEM_GAP_FACTOR * inner)
            clear = max(clear, SYSTEM_CLEAR_SP)
        if b.movement:                 # a new movement: double leading
            base += opts["gap"] * a.sp
        _, _, pb = _profiles_cached(a, nb)
        t_own, t_hdr, _ = _profiles_cached(b, nb)
        req = 0.0
        for t, c in ((t_own, clear),
                     (t_hdr, max(clear, HEADER_CLEAR_SP))):
            both = np.isfinite(t) & np.isfinite(pb)
            if both.any():
                req = max(req, float(np.max((pb[both] - a.staff_top)
                                            - (t[both] - b.staff_top))) + c * a.sp)
        out.append(max(base, req))
    return out


def ambitus_width(sp: float = AMB_SP) -> float:
    return 8.0 * sp
