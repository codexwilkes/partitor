# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""Data classes: Staff, PageResult, Strip, RestRun."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class Staff:
    page: int
    idx: int              # index on page, top first
    lines: list[float]    # 5 line centre rows (px)
    x0: int
    x1: int
    system: int = -1      # global system index
    label: str = ""       # OCR / text-layer label
    clef: str = "?"       # clef signature: G, F, C3, C4, ... or ?
    brace: int = -1       # bracket group id on the page
    steps: tuple | None = None   # (lowest, highest, x low, x high, bar index low, bar index high)

    @property
    def top(self) -> float:
        return self.lines[0]

    @property
    def bottom(self) -> float:
        return self.lines[-1]


@dataclass
class PageResult:
    page: int
    shape: tuple[int, int]
    sp: float                 # staff space incl. line (px)
    thick: int                # staff line thickness (px)
    skew: float               # degrees applied
    dewarp: float             # max vertical correction (px)
    staves: list[Staff]
    systems: list[list[Staff]]
    owner: np.ndarray         # int32 per pixel owner, OWN_NONE where white
    review: list[tuple[int, int, int, int, str]] = field(default_factory=list)
    gate: list[str] = field(default_factory=list)       # safety failures
    gate_boxes: list[tuple[int, int, int, int]] = field(default_factory=list)
    discard: dict[int, int] = field(default_factory=dict)
    ink_px: int = 0
    title: str = ""
    composer: str = ""        # right-aligned text line under the title
    music: bool = True
    barlines: dict[int, list[int]] = field(default_factory=dict)   # system -> x
    anchors: dict[int, list[tuple[int, int]]] = field(default_factory=dict)
    num_boxes: dict[int, list[tuple[int, int, int, int]]] = field(default_factory=dict)
    # system -> boxes of printed mid-line bar numbers (kept as ink)
    restart: set[int] = field(default_factory=set)  # systems that start a movement
    mensur: dict[int, list[int]] = field(default_factory=dict)  # system -> dotted bar x
    repeats: dict[int, list[tuple[int, str]]] = field(default_factory=dict)


# =============================================================================
# Strips
# =============================================================================
@dataclass
class Strip:
    img: np.ndarray       # bool ink, cropped
    staff_x0: int         # x of staff start inside img
    staff_top: int        # row of first staff line inside img
    staff_bottom: int     # row of last staff line inside img
    sp: float
    hdr: np.ndarray       # bool, header part of img (same shape)
    bar_no: int | None = None   # number printed at the line start
    bar_raise: float = 1.0      # least baseline height above the staff, sp
    bar_size: float = 2.0       # number size, sp
    marks: list = field(default_factory=list)   # [(x in img, letter)] rehearsal marks
    movement: bool = False      # starts a movement (extra space above)
    bracket: bool = False       # group score: draw a bracket at the left
    bars_x: list = field(default_factory=list)   # barline x in img (re-flow)
    bar_nums: list = field(default_factory=list) # number of each bar
    ends_at_bar: bool = False   # the line ends at a barline (re-flow may cut it)
    bars_why: str = ""          # why a group line has no barline to cut at (report)
    end_gap_sp: float = -1.0    # staff end minus last barline, in sp (-1: no barline)
    num_mask: np.ndarray | None = None  # ink of printed mid-line bar numbers (same shape)
    rest_label: tuple | None = None     # (x centre in img, text): multi-bar rest count
    rest_src: tuple | None = None       # (src, cw, RestRun): to rebuild at another width
    indent: int = 0             # px left of the staff start kept free (first line, labels)
    name_label: str | None = None       # full part name in the indent (small caps)
    staff_labels: list = field(default_factory=list)  # [(name, top row, bottom row)] group staves
    ambitus_marks: list = field(default_factory=list)  # [(x left, bottom-line row, clef, lo, hi, lo alt, hi alt)]


@dataclass
class RestRun:
    """Bars of a part in systems where the source prints no staff for it
    (the part rests). Becomes a multi-bar rest line (make_rest_strip)."""
    bars: int
    first: int | None            # number of the first bar (None: unknown)
    movement: bool = False       # the run starts a movement
    header: tuple | None = None  # (bool img, dx from staff start, gap above staff), movement title
