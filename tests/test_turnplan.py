# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""Tests for turnplan: spreads, fold-outs and turn classes (DESIGN.md §5.6).

The module is pure (no numpy, no pymupdf), so these tests need no venv packages.

    python3 -m unittest -v tests/test_turnplan.py
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "lib"))

from partitor import turnplan as tp  # noqa: E402

B = tp.Boundary


def run(n, bounds=None, avail=4.0, **kw):
    """n lines of height 1, a page holds `avail` lines; bounds: {j: Boundary}."""
    bounds = bounds or {}
    full = [B()] + [bounds.get(j, B()) for j in range(1, n)]
    return tp.plan_turns(n, lambda i, j: float(j - i), avail, full, **kw)


class TestClasses(unittest.TestCase):
    def test_classes_and_costs(self):
        c = tp.Costs()
        for b, want in ((B(rest_bars=2), ("rest", 0.0)), (B(rest_bars=9), ("rest", 0.0)),
                        (B(rest_bars=1), ("rest1", c.rest_one)),
                        (B(movement=True), ("attacca", c.attacca)),
                        (B(bridge_bars=1), ("bridge", c.bridge)),
                        (B(), ("bad", c.bad))):
            with self.subTest(b=b):
                self.assertEqual(tp.classify(b, c), want)

    def test_the_cheapest_class_that_applies_wins(self):
        c = tp.Costs()
        self.assertEqual(tp.classify(B(rest_bars=1, movement=True, bridge_bars=3), c)[0], "rest1")
        self.assertEqual(tp.classify(B(movement=True, bridge_bars=3), c)[0], "attacca")
        self.assertEqual(tp.classify(B(rest_bars=2, movement=True), c)[0], "rest")

    def test_costs_are_in_order(self):
        c = tp.Costs()
        self.assertLess(0.0, c.rest_one)
        self.assertLess(c.rest_one, c.attacca)
        self.assertLess(c.attacca, c.fold)
        self.assertLess(c.fold, c.bridge)
        self.assertLess(c.bridge, c.bad)


class TestSpreads(unittest.TestCase):
    def test_a_turn_falls_at_the_rest(self):
        p = run(16, {8: B(rest_bars=3)})
        self.assertEqual([g.pages for g in p.groups], [((0, 4), (4, 8)), ((8, 12), (12, 16))])
        self.assertEqual(p.counts(), {"rest": 1})
        self.assertEqual(p.cost, 4 * tp.Costs().page)

    def test_a_turn_while_playing_is_classed(self):
        for bounds, cls in (({}, "bad"), ({8: B(bridge_bars=1)}, "bridge"),
                            ({8: B(movement=True)}, "attacca"), ({8: B(rest_bars=1)}, "rest1")):
            with self.subTest(cls=cls):
                p = run(12, bounds, allow_fold=False)
                self.assertEqual(p.counts(), {cls: 1})

    def test_bridgeable_costs_less_than_bad(self):
        a, b = run(12, {8: B(bridge_bars=2)}, allow_fold=False), run(12, allow_fold=False)
        self.assertLess(a.cost, b.cost)
        self.assertEqual(a.playing, 1)
        self.assertEqual(b.playing, 1)

    def test_pages_tile_the_lines_and_groups_have_two_or_three_faces(self):
        p = run(37, {8: B(rest_bars=2), 20: B(rest_bars=4), 28: B(rest_bars=2)})
        spans = [pg for g in p.groups for pg in g.pages]
        self.assertEqual(spans[0][0], 0)
        self.assertEqual(spans[-1][1], 37)
        for a, b in zip(spans, spans[1:]):
            self.assertEqual(a[1], b[0])
        self.assertEqual(p.pages, len(spans))
        for g in p.groups[:-1]:
            self.assertIn(g.faces, (2, 3))

    def test_the_last_page_is_not_a_stub(self):
        c = tp.Costs(fill=0.0)                       # only the stub cost decides
        p = run(9, {}, avail=4.0, costs=c, allow_fold=False)
        last = p.groups[-1].pages[-1]
        self.assertGreaterEqual(last[1] - last[0], tp.MIN_LAST_LINES)

    def test_forced_break_ends_a_page(self):
        p = run(8, avail=4.0, forced=(3,))
        self.assertEqual(p.groups[0].pages[0], (0, 3))

    def test_first_page_may_be_shorter(self):
        full = [B()] * 8
        p = tp.plan_turns(8, lambda i, j: float(j - i), 4.0, full, avail_first=2.0)
        self.assertEqual(p.groups[0].pages[0][1], 2)

    def test_a_line_taller_than_the_page_stands_alone(self):
        p = tp.plan_turns(3, lambda i, j: 10.0 * (j - i), 4.0, [B()] * 3)
        self.assertEqual(p.pages, 3)

    def test_without_a_title_page_the_first_recto_stands_alone(self):
        p = run(12, {4: B(rest_bars=2), 12: B()}, title_page=False)
        self.assertEqual(p.groups[0].faces, 1)
        self.assertEqual(p.groups[0].pages, ((0, 4),))
        self.assertEqual(p.groups[0].turn.cls, "rest")

    def test_empty_and_tiny_parts(self):
        self.assertEqual(run(0).pages, 0)
        self.assertEqual(run(1).pages, 1)
        self.assertEqual(run(1).counts(), {})


class TestFoldOuts(unittest.TestCase):
    def test_three_pages_without_a_rest_take_a_fold_out(self):
        p = run(12)                                 # 3 pages, no turn possible
        self.assertEqual(p.folds, 1)
        self.assertEqual(p.groups[0].faces, 3)
        self.assertEqual(p.counts(), {})
        self.assertEqual(p.cost, 3 * tp.Costs().page + tp.Costs().fold)

    def test_without_fold_outs_the_same_part_has_a_bad_turn(self):
        p = run(12, allow_fold=False)
        self.assertEqual(p.folds, 0)
        self.assertEqual(p.counts(), {"bad": 1})

    def test_a_fold_out_ends_at_a_rest_turn_only(self):
        p = run(20, {12: B(rest_bars=2)})
        self.assertEqual(p.folds, 1)
        self.assertEqual(p.groups[0].turn.cls, "rest")
        self.assertEqual(p.groups[0].pages[-1][1], 12)

    def test_a_fold_out_never_ends_at_a_turn_while_playing(self):
        for bounds in ({}, {12: B(bridge_bars=1)}, {12: B(movement=True)}):
            with self.subTest(bounds=bounds):
                p = run(20, bounds)
                for g in p.groups:
                    if g.fold:
                        self.assertIn(g.turn.cls, ("rest", "rest1", "end"))

    def test_a_fold_out_never_follows_a_turn_while_playing(self):
        # lines 0-8 then a bad turn, then 12 lines (3 pages): the fold-out
        # would have to start after the bad turn (no hand free to unfold)
        p = run(20, {8: B(), 12: B()})
        for k, g in enumerate(p.groups):
            if g.fold and k > 0:
                self.assertIn(p.groups[k - 1].turn.cls, ("rest", "rest1"))

    def test_one_bar_of_rest_allows_a_fold_out(self):
        p = run(20, {12: B(rest_bars=1)})
        self.assertEqual(p.folds, 1)
        self.assertEqual(p.groups[0].turn.cls, "rest1")

    def test_a_fold_out_costs_more_than_a_rest_turn_and_less_than_a_bad_turn(self):
        # two rests make a plain spread cheaper than a fold-out
        p = run(16, {8: B(rest_bars=2)})
        self.assertEqual(p.folds, 0)
        # no rest: a fold-out beats a bad turn
        self.assertEqual(run(12).folds, 1)

    def test_fold_outs_can_be_switched_off(self):
        self.assertEqual(run(12, allow_fold=False).folds, 0)


if __name__ == "__main__":
    unittest.main()
