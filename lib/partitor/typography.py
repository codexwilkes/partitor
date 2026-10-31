# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""Fonts and text measure."""
from __future__ import annotations

import os
from pathlib import Path

import pymupdf


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
    if kind not in _FONTS:
        fname, base = FONT_FILES[kind]
        path = next((d / fname for d in font_dirs() if (d / fname).is_file()), None)
        if path is not None:
            _FONTS[kind] = (f"pt-{kind}", str(path), pymupdf.Font(fontfile=str(path)))
        else:
            _FONTS[kind] = (base, None, pymupdf.Font(base))
    return _FONTS[kind]


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
FILL_COST = 10.0        # unfilled share of a page (squared), pages before the last
# turns=rest (0.3.0-dev.37, `repage`): the player turns only while resting.
TURN_HARD = 1000.0      # a turn while playing (always worse than any other cost)
TURN_MOVE = 150.0       # turns=rest: a turn at a movement start, no rest (not always attacca)
REPAGE_FILL = 40.0      # unfilled share of a page (squared); medium weight
REST_TURN_MIN = 2       # a rest turn: a multi-bar rest of at least this many bars
