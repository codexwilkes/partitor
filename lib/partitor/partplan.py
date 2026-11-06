# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""Part planning: the options of a part (paper, staff size) with their page turns.

For `partitor plan` (DESIGN.md §5.8). The saved lines of a part are cut at their
barlines as re-flow would cut them (an estimate: the saved lines are justified,
so JUSTIFY_SHARE of a bar is taken as music), set at each staff size on each
paper, and handed to turnplan. Nothing is analysed or drawn: a table of options
in a fraction of a second. A build confirms the numbers."""
from __future__ import annotations

from dataclasses import dataclass, field

from .config import PAPER
from .reflow import _break_lines, find_prefixes
from .render import LARGE, RUN_HEAD, TITLE_BAND, page_box, usable_width
from .strips import BAR_END_SP, pitches
from .turnplan import Boundary, Plan, plan_turns

SIZES = (8.0, 7.5, 7.0, 6.5, 6.0, 5.5, 5.0)     # staff heights tried (mm)
JUSTIFY_SHARE = 0.93        # share of a saved (justified) bar that is music: an estimate (old saved lines)
LINE_FIT = 0.98             # re-flow fills a line up to this share of the text width
SOURCE_FORMAT = 1
SLACK_PAGES = 2             # `plan N` sets the page budget this much above the plan


@dataclass(frozen=True)
class Option:
    """One row of the table: a paper and a staff size, and what the planner makes of it."""
    paper: str
    staff_mm: float
    ok: bool                # False: a line cannot be cut narrow enough
    note: str = ""
    pages: int = 0          # content pages (faces; a flap counts)
    title_page: bool = False
    plan: Plan | None = None
    reflow: bool = False    # the lines are cut: re-flow is needed
    n: int = 0              # row number, from 1

    @property
    def folds(self) -> int:
        return self.plan.folds if self.plan else 0

    @property
    def counts(self) -> dict:
        return self.plan.counts() if self.plan else {}

    @property
    def playing(self) -> int:
        return self.plan.playing if self.plan else 0


@dataclass
class Source:
    """The lines of a part as the planner sees them."""
    dpi: int
    sp: float
    lines: list = field(default_factory=list)       # one dict per line
    exact: bool = True      # False: read from saved (justified) lines: an estimate

    def to_dict(self) -> dict:
        return {"format": SOURCE_FORMAT, "dpi": self.dpi, "sp": self.sp, "lines": self.lines}

    @classmethod
    def from_dict(cls, d: dict) -> "Source":
        if not isinstance(d, dict) or d.get("format") != SOURCE_FORMAT:
            raise ValueError("plan data from another partitor: rebuild the part")
        return cls(int(d["dpi"]), float(d["sp"]), list(d["lines"]))


def read_source(strips: list, opts: dict, dpi: int, share: float = 1.0) -> Source:
    """read_source -> Source: per line its pitch, height, rest bars, movement
    start and, if it can be cut, the width of each bar and of the clef + key
    copy a continuation line carries (px). share: the part of a bar's width
    that is music: 1.0 for the lines of a build (before they are justified),
    JUSTIFY_SHARE for saved lines."""
    pre = find_prefixes(strips)
    pit = pitches(strips, opts) + [0.0]
    src = Source(dpi, float(strips[0].sp), exact=share >= 1.0)
    for i, s in enumerate(strips):
        rest = s.rest_src[2].bars if s.rest_src is not None else 0
        ends = s.ends_at_bar or 0.0 <= s.end_gap_sp <= BAR_END_SP
        ln = {"rest": rest, "movement": bool(s.movement), "pit": float(pit[i]),
              "top": float(s.staff_top), "h": float(s.img.shape[0]),
              "whole": s.img.shape[1] * share, "bars": None, "copy": 0.0}
        p_ = pre[i]
        if p_ is None and s.ambitus_marks and not s.staff_labels:
            # the first line shows the ambitus in place of the staff names, so a saved
            # line has no labels to compare; the build saw them: take the nearest prefix
            near = [j for j in range(len(strips)) if pre[j] is not None]
            if near:
                j = min(near, key=lambda j: abs(j - i))
                p_ = (pre[j][0], j) if pre[j][1] == j else pre[j]
        if not rest and p_ is not None and ends and len(s.bars_x) >= 2:
            edges = [p_[0]] + list(s.bars_x)
            ln["bars"] = [(edges[b + 1] - edges[b]) * share for b in range(len(s.bars_x))]
            ln["copy"] = float(pre[p_[1]][0])
        src.lines.append(ln)
    return src


def _pieces(src: Source, width_px: float):
    """_pieces -> (pieces, too wide): the lines cut for a text width. A piece:
    (source line, first piece of its line, movement start)."""
    out, wide = [], None
    for i, ln in enumerate(src.lines):
        if ln["bars"] is None:
            if not ln["rest"] and ln["whole"] > width_px:
                wide = wide or (i, ln["whole"])
            out.append((i, True))
            continue
        starts = _break_lines(ln["bars"], ln["copy"], width_px)
        for k, a in enumerate(starts):
            z = starts[k + 1] if k + 1 < len(starts) else len(ln["bars"])
            piece = (ln["copy"] if k else 0.0) + sum(ln["bars"][a:z])
            if z - a == 1 and piece > width_px:          # one bar wider than a line
                wide = wide or (i, piece)
            out.append((i, k == 0))
    return out, wide


def estimate(src: Source, opts: dict, paper: str, staff_mm: float) -> Option:
    """estimate -> Option for one paper and staff height (mm)."""
    scale = staff_mm * src.dpi / (4.0 * src.sp * 25.4)
    ov = {**opts, "paper": paper, "scale": scale}
    pw, ph = PAPER[paper]
    k = 72.0 / src.dpi * scale
    width_px = LINE_FIT * usable_width(ov, pw) / k
    pieces, wide = _pieces(src, width_px)
    if wide is not None:
        i, w = wide
        return Option(paper, staff_mm, False,
                      f"line {i + 1} cannot be cut: {w * k / 72.0 * 25.4:.0f} mm of music")
    n = len(pieces)
    L = [src.lines[i] for i, _ in pieces]
    cum = [0.0]
    for ln in L:
        cum.append(cum[-1] + ln["pit"])
    _, _, mt, mb = page_box(ov, 0, False)

    def height(i: int, j: int) -> float:
        last = L[j - 1]
        return (L[i]["top"] + (cum[j - 1] - cum[i]) - last["top"] + last["h"]) * k

    bounds = [Boundary()] + [
        Boundary(rest_bars=max(L[j - 1]["rest"], L[j]["rest"]),
                 movement=bool(pieces[j][1] and L[j]["movement"])) for j in range(1, n)]
    forced = tuple(opts.get("_breaks") or [])

    def plan(title: bool) -> Plan:
        band = RUN_HEAD if title else TITLE_BAND
        return plan_turns(n, height, ph - mt - mb - RUN_HEAD, bounds,
                          avail_first=ph - mt - mb - band, title_page=title,
                          allow_fold=paper in LARGE and opts.get("duplex", "auto") != "off", forced=forced)
    best, title = plan(False), False
    if opts.get("title_page", "auto") == "auto" and best.pages >= 3:
        tp = plan(True)
        if tp.pages >= 3 and tp.cost <= best.cost:
            best, title = tp, True
    cut = any(ln["bars"] is not None for ln in src.lines) and n > len(src.lines)
    return Option(paper, staff_mm, True, "", best.pages, title, best, reflow=cut)


def options(src: Source, opts: dict, papers: tuple, sizes: tuple = SIZES,
            floor_mm: float = 5.0) -> list[Option]:
    """options -> numbered Options, one per paper and staff size (largest staff
    first, then paper), sizes below `floor_mm` left out."""
    out, n = [], 0
    for s in sizes:
        if s < floor_mm - 1e-9:
            continue
        for p in papers:
            n += 1
            o = estimate(src, opts, p, s)
            out.append(Option(o.paper, o.staff_mm, o.ok, o.note, o.pages, o.title_page, o.plan,
                              o.reflow, n))
    return out


def set_pairs(name: str, o: Option) -> list[str]:
    """set_pairs -> the `set` pairs that make a build follow option o: the
    paper, the largest staff, re-flow, the planner (fold-outs) and a page
    budget with some room."""
    pairs = [f"{name}:paper={o.paper}", f"{name}:max_staff_mm={o.staff_mm:g}",
             f"{name}:reflow={'on' if o.reflow else 'off'}", f"{name}:foldouts=on",
             f"{name}:pages={min(99, max(1, o.pages + SLACK_PAGES))}"]
    return pairs
