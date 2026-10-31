# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""Tests for bar numbers, barline edits, bar rules and the proof.

Needs the venv packages (numpy, opencv, pymupdf, PyYAML); without them every test
is skipped. Run with the venv interpreter:

    venv/bin/python3 -m unittest -v tests/test_bars.py

Shared helpers: tests/support.py.
"""
import builtins
import contextlib
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from support import (  # noqa: E402,F401
    SRC,
    make_score_pdf,
    needs_deps,
    np,
    pt,
    pymupdf,
    setUpModule,
    tearDownModule,
)


@needs_deps
class TestBarNumbers(unittest.TestCase):
    def rec(self, rid, nbars, anchors=(), restart=False):
        return {"id": rid, "nbars": nbars, "anchors": list(anchors), "restart": restart}

    def test_plain_count(self):
        bars, changed, used = pt.assign_bars([self.rec("a", 4), self.rec("b", 3), self.rec("c", 3)])
        self.assertEqual(bars, [1, 5, 8])
        self.assertEqual((changed, used), ([], 0))

    def test_printed_number_corrects_missed_barline(self):
        # count says system c starts at 8, the printed 10 (2nd bar) says 9
        recs = [self.rec("a", 4), self.rec("b", 3), self.rec("c", 3, [(1, 10, False)])]
        bars, changed, _ = pt.assign_bars(recs)
        self.assertEqual(bars, [1, 5, 9])
        self.assertEqual(changed, ["c"])

    def test_pickup_bar_is_zero(self):
        recs = [self.rec("a", 4), self.rec("b", 4, [(0, 4, True)])]
        self.assertEqual(pt.assign_bars(recs)[0], [0, 4])

    def test_missed_barline_does_not_move_earlier_systems(self):
        recs = [self.rec("a", 4), self.rec("b", 3), self.rec("c", 3, [(0, 10, True)])]
        self.assertEqual(pt.assign_bars(recs)[0], [1, 5, 10])

    def test_movement_restarts_at_one(self):
        recs = [self.rec("a", 4), self.rec("b", 4), self.rec("c", 3, restart=True)]
        self.assertEqual(pt.assign_bars(recs)[0], [1, 5, 1])

    def test_far_misread_needs_confirmation(self):
        # "45" where the count says 9: ignored without a second agreeing number
        recs = [self.rec("a", 4), self.rec("b", 4), self.rec("c", 4, [(0, 45, True)]),
                self.rec("d", 4)]
        self.assertEqual(pt.assign_bars(recs)[0], [1, 5, 9, 13])
        recs[3]["anchors"] = [(0, 49, True)]
        self.assertEqual(pt.assign_bars(recs)[0][2:], [45, 49])

    def test_detect_barlines_rules(self):
        sp, th = 20.0, 2
        h, w = 400, 1200
        owner = np.full((h, w), pt.OWN_NONE, np.int32)
        conn = np.zeros((h, w), bool)
        sts = [pt.Staff(0, 0, [100 + 20 * k for k in range(5)], 100, 1100),
               pt.Staff(0, 1, [250 + 20 * k for k in range(5)], 100, 1100)]
        for i, st in enumerate(sts):
            for ly in st.lines:
                owner[int(ly), 100:1101] = i
            for x in (130, 136):                       # C clef bars (clef zone)
                owner[int(st.top):int(st.bottom) + 1, x:x + 3] = i
            for x in (500, 800):                       # real barlines
                owner[int(st.top) - 1:int(st.bottom) + 2, x:x + 2] = i
            owner[int(st.top):int(st.bottom), 650:652] = i     # a stem ...
            owner[int(st.top) + 25:int(st.top) + 33, 652:662] = i  # ... with its notehead
        ink = owner != pt.OWN_NONE
        xs = pt.detect_barlines(owner, conn, ink, sts, [0, 1], sp, th)
        self.assertEqual(len(xs), 2, xs)
        self.assertTrue(abs(xs[0] - 501) <= 2 and abs(xs[1] - 801) <= 2, xs)


    def test_clef_tails_in_two_gaps_are_no_barline(self):
        # Schein Nun p4.s1: G clefs stacked at one x reach into the gaps
        # (ink in the top and bottom fifth of both gaps): not a barline
        sp, th = 20.0, 2
        owner = np.full((600, 1200), pt.OWN_NONE, np.int32)
        conn = np.zeros(owner.shape, bool)
        tops = (100, 250, 400)
        sts = [pt.Staff(0, k, [t + 20 * j for j in range(5)], 100, 1100)
               for k, t in enumerate(tops)]
        for i, st in enumerate(sts):
            for ly in st.lines:
                owner[int(ly), 100:1101] = i
            owner[int(st.top) - 1:int(st.bottom) + 2, 800:802] = i       # a real barline
        ink = owner != pt.OWN_NONE
        for k in (0, 1):
            g0, g1 = int(sts[k].bottom) + 3, int(sts[k + 1].top) - 3
            n = (g1 - g0) // 4
            for x in range(173, 176):                                 # 3.65 sp from the start
                ink[g0:g0 + n, x] = True
                ink[g1 - n:g1, x] = True
        xs = pt.detect_barlines(owner, conn, ink, sts, [0, 1, 2], sp, th)
        self.assertEqual(len(xs), 1, xs)
        self.assertTrue(abs(xs[0] - 801) <= 2, xs)
        # the same columns far from the start (8 sp): a dotted barline
        ink2 = owner != pt.OWN_NONE
        for k in (0, 1):
            g0, g1 = int(sts[k].bottom) + 3, int(sts[k + 1].top) - 3
            n = (g1 - g0) // 4
            for x in range(260, 263):
                ink2[g0:g0 + n, x] = True
                ink2[g1 - n:g1, x] = True
        xs2 = pt.detect_barlines(owner, conn, ink2, sts, [0, 1, 2], sp, th)
        self.assertEqual(len(xs2), 2, xs2)
        self.assertTrue(abs(xs2[0] - 261) <= 3, xs2)


@needs_deps
class TestBarEdits(unittest.TestCase):
    """The operator mends a misread barline (bar_rules.bar_edits)."""

    def systems(self):
        # Schein Nun p4: 3 bars counted in p4.s1, 2 printed; p5.s1 prints 25
        return [{"id": "p3.s1", "bars": 19, "widths": [30.0] * 19, "restart": True,
                 "anchors": [[0, 1]]},
                {"id": "p4.s1", "bars": 3, "widths": [3.65, 55.26, 60.52]},
                {"id": "p4.s2", "bars": 3, "widths": [52.5, 32.4, 34.6]},
                {"id": "p5.s1", "bars": 3, "widths": [45.4, 34.2, 39.0], "anchors": [[0, 25]]}]

    def test_parse_and_format(self):
        ed = pt.parse_bar_edit("p4.s1:j1/3")
        self.assertEqual((ed["sid"], ed["op"], ed["n"], ed["pct"], ed["raw"]),
                         ("p4.s1", "j", 1, None, 3))
        ed = pt.parse_bar_edit("p5.s1:a2@40/3")
        self.assertEqual((ed["op"], ed["n"], ed["pct"]), ("a", 2, 40))
        self.assertEqual(pt.format_bar_edit("p5.s1", "a", 2, 3, 40), "p5.s1:a2@40/3")
        self.assertEqual(pt.format_bar_edit("p4.s1", "j", 1, 3), "p4.s1:j1/3")
        for bad in ("p4.s1:j1", "p4.s1:j1@50/3", "p4.s1:a1/3", "x", "p4.s1:z1/3"):
            self.assertIsNone(pt.parse_bar_edit(bad), bad)

    def test_join_and_split_shift_widths_anchors_repeats(self):
        e = {**self.systems()[1], "repeats": [[0, "start"], [1, "end"]], "anchors": [[2, 22]]}
        j, notes = pt.edit_bars(e, [pt.parse_bar_edit("p4.s1:j1/3")])
        self.assertEqual((j["bars"], j["widths"]), (2, [58.91, 60.52]))
        self.assertEqual(j["anchors"], [[1, 22]])                 # bar 3 is bar 2 now
        # the joined barline's mark goes; a repeat start right after the clef
        # stays, in front of bar 1 (index -1)
        self.assertEqual(j["repeats"], [[-1, "start"], [0, "end"]])
        self.assertEqual(notes, [])
        a, _ = pt.edit_bars(e, [pt.parse_bar_edit("p4.s1:a2@25/3")])
        self.assertEqual((a["bars"], a["widths"]), (4, [3.65, 13.81, 41.45, 60.52]))
        self.assertEqual(a["anchors"], [[3, 22]])
        self.assertEqual(a["repeats"], [[0, "start"], [2, "end"]])
        self.assertEqual(e["bars"], 3)                            # the stored entry is not changed
        # in order: join, then add in the joined bar
        both, _ = pt.edit_bars(e, [pt.parse_bar_edit("p4.s1:j1/3"),
                                   pt.parse_bar_edit("p4.s1:a1@50/3")])
        self.assertEqual(both["bars"], 3)

    def test_edit_for_other_bar_count_is_skipped(self):
        e = self.systems()[1]
        out, notes = pt.edit_bars(e, [pt.parse_bar_edit("p4.s1:j1/4")])    # made for 4 bars
        self.assertEqual(out["bars"], 3)
        self.assertEqual(len(notes), 1)
        self.assertIn("has 3 bar(s) now", notes[0])
        out, notes = pt.edit_bars(e, [pt.parse_bar_edit("p4.s1:j3/3")])    # no bar after bar 3
        self.assertEqual((out["bars"], len(notes)), (3, 1))
        out, notes = pt.edit_bars(e, [pt.parse_bar_edit("p4.s1:a1@2/3")])  # 2 % is out of range
        self.assertEqual((out["bars"], len(notes)), (3, 1))

    def test_edit_barlines_on_the_page(self):
        bl, rp, mn, notes = pt.edit_barlines([pt.parse_bar_edit("p4.s1:j1/3")],
                                             [503, 1774, 3166], 419, [(0, "start")], [503])
        self.assertEqual((bl, rp, mn, notes), ([1774, 3166], [[-1, "start"]], [], []))
        bl, rp, mn, _ = pt.edit_barlines([pt.parse_bar_edit("p4.s1:a2@50/3")],
                                         [503, 1774, 3166], 419, [(1, "end")], [])
        self.assertEqual(bl, [503, 1138, 1774, 3166])             # half way through bar 2
        self.assertEqual(rp, [[2, "end"]])
        bl, *_ , notes = pt.edit_barlines([pt.parse_bar_edit("p4.s1:a1@50/3")],
                                          [503, 1774, 3166], 419)
        self.assertEqual(bl[0], 461)                              # bar 1 starts at the staff start
        _, _, _, notes = pt.edit_barlines([pt.parse_bar_edit("p4.s1:j1/3")], [503, 1774], 419)
        self.assertIn("has 2 bar(s) now", notes[0] if notes else "")

    def test_renumber_follows_the_edit(self):
        lay = {"systems": self.systems(), "bar_rules": {"pickup": [], "split": [], "fix": {}}}
        pt.renumber(lay)
        self.assertEqual([e["bar"] for e in lay["systems"]], [1, 20, 23, 25])   # p5.s1 follows its printed 25
        lay["bar_rules"]["bar_edits"] = ["p4.s1:j1/3"]
        pt.renumber(lay)
        self.assertEqual([e["bar"] for e in lay["systems"]], [1, 20, 22, 25])
        self.assertEqual(lay["systems"][1]["bar_nums"], [20, 21])
        self.assertEqual(lay["systems"][1]["bars"], 3)                       # as detected
        lay["bar_rules"]["marks_add"] = [22]
        pt.renumber(lay)
        self.assertEqual(lay["systems"][2]["marks"], [[0, "A"]])             # first bar of p4.s2

    def test_mismatch_found_reported_once_and_cleared(self):
        sy, rules = self.systems(), {"pickup": [], "split": [], "fix": {}}
        ms = pt.bar_mismatches(pt.effective_systems(sy, rules), rules)
        self.assertEqual([(m["id"], m["counted"], m["printed"]) for m in ms],
                         [("p5.s1", 26, 25)])                  # only where the difference starts
        self.assertEqual(ms[0]["prev"], "p4.s2")
        self.assertIn("count bar 26", pt.mismatch_text(ms[0]))
        self.assertIn("say bar 25", pt.mismatch_text(ms[0]))
        # an edit that makes the count agree clears it
        r2 = {**rules, "bar_edits": ["p4.s1:j1/3"]}
        self.assertEqual(pt.bar_mismatches(pt.effective_systems(sy, r2), r2), [])
        # the operator keeps the printed numbers: not asked again; a changed case asks again
        r3 = {**rules, "bars_ack": [ms[0]["key"]]}
        self.assertEqual(pt.bar_mismatches(pt.effective_systems(sy, r3), r3), [])
        sy2 = self.systems()
        sy2[2]["bars"], sy2[2]["widths"] = 4, [20, 20, 20, 20]
        r4 = {**rules, "bars_ack": [ms[0]["key"]]}
        self.assertEqual(len(pt.bar_mismatches(pt.effective_systems(sy2, r4), r4)), 1)

    def test_mismatch_left_out_with_a_pickup_rule(self):
        sy = [{"id": "a", "bars": 3, "widths": [10, 40, 40], "restart": True},
              {"id": "b", "bars": 3, "widths": [40, 40, 40], "anchors": [[0, 3]]}]
        self.assertTrue(pt.bar_mismatches(sy, {"pickup": []}))
        self.assertEqual(pt.bar_mismatches(sy, {"pickup": ["a"]}), [])

    def test_iter_pages_applies_edits_to_the_page(self):
        with tempfile.TemporaryDirectory() as d:
            pdf = os.path.join(d, "s.pdf")
            make_score_pdf(pdf)
            res0, recs0 = next(pt.iter_pages(Path(pdf), 300, [0], ocr=False))
            n = recs0[0]["nbars"]
            ed = {"p1.s1": [pt.parse_bar_edit(f"p1.s1:j1/{n}")]}
            res1, recs1 = next(pt.iter_pages(Path(pdf), 300, [0], ocr=False, bar_edits=ed))
            self.assertEqual(recs1[0]["nbars"], n - 1)
            self.assertEqual(recs1[1]["nbars"], n)                  # other systems untouched
            self.assertEqual(len(res1.barlines[res1.systems[0][0].system]), n - 1)


def half_bar_like():
    """Schein Nun p7.s4 / p8.s1 in small: the last bar of line 2 is a half
    bar; line 3 starts with a clef stub (5.7 sp), a repeat start and the
    other half (new mensuration). The source prints 8 at bar 4 of line 3
    (stub counted); the halves are bar 6. Line 4 prints 10 at its bar 2."""
    return [{"id": "p1.s1", "bars": 3, "widths": [40.0, 40.0, 40.0], "restart": True,
             "geom": {"page": 1, "h": 4678, "staves": [[165, 400, 495]]}},
            {"id": "p1.s2", "bars": 3, "widths": [40.0, 40.0, 16.9], "anchors": [[0, 4]],
             "geom": {"page": 1, "h": 4678, "staves": [[165, 800, 895]]}},
            {"id": "p2.s1", "bars": 4, "widths": [5.7, 32.7, 37.5, 37.0],
             "repeats": [[0, "start"]], "anchors": [[3, 8]],
             "geom": {"page": 2, "h": 4678, "staves": [[165, 400, 495]]}},
            {"id": "p2.s2", "bars": 3, "widths": [40.0, 38.0, 39.0], "anchors": [[1, 10]],
             "geom": {"page": 2, "h": 4678, "staves": [[165, 800, 895]]}}]


@needs_deps
class TestHalfBarOverStub(unittest.TestCase):
    """A half bar at a line end, its other half after a clef stub and a repeat
    sign at the start of the next line (Schein Nun p7.s4 / p8.s1)."""

    def lay(self, **rules):
        return {"systems": half_bar_like(),
                "bar_rules": {"pickup": [], "split": [], "fix": {}, **rules}}

    def nums(self, lay):
        pt.renumber(lay)
        return {e["id"]: e["bar_nums"] for e in lay["systems"]}

    def test_stub_is_found(self):
        sy = half_bar_like()
        self.assertTrue(pt.stub_bar(sy[2]))
        self.assertFalse(pt.stub_bar(sy[1]))                   # no repeat start
        self.assertFalse(pt.stub_bar({**sy[2], "widths": [9.0, 30.0]}))   # wide enough

    def test_join_keeps_the_repeat_start_in_front_of_bar_one(self):
        r = {"bar_edits": ["p2.s1:j1/4"]}
        eff = pt.effective_systems(half_bar_like(), r)[2]
        self.assertEqual((eff["bars"], eff["widths"]), (3, [38.4, 37.5, 37.0]))
        self.assertEqual(eff["repeats"], [[-1, "start"]])
        self.assertEqual(eff["anchors"], [[2, 8]])
        # the bar after that repeat sign is bar 1 of the line: a split candidate
        flat = pt._flat_bars(pt.effective_systems(half_bar_like(), r), [0, 1, 2, 3])
        cands = [flat[b] for b in pt._boundaries(pt.effective_systems(half_bar_like(), r),
                                                 [0, 1, 2, 3], flat)]
        self.assertEqual(cands, [(2, 0)])

    def test_count_and_print_differ_without_edits(self):
        lay = self.lay()
        eff = pt.effective_systems(lay["systems"], lay["bar_rules"])
        ms = pt.bar_mismatches(eff, lay["bar_rules"])
        self.assertEqual([(m["id"], m["counted"], m["printed"]) for m in ms], [("p2.s1", 7, 5)])

    def test_join_and_split_give_the_printed_numbers(self):
        lay = self.lay(bar_edits=["p2.s1:j1/4"], split=["p2.s1:0"])
        n = self.nums(lay)
        self.assertEqual(n["p1.s2"], [4, 5, 6])
        self.assertEqual(n["p2.s1"], [6, 7, 8])              # the half bar and its other half: 6
        self.assertEqual(n["p2.s2"], [9, 10, 11])
        self.assertEqual([e["bar"] for e in lay["systems"]], [1, 4, 6, 9])
        eff = pt.effective_systems(lay["systems"], lay["bar_rules"])
        self.assertEqual(pt.bar_mismatches(eff, lay["bar_rules"]), [])

    def test_split_without_the_join_misnumbers(self):
        # the stub counted as a bar: this is why s N I tells to join first
        lay = self.lay(split=["p2.s1:1"])
        self.assertNotEqual(self.nums(lay)["p2.s2"], [9, 10, 11])

    def test_keeping_printed_numbers_also_closes_the_mismatch(self):
        lay = self.lay(bar_edits=["p2.s1:j1/4"])
        eff = pt.effective_systems(lay["systems"], lay["bar_rules"])
        ms = pt.bar_mismatches(eff, lay["bar_rules"])
        self.assertEqual([(m["counted"], m["printed"]) for m in ms], [(7, 6)])
        lay["bar_rules"]["bars_ack"] = [ms[0]["key"]]
        self.assertEqual(self.nums(lay)["p2.s1"], [6, 7, 8])
        self.assertEqual(pt.bar_mismatches(eff, lay["bar_rules"]), [])

    def test_letters_by_bar_position(self):
        lay = self.lay(bar_edits=["p2.s1:j1/4"], split=["p2.s1:0"])
        pt.renumber(lay)
        by = {e["id"]: e.get("marks") for e in lay["systems"]}
        self.assertEqual(by["p2.s1"], [[1, "A"]])             # automatic: first full bar after the repeat
        self.assertEqual(pt.toggle_mark(lay["bar_rules"], lay["systems"], ("p2.s1", 0)), "added")
        pt.renumber(lay)
        self.assertEqual(lay["systems"][2]["marks"], [[0, "A"], [1, "B"]])
        self.assertEqual(pt.toggle_mark(lay["bar_rules"], lay["systems"], ("p2.s1", 1)), "removed")
        pt.renumber(lay)
        self.assertEqual(lay["systems"][2]["marks"], [[0, "A"]])
        self.assertEqual(lay["bar_rules"]["marks_add"], ["p2.s1:0"])
        self.assertEqual(lay["bar_rules"]["marks_drop"], ["p2.s1:1"])
        # again: both switch off
        self.assertEqual(pt.toggle_mark(lay["bar_rules"], lay["systems"], ("p2.s1", 0)), "removed")
        self.assertEqual(pt.toggle_mark(lay["bar_rules"], lay["systems"], ("p2.s1", 1)), "added")
        self.assertNotIn("marks_add", lay["bar_rules"])
        self.assertNotIn("marks_drop", lay["bar_rules"])

    def test_a_number_two_bars_share_marks_the_first(self):
        lay = self.lay(bar_edits=["p2.s1:j1/4"], split=["p2.s1:0"])
        pt.renumber(lay)
        pt.toggle_mark(lay["bar_rules"], lay["systems"], 6)
        pt.renumber(lay)
        self.assertEqual(lay["systems"][1]["marks"], [[2, "A"]])    # the half bar of line 2

    def test_toggle_mark_errors_and_mixed_list_order(self):
        lay = self.lay(bar_edits=["p2.s1:j1/4"], split=["p2.s1:0"])
        pt.renumber(lay)
        with self.assertRaises(ValueError):
            pt.toggle_mark(lay["bar_rules"], lay["systems"], ("p2.s1", 9))
        with self.assertRaises(ValueError):
            pt.toggle_mark(lay["bar_rules"], lay["systems"], ("p9.s9", 0))
        with self.assertRaises(ValueError):
            pt.toggle_mark(lay["bar_rules"], lay["systems"], 99)
        r = lay["bar_rules"]
        pt.toggle_mark(r, lay["systems"], ("p2.s1", 0))
        pt.toggle_mark(r, lay["systems"], 9)
        self.assertEqual(r["marks_add"], [9, "p2.s1:0"])           # numbers first
        self.assertEqual(pt.mark_items([3, "p2.s1:0", "7", "junk", "x:y"]),
                         ({3, 7}, {("p2.s1", 0)}))

    def test_bar_span_text(self):
        self.assertEqual(pt.bar_span_text([48, 49, 50]), "bars 48-50")
        self.assertEqual(pt.bar_span_text([48, 48, 49, 50]), "bars 48 48 49 50")
        self.assertEqual(pt.bar_span_text([7]), "bar 7")
        self.assertEqual(pt.bar_span_text([]), "")

    def test_bars_listing(self):
        lay = self.lay(bar_edits=["p2.s1:j1/4"], split=["p2.s1:0"])
        pt.renumber(lay)
        eff = pt.effective_systems(lay["systems"], lay["bar_rules"])
        txt = "\n".join(pt.bars_listing(lay["systems"][2], eff[2], lay["bar_rules"], 3))
        self.assertIn("line 3 p2.s1: 3 bar(s) (detected 4)", txt)
        self.assertIn("1: bar 6  width 38.4   completes the bar before it", txt)
        self.assertIn("3: bar 8  width 37   source prints 8", txt)
        raw = "\n".join(pt.bars_listing(lay["systems"][2], half_bar_like()[2], {}, 3))
        self.assertIn("clef stub: j 3 1", raw)


@needs_deps
class TestProofBars(unittest.TestCase):
    """proof.pdf shows the bar numbers, barline ticks and rehearsal letters."""

    def make_item(self, d, rules):
        item = Path(d, "2026-004-x")
        item.mkdir()
        doc = pymupdf.open()
        for _ in range(2):
            page = doc.new_page(width=600, height=840)
            page.insert_image(page.rect, pixmap=pymupdf.Pixmap(pymupdf.csRGB,
                                                               pymupdf.IRect(0, 0, 60, 84), 1))
        doc.save(item / "2026-004-proof.pdf")
        sy = half_bar_like()
        for e in sy:
            e["map"] = ["A"]
        pt.save_item(item, {"id": "2026-004", "slug": "x", "pages": "1-2", "systems": sy,
                            "bar_rules": {"pickup": [], "split": [], "fix": {}, **rules}})
        return item

    def texts(self, item):
        doc = pymupdf.open(pt.item_file(item, "proof.pdf"))
        return [p.get_text() for p in doc]

    def test_numbers_letters_and_split_label_drawn(self):
        with tempfile.TemporaryDirectory() as d:
            item = self.make_item(d, {"bar_edits": ["p2.s1:j1/4"], "split": ["p2.s1:0"],
                                      "marks_add": ["p2.s1:0"], "marks_drop": ["p2.s1:1"]})
            pt.annotate_proof(item)
            p1, p2 = self.texts(item)
            self.assertIn("magenta", p1)
            for n in ("1", "2", "3", "4", "5", "6"):
                self.assertIn(n, p1.split())
            self.assertIn("6 cont.", p2)
            self.assertEqual(p2.split().count("A"), 3)           # the letter, and the part label of 2 systems
            self.assertIn("9", p2.split())
            self.assertNotIn("B", p2.split())                    # the automatic letter was dropped

    def test_ticks_stand_at_the_barlines(self):
        with tempfile.TemporaryDirectory() as d:
            item = self.make_item(d, {})
            pt.annotate_proof(item)
            page = pymupdf.open(pt.item_file(item, "proof.pdf"))[0]
            f = page.rect.height / 4678.0
            sp = (495 - 400) / 4.0
            want = sorted(round((165 + 40.0 * i * sp) * f, 1) for i in (1, 2))   # line 1: bars at 40 sp
            ticks = sorted(round(dr["rect"].x0, 1) for dr in page.get_drawings()
                           if dr["color"] and abs(dr["color"][0] - pt.PROOF_BAR[0]) < 0.01
                           and dr["rect"].height > 5)
            for w in want:
                self.assertTrue(any(abs(w - t) < 0.7 for t in ticks), (w, ticks))

    def test_preview_draws_unsaved_rules_and_saved_file_is_untouched(self):
        with tempfile.TemporaryDirectory() as d:
            item = self.make_item(d, {})
            data = pt.load_item(item)
            data["bar_rules"] = {**data["bar_rules"], "bar_edits": ["p2.s1:j1/4"],
                                 "split": ["p2.s1:0"]}
            pt.annotate_proof(item, data)
            self.assertIn("6 cont.", self.texts(item)[1])
            self.assertNotIn("bar_edits", pt.load_item(item)["bar_rules"])   # not saved
            pt.annotate_proof(item)                                           # back to saved
            self.assertNotIn("6 cont.", self.texts(item)[1])

    def test_no_proof_is_no_error(self):
        with tempfile.TemporaryDirectory() as d:
            item = Path(d, "2026-004-x")
            item.mkdir()
            pt.annotate_proof(item)                       # nothing to draw on


def bach_like(anchors=((8,), (16,))):
    """Systems like the Bach chorale p8-9: pickup, repeat after bar 2 of
    line 2 with a split bar, printed line-start numbers 8 and 16 (plain
    count)."""
    sy = [{"id": "p1.s1", "bars": 7, "widths": [18.2, 10.9, 13.3, 12.7, 12.6, 13.3, 13.1],
           "restart": True},
          {"id": "p1.s2", "bars": 8, "widths": [23.1, 8.8, 5.7, 12.5, 13.1, 12.5, 10.6, 12.5],
           "repeats": [[1, "end"]]},
          {"id": "p1.s3", "bars": 6, "widths": [26.4, 13.8, 15.1, 15.5, 14.8, 13.2]},
          {"id": "p2.s1", "bars": 6, "widths": [25.4, 19.1, 12.9, 15.2, 12.9, 13.3]}]
    for e, a in zip(sy[1:], anchors):
        e["anchors"] = [[0, a[0]]]
    return sy


@needs_deps
class TestBarRules(unittest.TestCase):
    """Pickups, split bars at repeats, fixes, rehearsal letters."""

    def test_proposals_from_widths(self):
        r = pt.propose_bar_rules(bach_like())
        self.assertEqual(r["pickup"], ["p1.s1"])
        self.assertEqual(r["split"], ["p1.s2:2"])

    def test_no_proposal_for_even_bars(self):
        sy = [{"id": f"p1.s{k}", "bars": 4, "widths": [20.0, 14.0, 14.5, 13.8],
               "restart": k == 1} for k in (1, 2, 3)]
        sy[1]["repeats"] = [[1, "end"]]
        r = pt.propose_bar_rules(sy)
        self.assertEqual((r["pickup"], r["split"]), ([], []))

    def test_justified_lines_no_false_pickup(self):
        # Suite 1: line 1 has 4 bars, later lines 3 (wider bars); the short
        # first bar is only the denser line
        sy = [{"id": "p1.s1", "bars": 4, "widths": [29.1, 27.0, 35.4, 29.2], "restart": True},
              {"id": "p1.s2", "bars": 3, "widths": [45.3, 43.5, 37.0]},
              {"id": "p1.s3", "bars": 3, "widths": [48.6, 38.6, 38.6]},
              {"id": "p2.s1", "bars": 3, "widths": [54.1, 47.2, 47.0]}]
        self.assertEqual(pt.propose_bar_rules(sy)["pickup"], [])

    def test_naive_source_numbers_converted(self):
        sy = bach_like()
        starts, marks, scheme = pt.number_bars(sy, pt.propose_bar_rules(sy))
        self.assertEqual(scheme, "naive")
        self.assertEqual(starts, [0, 7, 14, 20])
        self.assertEqual(marks, {"p1.s2": [[3, "A"]]})   # first full bar after repeat

    def test_standard_source_numbers_not_corrected_twice(self):
        sy = bach_like(anchors=((7,), (14,)))
        starts, _, scheme = pt.number_bars(sy, pt.propose_bar_rules(sy))
        self.assertEqual(scheme, "standard")
        self.assertEqual(starts, [0, 7, 14, 20])

    def test_without_rules_plain_count(self):
        starts, marks, _ = pt.number_bars(bach_like(), None)
        self.assertEqual(starts, [1, 8, 16, 22])
        self.assertEqual(marks, {"p1.s2": [[2, "A"]]})

    def test_fix_moves_following_lines(self):
        sy = bach_like()
        rules = {"pickup": ["p1.s1"], "split": ["p1.s2:2"], "fix": {"p1.s3": 20}}
        self.assertEqual(pt.number_bars(sy, rules)[0], [0, 7, 20, 26])

    def test_letters_restart_per_movement(self):
        sy = bach_like() + [dict(e, id=e["id"].replace("p1", "p3").replace("p2", "p4"))
                            for e in bach_like()]
        _, marks, _ = pt.number_bars(sy, {"pickup": [], "split": [], "fix": {}})
        self.assertEqual(marks["p1.s2"][0][1], "A")
        self.assertEqual(marks["p3.s2"][0][1], "A")

    def test_renumber_sets_layout(self):
        lay = {"systems": bach_like(), "bar_rules": {"pickup": ["p1.s1"], "split": [], "fix": {}}}
        pt.renumber(lay)
        self.assertEqual([e["bar"] for e in lay["systems"]], [0, 7, 15, 21])
        self.assertIn("marks", lay["systems"][1])

    def test_confirm_bar_rules_asks_each(self):
        with tempfile.TemporaryDirectory() as d:
            item = Path(d)
            pt.save_item(item, {"id": "2026-001", "slug": "x", "systems": bach_like(),
                                "bar_rules": pt.propose_bar_rules(bach_like()),
                                "bar_rules_status": "proposed"})
            answers = iter(["", "n"])            # pickup yes, split no
            real = builtins.input
            builtins.input = lambda prompt="": next(answers)
            try:
                with open(os.devnull, "w") as dn, contextlib.redirect_stdout(dn):
                    pt.confirm_bar_rules(item)
            finally:
                builtins.input = real
            data = pt.load_item(item)
            self.assertEqual(data["bar_rules"]["pickup"], ["p1.s1"])
            self.assertEqual(data["bar_rules"]["split"], [])
            self.assertEqual(data["bar_rules_status"], "confirmed")
            self.assertEqual([e["bar"] for e in data["systems"]], [0, 7, 15, 21])

    def test_bars_screen(self):
        with tempfile.TemporaryDirectory() as d:
            share = Path(d, "share")
            (share / "inbox").mkdir(parents=True)
            year = time.localtime().tm_year
            item = share / "library" / f"{year}-004-x"
            item.mkdir(parents=True)
            sy = bach_like()
            for e in sy:
                e["map"] = ["?"]                 # needs choices: no rebuild
            pt.save_item(item, {"id": f"{year}-004", "slug": "x", "systems": sy,
                                "bar_rules": {"pickup": [], "split": [], "fix": {}}})
            env = dict(os.environ, PARTITOR_ALLOW_ROOT="1", PARTITOR_LIBRARY=str(share))
            r = subprocess.run([sys.executable, SRC, "bars", "4"], input="p 1\ns 1\nf 4=30\n\n",
                               capture_output=True, text=True, env=env, timeout=120)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            data = pt.load_item(item)
            self.assertEqual(data["bar_rules"], {"pickup": ["p1.s1"], "split": ["p1.s2:2"],
                                                 "fix": {"p2.s1": 30}})
            self.assertEqual([e["bar"] for e in data["systems"]], [0, 7, 14, 30])

    def half_bar_item(self, d):
        share = Path(d, "share")
        (share / "inbox").mkdir(parents=True)
        year = time.localtime().tm_year
        item = share / "library" / f"{year}-004-x"
        item.mkdir(parents=True)
        doc = pymupdf.open()
        for _ in range(2):
            page = doc.new_page(width=600, height=840)
            page.insert_image(page.rect, pixmap=pymupdf.Pixmap(pymupdf.csRGB,
                                                               pymupdf.IRect(0, 0, 60, 84), 1))
        doc.save(item / f"{year}-004-proof.pdf")
        sy = half_bar_like()
        for e in sy:
            e["map"] = ["A"]
        pt.save_item(item, {"id": f"{year}-004", "slug": "x", "pages": "1-2", "systems": sy,
                            "bar_rules": {"pickup": [], "split": [], "fix": {}}})
        env = dict(os.environ, PARTITOR_ALLOW_ROOT="1", PARTITOR_LIBRARY=str(share))
        return item, env

    def test_bars_menu_half_bar_over_a_clef_stub(self):
        with tempfile.TemporaryDirectory() as d:
            item, env = self.half_bar_item(d)
            script = ("b 3\ns 3 2\nj 3 1\ns 3 1\nm 3:1\nm 3:2\nv 3\nb 3\n?\n\n")
            r = subprocess.run([sys.executable, SRC, "bars", "4"], input=script,
                               capture_output=True, text=True, env=env, timeout=120)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            out = r.stdout
            self.assertIn("clef stub: j 3 1", out)                    # b 3 before the join
            self.assertIn("join it first (j 3 1)", out)               # s 3 2 refused
            self.assertIn("clef stub joined", out)
            self.assertIn("split on: p2.s1:0 completes the bar before it", out)
            self.assertIn("mark at bar 1 of line 3: added", out)
            self.assertIn("mark at bar 2 of line 3: removed", out)
            self.assertIn("letters now: A = bar 6 (line 3, bar 1)", out)
            self.assertIn("proof.pdf drawn with the edits (not saved yet): line 3 is on proof page 2",
                          out)
            self.assertIn("Example: the last bar of line 21", out)    # ? prints the example
            self.assertIn("NUMBERS", out)                             # the help text
            data = pt.load_item(item)
            br = data["bar_rules"]
            self.assertEqual((br["split"], br["bar_edits"]), (["p2.s1:0"], ["p2.s1:j1/4"]))
            self.assertEqual((br["marks_add"], br["marks_drop"]), (["p2.s1:0"], ["p2.s1:1"]))
            self.assertEqual([e["bar"] for e in data["systems"]], [1, 4, 6, 9])
            self.assertEqual(data["bar_rules_status"], "confirmed")
            doc = pymupdf.open(pt.item_file(item, "proof.pdf"))
            self.assertIn("6 cont.", doc[1].get_text())               # saved: proof shows it

    def test_bars_menu_bad_commands(self):
        with tempfile.TemporaryDirectory() as d:
            item, env = self.half_bar_item(d)
            r = subprocess.run([sys.executable, SRC, "bars", "4"],
                               input="s 1 1\ns 3 9\nm 9:1\nm 3:9\nm x\ns\nz\n\n",
                               capture_output=True, text=True, env=env, timeout=120)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("line 1 starts a movement: no bar before it", r.stdout)
            self.assertIn("line 3 has 4 bar(s): bar 1-4", r.stdout)
            self.assertIn("not understood: m 9:1", r.stdout)
            self.assertIn("no bar 9 of line 3", r.stdout)
            self.assertIn("not understood: m x", r.stdout)
            self.assertIn("unknown: z   (? = help)", r.stdout)
            self.assertEqual(pt.load_item(item)["bar_rules"].get("split"), [])

    def test_mismatch_text_names_the_stub(self):
        with tempfile.TemporaryDirectory() as d:
            item, env = self.half_bar_item(d)
            r = subprocess.run([sys.executable, SRC, "bars", "4"], input="\n",
                               capture_output=True, text=True, env=env, timeout=120)
            self.assertIn("its first bar is only 5.7 sp wide", r.stdout)
            self.assertIn("j 3 1 joins it", r.stdout)
            self.assertIn("s N I joins the two halves of a split bar", r.stdout)

    def test_proof_command_draws_again(self):
        with tempfile.TemporaryDirectory() as d:
            item, env = self.half_bar_item(d)
            data = pt.load_item(item)
            data["bar_rules"].update(bar_edits=["p2.s1:j1/4"], split=["p2.s1:0"])
            pt.save_item(item, data)
            r = subprocess.run([sys.executable, SRC, "proof", "4"], capture_output=True,
                               text=True, env=env, timeout=120)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("proof.pdf drawn again", r.stdout)
            self.assertIn("6 cont.", pymupdf.open(pt.item_file(item, "proof.pdf"))[1].get_text())
            pt.item_file(item, "proof.pdf").unlink()
            r = subprocess.run([sys.executable, SRC, "proof", "4"], capture_output=True,
                               text=True, env=env, timeout=120)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("no proof.pdf", r.stdout + r.stderr)
