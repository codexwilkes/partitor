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

from support import cli_items, flow_line, needs_deps, np, pt  # noqa: E402,F401
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
        self.assertTrue(big.note.endswith(" mm of music (bar 1)"), big.note)       # the bars of the line (0.8.32)
        st[4] = flow_line([], [1900], width=2000, key=False, nums=[37])
        self.assertIn("(bar 37)", pt.estimate(pt.read_source(st, OPTS, 400), OPTS, "letter", 8.0).note)

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
class TestAsBuilt(unittest.TestCase):
    """0.8.43 (F3): the plan models the default build: the gap the build tightens to, uncut lines up
    to the full text width, and a `*` row only for the layout that was built."""

    def test_pitch_terms_give_the_pitches_at_any_gap(self):
        st = part(12)
        st[5].movement = True
        terms = pt.pitch_terms(st, OPTS)
        for gap in (10.0, 8.5, 7.0):
            with self.subTest(gap=gap):
                self.assertEqual(pt.pitches(st, {**OPTS, "gap": gap}), [pt.pitch_at(t, gap) for t in terms])

    def pages_at(self, src, gap, gap_min, mm=6.0):
        return pt.estimate(src, {**OPTS, "gap": gap, "gap_min": gap_min}, "letter", mm)

    def test_the_estimate_tightens_the_gap_as_the_build_does(self):
        for n in range(20, 120):
            src = pt.read_source(part(n), OPTS, 400)
            wide, tight = self.pages_at(src, 10.0, 10.0), self.pages_at(src, 7.0, 7.0)
            if pt.turns(tight.pages) < pt.turns(wide.pages):
                break
        else:
            self.fail("no part where a tighter gap saves a turn")
        o = self.pages_at(src, 10.0, 7.0)
        self.assertEqual(pt.turns(o.pages), pt.turns(tight.pages))      # fewest turns first
        self.assertLess(o.gap, 10.0)
        self.assertGreaterEqual(o.gap, 7.0)
        old = pt.Source(src.dpi, src.sp, [{k: v for k, v in ln.items() if k != "pt"} for ln in src.lines])
        self.assertEqual(self.pages_at(old, 10.0, 7.0).pages, wide.pages)    # old plan data: the saved pitch

    def test_an_uncut_line_up_to_the_text_width_fits(self):
        st = part(10)
        st[4] = flow_line([], [1900], width=2000, key=False)         # one bar, no prefix: never cut
        src = pt.read_source(st, OPTS, 400)
        whole = src.lines[4]["whole"]
        pw, _ = pt.PAPER["letter"]
        usable = pt.usable_width({**OPTS, "paper": "letter"}, pw)
        mm = 0.99 * usable * 4.0 * src.sp * 25.4 / (72.0 * whole)      # the line fills 99 % of the text
        self.assertTrue(pt.estimate(src, OPTS, "letter", mm).ok)
        self.assertFalse(pt.estimate(src, OPTS, "letter", mm * 1.03).ok)

    def test_a_build_without_re_flow_is_estimated_without_cuts(self):
        src = pt.read_source(part(10), OPTS, 400)
        cut = pt.estimate(src, OPTS, "letter", 8.0)
        self.assertTrue(cut.ok and cut.reflow)
        whole = pt.estimate(src, OPTS, "letter", 8.0, cut=False)    # the lines are wider than the text
        self.assertFalse(whole.ok)
        small = pt.estimate(src, OPTS, "letter", 3.0, cut=False)
        self.assertTrue(small.ok)
        self.assertFalse(small.reflow)
        self.assertEqual(sum(j - i for g in small.plan.groups for i, j in g.pages), 10)

    def test_the_source_marks_section_starts(self):
        st = part(6)
        src = pt.read_source(st, OPTS, 400)
        self.assertEqual([ln["sec"] for ln in src.lines], [pt.section_start(x) for x in st])

    def test_with_the_costs_of_the_build_the_estimate_gives_the_pages_of_the_build(self):
        """The rows price turns as fold-out parts do; the estimate of a build without fold-outs takes
        the costs of the build (render.plan_costs) and gives the pages its planner gives."""
        o = {**OPTS, "turns": "any", "logo": "off", "title_page": "auto",
             "gap_min": OPTS["gap"]}                                            # the built gap
        sp = 10.0
        for n in range(30, 90, 4):
            st = part(n, rests={n // 3, n // 2 + 1})
            src = pt.read_source(st, o, 400)
            mm = 3.0
            s1 = mm * 400 / (4.0 * sp * 25.4)
            built = len(pt.layout_pages(st, 400, {**o, "scale": s1})[0])
            est = pt.estimate(src, o, "letter", mm, cut=False, costs=pt.plan_costs(o))
            with self.subTest(n=n):
                self.assertEqual(est.pages, built)

    def opt(self, staff=6.0, ok=True, reflow=False, folds=0, paper="letter"):
        plan = SimpleNamespace(folds=folds, playing=0, counts=lambda: {})
        return pt.Option(paper, staff, ok, "" if ok else "x", 3, False, plan if ok else None, reflow, 1)

    def test_the_star_marks_the_built_layout_only(self):
        built, lay = {"staff_mm": 5.9, "reflow": False}, {"paper": "letter"}
        self.assertTrue(pt.as_built(self.opt(), built, lay))
        self.assertFalse(pt.as_built(self.opt(paper="ledger"), built, lay))
        self.assertFalse(pt.as_built(self.opt(staff=6.5), built, lay))
        self.assertFalse(pt.as_built(self.opt(ok=False), built, lay))            # cannot be made
        self.assertFalse(pt.as_built(self.opt(reflow=True), built, lay))         # cut lines, built uncut
        self.assertTrue(pt.as_built(self.opt(reflow=True), {**built, "reflow": True}, lay))
        self.assertFalse(pt.as_built(self.opt(folds=1), built, lay))             # foldouts off
        self.assertTrue(pt.as_built(self.opt(folds=1), built, {**lay, "foldouts": "on"}))
        rows = pt.plan_rows([self.opt(ok=False)], built, lay)
        self.assertFalse(rows[1].startswith("*"))


@needs_deps
class TestLabelColumn(unittest.TestCase):
    """A group's label column is added after the cut and the staff shrinks to fit (0.8.7)."""

    def src(self, label_px):
        return pt.read_source(part(60), OPTS, 400, label_px=label_px)

    def test_label_column_helper(self):
        st = part(4)
        self.assertEqual(pt.label_column(st, 10.0), 0)               # a part: no labels
        g = [dataclasses.replace(s, staff_labels=[("Altposaune", 0, 40), ("Tenorposaune", 130, 170)])
             for s in st]
        col = pt.label_column(g, 10.0)
        self.assertGreater(col, 30)                                  # short names + 3 sp
        self.assertGreaterEqual(pt.label_column(g, 10.0, {"Altposaune": (1, 2)}),
                                int((pt.AMB_W_SP + 3.0) * 10.0))

    def test_the_label_column_is_kept_in_the_plan_data(self):
        s = self.src(80.0)
        self.assertEqual(pt.Source.from_dict(s.to_dict()).label_px, 80.0)
        self.assertEqual(pt.Source.from_dict({k: v for k, v in s.to_dict().items() if k != "label_px"}).label_px, 0.0)

    def test_lines_are_cut_for_a_larger_staff_than_the_one_printed(self):
        o = pt.estimate(self.src(150.0), OPTS, "letter", 6.5)
        self.assertTrue(o.ok)
        self.assertGreater(o.cap_mm, 6.5)                            # the build is told this cap
        self.assertGreaterEqual(o.budget, o.pages)                   # more pages at the cut size
        none = pt.estimate(self.src(0.0), OPTS, "letter", 6.5)
        self.assertAlmostEqual(none.cap_mm, 6.5, places=6)           # no label column: no shrink
        self.assertLess(none.cap_mm, o.cap_mm)

    def test_a_label_column_costs_pages(self):
        a = pt.estimate(self.src(0.0), OPTS, "letter", 6.5).pages
        b = pt.estimate(self.src(200.0), OPTS, "letter", 6.5).pages
        self.assertGreaterEqual(b, a)

    def test_a_label_column_wider_than_the_text_is_refused(self):
        o = pt.estimate(self.src(1e6), OPTS, "letter", 6.5)
        self.assertFalse(o.ok)
        self.assertIn("label column", o.note)

    def test_set_pairs_use_the_cap_and_the_budget(self):
        o = pt.estimate(self.src(150.0), OPTS, "letter", 6.5)
        pairs = pt.set_pairs("G", o)
        cap = float(next(p for p in pairs if "max_staff_mm" in p).split("=")[1])
        self.assertGreaterEqual(cap, o.cap_mm)
        self.assertLess(cap, o.cap_mm + 0.011)
        self.assertIn(f"G:pages={o.budget + pt.SLACK_PAGES}", pairs)


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

    @staticmethod
    def fake(n, paper, staff, bad, folds=0, pages=20, ok=True):
        plan = SimpleNamespace(folds=folds, playing=bad, counts=lambda: {"bad": bad})
        return pt.Option(paper, staff, ok, "" if ok else "x", pages, True, plan if ok else None, False, n)

    def test_best_row_per_paper_has_the_fewest_bad_turns_then_the_largest_staff(self):
        rows = [self.fake(1, "letter", 8.0, 3), self.fake(2, "ledger", 8.0, 0),
                self.fake(3, "letter", 7.0, 1), self.fake(4, "letter", 6.5, 0, folds=1),
                self.fake(5, "letter", 6.0, 0, folds=0), self.fake(6, "ledger", 7.5, 0),
                self.fake(7, "letter", 5.0, 0, ok=False)]
        self.assertEqual(pt.best_rows(rows), {2, 4})
        rows[3] = self.fake(4, "letter", 6.5, 0, folds=2)           # same staff size: fewer fold-outs
        rows.append(self.fake(8, "letter", 6.5, 0, folds=1))
        self.assertEqual(pt.best_rows(rows), {2, 8})
        self.assertEqual(pt.best_rows([self.fake(1, "letter", 8.0, 0, ok=False)]), set())

    def test_plan_rows_short_view_shows_built_and_best_rows_and_says_how_to_see_all(self):
        rows = [self.fake(i, "letter", 8.0 - 0.5 * i, 5 - i) for i in range(1, 5)]    # best: #4
        old, lay = {"staff_mm": 7.5}, {"paper": "letter"}                              # built: #1
        short = pt.plan_rows(rows, old, lay, show_all=False)
        self.assertIn("short", short[0])
        self.assertNotIn("1 bar", short[0])
        body = [x for x in short[1:] if "more options" not in x and (x.strip()[0:1].isdigit() or x[:1] == "*")]
        self.assertEqual([x.split()[1 if x[:1] == "*" else 0] for x in body], ["1", "4"])
        self.assertTrue(body[0].startswith("*"))
        self.assertIn("best", body[1])
        self.assertIn("2 more options: add --all", short[-1])
        full = pt.plan_rows(rows, old, lay)
        self.assertEqual(len(full), 5)                                  # header and four rows
        self.assertNotIn("more options", " ".join(full))

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


@needs_deps
class TestTrialGroups(unittest.TestCase):
    """`plan --group Name=A,B`: the data of the temporary copy (0.8.9)."""

    DATA = {"id": "2026-10-0003", "parts": ["Alto", "Tenor", "Bass", "Organ"],
            "groups": {"Trio": ["Alto", "Tenor", "Bass"]},
            "layout": {"paper": "ledger", pt.PART_LAYOUT_KEY: {"Trio": {"group_gap": 5.0, "binding": 12.7},
                                                              "Organ": {"gap": 9.0}}},
            "built": {"parts": [{"part": "Trio"}]}, "pending": ["gap"], "skip": []}

    def test_the_copy_has_only_the_trial_groups_and_skips_every_part(self):
        d, names = pt.trial_data(self.DATA, ["TB=Tenor,Bass", "AT=Alto,Tenor"])
        self.assertEqual(names, ["TB", "AT"])
        self.assertEqual(d["groups"], {"TB": ["Tenor", "Bass"], "AT": ["Alto", "Tenor"]})
        self.assertEqual(d[pt.SKIP_KEY], self.DATA["parts"])
        self.assertNotIn("built", d)
        self.assertNotIn("pending", d)

    def test_the_trial_groups_take_the_layout_of_the_first_group(self):
        d, _ = pt.trial_data(self.DATA, ["AT=Alto,Tenor"])
        self.assertEqual(d["layout"][pt.PART_LAYOUT_KEY], {"AT": {"group_gap": 5.0, "binding": 12.7}})
        self.assertEqual(d["layout"]["paper"], "ledger")

    def test_parts_may_be_named_or_numbered_and_stay_in_score_order(self):
        d, _ = pt.trial_data(self.DATA, ["X=3,Alto"])
        self.assertEqual(d["groups"]["X"], ["Alto", "Bass"])

    def test_every_part_is_a_group_too(self):
        d, _ = pt.trial_data(self.DATA, ["Tutti=all"])
        self.assertEqual(d["groups"]["Tutti"], self.DATA["parts"])

    def test_the_item_data_is_not_changed(self):
        before = repr(self.DATA)
        pt.trial_data(self.DATA, ["AT=Alto,Tenor"])
        self.assertEqual(repr(self.DATA), before)

    def test_bad_specs_are_refused(self):
        for bad in ("nogroup", "AT=", "=Alto,Tenor", "AT=Alto", "Alto=Tenor,Bass", "AT=Alto,Nobody",
                    "AT=Alto,Alto", "AT=9,10"):
            with self.subTest(spec=bad), self.assertRaises(ValueError):
                pt.trial_data(self.DATA, [bad])


if __name__ == "__main__":
    unittest.main()


@needs_deps
class TestMergedRestsAtTheEdge(unittest.TestCase):
    """A merged rest that ends or starts a line is a rest at a page turn (0.8.16)."""

    def line(self, rin=0, rout=0):
        return dataclasses.replace(music([250 * (k + 1) for k in range(8)]), rest_in=rin, rest_out=rout)

    def test_the_source_keeps_the_edges_of_each_line(self):
        st = [self.line(), self.line(rout=3), self.line(rin=2)]
        src = pt.read_source(st, OPTS, 400)
        self.assertEqual([(ln["rin"], ln["rout"]) for ln in src.lines], [(0, 0), (0, 3), (2, 0)])

    def test_edge_rest_counts_a_merged_rest_on_either_side_of_the_turn(self):
        st = [self.line(), self.line(rout=3), self.line(rin=2), self.line()]
        self.assertEqual(pt.edge_rest(st, 1), 0)
        self.assertEqual(pt.edge_rest(st, 2), 3)          # line 1 ends in a 3-bar rest
        self.assertEqual(pt.edge_rest(st, 3), 0)
        st2 = [self.line(), self.line(), self.line(rin=2)]
        self.assertEqual(pt.edge_rest(st2, 2), 2)         # line 2 starts with a 2-bar rest

    def test_a_merged_rest_of_two_bars_makes_a_rest_turn_and_one_bar_does_not(self):
        st = [self.line(), self.line(rout=2), self.line()]
        self.assertTrue(pt.rest_turn(st, 2))
        self.assertTrue(pt.good_turn(st, 2))
        st = [self.line(), self.line(rout=1), self.line()]
        self.assertFalse(pt.rest_turn(st, 2))             # one bar: not a rest turn (REST_TURN_MIN)
        self.assertFalse(pt.rest_turn([self.line(), self.line(), self.line()], 2))

    def test_a_cut_piece_gets_the_rest_of_its_edge_bar(self):
        """read_source keeps the rest counts of the bars; _pieces gives each piece its edges."""
        s = dataclasses.replace(self.line(), rest_counts=[0, 0, 0, 4, 0, 0, 0, 1])
        st = [music([250 * (k + 1) for k in range(8)], first=True), s,
              music([250 * (k + 1) for k in range(8)])]
        src = pt.read_source(st, OPTS, 400)
        self.assertEqual(src.lines[1]["rcount"], [0, 0, 0, 4, 0, 0, 0, 1])
        pieces, wide = pt._pieces(src, src.lines[1]["copy"] + 700)    # about 2.8 bars of 250 px
        self.assertIsNone(wide)
        mine = [p for p in pieces if p[0] == 1]
        self.assertGreater(len(mine), 1)
        self.assertEqual(sum(1 for p in mine if 4 in (p[2], p[3])), 1)  # one piece has the merged rest at an edge
        self.assertEqual(mine[-1][3], 1)                                # the last bar is a one-bar rest at the end
        self.assertTrue(all(p[2] in (0, 4) for p in mine))

    def test_the_planner_takes_the_rest_turn_it_could_not_see_before(self):
        """Two lines per page: with a 3-bar rest ending the first line of a spread, the plan has a rest turn there."""
        n = 12
        plain = [self.line() for _ in range(n)]
        marked = [self.line(rout=3) if i % 2 == 1 else self.line() for i in range(n)]
        o = {**OPTS, "paper": "letter", "foldouts": "off", "title_page": "off"}
        a = pt.estimate(pt.read_source(plain, o, 400), o, "letter", 8.0)
        b = pt.estimate(pt.read_source(marked, o, 400), o, "letter", 8.0)
        self.assertLessEqual(b.counts.get("bad", 0) + b.counts.get("bridge", 0),
                             a.counts.get("bad", 0) + a.counts.get("bridge", 0))
        self.assertGreaterEqual(b.counts.get("rest", 0), a.counts.get("rest", 0))



class TestManualBreaksInPlan(unittest.TestCase):
    """0.8.21: the estimates keep the manual page breaks (a break after a bar)."""

    def numbered(self, n=24, **kw):
        out = []
        for k in range(n):
            ln = music([250 * (j + 1) for j in range(8)], first=(k == 0))
            out.append(dataclasses.replace(ln, bar_nums=[], bar_no=1 + 8 * k, **kw))
        return out

    O = {**OPTS, "paper": "letter", "foldouts": "off", "title_page": "off"}

    def test_the_source_keeps_the_bar_span_of_each_line(self):
        src = pt.read_source(self.numbered(4), self.O, 400)
        self.assertEqual([ln["span"] for ln in src.lines], [[1, 8], [9, 16], [17, 24], None])   # the last line: unknown

    def test_a_piece_knows_its_last_bar(self):
        src = pt.read_source(self.numbered(4), self.O, 400)
        pieces, _ = pt._pieces(src, 1e9)
        self.assertEqual([p[4] for p in pieces], [8, 16, 24, None])

    def test_a_cut_line_gives_each_piece_its_last_bar(self):
        src = pt.read_source(self.numbered(3), self.O, 400)
        pieces, _ = pt._pieces(src, src.lines[1]["copy"] + 700)         # about 2.8 bars of 250 px
        mine = [p[4] for p in pieces if p[0] == 1]
        self.assertGreater(len(mine), 1)
        self.assertEqual(mine, sorted(mine))
        self.assertEqual(mine[-1], 16)                                   # the line ends at bar 16
        self.assertTrue(all(9 <= b <= 16 for b in mine))

    def test_a_merged_rest_counts_for_all_its_bars(self):
        st = self.numbered(3)
        st[1] = dataclasses.replace(st[1], rest_counts=[0, 0, 0, 4, 0, 0, 0, 1])      # 8 entries, 11 bars
        st[2] = dataclasses.replace(st[2], bar_no=20)
        src = pt.read_source(st, self.O, 400)
        self.assertEqual(src.lines[1]["span"], [9, 19])
        pieces, _ = pt._pieces(src, src.lines[1]["copy"] + 700)
        mine = [p[4] for p in pieces if p[0] == 1]
        self.assertEqual(mine[-1], 19)
        self.assertIn(15, mine + [15] if len(mine) == 1 else mine)      # after the 4-bar rest or before: never inside it

    def test_numbers_that_are_not_a_plain_run_are_unknown(self):
        st = self.numbered(3)
        st[1] = dataclasses.replace(st[1], bar_no=9)
        st[2] = dataclasses.replace(st[2], bar_no=30)                    # 8 bars, but the line spans 9-29
        src = pt.read_source(st, self.O, 400)
        pieces, _ = pt._pieces(src, 1e9)
        self.assertIsNone(pieces[1][4])

    def test_a_manual_break_ends_a_page_in_the_estimate(self):
        src = pt.read_source(self.numbered(24), self.O, 400)
        base = pt.estimate(src, self.O, "letter", 8.0)

        def ends(o):
            return sorted(j for g in o.plan.groups for _, j in g.pages)
        moved = []
        for bar in range(1, 190):
            got = pt.estimate(src, {**self.O, "breaks": [bar]}, "letter", 8.0)
            if got.lost == () and ends(got) != ends(base):
                moved.append((bar, got))
        self.assertTrue(moved, "no break changed the pages")

    def test_a_break_that_ends_no_line_is_reported_lost(self):
        src = pt.read_source(self.numbered(24), self.O, 400)
        got = pt.estimate(src, {**self.O, "breaks": [5, 999]}, "letter", 8.0)
        self.assertEqual(got.lost, (999,))      # 0.8.47: bar 5 is inside a line that is cut: a piece ends there
        self.assertEqual(pt.estimate(src, self.O, "letter", 8.0).lost, ())
        whole = pt.estimate(src, {**self.O, "breaks": [5]}, "letter", 3.0, cut=False)
        self.assertEqual(whole.lost, (5,))       # a line that is not cut keeps the bar inside

    def test_a_break_ends_a_cut_piece(self):
        """0.8.47: the estimate cuts a line at a break bar, as re-flow does."""
        src = pt.read_source(self.numbered(3), self.O, 400)
        pieces, _ = pt._pieces(src, 1e9, breaks=[12])
        self.assertEqual([p[4] for p in pieces if p[0] == 1], [12, 16])
        self.assertEqual([p[4] for p in pt._pieces(src, 1e9)[0] if p[0] == 1], [16])

    def test_the_table_says_when_a_break_is_lost(self):
        src = pt.read_source(self.numbered(24), self.O, 400)
        o = pt.estimate(src, {**self.O, "breaks": [999]}, "letter", 8.0)
        rows = cli_items.plan_rows([dataclasses.replace(o, n=1)], {"staff_mm": 8.0}, {"paper": "letter"})
        self.assertTrue(any("1 break(s) end no line" in r for r in rows), rows)

    def test_old_plan_data_without_spans_still_loads(self):
        src = pt.read_source(self.numbered(6), self.O, 400)
        d = src.to_dict()
        for ln in d["lines"]:
            ln.pop("span")
        back = pt.Source.from_dict(d)
        o = pt.estimate(back, {**self.O, "breaks": [8]}, "letter", 8.0)
        self.assertTrue(o.ok)
