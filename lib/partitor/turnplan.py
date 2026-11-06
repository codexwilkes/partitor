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


@dataclass(frozen=True)
class Turn:
    before: int             # the turn comes before this line
    cls: str                # rest | rest1 | attacca | bridge | bad | end (the part ends)
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
    if b.bridge_bars >= 1:
        options.append(("bridge", costs.bridge))
    options.append(("bad", costs.bad))
    return min(options, key=lambda o: o[1])


def plan_turns(n: int, used: Callable[[int, int], float], avail: float,
               bounds: list, *, avail_first: float | None = None,
               title_page: bool = True, allow_fold: bool = True,
               forced: tuple = (), costs: Costs | None = None,
               fold_sides: tuple = ("right",)) -> Plan:
    """plan_turns -> Plan for n lines.
    used(i, j): height of lines i..j-1 on one page; avail: height of a page
    (avail_first: of the first content page); bounds[j]: Boundary before line
    j (0 < j < n). title_page: page 1 is a title page, so the music starts on
    a verso; else the first content page is a recto, alone, with a turn after
    it. allow_fold: fold-out groups may be used, on the sides of fold_sides
    ("right", "left"; the cheapest wins, right on a tie). forced: line indices
    where a page must end (no page runs past one). Page breaks and fold-outs
    are chosen for the whole part at once (dynamic programming)."""
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

    def page_ends(i: int):
        """Possible ends j of a page that starts at line i."""
        cap = avail_first if i == 0 else avail
        fj = next((f for f in forced if f > i), None)
        for j in range(i + 1, n + 1):
            if used(i, j) > cap and j > i + 1:
                return
            yield j
            if fj is not None and j >= fj:
                return

    def page_cost(i: int, j: int) -> float:
        cap = avail_first if i == 0 else avail
        if j == n:
            return costs.page + (costs.short_last if n - i < MIN_LAST_LINES and i > 0 else 0.0)
        return costs.page + costs.fill * max(0.0, 1.0 - used(i, j) / cap) ** 2

    def foldable(t: Turn) -> bool:
        return t.cls in ("rest", "rest1")

    sides = tuple(s for s in fold_sides if s in ("right", "left")) if allow_fold else ()

    @functools.lru_cache(maxsize=None)
    def best(i: int, entry_ok: bool, prev_right: bool = False):
        """Lines i..n-1 as groups, the first group starting on a verso.
        entry_ok: the turn before i is a rest turn (a fold-out may start).
        prev_right: the group before i is a right fold-out."""
        if i >= n:
            return 0.0, ()
        found = []
        for a in page_ends(i):
            ca = page_cost(i, a)
            if a == n:
                found.append((ca, (Group(((i, a),), False, turn(n)),)))
                continue
            for b in page_ends(a):
                cb = ca + page_cost(a, b)
                if b == n:
                    found.append((cb, (Group(((i, a), (a, b)), False, turn(n)),)))
                    continue
                t = turn(b)
                sub, rest = best(b, foldable(t), False)
                found.append((cb + t.cost + sub, (Group(((i, a), (a, b)), False, t),) + rest))
                if not (sides and entry_ok):
                    continue
                for c in page_ends(b):
                    cc = cb + page_cost(b, c) + costs.fold
                    for side in sides:
                        if side == "left" and (prev_right or (i == 0 and title_page)):
                            continue
                        pages3 = ((i, a), (a, b), (b, c))
                        if c == n:
                            found.append((cc, (Group(pages3, True, turn(n), side),)))
                            continue
                        t = turn(c)
                        if not foldable(t):
                            continue
                        sub, rest = best(c, True, side == "right")
                        found.append((cc + t.cost + sub, (Group(pages3, True, t, side),) + rest))
        if not found:
            return INF, ()
        return min(found, key=lambda f: f[0])

    if n <= 0:
        return Plan((), 0.0)
    if title_page:
        cost, groups = best(0, True)
        return Plan(groups, cost)
    # no title page: content page 1 is a recto on its own, a turn after it
    found = []
    for a in page_ends(0):
        if a == n:
            found.append((page_cost(0, a), (Group(((0, a),), False, turn(n)),)))
            continue
        t = turn(a)
        sub, rest = best(a, foldable(t), False)
        found.append((page_cost(0, a) + t.cost + sub, (Group(((0, a),), False, t),) + rest))
    cost, groups = min(found, key=lambda f: f[0])
    return Plan(groups, cost)
