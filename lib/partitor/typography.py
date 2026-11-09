# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""Fonts and text measure; the cut and fold guides of printed sheets."""
from __future__ import annotations

import os
from pathlib import Path


# ── Typography (DESIGN.md §5.5): EB Garamond (OFL), embedded ──────────────
FONT_FILES = {"regular": ("EBGaramond-Regular.ttf", "tiro"),
              "italic": ("EBGaramond-Italic.ttf", "tiit"),
              "bold": ("EBGaramond-SemiBold.ttf", "tibo"),
              # Bravura (SMuFL, OFL): time-signature digits for multi-bar
              # rest counts, as engravers set them
              "music": ("Bravura.otf", "tibo")}
_FONTS: dict[str, tuple[str, str | None, object]] = {}


def font_dirs() -> list[Path]:
    """Where the fonts are: PARTITOR_FONTS, share/fonts of the repo this
    script belongs to (clone, tests), /opt/partitor/fonts, the fonts/ folder
    next to this script."""
    out = []
    if os.environ.get("PARTITOR_FONTS"):
        out.append(Path(os.environ["PARTITOR_FONTS"]))
    here = Path(__file__).resolve().parents[1]   # lib/ (this file is lib/partitor/typography.py)
    out += [here.parent / "share" / "fonts", Path("/opt/partitor/fonts"), here / "fonts"]
    return out


def _font(kind: str) -> tuple[str, str | None, object]:
    """_font -> (fontname for insert_text, fontfile or None, measurer).
    Falls back to the built-in Times when the TTF is not found."""
    import pymupdf
    if kind not in _FONTS:
        fname, base = FONT_FILES[kind]
        path = next((d / fname for d in font_dirs() if (d / fname).is_file()), None)
        if path is not None:
            _FONTS[kind] = (f"pt-{kind}", str(path), pymupdf.Font(fontfile=str(path)))
        else:
            _FONTS[kind] = (base, None, pymupdf.Font(base))
    return _FONTS[kind]


def missing_fonts() -> list[str]:
    """missing_fonts -> the font files that are not found (the text then uses the built-in
    Times, which has no music glyphs: no clef in an ambitus, no digits in a multi-bar rest)."""
    return [FONT_FILES[k][0] for k in FONT_FILES if _font(k)[1] is None]


def text_len(text: str, kind: str, size: float) -> float:
    return _font(kind)[2].text_length(text, fontsize=size)


def put_text(page: pymupdf.Page, xy: tuple[float, float], text: str, kind: str,
             size: float) -> None:
    name, file, _ = _font(kind)
    if file:
        page.insert_text(xy, text, fontsize=size, fontname=name, fontfile=file)
    else:
        page.insert_text(xy, text, fontsize=size, fontname=name)


TURN_BAD = 100.0        # a page turn that does not fall at a section boundary
PAGE_COST = 30.0        # each page of music
SHORT_LAST = 50.0       # last page with fewer than MIN_LAST_LINES lines
MIN_LAST_LINES = 3      # a part's last page holds at least this many lines
FILL_COST = 10.0        # unfilled share of a page (squared), pages before the last
# turns=rest (0.3.0-dev.37, `repage`): the player turns only while resting.
TURN_HARD = 1000.0      # a turn while playing (always worse than any other cost)
TURN_MOVE = 150.0       # turns=rest: a turn at a movement start, no rest (not always attacca)
REPAGE_FILL = 40.0      # unfilled share of a page (squared); medium weight
REST_TURN_MIN = 2       # a rest turn: a multi-bar rest of at least this many bars
# turnplan (0.8.3): turn classes of the spread / fold-out planner. A turn while
# playing is high but finite (a rehearsal part with a bad turn beats no part).
PLAN_REST_ONE = 100.0   # a turn at a one-bar rest (two bars or more: 0)
PLAN_FOLD = 300.0       # one fold-out (its two end turns are rest turns, counted apart)
PLAN_BRIDGE = 800.0     # a turn while playing, but one staff rests next to it (tape a few notes)
PLAN_BAD = 5000.0       # a turn while playing, no staff rests


CROP_MARK = (14.4, 50.4)   # pt from each side edge: the short cut marks (cutline marks)
CROP_LEN = 36.0            # pt: length of a crop mark at the top and foot of a fold-out sheet or flap
CUT_DASHES = "[4 3] 0"     # the dotted cut line


def cut_mark(page: pymupdf.Page, x: float, ph: float, cutline: str) -> bool:
    """cut_mark -> True when it drew a vertical cut line at x on a page of height ph, as the
    layout key cutline says: dotted = a dotted line over the full height; marks = a short
    mark at the top and one at the foot; off = nothing."""
    if cutline == "dotted":
        page.draw_line((x, 0), (x, ph), color=(0.5, 0.5, 0.5), width=0.6, dashes=CUT_DASHES)
    elif cutline == "marks":
        for a, b in ((0.0, CROP_LEN), (ph - CROP_LEN, ph)):
            page.draw_line((x, a), (x, b), color=(0, 0, 0), width=0.5)
    return cutline != "off"


def cut_words(cutline: str, where: str = "") -> str:
    """cut_words -> what the player does at the cut, as the printed notes say it
    ('Cut at the left dotted line', 'Cut at the crop marks', 'Trim 1/2 in off the edge').
    where: 'left', 'right' or '' (the free edge of a flap)."""
    side = f"{where} " if where else ""
    if cutline == "marks":
        return f"Cut at the {side}crop marks"
    if cutline == "off":
        return f"Trim 1/2 in off the {side}edge of the flap, no line is printed"
    return f"Cut at the {side}dotted line"


def sheet_guides(page: pymupdf.Page, fold_x: float, ph: float, cut_x: float, mt: float,
                  note: str, hint: str = "", lines: bool = True, cutline: str = "dotted") -> None:
    """Dotted fold line and the cut line (cutline, see cut_mark) on a fold-out sheet,
    with a note and a line for the printer at the foot (sheet number, flip edge, place)."""
    if lines:                # front only: a second set on the back would never meet the first
        page.draw_line((fold_x, 0), (fold_x, ph), color=(0.5, 0.5, 0.5), width=0.6, dashes=CUT_DASHES)
        put_text(page, (fold_x + 3, ph - 6), "fold", "regular", 6.5)
        if cut_mark(page, cut_x, ph, cutline):
            put_text(page, (cut_x + (3 if cut_x < fold_x else -34), 10), "cut 1/2 in", "regular", 6.5)
    put_text(page, (fold_x - text_len(note, "italic", 7) / 2, max(mt - 10, 10)), note, "italic", 7)
    if hint:
        put_text(page, (fold_x - text_len(hint, "italic", 7) / 2, ph - 16), hint, "italic", 7)


def flap_guides(page: pymupdf.Page, cut_x: float, tape_x: float, ph: float, mt: float,
                 note: str, hint: str, cutline: str = "dotted") -> None:
    """Cut line of a flap on a Letter page (cutline, see cut_mark; the 1/2 in beyond it is
    cut off), a mark at the tape edge, a note and a line for the printer at the foot."""
    if cut_mark(page, cut_x, ph, cutline):
        put_text(page, (cut_x + (3 if cut_x < tape_x else -34), 10), "cut 1/2 in", "regular", 6.5)
    on_left = tape_x < cut_x
    put_text(page, (tape_x + (3 if on_left else -34), ph - 6), "tape edge", "regular", 6.5)
    mid = (cut_x + tape_x) / 2
    put_text(page, (mid - text_len(note, "italic", 7) / 2, max(mt - 10, 10)), note, "italic", 7)
    put_text(page, (mid - text_len(hint, "italic", 7) / 2, ph - 16), hint, "italic", 7)
