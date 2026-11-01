# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""Clef signature, notehead steps and ambitus maths."""
from __future__ import annotations

import copy
import re

from .config import OWN_NONE, SKIP_KEY
from .mapping import CONTINUO_RE
from .model import Staff
from .typography import _font


# =============================================================================
# Clef signature
# =============================================================================
def clef_features(owner: np.ndarray, line_px: np.ndarray, st: Staff,
                  idx: int, sp: float, thick: int) -> tuple[float, float, float] | None:
    """clef_features -> (top, bottom, has_bar) of the clef blob: top
    relative to the top line, bottom relative to the bottom line, in
    staff spaces (negative = above); has_bar 1.0 when a column in the left
    part covers 80% of the blob height (C clef), else 0.0. None if no
    blob.

    The staff's own ink without staff lines, in the first 3.5 sp; barline
    columns (vertical cover >= 85% of the staff height) are removed; a
    vertical closing rejoins pieces cut by line removal; the largest blob
    is the clef."""
    import cv2
    import numpy as np
    x0 = max(0, int(st.x0 - 0.2 * sp))
    x1 = int(st.x0 + 3.5 * sp)
    y0 = max(0, int(st.top - 3 * sp))
    y1 = int(st.bottom + 3 * sp)
    blk = ((owner[y0:y1, x0:x1] == idx) & ~line_px[y0:y1, x0:x1]).astype(np.uint8)
    if blk.sum() < 0.5 * sp * sp:
        return None
    r0, r1 = int(st.top - y0), int(st.bottom - y0)
    cover = blk[r0:r1 + 1].sum(axis=0) / max(1, r1 - r0 + 1)
    bar = cover >= 0.85
    bar[int(st.x0 + 0.5 * sp) - x0:] = False      # barline only at the start
    blk[:, bar] = 0
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 2 * thick + 3))
    blk = cv2.morphologyEx(blk, cv2.MORPH_CLOSE, k)
    n, lab, stt, _ = cv2.connectedComponentsWithStats(blk, connectivity=8)
    if n <= 1:
        return None
    c = 1 + int(np.argmax(stt[1:, cv2.CC_STAT_AREA]))
    x, y, cw, ch, area = stt[c]
    if area < 0.5 * sp * sp or ch < 2.0 * sp:
        return None
    top = (y + y0 - st.top) / sp
    bot = (y + ch - 1 + y0 - st.bottom) / sp
    sub = lab[y:y + ch, x:x + cw] == c
    colcov = sub.sum(axis=0) / ch                 # tall bar in the left part?
    has_bar = bool((colcov[: max(1, int(0.45 * cw))] >= 0.8).any())
    return top, bot, (1.0 if has_bar else 0.0)


CLEF_GLYPHS = {"G": 0xE050, "C": 0xE05C, "F": 0xE062}   # SMuFL gClef, cClef, fClef
# clef and line (1 = bottom line) that scores use: G2 treble, G1 French
# violin; C1 soprano, C2 mezzo, C3 alto, C4 tenor, C5 baritone; F3
# baritone, F4 bass, F5 sub-bass (operator request 2026-10-24)
CLEF_CANDIDATES = [("G", 2), ("G", 1), ("C", 1), ("C", 2), ("C", 3), ("C", 4), ("C", 5),
                   ("F", 3), ("F", 4), ("F", 5)]
_CLEF_TPL: dict = {}
CLEF_MIN_NCC = 0.55         # Maria (scan): right reads 0.66-0.98
CLEF_COMMON = {"G2", "G8", "C1", "C3", "C4", "F4"}
CLEF_RARE_LEAD = 0.05       # a rare clef (G1, C2, C5, F3, F5) must lead the best common one
CLEF_LAST: dict = {}        # idx -> (label, score, margin) of the last page (diagnosis)


def _clef_template(kind: str, sp: float, scale: float) -> tuple[np.ndarray, int] | None:
    """_clef_template -> (bool glyph, row of its reference line) from
    Bravura at staff space sp (SMuFL: em = 4 sp, the glyph's baseline is
    the clef's line); None without the font."""
    import numpy as np
    import pymupdf
    key = (kind, round(sp * scale, 1))
    if key in _CLEF_TPL:
        return _CLEF_TPL[key]
    _, file, _ = _font("music")
    if not file:
        _CLEF_TPL[key] = None
        return None
    fs = 4.0 * sp * scale                      # px at 72 dpi = pt
    doc = pymupdf.open()
    page = doc.new_page(width=fs * 2, height=fs * 3)
    base = fs * 1.6
    page.insert_text((fs * 0.2, base), chr(CLEF_GLYPHS[kind]), fontsize=fs,
                     fontname="pt-music", fontfile=file)
    pix = page.get_pixmap(dpi=72, colorspace=pymupdf.csGRAY)
    g = np.frombuffer(pix.samples, np.uint8).reshape(pix.h, pix.w)
    m = g < 128
    rows, cols = np.flatnonzero(m.any(axis=1)), np.flatnonzero(m.any(axis=0))
    if not rows.size:
        _CLEF_TPL[key] = None
        return None
    tpl = m[rows[0]:rows[-1] + 1, cols[0]:cols[-1] + 1]
    _CLEF_TPL[key] = (tpl, int(round(base)) - rows[0])
    return _CLEF_TPL[key]


def clef_blob(owner: np.ndarray, line_px: np.ndarray, st: Staff, idx: int, sp: float,
              thick: int) -> dict | None:
    """clef_blob -> the clef's ink at the staff start (first 3.3 sp; a
    barline or bracket at the start removed; gaps from line removal
    closed): main (largest blob), dots (small pieces right of its centre,
    inside the staff: an F clef's dots), raw (main and dots with the staff
    lines kept, for the comparison with glyphs), x0, y0 (page position of
    the masks). None when there is no clef-sized blob."""
    import cv2
    import numpy as np
    # from 0.25 sp after the staff start: the system barline and bracket
    # stand there, a clef never
    x0 = max(0, int(st.x0 + 0.25 * sp))
    x1 = int(st.x0 + 3.4 * sp)
    y0 = max(0, int(st.top - 3 * sp))
    y1 = int(st.bottom + 3 * sp)
    blk = ((owner[y0:y1, x0:x1] == idx) & ~line_px[y0:y1, x0:x1]).astype(np.uint8)
    # barline or bracket: ink through the whole window height (3 sp above
    # to 3 sp below the staff); a clef never. Its bars matched a C clef
    # (Schein Nun p2: G2 read as C3)
    anyink = owner[y0:y1, x0:x1] != OWN_NONE
    full = anyink.mean(axis=0) >= 0.9
    if full.any():
        full = cv2.dilate(full.astype(np.uint8)[None, :],
                          np.ones((1, 2 * thick + 1), np.uint8))[0] > 0
        blk[:, full] = 0
    if blk.sum() < 0.5 * sp * sp:
        return None
    r0, r1 = int(st.top - y0), int(st.bottom - y0)
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 2 * thick + 3))
    blk = cv2.morphologyEx(blk, cv2.MORPH_CLOSE, k)
    n, lab, stt, _ = cv2.connectedComponentsWithStats(blk, connectivity=8)
    if n <= 1:
        return None
    c = 1 + int(np.argmax(stt[1:, cv2.CC_STAT_AREA]))
    bx, by, bw, bh, area = stt[c]
    if area < 0.5 * sp * sp or bh < 2.0 * sp:
        return None
    dots = []
    for j in range(1, n):
        x, y, w, h, a = stt[j]
        cx, cy = x + w / 2, y + h / 2
        if j != c and 0.02 * sp * sp <= a <= 0.6 * sp * sp and bx + bw / 2 < cx <= bx + bw + 0.9 * sp \
           and r0 - 0.3 * sp <= cy <= r1 + 0.3 * sp and max(w, h) <= 1.4 * sp:
            dots.append(j)
    keep = np.zeros(n, bool)
    keep[[c] + dots] = True
    mask = keep[lab]
    own = owner[y0:y1, x0:x1] == idx
    if full.any():
        own[:, full] = False
    raw = own.copy()
    raw[:, ~mask.any(axis=0)] = False
    near = cv2.dilate(mask.astype(np.uint8), np.ones((int(sp) | 1, int(sp) | 1), np.uint8)) > 0
    raw &= near
    mm = (lab == c)[by:by + bh, bx:bx + bw]
    sym = float((mm & mm[::-1]).sum()) / max(1, int((mm | mm[::-1]).sum()))
    # a C clef's bars: columns in its left part covering most of its height
    colcov = mm.sum(axis=0) / max(1, bh)
    barcov = float(colcov[:max(1, int(0.45 * bw))].max())
    return {"main": lab == c, "box": (bx, by, bw, bh), "dots": [stt[j] for j in dots],
            "raw": raw, "x0": x0, "y0": y0, "sym": sym, "barcov": barcov}


# ── Ambitus (DESIGN.md §4.3 item 13): noteheads per staff ───────────────────
# staff step 0 = bottom line, 1 = the space above it, ...; diatonic number
# of the bottom line per clef (C0 = 0, 7 per octave)
CLEF_BOTTOM = {"G2": 30, "G8": 23, "G1": 32, "C1": 28, "C2": 26, "C3": 24, "C4": 22,
               "C5": 20, "F3": 20, "F4": 18, "F5": 16}
NOTE_NAMES = "CDEFGAB"


def pitch_name(d: int) -> str:
    """pitch_name 30 -> 'E4' (diatonic number, scientific pitch)."""
    return f"{NOTE_NAMES[d % 7]}{d // 7}"


ACC_MARK = {0: "", 1: "#", -1: "b"}
ACC_GLYPH = {1: "\ue262", -1: "\ue260"}      # SMuFL accidentalSharp, accidentalFlat


def parse_pitch(name: str) -> tuple[int, int]:
    """parse_pitch 'F#3' -> (diatonic number, alteration +1 / 0 / -1).
    Accepts # and b (or the symbols); ValueError on a bad name."""
    m = re.fullmatch(r"([A-Ga-g])([#b\u266f\u266d]?)(-?\d)", name.strip())
    if not m:
        raise ValueError(f"not a note: {name!r} (letter, optional # or b, octave; "
                         "e.g. C4, F#3, Bb2)")
    alt = {"#": 1, "\u266f": 1, "b": -1, "\u266d": -1}.get(m.group(2), 0)
    return int(m.group(3)) * 7 + NOTE_NAMES.index(m.group(1).upper()), alt


def pitch_num(name: str) -> int:
    """pitch_num 'E4' -> 30; 'F#3' -> 24 (the staff position; the
    accidental is dropped, see parse_pitch). ValueError on a bad name."""
    return parse_pitch(name)[0]


def pitch_str(d: int, alt: int = 0) -> str:
    """pitch_str 24, 1 -> 'F#3'."""
    return pitch_name(d)[0] + ACC_MARK[alt] + pitch_name(d)[1:]


def order_pitches(a: tuple[int, int], b: tuple[int, int]) -> tuple[tuple[int, int], tuple[int, int]]:
    """order_pitches -> (lower, higher); equal staff positions: flat < natural < sharp."""
    return (a, b) if a <= b else (b, a)


AMBITUS_FROM = ("auto", "on", "operator", "off")


def part_clef_steps(data: dict, part: str) -> tuple[str | None, list[int]]:
    """part_clef_steps -> (first clef of the part, diatonic numbers of its
    lowest and highest noteheads per staff) from the systems' maps.
    Clefs are smoothed along the part (a misread clef shifts every note):
    a clef unlike both neighbouring systems of the part, which agree (at
    either end: unlike the next three, which agree), takes theirs; a part with G8
    on a quarter or more of its staves is G8 where G2 was read (the 8 is
    missed more often than invented). Real clef changes last."""
    seq = part_clef_seq(data, part)
    clef, nums = None, []
    for c, st_, _, _ in seq:
        if clef is None and c in CLEF_BOTTOM:
            clef = c
        if st_ and c in CLEF_BOTTOM:
            nums += [CLEF_BOTTOM[c] + int(st_[0]), CLEF_BOTTOM[c] + int(st_[1])]
    return clef, nums


def part_clef_seq(data: dict, part: str) -> list[list]:
    """part_clef_seq -> [[clef (smoothed), steps, system id, staff], ...]
    of a part in score order (see part_clef_steps)."""
    seq = []
    for e in data.get("systems") or []:
        steps = e.get("steps") or []
        clefs = e.get("clefs") or []
        for k, x in enumerate(e.get("map") or []):
            if x == part:
                seq.append([clefs[k] if k < len(clefs) else "?",
                            steps[k] if k < len(steps) else None, e["id"], k])
    cl = [it[0] for it in seq]
    n_ = len(cl)
    for i, c in enumerate(cl):
        if 0 < i < n_ - 1:
            a_, b_ = cl[i - 1], cl[i + 1]
            if a_ == b_ and a_ in CLEF_BOTTOM and c != a_:
                seq[i][0] = a_
        elif n_ >= 4:                         # an end: the next three agree
            nxt = cl[1:4] if i == 0 else cl[-4:-1]
            if len(set(nxt)) == 1 and nxt[0] in CLEF_BOTTOM and c != nxt[0]:
                seq[i][0] = nxt[0]
    n8 = sum(1 for it in seq if it[0] == "G8")
    if n8 and n8 >= 0.25 * sum(1 for it in seq if it[0] in ("G2", "G8")):
        for it in seq:
            if it[0] == "G2":
                it[0] = "G8"
    return seq


def extreme_bar(data: dict, sid: str, st_: list, which: str) -> int | None:
    """extreme_bar -> the bar number of a staff's lowest or highest note
    (bar index stored at analysis, numbered with the system's bar_nums)."""
    k = 4 if which == "low" else 5
    if len(st_) <= k:
        return None
    e = next((x for x in data.get("systems") or [] if x["id"] == sid), None)
    nums = (e or {}).get("bar_nums") or []
    i = int(st_[k])
    return int(nums[min(i, len(nums) - 1)]) if nums else None


def ambitus_report(data: dict, part: str) -> dict:
    """ambitus_report -> {'low': [bars], 'high': [bars], 'doubts': [text]}
    for a part's computed extremes. An extreme is doubtful when it is seen
    on one staff only and stands 3 or more steps beyond the next, or 2 or
    more ledger lines out, or 4 or more steps beyond the next at all
    (lyrics, figures, "Cap." gave such values; 0.3.0-dev.19). A doubt is
    a question, not a cut: every note counts."""
    seq = [it for it in part_clef_seq(data, part) if it[1] and it[0] in CLEF_BOTTOM]
    out = {"low": [], "high": [], "doubts": [], "low_at": [], "high_at": [],
           "suggest": "", "why": ""}
    if not seq:
        return out
    ends = {}
    for which, k, sign in (("low", 0, 1), ("high", 1, -1)):
        vals = [(CLEF_BOTTOM[c] + int(st_[k]), int(st_[k]), sid, st_) for c, st_, sid, _ in seq]
        vals.sort(key=lambda v: sign * v[0])
        ext = vals[0][0]
        at = [v for v in vals if v[0] == ext]
        out[which] = sorted({b for b in (extreme_bar(data, v[2], v[3], which) for v in at) if b})
        out[which + "_at"] = [f"bar {extreme_bar(data, v[2], v[3], which) or '?'} "
                              f"(page {v[2][1:].split('.')[0]}, system {v[2].split('.s')[-1]})"
                              for v in at][:3]
        nxt = next((v[0] for v in vals if v[0] != ext), None)
        gap = abs(ext - nxt) if nxt is not None else 0
        ledgers = max(0, (-at[0][1] if which == "low" else at[0][1] - 8) // 2)
        bars = "; ".join(out[which + "_at"]) or "?"
        ends[which] = ext
        if len(at) == 1 and (gap >= 3 or ledgers >= 2) or gap >= 4:
            if nxt is not None:
                # if the doubtful note is wrong (a letter, a beam, a sharp),
                # the range ends at the next note found
                ends[which] = nxt
                out["why"] += (f"{'; ' if out['why'] else ''}{which} {pitch_name(ext)} left "
                               f"out: next {'lowest' if which == 'low' else 'highest'} "
                               f"{pitch_name(nxt)}")
            why = []
            if len(at) == 1:
                why.append("seen once")
            if gap >= 3:
                why.append(f"{gap} steps beyond the next ({pitch_name(nxt)})")
            if ledgers >= 2:
                why.append(f"{ledgers} ledger lines")
            out["doubts"].append(f"{which} {pitch_name(ext)} ({bars}): {', '.join(why)}")
    if out["doubts"] and out["why"]:
        out["suggest"] = f"{pitch_name(ends['low'])}-{pitch_name(ends['high'])}"
    return out


def part_extremes(data: dict, part: str) -> list[tuple[str, int, str, int, int]]:
    """part_extremes -> [(system id, staff, 'low' | 'high', x, diatonic)]:
    where the part's computed lowest and highest notes stand (for the
    proof)."""
    seq = [it for it in part_clef_seq(data, part) if it[1] and it[0] in CLEF_BOTTOM]
    if not seq:
        return []
    lows = [CLEF_BOTTOM[c] + int(st_[0]) for c, st_, _, _ in seq]
    highs = [CLEF_BOTTOM[c] + int(st_[1]) for c, st_, _, _ in seq]
    lo, hi = min(lows), max(highs)
    out = []
    for (c, st_, sid, k), a_, b_ in zip(seq, lows, highs):
        if a_ == lo:
            out.append((sid, k, "low", int(st_[2]) if len(st_) > 2 else 0, a_))
        if b_ == hi:
            out.append((sid, k, "high", int(st_[3]) if len(st_) > 3 else 0, b_))
    return out


def refresh_ambitus(data: dict) -> dict:
    """refresh_ambitus -> data['ambitus']: {part: {range, from}} for every
    extracted part. from: auto (computed from the noteheads), on (computed
    for a continuo-like part), operator (set by hand: kept), off (none; the
    default for continuo-like names: figures and realisations mislead)."""
    old = data.get("ambitus") or {}
    skip = set(data.get(SKIP_KEY) or [])
    out = {}
    for part in data.get("parts") or []:
        if part in skip or part == "-":
            continue
        o = old.get(part) or {}
        frm = o.get("from") if o.get("from") in AMBITUS_FROM else (
            "off" if CONTINUO_RE.search(part) else "auto")
        if frm in ("operator", "off"):
            out[part] = {"range": o.get("range", "") if frm == "operator" else "", "from": frm}
            continue
        _, nums = part_clef_steps(data, part)
        rng = f"{pitch_name(min(nums))}-{pitch_name(max(nums))}" if nums else ""
        out[part] = {"range": rng, "from": frm}
    data["ambitus"] = out
    return out


def ambitus_for(data: dict, part: str) -> tuple[str, int, int, int, int] | None:
    """ambitus_for -> (clef, lowest, highest, lowest alteration, highest
    alteration) to print, or None."""
    a = (data.get("ambitus") or {}).get(part) or {}
    rng = a.get("range") or ""
    if a.get("from") == "off" or "-" not in rng:
        return None
    clef, _ = part_clef_steps(data, part)
    try:
        lo, hi = order_pitches(*(parse_pitch(x) for x in rng.split("-", 1)))
    except ValueError:
        return None
    return (clef or "G2", lo[0], hi[0], lo[1], hi[1])


def _wide_run(ink: np.ndarray, x: int, y: int, w: int, h: int, sp: float,
              thick: int) -> float:
    """Height (px) of the run of rows through a candidate head where the ink
    in its columns is 0.35 sp wide or more, gaps from staff-line removal
    (up to 2 thick + 3) bridged. A head gives about 1 sp (its stem is
    narrow); a digit 2 sp, a stacked time signature 4 sp."""
    r0, r1 = max(0, int(y - 2.5 * sp)), min(ink.shape[0], int(y + h + 2.5 * sp))
    wide = ink[r0:r1, x:x + w].sum(axis=1) >= 0.35 * sp
    gap = 2 * thick + 3
    c = int(y + h / 2) - r0
    if c < 0 or c >= wide.size:
        return float(h)
    if not wide[c]:                     # the centre on a removed staff line
        near = [k for k in range(max(0, c - gap), min(wide.size, c + gap + 1)) if wide[k]]
        if not near:
            return float(h)
        c = min(near, key=lambda k: abs(k - c))
    top = c
    while top > 0:
        k = top - 1
        while k >= 0 and not wide[k] and top - k <= gap:
            k -= 1
        if k >= 0 and wide[k]:
            top = k
        else:
            break
    bot = c
    while bot < wide.size - 1:
        k = bot + 1
        while k < wide.size and not wide[k] and k - bot <= gap:
            k += 1
        if k < wide.size and wide[k]:
            bot = k
        else:
            break
    return float(bot - top + 1)


def _ledger_beside(own: np.ndarray, ly: float, x: int, w: int, sp: float,
                   thick: int) -> bool:
    """A ledger line at row ly: on both sides of the head (0.3 sp beside
    it), ink in a thin band around ly and none 0.35 sp above or below it
    (letters and figures have tall strokes there)."""
    H, W = own.shape
    r0, r1 = int(ly - thick - 1), int(ly + thick + 2)
    q0, q1 = int(ly - 0.45 * sp), int(ly + 0.45 * sp)
    if q0 < 0 or q1 > H:
        return False
    for c0, c1 in ((int(x - 0.3 * sp), x - 1), (x + w + 1, int(x + w + 0.3 * sp))):
        c0, c1 = max(0, c0), min(W, c1)
        if c1 - c0 < 2:
            return False
        band = own[r0:r1, c0:c1].any(axis=0)
        if band.mean() < 0.8:
            return False
        outside = own[q0:q1, c0:c1].copy()
        outside[r0 - q0:r1 - q0] = False
        if outside.any(axis=0).mean() > 0.3:
            return False
    return True


def note_steps(owner: np.ndarray, line_px: np.ndarray, st: "Staff", idx: int,
               sp: float, thick: int, heads_out: list | None = None,
               blank: list | None = None, barxs: list | None = None) -> tuple | None:
    """note_steps -> (lowest step, highest step, noteheads found) of a staff,
    or None. Noteheads: the staff's ink after the clef without its staff
    lines, holes filled (half and whole notes), opened with an ellipse
    0.8 x 0.7 sp (stems, beams, slurs and text strokes go); blobs 0.7 sp
    or more high and 0.9-2.0 sp wide. A stacked chord gives a taller blob:
    its top and bottom head count. A head 1 sp or more outside the staff
    needs the ledger line nearest the staff beside it (lyrics and figures
    have none). A single head is 1.1 times as wide as high or more
    (letters and time-signature digits are not); printed bar numbers and
    the barlines (1.2 sp each side) are blanked. Accidentals are not
    read: the steps are letter names.
    Returns (lowest, highest, count, x of the lowest, x of the highest)."""
    import cv2
    import numpy as np
    x0 = int(st.x0 + 3.5 * sp)
    x1 = int(st.x1)
    y0 = max(0, int(st.top - 6 * sp))
    y1 = min(owner.shape[0], int(st.bottom + 6 * sp))
    if x1 - x0 < 2 * sp:
        return None
    own = owner[y0:y1, x0:x1] == idx
    for bx0, by0, bx1, by1 in blank or []:     # printed bar numbers
        own[max(0, by0 - y0):max(0, by1 - y0 + 1), max(0, bx0 - x0):max(0, bx1 - x0 + 1)] = False
    m = (own & ~line_px[y0:y1, x0:x1]).astype(np.uint8)
    orig = m.astype(bool)
    # rejoin a head cut by line removal (thick + 2: a larger kernel bridged
    # line remnants into blobs on empty staves, Maria p7 Tenore I)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE,
                         cv2.getStructuringElement(cv2.MORPH_RECT, (1, thick + 2)))
    # close the ring of a half or whole note broken by line removal (a
    # small round kernel; Maria p10 Tenore II: most half notes missed)
    rk = max(3, int(round(0.4 * sp)) | 1)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE,
                         cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (rk, rk)))
    # fill holes: half and whole noteheads become solid
    inv = (1 - m).astype(np.uint8)
    ff = inv.copy()
    msk = np.zeros((ff.shape[0] + 2, ff.shape[1] + 2), np.uint8)
    cv2.floodFill(ff, msk, (0, 0), 0)
    m = m | ff
    kw, kh = max(3, int(round(0.8 * sp))), max(3, int(round(0.7 * sp)))
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN,
                         cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kw, kh)))
    n, lab, stt, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
    top_y, bot_y = st.top - y0, st.bottom - y0
    lo = hi = None
    xlo = xhi = 0
    count = 0
    cands: list[tuple[float, float, int]] = []
    half = sp / 2.0
    for j in range(1, n):
        x, y, w, h, a = stt[j]
        if not (0.9 * sp <= w <= 2.0 * sp and 0.7 * sp <= h <= 6.0 * sp):
            continue
        if a < 0.5 * w * h:
            continue
        if a > 0.88 * w * h and h < 0.9 * sp:
            continue                               # a block: whole or half rest
        if h <= 1.4 * sp and _wide_run(orig, x, y, w, h, sp, thick) >= 1.7 * sp:
            continue                               # a digit (time signature): wide ink
                                                   # 2 sp or more high (Maria p10 3/2)
        if h <= 1.4 * sp and w < 1.1 * h:
            continue                               # a head is wider than high; letters
                                                   # ("Cap."), digits are not (Maria p10)
        if orig[y:y + h, x:x + w][lab[y:y + h, x:x + w] == j].mean() < 0.35:
            continue                               # mostly filled space, little ink
        if h > 1.4 * sp:
            # a chord, or a head with ledger lines filled between them: a
            # head is a band of real ink 0.45 sp or more high (a ledger
            # line is a few rows; Maria p1.s2 gave G1 for C2)
            rows = (orig[y:y + h, x:x + w] & (lab[y:y + h, x:x + w] == j)).sum(axis=1) >= 0.4 * sp
            runs, r0_ = [], None
            for r_, ok in enumerate(list(rows) + [False]):
                if ok and r0_ is None:
                    r0_ = r_
                elif not ok and r0_ is not None:
                    if r_ - r0_ >= 0.45 * sp:
                        runs.append((r0_, r_))
                    r0_ = None
            if not runs:
                continue
            heads = [y + max(runs[0][0] + 0.5 * sp, (runs[0][0] + runs[0][1]) / 2.0),
                     y + min(runs[-1][1] - 0.5 * sp, (runs[-1][0] + runs[-1][1]) / 2.0)]
        else:
            heads = [y + h / 2.0]
        for yc in heads:
            step = int(round((bot_y - yc) / half))
            if step == 9 and y + h < top_y - 2 * thick:
                continue                           # floats above: text, not a head
            if step == -1 and y > bot_y + 2 * thick:
                continue
            if step >= 10 or step <= -2:           # needs every ledger line
                # between the staff and the head (a lyric under a ledger
                # note passed with the first one only: Maria p11 F1)
                need = range(10, step + 1, 2) if step >= 10 else range(-2, step - 1, -2)
                if not all(_ledger_beside(own, bot_y - ls * half, x, w, sp, thick)
                           for ls in need):
                    continue
            if step > 16 or step < -8:
                continue
            cands.append((x0 + x + w / 2.0, y0 + yc, step))
    # a time signature after the clef or a barline: two "heads" at one x,
    # one in the upper half of the staff, one in the lower (Maria p10 3/2)
    starts = [st.x0 + 3.5 * sp] + [float(b) for b in barxs or []]
    drop = set()
    half_rows = int(2 * sp)
    for i_, (xa, _, sa) in enumerate(cands):
        if not any(0 <= xa - b <= 7 * sp for b in starts):
            continue
        # stacked digits fill both halves of the staff in these columns
        # (rows 0.2 sp wide or more; a stem is narrower)
        ca, cb = int(xa - 0.6 * sp - x0), int(xa + 0.6 * sp - x0)
        band = orig[:, max(0, ca):max(0, cb)].sum(axis=1) >= max(4, 0.2 * sp)
        t_, b_ = int(top_y), int(bot_y)
        mid = (t_ + b_) // 2
        if band[t_:mid].sum() >= 0.45 * half_rows and band[mid:b_].sum() >= 0.45 * half_rows:
            drop.add(i_)
            continue
        for j_, (xb, _, sb) in enumerate(cands):
            if j_ != i_ and abs(xa - xb) <= 0.4 * sp and 5 <= sa <= 7 and 1 <= sb <= 3:
                drop |= {i_, j_}
    for i_, (xc, yc, step) in enumerate(cands):
        if i_ in drop:
            continue
        count += 1
        if heads_out is not None:
            heads_out.append((xc, yc, step))
        if lo is None or step < lo:
            lo, xlo = step, int(xc)
        if hi is None or step > hi:
            hi, xhi = step, int(xc)
    return (lo, hi, count, xlo, xhi) if count else None


CLEF_SHIFTS = (0.0, 0.5, 1.0)   # staff start offsets tried, sp (right only: left takes in the barline)


def clef_signature(owner: np.ndarray, line_px: np.ndarray, st: Staff,
                   idx: int, sp: float, thick: int = 3) -> str:
    """clef_signature -> the clef read at several staff-start offsets
    (CLEF_SHIFTS), the one with the best glyph match. A start 0.57 sp off
    turned G2 and F4 into C3 (Schein Nun p6.s1, 0.3.0-dev.12): the
    window is fixed to the measured start."""
    best_lab, best_sc = "?", -1.0
    for d in CLEF_SHIFTS:
        s2 = copy.copy(st)
        s2.x0 = int(round(st.x0 + d * sp))
        lab, sc = _clef_once(owner, line_px, s2, idx, sp, thick)
        if sc > best_sc + 0.01:                 # ties: the measured start
            best_lab, best_sc = lab, sc
    if best_lab == "G2" and _octave_eight_below(owner, st, idx, sp):
        best_lab = "G8"                          # tenor clef: treble, an octave lower
    CLEF_LAST[idx] = (best_lab, round(best_sc, 3))
    return best_lab if best_sc >= CLEF_MIN_NCC else "?"


def _octave_eight_below(owner: np.ndarray, st: Staff, idx: int, sp: float) -> bool:
    """A small '8' under a G clef (vocal tenor): a piece 0.5-1.7 sp high,
    0.3-1.2 sp wide, with a hole, 1.2-4 sp below the bottom line, centred
    under the clef (0.8-2.6 sp after the staff start; lyrics start later)."""
    import cv2
    import numpy as np
    x0, x1 = max(0, int(st.x0 + 0.25 * sp)), int(st.x0 + 3.4 * sp)
    y0, y1 = int(st.bottom + 1.2 * sp), min(owner.shape[0], int(st.bottom + 4.0 * sp))
    if y1 <= y0:
        return False
    m = (owner[y0:y1, x0:x1] == idx).astype(np.uint8)
    n, lab, stt, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
    for j in range(1, n):
        x, y, w, h, a = stt[j]
        if not (0.5 * sp <= h <= 1.7 * sp and 0.3 * sp <= w <= 1.2 * sp):
            continue
        cx = x0 + x + w / 2.0 - st.x0
        if not 0.8 * sp <= cx <= 2.6 * sp:
            continue
        if y + h >= m.shape[0] - 1:
            continue                              # runs on down: not a small digit
        blob = (lab[y:y + h, x:x + w] == j).astype(np.uint8)
        inv = 1 - blob
        k_, _, _, _ = cv2.connectedComponentsWithStats(np.pad(inv, 1, constant_values=1), connectivity=4)
        if k_ - 1 >= 2:                           # outside + at least one hole
            return True
    return False


def _clef_once(owner: np.ndarray, line_px: np.ndarray, st: Staff,
               idx: int, sp: float, thick: int = 3) -> tuple[str, float]:
    """_clef_once -> (clef, match score) at one staff start:
    'G2', 'G1', 'C1'..'C5', 'F3', 'F4', 'F5' or '?'.

    Family from robust shape facts: a G clef reaches far above and below
    the staff; an F clef has its two dots to the right of its body; else a
    C clef. The line: F from the dots (the F line runs between them), G
    and C by comparing the clef with the Bravura glyph at each line where
    that clef is used (normalised cross-correlation of blurred images,
    staff lines drawn into both). Maria (scan): mensuration signs, scan
    tails and taller old C clefs no longer mislead."""
    import cv2
    import numpy as np
    b = clef_blob(owner, line_px, st, idx, sp, thick)
    if b is None:
        return "?", -1.0
    cands = list(CLEF_CANDIDATES)
    if _clef_template("G", sp, 1.0) is None:
        lab = clef_signature_rules(owner, line_px, st, idx, sp, thick)
        return lab, (1.0 if lab != "?" else -1.0)
    A, ay0 = b["raw"], b["y0"]
    cols = np.flatnonzero(A.any(axis=0))
    m = int(round(0.6 * sp))                       # template slides +-0.6 sp
    A = np.pad(A[:, cols[0]:cols[-1] + 1], ((0, 0), (m, m)))
    h, w = A.shape
    sig = max(1.0, 0.25 * sp)
    bA = cv2.GaussianBlur(A.astype(np.float32), (0, 0), sig)[:, m:w - m]
    bA -= bA.mean()
    nA = float(np.sqrt((bA * bA).sum()))
    colmask = np.zeros_like(A)
    colmask[:, m:w - m] = True
    lines = np.zeros_like(A)
    for kk in range(5):
        y = int(round(st.top + kk * sp - ay0))
        lines[max(0, y - thick // 2):y + thick - thick // 2 + 1, :] = True
    lines &= colmask
    step = max(1, int(round(0.2 * sp)))
    best, label = -1.0, "?"
    per: dict[str, float] = {}
    for kind, line in cands:
        for scale in (0.85, 1.0, 1.15):
            tpl, base = _clef_template(kind, sp, scale)
            ty = int(round(st.top + (5 - line) * sp - ay0 - base))
            th, tw = tpl.shape
            ys0, ys1 = max(0, ty), min(h, ty + th)
            if ys1 <= ys0:
                continue
            for tx in range(0, 2 * m + 1, step):
                T = lines.copy()
                xs1 = min(w, tx + tw)
                T[ys0:ys1, tx:xs1] |= tpl[ys0 - ty:ys1 - ty, :xs1 - tx]
                T &= colmask
                bT = cv2.GaussianBlur(T.astype(np.float32), (0, 0), sig)[:, m:w - m]
                bT -= bT.mean()
                den = float(np.sqrt((bT * bT).sum()) * nA)
                sc = float((bA * bT).sum()) / den if den > 0 else 0.0
                lab_ = f"{kind}{line}"
                per[lab_] = max(per.get(lab_, -1.0), sc)
                if sc > best:
                    best, label = sc, lab_
    # F clef dots: two small pieces one above the other, 0.6-1.4 sp apart,
    # at the clef's right end (or both merged by line removal into one
    # piece 0.8-1.6 sp high); the F line runs between them
    bx, by, bw, bh = b["box"]
    dl = [d_ for d_ in b["dots"] if d_[0] + d_[2] / 2 >= bx + 0.6 * bw]
    fline = None
    if len(dl) == 2:
        (xa, ya, wa, ha, _), (xb, yb, wb, hb, _) = dl
        dy = abs((ya + ha / 2) - (yb + hb / 2)) / sp
        if 0.6 <= dy <= 1.4 and abs((xa + wa / 2) - (xb + wb / 2)) <= 0.5 * sp:
            fline = ((ya + ha / 2) + (yb + hb / 2)) / 2
    elif len(dl) == 1 and 0.8 <= dl[0][3] / sp <= 1.6 and dl[0][2] <= 0.7 * sp:
        fline = dl[0][1] + dl[0][3] / 2
    if fline is not None:
        ln = int(round(5 - (fline + b["y0"] - st.top) / sp))
        if ln in (3, 4, 5):
            label = f"F{ln}"
            best = max(best, per.get(label, best))
    # a G clef reaches more than 1 sp beyond both staff edges; C and F never
    top = (by + b["y0"] - st.top) / sp
    bot = (by + bh - 1 + b["y0"] - st.bottom) / sp
    if top <= -1.0 and bot >= 1.0 and not label.startswith("G"):
        label = max(("G2", "G1"), key=lambda k_: per.get(k_, -1.0))
        best = per.get(label, best)
    # rare clefs only with a clear lead (scattered misreads into rare clefs
    # break the part mapping, which compares clefs from system to system)
    if label not in CLEF_COMMON:
        common = max(CLEF_COMMON, key=lambda k_: per.get(k_, -1.0))
        if best - per.get(common, -1.0) < CLEF_RARE_LEAD:
            label, best = common, per.get(common, -1.0)
    return label, best


def clef_signature_rules(owner: np.ndarray, line_px: np.ndarray, st: Staff,
                         idx: int, sp: float, thick: int = 3) -> str:
    """Fallback without Bravura: shape rules (G2, F4, C1..C5 or '?')."""
    f = clef_features(owner, line_px, st, idx, sp, thick)
    if f is None:
        return "?"
    top, bot, has_bar = f
    height = 4.0 + bot - top                     # blob height in sp
    if top < -0.8 and bot > 0.5:
        return "G2"
    if has_bar and 3.3 <= height <= 5.0:
        centre = (top + 4.0 + bot) / 2           # sp below the top line
        line = int(round(5 - centre))
        if 1 <= line <= 5:
            return f"C{line}"
    if not has_bar and -0.6 <= top <= 0.8 and height <= 4.3:
        return "F4"
    return "?"


def part_clefs(data: dict) -> dict[str, str]:
    """Clef of each part, from the systems where it is mapped (most common
    clef read there; a part on two staves: 'G+F'); '?' when none was read."""
    seen: dict[str, dict[str, int]] = {}
    for e in data.get("systems") or []:
        per: dict[str, list[str]] = {}
        for name, clef in zip(e.get("map") or [], e.get("clefs") or []):
            if name not in ("?", "-"):
                per.setdefault(name, []).append(clef or "?")
        for name, cl in per.items():
            if all(c == "?" for c in cl):
                continue
            key = "+".join(cl)
            seen.setdefault(name, {}).setdefault(key, 0)
            seen[name][key] += 1
    return {p: (max(seen[p], key=seen[p].get) if p in seen else "?")
            for p in data.get("parts") or []}
