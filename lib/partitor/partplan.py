# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""Part planning: the options of a part (paper, staff size) with their page turns.

For `partitor plan` (DESIGN.md §5.8). The saved lines of a part are cut at their
barlines as re-flow would cut them (an estimate: the saved lines are justified,
so JUSTIFY_SHARE of a bar is taken as music), set at each staff size on each
paper, and handed to turnplan. Nothing is analysed or drawn: a table of options
in a fraction of a second. A build confirms the numbers."""
from __future__ import annotations

import dataclasses
import math
from dataclasses import dataclass, field

from .config import PAPER
from .reflow import _break_lines, find_prefixes
from .render import LARGE, RUN_HEAD, TITLE_BAND, fold_sides, page_box, usable_width
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
    cap_mm: float = 0.0     # `max_staff_mm` that gives this row (the staff shrinks to fit the label column)
    budget: int = 0         # pages at that size, before the shrink: the page budget the build needs

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
    label_px: float = 0.0   # the label column a group's lines get after the cut (px)

    def to_dict(self) -> dict:
        return {"format": SOURCE_FORMAT, "dpi": self.dpi, "sp": self.sp, "lines": self.lines,
                "label_px": self.label_px}

    @classmethod
    def from_dict(cls, d: dict) -> "Source":
        if not isinstance(d, dict) or d.get("format") != SOURCE_FORMAT:
            raise ValueError("plan data from another partitor: rebuild the part")
        return cls(int(d["dpi"]), float(d["sp"]), list(d["lines"]), label_px=float(d.get("label_px", 0.0)))


def read_source(strips: list, opts: dict, dpi: int, share: float = 1.0, label_px: float = 0.0) -> Source:
    """read_source -> Source: per line its pitch, height, rest bars, movement
    start and, if it can be cut, the width of each bar and of the clef + key
    copy a continuation line carries (px). share: the part of a bar's width
    that is music: 1.0 for the lines of a build (before they are justified),
    JUSTIFY_SHARE for saved lines. label_px: the label column of a group."""
    pre = find_prefixes(strips)
    pit = pitches(strips, opts) + [0.0]
    src = Source(dpi, float(strips[0].sp), exact=share >= 1.0, label_px=float(label_px))
    for i, s in enumerate(strips):
        rest = s.rest_src[2].bars if s.rest_src is not None else 0
        ends = s.ends_at_bar or 0.0 <= s.end_gap_sp <= BAR_END_SP
        ln = {"rest": rest, "rin": int(s.rest_in), "rout": int(s.rest_out),
              "movement": bool(s.movement), "pit": float(pit[i]),
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
            # the merged rests among the bars: where a cut leaves a rest at a line edge
            if any(s.rest_counts) and len(s.rest_counts) == len(s.bars_x):
                ln["rcount"] = [int(v) for v in s.rest_counts]
        src.lines.append(ln)
    return src


def _pieces(src: Source, width_px: float):
    """_pieces -> (pieces, too wide): the lines cut for a text width. A piece:
    (source line, first piece of its line, bars of a merged rest at its start, at its end)."""
    out, wide = [], None
    for i, ln in enumerate(src.lines):
        if ln["bars"] is None:
            if not ln["rest"] and ln["whole"] > width_px:
                wide = wide or (i, ln["whole"])
            out.append((i, True, ln.get("rin", 0), ln.get("rout", 0)))
            continue
        starts = _break_lines(ln["bars"], ln["copy"], width_px)
        for k, a in enumerate(starts):
            z = starts[k + 1] if k + 1 < len(starts) else len(ln["bars"])
            piece = (ln["copy"] if k else 0.0) + sum(ln["bars"][a:z])
            if z - a == 1 and piece > width_px:          # one bar wider than a line
                wide = wide or (i, piece)
            rc = ln.get("rcount")
            out.append((i, k == 0, rc[a] if rc else 0, rc[z - 1] if rc else 0))
    return out, wide


def estimate(src: Source, opts: dict, paper: str, staff_mm: float) -> Option:
    """estimate -> Option for one paper and the staff height (mm) the part ends
    with. Re-flow cuts the lines for the text width at a first staff size; a
    group then gets its label column, which widens every line, and the staff
    shrinks to fit: the lines are cut for a staff a little larger than the one
    that is printed (cap_mm), and the pages are laid out at the printed size."""
    sp, dpi = src.sp, src.dpi
    s1 = staff_mm * dpi / (4.0 * sp * 25.4)             # scale of the printed staff
    ov = {**opts, "paper": paper, "scale": s1}
    pw, ph = PAPER[paper]
    usable = usable_width(ov, pw)
    c = src.label_px * 72.0 / dpi                        # label column, pt at scale 1
    if c > 0.0:
        room = usable - c * s1
        if room <= 0.0:
            return Option(paper, staff_mm, False, "the label column is wider than the text")
        s0 = LINE_FIT * usable * s1 / room               # the scale the lines are cut for
    else:
        s0 = s1
    k0, k1 = 72.0 / dpi * s0, 72.0 / dpi * s1
    pieces, wide = _pieces(src, LINE_FIT * usable / k0)
    if wide is not None:
        i, w = wide
        return Option(paper, staff_mm, False,
                      f"line {i + 1} cannot be cut: {w * k0 / 72.0 * 25.4:.0f} mm of music")
    n = len(pieces)
    L = [src.lines[p[0]] for p in pieces]
    cum = [0.0]
    for ln in L:
        cum.append(cum[-1] + ln["pit"])
    _, _, mt, mb = page_box(ov, 0, False)

    def height(k: float):
        def h(i: int, j: int) -> float:
            last = L[j - 1]
            return (L[i]["top"] + (cum[j - 1] - cum[i]) - last["top"] + last["h"]) * k
        return h

    bounds = [Boundary()] + [
        Boundary(rest_bars=max(L[j - 1]["rest"], L[j]["rest"], pieces[j - 1][3], pieces[j][2]),
                 movement=bool(pieces[j][1] and L[j]["movement"])) for j in range(1, n)]
    forced = tuple(opts.get("_breaks") or [])
    fold = paper in LARGE and opts.get("duplex", "auto") != "off"

    def plan(title: bool, k: float) -> Plan:
        band = RUN_HEAD if title else TITLE_BAND
        return plan_turns(n, height(k), ph - mt - mb - RUN_HEAD, bounds,
                          avail_first=ph - mt - mb - band, title_page=title,
                          allow_fold=fold, forced=forced, fold_sides=fold_sides(opts))
    best, title = plan(False, k1), False
    if opts.get("title_page", "auto") == "auto" and best.pages >= 3:
        tp = plan(True, k1)
        if tp.pages >= 3 and tp.cost <= best.cost:
            best, title = tp, True
    budget = plan(title, k0).pages                       # the build lays the cut lines out at k0 first
    cut = any(ln["bars"] is not None for ln in src.lines) and n > len(src.lines)
    return Option(paper, staff_mm, True, "", best.pages, title, best, reflow=cut,
                  cap_mm=s0 * 4.0 * sp * 25.4 / dpi, budget=budget)


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
            out.append(dataclasses.replace(o, n=n))
    return out


def best_rows(rows: list[Option]) -> set[int]:
    """best_rows -> the numbers of the best row of each paper: the fewest turns while playing,
    then the largest staff, then the fewest fold-outs, then the fewest pages."""
    out = set()
    for paper in dict.fromkeys(o.paper for o in rows):
        ok = [o for o in rows if o.paper == paper and o.ok]
        if ok:
            out.add(min(ok, key=lambda o: (o.counts.get("bad", 0) + o.counts.get("bridge", 0),
                                           -o.staff_mm, o.folds, o.pages)).n)
    return out


def set_pairs(name: str, o: Option) -> list[str]:
    """set_pairs -> the `set` pairs that make a build follow option o: the
    paper, the largest staff, re-flow, the planner (fold-outs) and a page
    budget with some room."""
    cap = math.ceil((o.cap_mm or o.staff_mm) * 100.0 - 1e-6) / 100.0     # the cap of the cut size
    pairs = [f"{name}:paper={o.paper}", f"{name}:max_staff_mm={cap:g}",
             f"{name}:reflow={'on' if o.reflow else 'off'}", f"{name}:foldouts=on",
             f"{name}:pages={min(99, max(1, (o.budget or o.pages) + SLACK_PAGES))}"]
    return pairs
