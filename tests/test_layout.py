# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""Tests for re-flow, rests, titles and group layout.

Needs the venv packages (numpy, opencv, pymupdf, PyYAML); without them every test
is skipped. Run with the venv interpreter:

    venv/bin/python3 -m unittest -v tests/test_layout.py

Shared helpers: tests/support.py.
"""
import builtins
import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import test_analysis  # noqa: E402  (TestSystemWindow.make_pdf; the module, not the class: no second run)
from support import (  # noqa: E402,F401
    SP,
    SRC,
    flow_line,
    make_score_pdf,
    mock_attr,
    needs_deps,
    np,
    pt,
    pymupdf,
    rasterize,
    yaml,
    setUpModule,
    tearDownModule,
)


@needs_deps
class TestRepeatsAndExtras(unittest.TestCase):
    """Repeat signs, composer, letters, movement spacing, large copies."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.pdf = os.path.join(cls.tmp.name, "rep.pdf")

        def extra(page, tops):
            bx = 110 + 170                       # the first barline: make it ':||'
            for t in tops:
                page.draw_line((bx + 2.5, t), (bx + 2.5, t + 4 * SP), width=2.2)
                for yy in (t + 1.5 * SP, t + 2.5 * SP):
                    page.draw_circle((bx - 3.5, yy), 1.0, fill=(0, 0, 0))
            for a, b in zip(tops, tops[1:]):     # through the system, as engraved
                if b - a < 20 * SP:
                    page.draw_line((bx, a + 4 * SP), (bx, b), width=0.8)
                    page.draw_line((bx + 2.5, a + 4 * SP), (bx + 2.5, b), width=2.2)
            w = pymupdf.get_text_length("J. Tester", fontsize=10)
            page.insert_text((560 - w, tops[0] - 30), "J. Tester", fontsize=10)
        make_score_pdf(cls.pdf, extra=extra, lyrics=False)
        cls.res = pt.analyse_page(pymupdf.open(cls.pdf)[0], 0, 400, 0)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_end_repeat_found_on_every_system(self):
        for g in self.res.barlines:
            self.assertIn((0, "end"), self.res.repeats[g])
        self.assertEqual(self.res.gate, [])

    def test_composer_from_page(self):
        self.assertEqual(self.res.composer, "J. Tester")

    def test_plain_barlines_and_mensurstriche_are_not_repeats(self):
        res = pt.analyse_page(pymupdf.open(test_analysis.TestSystemWindow.make_pdf(self.tmp.name))[0], 0, 400, 0)
        self.assertTrue(all(not v for v in res.repeats.values()), res.repeats)

    def strip(self, **kw):
        img = np.zeros((120, 600), bool)
        for k in range(5):
            img[40 + 10 * k, :] = True
        return pt.Strip(img, 0, 40, 80, 10.0, np.zeros_like(img), **kw)

    def test_rehearsal_box_above_staff_and_number_beside_it(self):
        s = self.strip(bar_no=12, marks=[(0, "A"), (300, "B")])
        boxes = pt.reh_boxes(s)
        self.assertEqual([b[4] for b in boxes], ["A", "B"])
        self.assertTrue(all(b[3] <= 40 - 10 for b in boxes))     # above the staff
        self.assertGreater(pt.bar_x(s), boxes[0][2])              # number right of A

    def test_movement_gets_double_leading(self):
        opts = {**pt.LAYOUT_DEFAULTS}
        p = pt.pitches([self.strip(), self.strip(), self.strip(movement=True)], opts)
        self.assertAlmostEqual(p[1] - p[0], opts["gap"] * 10)

    def test_large_copies(self):
        with tempfile.TemporaryDirectory() as d:
            for paper, size, marks in (("letter", (792.0, 1224.0), 2), ("a4", (841.89, 1190.55), 0)):
                src = Path(d, f"{paper}.pdf")
                doc = pymupdf.open()
                doc.new_page(width=pt.PAPER[paper][0], height=pt.PAPER[paper][1])
                doc.save(src)
                out = pt.large_copy(src, paper)
                big = pymupdf.open(out)[0]
                with self.subTest(paper=paper):
                    self.assertAlmostEqual(big.rect.width, size[0], places=1)
                    self.assertAlmostEqual(big.rect.height, size[1], places=1)
                    lines = [dr for dr in big.get_drawings()]
                    self.assertEqual(len(lines), marks)
                    if marks:
                        y = 792.0 * 792.0 / 612.0
                        self.assertAlmostEqual(lines[0]["rect"].y0, y, delta=0.5)


@needs_deps
class TestReflow(unittest.TestCase):
    """Re-flow (DESIGN.md §4.2 item 2) and the small-print offer."""

    def lines(self):
        return [flow_line([(70, 44), (110, 60)], [100, 140, 198], key=True, first=True),
                flow_line([(75, 60), (120, 52)], [105, 150, 198], key=True),
                flow_line([(72, 52), (125, 44)], [110, 160, 198], key=True)]

    def test_prefix_ends_after_the_key_signature(self):
        pre = pt.find_prefixes(self.lines())
        for i, p in enumerate(pre):
            with self.subTest(line=i):
                self.assertIsNotNone(p)
                self.assertEqual(p[1], i)                 # own prefix
                self.assertTrue(54 <= p[0] <= 60, p)      # after the last key stroke (x 52-53)

    def test_key_change_line_is_never_cut(self):
        ls = self.lines() + [flow_line([(70, 60)], [100, 198])]   # no key signature
        self.assertIsNone(pt.find_prefixes(ls)[3])

    def test_one_line_movement_is_not_cut(self):
        self.assertEqual(pt.find_prefixes([flow_line([(70, 44)], [100, 198], first=True)]),
                         [None])

    def test_break_lines_balanced(self):
        self.assertEqual(pt._break_lines([30.0] * 4, 10.0, 75.0), [0, 2])
        self.assertEqual(pt._break_lines([90.0, 10.0], 10.0, 75.0), [0, 1])  # too wide: alone

    def test_reflow_cuts_at_barlines_copies_clef_and_drops_printed_numbers(self):
        ls = self.lines()
        num = np.zeros_like(ls[1].img)
        num[30:37, 120:128] = True                   # a printed "10" above the staff
        ls[1].img |= num
        ls[1].num_mask = num
        pre = pt.find_prefixes(ls)
        out = pt.reflow(ls, 140.0, pre)
        self.assertGreater(len(out), len(ls))
        self.assertTrue(all(o.img.shape[1] <= 140 for o in out))
        for k, o in enumerate(out):
            with self.subTest(line=k):
                above = np.flatnonzero(o.img[28:37].any(axis=0))
                # above the staff: only the clef at the line start
                self.assertTrue(above.size and above.max() < 25, above)
                self.assertTrue(o.img[50:60, 36:56].any())     # key signature copied
        # every bar kept once: note heads in = note heads out
        heads = lambda st: int((st.img[:, 30:] & ~np.roll(st.img, 1, axis=1)[:, 30:]).sum())
        self.assertGreater(sum(heads(o) for o in out), 0)
        self.assertEqual(out[0].bar_no, None)              # movement start: no number
        self.assertEqual([o.bar_no for o in out[1:3]], [2, 3])

    def test_borrowed_prefix_starts_a_line(self):
        ls = self.lines()
        pre = pt.find_prefixes(ls)
        pre[1] = (0, 0)                               # line 1 borrows line 0's clef
        out = pt.reflow(ls, 140.0, pre)
        for o in out:                                 # no clef in mid-line
            above = np.flatnonzero(o.img[28:37].any(axis=0))
            self.assertLess(above.max(), 25)

    def test_caps(self):
        ls = self.lines()
        pre = pt.find_prefixes(ls)
        cap = pt.reflow_caps(ls, pre)
        self.assertLess(cap, 200)
        self.assertGreater(cap, 50)
        pre[2] = None                                 # a line that stays whole
        self.assertEqual(pt.reflow_caps(ls, pre), 200)

    def test_band_ignores_skewed_staff_lines_and_system_barline(self):
        s = flow_line([], [198])
        s.img[40:81, 0:2] = True                      # system barline at the start
        for k in range(5):                            # a slanted staff line, 1 px per 30 px
            for x in range(0, 200, 30):
                s.img[41 + 10 * k, x:x + 30] = True
        b = pt._band(s)
        self.assertFalse(b[:, 0:3].any())
        self.assertFalse(b[:, 30:190].any())          # nothing left between clef and end

    def built(self, staff=5.9, width=5.9, reflow=None):
        lay = {"gap": 10.0}
        if reflow:
            lay["reflow"] = reflow
        return {"layout": lay, "built": {"parts": [
            {"part": "A", "pages": 2, "content_pages": 2, "staff_mm": staff,
             "staff_max_mm": staff, "width_mm": width, "gap": 10.0}]}}

    def test_small_print_and_expand_step(self):
        self.assertEqual([p["part"] for p in pt.small_parts(self.built())], ["A"])
        self.assertEqual(pt.small_parts(self.built(staff=7.0, width=7.0)), [])
        self.assertEqual(pt.small_parts(self.built(reflow="on")), [])
        self.assertEqual(pt.step_size(self.built(), True)[0], ["reflow=on"])
        self.assertEqual(pt.step_size(self.built(reflow="on"), True)[0], ["gap=11.0"])
        self.assertEqual(pt.step_size(self.built(staff=8.0, width=8.0), True)[0],
                         ["gap=11.0"])                # page width allows the maximum

    def offer(self, answers):
        with tempfile.TemporaryDirectory() as d:
            item = Path(d)
            pt.save_item(item, {"id": "2026-001", "parts": ["A"], **self.built()})
            calls = []

            def fake_build(it):
                data = pt.load_item(it)
                on = (data.get("layout") or {}).get("reflow") == "on"
                calls.append(on)
                data["built"]["parts"][0].update(
                    {"staff_mm": 8.0 if on else 5.9, "content_pages": 4 if on else 2})
                pt.save_item(it, data)
                return 0
            ans = iter(answers)
            with mock_attr(pt, "run_build", fake_build), \
                 mock_attr(builtins, "input", lambda *_: next(ans)), \
                 contextlib.redirect_stdout(io.StringIO()):
                pt.offer_reflow(item)
            return calls, (pt.load_item(item).get("layout") or {}).get("reflow")

    def test_offer_keep_and_undo(self):
        self.assertEqual(self.offer(["", ""]), ([True], "on"))        # Enter, Enter: keep
        self.assertEqual(self.offer(["", "n"]), ([True, False], "off"))  # undo: built again
        self.assertEqual(self.offer(["n"]), ([], None))               # not tried


@needs_deps
class TestRestsAndTitles(unittest.TestCase):
    """Multi-bar rests for systems without a part's staff; no false title."""

    def line(self, k=0):
        notes = ([(70, 44), (110, 60)], [(75, 60), (120, 52)], [(72, 52), (125, 44)])[k]
        return flow_line(notes, [100, 140, 198], key=True)

    def test_runs_merge_and_movement_splits(self):
        a, b = self.line(0), self.line(1)
        items = [a, pt.RestRun(3, 5), pt.RestRun(2, 8), b, pt.RestRun(1, 20),
                 pt.RestRun(4, 1, movement=True)]
        out = pt.fill_rests(items, {**pt.LAYOUT_DEFAULTS})
        self.assertEqual(len(out), 5)
        self.assertIs(out[0], a)
        self.assertIs(out[2], b)
        r1, r2, r3 = out[1], out[3], out[4]
        self.assertEqual((r1.bar_no, r1.rest_label[1]), (5, "5"))     # 3 + 2 bars from 5
        self.assertEqual((r2.bar_no, r2.rest_label), (20, None))      # one bar: whole rest
        self.assertEqual((r3.bar_no, r3.rest_label[1], r3.movement), (None, "4", True))
        # clef and key copied, staff lines across, closing barline
        self.assertTrue(r1.img[r1.staff_top - 12:r1.staff_top - 4, 6:25].any())   # clef
        self.assertTrue(r1.img[r1.staff_top + 4:r1.staff_top + 22, 36:56].any())  # key
        for kk in range(5):
            self.assertTrue(r1.img[r1.staff_top + 10 * kk, 60:r1.img.shape[1] - 10].all())
        self.assertTrue(r1.img[r1.staff_top:r1.staff_bottom, -2].all())
        self.assertTrue(pt.rest_box(r1)[3] < r1.staff_top)           # count above the staff

    def test_movement_rest_keeps_its_title(self):
        title = np.zeros((20, 60), bool)
        title[2:18, 5:55] = True                        # "Allemande"
        out = pt.fill_rests([self.line(0), self.line(1),
                             pt.RestRun(22, 1, movement=True, header=(title, 0, 15))], {})
        r = out[2]
        self.assertTrue(r.movement)
        self.assertEqual(int(r.hdr.sum()), int(title.sum()))
        rows = np.flatnonzero(r.hdr.any(axis=1))
        self.assertLessEqual(rows.max(), r.staff_top - 15)   # above the staff, gap kept

    def test_run_at_start_takes_clef_from_next_line(self):
        a, b = self.line(0), self.line(2)
        out = pt.fill_rests([pt.RestRun(6, 1), a, b], {**pt.LAYOUT_DEFAULTS})
        self.assertEqual(len(out), 3)
        self.assertTrue(out[0].img[out[0].staff_top - 12:out[0].staff_top - 4, 6:25].any())
        # one line only: clef and key cannot be told; staff and rest only
        one = pt.fill_rests([self.line(0), pt.RestRun(3, 4)], {})
        self.assertFalse(one[1].img[:one[1].staff_top - 2].any())
        self.assertEqual(one[1].rest_label[1], "3")
        self.assertEqual(pt.fill_rests([pt.RestRun(2, 1)], {}), [])     # never a staff: none

    def test_build_writes_rest_line_for_missing_staff(self):
        with tempfile.TemporaryDirectory() as d:
            pdf = os.path.join(d, "s.pdf")
            make_score_pdf(pdf)
            env = dict(os.environ, PARTITOR_ALLOW_ROOT="1")
            run = lambda *a: subprocess.run([sys.executable, SRC, *a], capture_output=True,
                                            text=True, env=env)
            r = run("detect", pdf, "--dpi", "300")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            lp = Path(d, "s.partitor", "layout.yaml")
            lay = yaml.safe_load(lp.read_text())
            lay["systems"][1]["map"] = ["Alto", "Tenor", "-"]     # Bass rests in system 2
            nb = lay["systems"][1]["bars"]
            lp.write_text(yaml.safe_dump(lay, sort_keys=False))
            r = run("build", pdf, "--large", "off")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("Bass:  2 lines", r.stdout)
            text = pymupdf.open(Path(d, "s.partitor", "parts", "03-Bass.pdf"))[0].get_text()
            want = pt.rest_text(str(nb))[0]          # Bravura time-signature digits
            self.assertIn(want, text.split())

    def _rests_run(self, d, quiet, build_args=(), extra=None, groups=None):
        pdf = os.path.join(d, "s.pdf")
        make_score_pdf(pdf, quiet=quiet, extra=extra)
        env = dict(os.environ, PARTITOR_ALLOW_ROOT="1")
        run = lambda *a: subprocess.run([sys.executable, SRC, *a], capture_output=True,
                                        text=True, env=env)
        r = run("detect", pdf, "--dpi", "300")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        lp = Path(d, "s.partitor", "layout.yaml")
        lay = yaml.safe_load(lp.read_text())
        if groups:
            lay["groups"] = groups
            lp.write_text(yaml.safe_dump(lay, sort_keys=False))
        r = run("build", pdf, "--large", "off", *build_args)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        digits = pt.rest_text(str(lay["systems"][1]["bars"]))[0]
        text = lambda n: " ".join(pg.get_text() for pg in
                                  pymupdf.open(Path(d, "s.partitor", "parts", n)))
        return r, digits, text

    def test_empty_staff_becomes_rest_and_group_follows(self):
        q = {(1, 1), (1, 2)}                       # Tenor and Bass empty in system 2
        with tempfile.TemporaryDirectory() as d:
            r, digits, text = self._rests_run(d, q, groups={"Low": ["Tenor", "Bass"]})
            self.assertIn(digits, text("03-Bass.pdf").split())
            self.assertIn(digits, text("02-Tenor.pdf").split())
            self.assertIn(digits, text("04-Low.pdf").split())    # all its staves rest
            self.assertNotIn(digits, text("01-Alto.pdf").split())
        with tempfile.TemporaryDirectory() as d:     # keep: as engraved
            r, digits, text = self._rests_run(d, q, ("--rests", "keep"),
                                              groups={"Low": ["Tenor", "Bass"]})
            for n in ("03-Bass.pdf", "02-Tenor.pdf", "04-Low.pdf"):
                self.assertNotIn(digits, text(n).split())

    def test_group_stays_whole_when_one_staff_plays(self):
        with tempfile.TemporaryDirectory() as d:
            r, digits, text = self._rests_run(d, {(1, 2)}, groups={"Low": ["Tenor", "Bass"]})
            self.assertIn(digits, text("03-Bass.pdf").split())      # the part compresses
            self.assertNotIn(digits, text("02-Tenor.pdf").split())
            self.assertNotIn(digits, text("04-Low.pdf").split())    # the group does not

    def test_stem_without_head_keeps_staff_as_engraved(self):
        def stem(page, tops):
            top = tops[3 + 2]                       # Bass, system 2
            page.draw_line((350, top + 2 * SP), (350, top - 2 * SP), width=0.7)
        with tempfile.TemporaryDirectory() as d:
            r, digits, text = self._rests_run(d, {(1, 2)}, extra=stem)
            self.assertIn("ink that is not a rest", r.stdout + r.stderr)
            self.assertNotIn(digits, text("03-Bass.pdf").split())

    def test_text_line_shape(self):
        self.assertTrue(pt.looks_like_text([30, 25, 40, 28, 60], 40))
        self.assertFalse(pt.looks_like_text([1465], 21))            # page edge
        self.assertFalse(pt.looks_like_text([30, 900, 25], 40))     # a rule through words
        self.assertFalse(pt.looks_like_text([30, 25], 40))

    def test_page_edge_is_no_title_and_no_movement_start(self):
        with tempfile.TemporaryDirectory() as d:
            src, scan = os.path.join(d, "v.pdf"), os.path.join(d, "r.pdf")

            def edge(page, tops):
                page.draw_rect(pymupdf.Rect(150, 40, 470, 48), fill=(0, 0, 0))
            make_score_pdf(src, title=None, extra=edge)
            rasterize(src, scan, dpi=200)
            res = pt.analyse_page(pymupdf.open(scan)[0], 1, 400, 0)
            self.assertEqual(res.title, "")
            self.assertEqual(res.restart, set())


@needs_deps
class TestEngravedLook(unittest.TestCase):
    """One line width, first-line indent, group labels, dust, gap barline."""

    def line(self, notes, bars, width=200, lyric=None, movement=False):
        s = flow_line(notes, bars, width=width, key=True)
        s.movement = movement
        if lyric:                                     # a word: letters 2 px apart
            for x in range(lyric, lyric + 30, 6):
                s.img[100:108, x:x + 4] = True
        return s

    def test_justify_adds_space_in_gaps_only(self):
        s = self.line([(70, 44), (110, 60)], [100, 150], width=160, lyric=112)
        out = pt.justify(s, 190)
        self.assertEqual(pt.staff_end(out) - out.staff_x0, 190)
        nonstaff = lambda st: int(st.img[85:].sum() + st.img[:38].sum())
        self.assertEqual(nonstaff(out), nonstaff(s))           # glyphs not stretched
        span = lambda st: np.ptp(np.flatnonzero(st.img[100:108].any(axis=0)))
        self.assertEqual(span(out), span(s))                      # word intact
        self.assertGreater(out.bars_x[0], s.bars_x[0])
        self.assertEqual(pt.justify(s, 150), s)                  # long enough already

    def test_finish_lines_indent_name_and_ragged_last(self):
        a = self.line([(70, 44), (110, 60), (300, 52)], [100, 250, 500], width=510)
        b = self.line([(75, 60), (120, 52), (400, 44)], [105, 300, 598], width=600)
        c = self.line([(72, 52)], [100], width=102)              # short last line
        out = pt.finish_lines([a, b, c], "Alto", False)
        self.assertEqual(out[0].name_label, "Alto")
        self.assertGreater(out[0].indent, 0)
        right = [pt.staff_end(o) - pt.anchor(o) for o in out[:2]]
        self.assertEqual(right[0], right[1])                     # right edges align
        self.assertIs(out[2], c)                                 # movement end: stays short
        labels = pt.line_labels(out[0])
        self.assertEqual(labels[0][0], "Alto")
        self.assertTrue(labels[0][4])                            # small caps

    def test_rest_line_takes_the_full_width(self):
        a = self.line([(70, 44), (110, 60)], [100, 198])
        b = self.line([(75, 60), (120, 52)], [105, 198])
        items = pt.fill_rests([a, pt.RestRun(14, 9), b], {})
        out = pt.finish_lines(items, "T", False)
        r = out[1]
        self.assertEqual(pt.staff_end(r) - r.staff_x0, pt.staff_end(out[2]) - out[2].staff_x0)
        hbar = r.img[r.staff_top + 20 - 4:r.staff_top + 20 + 5].all(axis=0).sum()
        self.assertGreaterEqual(hbar, r.img.shape[1] - r.rest_src[1] - 45)  # across the measure
        if pt._font("music")[1]:
            self.assertEqual(pt.rest_text("14")[0], "\ue081\ue084")

    def test_group_labels(self):
        self.assertEqual(pt.short_name("Basso Trombone grosso"), "Bas. Tro. gro.")
        self.assertEqual(pt.short_name("Tenore II"), "Ten. II")

        def g(parts):
            s = self.line([(70, 44)], [198])
            s.bracket = True
            s.staff_labels = [(p, 40, 80) for p in parts]
            return s
        # one label column on every line, so the right edges align
        same = pt.finish_lines([g(["Alto", "Basso"]), g(["Alto", "Basso"])], "G", True)
        self.assertEqual([len(s.staff_labels) for s in same], [2, 2])
        self.assertEqual(same[0].indent, same[1].indent)
        self.assertEqual(same[0].img.shape[1], same[1].img.shape[1])
        vary = pt.finish_lines([g(["Alto", "Basso"]), g(["Basso"])], "G", True)
        self.assertEqual([n for n, *_ in vary[1].staff_labels], ["Bas."])   # short names
        self.assertEqual(vary[0].indent, vary[1].indent)
        self.assertGreater(vary[1].indent, 0)

    def test_group_staves_close_up(self):
        with tempfile.TemporaryDirectory() as d:
            pdf = os.path.join(d, "s.pdf")
            make_score_pdf(pdf, lyrics=False)
            res = pt.analyse_page(pymupdf.open(pdf)[0], 0, 400, 0)
            grp = [st.idx for st in res.systems[0]]
            step = res.staves[grp[1]].top - res.staves[grp[0]].top
            g = pt.group_strip(res, grp, [("A", [grp[0]]), ("B", [grp[2]])],
                               pt.OWN_HEADER_BASE + res.staves[grp[0]].system)
            (_, t1, _), (_, t2, _) = g.staff_labels
            self.assertAlmostEqual(t2 - t1, step, delta=0.5 * res.sp)   # no gap for staff 2

    def test_page_turns_at_section_boundaries(self):
        def strip(mark=False):
            img = np.zeros((120, 600), bool)
            for k in range(5):
                img[40 + 10 * k, :] = True
            return pt.Strip(img, 0, 40, 80, 10.0, np.zeros_like(img),
                            marks=[(0, "A")] if mark else [])
        opts = {**pt.LAYOUT_DEFAULTS, "scale": 2.0, "gap": 6.0}
        per = len(pt.pack([strip() for _ in range(40)], 400, {**opts, "_no_band": True})[0])
        # music before the section, then a section of 2 pages (letter A)
        before, sect = 2 * per + 1, 2 * per
        lines = [strip() for _ in range(before)] + [strip(True)] + \
                [strip() for _ in range(sect - 1)]
        for title_page in (False, True):
            pages, bad = pt.plan_pages(lines, 400, opts, title_page)
            first = 2 if title_page else 1
            j = 0
            for c, pg in enumerate(pages[:-1]):
                j += len(pg)
                if (first + c) % 2 == 1:                 # a turn after a recto
                    with self.subTest(title_page=title_page, page=c):
                        self.assertTrue(j <= before or pt.good_turn(lines, j),
                                        f"turn inside the section before line {j}")
        pages, tp = pt.layout_pages(lines, 400, opts)
        sizes = [len(p) for p in pages]
        start = before                                   # the section starts a verso
        first = 2 if tp else 1
        acc, c = 0, 0
        while acc < start:
            acc += sizes[c]
            c += 1
        self.assertEqual(acc, start)
        self.assertEqual((first + c) % 2, 0)

    def test_header_dust_and_gap_barline(self):
        with tempfile.TemporaryDirectory() as d:
            pdf = os.path.join(d, "s.pdf")

            def extra(page, tops):
                page.draw_circle((480, tops[3] - 3 * SP), 0.5, fill=(0, 0, 0))  # dust
                # broken system barline under staff 1, attached to the staff
                page.draw_line((110.4, tops[0] + 4 * SP), (110.4, tops[0] + 7 * SP), width=0.8)
            make_score_pdf(pdf, extra=extra, connector="none", lyrics=False)
            res = pt.analyse_page(pymupdf.open(pdf)[0], 0, 400, 0)
            k = 400 / 72
            y, x = int((tops_y := res.staves[3].top) - 3 * res.sp), int(480 * k)
            self.assertFalse(((res.owner[y - 4:y + 5, x - 4:x + 5] >= pt.OWN_HEADER_BASE)).any())
            st = res.staves[0]
            col = res.owner[int(st.bottom + 0.5 * res.sp):int(st.bottom + 2.5 * res.sp),
                            int(110.4 * k) - 3:int(110.4 * k) + 4]
            self.assertFalse(((col >= 0) & (col < len(res.staves))).any())
            del tops_y


def group_line(notes, bars, width=200, key=True, first=False, parts=("A", "B", "C"),
               tops=(40, 170, 300), nums=None, why=""):
    """Synthetic group line, sp 10: one staff per part at rows tops (clef,
    key signature, note heads (x, dy below the staff top) per staff, barlines
    through every staff), bracket, labels."""
    img = np.zeros((tops[-1] + 90, width), bool)
    for t in tops[:len(parts)]:
        for k in range(5):
            img[t + 10 * k, :] = True
        for x0 in (6, 13, 20):
            img[t - 12:t + 54, x0:x0 + 3] = True
        if key:
            for x0 in (36, 40, 48, 52):
                img[t + 4:t + 22, x0:x0 + 2] = True
        for x, dy in notes:
            img[t + dy:t + dy + 7, x:x + 8] = True
        for b in bars:
            img[t:t + 41, b:b + 2] = True
    ts = list(tops[:len(parts)])
    return pt.Strip(img, 0, ts[0], ts[-1] + 40, 10.0, np.zeros_like(img), bars_x=list(bars),
                    bar_nums=list(nums or range(1, len(bars) + 1)), ends_at_bar=not why,
                    movement=first, bracket=True, bars_why=why,
                    staff_labels=[(n, t, t + 40) for n, t in zip(parts, ts)])


@needs_deps
class TestGroupReflow(unittest.TestCase):
    """Re-flow of group scores (DESIGN.md §4.3 item 11, 0.3.0-dev.34)."""

    def lines(self):
        return [group_line([(70, 4), (110, 20)], [100, 140, 198], first=True),
                group_line([(75, 20), (120, 12)], [105, 150, 198]),
                group_line([(72, 12), (125, 4)], [110, 160, 198])]

    def test_prefix_is_found_for_group_lines(self):
        pre = pt.find_prefixes(self.lines())
        for i, p in enumerate(pre):
            with self.subTest(line=i):
                self.assertIsNotNone(p)
                self.assertTrue(54 <= p[0] <= 60, p)

    def test_cut_keeps_bracket_labels_and_copies_clef_key_to_every_staff(self):
        ls = self.lines()
        out = pt.reflow(ls, 140.0, pt.find_prefixes(ls))
        self.assertGreater(len(out), len(ls))
        for k, o in enumerate(out):
            with self.subTest(line=k):
                self.assertLessEqual(o.img.shape[1], 140)
                self.assertTrue(o.bracket)
                self.assertEqual([n for n, *_ in o.staff_labels], ["A", "B", "C"])
                self.assertEqual([t - o.staff_top for _, t, _ in o.staff_labels], [0, 130, 260])
                for _, t, _ in o.staff_labels:             # clef and key on each staff
                    self.assertTrue(o.img[t - 12:t + 54, 6:25].any())
                    self.assertTrue(o.img[t + 4:t + 22, 36:56].any())
        # every bar once: note heads in = out (3 staves x 2 heads x 3 lines)
        heads = lambda st: int((st.img[:, 60:] & ~np.roll(st.img, 1, axis=1)[:, 60:]).sum())
        self.assertGreater(sum(heads(o) for o in out), 0)
        self.assertEqual([o.bar_no for o in out[1:3]], [2, 3])      # numbers follow the bars

    def test_label_column_is_equal_on_every_re_flowed_line(self):
        ls = self.lines()
        out = pt.finish_lines(pt.reflow(ls, 140.0, pt.find_prefixes(ls)), "G", True)
        self.assertEqual(len({o.indent for o in out}), 1)
        self.assertGreater(out[0].indent, 0)
        self.assertEqual(len({pt.anchor(o) for o in out}), 1)       # staves start at one column

    def test_line_without_common_barline_at_its_end_stays_whole(self):
        ls = self.lines()
        ls[1] = group_line([(75, 20)], [105, 150], why="barline 3 is not on every staff")
        ls[1].ends_at_bar = False
        pre = pt.find_prefixes(ls)
        out = pt.reflow(ls, 140.0, pre)
        self.assertTrue(any(o is ls[1] for o in out))               # the same strip, whole
        self.assertIn("barline 3 is not on every staff", pt.reflow_report(ls, pre))
        self.assertEqual(pt.whole_reason(ls[0], pre[0]), "")

    def test_other_staves_never_share_a_line_or_a_prefix(self):
        ls = self.lines()
        ls[1] = group_line([(75, 20), (120, 12)], [105, 150, 198], parts=("A", "C"),
                           tops=(40, 170))
        pre = pt.find_prefixes(ls)
        out = pt.reflow(ls, 400.0, pre)                             # wide: only the sets decide
        sets = [tuple(n for n, *_ in o.staff_labels) for o in out]
        self.assertEqual(sets, [("A", "B", "C"), ("A", "C"), ("A", "B", "C")])
        stack = group_line([(75, 20)], [105, 198], tops=(40, 176, 300))   # staff 2 moved 6 px
        self.assertFalse(pt._same_stack(ls[0], stack))

    def test_rest_line_is_whole_and_keeps_its_bracket(self):
        ls = self.lines()
        items = pt.fill_rests([ls[0], pt.RestRun(8, 4), ls[1]], {})
        items[1].bracket = True
        pre = pt.find_prefixes(items)
        out = pt.reflow(items, 140.0, pre)
        rest = [o for o in out if o.rest_src is not None]
        self.assertEqual(len(rest), 1)
        self.assertTrue(rest[0].bracket)
        self.assertEqual(pt.whole_reason(items[1], pre[1]), "multi-bar rest")

    def test_group_bars_only_where_every_staff_has_the_stroke(self):
        with tempfile.TemporaryDirectory() as d:
            pdf = os.path.join(d, "s.pdf")
            make_score_pdf(pdf, lyrics=False)
            res = pt.analyse_page(pymupdf.open(pdf)[0], 0, 400, 0)
            grp = [st.idx for st in res.systems[0]]
            g0 = res.staves[grp[0]].system
            bx, nn, why = pt.group_bars(res, grp, g0, [1, 2, 3])
            self.assertEqual((len(bx), nn, why), (3, [1, 2, 3], ""))
            st = res.staves[grp[2]]                     # erase barline 2 on the last staff
            x = res.barlines[g0][1]
            w = int(res.sp)
            res.owner[int(st.top - 5):int(st.bottom + 6), x - w:x + w] = pt.OWN_NONE
            bx, nn, why = pt.group_bars(res, grp, g0, [1, 2, 3])
            self.assertEqual(len(bx), 2)
            self.assertEqual(nn, [1, 2])                # merged bars 2+3 keep the number 2
            self.assertEqual(pt.group_bars(res, grp, g0, [1, 2])[2],
                             "bar numbers do not match the barlines")

    def test_pages_and_page_turns_treat_group_lines_as_ordinary_lines(self):
        opts = {**pt.LAYOUT_DEFAULTS, "scale": 1.0}
        ls = self.lines() * 6
        for s_ in ls[1:]:
            s_.movement = False
        cut = pt.reflow(ls, 140.0, pt.find_prefixes(ls))
        p0, p1 = pt.pitches(ls, opts), pt.pitches(cut, opts)
        self.assertAlmostEqual(p1[0], p0[0])            # same system gap rule (staff_labels kept)
        pages, _ = pt.layout_pages(cut, 400, {**opts, "scale": 0.3})[:2]
        self.assertGreaterEqual(len(pages), 1)
        self.assertEqual(sum(len(pg) for pg in pages), len(cut))   # no line lost
        self.assertEqual([pt.turns(n) for n in (1, 2, 3, 5)], [0, 0, 1, 2])

    def test_group_page_budget_limits_the_staff(self):
        ls = self.lines() * 8
        for s_ in ls[1:]:
            s_.movement = False
        opts = {**pt.LAYOUT_DEFAULTS, "max_staff_mm": 12.0, "min_staff_mm": 5.0}
        free = pt.choose_reflow(ls, 400, opts)
        capped = pt.choose_reflow(ls, 400, {**opts, "page_count": max(1, free[2] - 1)},
                                  None, 0.5)
        self.assertLessEqual(capped[2], max(1, free[2] - 1))
        self.assertLess(capped[0], free[0])                          # a smaller staff

    def test_report_names_the_widest_whole_line(self):
        ls = self.lines() + [group_line([(75, 20)], [105], width=300, why="no barline in the system")]
        ls[-1].ends_at_bar = False
        txt = pt.reflow_report(ls, pt.find_prefixes(ls))
        self.assertIn("3 of 4 lines can be cut", txt)
        self.assertIn("widest whole line 30 sp (line 4: no barline in the system)", txt)

    def test_small_parts_sees_groups_and_per_part_reflow(self):
        built = {"layout": {"parts": {"G": {"reflow": "on"}}}, "built": {"parts": [
            {"part": "A", "pages": 2, "content_pages": 2, "staff_mm": 3.7, "staff_max_mm": 3.9,
             "width_mm": 3.9, "gap": 10.0},
            {"part": "G", "pages": 5, "content_pages": 4, "staff_mm": 3.7, "staff_max_mm": 3.9,
             "width_mm": 3.9, "gap": 10.0, "group": True},
            {"part": "H", "pages": 5, "content_pages": 4, "staff_mm": 3.7, "staff_max_mm": 3.9,
             "width_mm": 3.9, "gap": 10.0, "group": True}]}}
        self.assertEqual([p["part"] for p in pt.small_parts(built)], ["A", "H"])  # G is on
        self.assertEqual([p["part"] for p in pt.small_parts(built, ["H"])], ["H"])

    def test_offer_after_a_group_build_sets_the_part_key_and_builds_only_it(self):
        with tempfile.TemporaryDirectory() as d:
            item = Path(d)
            rec = lambda n, g: {"part": n, "pages": 12, "content_pages": 11, "staff_mm": 3.7,
                                "staff_max_mm": 3.9, "width_mm": 3.9, "gap": 10.0,
                                **({"group": True} if g else {})}
            pt.save_item(item, {"id": "2026-001", "parts": ["A", "B", "G"], "groups": {"G": ["A", "B"]},
                                "layout": {"gap": 10.0}, "built": {"parts": [rec("A", 0), rec("G", 1)]}})
            calls = []

            def fake_build(it, only=None, jobs=None):
                data = pt.load_item(it)
                calls.append((only, (data["layout"].get("parts") or {}).get("G", {}).get("reflow"),
                              data["layout"].get("reflow")))
                data["built"]["parts"][1].update({"staff_mm": 4.5, "content_pages": 17})
                pt.save_item(it, data)
                return 0
            ans = iter(["", ""])
            with mock_attr(pt, "run_build", fake_build), \
                 mock_attr(builtins, "input", lambda *_: next(ans)), \
                 contextlib.redirect_stdout(io.StringIO()) as out:
                pt.offer_reflow(item, ["G"])
            self.assertEqual(calls, [(["G"], "on", None)])              # item key untouched
            self.assertIn("page budget is 1.5 x", out.getvalue())
            self.assertEqual(pt.load_item(item)["layout"]["parts"]["G"]["reflow"], "on")


@needs_deps
class TestGroupReflowReal(unittest.TestCase):
    """The real engine on a synthetic 3-staff score: a group is re-flowed at
    its barlines, workers give the same file as the serial build, and a group
    that cannot be cut is the same as before."""

    def run_build(self, d, systems, jobs, *args):
        pdf = os.path.join(d, "s.pdf")
        make_score_pdf(pdf, systems=systems, staves=3, lyrics=False)
        env = dict(os.environ, PARTITOR_ALLOW_ROOT="1", PARTITOR_JOBS=str(jobs))
        run = lambda *a: subprocess.run([sys.executable, SRC, *a], capture_output=True,
                                        text=True, env=env)
        r = run("detect", pdf, "--dpi", "300")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        lp = Path(d, "s.partitor", "layout.yaml")
        lay = yaml.safe_load(lp.read_text())
        lay["groups"] = {"G": ["Alto", "Tenor", "Bass"]}
        lp.write_text(yaml.safe_dump(lay, sort_keys=False))
        r = run("build", pdf, "--large", "off", *args)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r.stdout + r.stderr, Path(d, "s.partitor", "parts", "04-G.pdf")

    @staticmethod
    def sig(f):
        import hashlib
        return [hashlib.md5(pg.get_pixmap(dpi=50).samples).hexdigest() for pg in pymupdf.open(str(f))]

    def test_group_is_cut_and_workers_give_the_same_file(self):
        args = ("--reflow", "on", "--max-staff-mm", "12", "--page-count", "3")
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            txt, f1 = self.run_build(a, 2, 1, *args)
            self.assertIn("G:  3 lines (re-flowed from 2)", txt)
            self.assertIn("G: re-flow: 2 of 2 lines can be cut", txt)
            _, f2 = self.run_build(b, 2, 2, *args)
            self.assertEqual(self.sig(f1), self.sig(f2))

    def test_group_budget_note_and_whole_line_report(self):
        with tempfile.TemporaryDirectory() as a:
            txt, _ = self.run_build(a, 1, 1, "--reflow", "on")      # one line: nothing to cut
            self.assertIn("G: page budget", txt)
            self.assertIn("G: re-flow: 0 of 1 lines can be cut; whole: 1 no clef and key prefix found", txt)


@needs_deps
class TestGroupGapAndSizeFirst(unittest.TestCase):
    """group_gap (stacked staves) and size-first layout on ledger (0.3.0-dev.36)."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.pdf = os.path.join(cls.tmp.name, "s.pdf")
        make_score_pdf(cls.pdf, lyrics=False)
        cls.res = pt.analyse_page(pymupdf.open(cls.pdf)[0], 0, 400, 0)
        cls.grp = [st.idx for st in cls.res.systems[0]]

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def stack(self, gap, runs=None, **kw):
        g, res = self.grp, self.res
        runs = runs or [("A", [g[0]]), ("B", [g[2]])]
        return pt.group_strip(res, g, runs, pt.OWN_HEADER_BASE + res.staves[g[0]].system,
                              gap_sp=gap, **kw)

    def test_group_gap_sets_the_space_between_staves(self):
        sp = self.res.sp
        for gap in (6.0, 20.0):                      # wider than the ink guard needs
            with self.subTest(gap=gap):
                (_, t1, _), (_, t2, _) = self.stack(gap).staff_labels
                self.assertAlmostEqual((t2 - t1) / sp, 4 + gap, delta=0.6)
        # a small gap: the staves come closer than the source, never closer than the ink guard
        (_, t1, _), (_, t2, _) = self.stack(1.0).staff_labels
        (_, u1, _), (_, u2, _) = self.stack(None).staff_labels
        self.assertLess(t2 - t1, u2 - u1)
        self.assertGreaterEqual((t2 - t1) / sp, 4 + 1.0)

    def test_no_group_gap_keeps_the_source_distance(self):
        g, res = self.grp, self.res
        a = pt.group_strip(res, g, [("A", [g[0]]), ("B", [g[2]])],
                           pt.OWN_HEADER_BASE + res.staves[g[0]].system)
        b = self.stack(None)
        self.assertEqual(a.staff_labels, b.staff_labels)
        self.assertTrue((a.img == b.img).all())

    def test_two_staff_part_without_labels(self):
        g = self.grp
        runs = [("P", [g[0]]), ("P", [g[1]])]
        two = self.stack(30.0, runs=runs, labels=False)
        self.assertEqual(two.staff_labels, [])
        src = pt.make_strip(self.res, [g[0], g[1]],
                            pt.OWN_HEADER_BASE + self.res.staves[g[0]].system)
        self.assertGreater(two.img.shape[0], src.img.shape[0])       # 30 sp apart
        near = self.stack(1.0, runs=runs, labels=False)
        self.assertLessEqual(near.img.shape[0], src.img.shape[0])

    def test_set_key_and_per_part_value(self):
        data = {"parts": ["A", "B"], "groups": {"Trbs": ["A", "B"]}, "layout": {}}
        ch = pt.apply_set(data, ["group_gap=5", "Trbs:group_gap=3"])
        self.assertEqual(data["layout"]["group_gap"], 5.0)
        self.assertEqual(data["layout"]["parts"]["Trbs"]["group_gap"], 3.0)
        self.assertIn("group_gap: source -> 5.0", ch)
        opts = {**pt.LAYOUT_DEFAULTS, "group_gap": 5.0}
        self.assertEqual(pt.own_group_gap(data, "Trbs", opts), 3.0)
        self.assertEqual(pt.own_group_gap(data, "A", opts), 5.0)
        self.assertIsNone(pt.own_group_gap({}, "A", {**pt.LAYOUT_DEFAULTS}))
        pt.apply_set(data, ["group_gap=source", "Trbs:group_gap=source"])
        self.assertNotIn("group_gap", data["layout"])
        for bad in (["group_gap=0.5"], ["group_gap=99"], ["group_gap=x"]):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                pt.apply_set(data, bad)

    def test_ledger_takes_the_largest_staff_first(self):
        def strip():
            img = np.zeros((120, 2000), bool)
            for k in range(5):
                img[40 + 10 * k, :] = True
            return pt.Strip(img, 0, 40, 80, 10.0, np.zeros_like(img))
        strips = [strip() for _ in range(60)]
        opts = {**pt.LAYOUT_DEFAULTS, "paper": "ledger"}
        smax = pt.fit_scale(strips, 400, opts)
        sc, _, n = pt.choose_layout(strips, 400, opts)
        self.assertAlmostEqual(sc, smax, places=6)
        saved = pt.SIZE_FIRST
        try:
            pt.SIZE_FIRST = set()                           # the page-turn rule first
            sc2, _, n2 = pt.choose_layout(strips, 400, opts)
        finally:
            pt.SIZE_FIRST = saved
        self.assertLess(sc2, smax)                           # it gave staff size for turns
        self.assertLessEqual(pt.turns(n2), pt.turns(n))
        lt = {**pt.LAYOUT_DEFAULTS}                          # Letter keeps its rule
        self.assertLess(pt.fit_scale(strips, 400, lt), smax)

    def test_build_with_group_gap_makes_a_shorter_group_line(self):
        with tempfile.TemporaryDirectory() as d:
            pdf = os.path.join(d, "s.pdf")
            make_score_pdf(pdf, lyrics=False)
            env = dict(os.environ, PARTITOR_ALLOW_ROOT="1")
            run = lambda *a: subprocess.run([sys.executable, SRC, *a], capture_output=True,
                                            text=True, env=env)
            self.assertEqual(run("detect", pdf, "--dpi", "300").returncode, 0)
            lp = Path(d, "s.partitor", "layout.yaml")
            lay = yaml.safe_load(lp.read_text())
            lay["groups"] = {"Low": ["Alto", "Bass"]}
            heights = {}
            for gap in (None, 2.0):
                lay["layout"] = {"group_gap": gap} if gap else {}
                lp.write_text(yaml.safe_dump(lay, sort_keys=False))
                r = run("build", pdf, "--large", "off")
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                page = pymupdf.open(Path(d, "s.partitor", "parts", "04-Low.pdf"))[0]
                pix = page.get_pixmap(dpi=72)
                ink = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, -1)[..., 0] < 128
                rows = np.where(ink[60:700, :].any(axis=1))[0]      # not the folio
                heights[gap] = rows.max() - rows.min()
            self.assertLess(heights[2.0], heights[None])
