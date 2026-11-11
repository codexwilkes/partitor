# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""Page-turn planner for bound parts: spreads, fold-outs, turn classes.

Pure functions: no strips, no drawing. The caller says how tall a run of
lines is, which boundaries have a rest, a movement start or a bridgeable
staff, and gets the pages, the fold-outs and the class of every turn.
DESIGN.md §5.6.

A bound part is read as spreads: a verso and a recto (two content pages), a
turn after each recto. A fold-out group has three faces (verso, recto, flap
to the right of the recto; or flap, verso, recto) and one turn at its end.
The flap is unfolded at the start of the spread and folded in before the
turn, so both ends of a fold-out group must be rest turns.

Where the faces sit on paper decides which groups may follow each other. A
right fold-out is one leaf: its recto and flap on the front, the verso of the
next group on the back. A left fold-out is one leaf too: the verso and the
flap on one side, the last recto of the previous group on the other. So a
right fold-out cannot be followed by a left one (they would need the same
leaf with a flap on each edge), and a left fold-out cannot open the part
after a title page (the title page would be on its back)."""
from __future__ import annotations

import functools
from dataclasses import dataclass
from typing import Callable

from .typography import (MIN_LAST_LINES, PAGE_COST, PLAN_BAD, PLAN_BRIDGE, PLAN_FOLD,
                         PLAN_REST_ONE, REPAGE_FILL, REST_TURN_MIN, SHORT_LAST, TURN_MOVE)

INF = float("inf")


@dataclass(frozen=True)
class Boundary:
    """What stands at a page break before line j.
    rest_bars: bars of rest (all staves) next to the break; movement: a
    movement starts at line j; bridge_bars: bars one staff rests next to the
    break (the player can tape a few notes over the turn)."""
    rest_bars: int = 0
    movement: bool = False
    bridge_bars: int = 0
    section: bool = False   # a section starts at line j (a rehearsal letter): class "section" (0.8.40)
                            # when Costs.section is below Costs.bad


@dataclass(frozen=True)
class Costs:
    rest_one: float = PLAN_REST_ONE
    attacca: float = TURN_MOVE
    fold: float = PLAN_FOLD
    bridge: float = PLAN_BRIDGE
    bad: float = PLAN_BAD
    page: float = PAGE_COST
    fill: float = REPAGE_FILL
    short_last: float = SHORT_LAST
    section: float = PLAN_BAD      # a turn at a section start while playing (0.8.40; the caller sets it)


@dataclass(frozen=True)
class Turn:
    before: int             # the turn comes before this line
    cls: str                # rest | rest1 | attacca | section | bridge | bad | end (the part ends)
    cost: float
    bars: int               # rest bars next to the turn (0: none)


@dataclass(frozen=True)
class Group:
    """Pages read without a turn between them."""
    pages: tuple            # ((first line, end line), ...) per content page
    fold: bool              # three faces with a flap that folds out
    turn: Turn              # the turn after the group
    side: str = ""          # a fold-out: "right" (verso, recto, flap) or "left" (flap, verso, recto)

    @property
    def faces(self) -> int:
        return len(self.pages)


@dataclass(frozen=True)
class Plan:
    groups: tuple
    cost: float

    @property
    def pages(self) -> int:
        return sum(g.faces for g in self.groups)

    @property
    def folds(self) -> int:
        return sum(1 for g in self.groups if g.fold)

    def sides(self) -> dict:
        """Number of fold-outs per side."""
        out: dict = {}
        for g in self.groups:
            if g.fold:
                out[g.side] = out.get(g.side, 0) + 1
        return out

    def counts(self) -> dict:
        """Number of turns per class (the end of the part is not a turn)."""
        out: dict = {}
        for g in self.groups:
            if g.turn.cls != "end":
                out[g.turn.cls] = out.get(g.turn.cls, 0) + 1
        return out

    @property
    def playing(self) -> int:
        """Turns while playing: bridgeable and bad."""
        c = self.counts()
        return c.get("bridge", 0) + c.get("bad", 0)


def classify(b: Boundary, costs: Costs) -> tuple[str, float]:
    """classify -> (class, cost) of a turn at boundary b: the cheapest class
    that applies. A one-bar rest is a rest turn (the player can turn, with
    less time); two bars or more are free."""
    if b.rest_bars >= REST_TURN_MIN:
        return "rest", 0.0
    options = []
    if b.rest_bars >= 1:
        options.append(("rest1", costs.rest_one))
    if b.movement:
        options.append(("attacca", costs.attacca))
    if b.section and costs.section < costs.bad:      # else it is a bad turn, named so
        options.append(("section", costs.section))
    if b.bridge_bars >= 1:
        options.append(("bridge", costs.bridge))
    options.append(("bad", costs.bad))
    return min(options, key=lambda o: o[1])


def plan_turns(n: int, used: Callable[[int, int], float], avail: float,
               bounds: list, *, avail_first: float | None = None,
               title_page: bool = True, allow_fold: bool = True,
               forced: tuple = (), costs: Costs | None = None,
               fold_sides: tuple = ("right",), last_cost: Callable[[int], float] | None = None,
               single: bool = False, flat: bool = False) -> Plan:
    """plan_turns -> Plan for n lines.
    used(i, j): height of lines i..j-1 on one page; avail: height of a page
    (avail_first: of the first content page); bounds[j]: Boundary before line
    j (0 < j < n). title_page: page 1 is a title page, so the music starts on
    a verso; else the first content page is a recto, alone, with a turn after
    it. allow_fold: fold-out groups may be used, on the sides of fold_sides
    ("right", "left"; the cheapest wins, right on a tie). forced: line indices
    where a page must end (no page runs past one). Page breaks and fold-outs
    are chosen for the whole part at once (dynamic programming).
    last_cost(i): an extra cost of the last page when it holds lines i..n-1 (the
    caller's logo room, 0.8.40). single: printed on one side, so a turn follows
    every page and there are no spreads or fold-outs (0.8.40). flat: a part of 1 or 2 pages
    (no title page) lies side by side on the stand with no turn (0.8.42): the best such plan
    is one group without a turn, and it wins over the other plans at equal or lower cost."""
    costs = costs or Costs()
    avail_first = avail if avail_first is None else avail_first
    forced = tuple(sorted(f for f in set(forced) if 0 < f < n))
    turns: dict = {}

    def turn(j: int) -> Turn:
        if j >= n:
            return Turn(j, "end", 0.0, 0)
        if j not in turns:
            b = bounds[j]
            cls, cost = classify(b, costs)
            turns[j] = Turn(j, cls, cost, b.rest_bars)
        return turns[j]

    @functools.lru_cache(maxsize=None)
    def page_ends(i: int) -> tuple:
        """Possible ends j of a page that starts at line i (made once per i, 0.8.40)."""
        cap = avail_first if i == 0 else avail
        fj = next((f for f in forced if f > i), None)
        out = []
        for j in range(i + 1, n + 1):
            if used(i, j) > cap and j > i + 1:
                break
            out.append(j)
            if fj is not None and j >= fj:
                break
        return tuple(out)

    pcost: dict = {}

    def page_cost(i: int, j: int) -> float:
        got = pcost.get((i, j))
        if got is None:
            cap = avail_first if i == 0 else avail
            if j == n:
                got = costs.page + (costs.short_last if n - i < MIN_LAST_LINES and i > 0 else 0.0)
                if last_cost is not None:
                    got += last_cost(i)
            else:
                got = costs.page + costs.fill * max(0.0, 1.0 - used(i, j) / cap) ** 2
            pcost[(i, j)] = got
        return got

    def foldable(t: Turn) -> bool:
        return t.cls in ("rest", "rest1")

    sides = tuple(s for s in fold_sides if s in ("right", "left")) if allow_fold and not single else ()

    @functools.lru_cache(maxsize=None)
    def best(i: int, entry_ok: bool, prev_right: bool = False):
        """Lines i..n-1 as groups, the first group starting on a verso.
        entry_ok: the turn before i is a rest turn (a fold-out may start).
        prev_right: the group before i is a right fold-out. The cheapest candidate
        is kept as it is met (the first of equal costs, as min over the list in
        this order); its groups are made only for it (0.8.40)."""
        if i >= n:
            return 0.0, ()
        top, make = INF, None
        for a in page_ends(i):
            ca = page_cost(i, a)
            if a == n:
                if ca < top:
                    top, make = ca, (0, i, a)
                continue
            for b in page_ends(a):
                cb = ca + page_cost(a, b)
                if b == n:
                    if cb < top:
                        top, make = cb, (1, i, a, b)
                    continue
                t = turn(b)
                sub, _ = best(b, foldable(t), False)
                c = cb + t.cost + sub
                if c < top:
                    top, make = c, (2, i, a, b)
                if not (sides and entry_ok):
                    continue
                for c_ in page_ends(b):
                    cc = cb + page_cost(b, c_) + costs.fold
                    for side in sides:
                        if side == "left" and (prev_right or (i == 0 and title_page)):
                            continue
                        if c_ == n:
                            if cc < top:
                                top, make = cc, (3, i, a, b, c_, side)
                            continue
                        t3 = turn(c_)
                        if not foldable(t3):
                            continue
                        sub, _ = best(c_, True, side == "right")
                        c = cc + t3.cost + sub
                        if c < top:
                            top, make = c, (4, i, a, b, c_, side)
        if make is None:
            return INF, ()
        kind = make[0]
        if kind == 0:
            return top, (Group(((i, make[2]),), False, turn(n)),)
        if kind == 1:
            return top, (Group(((i, make[2]), (make[2], make[3])), False, turn(n)),)
        if kind == 2:
            _, _, a, b = make
            t = turn(b)
            return top, (Group(((i, a), (a, b)), False, t),) + best(b, foldable(t), False)[1]
        _, _, a, b, c_, side = make
        pages3 = ((i, a), (a, b), (b, c_))
        if kind == 3:
            return top, (Group(pages3, True, turn(n), side),)
        t3 = turn(c_)
        return top, (Group(pages3, True, t3, side),) + best(c_, True, side == "right")[1]

    @functools.lru_cache(maxsize=None)
    def best_single(i: int):
        """Lines i..n-1 printed on one side: one page per group, a turn after each page."""
        if i >= n:
            return 0.0, ()
        top, pick = INF, None
        for a in page_ends(i):
            c = page_cost(i, a)
            if a < n:
                c += turn(a).cost + best_single(a)[0]
            if c < top:
                top, pick = c, a
        if pick is None:
            return INF, ()
        return top, (Group(((i, pick),), False, turn(pick)),) + best_single(pick)[1]

    def best_flat():
        """The cheapest plan of 1 or 2 pages read without a turn (None if 2 pages do not hold it)."""
        top, pick = INF, None
        for a in page_ends(0):
            if a == n:
                c, pg = page_cost(0, n), ((0, n),)
            elif n in page_ends(a):
                c, pg = page_cost(0, a) + page_cost(a, n), ((0, a), (a, n))
            else:
                continue
            if c < top:
                top, pick = c, pg
        return None if pick is None else Plan((Group(pick, False, turn(n)),), top)

    if n <= 0:
        return Plan((), 0.0)
    two = best_flat() if flat and not title_page else None
    if single:
        cost, groups = best_single(0)
        return two if two is not None and two.cost <= cost else Plan(groups, cost)
    if title_page:
        cost, groups = best(0, True)
        return Plan(groups, cost)
    # no title page: content page 1 is a recto on its own, a turn after it
    top, pick = INF, None
    for a in page_ends(0):
        if a == n:
            c = page_cost(0, a)
        else:
            t = turn(a)
            c = page_cost(0, a) + t.cost + best(a, foldable(t), False)[0]
        if c < top:
            top, pick = c, a
    if two is not None and two.cost <= top:
        return two
    if pick == n:
        return Plan((Group(((0, n),), False, turn(n)),), top)
    t = turn(pick)
    return Plan((Group(((0, pick),), False, t),) + best(pick, foldable(t), False)[1], top)
