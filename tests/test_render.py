# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""Tests for rendering, layout model, batch extras, ledger and repage.

Needs the venv packages (numpy, opencv, pymupdf, PyYAML); without them every test
is skipped. Run with the venv interpreter:

    venv/bin/python3 -m unittest -v tests/test_render.py

Shared helpers: tests/support.py.
"""
import argparse
import contextlib
import io
import os
import re
import subprocess
import sys
import tempfile
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
    yaml,
    setUpModule,
    tearDownModule,
)


@needs_deps
class TestRendering(unittest.TestCase):
    def test_header_left_of_staff_moves_right(self):
        # header text starting left of the staff start must not indent the
        # staff: the strip starts at the staff ink, the header moves right
        sp = 10.0
        owner = np.full((200, 400), pt.OWN_NONE, np.int32)
        st = pt.Staff(0, 0, [100 + 10 * k for k in range(5)], 100, 380, system=0)
        for ly in st.lines:
            owner[int(ly), 100:381] = 0
        owner[70:80, 40:90] = pt.OWN_HEADER_BASE       # "Allemande" left of x0
        res = pt.PageResult(0, owner.shape, sp, 1, 0.0, 0.0, [st], [[st]], owner)
        s = pt.make_strip(res, [0], pt.OWN_HEADER_BASE)
        self.assertEqual(s.staff_x0, 0)
        self.assertEqual(int(np.flatnonzero(s.hdr.any(axis=0)).min()), 0)

    def test_duplex_pages_shift_by_gutter(self):
        img = np.zeros((120, 600), bool)
        for k in range(5):
            img[40 + 10 * k, :] = True
        strips = [pt.Strip(img.copy(), 0, 40, 80, 10.0, np.zeros_like(img)) for _ in range(40)]
        opts = {**pt.LAYOUT_DEFAULTS, "scale": 2.0, "gap": 6.0, "gutter": 6.0}
        with tempfile.TemporaryDirectory() as d:
            out = Path(d, "p.pdf")
            n = pt.render_part("X", strips, {"title": "T"}, 400, opts, out)
            self.assertGreater(n, 3)
            doc = pymupdf.open(out)
            # 3+ pages of music: p1 is a title page (no music), the music
            # starts on p2 (verso) facing p3 (recto)
            # the title page holds no music: its only image is the logo (0.3.0-dev.40)
            self.assertEqual(len(doc[0].get_image_info()), 1)
            self.assertIn("X", doc[0].get_text())
            self.assertTrue(pt.LAST_RENDER["title_page"])
            self.assertEqual(pt.LAST_RENDER["content"], n - 1)
            xs = [min(i["bbox"][0] for i in doc[p].get_image_info()) for p in (1, 2)]
            self.assertAlmostEqual(xs[1] - xs[0], pt.mm2pt(6.0), delta=0.05)
            out2 = Path(d, "q.pdf")
            n2 = pt.render_part("X", strips, {}, 400, {**opts, "title_page": "off"}, out2)
            self.assertFalse(pt.LAST_RENDER["title_page"])
            self.assertNotEqual(pymupdf.open(out2)[0].get_image_info(), [])
            del n2

    def test_darker_adds_ink(self):
        owner = np.full((200, 400), pt.OWN_NONE, np.int32)
        st = pt.Staff(0, 0, [60.0 + 10 * k for k in range(5)], 20, 380, system=0)
        for k in range(5):
            owner[60 + 10 * k, 20:380] = 0
        res = pt.PageResult(0, (200, 400), 10.0, 1, 0.0, 0.0, [st], [[st]], owner)
        a = pt.make_strip(res, [0], pt.OWN_HEADER_BASE, darker=False)
        b = pt.make_strip(res, [0], pt.OWN_HEADER_BASE, darker=True)
        self.assertGreater(b.img.sum(), 2 * a.img.sum())

    def test_nested_strip_does_not_hide_ink_above(self):
        """Paper of a strip is transparent: ink of the strip above stays."""
        def strip(low_note):
            img = np.zeros((120, 600), bool)
            for k in range(5):
                img[40 + 10 * k, :] = True
            if low_note:
                img[110:118, 300:310] = True          # low note, bottom edge
            return pt.Strip(img, 0, 40, 80, 10.0, np.zeros_like(img))
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "p.pdf"
            opts = {**pt.LAYOUT_DEFAULTS, "clearance": 0.0, "gap": 0.5}
            pt.render_part("X", [strip(True), strip(False)], {}, 400, opts, out)
            pix = pymupdf.open(out)[0].get_pixmap(dpi=400, colorspace=pymupdf.csGRAY)
            g = np.frombuffer(pix.samples, np.uint8).reshape(pix.h, pix.w)
            # the low note must still be visible as a dark blob
            self.assertGreater(int((g < 100).sum()), 0)
            pages = pt.pack([strip(True), strip(False)], 400, opts)
            self.assertEqual(len(pages), 1)
            (s1, y1), (s2, y2) = pages[0]
            k = 72.0 / 400
            self.assertLess(y2, y1 + 120 * k)        # strips do overlap (nested)
            # pixel under the low note's centre is ink
            x = int(round((pt.MARGIN + 305 * k) * 400 / 72))
            y = int(round((pt.MARGIN + pt.TITLE_BAND + y1 + 114 * k) * 400 / 72))
            self.assertLess(int(g[y - 3:y + 4, x - 3:x + 4].min()), 100)


@needs_deps
class TestLayoutModel(unittest.TestCase):
    def strip(self, low=False, sp=10.0):
        img = np.zeros((120, 600), bool)
        for k in range(5):
            img[40 + 10 * k, :] = True
        if low:
            img[110:118, 300:310] = True
        return pt.Strip(img, 0, 40, 80, sp, np.zeros_like(img))

    def test_constant_pitch_without_collisions(self):
        opts = {**pt.LAYOUT_DEFAULTS}
        p = pt.pitches([self.strip(), self.strip(), self.strip()], opts)
        self.assertEqual(p[0], p[1])
        self.assertAlmostEqual(p[0], 40 + opts["gap"] * 10)

    def test_pitch_grows_only_where_ink_collides(self):
        opts = {**pt.LAYOUT_DEFAULTS, "gap": 1.0}
        p = pt.pitches([self.strip(low=True), self.strip(), self.strip()], opts)
        self.assertGreater(p[0], p[1])
        self.assertAlmostEqual(p[1], 40 + 1.0 * 10)

    def test_last_page_never_holds_one_line(self):
        strips = [self.strip() for _ in range(40)]
        opts = {**pt.LAYOUT_DEFAULTS, "gap": 6.0, "scale": 2.0}
        greedy = pt._pack(strips, 400, opts, None)
        k = next(m for m in range(len(strips), 0, -1)
                 if len(pt._pack(strips[:m], 400, opts, None)[-1]) == 1)
        pages = pt.pack(strips[:k], 400, opts)
        self.assertGreater(len(greedy), 1)
        self.assertEqual(len(pages), len(pt._pack(strips[:k], 400, opts, None)))
        self.assertGreaterEqual(len(pages[-1]), pt.MIN_LAST_LINES)
        self.assertEqual(sum(len(p) for p in pages), k)

    def test_two_staff_part_uses_one_staff_height(self):
        img = np.zeros((300, 600), bool)
        for t in (40, 160):
            for k in range(5):
                img[t + 10 * k, :] = True
        # 60 two-staff lines force shrinking; the floor applies to one staff
        # (4 sp), not to the two staves together
        two = [pt.Strip(img.copy(), 0, 40, 200, 10.0, np.zeros_like(img)) for _ in range(60)]
        opts = {**pt.LAYOUT_DEFAULTS, "min_staff_mm": 4.5, "scale": 2.0}
        sc, _, _ = pt.choose_layout(two, 400, opts)
        mm = 40 * 72.0 / 400 * sc * 25.4 / 72.0     # 4 sp of 10 px
        self.assertLess(sc, 2.0)                     # it did shrink
        self.assertGreaterEqual(mm, 4.5 - 0.1)

    def test_turns(self):
        self.assertEqual([pt.turns(n) for n in (1, 2, 3, 4, 5)], [0, 0, 1, 1, 2])

    def test_choose_layout_prefers_fewer_turns_over_gap(self):
        strips = [self.strip() for _ in range(60)]
        opts = {**pt.LAYOUT_DEFAULTS, "min_staff_mm": 1.0}
        sc, gap, n = pt.choose_layout(strips, 400, opts)
        self.assertLessEqual(n, 2)          # fits 2 pages by a smaller gap
        self.assertLess(gap, opts["gap"])
        self.assertGreaterEqual(gap, opts["gap_min"])

    def test_page_box_duplex_spine_wider_same_width(self):
        o = {**pt.LAYOUT_DEFAULTS, "margin_side": 15.0, "gutter": 6.0}
        l1, r1, _, _ = pt.page_box(o, 0, True)       # recto: spine left
        l2, r2, _, _ = pt.page_box(o, 1, True)       # verso: spine right
        self.assertAlmostEqual(l1 - r1, pt.mm2pt(6.0))
        self.assertAlmostEqual(r2 - l2, pt.mm2pt(6.0))
        self.assertAlmostEqual(l1 + r1, l2 + r2)
        l3, r3, _, _ = pt.page_box(o, 1, False)
        self.assertAlmostEqual(l3, r3)

    def test_duplex_auto_over_two_pages(self):
        o = {**pt.LAYOUT_DEFAULTS}
        self.assertEqual([pt.is_duplex(o, n) for n in (1, 2, 3)], [False, False, True])
        self.assertTrue(pt.is_duplex({**o, "duplex": "on"}, 1))
        self.assertFalse(pt.is_duplex({**o, "duplex": "off"}, 4))

    def test_check_margins(self):
        o = {**pt.LAYOUT_DEFAULTS}
        self.assertEqual(pt.check_margins(o), "")
        self.assertIn("outer margin", pt.check_margins({**o, "gutter": 22.0}))
        self.assertIn("margin_top", pt.check_margins({**o, "margin_top": 2.0}))
        self.assertIn("duplex", pt.check_margins({**o, "duplex": "yes"}))

    def test_bar_mark_clears_clef_and_keeps_raise(self):
        s = self.strip()                     # staff top row 40, sp 10
        s.bar_no = 12
        base, top, wpx = pt.bar_mark(s)
        self.assertAlmostEqual(base, 40 - 1.0 * 10)       # bar_raise only
        self.assertGreater(wpx, 0)
        s.img[20:90, 0:15] = True            # clef reaching 2 sp above the staff
        base, top, _ = pt.bar_mark(s)
        self.assertLessEqual(base, 20 - pt.BAR_CLEAR_SP * 10 + 1e-9)
        self.assertLess(top, base)
        s.bar_raise = 3.0
        self.assertLessEqual(pt.bar_mark(s)[0], 40 - 30 + 1e-9)

    def test_bar_number_space_reserved_in_pitch(self):
        a, b = self.strip(), self.strip()
        b.img[20:90, 0:15] = True            # tall clef on the next line
        b.bar_no = 7
        b.bar_size = 4.0
        opts = {**pt.LAYOUT_DEFAULTS, "gap": 1.0}
        p_num = pt.pitches([a, b], opts)[0]
        b.bar_no = None
        b._prof = None
        p_none = pt.pitches([a, b], opts)[0]
        self.assertGreater(p_num, p_none)

    def test_refine_start_skips_bracket_gap(self):
        raw = np.zeros((200, 400), bool)
        grp = [(50.0 + 10 * k, 0, 0) for k in range(5)]
        for g in grp:
            raw[int(g[0]), 130:390] = True      # lines start at 130
        self.assertEqual(pt.refine_start(raw, grp, 1, 10.0, 115), 130)
        self.assertEqual(pt.refine_start(raw, grp, 1, 10.0, 60), 60)   # none within 2.5 sp


@needs_deps
class TestBatchExtras(unittest.TestCase):
    """Groups, parts not extracted, fonts, title-page rule, staff ceiling."""

    def test_group_ops(self):
        data = {"parts": ["S", "A", "T1", "T2", "Org"]}
        self.assertEqual(pt.apply_group_op(data, "Trbs=4,3"), "")
        self.assertEqual(data["groups"], {"Trbs": ["T1", "T2"]})       # score order
        for bad in ("Trbs", "=1", "X=9", "S=1,2", "X=a", "Nope="):
            with self.subTest(bad=bad):
                self.assertNotEqual(pt.apply_group_op(data, bad), "")
        self.assertEqual(pt.apply_group_op(data, "Trbs="), "")
        self.assertNotIn("groups", data)

    def strips(self, n):
        img = np.zeros((120, 600), bool)
        for k in range(5):
            img[40 + 10 * k, :] = True
        return [pt.Strip(img.copy(), 0, 40, 80, 10.0, np.zeros_like(img)) for _ in range(n)]

    def test_two_pages_of_music_get_no_title_page(self):
        opts = {**pt.LAYOUT_DEFAULTS, "scale": 2.0, "gap": 6.0}
        n1 = len(pt.pack(self.strips(1), 400, opts))
        per = 1
        while len(pt.pack(self.strips(per + 1), 400, opts)) == n1:
            per += 1
        with tempfile.TemporaryDirectory() as d:
            n = pt.render_part("X", self.strips(per + 1), {"title": "T"}, 400, opts,
                               Path(d, "p.pdf"))
        self.assertEqual(n, 2)
        self.assertFalse(pt.LAST_RENDER["title_page"])

    def _logo_boxes(self, page):
        """Bounding boxes of the logo images on a page (found by aspect ratio)."""
        path = pt.logo_path()
        pix = pymupdf.Pixmap(str(path))
        asp = pix.width / pix.height
        return [pymupdf.Rect(i["bbox"]) for i in page.get_image_info()
                if abs(i["width"] / i["height"] - asp) < 0.01]

    def _render(self, n_strips, **kw):
        opts = {**pt.LAYOUT_DEFAULTS, "scale": 2.0, "gap": 6.0, **kw.pop("opts", {})}
        with tempfile.TemporaryDirectory() as d:
            out = Path(d, "p.pdf")
            pt.LAST_RENDER.clear()
            n = pt.render_part("X", self.strips(n_strips), {"title": "T", **kw}, 400, opts, out)
            doc = pymupdf.open(out)
            boxes = [self._logo_boxes(p) for p in doc]
            size = (doc[0].rect.width, doc[0].rect.height)
        return n, boxes, size

    def test_logo_on_title_page_centred_low_and_on_back_page_centred(self):
        n, boxes, (pw, ph) = self._render(40)
        self.assertTrue(pt.LAST_RENDER["title_page"])
        self.assertEqual([len(b) for b in boxes], [1] + [0] * (n - 2) + [1])
        t, b = boxes[0][0], boxes[-1][0]
        opts = {**pt.LAYOUT_DEFAULTS, "scale": 2.0, "gap": 6.0}
        c0 = lambda pi: (lambda ml, mr, *_: (ml + pw - mr) / 2)(*pt.page_box(opts, pi, True))
        self.assertAlmostEqual((t.x0 + t.x1) / 2, c0(0), delta=1.0)    # centred on the text block
        self.assertGreater((t.y0 + t.y1) / 2, ph * 0.65)                # towards the bottom
        self.assertLess(t.y1, ph - 40.0)
        self.assertAlmostEqual((b.x0 + b.x1) / 2, c0(n - 1), delta=1.0)   # centred, as the folio
        self.assertLessEqual(b.height, pt.LOGO_LAST_H + 0.1)            # not too big

    def test_logo_not_on_page_1_band_and_sits_above_the_folio(self):
        opts = {**pt.LAYOUT_DEFAULTS, "scale": 2.0, "gap": 6.0}
        per = 1
        while len(pt.pack(self.strips(per + 1), 400, opts)) == 1:
            per += 1
        n, boxes, _ = self._render(per + 1)
        self.assertEqual(n, 2)
        self.assertEqual([len(b) for b in boxes], [0, 1])               # no logo in the title band
        with tempfile.TemporaryDirectory() as d:
            out = Path(d, "p.pdf")
            pt.render_part("X", self.strips(per + 1), {"title": "T"}, 400, opts, out)
            page = pymupdf.open(out)[1]
            folio = [w for w in page.get_text("words") if "/" in w[4]][0]
            logo = self._logo_boxes(page)[0]
            self.assertLessEqual(logo.y1, folio[1])                     # above the page number
            self.assertGreater(logo.y1, folio[1] - 16.0)                # and close to it

    def test_one_page_part_has_the_logo_on_its_only_page_once(self):
        n, boxes, _ = self._render(1)
        self.assertEqual((n, [len(b) for b in boxes]), (1, [1]))

    def _render_quiet(self, n_strips=40):
        with contextlib.redirect_stdout(io.StringIO()) as buf:
            with tempfile.TemporaryDirectory() as d:
                n = pt.render_part("X", self.strips(n_strips), {"title": "T"}, 400,
                                   {**pt.LAYOUT_DEFAULTS, "scale": 2.0, "gap": 6.0},
                                   Path(d, "p.pdf"))
                doc = pymupdf.open(Path(d, "p.pdf"))
                images = sum(len(p.get_image_info()) for p in doc)
                texts = [p.get_text() for p in doc]
        return n, images, buf.getvalue(), texts

    def test_logo_off(self):
        _, boxes, _ = self._render(40, opts={"logo": "off"})
        self.assertEqual(sum(len(b) for b in boxes), 0)

    def test_no_logo_configured_is_silent_and_keeps_no_room(self):
        old = os.environ.pop("PARTITOR_LOGO")
        try:
            pt._LOGO_WARNED.clear()
            self.assertIsNone(pt.logo_path())
            self.assertFalse(pt.logo_wanted({}))
            n, _, out, _ = self._render_quiet()
            self.assertEqual(out.count("logo:"), 0)                      # no warning
            opts = {**pt.LAYOUT_DEFAULTS, "scale": 2.0, "gap": 6.0}
            for k in range(30, 60):                                      # same plan as logo off
                a, _ = pt.plan_pages(self.strips(k), 400, opts, False)
                b, _ = pt.plan_pages(self.strips(k), 400, {**opts, "logo": "off"}, False)
                self.assertEqual(len(a), len(b))
        finally:
            os.environ["PARTITOR_LOGO"] = old

    def test_logo_configured_but_missing_warns_once(self):
        old = os.environ["PARTITOR_LOGO"]
        os.environ["PARTITOR_LOGO"] = old + ".missing"
        try:
            pt._LOGO_WARNED.clear()
            n, images, out, _ = self._render_quiet()
        finally:
            os.environ["PARTITOR_LOGO"] = old
        self.assertGreaterEqual(n, 3)                                    # no logo, no failure
        self.assertEqual(out.count("logo:"), 1)                          # one warning only
        self.assertIn(".missing", out)

    def test_logo_path_is_the_env_file(self):
        self.assertEqual(pt.logo_path(), Path(os.environ["PARTITOR_LOGO"]))
        self.assertTrue(pt.logo_wanted({}))
        self.assertFalse(pt.logo_wanted({"logo": "off"}))

    def test_logo_set_key(self):
        self.assertEqual(pt.LAYOUT_DEFAULTS["logo"], "on")
        self.assertIn("logo", pt.SET_KEYS)

    def test_logo_stays_inside_the_margins(self):
        n, boxes, (pw, ph) = self._render(40)
        for r in (boxes[0][0], boxes[-1][0]):
            self.assertGreaterEqual(r.x0, 14.0)                         # printer edge (5 mm)
            self.assertLessEqual(r.x1, pw - 14.0)
            self.assertLessEqual(r.y1, ph - 14.0)

    def test_last_page_room_for_the_logo_is_planned(self):
        # a last page that the logo would not fit under costs LOGO_COST, so the
        # page breaks move lines forward when that saves the room
        opts = {**pt.LAYOUT_DEFAULTS, "scale": 2.0, "gap": 6.0}
        _, ph = pt.PAPER["letter"]
        self.assertGreater(pt.logo_room(ph, 42.5), 0.0)
        for n in range(30, 60):
            pages, _ = pt.plan_pages(self.strips(n), 400, opts, False)
            pages_off, _ = pt.plan_pages(self.strips(n), 400, {**opts, "logo": "off"}, False)
            self.assertLessEqual(len(pages), len(pages_off) + 1)

    def test_fonts_embedded(self):
        if not any(Path(f, "EBGaramond-Regular.ttf").is_file() for f in pt.font_dirs()):
            self.skipTest("EB Garamond not installed")
        with tempfile.TemporaryDirectory() as d:
            out = Path(d, "p.pdf")
            pt.render_part("Alto", self.strips(3), {"title": "T", "composer": "C"}, 400,
                           {**pt.LAYOUT_DEFAULTS}, out)
            names = {f[3] for f in pymupdf.open(out)[0].get_fonts()}
        self.assertTrue(any("Garamond" in n for n in names), names)

    def test_default_staff_ceiling(self):
        opts = {**pt.LAYOUT_DEFAULTS}
        self.assertIsNone(opts["scale"])
        sc = pt.fit_scale(self.strips(1), 400, opts)     # short line: width allows more
        mm = 40 * 72.0 / 400 * sc * 25.4 / 72.0
        self.assertAlmostEqual(mm, opts["max_staff_mm"], delta=0.05)

    def test_build_skips_part_and_prints_group(self):
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
            lay["skip"] = ["Alto"]
            lay["groups"] = {"Low": ["Tenor", "Bass"]}
            lp.write_text(yaml.safe_dump(lay, sort_keys=False))
            r = run("build", pdf, "--large", "off")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("not extracted", r.stdout)
            parts = sorted(p.name for p in Path(d, "s.partitor", "parts").iterdir())
            self.assertEqual(parts, ["02-Tenor.pdf", "03-Bass.pdf", "04-Low.pdf"])
            doc = pymupdf.open(Path(d, "s.partitor", "parts", "04-Low.pdf"))
            self.assertIn("Tenor", doc[0].get_text())          # members line
            self.assertTrue(doc[0].get_drawings())              # bracket


@needs_deps
class TestLedger(unittest.TestCase):
    """Paper ledger: 17 x 11 in landscape (0.3.0-dev.35)."""

    def wide(self, n=1, px=4000):
        img = np.zeros((120, px), bool)
        for k in range(5):
            img[40 + 10 * k, :] = True
        return [pt.Strip(img.copy(), 0, 40, 80, 10.0, np.zeros_like(img)) for _ in range(n)]

    def test_table_set_key_and_menu_cycle(self):
        self.assertEqual(pt.PAPER["ledger"], (1224.0, 792.0))
        data = {"title": "A", "layout": {}}
        pt.apply_set(data, ["paper=ledger"])
        self.assertEqual(data["layout"]["paper"], "ledger")
        with self.assertRaises(ValueError):
            pt.apply_set(data, ["paper=a3"])
        cur, seen = "letter", []
        for _ in range(3):
            cur = pt.PAPER_NEXT[cur]
            seen.append(cur)
        self.assertEqual(seen, ["a4", "ledger", "letter"])

    def test_per_part_paper_stays_refused(self):
        data = {"parts": ["Canto"], "layout": {}}
        with self.assertRaises(ValueError):
            pt.apply_set(data, ["Canto:paper=ledger"])

    def test_width_fit_is_the_page_width_ratio(self):
        # a line 720 pt wide: Letter holds 527 pt, ledger 1139 pt (margins 15 mm)
        s = self.wide()
        lt = pt.fit_scale(s, 400, {**pt.LAYOUT_DEFAULTS})
        lg = pt.fit_scale(s, 400, {**pt.LAYOUT_DEFAULTS, "paper": "ledger"})
        usable = lambda w: w - 2 * pt.mm2pt(15.0)
        self.assertAlmostEqual(lg / lt, usable(1224.0) / usable(612.0), places=6)

    def test_max_staff_cap_binds_on_a_short_line(self):
        sc = pt.fit_scale(self.wide(px=600), 400, {**pt.LAYOUT_DEFAULTS, "paper": "ledger"})
        mm = 40 * 72.0 / 400 * sc * 25.4 / 72.0
        self.assertAlmostEqual(mm, 8.0, delta=0.01)

    def test_lines_per_page_fall_with_the_larger_staff(self):
        opts = {**pt.LAYOUT_DEFAULTS, "paper": "ledger", "gap": 6.0}
        strips = self.wide(60)
        o_lt = {**pt.LAYOUT_DEFAULTS, "gap": 6.0}
        n_lt = len(pt.pack(strips, 400, {**o_lt, "scale": pt.fit_scale(strips, 400, o_lt)}))
        n_lg = len(pt.pack(strips, 400, {**opts, "scale": pt.fit_scale(strips, 400, opts)}))
        self.assertGreater(n_lg, n_lt)

    def test_render_geometry_and_footer_on_a_landscape_page(self):
        strips = self.wide(80, px=3000)
        opts = {**pt.LAYOUT_DEFAULTS, "paper": "ledger", "gap": 6.0, "duplex": "on",
                "scale": pt.fit_scale(self.wide(1, px=3000), 400,
                                      {**pt.LAYOUT_DEFAULTS, "paper": "ledger"})}
        with tempfile.TemporaryDirectory() as d:
            out = Path(d, "p.pdf")
            n = pt.render_part("Alto", strips, {"title": "T", "composer": "C D",
                                                "composer_short": "D"}, 400, opts, out)
            doc = pymupdf.open(out)
            self.assertEqual(len(doc), n)
            self.assertGreater(n, 2)
            ml0, mr0, _, mb = pt.page_box(opts, 0, True)
            for i, page in enumerate(doc):
                self.assertEqual((page.rect.width, page.rect.height), (1224.0, 792.0))
                ml, mr, _, _ = pt.page_box(opts, i, True)
                pix = page.get_pixmap(dpi=72)
                ink = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, -1)[..., 0] < 128
                cols = np.where(ink.any(axis=0))[0]
                if i == 0:
                    continue                                    # title page: text only
                self.assertGreaterEqual(cols.min(), int(ml) - 1)    # the spine side margin
                self.assertLessEqual(cols.max(), int(1224 - mr) + 1)
                words = [w for w in page.get_text("words") if "/" in w[4]]
                self.assertEqual(len(words), 1)                 # the folio "n/N"
                cx = (words[0][0] + words[0][2]) / 2
                self.assertAlmostEqual(cx, (ml + 1224 - mr) / 2, delta=2.0)
                self.assertGreater(words[0][3], 792 - mb)       # in the bottom margin
            # recto head at the outer (right) side, verso at the left
            head2 = [w for w in doc[2].get_text("words") if w[4] == "T"][0]
            head1 = [w for w in doc[1].get_text("words") if w[4] == "T"][0]
            self.assertGreater(head2[0], 612)
            self.assertLess(head1[0], 612)

    def test_small_print_offer_is_silent_on_ledger(self):
        rec = lambda mm, w: {"part": "A", "pages": 5, "staff_mm": mm, "width_mm": w}
        data = {"layout": {"paper": "ledger"}, "built": {"parts": [rec(8.0, 8.0)]}}
        self.assertEqual(pt.small_parts(data), [])
        data = {"layout": {}, "built": {"parts": [rec(3.7, 3.7)]}}
        self.assertEqual(len(pt.small_parts(data)), 1)           # letter: as before

    def test_build_ledger_has_no_large_copy_and_workers_match(self):
        with tempfile.TemporaryDirectory() as d:
            pdf = os.path.join(d, "s.pdf")
            make_score_pdf(pdf)
            env = dict(os.environ, PARTITOR_ALLOW_ROOT="1")
            run = lambda *a: subprocess.run([sys.executable, SRC, *a], capture_output=True,
                                            text=True, env=env)
            r = run("detect", pdf, "--dpi", "300")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            pages = {}
            for jobs in ("1", "2"):
                out = Path(d, "s.partitor")
                r = run("build", pdf, "--paper", "ledger", "--jobs", jobs)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertIn("large copy: skipped (paper ledger is already 11x17)", r.stdout)
                names = sorted(p.name for p in Path(out, "parts").iterdir())
                self.assertEqual(names, ["01-Alto.pdf", "02-Tenor.pdf", "03-Bass.pdf"])
                doc = pymupdf.open(Path(out, "parts", "01-Alto.pdf"))
                self.assertEqual((doc[0].rect.width, doc[0].rect.height), (1224.0, 792.0))
                pages[jobs] = doc[0].get_pixmap(dpi=72).samples
            self.assertEqual(pages["1"], pages["2"])             # serial = workers
            r = run("build", pdf, "--paper", "letter")
            self.assertNotIn("large copy: skipped", r.stdout)
            self.assertTrue(Path(d, "s.partitor", "parts", "01-Alto-11x17.pdf").is_file())


@needs_deps
class TestRepage(unittest.TestCase):
    """turns=rest, manual breaks, saved lines and `repage` (0.3.0-dev.37)."""

    OPTS = {**pt.LAYOUT_DEFAULTS, "paper": "letter", "scale": 1.0}

    @staticmethod
    def line(rest=0, bars=(1, 2), movement=False, mark=False, h=300):
        img = np.zeros((h, 400), bool)
        s = pt.Strip(img, 0, 100, 180, 10.0, np.zeros_like(img), movement=movement)
        if rest:
            s = pt.dc_replace(s, rest_src=(None, 0, pt.RestRun(rest, bars[0])))
        else:
            s = pt.dc_replace(s, bar_nums=list(range(bars[0], bars[1] + 1)), bar_no=bars[0])
        if mark:
            s = pt.dc_replace(s, marks=[(0, "A")])
        return s

    def music(self, n=40, rests=()):
        out, bar = [], 1
        for i in range(n):
            if i in rests:
                out.append(self.line(rest=6, bars=(bar, bar + 5)))
                bar += 6
            else:
                out.append(self.line(bars=(bar, bar + 3)))
                bar += 4
        return out

    def test_rest_turn_is_stricter_than_good_turn(self):
        st = [self.line(), self.line(movement=True), self.line(mark=True),
              self.line(rest=6, bars=(9, 14)), self.line(), self.line(rest=1, bars=(20, 20)),
              self.line()]
        self.assertTrue(pt.good_turn(st, 1) and not pt.rest_turn(st, 1))   # movement start
        self.assertTrue(pt.good_turn(st, 2) and not pt.rest_turn(st, 2))   # rehearsal letter
        self.assertTrue(pt.rest_turn(st, 3) and pt.rest_turn(st, 4))       # rest on either side
        self.assertFalse(pt.rest_turn(st, 6))                              # a one-bar rest

    def test_any_is_unchanged_and_rest_turns_only_at_rests(self):
        st = self.music(40, rests={9, 17, 25, 33})
        base, bad0 = pt.plan_pages(st, 400, dict(self.OPTS), False)
        same, _ = pt.plan_pages(st, 400, {**self.OPTS, "turns": "any"}, False)
        self.assertEqual([len(p) for p in base], [len(p) for p in same])
        pages, bad = pt.plan_pages(st, 400, {**self.OPTS, "turns": "rest"}, False)
        self.assertEqual(bad, 0)
        self.assertGreaterEqual(len(pages), 3)
        j = 0
        for c, pg in enumerate(pages[:-1]):
            j += len(pg)
            if (1 + c) % 2 == 1:                     # a turn follows each recto
                self.assertTrue(pt.rest_turn(st, j), f"turn after page {c + 1} at line {j}")

    def test_no_rest_available_counts_turns_while_playing(self):
        st = self.music(40, rests=())
        pages, bad = pt.plan_pages(st, 400, {**self.OPTS, "turns": "rest"}, False)
        self.assertEqual(bad, len(pages[:-1][::2]))          # every recto turn

    def test_manual_break_and_fill(self):
        st = self.music(40, rests={9, 17, 25, 33})
        pages, _ = pt.plan_pages(st, 400, {**self.OPTS, "turns": "rest", "_breaks": [7]}, False)
        ends, j = set(), 0
        for pg in pages:
            j += len(pg)
            ends.add(j)
        self.assertIn(7, ends)
        free = lambda pg: len(pg)                            # noqa: E731
        no_fill_gap = [free(p) for p in pages[:-1]]
        self.assertTrue(all(n >= 2 for n in no_fill_gap))

    def test_break_lines(self):
        st = self.music(10, rests={3})
        js, warns = pt.break_lines(st, [4, 12])
        self.assertEqual(pt.line_bars(st[0]), (1, 4))
        self.assertEqual(js, [1, 3])                        # bars 4 and 12 end lines 0 and 2
        self.assertEqual(warns, [])
        js, warns = pt.break_lines(st, [15])                # inside the rest line (bars 13-18)
        self.assertEqual(js, [])
        self.assertEqual(len(warns), 1)
        self.assertIn("inside a line", warns[0])
        js, warns = pt.break_lines(st, [999])
        self.assertEqual(js, [])
        self.assertIn("no line ends", warns[0])

    def test_set_turns_and_breaks(self):
        data = {"parts": ["Alto", "Bass"], "layout": {}}
        pt.apply_set(data, ["Alto:turns=rest", "Alto:breaks=45,60"])
        self.assertEqual(data["layout"]["parts"]["Alto"], {"turns": "rest", "breaks": [45, 60]})
        pt.apply_set(data, ["Alto:breaks=+50", "Alto:breaks=-45"])
        self.assertEqual(data["layout"]["parts"]["Alto"]["breaks"], [50, 60])
        pt.apply_set(data, ["Alto:breaks=none"])
        self.assertNotIn("breaks", data["layout"]["parts"]["Alto"])
        with self.assertRaises(ValueError):
            pt.apply_set(data, ["breaks=45"])                # per part only
        with self.assertRaises(ValueError):
            pt.apply_set(data, ["Alto:breaks=abc"])
        with self.assertRaises(ValueError):
            pt.apply_set(data, ["turns=sometimes"])

    def test_lines_round_trip_and_safe_load(self):
        st = self.music(5, rests={2})
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp, "x.lines")
            pt.save_lines(f, "Alto", 400, {"title": "T"}, {"paper": "letter", "_x": 1}, st)
            d = pt.load_lines(f)
            self.assertEqual(d["name"], "Alto")
            self.assertNotIn("_x", d["opts"])
            self.assertTrue(all((a.img == b.img).all() for a, b in zip(st, d["strips"])))
            self.assertEqual(d["strips"][2].rest_src[2].bars, 6)
            self.assertEqual(pt.line_bars(d["strips"][2]), (9, 14))
            # a pickle that calls os.system is refused
            import gzip
            import pickle

            class Evil:
                def __reduce__(self):
                    return (os.system, ("true",))
            with gzip.open(Path(tmp, "bad.lines"), "wb") as g:
                pickle.dump({"format": pt.LINES_FORMAT, "x": Evil()}, g)
            with self.assertRaises(ValueError):
                pt.load_lines(Path(tmp, "bad.lines"))
            with self.assertRaises(ValueError):
                pt.load_lines(Path(tmp, "missing.lines"))
            with gzip.open(Path(tmp, "old.lines"), "wb") as g:
                pickle.dump({"format": 0}, g)
            with self.assertRaises(ValueError):
                pt.load_lines(Path(tmp, "old.lines"))

    def test_build_saves_lines_and_repage_replans(self):
        with tempfile.TemporaryDirectory() as tmp:
            one = Path(tmp, "page.pdf")
            make_score_pdf(str(one), systems=2, staves=2, labels=("Alto", "Bass"), title="")
            doc = pymupdf.open()
            for _ in range(6):
                doc.insert_pdf(pymupdf.open(str(one)))
            share = Path(tmp, "share")
            (share / "inbox").mkdir(parents=True)
            item = share / "library" / "2026-10-0001-c-t"
            item.mkdir(parents=True)
            doc.save(str(item / "2026-10-0001-source.pdf"))
            pt.save_item(item, {"id": "2026-10-0001", "slug": "c-t", "created": "2026-10-27"})
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(pt.run_detect(item, None, "T", "C D"), 0)
                d = pt.load_item(item)
                pt.apply_set(d, ["pages=5", "max_staff_mm=8"])
                pt.save_item(item, d)
                self.assertEqual(pt.run_build(item), 0)
            self.assertTrue(any((item / "lines").glob("*.lines")))
            self.assertFalse((item / pt.LINES_NEW).exists())
            before = pt.load_item(item)["built"]["parts"]
            self.assertTrue(all("bad_turns" in r for r in before))
            d = pt.load_item(item)
            pt.apply_set(d, ["Alto:breaks=4"])
            pt.mark_pending(d, "Alto:breaks")
            pt.save_item(item, d)
            buf = io.StringIO()
            old_share = os.environ.get("PARTITOR_LIBRARY")
            os.environ["PARTITOR_LIBRARY"] = str(share)
            try:
                with contextlib.redirect_stdout(buf):
                    rc = pt._engine_step(pt.cmd_repage,
                                         argparse.Namespace(id="2026-10-0001", parts=["Alto"]))
            finally:
                if old_share is None:
                    os.environ.pop("PARTITOR_LIBRARY", None)
                else:
                    os.environ["PARTITOR_LIBRARY"] = old_share
            out = buf.getvalue()
            self.assertEqual(rc, 0, out)
            after = pt.load_item(item)
            self.assertEqual(after["layout"]["parts"]["Alto"]["turns"], "rest")
            self.assertNotIn("Alto:breaks", after.get("pending") or [])
            self.assertTrue((item / "parts.prev").is_dir())
            self.assertEqual({r["part"] for r in after["built"]["parts"]},
                             {r["part"] for r in before})
            for r in after["built"]["parts"]:
                self.assertTrue((item / "parts" / r["file"]).is_file())
            self.assertIn("pages of music", out)

    def test_movement_start_is_second_choice(self):
        st = self.music(40, rests=())
        for i in (8, 16, 24, 32):
            st[i] = self.line(bars=(1, 4), movement=True)
        pages, bad = pt.plan_pages(st, 400, {**self.OPTS, "turns": "rest"}, False)
        self.assertEqual(bad, 0)                      # a movement start is not a turn while playing
        j = 0
        for c, pg in enumerate(pages[:-1]):
            j += len(pg)
            if (1 + c) % 2 == 1:
                self.assertTrue(st[j].movement, f"turn after page {c + 1} at line {j}")
        tl = pt.turn_list(st, pages, False, {**self.OPTS, "turns": "rest"})
        self.assertTrue(all(t["movement"] for t in tl))
        self.assertEqual(pt.count_bad_turns(tl, {"turns": "rest"}), 0)
        self.assertIn("attacca", pt.turn_text({**tl[0], "resting": False}))

    def test_rest_beats_movement_and_letter_is_not_a_turn(self):
        st = self.music(40, rests={9, 17, 25, 33})
        for i in (8, 16, 24, 32):
            st[i] = self.line(bars=(1, 4), movement=True)
        pages, bad = pt.plan_pages(st, 400, {**self.OPTS, "turns": "rest"}, False)
        self.assertEqual(bad, 0)
        j = 0
        for c, pg in enumerate(pages[:-1]):
            j += len(pg)
            if (1 + c) % 2 == 1:
                self.assertTrue(pt.rest_turn(st, j))
        lt = [self.line(bars=(4 * i + 1, 4 * i + 4), mark=(i % 2 == 0)) for i in range(40)]
        _, bad = pt.plan_pages(lt, 400, {**self.OPTS, "turns": "rest"}, False)
        self.assertGreater(bad, 0)                    # letters give no place to turn

    def test_wrapper_lists_every_library_command(self):
        eng = Path(SRC).read_text()
        cmds = set(re.findall(r'"(\w+)": cmd_\w+', eng.split("cmds = {", 1)[1].split("}", 1)[0]))
        run = (Path(SRC).parent.parent / "bin" / "partitor").read_text()
        line = next(ln for ln in run.splitlines() if "needs_lib=1 ;;" in ln and "|" in ln)
        listed = set(line.split(")")[0].strip().split("|"))
        for c in cmds - {"pieces", "detect", "build"}:
            self.assertIn(c, listed, f"bin/partitor does not list {c}")

    def test_partitor_color_gives_colour_without_a_terminal(self):
        code = ("import importlib.machinery as m, importlib.util as u, sys;"
                "l = m.SourceFileLoader('pm', sys.argv[1]);"
                "s = u.spec_from_loader('pm', l); mod = u.module_from_spec(s); sys.modules['pm'] = mod;"
                "l.exec_module(mod); print(repr(mod.BOLD), mod._TTY)")
        for val, want in (("1", ("'\\x1b[1m'", "True")), ("0", ("''", "False")), (None, ("''", "False"))):
            env = {k: v for k, v in os.environ.items() if k != "PARTITOR_COLOR"}
            if val is not None:
                env["PARTITOR_COLOR"] = val
            r = subprocess.run([sys.executable, "-I", "-c", code, SRC], env=env,
                               capture_output=True, text=True, stdin=subprocess.DEVNULL)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stdout.split(), list(want), f"PARTITOR_COLOR={val}")

    def test_repage_without_lines_asks_for_a_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                pt.load_lines(Path(tmp, "none.lines"))
