# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""Page render, tracking, dewarp, staff and system detection, OCR."""
from __future__ import annotations

import re
import shutil
import subprocess

import cv2
import numpy as np
import pymupdf

from .config import DEWARP_MIN_PX, MAX_SKEW_DEG, PAPER_GUARD, TRACK_BANDS
from .mapping import _NUMERALS
from .model import Staff


# =============================================================================
# Page rendering and conditioning
# =============================================================================
def render_page(page: pymupdf.Page, dpi: int) -> np.ndarray:
    """render_page <page> <dpi> -> uint8 grey image (0 black, 255 white)."""
    pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY, alpha=False)
    return np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w).copy()


def flatten(grey: np.ndarray) -> np.ndarray:
    """flatten <grey> -> grey with an even background (shading, grey paper
    and spine shadow divided out). The background estimate is a grey
    closing at 1/8 scale, which removes all ink smaller than about 8 mm."""
    h, w = grey.shape
    small = cv2.resize(grey, (max(1, w // 8), max(1, h // 8)),
                       interpolation=cv2.INTER_AREA)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))
    bg = cv2.morphologyEx(small, cv2.MORPH_CLOSE, k)
    bg = cv2.GaussianBlur(bg, (0, 0), 3)
    bg = cv2.resize(bg, (w, h), interpolation=cv2.INTER_LINEAR).astype(np.float32)
    norm = grey.astype(np.float32) / np.maximum(bg, 1.0) * 255.0
    return np.clip(norm, 0, 255).astype(np.uint8)


def sauvola(img: np.ndarray, win: int = 41, k: float = 0.2,
            r: float = 128.0) -> np.ndarray:
    """sauvola <img> -> bool ink mask by local mean and deviation."""
    f = img.astype(np.float32)
    m = cv2.boxFilter(f, -1, (win, win))
    m2 = cv2.boxFilter(f * f, -1, (win, win))
    s = np.sqrt(np.maximum(m2 - m * m, 0))
    return f < m * (1 + k * (s / r - 1))


def binarize(norm: np.ndarray) -> np.ndarray:
    """binarize <flattened grey> -> bool ink mask.

    Otsu ink, united with local (Sauvola) ink that is at least 10% darker
    than the paper (paper is about 255 after flatten). The union never
    makes print lighter than plain Otsu, and it keeps light grey print
    that a global threshold drops (Otsu is low on a page with very dark
    ink, so the paper guard must not depend on it)."""
    otsu, _ = cv2.threshold(norm, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    glob = norm < otsu
    loc = sauvola(norm) & (norm < PAPER_GUARD)
    return glob | loc


def estimate_skew(ink: np.ndarray) -> float:
    """estimate_skew <ink> -> degrees. Maximises row-projection sharpness."""
    h, w = ink.shape
    f = 1000.0 / max(h, w)
    small = cv2.resize(ink.astype(np.uint8) * 255, (int(w * f), int(h * f)),
                       interpolation=cv2.INTER_AREA)
    best, best_a = -1.0, 0.0
    for a in np.arange(-MAX_SKEW_DEG, MAX_SKEW_DEG + 0.001, 0.1):
        m = cv2.getRotationMatrix2D((small.shape[1] / 2, small.shape[0] / 2), a, 1)
        r = cv2.warpAffine(small, m, (small.shape[1], small.shape[0]),
                           flags=cv2.INTER_NEAREST, borderValue=0)
        prof = r.sum(axis=1, dtype=np.float64)
        score = float(np.sum(np.diff(prof) ** 2))
        if score > best:
            best, best_a = score, a
    return float(best_a)


def rotate(grey: np.ndarray, deg: float) -> np.ndarray:
    if abs(deg) < 0.05:
        return grey
    h, w = grey.shape
    m = cv2.getRotationMatrix2D((w / 2, h / 2), deg, 1)
    return cv2.warpAffine(grey, m, (w, h), flags=cv2.INTER_LINEAR,
                          borderValue=255)


def run_lengths(ink: np.ndarray) -> tuple[int, int]:
    """run_lengths <ink> -> (line thickness, staff space gap) in px.

    Most common vertical black run = line thickness; most common white run
    = gap between lines. Classic OMR estimate."""
    h, w = ink.shape
    cols = ink[:, :: max(1, w // 300)].T
    black, white = np.zeros(h + 1, np.int64), np.zeros(h + 1, np.int64)
    for col in cols:
        d = np.diff(np.concatenate(([0], col.astype(np.int8), [0])))
        starts, ends = np.flatnonzero(d == 1), np.flatnonzero(d == -1)
        if len(starts) == 0:
            continue
        np.add.at(black, ends - starts, 1)
        if len(starts) > 1:
            np.add.at(white, starts[1:] - ends[:-1], 1)
    thick = int(np.argmax(black[1:]) + 1)
    gap = int(np.argmax(white[1:]) + 1)
    return thick, gap


def line_mask(ink: np.ndarray, sp: float, open_len: float) -> np.ndarray:
    """line_mask -> bool mask of horizontal line pixels. Small breaks
    (faint or dotted lines in scans) are bridged before the opening."""
    bridge = cv2.getStructuringElement(cv2.MORPH_RECT, (max(3, int(0.6 * sp)), 1))
    closed = cv2.morphologyEx(ink.astype(np.uint8), cv2.MORPH_CLOSE, bridge)
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (max(15, int(open_len)), 1))
    return cv2.morphologyEx(closed, cv2.MORPH_OPEN, k) > 0


# =============================================================================
# Staff tracking (bands) and dewarp
# =============================================================================
def staff_tracks(ink: np.ndarray, thick: int, sp: float,
                 nb: int = TRACK_BANDS) -> list[list[tuple[float, list[float]]]]:
    """staff_tracks -> staff tracks across the page.

    Each band (1/nb of the width) gives 5-line staff candidates from its
    own row projection, so a bent staff is still straight inside one band.
    Candidates are linked band to band (slope-predicted, within 0.8 sp).
    A track = [(band centre x, 5 line rows), ...]; kept with >= nb/4 bands."""
    h, w = ink.shape
    lm = line_mask(ink, sp, 2.5 * sp)
    bw = w / nb
    cands: list[list[tuple[float, list[float]]]] = []
    for b in range(nb):
        x0, x1 = int(b * bw), int((b + 1) * bw)
        prof = lm[:, x0:x1].sum(axis=1) / max(1, x1 - x0)
        rows = prof > 0.45
        d = np.diff(np.concatenate(([0], rows.astype(np.int8), [0])))
        st, en = np.flatnonzero(d == 1), np.flatnonzero(d == -1)
        ls = [(a + z - 1) / 2.0 for a, z in zip(st, en) if z - a <= 2.5 * thick + 3]
        found = []
        i = 0
        while i + 4 < len(ls):
            g = ls[i:i + 5]
            if np.all(np.abs(np.diff(g) - sp) < 0.25 * sp):
                found.append(((x0 + x1) / 2.0, g))
                i += 5
            else:
                i += 1
        cands.append(found)
    tracks: list[list[tuple[int, float, list[float]]]] = []
    for b in range(nb):
        for xc, g in cands[b]:
            best, bd = None, 1e9
            for t in tracks:
                lb, _, ll = t[-1]
                if lb == b or b - lb > 4:
                    continue
                pred = ll[2]
                if len(t) >= 2:
                    pb, _, pl = t[-2]
                    pred = ll[2] + (ll[2] - pl[2]) / (lb - pb) * (b - lb)
                dd = abs(g[2] - pred)
                if dd < 0.8 * sp and dd < bd:
                    best, bd = t, dd
            if best is not None:
                best.append((b, xc, g))
            else:
                tracks.append([(b, xc, g)])
    keep = [t for t in tracks if len(t) >= max(3, nb // 4)]
    return [[(xc, g) for _, xc, g in t] for t in keep]


def track_fit(track: list[tuple[float, list[float]]], w: int) -> np.ndarray:
    """track_fit -> middle-line row for every column.

    Piecewise linear between the band points (a page curl is not a clean
    parabola), lightly smoothed, constant beyond the first/last band."""
    bx = np.array([c[0] for c in track])
    by = np.array([c[1][2] for c in track], dtype=np.float64)
    if len(by) >= 5:
        by = np.convolve(np.pad(by, 1, mode="edge"), [0.25, 0.5, 0.25], mode="valid")
    return np.interp(np.arange(w, dtype=np.float64), bx, by)


def dewarp(grey: np.ndarray, tracks: list, w: int, h: int
           ) -> tuple[np.ndarray, float]:
    """dewarp -> (straightened grey, max correction px).

    Vertical displacement per column, from the fitted staff tracks,
    interpolated between staves (constant above the first and below the
    last). No change below DEWARP_MIN_PX."""
    if not tracks:
        return grey, 0.0
    Y, D = [], []
    for t in tracks:
        yfit = track_fit(t, w)
        mean = float(np.mean(yfit))
        Y.append(mean)
        D.append(yfit - mean)
    order = np.argsort(Y)
    Ya = np.array(Y)[order]
    Da = np.array(D)[order]
    dmax = float(np.abs(Da).max())
    if dmax < DEWARP_MIN_PX:
        return grey, 0.0
    rows = np.arange(h, dtype=np.float32)
    mapy = np.empty((h, w), np.float32)
    for x in range(w):
        mapy[:, x] = rows + np.interp(rows, Ya, Da[:, x])
    mapx = np.broadcast_to(np.arange(w, dtype=np.float32), (h, w)).copy()
    out = cv2.remap(grey, mapx, mapy, cv2.INTER_LINEAR, borderValue=255)
    return out, dmax


# =============================================================================
# Staff and system detection
# =============================================================================
def detect_staves(ink: np.ndarray, thick: int, gap: int, page: int
                  ) -> tuple[list[Staff], np.ndarray]:
    """detect_staves -> (staves, long-horizontal-line mask).

    Runs on a straightened page. Lines = row runs of the line mask longer
    than 25% of the longest; 5 lines at staff spacing = one staff. A staff
    must be at least 8 sp long."""
    sp = gap + thick
    hmask = line_mask(ink, sp, max(6 * sp, 15))
    # unbridged lines for the staff extent: bridging would join a bracket
    # or brace to the line ends and move the staff start left
    raw = cv2.morphologyEx(ink.astype(np.uint8), cv2.MORPH_OPEN,
                           cv2.getStructuringElement(cv2.MORPH_RECT, (max(9, int(2 * sp)), 1))) > 0
    prof = hmask.sum(axis=1)
    if prof.max() == 0:
        return [], hmask
    rows = prof > 0.25 * prof.max()
    d = np.diff(np.concatenate(([0], rows.astype(np.int8), [0])))
    starts, ends = np.flatnonzero(d == 1), np.flatnonzero(d == -1)
    runs: list[list[int]] = []
    for s0, e0 in zip(starts, ends):            # merge runs split by a
        if runs and s0 - runs[-1][1] <= thick:  # residual bend
            runs[-1][1] = int(e0)
        else:
            runs.append([int(s0), int(e0)])
    lines = [((s0 + e0 - 1) / 2.0, s0, e0) for s0, e0 in runs
             if e0 - s0 <= 3 * thick + 4]
    staves: list[Staff] = []
    i = 0
    tol = 0.3 * sp
    while i + 4 < len(lines):
        grp = lines[i:i + 5]
        ds = np.diff([g[0] for g in grp])
        if np.all(np.abs(ds - sp) < tol):
            ext = staff_extent(hmask, grp, thick, sp)
            if ext is not None:
                ext = (refine_start(raw, grp, thick, sp, ext[0]), ext[1])
            if ext is not None and ext[1] - ext[0] >= 8 * sp:
                staves.append(Staff(page, len(staves), [g[0] for g in grp],
                                    ext[0], ext[1]))
                i += 5
                continue
        i += 1
    return staves, hmask


def refine_start(raw: np.ndarray, grp: list, thick: int, sp: float, x0: int) -> int:
    """refine_start -> first column at or right of x0 (within 2.5 sp) where
    4 of 5 line rows hold unbridged line pixels. Bridging joins a bracket
    or barline to the line ends; this finds where the lines really start.
    Returns x0 when no such column is found (broken scan lines)."""
    x1 = min(raw.shape[1], int(x0 + 2.5 * sp))
    cnt = np.zeros(max(0, x1 - x0), np.int16)
    for g in grp:
        r0, r1 = max(0, int(g[0] - thick)), int(g[0] + thick) + 1
        cnt += raw[r0:r1, x0:x1].any(axis=0)
    hit = np.flatnonzero(cnt >= 4)
    return int(x0 + hit[0]) if hit.size else x0


def staff_extent(hmask: np.ndarray, grp: list, thick: int, sp: float
                 ) -> tuple[int, int] | None:
    """staff_extent -> (x0, x1) of a staff: the longest run of columns
    where at least 4 of the 5 line rows hold line pixels (gaps below 1 sp
    bridged: broken scan lines). Label text and incipit staves to the left
    drop out. The start is then refined with refine_start()."""
    cnt = np.zeros(hmask.shape[1], np.int16)
    for g in grp:
        r0, r1 = max(0, int(g[0] - thick)), int(g[0] + thick) + 1
        cnt += hmask[r0:r1].any(axis=0)
    cov = cnt >= 4
    d = np.diff(np.concatenate(([0], cov.astype(np.int8), [0])))
    st, en = np.flatnonzero(d == 1), np.flatnonzero(d == -1)
    if st.size == 0:
        return None
    runs = [[int(st[0]), int(en[0])]]
    for a, b in zip(st[1:], en[1:]):
        if a - runs[-1][1] < sp:
            runs[-1][1] = int(b)
        else:
            runs.append([int(a), int(b)])
    best = max(runs, key=lambda r: r[1] - r[0])
    return best[0], best[1] - 1


def gap_column_fraction(ink: np.ndarray, a: Staff, b: Staff, thick: int
                        ) -> np.ndarray:
    """Ink fraction per column over the gap between staff a and staff b."""
    g0, g1 = int(a.bottom + thick) + 1, int(b.top - thick) - 1
    if g1 <= g0:
        return np.zeros(ink.shape[1])
    return ink[g0:g1 + 1].mean(axis=0)


def group_systems(ink: np.ndarray, staves: list[Staff], sp: float, thick: int
                  ) -> list[list[Staff]]:
    """group_systems -> staves grouped into systems.

    A gap is joined when (a) the system-start zone has a column that is
    at least 50% ink across the gap (solid, dotted or broken barline,
    bracket), or (b) two or more columns across the staff are at least 60%
    ink (Mensurstriche), or (c) it has no evidence but is no wider than
    1.2 x the median joined gap on the page. A page with no joined gap
    falls back to gap-size clustering. Rule (c) needs some ink (0.15) in
    the system-start zone when two or more gaps on the page have a bracket
    or barline (0.3.0-dev.21)."""
    if not staves:
        return []
    joined: list[bool | None] = []
    zone_max: list[float] = []
    for a, b in zip(staves, staves[1:]):
        frac = gap_column_fraction(ink, a, b, thick)
        zx0 = max(0, min(a.x0, b.x0) - int(3 * sp))
        zx1 = min(ink.shape[1], max(a.x0, b.x0) + int(1 * sp))
        zm = float(frac[zx0:zx1].max()) if frac[zx0:zx1].size else 0.0
        zone_max.append(zm)
        if zm >= 0.5:
            joined.append(True)
            continue
        inner = frac[max(a.x0, b.x0) + int(1 * sp):min(a.x1, b.x1)] >= 0.6
        d = np.diff(np.concatenate(([0], inner.astype(np.int8), [0])))
        positions = int((d == 1).sum())
        joined.append(True if positions >= 2 else None)
    gaps_all = [b.top - a.bottom for a, b in zip(staves, staves[1:])]
    known = [g for g, j in zip(gaps_all, joined) if j]
    if known:
        # a gap without evidence joins when it is no wider than the joined
        # gaps on the same page (lyrics may widen a gap by about 20%)
        lim = 1.2 * float(np.median(known))
        # ... but not a gap with no connecting ink at all at the system
        # start when other gaps on the page have a bracket or barline: the
        # bracket shows where a system ends (operator request 2026-10-25; Biber p53:
        # four small systems joined into one of 18 staves). Broken scan
        # barlines leave some ink (0.15 or more).
        n_bar = sum(1 for zm in zone_max if zm >= 0.5)
        joined = [True if j else bool(g <= lim and (zm >= 0.15 or n_bar < 2))
                  for g, j, zm in zip(gaps_all, joined, zone_max)]
    if not any(j for j in joined) and len(staves) > 1:
        gaps = np.array([b.top - a.bottom for a, b in zip(staves, staves[1:])])
        if gaps.max() / max(gaps.min(), 1.0) >= 1.4:
            cut = float(np.sqrt(gaps.max() * gaps.min()))
            joined = [bool(g < cut) for g in gaps]
        else:
            joined = [True] * len(gaps)
    groups, cur = [], [staves[0]]
    for st, j in zip(staves[1:], joined):
        if j:
            cur.append(st)
        else:
            groups.append(cur)
            cur = [st]
    groups.append(cur)
    return groups


# =============================================================================
# OCR and text layer
# =============================================================================
_TESS = {"path": shutil.which("tesseract")}


def ocr_line(img: np.ndarray, digits: bool = False) -> str:
    """ocr_line <bool ink crop> -> text (one line), '' when tesseract is
    missing or reads nothing. digits: read 0-9 only (bar numbers)."""
    if _TESS["path"] is None or img.size == 0 or not img.any():
        return ""
    pad = np.pad(img, 20, constant_values=False)
    ok, png = cv2.imencode(".png", np.where(pad, 0, 255).astype(np.uint8))
    if not ok:
        return ""
    try:
        cmd = [_TESS["path"], "stdin", "stdout", "--psm", "7"]
        if digits:
            cmd += ["-c", "tessedit_char_whitelist=0123456789"]
        r = subprocess.run(cmd, input=png.tobytes(), capture_output=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return re.sub(r"\s+", " ", r.stdout.decode("utf-8", "replace")).strip()


FOOTER_RE = re.compile(r"©|@|\(c\)|copyright|verlag|edition|publish|"
                       r"\bby\b.*\b(1[89]|20)\d\d\b|\b(1[89]|20)\d\d\b.*\bby\b|^\*",
                       re.IGNORECASE)


def is_footer_text(txt: str) -> bool:
    """is_footer_text -> True for page-foot text: copyright, publisher, a
    page number (digits alone), a footnote ("*) ...")."""
    t = txt.strip()
    return bool(t) and (bool(FOOTER_RE.search(t)) or bool(re.fullmatch(r"\d{1,4}", t)))


def is_cue_text(txt: str) -> bool:
    """is_cue_text -> True for a header that is not a movement title: a
    voice cue in brackets, with or without a bar number before it
    ("35 (Alto I)", "(Canto I)"), or a bar number alone."""
    t = txt.strip()
    # any bracket: OCR reads "35(Alto I)" as "Farce I)"; movement titles
    # do not hold brackets
    return bool(t) and (bool(re.search(r"[()\[\]{}]", t))
                        or bool(re.fullmatch(r"\d{1,4}", t)))


def read_text(page: pymupdf.Page, rect_px: tuple[int, int, int, int], dpi: int,
              crop: np.ndarray, vector_text: bool, scale_up: bool = False) -> str:
    """read_text -> text of a region: the PDF text layer when the page has
    one and it holds words there, else OCR of the ink crop."""
    if vector_text:
        t = text_in_rect(page, rect_px, dpi)
        if t.strip():
            return t
    if scale_up:
        crop = cv2.resize(crop.astype(np.uint8), None, fx=2, fy=2,
                          interpolation=cv2.INTER_NEAREST) > 0
    return ocr_line(crop)


def text_in_rect(page: pymupdf.Page, rect_px: tuple[int, int, int, int],
                 dpi: int) -> str:
    """Text-layer words inside a pixel rectangle (vector pages)."""
    k = 72.0 / dpi
    x0, y0, x1, y1 = rect_px
    r = pymupdf.Rect(x0 * k, y0 * k, x1 * k, y1 * k)
    words = page.get_text("words", clip=r)
    return " ".join(w[4] for w in sorted(words, key=lambda w: (w[5], w[6], w[0])))


def looks_like_text(widths: list[int], height: float) -> bool:
    """A text line is several glyphs (3+ components), none much wider than
    the line is high (4x); a scan's page edge or a rule is one long
    stroke (Maria p2: one component 1465 x 21 px read as a title)."""
    return len(widths) >= 3 and max(widths) <= 4 * height


def clean_title(text: str) -> str:
    """clean_title -> title text without OCR debris at the ends."""
    t = re.sub(r"\s+", " ", text).strip(" .,;:-_|'\"")
    return t if re.search(r"[A-Za-zÀ-ÿ]{3}", t) else ""


def clean_label(text: str) -> str:
    """clean_label -> label text without OCR debris: keeps words of 2+
    letters and roman/arabic numbers; '' when no word of 3+ letters."""
    t = re.sub(r"\bII[\]\|l1!]", "III", text)        # OCR reads I as ] | l 1 !
    t = re.sub(r"\bI[\]\|l1!](?![a-z])", "II", t)
    toks = re.findall(r"[A-Za-zÀ-ÿ]+|\d+", t.replace("[", "").replace("]", ""))
    keep = [t for t in toks if len(t) >= 2 or t.lower() in _NUMERALS]
    if not any(len(t) >= 3 and t.isalpha() for t in keep):
        return ""
    return " ".join(keep)
