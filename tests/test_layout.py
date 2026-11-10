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
    build,
    config,
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
            for paper, size, marks in (("letter", (792.0, 1224.0), 1), ("a4", (841.89, 1190.55), 0)):
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
                        self.assertAlmostEqual(lines[0]["rect"].width, size[0], delta=0.5)

    def test_large_copy_cutline_choices(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d, "p.pdf")
            doc = pymupdf.open()
            doc.new_page(width=612.0, height=792.0)
            doc.save(src)
            got = {}
            for c in ("dotted", "marks", "off"):
                got[c] = pymupdf.open(pt.large_copy(src, "letter", c))[0].get_drawings()
        self.assertEqual([len(got[c]) for c in ("dotted", "marks", "off")], [1, 2, 0])
        self.assertLess(got["marks"][0]["rect"].width, 100)

    def test_large_copy_cut_line_is_dotted(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d, "p.pdf")
            doc = pymupdf.open()
            doc.new_page(width=612.0, height=792.0)
            doc.save(src)
            dr = pymupdf.open(pt.large_copy(src, "letter"))[0].get_drawings()
        self.assertEqual(len(dr), 1)
        self.assertTrue(dr[0].get("dashes"), dr[0].get("dashes"))
        self.assertNotIn("[] 0", dr[0]["dashes"])


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

    def test_blank_after_the_key_ends_the_prefix_even_when_lines_look_alike(self):
        """Every line has the same marks (x 100-128, no gap in them) after the
        key and differs only from x 130 on: the lines look alike for a long
        way, but a blank of 4 sp after the key still ends the key."""
        def mk(dy, first=False):
            s = flow_line([(130, dy)], [170, 198], key=True, first=first)
            for x0 in range(100, 128, 5):            # strokes 2 px apart: no gap of 0.3 sp
                s.img[42:62, x0:x0 + 3] = True
            return s
        ls = [mk(44, True), mk(52), mk(60)]
        for i, p in enumerate(pt.find_prefixes(ls)):
            with self.subTest(line=i):
                self.assertIsNotNone(p)
                self.assertTrue(54 <= p[0] <= 60, p)

    def test_line_without_the_highest_common_gap_takes_a_lower_one(self):
        """Two lines have a time signature after the key (a second gap at x 68),
        the third has none: it keeps its own prefix, ending after the key."""
        def mk(sig, notes):
            s = flow_line(notes, [150, 198], key=True)
            if sig:
                s.img[44:60, 62:65] = True
            return s
        ls = [mk(True, [(90, 44)]), mk(True, [(90, 52)]), mk(False, [(80, 60)])]
        pre = pt.find_prefixes(ls)
        self.assertTrue(all(p is not None for p in pre), pre)
        self.assertTrue(54 <= pre[2][0] <= 60, pre[2])
        self.assertGreater(pre[0][0], pre[2][0])

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
            with mock_attr(build, "run_build", fake_build), \
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

    def test_justify_keeps_a_final_barline_together(self):
        """A thin line, a small gap and a thick line (final barline) are not pulled apart."""
        s = self.line([(70, 44), (110, 60)], [100, 150], width=160)
        top, bot = int(s.staff_top), int(s.staff_top + 4 * s.sp) + 1
        end = pt.staff_end(s)
        s.img[top:bot, end - 10:end - 8] = True                   # thin line
        s.img[top:bot, end - 3:end + 1] = True                    # thick line, a gap of 5 px
        s.img[top + 8:bot - 8, end - 4] = True                    # a partly inked edge column
        s = pt.dc_replace(s, img=s.img[:, :end + 1].copy()) if hasattr(pt, "dc_replace") else s
        bars = lambda st: [x for x in range(st.img.shape[1]) if st.img[top:bot, x].mean() > 0.9]
        before = bars(s)
        out = pt.justify(s, 250)
        self.assertGreater(pt.staff_end(out) - out.staff_x0, pt.staff_end(s) - s.staff_x0)   # it was stretched
        after = bars(out)
        self.assertEqual(after[-1] - after[-5], before[-1] - before[-5])       # thin to thick: same distance

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

    def test_group_first_line_names_only_when_there_is_room(self):
        # 0.8.29: the ambitus always shows; the full names stand left of it
        # only when the first line is short enough to hold them
        amb = {"Alto": ("C3", 21, 37), "Basso": ("F2", 14, 30)}

        def g(width, bars):
            s = self.line([(70, 44)], bars, width=width)
            s.bracket = True
            s.sp = 4.0
            s.staff_labels = [(p, 40, 80) for p in ("Alto", "Basso")]
            return s
        full = [g(1200, [198, 1100]), g(1200, [198, 1100])]
        out = pt.finish_lines(full, "G", True, amb_map=amb)
        self.assertEqual(out[0].name_labels, [])                  # no room: no names
        self.assertEqual(len(out[0].ambitus_marks), 2)            # the ambitus stays
        short = [g(700, [198, 600]), g(1200, [198, 1100])]
        out = pt.finish_lines(short, "G", True, amb_map=amb)
        self.assertEqual([n for n, *_ in out[0].name_labels], ["Alto", "Basso"])
        self.assertEqual(len(out[0].ambitus_marks), 2)            # both are drawn
        self.assertEqual(out[1].name_labels, [])
        names = [lb for lb in pt.line_labels(out[0]) if lb[0] in ("Alto", "Basso")]
        amb_left = min(m[0] for m in out[0].ambitus_marks)
        self.assertTrue(all(x < amb_left for _, x, *_ in names), (names, amb_left))
        self.assertGreaterEqual(min(x - pt.text_len(n, "regular", f) for n, x, _, f, _ in names), 0)

    def test_group_short_names_default_rule_and_custom(self):
        # 0.8.30: `Part:short=...` replaces the rule for one part; the rule stays the default
        self.assertEqual(pt.short_name("Bass Trombone Grosso"), "Bass Tro. Gro.")
        self.assertEqual(pt.short_name("Bass Trombone Grosso", None), "Bass Tro. Gro.")
        self.assertEqual(pt.short_name("Bass Trombone Grosso", ""), "Bass Tro. Gro.")
        self.assertEqual(pt.short_name("Bass Trombone Grosso", "B.Tbn."), "B.Tbn.")

        def g(parts):
            s = self.line([(70, 44)], [198])
            s.bracket = True
            s.staff_labels = [(p, 40, 80) for p in parts]
            return s
        lines = [g(["Alto Trombone", "Bass Trombone"]), g(["Alto Trombone", "Bass Trombone"])]
        plain = pt.finish_lines(lines, "G", True)
        self.assertEqual([n for n, *_ in plain[1].staff_labels], ["Alto Tro.", "Bass Tro."])
        own = pt.finish_lines([g(["Alto Trombone", "Bass Trombone"]),
                               g(["Alto Trombone", "Bass Trombone"])], "G", True,
                              short_map={"Bass Trombone": "B.Tbn."})
        self.assertEqual([n for n, *_ in own[1].staff_labels], ["Alto Tro.", "B.Tbn."])
        # the label column is as wide as the longest short form
        wide = pt.label_column(lines, 10.0, None, {"Bass Trombone": "Bass Trombone Grosso!"})
        self.assertGreater(wide, pt.label_column(lines, 10.0))

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
class TestLineEndAtBarline(unittest.TestCase):
    """A final or repeat barline (thin + thick) is found at its middle, up to
    2.2 sp before the staff end: the line still ends at a barline."""

    def ends(self, gap_sp):
        from types import SimpleNamespace
        res = SimpleNamespace(staves=[SimpleNamespace(x0=0, x1=1000)], sp=10.0,
                              barlines={0: [300, 600, int(1000 - gap_sp * 10)]})
        s = flow_line([], [10], width=1000)
        pt.set_bar_geometry(s, res, [0], 0, [1, 2, 3])
        return s

    def test_final_barline_found_at_its_middle_ends_the_line(self):
        for gap in (0.1, 2.0, 2.2, 2.5):
            with self.subTest(gap=gap):
                self.assertTrue(self.ends(gap).ends_at_bar)

    def test_a_partial_bar_does_not_end_the_line(self):
        for gap in (2.6, 5.0, 20.0):
            with self.subTest(gap=gap):
                self.assertFalse(self.ends(gap).ends_at_bar)
        self.assertAlmostEqual(self.ends(5.0).end_gap_sp, 5.0, places=1)

    def test_the_limit_is_one_constant(self):
        self.assertEqual(pt.BAR_END_SP, 2.5)


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

    def test_line_alone_between_rest_lines_borrows_the_prefix_of_its_movement(self):
        """A multi-bar rest line has no staff labels, so it splits the movement
        into segments; a line that stands alone in its segment still gets the
        clef and key of the movement (and is cut), a line of another movement
        does not borrow."""
        from types import SimpleNamespace
        a = self.lines()
        rest = group_line([], [198])
        rest.staff_labels = []
        rest.rest_src = (None, None, SimpleNamespace(bars=6))
        lone = group_line([(72, 12), (125, 4)], [110, 160, 198])
        ls = a[:2] + [rest, lone]
        pre = pt.find_prefixes(ls)
        self.assertIsNone(pre[2])
        self.assertIsNotNone(pre[3])
        self.assertIn(pre[3][1], (0, 1))
        self.assertEqual(pt.whole_reason(lone, pre[3]), "")
        out = pt.reflow(ls, 140.0, pre)
        self.assertGreater(len(out), len(ls))                       # the lone line is cut too
        ls[3].movement = True                                       # another movement: no donor
        self.assertIsNone(pt.find_prefixes(ls)[3])

    def odd_lone(self, tops):
        """Two lines, a multi-bar rest line, and a lone line whose staves lie a few px off the
        others (scan jitter). The lone line has no gap of its own to compare: it must borrow."""
        from types import SimpleNamespace
        ls = self.lines()[:2]
        rest = group_line([], [198])
        rest.staff_labels = []
        rest.rest_src = (None, None, SimpleNamespace(bars=6))
        return ls + [rest, group_line([(72, 12), (125, 4)], [110, 160, 198], tops=tops)]

    def test_line_with_staves_a_few_px_off_still_borrows_a_prefix(self):
        """Real item: one line of a trombone group had its staves 2 and 3 px off
        (0.2 sp) from every other line, so no line could lend it a prefix: it
        stayed whole and its width capped the staff of the whole part."""
        ls = self.odd_lone((40, 168, 298))
        self.assertFalse(pt._same_stack(ls[0], ls[3]))              # beyond the join tolerance
        self.assertTrue(pt._same_stack(ls[0], ls[3], pt.REFLOW_STACK_SP))
        pre = pt.find_prefixes(ls)
        self.assertIsNotNone(pre[3])
        self.assertIn(pre[3][1], (0, 1))
        self.assertEqual(pt.whole_reason(ls[3], pre[3]), "")

    def test_a_staff_far_off_gets_no_prefix(self):
        ls = self.odd_lone((40, 176, 300))                          # 6 px: 0.6 sp
        self.assertIsNone(pt.find_prefixes(ls)[3])

    def test_borrowed_prefix_is_moved_to_the_staves_of_its_line(self):
        ls = self.odd_lone((40, 168, 298))
        out = pt.reflow(ls, 140.0, pt.find_prefixes(ls))
        mine = [o for o in out if [t - o.staff_top for _, t, _ in o.staff_labels] == [0, 128, 258]]
        self.assertGreater(len(mine), 1)                            # the lone line is cut
        for o in mine:
            for _, t, _ in o.staff_labels:
                # the staff lines run through the copied clef and key without a step
                self.assertTrue(o.img[t:t + 41:10, 0:60].any(axis=1).all(), t)
                self.assertTrue(o.img[t - 12:t + 54, 6:25].any())   # the copied clef sits on its staff
                self.assertTrue(o.img[t + 4:t + 22, 36:56].any())   # and the key signature

    def test_restack_leaves_equal_stacks_alone_and_moves_the_others(self):
        a = group_line([(70, 4)], [100, 198], first=True)
        same = group_line([(75, 20)], [105, 198], tops=(40, 170, 300))
        self.assertIs(pt._restack(a, same), a)                      # builds that work are unchanged
        far = group_line([(75, 20)], [105, 198], tops=(40, 167, 296))
        moved = pt._restack(a, far)
        self.assertIsNot(moved, a)
        self.assertEqual(moved.img.shape, a.img.shape)
        self.assertTrue(moved.img[167:167 + 41:10, 0:60].any(axis=1).all())    # staff 2 lines at the new rows
        self.assertFalse(np.array_equal(moved.img, a.img))
        self.assertEqual(int(moved.img[40:81].sum()), int(a.img[40:81].sum()))  # the top staff is untouched

    def test_barline_inside_the_prefix_gives_a_bar_without_width_not_a_crash(self):
        """A line whose first barline lies inside its own prefix (a bar cut by a line
        break leaves no music after the key signature): the bar has no width. It
        gave a negative width and a ValueError in the composition."""
        ls = self.lines()
        ls[1] = group_line([(75, 20), (120, 12)], [50, 150, 198])
        pre = pt.find_prefixes(ls)
        self.assertGreater(pre[1][0], 50)                           # the barline is inside the prefix
        out = pt.reflow(ls, 140.0, pre)
        self.assertGreater(len(out), len(ls))
        for o in out:
            self.assertGreater(o.img.shape[1], 0)

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
            with mock_attr(build, "run_build", fake_build), \
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

    def run_build(self, d, systems, jobs, *args, layout=None):
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
        if layout:
            lay.setdefault("layout", {}).update(layout)
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

    def test_a_part_can_have_its_own_paper(self):
        """0.8.4: the group on ledger while the item is on Letter."""
        with tempfile.TemporaryDirectory() as a:
            txt, f = self.run_build(a, 1, 1, layout={"parts": {"G": {"paper": "ledger"}}})
            self.assertIn("G: own layout paper=ledger", txt)
            r = pymupdf.open(str(f))[0].rect
            self.assertEqual((round(r.width), round(r.height)), (1224, 792))
        with tempfile.TemporaryDirectory() as b:
            _, f = self.run_build(b, 1, 1)
            self.assertEqual(round(pymupdf.open(str(f))[0].rect.width), 612)

    def test_binding_narrows_the_text_and_the_staff(self):
        def staff(d, *args, layout=None):
            txt, _ = self.run_build(d, 1, 1, *args, layout=layout)
            import re
            return float(re.search(r"G:  .*staff ([0-9.]+) mm", txt).group(1))
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            wide = staff(a, "--margin-side", "8", "--duplex", "on")
            bound = staff(b, "--margin-side", "8", "--duplex", "on", layout={"binding": 60.0})
            self.assertLess(bound, wide)

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
        class Asked(set):                                   # call assertion: choose_layout
            asked = 0                                       # reads config.SIZE_FIRST

            def __contains__(self, item):
                Asked.asked += 1
                return super().__contains__(item)
        saved = config.SIZE_FIRST
        try:
            config.SIZE_FIRST = Asked()                     # the page-turn rule first
            sc2, _, n2 = pt.choose_layout(strips, 400, opts)
        finally:
            config.SIZE_FIRST = saved
        self.assertGreater(Asked.asked, 0)
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


@needs_deps
class TestMergeRestBars(unittest.TestCase):
    """Bars that hold only measure rests on every staff become one multi-bar rest."""

    BARS = [130, 230, 330, 430]       # barline x: bar 0 starts at PRE
    PRE = 30

    def line(self, staves=1, hollow=None, note=None, mark=None, rests=(0, 1, 2)):
        """sp 10; a staff top at 40, 140, ...; a whole rest hangs under line 2 in each
        bar of `rests`; `note` (bar, staff): a quarter note instead; `hollow`
        (bar, staff): a whole note."""
        h = 40 + 100 * staves
        img = np.zeros((h, 440), bool)
        tops = [40 + 100 * k for k in range(staves)]
        for t0 in tops:
            for k in range(5):
                img[t0 + 10 * k, :] = True
        starts = [self.PRE] + [b + 2 for b in self.BARS[:-1]]
        for b in rests:
            for k, t0 in enumerate(tops):
                cx = starts[b] + 40
                if (b, k) == note:
                    img[t0 + 20:t0 + 28, cx:cx + 9] = True
                    img[t0 - 5:t0 + 24, cx + 8:cx + 10] = True       # a stem
                elif (b, k) == hollow:
                    img[t0 + 20:t0 + 30, cx:cx + 13] = True
                    img[t0 + 22:t0 + 28, cx + 3:cx + 10] = False
                else:
                    img[t0 + 11:t0 + 16, cx:cx + 14] = True          # whole rest, 0.5 sp
        for b in self.BARS:
            img[tops[0]:tops[-1] + 41, b:b + 2] = True
        s = pt.Strip(img, 0, tops[0], tops[0] + 40, 10.0, np.zeros_like(img),
                     bars_x=list(self.BARS), bar_nums=[10, 11, 12, 13], ends_at_bar=True)
        if mark is not None:
            s.marks = [mark]
        return s

    def test_a_run_of_rest_bars_is_found(self):
        self.assertEqual(pt.rest_bar_runs(self.line(), self.PRE), [(0, 2)])
        self.assertEqual(pt.rest_bar_runs(self.line(staves=3), self.PRE), [(0, 2)])

    def test_the_first_bar_needs_a_known_start(self):
        self.assertEqual(pt.rest_bar_runs(self.line(), None), [(1, 2)])

    def test_a_bar_with_a_note_is_never_merged(self):
        self.assertEqual(pt.rest_bar_runs(self.line(note=(1, 0)), self.PRE), [])
        self.assertEqual(pt.rest_bar_runs(self.line(staves=3, note=(2, 2)), self.PRE), [(0, 1)])
        self.assertEqual(pt.rest_bar_runs(self.line(rests=(0, 1, 2, 3)), self.PRE), [(0, 3)])

    def test_a_whole_note_is_not_a_rest(self):
        """A hollow whole note on one staff keeps its bar."""
        self.assertEqual(pt.rest_bar_runs(self.line(staves=3, hollow=(0, 1)), self.PRE), [(1, 2)])

    def test_a_single_rest_bar_is_kept(self):
        self.assertEqual(pt.rest_bar_runs(self.line(rests=(0,)), self.PRE), [])

    def test_a_rehearsal_mark_keeps_its_bar(self):
        """The mark stands at the start of bar 2: that bar stays."""
        self.assertEqual(pt.rest_bar_runs(self.line(mark=(240, "A")), self.PRE), [(0, 1)])

    def merged(self, **kw):
        return pt.merge_rest_bars([self.line(**kw)], {"rests": "compress"}, pre=[(self.PRE, 0)])[0]

    def test_the_merge_rebuilds_the_line(self):
        s = self.line(staves=3)
        out = self.merged(staves=3)
        self.assertEqual(len(out.bars_x), 2)
        self.assertEqual(out.bar_nums, [10, 13])                      # the merged bar keeps its first number
        self.assertLess(out.img.shape[1], s.img.shape[1])
        self.assertEqual([(tx, off) for _, tx, off in out.rest_labels], [("3", 0), ("3", 100), ("3", 200)])
        self.assertTrue(all(self.PRE < cx < out.bars_x[0] for cx, _, _ in out.rest_labels))
        for t0 in (40, 140, 240):                                     # an H-bar on every staff
            self.assertGreater(int(out.img[t0 + 20, self.PRE + 30:out.bars_x[0] - 30].sum()), 0)
        d = out.bars_x[1] - s.bars_x[3]                               # the last bar is the old one, moved
        self.assertTrue((out.img[:, s.bars_x[2] + 10 + d:s.bars_x[3] + 2 + d]
                         == s.img[:, s.bars_x[2] + 10:s.bars_x[3] + 2]).all())
        self.assertEqual(out.img.shape, out.hdr.shape)
        self.assertEqual(len(pt.rest_boxes(out)), 3)                  # a count above every staff

    def test_the_count_stands_above_every_staff(self):
        out = self.merged(staves=3)
        boxes = pt.rest_boxes(out)
        bases = sorted(b[3] for b in boxes)
        self.assertEqual(len(bases), 3)
        for base, t0 in zip(bases, (40, 140, 240)):
            self.assertLess(base, t0)                                   # above its staff ...
            self.assertGreater(base, t0 - 100 + 40)                     # ... and below the staff above it
        self.assertEqual(len(pt.rest_boxes(out, top_only=True)), 1)     # line spacing keeps only the top one free

    def test_a_count_without_a_row_is_above_the_top_staff(self):
        """Saved lines of 0.8.11 have (x, text) counts."""
        s = self.merged(staves=3)
        import dataclasses
        old = dataclasses.replace(s, rest_labels=[(cx, tx) for cx, tx, _ in s.rest_labels[:1]])
        box = pt.rest_boxes(old)[0]
        self.assertLess(box[3], old.staff_top)

    def test_every_staff_line_runs_across_the_new_measure(self):
        out = self.merged(staves=3)
        for t0 in (40, 140, 240):
            for k in range(5):
                self.assertTrue(out.img[t0 + 10 * k, 5:out.img.shape[1] - 5].all())

    def test_rests_keep_leaves_the_lines_alone(self):
        s = self.line()
        self.assertIs(pt.merge_rest_bars([s], {"rests": "keep"}, pre=[(self.PRE, 0)])[0], s)

    def test_a_line_without_a_run_keeps_its_image(self):
        s = self.line(note=(1, 0))
        out = pt.merge_rest_bars([s], {}, pre=[(self.PRE, 0)])[0]
        self.assertIs(out.img, s.img)                                 # nothing merged
        self.assertEqual(out.bars_x, s.bars_x)
        self.assertEqual((out.rest_in, out.rest_out), (1, 0))         # but bar 0 is a one-bar rest at the edge

    def test_a_single_rest_bar_at_either_edge_is_a_one_bar_rest(self):
        a = pt.merge_rest_bars([self.line(rests=(0,), note=(0, 0))], {}, pre=[(self.PRE, 0)])[0]
        self.assertEqual((a.rest_in, a.rest_out), (0, 0))             # a note in bar 0: no rest
        b = pt.merge_rest_bars([self.line(rests=(0, 1, 2, 3), note=(1, 0))], {}, pre=[(self.PRE, 0)])[0]
        self.assertEqual((b.rest_in, b.rest_out), (1, 2))             # bar 0 alone; bars 2-3 at the end
        c = pt.merge_rest_bars([self.line(rests=(0,))], {"rests": "keep"}, pre=[(self.PRE, 0)])[0]
        self.assertEqual((c.rest_in, c.rest_out), (0, 0))             # rests: keep records nothing

    def test_a_merge_that_saves_nothing_is_not_made(self):
        import dataclasses
        narrow = dataclasses.replace(self.line(), bars_x=[60, 90, 120, 150])
        self.assertIs(pt._merge_run(narrow, 0, 1, 10), narrow)

    def test_the_count_moves_with_justify_and_indent(self):
        out = self.merged()
        j = pt.justify(out, out.img.shape[1] + 80)
        self.assertEqual(len(j.rest_labels), 1)
        self.assertGreaterEqual(j.rest_labels[0][0], out.rest_labels[0][0])
        self.assertEqual(pt.pad_left(j, 12).rest_labels[0][0], j.rest_labels[0][0] + 12)

    def test_the_count_moves_with_re_flow(self):
        out = self.merged()
        cut = pt.reflow([out], 150.0, pre=[(self.PRE, 0)])
        self.assertEqual([t for s_ in cut for _, t, _ in s_.rest_labels], ["3"])

    def test_the_planner_sees_the_shorter_line(self):
        s = self.line(staves=3)
        before = pt.read_source([s], {}, 150).lines[0]["whole"]
        after = pt.read_source([self.merged(staves=3)], {}, 150).lines[0]["whole"]
        self.assertLess(after, before)

    def test_justify_stretches_the_h_bar_and_keeps_the_count_in_its_middle(self):
        """A merged rest that fills most of the line: its H-bar is not mistaken for a staff line,
        takes most of the extra space, and the count stays centred over it."""
        s = self.merged(staves=3)
        wide = pt.justify(s, s.img.shape[1] + 200)
        self.assertGreater(pt.staff_end(wide) - wide.staff_x0, pt.staff_end(s) - s.staff_x0)
        mid = 40 + 20
        band = lambda st: st.img[mid - 4:mid + 5].all(axis=0)

        def hbar(st):
            cx = int(st.rest_labels[0][0])
            b = band(st)
            a = z = cx
            while a > 0 and b[a - 1]:
                a -= 1
            while z + 1 < len(b) and b[z + 1]:
                z += 1
            return a, z + 1
        a0, z0 = hbar(s)
        a1, z1 = hbar(wide)
        self.assertGreater(z1 - a1, z0 - a0 + 100)                    # most of the 200 px went into the bar
        self.assertLessEqual(abs(wide.rest_labels[0][0] - (a1 + z1) / 2.0), 1.0)    # the count is centred
        self.assertEqual(len({round(c) for c, _, _ in wide.rest_labels}), 1)        # one column for all staves

    def test_a_rest_that_fills_the_line_keeps_its_staff_lines(self):
        """Few bars, mostly H-bar: the staff lines are still found from the staff, not the ink."""
        s = self.merged(staves=3)
        self.assertEqual(len(pt.staff_lines(s)), 3)
        wide = pt.justify(s, s.img.shape[1] + 120)
        self.assertEqual(len(pt.staff_lines(wide)), 3)

    def test_a_merged_rest_at_a_line_edge_is_recorded(self):
        out = self.merged(staves=3)                                   # bars 0-2 merged, bar 3 music
        self.assertEqual((out.rest_in, out.rest_out), (3, 0))
        mid = pt.merge_rest_bars([self.line(rests=(0, 1, 2, 3), note=(0, 0))], {}, pre=[(self.PRE, 0)])[0]
        self.assertEqual((mid.rest_in, mid.rest_out), (0, 3))         # bars 1-3: a rest at the end
        both = pt.merge_rest_bars([self.line(rests=(1, 2), note=(0, 0))], {}, pre=[(self.PRE, 0)])[0]
        self.assertEqual((both.rest_in, both.rest_out), (0, 0))       # a run in the middle: no edge
        self.assertEqual(self.line().rest_in, 0)

    def test_re_flow_gives_each_piece_the_rest_of_its_edge_bar(self):
        out = self.merged()
        cut = pt.reflow([out], 150.0, pre=[(self.PRE, 0)])
        self.assertEqual(cut[0].rest_in, 3)                           # the piece that is the merged rest
        self.assertEqual(cut[-1].rest_in, 0)                          # the piece with the music bar
        self.assertEqual(cut[-1].rest_out, 0)

    def test_a_line_with_no_barline_and_one_rest_per_staff_is_a_one_bar_rest(self):
        s = self.line(staves=3, rests=(1,))                           # a rest in the middle of the line
        import dataclasses
        one = dataclasses.replace(s, bars_x=[], bar_nums=[], ends_at_bar=False)
        out = pt.merge_rest_bars([one], {}, pre=[None])[0]
        self.assertEqual((out.rest_in, out.rest_out), (1, 1))
        self.assertIs(out.img, one.img)                               # nothing is drawn again
        note = dataclasses.replace(self.line(staves=3, rests=(1,), note=(1, 1)), bars_x=[], bar_nums=[], ends_at_bar=False)
        self.assertEqual(pt.merge_rest_bars([note], {}, pre=[None])[0].rest_in, 0)     # a note: not a rest
        two = dataclasses.replace(self.line(staves=3, rests=(1, 2)), bars_x=[], bar_nums=[], ends_at_bar=False)
        self.assertEqual(pt.merge_rest_bars([two], {}, pre=[None])[0].rest_in, 0)      # two blocks: not read

    def test_the_rest_count_of_each_bar_is_kept_for_re_flow(self):
        out = self.merged(staves=3)                                   # bars 0-2 merged, bar 3 music
        self.assertEqual(out.rest_counts, [3, 0])
        one = pt.merge_rest_bars([self.line(rests=(0, 1, 2, 3), note=(1, 0))], {}, pre=[(self.PRE, 0)])[0]
        self.assertEqual(len(one.rest_counts), len(one.bars_x))       # one count per bar left
        self.assertEqual(one.rest_counts[:2], [1, 0])                 # bar 0 a one-bar rest, bar 1 notes
        self.assertEqual(sum(one.rest_counts), 3)                     # bars 2-3 add two more bars of rest

    def test_a_one_bar_rest_cut_by_re_flow_is_a_rest_at_the_edge_of_its_line(self):
        s = self.line(rests=(0, 1, 2, 3), note=(1, 0))                # bar 0 rest, bar 1 note, bars 2-3 rests
        out = pt.merge_rest_bars([s], {}, pre=[(self.PRE, 0)])[0]
        cut = pt.reflow([out], 120.0, pre=[(self.PRE, 0)])
        self.assertTrue(len(cut) >= 2)
        self.assertEqual((cut[0].rest_in, cut[0].rest_out), (1, 1))   # the line of bar 0 alone
        self.assertEqual((cut[1].rest_in, cut[1].rest_out), (0, 0))   # the bar with the note


    def two_lines(self, a, b):
        """Two source lines of one movement, each with its own prefix, as merge_rest_bars leaves them."""
        return [self.merged(**a), self.merged(**b)], [(self.PRE, 0), (self.PRE, 1)]

    def test_two_multi_bar_rests_that_meet_at_a_line_break_become_one_after_re_flow(self):
        """Bars 109-110 end one source line and bars 111-116 start the next, both multi-bar
        rests: re-flow put them in one line as "2" and "6". They are one rest of 8."""
        ls, pre = self.two_lines(dict(rests=(0, 1, 2, 3), note=(0, 0)),       # note, then 3 bars of rest
                                 dict(rests=(0, 1, 2, 3), note=(3, 0)))       # 3 bars of rest, then a note
        self.assertEqual([s.rest_counts for s in ls], [[0, 3], [3, 0]])
        out = pt.reflow(ls, 5000.0, pre)
        self.assertEqual(len(out), 1)
        self.assertEqual([(t, off) for _, t, off in out[0].rest_labels], [("6", 0)])
        self.assertLess(out[0].img.shape[1], sum(s.img.shape[1] for s in ls) - 2 * self.PRE)
        self.assertEqual((out[0].rest_in, out[0].rest_out), (0, 0))
        calls = []
        with mock_attr(pt, "_join_rests", lambda *a, **k: calls.append(1) or a[:4]):
            old = pt.reflow(ls, 5000.0, pre)
        self.assertTrue(calls)                                        # the step runs for the line
        self.assertEqual([t for _, t, _ in old[0].rest_labels], ["3", "3"])   # without it: "3" and "3"

    def test_the_joined_rest_is_drawn_once_with_staff_lines_around_it(self):
        ls, pre = self.two_lines(dict(rests=(0, 1, 2, 3), note=(0, 0), staves=3),
                                 dict(rests=(0, 1, 2, 3), note=(3, 0), staves=3))
        out = pt.reflow(ls, 5000.0, pre)[0]
        self.assertEqual([(t, off) for _, t, off in out.rest_labels], [("6", 0), ("6", 100), ("6", 200)])
        x = int(out.rest_labels[0][0])
        for t0 in (out.staff_top, out.staff_top + 100, out.staff_top + 200):
            self.assertTrue(out.img[t0 + 20, x - 40:x + 40].all())            # the H-bar on the middle line
            self.assertFalse(out.img[t0 + 12:t0 + 15, x - 30:x + 30].any())        # no whole rest left in the span

    def test_rests_with_music_between_them_are_not_joined(self):
        ls, pre = self.two_lines(dict(rests=(0, 1, 2, 3), note=(0, 0)), dict(rests=(0, 1, 2, 3), note=(0, 0)))
        out = pt.reflow(ls, 5000.0, pre)
        self.assertEqual(len(out), 1)
        self.assertEqual([t for _, t, _ in out[0].rest_labels], ["3", "3"])   # note, 3, note, 3

    def test_a_multi_bar_rest_alone_stays_as_it_is_after_re_flow(self):
        ls, pre = self.two_lines(dict(rests=(0, 1, 2, 3), note=(0, 0)), dict(rests=(0, 1, 2, 3), note=(0, 0)))
        cut = pt.reflow(ls, 200.0, pre)
        self.assertEqual(sorted(t for o in cut for _, t, _ in o.rest_labels), ["3", "3"])

    def test_the_prefix_of_a_line_that_starts_with_a_multi_bar_rest_is_not_copied(self):
        """find_prefixes ends such a line's prefix after the left bracket of its H-bar. A
        continuation line that copied it showed the bracket as a stray thick barline (bar 124).
        It copies the clef and key of a line without a rest at its start."""
        plain = self.merged(rests=(0, 1, 2, 3), note=(0, 0))
        rest = self.merged(rests=(0, 1, 2))
        self.assertEqual(rest.rest_counts, [3, 0])
        pre = [(self.PRE, 0), (60, 1)]                                # the bracket (x 50-55) lies inside 60
        tail = rest.img.shape[1] - (rest.bars_x[0] + 2)               # the bar after the rest
        out = pt.reflow([plain, rest], 260.0, pre)
        self.assertEqual(out[-1].img.shape[1], self.PRE + tail)       # clef and key of the plain line only
        called = []
        real = pt._starts_with_rest
        with mock_attr(pt, "_starts_with_rest", lambda s: called.append(s) or False):
            old = pt.reflow([plain, rest], 260.0, pre)
        self.assertTrue(called)                                       # the test goes through the guard
        self.assertEqual(old[-1].img.shape[1], 60 + tail)             # without it: the bracket comes along
        self.assertTrue(real(rest) and not real(plain))

    def test_a_line_with_a_rest_at_its_start_and_no_other_donor_keeps_its_own_prefix(self):
        rest = self.merged(rests=(0, 1, 2))
        a = self.merged(rests=(0, 1, 2))
        pre = [(60, 0), (60, 1)]
        out = pt.reflow([a, rest], 200.0, pre)
        self.assertEqual(out[-1].img.shape[1], 60 + rest.img.shape[1] - (rest.bars_x[0] + 2))

    def test_a_multi_bar_rest_block_is_drawn_for_a_span_and_none_for_a_narrow_one(self):
        img = np.zeros((140, 500), bool)
        for k in range(5):
            img[40 + 10 * k, :] = True
        wide = pt.rest_bar_block(img, 30, 430, [40], 10.0)
        self.assertEqual(wide.shape, (140, 260))                      # at most REST_BAR_SP
        self.assertTrue(wide[60, 30:230].all())                       # the H-bar on the middle line
        mid = pt.rest_bar_block(img, 30, 230, [40], 10.0)
        self.assertEqual(mid.shape[1], 170)                           # 0.85 of the span
        self.assertIsNone(pt.rest_bar_block(img, 30, 100, [40], 10.0))    # saves too little

    def hbar(self, style=None, sp=20.0, top=40):
        img = np.zeros((int(top + 6 * sp), 600), bool)
        if style is None:
            pt.draw_hbar(img, top, 100, 400, sp)
        else:
            pt.draw_hbar(img, top, 100, 400, sp, style)
        return img

    def staff_strip(self, **kw):
        img = np.zeros((120, 600), bool)
        for k in range(5):
            img[40 + 10 * k, :] = True
        return pt.Strip(img, 0, 40, 80, 10.0, np.zeros_like(img), **kw)

    def test_the_engraved_h_bar_has_thin_serifs_from_line_2_to_line_4(self):
        img = self.hbar("engraved")                                    # sp 20: top line row 40, middle line row 80
        self.assertEqual(int(img[65, 100:110].sum()), 3)               # the left serif: 0.16 sp is 3 px
        self.assertEqual(int(img[65, 390:400].sum()), 3)               # the right serif ends at the bar's end
        col = img[:, 100]
        self.assertFalse(col[:60].any())                               # nothing above line 2
        self.assertTrue(col[60:102].all())                             # line 2 to line 4 with its thickness
        self.assertFalse(col[102:].any())                              # nothing below line 4
        self.assertEqual(int(img[:, 250].sum()), 21)                   # the bar is 1 sp thick
        self.assertTrue(img[80, 100:400].all())                        # across, on the middle line

    def test_the_heavy_h_bar_is_the_look_of_0_8_30(self):
        img = self.hbar("heavy")
        self.assertEqual(int(img[45, 100:130].sum()), 10)              # a bracket 0.5 sp wide
        self.assertTrue(img[40:122, 100].all())                        # the full staff height
        self.assertEqual(int(img[:, 250].sum()), 19)                   # a bar 0.9 sp thick

    def test_the_bold_h_bar_has_serifs_of_0_35_sp_over_the_full_staff_height(self):
        img = self.hbar("bold")
        self.assertEqual(int(img[45, 100:130].sum()), 7)
        self.assertTrue(img[40:122, 100].all())
        self.assertEqual(int(img[:, 250].sum()), 21)

    def test_an_unknown_h_bar_style_draws_the_default_and_a_small_staff_keeps_a_serif(self):
        self.assertTrue((self.hbar("nonsense") == self.hbar("engraved")).all())
        self.assertTrue((self.hbar(None) == self.hbar("engraved")).all())
        tiny = self.hbar("engraved", sp=6.0, top=10)                   # 0.16 sp is 1 px: the serif keeps 2
        self.assertEqual(int(tiny[17, 100:110].sum()), 2)

    def test_a_merged_block_and_a_rest_line_take_the_h_bar_style(self):
        img = np.zeros((140, 500), bool)
        for k in range(5):
            img[40 + 10 * k, :] = True
        eng = pt.rest_bar_block(img, 30, 430, [40], 10.0)
        hvy = pt.rest_bar_block(img, 30, 430, [40], 10.0, "heavy")
        self.assertFalse(eng[41:49, 20].any())                         # engraved: no serif above line 2
        self.assertTrue(eng[50:71, 20].all())
        self.assertTrue(hvy[40:81, 20].all())                          # heavy: a bracket over the full height
        for style in ("engraved", "bold", "heavy"):
            s = pt.make_rest_strip(self.staff_strip(), None, 0, pt.RestRun(5, 3), {"rest_bar": style})
            self.assertEqual(s.rest_bar, style)
            self.assertEqual(pt.justify(s, 400).rest_bar, style)       # drawn again at the width, same look
        s = pt.make_rest_strip(self.staff_strip(rest_bar="bold"), None, 0, pt.RestRun(5, 3), {})
        self.assertEqual(s.rest_bar, "bold")                           # no option: the line's own

    def test_the_rest_bar_key_is_a_layout_default_and_a_set_key(self):
        self.assertEqual(pt.LAYOUT_DEFAULTS["rest_bar"], "engraved")
        self.assertEqual(pt.SET_KEYS["rest_bar"], ("rest_bar", ("engraved", "bold", "heavy")))
        self.assertEqual(set(pt.REST_BAR_STYLES), {"engraved", "bold", "heavy"})
        self.assertEqual(pt.Strip.__dataclass_fields__["rest_bar"].default, "engraved")
