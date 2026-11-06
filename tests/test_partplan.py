# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""Tests for partplan: the options of a part, `partitor plan` (DESIGN.md §5.8).

Needs the venv packages (numpy, opencv, pymupdf, PyYAML); without them every test
is skipped. Run with the venv interpreter:

    venv/bin/python3 -m unittest -v tests/test_partplan.py
"""
import dataclasses
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from support import flow_line, needs_deps, np, pt  # noqa: E402,F401
from support import setUpModule, tearDownModule  # noqa: E402,F401


def music(bars, width=2000, key=True, first=False, h=300):
    """A synthetic line of len(bars) bars; bars: barline x positions."""
    s = flow_line([(70 + 10 * i, 44 + 3 * (i % 5)) for i in range(len(bars) - 1)], list(bars),
                  width=width, key=key, first=first)
    return s


def rest(bars_n, bar=1):
    img = np.zeros((130, 2000), bool)
    s = pt.Strip(img, 0, 40, 80, 10.0, np.zeros_like(img))
    return dataclasses.replace(s, rest_src=(None, 0, pt.RestRun(bars_n, bar)))


def part(n_lines=60, rests=()):
    """A part of n_lines lines of 8 bars: two lines share their key, so a prefix is found."""
    out = []
    for i in range(n_lines):
        if i in rests:
            out.append(rest(8, 1 + 8 * i))
        else:
            out.append(music([250 * (k + 1) for k in range(8)], first=(i == 0)))
    return out


OPTS = {**pt.LAYOUT_DEFAULTS, "scale": 1.0, "margin_side": 8.0, "binding": 12.7, "title_page": "auto"}


@needs_deps
class TestSource(unittest.TestCase):
    def test_lines_are_read_with_bars_prefix_and_rests(self):
        st = part(10, rests={3})
        src = pt.read_source(st, OPTS, 400)
        self.assertEqual(len(src.lines), 10)
        self.assertEqual(src.lines[3]["rest"], 8)
        self.assertIsNone(src.lines[3]["bars"])
        ln = src.lines[1]
        self.assertEqual(len(ln["bars"]), 8)
        self.assertGreater(ln["copy"], 0)
        self.assertTrue(src.exact)

    def test_saved_lines_are_taken_at_their_music_share(self):
        st = part(10)
        full = pt.read_source(st, OPTS, 400)
        est = pt.read_source(st, OPTS, 400, share=pt.JUSTIFY_SHARE)
        self.assertFalse(est.exact)
        self.assertAlmostEqual(est.lines[1]["bars"][2], full.lines[1]["bars"][2] * pt.JUSTIFY_SHARE)

    def test_a_line_that_ends_at_a_final_barline_can_be_cut(self):
        s = music([250 * (k + 1) for k in range(8)])
        s.ends_at_bar = False                     # saved before BAR_END_SP: the flag is stale
        s.end_gap_sp = 2.2
        st = [music([250 * (k + 1) for k in range(8)], first=True), s, music([250 * (k + 1) for k in range(8)])]
        self.assertIsNotNone(pt.read_source(st, OPTS, 400).lines[1]["bars"])
        s.end_gap_sp = 6.0
        self.assertIsNone(pt.read_source(st, OPTS, 400).lines[1]["bars"])

    def test_the_source_survives_json(self):
        src = pt.read_source(part(10, rests={3}), OPTS, 400)
        back = pt.Source.from_dict(json.loads(json.dumps(src.to_dict())))
        self.assertEqual(back.lines, src.lines)
        self.assertEqual((back.dpi, back.sp), (src.dpi, src.sp))

    def test_plan_data_of_another_format_is_refused(self):
        with self.assertRaises(ValueError):
            pt.Source.from_dict({"format": 999, "dpi": 400, "sp": 10, "lines": []})
        with self.assertRaises(ValueError):
            pt.Source.from_dict({})

    def test_plan_data_is_kept_in_the_saved_lines(self):
        with tempfile.TemporaryDirectory() as d:
            p = pt.lines_path(Path(d), "Trombones")
            st = part(10)
            pt.save_lines(p, "Trombones", 400, {}, dict(OPTS), st, pt.read_source(st, OPTS, 400).to_dict())
            back = pt.load_lines(p)
            self.assertEqual(pt.Source.from_dict(back["plan"]).lines, pt.read_source(st, OPTS, 400).lines)
            pt.save_lines(p, "Trombones", 400, {}, dict(OPTS), st)           # none given: no key
            self.assertNotIn("plan", pt.load_lines(p))


@needs_deps
class TestEstimate(unittest.TestCase):
    def src(self, n=60, rests=()):
        return pt.read_source(part(n, rests), OPTS, 400)

    def test_a_smaller_staff_needs_fewer_pages(self):
        s = self.src()
        pages = [pt.estimate(s, OPTS, "letter", mm).pages for mm in (8.0, 7.0, 6.0, 5.0)]
        self.assertEqual(pages, sorted(pages, reverse=True))
        self.assertGreater(pages[0], pages[-1])

    def test_ledger_needs_fewer_pages_than_letter(self):
        s = self.src()
        self.assertLess(pt.estimate(s, OPTS, "ledger", 7.0).pages, pt.estimate(s, OPTS, "letter", 7.0).pages)

    def test_lines_are_cut_when_the_text_is_narrower_than_the_line(self):
        s = self.src()
        o = pt.estimate(s, OPTS, "letter", 8.0)
        self.assertTrue(o.ok and o.reflow)

    def test_a_line_that_cannot_be_cut_limits_the_staff(self):
        st = part(10)
        st[4] = flow_line([], [1900], width=2000, key=False)         # one bar, no prefix: whole
        s = pt.read_source(st, OPTS, 400)
        big = pt.estimate(s, OPTS, "letter", 8.0)
        self.assertFalse(big.ok)
        self.assertIn("line 5 cannot be cut", big.note)

    def test_fold_outs_only_where_a_sheet_of_two_pages_exists(self):
        s = pt.read_source(part(36, {16, 33}), OPTS, 400)
        letter = pt.estimate(s, OPTS, "letter", 6.0)
        self.assertGreaterEqual(letter.folds, 1)                 # three pages between two rests
        self.assertEqual(pt.estimate(s, OPTS, "ledger", 6.0).folds, 0)

    def test_no_fold_outs_when_duplex_is_off(self):
        s = pt.read_source(part(36, {16, 33}), OPTS, 400)
        self.assertEqual(pt.estimate(s, {**OPTS, "duplex": "off"}, "letter", 6.0).folds, 0)

    def test_a_part_with_no_rest_has_no_fold_out(self):
        s = self.src(n=80)
        self.assertEqual(pt.estimate(s, OPTS, "letter", 6.0).folds, 0)   # a fold-out ends at a rest turn

    def test_binding_costs_text_width_and_so_pages(self):
        s = self.src()
        a = pt.estimate(s, {**OPTS, "binding": 0.0}, "letter", 8.0).pages
        b = pt.estimate(s, {**OPTS, "binding": 40.0}, "letter", 8.0).pages
        self.assertGreaterEqual(b, a)

    def test_rests_give_rest_turns(self):
        s = self.src(n=60, rests={9, 19, 29, 39, 49})
        o = pt.estimate(s, OPTS, "letter", 5.0)
        self.assertGreater(o.counts.get("rest", 0), 0)


@needs_deps
class TestOptions(unittest.TestCase):
    def test_rows_are_numbered_largest_staff_first_one_per_paper(self):
        s = pt.read_source(part(30), OPTS, 400)
        rows = pt.options(s, OPTS, ("letter", "ledger"))
        self.assertEqual([r.n for r in rows], list(range(1, len(rows) + 1)))
        self.assertEqual([(r.paper, r.staff_mm) for r in rows[:4]],
                         [("letter", 8.0), ("ledger", 8.0), ("letter", 7.5), ("ledger", 7.5)])
        self.assertEqual(len(rows), 2 * len(pt.SIZES))

    def test_sizes_below_the_floor_are_left_out(self):
        s = pt.read_source(part(30), OPTS, 400)
        rows = pt.options(s, OPTS, ("letter",), floor_mm=6.0)
        self.assertTrue(all(r.staff_mm >= 6.0 for r in rows))

    def test_set_pairs_follow_the_option(self):
        o = pt.Option("letter", 6.5, True, "", 29, True, None, True, 7)
        self.assertEqual(pt.set_pairs("Trombones", o),
                         ["Trombones:paper=letter", "Trombones:max_staff_mm=6.5", "Trombones:reflow=on",
                          "Trombones:foldouts=on", f"Trombones:pages={29 + pt.SLACK_PAGES}"])
        o2 = pt.Option("ledger", 8.0, True, "", 120, False, None, False, 1)
        pairs = pt.set_pairs("X", o2)
        self.assertIn("X:reflow=off", pairs)
        self.assertIn("X:pages=99", pairs)                       # never above the limit of `set`

    def test_the_pairs_are_accepted_by_set(self):
        o = pt.Option("letter", 6.5, True, "", 29, True, None, True, 7)
        data = {"parts": ["Trombones"], "layout": {}}
        pt.apply_set(data, pt.set_pairs("Trombones", o))
        own = data["layout"][pt.PART_LAYOUT_KEY]["Trombones"]
        self.assertEqual((own["paper"], own["max_staff_mm"], own["reflow"], own["foldouts"], own["page_count"]),
                         ("letter", 6.5, "on", "on", 31))


if __name__ == "__main__":
    unittest.main()
