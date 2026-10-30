# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""Unit and regression tests for partitor (score -> parts).

Needs the venv packages (numpy, opencv, pymupdf, PyYAML). Run with
the venv interpreter:

    venv/bin/python3 -m unittest -v tests/test_partitor.py

Without those packages every test is skipped. tesseract is not needed: the
synthetic pages are vector PDFs, so labels and titles come from the text
layer.

Corpus regression tests (slow, about 15 min) run only when PARTITOR_CORPUS
names a directory with the reference PDFs (see CORPUS below). The PDFs are
not in the repo (copyright).
"""
import argparse
import builtins
import contextlib
import importlib.machinery
import importlib.util
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "lib", "partitor-engine")

try:
    import cv2  # noqa: F401
    import numpy as np
    import pymupdf
    import yaml  # noqa: F401
    _loader = importlib.machinery.SourceFileLoader("partitor_mod", SRC)
    _spec = importlib.util.spec_from_loader("partitor_mod", _loader)
    pt = importlib.util.module_from_spec(_spec)
    sys.modules["partitor_mod"] = pt      # dataclasses look the module up
    _loader.exec_module(pt)
    HAVE_DEPS = True
except ImportError:          # system python without the venv packages
    HAVE_DEPS = False

needs_deps = unittest.skipUnless(HAVE_DEPS, "partitor venv packages not installed")

_LOGO_TMP = None
_LOGO_OLD = None


def make_logo_png(path, w=400, h=457):
    """Write a plain synthetic PNG (aspect about 0.88, like a tall mark) for the logo tests."""
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, w, h), False)
    pix.set_rect(pix.irect, (20, 20, 20))
    pix.save(str(path))


def setUpModule():
    """The logo is optional (PARTITOR_LOGO). Tests run with a synthetic one;
    LogoOptionalTests removes it for single tests."""
    global _LOGO_TMP, _LOGO_OLD
    _LOGO_OLD = os.environ.get("PARTITOR_LOGO")
    if HAVE_DEPS:
        _LOGO_TMP = tempfile.mkdtemp(prefix="pt-logo-")
        make_logo_png(Path(_LOGO_TMP, "logo.png"))
        os.environ["PARTITOR_LOGO"] = str(Path(_LOGO_TMP, "logo.png"))


def tearDownModule():
    if _LOGO_TMP:
        shutil.rmtree(_LOGO_TMP, ignore_errors=True)
    if _LOGO_OLD is None:
        os.environ.pop("PARTITOR_LOGO", None)
    else:
        os.environ["PARTITOR_LOGO"] = _LOGO_OLD


SP = 6.0          # staff space in points for synthetic pages (~33 px at 400 dpi)


def make_score_pdf(path, systems=2, staves=3, curve=0.0, labels=("Alto", "Tenor", "Bass"),
                   title="Test Chorale", lyrics=True, dot=True, connector="solid",
                   extra=None, quiet=()):
    """Write a synthetic one-page vector score. quiet: {(system, staff)}
    drawn with a half-rest block in each bar instead of notes.

    systems x staves, staff lines 6 pt apart, a bracket and system barline,
    barlines, noteheads, one ledger note above staff 1, a staccato dot, a
    lyric row under staff 1, labels left, a title, a page number. curve
    bends every staff line (pt) to test dewarp on a raster copy."""
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    x0, x1 = 110, 560
    y = 170
    tops = []
    for s in range(systems):
        sys_top = y
        for k in range(staves):
            tops.append(y)
            for ln in range(5):
                yy = y + ln * SP
                if curve:
                    pts = [pymupdf.Point(x, yy + curve * np.sin((x - x0) / (x1 - x0) * np.pi))
                           for x in np.linspace(x0, x1, 40)]
                    page.draw_polyline(pts, width=0.6)
                else:
                    page.draw_line((x0, yy), (x1, yy), width=0.6)
            for bx in (x0 + 170, x0 + 310, x1):
                page.draw_line((bx, y), (bx, y + 4 * SP), width=0.8)
            if (s, k) in quiet:
                for a_, b_ in ((x0, x0 + 170), (x0 + 170, x0 + 310), (x0 + 310, x1)):
                    mid = (a_ + b_) / 2
                    page.draw_rect(pymupdf.Rect(mid - 5, y + 2 * SP - 3, mid + 5, y + 2 * SP),
                                   fill=(0, 0, 0))
            else:
                for nx in range(x0 + 40, x1 - 20, 35):
                    cy = y + ((nx // 35) % 5) * SP
                    page.draw_oval(pymupdf.Rect(nx, cy - 2.6, nx + 7.5, cy + 2.6),
                                   fill=(0, 0, 0))
                    page.draw_line((nx + 7.2, cy), (nx + 7.2, cy - 3.3 * SP), width=0.7)
            if s == 0 and k < len(labels):
                page.insert_text((40, y + 2.5 * SP), labels[k], fontsize=9)
            y += 4 * SP + 9 * SP
        sys_bottom = y - 9 * SP
        if connector == "solid":
            page.draw_line((x0, sys_top), (x0, sys_bottom), width=1.0)
            page.draw_rect(pymupdf.Rect(x0 - 6, sys_top - 2, x0 - 3, sys_bottom + 2), fill=(0, 0, 0))
        elif connector == "dotted":
            yy = sys_top
            while yy < sys_bottom:
                page.draw_line((x0, yy), (x0, min(yy + 3, sys_bottom)), width=1.0)
                yy += 5
        y += 8 * SP
    first = tops[0]
    if title:
        page.insert_text((230, first - 70), title, fontsize=20)
    # ledger note above staff 1 (one ledger line 1 sp above the top line)
    page.draw_line((x0 + 200, first - SP), (x0 + 214, first - SP), width=0.6)
    page.draw_oval(pymupdf.Rect(x0 + 203, first - SP - 2.6, x0 + 210.5, first - SP + 2.6),
                   fill=(0, 0, 0))
    if dot:          # staccato dot just above staff 1 (belongs to staff 1)
        page.draw_circle((x0 + 252, first - 0.8 * SP), 0.9, fill=(0, 0, 0))
    if lyrics:       # lyric row in the upper part of the gap under staff 1
        for i, w in enumerate(["Wie", "sich", "ein", "Vater", "er", "barmt"]):
            page.insert_text((x0 + 40 + i * 60, first + 4 * SP + 2.5 * SP), w, fontsize=8)
    page.insert_text((300, 770), "1", fontsize=9)
    if extra:
        extra(page, tops)
    doc.save(path)
    return tops


def rasterize(src, dst, dpi=200, angle=0.0, curve_px=0):
    """Raster copy of a PDF (scan simulation): grey image, optional
    rotation and vertical sine bend, JPEG-free (PNG) for determinism."""
    s = pymupdf.open(src)
    out = pymupdf.open()
    for p in s:
        pix = p.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)
        g = np.frombuffer(pix.samples, np.uint8).reshape(pix.h, pix.w).copy()
        if angle:
            m = cv2.getRotationMatrix2D((pix.w / 2, pix.h / 2), angle, 1)
            g = cv2.warpAffine(g, m, (pix.w, pix.h), borderValue=255)
        if curve_px:
            h, w = g.shape
            mapx = np.tile(np.arange(w, dtype=np.float32), (h, 1))
            mapy = (np.arange(h, dtype=np.float32)[:, None]
                    + curve_px * np.sin(np.arange(w) / w * np.pi)[None, :]).astype(np.float32)
            g = cv2.remap(g, mapx, mapy, cv2.INTER_LINEAR, borderValue=255)
        ok, png = cv2.imencode(".png", g)
        pg = out.new_page(width=p.rect.width, height=p.rect.height)
        pg.insert_image(pg.rect, stream=png.tobytes())
    out.save(dst)


@needs_deps
class TestHelpers(unittest.TestCase):
    def test_parse_pages(self):
        self.assertEqual(pt.parse_pages("3-5", 10), [2, 3, 4])
        self.assertEqual(pt.parse_pages("7", 10), [6])
        self.assertEqual(pt.parse_pages(None, 3), [0, 1, 2])
        with self.assertRaises(ValueError):
            pt.parse_pages("5-3", 10)
        with self.assertRaises(ValueError):
            pt.parse_pages("1-11", 10)
        with self.assertRaises(ValueError):
            pt.parse_pages("x", 10)

    def test_file_part_name(self):
        self.assertEqual(pt.file_part_name("Basso Trombone 1"), "Basso-Trombone-1")
        self.assertEqual(pt.file_part_name("Tenor (II)"), "Tenor-II")
        self.assertEqual(pt.file_part_name("???"), "part")

    def test_workdir_with_pages(self):
        self.assertEqual(pt.workdir(Path("/x/bach.pdf"), None, "8-9").name,
                         "bach.p8-9.partitor")
        self.assertEqual(pt.workdir(Path("/x/bach.pdf"), None).name, "bach.partitor")

    def test_label_match_numbers_must_agree(self):
        self.assertEqual(pt.label_match("Tenore II", "Tenore III Trombone"), 0.0)
        self.assertGreaterEqual(pt.label_match("Tenore II", "Tenore II Trombone"), 0.7)

    def test_label_match_short_forms(self):
        self.assertGreaterEqual(pt.label_match("T1", "Tenor 1"), 0.7)
        self.assertLess(pt.label_match("T1", "Tenor 2"), 0.7)
        self.assertGreaterEqual(pt.label_match("B", "Bass"), 0.7)
        self.assertGreaterEqual(pt.label_match("Alto", "Alto Trombone"), 0.7)

    def test_clean_label_repairs_roman_numerals(self):
        self.assertEqual(pt.clean_label("Tenore I]"), "Tenore II")
        self.assertEqual(pt.clean_label("Tenore II|"), "Tenore III")
        self.assertEqual(pt.clean_label("_ a"), "")
        self.assertEqual(pt.clean_label("[BASSO] TROMBONE"), "BASSO TROMBONE")

    def test_clean_title(self):
        self.assertEqual(pt.clean_title("  Ich will alle meine Tage. "), "Ich will alle meine Tage")
        self.assertEqual(pt.clean_title("|- ."), "")

    def test_clefs_compatible(self):
        self.assertTrue(pt.clefs_compatible(["G", "?", "F"], ["G", "C3", "F"]))
        self.assertFalse(pt.clefs_compatible(["G", "C3"], ["G", "F"]))
        self.assertFalse(pt.clefs_compatible(["G"], ["G", "F"]))


@needs_deps
class TestMapping(unittest.TestCase):
    def rec(self, rid, labels, clefs, braces=None):
        n = len(labels)
        return {"id": rid, "page": 0, "staves": list(range(n)), "labels": labels,
                "clefs": clefs, "braces": braces or [-1] * n}

    def test_reference_numbers_duplicate_labels(self):
        r = self.rec("p1.s1", ["Tenore", "Basso Trombone", "Basso Trombone", "Organo"],
                     ["G", "F", "F", "F"])
        names, _, _ = pt.build_reference([r], [])
        self.assertEqual(names, ["Tenore", "Basso Trombone 1", "Basso Trombone 2", "Organo"])

    def test_reference_parts_override(self):
        r = self.rec("p1.s1", ["x", "y", "z"], ["G", "G", "F"])
        names, _, _ = pt.build_reference([r], ["A", "B", "C"])
        self.assertEqual(names, ["A", "B", "C"])

    def test_reduced_system_by_labels(self):
        full = self.rec("p1.s1", ["Canto", "Alto", "Tenore", "Basso"], ["G", "C3", "C4", "F"])
        red = self.rec("p1.s2", ["Alto", "Basso"], ["C3", "F"])
        names, entries = pt.assign_maps([full, red], [])
        self.assertEqual(entries[1]["map"], ["Alto", "Basso"])

    def test_continuity_without_labels(self):
        full = self.rec("p1.s1", ["Canto", "Alto", "Tenore", "Basso"], ["G", "C3", "C4", "F"])
        red = self.rec("p1.s2", ["Tenore", "Basso"], ["C4", "F"])
        cont = self.rec("p1.s3", ["", ""], ["?", "F"])
        _, entries = pt.assign_maps([full, red, cont], [])
        self.assertEqual(entries[2]["map"], ["Tenore", "Basso"])
        self.assertEqual(entries[2]["why"], "same as previous system")

    def test_reference_by_labels_and_continuo(self):
        parts = ["Violine I", "Violine II", "Viola I", "Viola II", "Canto", "Organo BC"]
        full = self.rec("p1.s1", parts, ["G2", "G2", "C3", "C4", "G2", "F4"])
        # a stray system with one staff more and junk labels must not name the parts
        stray = self.rec("p9.s1", ["", "", "Continuo", "", "", "", "Continuo"],
                         ["G2"] * 6 + ["F4"])
        short = self.rec("p2.s1", ["", "", "Vla I", "Vla II", "Continuo"],
                         ["G2", "G2", "C3", "C4", "F4"])
        names, entries = pt.assign_maps([full, stray, short], [])
        self.assertEqual(names, parts)
        got = entries[2].get("suggest") or entries[2]["map"]
        self.assertEqual(got, ["Violine I", "Violine II", "Viola I", "Viola II", "Organo BC"])
        self.assertEqual(pt.label_match("Continuo", "Organo BC"), 1.0)
        self.assertGreaterEqual(pt.label_match("Vla I", "Viola I"), 0.7)
        self.assertEqual(pt.label_match("Vla I", "Viola II"), 0.0)
        self.assertGreaterEqual(pt.label_match("Cornet", "Cornetto"), 0.7)

    def test_part_goes_on_when_staff_count_changes(self):
        # Schein Nun p6: Canto, Alto, continuo (2 braced) -> 3 staves without
        # labels; the top one is the Alto, not the Bass (bottom alignment)
        parts = ["Canto I", "Canto II", "Alto I", "Alto II", "Tenor", "Bass", "Org", "Cont"]
        full = self.rec("p1.s1", parts, ["G2", "G2", "G2", "C3", "C4", "F4", "G2", "F4"],
                        [-1, -1, -1, -1, -1, -1, 0, 0])
        four = self.rec("p6.s2", ["Canto I", "Alto I", "", ""], ["G2", "G2", "G2", "F4"],
                        [-1, -1, 1, 1])
        three = self.rec("p6.s3", ["", "", ""], ["G2", "G2", "F4"], [-1, 2, 2])
        _, entries = pt.assign_maps([full, four, three], parts)
        got = entries[2].get("suggest") or entries[2]["map"]
        # Canto I and Alto I are both G2 and both in the system before; with
        # no label nothing tells them apart, so either is right here (the
        # operator answers the real case). The test is: not the Bass.
        self.assertIn(got[0], ("Canto I", "Alto I"))
        self.assertEqual(got[1:], ["Org", "Cont"])

    def test_braced_pair_maps_to_braced_slots(self):
        parts = ["Alto I", "Alto II", "Tenor", "Org", "Cont"]
        full = self.rec("p1.s1", parts, ["G2", "C3", "C4", "G2", "F4"], [-1, -1, -1, 0, 0])
        # clefs misread as the trombones' C3 C4; the brace tells the continuo
        red = self.rec("p3.s1", ["Alto I", "", ""], ["G2", "C3", "C4"], [-1, 1, 1])
        _, entries = pt.assign_maps([full, red], parts)
        got = entries[1].get("suggest") or entries[1]["map"]
        self.assertEqual(got, ["Alto I", "Org", "Cont"])

    def test_ambiguous_system_is_question_mark_with_suggestion(self):
        full = self.rec("p1.s1", ["Canto", "Alto", "Tenore", "Basso"], ["?", "?", "?", "?"])
        amb = self.rec("p1.s2", ["", ""], ["?", "?"])
        _, entries = pt.assign_maps([full, amb], [])
        self.assertEqual(entries[1]["map"], ["?", "?"])
        self.assertIn("suggest", entries[1])

    def test_more_staves_than_reference_impossible(self):
        full = self.rec("p1.s1", ["A", "B"], ["G", "F"])
        idx, best, _ = pt.map_system(self.rec("x", ["", "", ""], ["?"] * 3),
                                     ["A", "B"], ["G", "F"], None)
        self.assertEqual(idx, [])
        self.assertEqual(best, float("inf"))
        del full


@needs_deps
class TestConditioning(unittest.TestCase):
    def test_flatten_and_binarize_keep_light_print_on_shaded_paper(self):
        h, w = 600, 800
        bg = np.tile(np.linspace(255, 150, w, dtype=np.float32), (h, 1))   # shading
        g = bg.copy()
        g[100:104, 50:750] = 60            # dark stroke
        g[300:304, 50:750] = bg[300:304, 50:750] * 0.72   # light grey stroke
        g = g.astype(np.uint8)
        ink = pt.binarize(pt.flatten(g))
        self.assertGreater(ink[100:104, 60:740].mean(), 0.95)
        self.assertGreater(ink[300:304, 60:740].mean(), 0.9)
        self.assertLess(ink[400:600].mean(), 0.01)       # no false ink on shading

    def test_union_never_lighter_than_otsu(self):
        rng = np.random.default_rng(3)
        g = np.full((300, 300), 245, np.uint8)
        g[100:104, 20:280] = 40
        g[150:153, 20:280] = 170
        g = np.clip(g.astype(int) + rng.integers(-8, 9, g.shape), 0, 255).astype(np.uint8)
        n = pt.flatten(g)
        ink = pt.binarize(n)
        _, otsu = cv2.threshold(n, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        self.assertTrue(np.all(ink[otsu > 0]))
        self.assertLess(ink[200:300].mean(), 0.005)        # noise stays paper


@needs_deps
class TestStaffTracking(unittest.TestCase):
    def synthetic(self, curve_px):
        h, w = 1600, 2000
        img = np.zeros((h, w), bool)
        sp, th = 24, 3
        for top in (300, 700, 1100):
            for ln in range(5):
                ys = top + ln * sp + curve_px * np.sin(np.arange(w) / w * np.pi)
                for x in range(150, 1850):
                    y = int(round(ys[x]))
                    img[y:y + th, x] = True
        return img, th, sp

    def test_tracks_found_on_bent_staves(self):
        img, th, sp = self.synthetic(14)
        tracks = pt.staff_tracks(img, th, sp)
        self.assertEqual(len(tracks), 3)

    def test_dewarp_straightens(self):
        img, th, sp = self.synthetic(14)
        grey = np.where(img, 0, 255).astype(np.uint8)
        tracks = pt.staff_tracks(img, th, sp)
        out, dmax = pt.dewarp(grey, tracks, img.shape[1], img.shape[0])
        self.assertGreater(dmax, 2)
        ink = out < 128
        rows = [int(np.flatnonzero(ink[250:400, x])[0]) for x in (200, 600, 1000, 1400, 1800)]
        self.assertLessEqual(max(rows) - min(rows), 3, rows)   # was 14 px bent
        staves, _ = pt.detect_staves(ink, th, sp - th, 0)
        self.assertEqual(len(staves), 3)

    def test_straight_page_not_warped(self):
        img, th, sp = self.synthetic(0)
        grey = np.where(img, 0, 255).astype(np.uint8)
        out, dmax = pt.dewarp(grey, pt.staff_tracks(img, th, sp), img.shape[1], img.shape[0])
        self.assertEqual(dmax, 0.0)
        self.assertIs(out, grey)

    def test_staff_extent_ignores_label_text(self):
        img, th, sp = self.synthetic(0)
        # "label" blocks on two line rows left of the staff (bridged text)
        img[300:306, 20:140] = True
        img[348:354, 20:140] = True
        staves, _ = pt.detect_staves(img, th, sp - th, 0)
        self.assertEqual(len(staves), 3)
        self.assertGreaterEqual(staves[0].x0, 145)

    def test_group_systems_gap_clustering(self):
        st = [pt.Staff(0, i, [t + k * 24 for k in range(5)], 100, 1800)
              for i, t in enumerate((100, 300, 500, 900, 1100, 1300))]
        ink = np.zeros((1500, 1900), bool)
        groups = pt.group_systems(ink, st, 24, 3)
        self.assertEqual([len(g) for g in groups], [3, 3])

    def test_group_systems_dotted_connector(self):
        st = [pt.Staff(0, i, [t + k * 24 for k in range(5)], 100, 1800)
              for i, t in enumerate((100, 300))]
        ink = np.zeros((600, 1900), bool)
        for y in range(196, 300, 6):           # dotted vertical line, 50% ink
            ink[y:y + 3, 100:103] = True
        self.assertEqual([len(g) for g in pt.group_systems(ink, st, 24, 3)], [2])


@needs_deps
class TestPageAnalysis(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.vec = os.path.join(cls.tmp.name, "score.pdf")
        cls.tops = make_score_pdf(cls.vec)
        cls.res = pt.analyse_page(pymupdf.open(cls.vec)[0], 0, 400, 0)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_staves_and_systems(self):
        self.assertEqual(len(self.res.staves), 6)
        self.assertEqual([len(g) for g in self.res.systems], [3, 3])

    def test_one_start_per_system(self):
        for grp in self.res.systems:
            self.assertEqual(len({s.x0 for s in grp}), 1)

    def test_barlines_found_and_clef_zone_ignored(self):
        # synthetic score: barlines at x0+150, x0+300 and the end per staff
        k = 400 / 72.0
        for g, xs in self.res.barlines.items():
            self.assertEqual(len(xs), 3, xs)
            self.assertAlmostEqual(xs[0] / k, 110 + 170, delta=3)

    def test_no_silent_loss(self):
        self.assertEqual(self.res.gate, [])
        o = self.res.owner
        self.assertEqual(int((o == pt.OWN_NONE).sum()), o.size - self.res.ink_px)
        self.assertNotIn(pt.OWN_DISCARD, self.res.discard)

    def test_labels_and_title_from_text_layer(self):
        self.assertEqual([s.label for s in self.res.staves[:3]], ["Alto", "Tenor", "Bass"])
        self.assertEqual(self.res.title, "Test Chorale")

    def test_lyrics_belong_to_staff_above(self):
        k = 400 / 72.0
        st0 = self.res.staves[0]
        y = int((self.tops[0] + 4 * SP + 2.5 * SP - 3) * k)
        row = self.res.owner[y - 10:y + 10, int(150 * k):int(500 * k)]
        vals = row[row != pt.OWN_NONE]
        self.assertGreater(vals.size, 50)
        self.assertTrue(np.all(vals == 0), set(np.unique(vals).tolist()))
        del st0

    def test_ledger_note_and_dot_belong_to_staff_1(self):
        k = 400 / 72.0
        y = int((self.tops[0] - SP) * k)
        blk = self.res.owner[y - 12:y + 12, int(313 * k):int(321 * k)]
        vals = blk[blk != pt.OWN_NONE]
        self.assertTrue(vals.size > 0 and np.all(vals == 0))
        yd = int((self.tops[0] - 0.8 * SP) * k)
        dot = self.res.owner[yd - 6:yd + 6, int(361 * k):int(363 * k) + 1]
        self.assertTrue(np.all(dot[dot != pt.OWN_NONE] == 0))

    def test_page_number_and_title_discarded_by_class(self):
        self.assertIn(pt.D_FOOTER, self.res.discard)
        self.assertIn(pt.D_HEADER, self.res.discard)

    def test_no_music_page(self):
        p = os.path.join(self.tmp.name, "text.pdf")
        d = pymupdf.open()
        pg = d.new_page()
        pg.insert_text((72, 100), "Introduction", fontsize=20)
        d.save(p)
        r = pt.analyse_page(pymupdf.open(p)[0], 0, 200, 0, ocr=False)
        self.assertFalse(r.music)
        self.assertEqual(r.gate, [])


@needs_deps
class TestSystemWindow(unittest.TestCase):
    """Ink outside a system's x-range is never a staff's: bracket pieces at
    the left, page edge at the right; dotted Mensurstriche in the gaps are
    connectors."""
    X0, X1 = 110, 560

    @classmethod
    def make_pdf(cls, folder):
        """The test page of this class (also used by other tests)."""
        pdf = os.path.join(folder, "w.pdf")
        cls._extra_pdf(pdf)
        return pdf

    @classmethod
    def _extra_pdf(cls, pdf):
        def extra(page, tops):
            t = tops[0]
            # bracket piece in staff 1 only, 4 pt left of the start
            page.draw_line((cls.X0 - 4, t), (cls.X0 - 4, t + 4 * SP), width=1.2)
            # stroke from the music into the right margin, above staff 1
            page.draw_line((cls.X1 - 30, t - 0.6 * SP), (cls.X1 + 40, t - 0.6 * SP), width=0.8)
            # dotted Mensurstrich at x0+230 in both gaps of system 1
            for a, b in zip(tops[0:2], tops[1:3]):
                yy = a + 4 * SP + 1
                while yy < b - 1:
                    page.draw_line((cls.X0 + 230, yy), (cls.X0 + 230, min(yy + 3, b - 1)),
                                   width=0.8)
                    yy += 5
        return make_score_pdf(pdf, extra=extra, lyrics=False)

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.pdf = os.path.join(cls.tmp.name, "w.pdf")
        cls.tops = cls._extra_pdf(cls.pdf)
        cls.res = pt.analyse_page(pymupdf.open(cls.pdf)[0], 0, 400, 0)
        cls.k = 400 / 72.0

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def px(self, x, y):
        return int(round(x * self.k)), int(round(y * self.k))

    def test_bracket_piece_left_of_start(self):
        x, y = self.px(self.X0 - 4, self.tops[0] + 1.5 * SP)
        blk = self.res.owner[y - 2:y + 3, x - 4:x + 5]
        self.assertTrue(np.isin(blk, (pt.D_BRACKET, pt.D_LABEL)).any())
        self.assertFalse(((blk >= 0) & (blk < len(self.res.staves))).any())

    def test_ink_past_right_end_is_edge_and_music_part_kept(self):
        o = self.res.owner
        x, y = self.px(self.X1 + 30, self.tops[0] - 0.6 * SP)
        self.assertTrue((o[y - 3:y + 4, x - 2:x + 3] == pt.D_EDGE).any())
        x, y = self.px(self.X1 - 20, self.tops[0] - 0.6 * SP)
        self.assertTrue((o[y - 3:y + 4, x - 2:x + 3] == 0).any())

    def test_mensurstrich_counted_and_gaps_not_owned(self):
        g = self.res.staves[0].system
        self.assertEqual(len(self.res.barlines[g]), 4, self.res.barlines[g])
        self.assertEqual(len(self.res.mensur[g]), 1, self.res.mensur)
        x, _ = self.px(self.X0 + 230, 0)
        _, y0 = self.px(0, self.tops[0] + 4 * SP + 2)
        _, y1 = self.px(0, self.tops[1] - 2)
        col = self.res.owner[y0:y1, x - 4:x + 5]
        ink = col != pt.OWN_NONE
        self.assertTrue(ink.any())
        self.assertFalse(((col >= 0) & (col < len(self.res.staves)) & ink).any())

    def test_no_gate(self):
        self.assertEqual(self.res.gate, [])


@needs_deps
class TestScanPath(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        vec = os.path.join(cls.tmp.name, "score.pdf")
        make_score_pdf(vec, labels=("", "", ""), title="")
        cls.scan = os.path.join(cls.tmp.name, "scan.pdf")
        rasterize(vec, cls.scan, dpi=200, angle=0.8, curve_px=9)
        cls.res = pt.analyse_page(pymupdf.open(cls.scan)[0], 0, 400, 0, ocr=False)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_skew_and_bend_corrected(self):
        # deskew takes part of the 0.8 deg; band tracking (dewarp) takes the
        # rest together with the 9 px bend
        self.assertGreater(abs(self.res.skew), 0.1)
        self.assertGreater(self.res.dewarp, 3)

    def test_all_staves_found_no_gate(self):
        self.assertEqual(len(self.res.staves), 6)
        self.assertEqual(self.res.gate, [])


@needs_deps
class TestSafetyGate(unittest.TestCase):
    def test_staff_in_discard_fails(self):
        h, w = 800, 1600
        owner = np.full((h, w), pt.OWN_NONE, np.int32)
        for ln in range(5):
            owner[300 + ln * 24:303 + ln * 24, 100:1500] = pt.D_HEADER
        res = pt.PageResult(0, (h, w), 24.0, 3, 0.0, 0.0, [], [], owner,
                            ink_px=int((owner != pt.OWN_NONE).sum()))
        pt._gate_discards(res, owner != pt.OWN_NONE, 3, 24.0)
        self.assertTrue(any("staff-like lines in discarded ink" in g for g in res.gate))

    def test_unclassified_discard_fails(self):
        owner = np.full((50, 50), pt.OWN_NONE, np.int32)
        owner[10:20, 10:20] = pt.OWN_DISCARD
        res = pt.PageResult(0, (50, 50), 24.0, 3, 0.0, 0.0, [], [], owner, ink_px=100)
        pt._finish_discard(res)
        self.assertTrue(any("unclassified" in g for g in res.gate))

    def test_ink_without_owner_fails(self):
        owner = np.full((50, 50), pt.OWN_NONE, np.int32)
        res = pt.PageResult(0, (50, 50), 24.0, 3, 0.0, 0.0, [], [], owner, ink_px=10)
        pt._finish_discard(res)
        self.assertIn("ink without owner", res.gate)


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
class TestCommands(unittest.TestCase):
    def run_cli(self, *args):
        # the engine refuses root (a test harness may run as root); these are
        # synthetic PDFs, so the opt-in is safe here
        env = dict(os.environ, PARTITOR_ALLOW_ROOT="1")
        return subprocess.run([sys.executable, SRC, *args], capture_output=True, text=True,
                              env=env)

    def test_detect_and_build_end_to_end(self):
        with tempfile.TemporaryDirectory() as d:
            pdf = os.path.join(d, "s.pdf")
            make_score_pdf(pdf)
            r = self.run_cli("detect", pdf, "--dpi", "300")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            lay = yaml.safe_load(Path(d, "s.partitor", "layout.yaml").read_text())
            self.assertEqual(lay["parts"], ["Alto", "Tenor", "Bass"])
            self.assertEqual(lay["layout"], {})     # defaults are not frozen in
            self.assertEqual(lay["title"], "Test Chorale")
            self.assertTrue(all("?" not in s["map"] for s in lay["systems"]))
            r = self.run_cli("build", pdf, "--ink", "darker")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            parts = sorted(p.name for p in Path(d, "s.partitor", "parts").iterdir())
            self.assertEqual(parts, ["01-Alto-11x17.pdf", "01-Alto.pdf", "02-Tenor-11x17.pdf",
                                     "02-Tenor.pdf", "03-Bass-11x17.pdf", "03-Bass.pdf"])

    def test_build_refuses_bad_margins(self):
        with tempfile.TemporaryDirectory() as d:
            pdf = os.path.join(d, "s.pdf")
            make_score_pdf(pdf)
            self.assertEqual(self.run_cli("detect", pdf, "--dpi", "200").returncode, 0)
            r = self.run_cli("build", pdf, "--gutter", "30")
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("outer margin", r.stdout + r.stderr)

    def test_build_refuses_question_marks(self):
        with tempfile.TemporaryDirectory() as d:
            pdf = os.path.join(d, "s.pdf")
            make_score_pdf(pdf)
            self.assertEqual(self.run_cli("detect", pdf, "--dpi", "300").returncode, 0)
            lp = Path(d, "s.partitor", "layout.yaml")
            lay = yaml.safe_load(lp.read_text())
            lay["systems"][1]["map"] = ["?", "?", "?"]
            lp.write_text(yaml.safe_dump(lay))
            r = self.run_cli("build", pdf)
            self.assertEqual(r.returncode, 1)
            self.assertIn("map:", r.stdout)

    def test_pieces_lists_pages(self):
        with tempfile.TemporaryDirectory() as d:
            pdf = os.path.join(d, "s.pdf")
            make_score_pdf(pdf)
            r = self.run_cli("pieces", pdf)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("Test Chorale", r.stdout)
            self.assertIn("--pages 1", r.stdout)

    def test_detect_page_range_out_of_bounds(self):
        with tempfile.TemporaryDirectory() as d:
            pdf = os.path.join(d, "s.pdf")
            make_score_pdf(pdf)
            r = self.run_cli("detect", pdf, "--pages", "2-3")
            self.assertEqual(r.returncode, 1)


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


@needs_deps
class TestSafeBuild(unittest.TestCase):
    """A build writes parts.new/ and replaces parts/ only when it succeeds."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.item = Path(self.tmp.name, "2026-10-0004-x")
        self.item.mkdir()
        pt.save_item(self.item, {"id": "2026-10-0004", "slug": "x", "composer": "Schein",
                                 "title": "Nun", "parts": ["A"], "layout": {}})
        (self.item / "2026-10-0004-source.pdf").write_bytes(b"%PDF")
        self.real = pt.cmd_build
        self.mode = "ok"
        self.calls = 0
        pt.cmd_build = self.fake

    def tearDown(self):
        pt.cmd_build = self.real
        self.tmp.cleanup()

    def fake(self, ns):
        self.calls += 1
        d = Path(ns.parts_dir)
        d.mkdir(exist_ok=True)
        (d / f"01-a-gen{self.calls}.pdf").write_bytes(b"x")
        if self.mode == "fail":
            return 1
        if self.mode == "kill":
            raise KeyboardInterrupt
        pt.LAST_BUILD.clear()
        pt.LAST_BUILD.append({"part": "A", "pages": 2, "content_pages": 2, "staff_mm": 6.0,
                              "staff_max_mm": 6.0, "width_mm": 6.0, "gap": 10.0,
                              "file": f"01-a-gen{self.calls}.pdf"})
        return 0

    def names(self, sub="parts"):
        d = self.item / sub
        return sorted(p.name for p in d.iterdir()) if d.is_dir() else None

    def build(self):
        with open(os.devnull, "w") as dn, contextlib.redirect_stdout(dn):
            return pt.run_build(self.item)

    def test_first_build_makes_parts_and_no_stage(self):
        self.assertEqual(self.build(), 0)
        self.assertEqual(self.names(), ["01-a-gen1.pdf"])
        self.assertIsNone(self.names("parts.new"))
        self.assertIsNone(self.names("parts.prev"))
        self.assertEqual(pt.load_item(self.item)["built"]["parts"][0]["file"], "01-a-gen1.pdf")

    def test_second_build_keeps_the_set_before_and_drops_the_older(self):
        self.build()
        self.build()
        self.assertEqual(self.names(), ["01-a-gen2.pdf"])
        self.assertEqual(self.names("parts.prev"), ["01-a-gen1.pdf"])
        self.build()
        self.assertEqual(self.names("parts.prev"), ["01-a-gen2.pdf"])      # one generation back

    def test_failed_build_leaves_parts_and_built_as_they_were(self):
        self.build()
        self.mode = "fail"
        self.assertEqual(self.build(), 1)
        self.assertEqual(self.names(), ["01-a-gen1.pdf"])
        self.assertEqual(self.names("parts.new"), ["01-a-gen2.pdf"])        # partial, for a look
        self.assertEqual(pt.load_item(self.item)["built"]["parts"][0]["file"], "01-a-gen1.pdf")
        self.mode = "ok"                                                     # the next build cleans up
        self.build()
        self.assertEqual(self.names(), ["01-a-gen3.pdf"])
        self.assertIsNone(self.names("parts.new"))

    def test_killed_build_leaves_parts(self):
        self.build()
        self.mode = "kill"
        with self.assertRaises(KeyboardInterrupt):
            self.build()
        self.assertEqual(self.names(), ["01-a-gen1.pdf"])

    def test_recover_after_a_stop_between_the_renames(self):
        self.build()
        self.build()
        os.replace(self.item / "parts", self.item / "gone")      # parts missing, prev + stage left
        (self.item / "parts.new").mkdir()
        with open(os.devnull, "w") as dn, contextlib.redirect_stdout(dn):
            pt.recover_parts(self.item)
        self.assertEqual(self.names(), ["01-a-gen1.pdf"])

    def test_restore_previous_parts(self):
        self.assertFalse(pt.restore_previous_parts(self.item))
        self.build()
        self.build()
        self.assertTrue(pt.restore_previous_parts(self.item))
        self.assertEqual(self.names(), ["01-a-gen1.pdf"])
        self.assertIsNone(self.names("parts.prev"))

    def test_reflow_undo_restores_the_old_parts_without_a_second_build(self):
        self.build()
        data = pt.load_item(self.item)
        data["built"]["parts"][0]["staff_mm"] = 4.0               # small print: re-flow is offered
        data["built"]["parts"][0]["width_mm"] = 4.0
        pt.save_item(self.item, data)
        answers = iter(["y", "n"])                                # try re-flow; keep it: no
        real = builtins.input
        builtins.input = lambda prompt="": next(answers)
        try:
            with open(os.devnull, "w") as dn, contextlib.redirect_stdout(dn):
                pt.offer_reflow(self.item)
        finally:
            builtins.input = real
        self.assertEqual(self.calls, 2)                           # the first build and the trial only
        self.assertEqual(self.names(), ["01-a-gen1.pdf"])         # the old set is back
        d = pt.load_item(self.item)
        self.assertEqual(d["layout"].get("reflow", "off"), "off")
        self.assertEqual(d["built"]["parts"][0]["file"], "01-a-gen1.pdf")
        self.assertNotIn("pending", d)

    def test_reflow_offer_is_off_by_default_and_on_by_setting(self):
        self.assertEqual(pt.LAYOUT_DEFAULTS["reflow_offer"], "off")
        self.build()
        data = pt.load_item(self.item)
        data["built"]["parts"][0]["staff_mm"] = 4.0               # small print
        data["built"]["parts"][0]["width_mm"] = 4.0
        pt.save_item(self.item, data)

        def run():
            asked = []
            real = builtins.input
            builtins.input = lambda prompt="": asked.append(prompt) or "n"
            try:
                with open(os.devnull, "w") as dn, contextlib.redirect_stdout(dn):
                    pt.maybe_offer_reflow(self.item)
            finally:
                builtins.input = real
            return asked
        self.assertEqual(run(), [])                               # default: no question
        d = pt.load_item(self.item)
        pt.apply_set(d, ["reflow_offer=on"])
        pt.save_item(self.item, d)
        self.assertEqual(len(run()), 1)                           # on: "Try re-flow?"

    def test_reflow_failed_trial_keeps_parts_and_resets_the_setting(self):
        self.build()
        data = pt.load_item(self.item)
        data["built"]["parts"][0]["staff_mm"] = 4.0
        data["built"]["parts"][0]["width_mm"] = 4.0
        pt.save_item(self.item, data)
        self.mode = "fail"
        answers = iter(["y"])
        real = builtins.input
        builtins.input = lambda prompt="": next(answers)
        try:
            with open(os.devnull, "w") as dn, contextlib.redirect_stdout(dn):
                pt.offer_reflow(self.item)
        finally:
            builtins.input = real
        self.assertEqual(self.calls, 2)                           # no rebuild to undo
        self.assertEqual(self.names(), ["01-a-gen1.pdf"])
        self.assertEqual(pt.load_item(self.item)["layout"].get("reflow", "off"), "off")


@needs_deps
class TestSelection(unittest.TestCase):
    """rebuild <id> [parts]: which parts and groups a build is asked for."""

    DATA = {"parts": ["Canto", "Alto", "Tenor", "Bass Trombone", "Continuo"],
            "skip": ["Continuo"], "groups": {"Trombones": ["Tenor", "Bass Trombone"]}}

    def p(self, *words):
        return pt.parse_parts(self.DATA, list(words))

    def test_numbers_ranges_and_names(self):
        # numbers are those of the part files and of `show`: parts, then groups
        self.assertEqual(self.p("6"), ["Trombones"])
        self.assertEqual(self.p("2-3"), ["Alto", "Tenor"])
        self.assertEqual(self.p("3,1"), ["Canto", "Tenor"])              # file order, once each
        self.assertEqual(self.p("trombones"), ["Trombones"])
        self.assertEqual(self.p("Bass", "Trombone", "Alto"), ["Alto", "Bass Trombone"])
        self.assertEqual(self.p("Can"), ["Canto"])                         # a start no other name has
        self.assertEqual(self.p("Alto", "2"), ["Alto"])

    def test_all_and_everything_are_a_full_build(self):
        self.assertIsNone(self.p("all"))
        self.assertIsNone(self.p("1-4", "Trombones"))

    def test_errors_name_the_problem(self):
        for words, text in ((("7",), "no part number 7"), (("Tenorr",), "no part or group"),
                            (("T",), "more than one"), (("5",), "not extracted"),
                            (("4-2",), "backwards"), ((), "no part named")):
            with self.subTest(words=words):
                with self.assertRaises(ValueError) as cm:
                    self.p(*words)
                self.assertIn(text, str(cm.exception))

    def test_numbers_keep_not_extracted_parts(self):
        d = {**self.DATA, "skip": ["Alto"]}
        self.assertEqual(pt.parse_parts(d, ["3"]), ["Tenor"])             # NN as in the file name
        self.assertIn("2 Alto (not extracted)", pt.selection_help(d))
        self.assertIn("6 Trombones (group)", pt.selection_help(d))

    def test_job_count(self):
        env = dict(os.environ)
        try:
            os.environ["PARTITOR_MEMORY_MAX"] = "8G"
            os.environ.pop("PARTITOR_JOBS", None)
            cpus = (len(os.sched_getaffinity(0))
                    if hasattr(os, "sched_getaffinity")
                    else (os.cpu_count() or 1))
            self.assertEqual(pt.job_count(None, 1.5, 1), 1)                  # one item: no workers
            self.assertEqual(pt.job_count("3", 1.5, 10), 3)                  # a number is taken as it is
            self.assertEqual(pt.job_count("9", 1.5, 4), 4)                   # never more than the items
            self.assertEqual(pt.job_count("1", 1.5, 10), 1)
            self.assertEqual(pt.job_count(None, 1.5, 10), max(1, min(cpus - 1, 4)))   # (8-2)/1.5
            os.environ["PARTITOR_MEMORY_MAX"] = "3G"
            self.assertEqual(pt.job_count("auto", 1.5, 10), 1)               # the cap holds one
            os.environ["PARTITOR_JOBS"] = "2"
            self.assertEqual(pt.job_count(None, 1.5, 10), 2)
            self.assertEqual(pt.parse_size("1500M"), 1500 * 1024 ** 2)
            self.assertIsNone(pt.parse_size("infinity"))
        finally:
            os.environ.clear()
            os.environ.update(env)


@needs_deps
class TestForkMap(unittest.TestCase):
    """Workers: order, replayed output, failures."""

    def run_map(self, fn, items, jobs):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            out = list(pt.fork_map(fn, items, jobs))
        return out, buf.getvalue()

    def setUp(self):
        self.counts = dict(pt._counts)

    def tearDown(self):
        pt._reset_counts()

    def test_results_in_order_with_their_output_and_counts(self):
        def fn(i):
            time.sleep(0.05 * (4 - i))            # the last item ends first
            pt._ok(f"item {i}")
            if i == 2:
                pt._warn("two")
            return i * i
        pt._reset_counts()
        out, text = self.run_map(fn, range(4), 3)
        self.assertEqual(out, [0, 1, 4, 9])
        self.assertEqual([l.split()[-1] for l in text.splitlines()], ["0", "1", "2", "two", "3"])
        self.assertEqual((pt._counts["pass"], pt._counts["warn"]), (4, 1))
        self.assertEqual(pt._WARNINGS, ["two"])

    def test_children_work_after_the_parent_used_opencv_threads(self):
        # A fork copies OpenCV's thread pool without its threads: a child that
        # then used OpenCV waited for ever once (cv2 setNumThreads in the child
        # of a process that had analysed before). Timing decides, so this is a
        # guard, not a proof; fork_map stops the pool in the parent before it forks.
        import signal as sg
        img = (np.random.rand(3000, 3000) * 255).astype(np.uint8)
        cv2.setNumThreads(4)
        expected_threads = cv2.getNumThreads()
        cv2.GaussianBlur(img, (0, 0), 3)                  # the parent starts the pool

        def fn(i):
            return int(cv2.GaussianBlur(img, (0, 0), 3).sum() % 7) + i * 0

        def late(*_):
            raise AssertionError("worker hangs")
        sg.signal(sg.SIGALRM, late)
        sg.alarm(60)
        try:
            out, _ = self.run_map(fn, range(3), 2)
        finally:
            sg.alarm(0)
        self.assertEqual(len(out), 3)
        self.assertEqual(cv2.getNumThreads(), expected_threads)  # pool size restored to what this build accepted

    def test_one_job_runs_here(self):
        pid = os.getpid()
        out, _ = self.run_map(lambda i: os.getpid() == pid, range(3), 1)
        self.assertEqual(out, [True] * 3)
        out, _ = self.run_map(lambda i: os.getpid() == pid, range(3), 2)
        self.assertEqual(out, [False] * 3)

    def test_a_failing_worker_raises_with_its_traceback(self):
        def fn(i):
            if i == 1:
                raise KeyError("boom")
            return i
        with self.assertRaises(RuntimeError) as cm:
            self.run_map(fn, range(3), 2)
        self.assertIn("KeyError", str(cm.exception))
        self.assertIn("item 2 of 3", str(cm.exception))

    def test_die_in_a_worker_ends_the_run(self):
        def fn(i):
            if i == 1:
                raise SystemExit(1)
            return i
        with self.assertRaises(SystemExit):
            self.run_map(fn, range(3), 2)

    def test_a_killed_worker_is_named(self):
        def fn(i):
            if i == 1:
                os.kill(os.getpid(), 9)
            return i
        with self.assertRaises(RuntimeError) as cm:
            self.run_map(fn, range(3), 2)
        self.assertIn("killed by SIGKILL", str(cm.exception))
        self.assertIn("PARTITOR_MEMORY_MAX", str(cm.exception))

    def test_closing_early_stops_the_workers_and_cleans_up(self):
        def tmp_dirs():
            return {d for d in os.listdir(tempfile.gettempdir()) if d.startswith("partitor-")}
        before = tmp_dirs()
        t = time.monotonic()
        with contextlib.redirect_stdout(io.StringIO()):
            gen = pt.fork_map(lambda i: i if i == 0 else (time.sleep(30), i)[1], range(3), 2)
            self.assertEqual(next(gen), 0)
            gen.close()                      # item 1 still sleeps: its worker is stopped
        self.assertLess(time.monotonic() - t, 5)
        self.assertEqual(tmp_dirs(), before)


@needs_deps
class TestPartialBuild(unittest.TestCase):
    """A build of some parts replaces only those; the other files stay."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.item = Path(self.tmp.name, "2026-10-0004-x")
        self.item.mkdir()
        self.tail = "-Schein-Nun--2026-10-0004"
        names = ["A", "B", "C"]
        pt.save_item(self.item, {"id": "2026-10-0004", "slug": "x", "composer": "Schein",
                                 "title": "Nun", "parts": names, "groups": {"G": ["B", "C"]},
                                 "layout": {}})
        (self.item / "2026-10-0004-source.pdf").write_bytes(b"%PDF")
        self.real = pt.cmd_build
        self.gen = 0
        self.asked = []
        pt.cmd_build = self.fake
        self.build()                                           # the first, full build

    def tearDown(self):
        pt.cmd_build = self.real
        self.tmp.cleanup()

    def fake(self, ns):
        """A build that writes one file per part asked for (all when only is None)."""
        self.gen += 1
        self.asked.append(ns.only)
        d = Path(ns.parts_dir)
        d.mkdir(exist_ok=True)
        pt.LAST_BUILD.clear()
        data = pt.load_item(self.item)
        for num, nm in pt.build_names(data):
            if ns.only and nm not in ns.only:
                continue
            fn = pt.part_file_name(num, nm, ns.tail)
            (d / fn).write_bytes(f"g{self.gen}".encode())            # the generation is the content
            (d / fn.replace(".pdf", "-11x17.pdf")).write_bytes(f"g{self.gen}".encode())
            pt.LAST_BUILD.append({"part": nm, "pages": 2, "content_pages": 2, "staff_mm": 6.0,
                                  "staff_max_mm": 6.0, "width_mm": 6.0, "gap": 10.0,
                                  "file": fn, "large": fn.replace(".pdf", "-11x17.pdf")})
        return 0

    def build(self, only=None):
        with open(os.devnull, "w") as dn, contextlib.redirect_stdout(dn):
            return pt.run_build(self.item, only)

    def files(self, sub="parts"):
        return sorted(p.name for p in (self.item / sub).iterdir())

    def gens(self, sub="parts"):
        """{part file: generation that wrote it}, large copies left out."""
        return {f.split("--")[0]: (self.item / sub / f).read_text()
                for f in self.files(sub) if "11x17" not in f}

    def test_only_the_asked_parts_are_new_and_the_others_stay(self):
        self.build()                                           # full again: generation 2 everywhere
        self.assertEqual(set(self.gens().values()), {"g2"})
        self.assertEqual(self.build(["B"]), 0)
        self.assertEqual(self.gens(), {"01-a-Schein-Nun": "g2", "02-b-Schein-Nun": "g3",
                                       "03-c-Schein-Nun": "g2", "04-g-Schein-Nun": "g2"})
        self.assertEqual(len(self.files()), 8)                 # four parts, four large copies
        self.assertEqual(self.asked[-1], ["B"])
        built = pt.load_item(self.item)["built"]["parts"]
        self.assertEqual([r["part"] for r in built], ["A", "B", "C", "G"])    # file order kept
        self.assertEqual(set(self.gens("parts.prev").values()), {"g2"})       # the whole old set
        self.assertEqual(len(self.files("parts.prev")), 8)
        self.assertIsNone(pt.load_item(self.item).get("pending"))

    def test_pending_of_the_built_parts_goes_the_others_stay(self):
        d = pt.load_item(self.item)
        pt.mark_pending(d, "B:gap", "A:pages", "paper")
        pt.save_item(self.item, d)
        self.build(["B"])
        self.assertEqual(pt.load_item(self.item)["pending"], ["A:pages", "paper"])
        self.build(["A"])
        self.assertEqual(pt.load_item(self.item)["pending"], ["paper"])
        self.build()
        self.assertNotIn("pending", pt.load_item(self.item))

    def test_a_group_alone(self):
        self.build(["G"])
        self.assertEqual(self.asked[-1], ["G"])
        self.assertEqual(sorted(self.gens().values()), ["g1", "g1", "g1", "g2"])

    def test_a_changed_file_name_builds_everything(self):
        d = pt.load_item(self.item)
        d["title"] = "Neu"
        pt.save_item(self.item, d)
        self.build(["A"])
        self.assertIsNone(self.asked[-1])                      # whole set: the others' names change
        self.assertTrue(all("Neu" in f for f in self.files()))

    def test_a_missing_file_builds_everything(self):
        os.unlink(self.item / "parts" / pt.load_item(self.item)["built"]["parts"][2]["file"])
        self.build(["A"])
        self.assertIsNone(self.asked[-1])

    def test_nothing_built_yet_builds_everything(self):
        shutil.rmtree(self.item / "parts")
        shutil.rmtree(self.item / "parts.prev", ignore_errors=True)
        d = pt.load_item(self.item)
        d.pop("built")
        pt.save_item(self.item, d)
        self.build(["A"])
        self.assertIsNone(self.asked[-1])
        self.assertEqual(len(self.files()), 8)

    def test_a_failed_partial_build_leaves_parts_as_they_were(self):
        before = self.files()
        pt.cmd_build = lambda ns: 1
        self.assertEqual(self.build(["B"]), 1)
        self.assertEqual(self.files(), before)

    def test_menu_r_with_words(self):
        calls = []
        real = pt.cmd_rebuild
        pt.cmd_rebuild = lambda ns: calls.append((ns.parts, ns.jobs)) or 0
        answers = iter(["r Trombones 2-3", "R", "b"])
        real_in = builtins.input
        builtins.input = lambda prompt="": next(answers)
        try:
            with open(os.devnull, "w") as dn, contextlib.redirect_stdout(dn):
                pt.item_menu(self.item)
        finally:
            builtins.input = real_in
            pt.cmd_rebuild = real
        self.assertEqual(calls, [(["Trombones", "2-3"], None), ([], None)])


@needs_deps
class TestPartialBuildReal(unittest.TestCase):
    """The real engine on a 3-page synthetic score: parallel = serial, a build of one
    part gives the same part as a full build, pages without it are not analysed."""

    def test_workers_and_one_part_give_the_same_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            one = Path(tmp, "page.pdf")
            make_score_pdf(str(one), systems=1, staves=2, labels=("Alto", "Bass"), title="")
            doc = pymupdf.open()
            for _ in range(3):
                doc.insert_pdf(pymupdf.open(str(one)))
            item = Path(tmp, "2026-10-0001-c-t")
            item.mkdir()
            doc.save(str(item / "2026-10-0001-source.pdf"))
            pt.save_item(item, {"id": "2026-10-0001", "slug": "c-t", "created": "2026-10-26"})
            quiet = contextlib.redirect_stdout(io.StringIO())
            env = os.environ.get("PARTITOR_JOBS")
            try:
                with quiet:
                    self.assertEqual(pt.run_detect(item, None, "T", "C D"), 0)
                    # Alto is on pages 1 and 3 only; page 2 has the staves of Bass alone
                    d = pt.load_item(item)
                    for e in d["systems"]:
                        if e["id"].startswith("p2."):
                            e["map"] = ["-", "Bass"]
                    pt.save_item(item, d)
                    os.environ["PARTITOR_JOBS"] = "1"
                    self.assertEqual(pt.run_build(item), 0)
                    serial = self.sig(item)
                    os.environ["PARTITOR_JOBS"] = "2"
                    self.assertEqual(pt.run_build(item), 0)
                    self.assertEqual(self.sig(item), serial)             # workers: the same files
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    self.assertEqual(pt.run_build(item, ["Alto"]), 0)
                self.assertIn("analysing 2 of 3 page(s)", buf.getvalue())   # page 2 only rests
                self.assertEqual(self.sig(item), serial)                 # Alto the same, Bass kept
            finally:
                if env is None:
                    os.environ.pop("PARTITOR_JOBS", None)
                else:
                    os.environ["PARTITOR_JOBS"] = env

    @staticmethod
    def sig(item):
        import hashlib
        return {p.name: [hashlib.md5(pg.get_pixmap(dpi=40).samples).hexdigest()
                         for pg in pymupdf.open(str(p))]
                for p in sorted((item / "parts").glob("*.pdf"))}


@needs_deps
class TestDetectParallel(unittest.TestCase):
    """detect with workers (0.4.1): the same output as one process."""

    SYSTEMS = (1, 2, 3, 2)               # systems on pages 1-4 (base shifts on every page)

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="detpar-")
        doc = pymupdf.open()
        for i, n in enumerate(cls.SYSTEMS):
            one = os.path.join(cls.tmp, f"p{i}.pdf")
            make_score_pdf(one, systems=n, staves=2, labels=("Alto", "Bass"),
                           title="Test Chorale" if i == 0 else "")
            doc.insert_pdf(pymupdf.open(one))
        cls.pdf = os.path.join(cls.tmp, "score.pdf")
        doc.save(cls.pdf)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def tearDown(self):
        pt._reset_counts()

    def detect(self, jobs, name, pages=None):
        out = os.path.join(self.tmp, name)
        ns = argparse.Namespace(pdf=self.pdf, pages=pages, parts="", title="", subtitle="",
                                composer="", dpi=200, out=out, page_header_sp=pt.PAGE_HEADER_SP,
                                force=True, jobs=jobs)
        buf = io.StringIO()
        pt._reset_counts()
        with contextlib.redirect_stdout(buf):
            rc = pt.cmd_detect(ns)
        text = buf.getvalue().replace(out, "OUT")
        text = re.sub(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d \w+", "DATE", text)
        text = re.sub(r"elapsed: \d+ms", "elapsed: T", text)
        return rc, text, Path(out)

    @staticmethod
    def files(out):
        import hashlib
        return {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted((out / "preview").iterdir())}

    def test_parallel_equals_sequential(self):
        rc1, text1, o1 = self.detect("1", "seq")
        rc2, text2, o2 = self.detect("2", "par")
        self.assertEqual((rc1, rc2), (0, 0))
        self.assertEqual((o1 / "layout.yaml").read_text().replace(str(o1), "OUT"),
                         (o2 / "layout.yaml").read_text().replace(str(o2), "OUT"))
        self.assertEqual(self.files(o1), self.files(o2))       # names and bytes
        notes = ("worker", "analysis took")
        self.assertFalse(any(n in text1 for n in notes))        # one job: no new text
        self.assertIn("analysing 4 page(s) with 2 worker(s)", text2)
        self.assertEqual(text1, "\n".join(l for l in text2.split("\n")
                                          if not any(n in l for n in notes)))

    def test_system_ids_follow_the_pages(self):
        _, _, out = self.detect("2", "ids")
        lay = yaml.safe_load((out / "layout.yaml").read_text())
        want = [f"p{p + 1}.s{k + 1}" for p, n in enumerate(self.SYSTEMS) for k in range(n)]
        self.assertEqual([e["id"] for e in lay["systems"]], want)
        self.assertEqual([e["geom"]["page"] for e in lay["systems"]],
                         [p + 1 for p, n in enumerate(self.SYSTEMS) for _ in range(n)])

    def test_system_base_changes_no_record(self):
        # nsys is only the base of the system index: a worker passes 0, the old
        # loop passed the systems before. Pages with 1, 2 and 3 systems.
        doc = pymupdf.open(self.pdf)
        for pno, n in enumerate(self.SYSTEMS[:3]):
            r0, rec0 = pt.analyse_one(doc, pno, 200, 0)
            r7, rec7 = pt.analyse_one(doc, pno, 200, 7)
            self.assertEqual(len(rec0), n)
            self.assertEqual(rec0, rec7)
            self.assertEqual([[st.system for st in g] for g in r7.systems],
                             [[7 + k] * 2 for k in range(n)])
            self.assertEqual(list(r0.barlines.values()), list(r7.barlines.values()))
            self.assertTrue(np.array_equal(
                np.where(r0.owner >= pt.OWN_HEADER_BASE, 1, r0.owner),
                np.where(r7.owner >= pt.OWN_HEADER_BASE, 1, r7.owner)))

    def test_what_a_worker_returns_is_small_and_transferable(self):
        import pickle
        doc = pymupdf.open(self.pdf)
        res, recs = pt.analyse_one(doc, 1, 200, 0)
        item = pt.preview_page(res, recs, Path(self.tmp))
        small = pickle.dumps((recs, item, res.title, res.composer))
        self.assertEqual(pickle.loads(small), (recs, item, res.title, res.composer))
        self.assertLess(len(small), 64 * 1024)
        self.assertGreater(len(pickle.dumps(res)), 20 * len(small))   # the image stays behind

    def test_one_job_uses_no_workers(self):
        def no_fork(*a, **k):
            raise AssertionError("fork_map called with one job")
        with mock_attr(pt, "fork_map", no_fork):
            rc, _, _ = self.detect("1", "one")
        self.assertEqual(rc, 0)

    def test_jobs_from_the_environment(self):
        old = os.environ.get("PARTITOR_JOBS")
        os.environ["PARTITOR_JOBS"] = "2"
        try:
            _, text, _ = self.detect(None, "env")
        finally:
            if old is None:
                os.environ.pop("PARTITOR_JOBS", None)
            else:
                os.environ["PARTITOR_JOBS"] = old
        self.assertIn("with 2 worker(s)", text)

    def test_die_in_a_worker_stops_detect(self):
        real = pt.analyse_one

        def die_on_page_two(doc, pno, dpi, nsys, **kw):
            if pno == 1:
                pt._die("page 2: test failure")
            return real(doc, pno, dpi, nsys, **kw)
        out = Path(self.tmp, "die")
        with mock_attr(pt, "analyse_one", die_on_page_two), \
                contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as cm:
                self.detect("2", "die")
        self.assertEqual(cm.exception.code, 1)
        self.assertFalse((out / "layout.yaml").exists())      # nothing half written

    def test_error_in_a_worker_names_the_page_position(self):
        real = pt.analyse_one

        def fail_on_page_three(doc, pno, dpi, nsys, **kw):
            if pno == 2:
                raise KeyError("boom")
            return real(doc, pno, dpi, nsys, **kw)
        with mock_attr(pt, "analyse_one", fail_on_page_three):
            with self.assertRaises(RuntimeError) as cm:
                self.detect("2", "err")
        self.assertIn("item 3 of 4", str(cm.exception))
        self.assertIn("KeyError", str(cm.exception))

    def test_detect_then_build_in_one_process(self):
        # `new`: detect, then (after the prompts) build, in one process
        item = Path(self.tmp, "2026-10-0001-c-t")
        item.mkdir()
        shutil.copy(self.pdf, item / "2026-10-0001-source.pdf")
        pt.save_item(item, {"id": "2026-10-0001", "slug": "c-t", "created": "2026-10-30"})
        old = os.environ.get("PARTITOR_JOBS")
        os.environ["PARTITOR_JOBS"] = "2"
        threads = cv2.getNumThreads()
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(pt.run_detect(item, None, "T", "C D"), 0)
                self.assertEqual(cv2.getNumThreads(), threads)   # pool restored after the fork
                self.assertEqual(pt.run_build(item), 0)
        finally:
            if old is None:
                os.environ.pop("PARTITOR_JOBS", None)
            else:
                os.environ["PARTITOR_JOBS"] = old
        self.assertTrue(list((item / "parts").glob("*.pdf")))

    def test_help_lists_jobs(self):
        env = dict(os.environ, PARTITOR_ALLOW_ROOT="1")
        r = subprocess.run([sys.executable, SRC, "detect", "--help"], capture_output=True,
                           text=True, env=env)
        self.assertEqual(r.returncode, 0)
        self.assertIn("--jobs", r.stdout)


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
class TestLibrary(unittest.TestCase):
    """Library model and CLI (DESIGN.md §2, §3, §6)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.share = Path(self.tmp.name, "share")
        (self.share / "inbox").mkdir(parents=True)
        (self.share / "library").mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def test_slugs(self):
        self.assertEqual(pt.slugify("Heinrich Schütz"), "heinrich-schuetz")
        self.assertEqual(pt.slugify("Maria, gegrüßet seist du"), "maria-gegruesset-seist-du")
        self.assertEqual(pt.slugify("Café"), "cafe")
        self.assertEqual(pt.make_slug("Johann Hermann Schein", "23. Komm, heiliger Geist"),
                         "schein-komm-heiliger-geist")
        self.assertEqual(pt.make_slug("", ""), "untitled")
        self.assertEqual(pt.slugify("Wie sich ein Vat'r erbarmet"), "wie-sich-ein-vatr-erbarmet")
        self.assertLessEqual(len(pt.slugify("word " * 40, 30)), 30)

    def test_ids(self):
        lib = self.share / "library"
        for n in ("2026-001-a", "2026-10-0007-b", "2025-030-c", "notes"):
            (lib / n).mkdir()
        # YYYY-MM-NNNN; the serial counts on through the year (old YYYY-NNN too)
        self.assertEqual(pt.next_id(lib, 2026, 11), "2026-11-0008")
        self.assertEqual(pt.next_id(lib, 2027, 1), "2027-01-0001")
        self.assertEqual(pt.resolve_id("7", 2026), (2026, None, 7))
        self.assertEqual(pt.resolve_id("2025-30", 2026), (2025, None, 30))
        self.assertEqual(pt.resolve_id("2026-10-0007", 2026), (2026, 10, 7))
        with self.assertRaises(ValueError):
            pt.resolve_id("x7", 2026)
        self.assertEqual(pt.find_item(lib, "2026-7").name, "2026-10-0007-b")
        self.assertEqual(pt.find_item(lib, "2025-30").name, "2025-030-c")      # old id
        self.assertEqual(pt.item_id(lib / "2026-10-0007-b"), "2026-10-0007")
        self.assertEqual(pt.piece_tag("Johann Hermann Schein", "11. Maria, gegrüßet"),
                         "Schein-Maria")
        self.assertEqual(pt.part_file_name(6, "Bass Trombone grosso", "-Schein-Maria--2026-10-0001"),
                         "06-bass-trombone-grosso-Schein-Maria--2026-10-0001.pdf")
        # old plain item files are renamed to <id>-<file> on first use
        old = lib / "2025-030-c"
        (old / "score.yaml").write_text("id: 2025-030\n")
        self.assertEqual(pt.load_item(old)["id"], "2025-030")
        self.assertTrue((old / "2025-030-score.yaml").is_file())
        self.assertFalse((old / "score.yaml").exists())

    def test_inbox_natural_order_and_meta(self):
        for n in ("b10.pdf", "b2.pdf", "notes.txt"):
            (self.share / "inbox" / n).write_bytes(b"%PDF-1.4\n")
        self.assertEqual([p.name for p in pt.inbox_pdfs(self.share)], ["b2.pdf", "b10.pdf"])
        pdf = Path(self.tmp.name, "IMSLP123-PMLP45-Schein_Banchetto_22.pdf")
        make_score_pdf(str(pdf))
        self.assertEqual(pt.suggest_meta(pdf)[0], "Schein Banchetto 22")

    def test_apply_set(self):
        data = {"title": "A", "layout": {}}
        ch = pt.apply_set(data, ["gap=12", "paper=a4", "pages=2", "title=B"])
        self.assertEqual(data["layout"], {"gap": 12.0, "paper": "a4", "page_count": 2})
        self.assertEqual(data["title"], "B")
        self.assertEqual(len(ch), 4)
        pt.apply_set(data, ["pages=auto"])
        self.assertNotIn("page_count", data["layout"])
        for bad in (["nokey=1"], ["paper=a3"], ["gap"], ["gutter=40"], ["pages=0"]):
            with self.subTest(bad=bad):
                before = dict(data["layout"])
                with self.assertRaises(ValueError):
                    pt.apply_set(data, bad)
                self.assertEqual(data["layout"], before)

    def test_expand_contract_ladder(self):
        def d(pages, staff, smax, gap=10.0):
            return {"layout": {"gap": gap},
                    "built": {"parts": [{"pages": pages, "staff_mm": staff,
                                         "staff_max_mm": smax}]}}
        self.assertEqual(pt.step_size(d(2, 6.0, 7.0), True)[0], ["pages=3"])
        self.assertEqual(pt.step_size(d(2, 7.0, 7.0), True)[0], ["gap=11.0"])
        with self.assertRaises(ValueError):
            pt.step_size(d(2, 7.0, 7.0, gap=pt.GAP_MAX), True)
        self.assertEqual(pt.step_size(d(3, 7.0, 7.0), False)[0], ["pages=2"])
        self.assertEqual(pt.step_size(d(1, 7.0, 7.0), False)[0], ["gap=9.0"])
        with self.assertRaises(ValueError):
            pt.step_size(d(1, 7.0, 7.0, gap=7.0), False)

    def test_per_part_layout(self):
        data = {"parts": ["Canto", "Continuo"], "groups": {"Tutti": ["Canto"]},
                "layout": {"gap": 10.0},
                "built": {"parts": [
                    {"part": "Canto", "pages": 2, "staff_mm": 7.0, "staff_max_mm": 7.0},
                    {"part": "Continuo", "pages": 3, "staff_mm": 6.0, "staff_max_mm": 7.0}]}}
        self.assertEqual(pt.step_size(data, False, "Continuo")[0], ["Continuo:pages=2"])
        self.assertEqual(pt.step_size(data, True, "Canto")[0], ["Canto:gap=11.0"])
        pt.apply_set(data, ["Continuo:pages=2", "Tutti:gap=9"])
        self.assertEqual(data["layout"]["parts"], {"Continuo": {"page_count": 2},
                                                   "Tutti": {"gap": 9.0}})
        self.assertEqual(data["layout"]["gap"], 10.0)          # item value unchanged
        self.assertEqual(pt.part_layout(data, "Tutti")["gap"], 9.0)
        pt.apply_set(data, ["Continuo:pages=auto"])
        self.assertNotIn("Continuo", data["layout"]["parts"])
        for bad in (["Nobody:gap=9"], ["Canto:paper=a4"], ["Canto:title=x"]):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                pt.apply_set(data, bad)
        with self.assertRaises(ValueError):
            pt.step_size({"layout": {}}, True)

    def test_choose_maps_suggestion_and_numbers(self):
        item = self.share / "library" / "2026-001-x"
        item.mkdir()
        pt.save_item(item, {"id": "2026-001", "slug": "x", "parts": ["A", "B", "C"],
                            "systems": [
                                {"id": "p1.s1", "staves": 2, "map": ["?", "?"],
                                 "suggest": ["B", "C"]},
                                {"id": "p1.s2", "staves": 2, "map": ["?", "?"],
                                 "suggest": ["A", "B"]}]})
        answers = iter(["", "9 9", "1 0"])     # suggestion; bad; numbers with a drop
        real = builtins.input
        builtins.input = lambda prompt="": next(answers)
        try:
            with open(os.devnull, "w") as devnull, contextlib.redirect_stdout(devnull):
                self.assertTrue(pt.choose_maps(item))
        finally:
            builtins.input = real
        maps = [s["map"] for s in pt.load_item(item)["systems"]]
        self.assertEqual(maps, [["B", "C"], ["A", "-"]])
        self.assertEqual(pt.item_status(pt.load_item(item)), "ready to build")

    def test_choose_maps_answer_becomes_later_suggestion(self):
        item = self.share / "library" / "2026-003-z"
        item.mkdir()
        sysm = lambda i, cl: {"id": f"p1.s{i}", "staves": 2, "map": ["?", "?"],
                              "suggest": ["C", "B"], "clefs": cl}
        pt.save_item(item, {"id": "2026-003", "slug": "z", "parts": ["A", "B", "C"],
                            "systems": [sysm(1, ["G2", "F4"]), sysm(2, ["G2", "F4"]),
                                        sysm(3, ["C3", "F4"])]})
        answers = iter(["1 2", "", ""])        # correct the first; Enter on the rest
        real = builtins.input
        builtins.input = lambda prompt="": next(answers)
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertTrue(pt.choose_maps(item))
        finally:
            builtins.input = real
        maps = [s["map"] for s in pt.load_item(item)["systems"]]
        # same clefs: the answer; other clefs: its own suggestion
        self.assertEqual(maps, [["A", "B"], ["A", "B"], ["C", "B"]])

    def test_rename_item(self):
        lib = self.share / "library"
        item = lib / "2026-10-0007-schein-maria-gegriibet"
        item.mkdir(parents=True)
        pt.save_item(item, {"id": "2026-10-0007", "slug": "schein-maria-gegriibet",
                            "composer": "Johann Hermann Schein",
                            "title": "11. Maria, gegrüßet seist du"})
        dst = pt.rename_item(lib, item)
        self.assertEqual(dst.name, "2026-10-0007-schein-maria-gegruesset-seist-du")
        self.assertTrue(pt.item_file(dst, pt.SCORE_FILE).is_file())
        self.assertEqual(pt.load_item(dst)["slug"], "schein-maria-gegruesset-seist-du")
        self.assertEqual(pt.rename_item(lib, dst), dst)           # already matches

    def test_reid_old_item(self):
        lib = self.share / "library"
        old = lib / "2026-001-schein-maria"
        (old / "parts").mkdir(parents=True)
        pt.save_item(old, {"id": "2026-001", "slug": "schein-maria", "created": "2026-10-23",
                           "source": "source.pdf",
                           "built": {"parts": [{"part": "A", "file": "01-a-Schein-Maria--2026-001.pdf"}]}})
        (old / "2026-001-source.pdf").write_bytes(b"%PDF")
        (old / "parts" / "01-a-Schein-Maria--2026-001.pdf").write_bytes(b"%PDF")
        (lib / "2026-10-0002-x").mkdir()                       # serial 2 taken, 1 free
        dst = pt.reid_item(lib, old)
        self.assertEqual(dst.name, "2026-10-0001-schein-maria")
        self.assertTrue((dst / "2026-10-0001-source.pdf").is_file())
        self.assertTrue((dst / "parts" / "01-a-Schein-Maria--2026-10-0001.pdf").is_file())
        data = pt.load_item(dst)
        self.assertEqual((data["id"], data["source"]), ("2026-10-0001", "2026-10-0001-source.pdf"))
        self.assertEqual(data["built"]["parts"][0]["file"], "01-a-Schein-Maria--2026-10-0001.pdf")
        with self.assertRaises(ValueError):
            pt.reid_item(lib, dst)

    def test_menu_keys_and_order(self):
        lib = self.share / "library"
        a = lib / "2026-10-0012-x"
        b = lib / "2025-11-0014-y"
        c = lib / "2026-10-0003-z"
        for d in (a, b, c):
            d.mkdir(parents=True)
        self.assertEqual(pt.menu_key(a, 2026), "12")
        self.assertEqual(pt.menu_key(b, 2026), "2025-14")
        self.assertEqual(sorted([b, c, a], key=pt.id_order, reverse=True), [a, c, b])
        pt.save_item(a, {"id": "2026-10-0012", "systems": [{"map": ["?"]}]})
        self.assertEqual(pt.work_mark(a), "*")

    def test_item_matches_and_page_size(self):
        item = self.share / "library" / "2026-10-0005-schein-x"
        item.mkdir()
        pt.save_item(item, {"id": "2026-10-0005", "composer": "Johann Hermann Schein",
                            "title": "Nun ist das Heil", "parts": ["Alto I", "Continuo"]})
        self.assertTrue(pt.item_matches(item, "schein"))
        self.assertTrue(pt.item_matches(item, "Schein continuo"))
        self.assertFalse(pt.item_matches(item, "Schein Bach"))
        self.assertIn(" · Schein · Nun ist das Heil · ", pt.item_line(item, pt.load_item(item)))
        old = os.environ.get("PARTITOR_LIST_PAGE")
        try:
            for v, want in (("50", 50), ("2", 5), ("999", 200), ("x", 20)):
                os.environ["PARTITOR_LIST_PAGE"] = v
                self.assertEqual(pt.list_page_size(), want)
        finally:
            if old is None:
                os.environ.pop("PARTITOR_LIST_PAGE", None)
            else:
                os.environ["PARTITOR_LIST_PAGE"] = old

    def test_item_without_id_keys_after_failed_detect(self):
        item = self.share / "library" / "2026-10-0003-new"
        item.mkdir()
        pt.save_item(item, {"title": "Psalmi", "parts": ["A"]})   # detect left no id
        self.assertEqual(pt.load_item(item)["id"], "2026-10-0003")
        self.assertTrue(pt.item_line(item, pt.load_item(item)).startswith("2026-10-0003 · "))

    def test_set_and_show_use_set_names(self):
        data = {"parts": ["A"], "layout": {"page_count": 5}}
        self.assertEqual(pt.apply_set(data, ["pages=auto"]), ["pages: 5 -> auto"])
        self.assertEqual(pt.apply_set(data, ["gap=11"]), ["gap: 10.0 (default) -> 11.0"])
        self.assertEqual(pt.set_name("page_count"), "pages")

    def item_with_choice(self):
        item = self.share / "library" / f"{time.localtime().tm_year}-002-y"
        item.mkdir()
        pt.save_item(item, {
            "id": f"{time.localtime().tm_year}-002", "slug": "y", "pages": "3-3",
            "parts": ["Alto", "Tenor", "Bass"],
            "systems": [
                {"id": "p3.s1", "staves": 3, "map": ["Alto", "Tenor", "Bass"],
                 "clefs": ["C3", "C4", "F"],
                 "geom": {"page": 3, "h": 400, "staves": [[40, 50, 90], [40, 120, 160],
                                                          [40, 190, 230]]}},
                {"id": "p3.s2", "staves": 2, "map": ["?", "?"], "suggest": ["Tenor", "Bass"],
                 "clefs": ["C4", "F"], "labels": ["Ten.", ""],
                 "geom": {"page": 3, "h": 400, "staves": [[40, 280, 320], [40, 340, 380]]}}]})
        (item / "preview").mkdir()
        cv2.imwrite(str(item / "preview" / "page-03.png"), np.full((400, 300), 255, np.uint8))
        return item

    def quiet_input(self, answers, fn, *args):
        it = iter(answers)
        real = builtins.input
        builtins.input = lambda prompt="": next(it)
        buf = __import__("io").StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                out = fn(*args)
        finally:
            builtins.input = real
        return out, buf.getvalue()

    def test_proof_labels_systems_parts_and_choices(self):
        item = self.item_with_choice()
        pt.proof_from_preview(item)
        text = pymupdf.open(pt.item_file(item, "proof.pdf"))[0].get_text()
        for want in ("source page 3", "1 system(s) to choose", "p3.s1", "p3.s2", "Alto",
                     "? Tenor", "? Bass"):
            self.assertIn(want, text)
        _, out = self.quiet_input(["1 0"], pt.choose_maps, item)
        self.assertIn("source page 3, system 2 of 2 from the top (proof page 1)", out)
        self.assertIn("clefs top to bottom: C4 F; printed labels: Ten.", out)
        self.assertIn("(= 2 3)", out)
        self.assertIn("Tenor  (C4 clef)", out)
        text = pymupdf.open(pt.item_file(item, "proof.pdf"))[0].get_text()   # redrawn
        self.assertNotIn("to choose", text)
        self.assertIn("(left out)", text)

    def test_rename_one_part(self):
        item = self.item_with_choice()
        res, _ = self.quiet_input(["2=Tenore", "9=X", "3=Alto", "3=Basso; 1=Altus", ""],
                                  pt.rename_parts, item)
        self.assertIsNone(res)
        data = pt.load_item(item)
        self.assertEqual(data["parts"], ["Altus", "Tenore", "Basso"])
        self.assertEqual(data["systems"][0]["map"], ["Altus", "Tenore", "Basso"])
        self.assertEqual(data["systems"][1]["suggest"], ["Tenore", "Basso"])
        res, _ = self.quiet_input(["A, B"], pt.rename_parts, item)
        self.assertEqual(res, ["A", "B"])            # other count: detect again

    def test_leave_out_and_join_parts(self):
        data = {"parts": ["S", "A", "Org R", "BC"],
                "systems": [{"map": ["S", "A", "Org R", "BC"], "clefs": ["G", "C3", "G", "F"]},
                            {"map": ["?", "?"], "suggest": ["Org R", "BC"],
                             "clefs": ["G", "F"]}]}
        d1 = __import__("copy").deepcopy(data)
        self.assertEqual(pt.apply_part_ops(d1, "3=-; 4=Continuo"), "")
        # a part not extracted stays in the list (its staves are still named)
        self.assertEqual(d1["parts"], ["S", "A", "Org R", "Continuo"])
        self.assertEqual(d1["skip"], ["Org R"])
        self.assertEqual(d1["systems"][0]["map"], ["S", "A", "Org R", "Continuo"])
        self.assertEqual(pt.apply_part_ops(d1, "3=Organ"), "")     # rename keeps the mark
        self.assertEqual(d1["skip"], ["Organ"])
        self.assertEqual(pt.apply_part_ops(d1, "3=+"), "")
        self.assertNotIn("skip", d1)
        d2 = __import__("copy").deepcopy(data)
        self.assertEqual(pt.apply_part_ops(d2, "3+4; 4=Organ"), "")
        self.assertEqual(d2["parts"], ["S", "A", "Organ"])
        self.assertEqual(d2["systems"][0]["map"], ["S", "A", "Organ", "Organ"])
        self.assertEqual(pt.part_clefs(d2)["Organ"], "G+F")
        for bad in ("9=-", "3+3", "1=-; 2=-; 3=-; 4=-", "3+4; 4+1", "3=-; 3=+", "2=S", "x"):
            d3 = __import__("copy").deepcopy(data)
            with self.subTest(bad=bad):
                self.assertNotEqual(pt.apply_part_ops(d3, bad), "")
                self.assertEqual(d3, data)

    def test_proof_from_preview(self):
        item = Path(self.tmp.name, "item")
        (item / "preview").mkdir(parents=True)
        for k in (1, 2):
            img = np.full((40, 30), 255, np.uint8)
            cv2.imwrite(str(item / "preview" / f"page-{k:02d}.png"), img)
        out = pt.proof_from_preview(item)
        self.assertEqual(len(pymupdf.open(out)), 2)
        self.assertFalse((item / "preview").exists())

    def run_cli(self, *args, stdin=""):
        env = dict(os.environ, PARTITOR_ALLOW_ROOT="1", PARTITOR_LIBRARY=str(self.share))
        return subprocess.run([sys.executable, SRC, *args], input=stdin, capture_output=True,
                              text=True, env=env, cwd=self.tmp.name, timeout=600)

    def test_new_wizard_end_to_end(self):
        make_score_pdf(str(self.share / "inbox" / "chorale.pdf"))
        # pages, title, composer, short composer, part names, (no choices), build now
        r = self.run_cli("new", stdin="1\n\nTest Chorale\nJ. H. Schein\n\nA,T,B\n\n\n")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        now = time.localtime()
        iid = f"{now.tm_year}-{now.tm_mon:02d}-0001"
        item = self.share / "library" / f"{iid}-schein-test-chorale"
        self.assertTrue((item / f"{iid}-source.pdf").is_file())
        self.assertFalse((self.share / "inbox" / "chorale.pdf").exists())
        self.assertTrue((item / f"{iid}-proof.pdf").is_file())
        self.assertTrue((item / f"{iid}-score.yaml").is_file())
        data = pt.load_item(item)
        self.assertEqual((data["id"], data["parts"]), (iid, ["A", "T", "B"]))
        self.assertEqual(pt.item_status(data), "built")
        self.assertEqual(sorted(p.name for p in (item / "parts").iterdir()),
                         sorted(f"0{k}-{n}-Schein-Test--{iid}{x}.pdf"
                                for k, n in ((1, "a"), (2, "t"), (3, "b"))
                                for x in ("", "-11x17")))
        self.assertIn("Review:", r.stdout)                  # shown before "Build now?"
        # edits are saved, not built (operator request 2026-10-24)
        before = {p.name: p.stat().st_mtime for p in (item / "parts").iterdir()}
        r = self.run_cli("set", "1", "title=Other Title", "gap=12")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("saved, not built", r.stdout)
        data = pt.load_item(item)
        self.assertEqual((data["title"], data["layout"]["gap"]), ("Other Title", 12.0))
        self.assertEqual(pt.item_status(data), "changes not built")
        self.assertEqual(data["pending"], ["title", "gap"])
        self.assertEqual({p.name: p.stat().st_mtime for p in (item / "parts").iterdir()}, before)
        r = self.run_cli("show", "1")
        self.assertIn("not built: title, gap", r.stdout)
        self.assertIn("short:     Schein", r.stdout)
        r = self.run_cli("rebuild", "1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        data = pt.load_item(item)
        self.assertNotIn("pending", data)
        self.assertEqual(pt.item_status(data), "built")
        self.assertEqual(data["id"], iid)                    # id and slug never change
        self.assertEqual(len(list((item / "parts").glob("*.pdf"))), 6)   # renamed, none left over
        self.assertTrue(any("Other" in p.name for p in (item / "parts").iterdir()))
        r = self.run_cli("set", "1", "composer_short=J.H. Schein", "--build")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        data = pt.load_item(item)
        self.assertEqual((data["composer_short"], pt.item_status(data)), ("J.H. Schein", "built"))
        r = self.run_cli("list")
        self.assertIn("Other Title", r.stdout)
        # analyse again: groups and title kept, a new proof, not built
        r = self.run_cli("groups", "1", stdin="Low=2,3\n\n")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        r = self.run_cli("analyse", "1", "--yes", stdin="\n")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        data = pt.load_item(item)
        self.assertEqual(data["groups"], {"Low": ["T", "B"]})
        self.assertEqual(data["title"], "Other Title")
        self.assertIn("analysed again", data["pending"])

    def test_bars_menu_marks_by_bar_number(self):
        make_score_pdf(str(self.share / "inbox" / "chorale.pdf"))
        r = self.run_cli("new", stdin="1\n\nTest Chorale\nJ. H. Schein\n\nA,T,B\n\n\n")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        r = self.run_cli("bars", "1", stdin="m 2 3\nm 99\n\n")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("bars 1-", r.stdout)                       # bar range of each line
        self.assertIn("mark at bar 2: added", r.stdout)
        self.assertIn("mark at bar 3: added", r.stdout)
        self.assertIn("no bar 99", r.stdout)
        self.assertIn("mark B at bar 3", r.stdout)                # letter and real bar number
        data = pt.load_item(next((self.share / "library").iterdir()))
        self.assertEqual(data["bar_rules"]["marks_add"], [2, 3])

    def test_bars_menu_join_add_undo_and_build(self):
        make_score_pdf(str(self.share / "inbox" / "chorale.pdf"))
        r = self.run_cli("new", stdin="1\n\nTest Chorale\nJ. H. Schein\n\nA,T,B\n\n\n")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        item = next((self.share / "library").iterdir())
        raw = pt.load_item(item)["systems"][0]["bars"]
        r = self.run_cli("bars", "1", stdin="j 1 1\nb 1\nj 1 9\na 1 1 40\nu 1\n\n")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("bars edited", r.stdout)
        self.assertIn("join needs a bar", r.stdout)                 # bar 9 does not exist
        data = pt.load_item(item)
        self.assertEqual(data["bar_rules"]["bar_edits"], [f"p1.s1:j1/{raw}"])   # a: then u removed it
        self.assertEqual(data["systems"][0]["bars"], raw)           # detection stays as detected
        self.assertEqual(len(data["systems"][0]["bar_nums"]), raw - 1)
        # the build applies the edit to the barlines (one bar less in line 1)
        r = self.run_cli("rebuild", "1", stdin="\n\n")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        # analyse again: the edit stays while the line has the same bars
        r = self.run_cli("analyse", "1", "--yes", stdin="\n")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(pt.load_item(item)["bar_rules"]["bar_edits"], [f"p1.s1:j1/{raw}"])
        r = self.run_cli("bars", "1", stdin="u 1\n\n")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("bar_edits", pt.load_item(item)["bar_rules"])

    def test_build_stops_on_printed_number_mismatch_until_kept(self):
        make_score_pdf(str(self.share / "inbox" / "chorale.pdf"))
        r = self.run_cli("new", stdin="1\n\nTest Chorale\nJ. H. Schein\n\nA,T,B\n\n\n")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        item = next((self.share / "library").iterdir())
        data = pt.load_item(item)
        # two printed numbers agree: line 2 starts at bar 9, the count says 4
        data["systems"][1]["anchors"] = [[0, 9], [1, 10]]
        pt.renumber(data)
        pt.save_item(item, data)
        ms = pt.bar_mismatches(pt.effective_systems(data["systems"], data["bar_rules"]),
                               data["bar_rules"])
        self.assertEqual([m["id"] for m in ms], [data["systems"][1]["id"]])
        parts_before = sorted(p.name for p in (item / "parts").glob("*.pdf"))
        r = self.run_cli("rebuild", "1", stdin="n\n\n")           # asked; left open
        self.assertIn("keep the printed numbers", r.stdout)
        self.assertIn("left open", r.stdout)
        self.assertIn("printed", r.stdout + r.stderr)
        # the stopped build leaves the earlier parts alone (0.3.0-dev.32)
        self.assertEqual(sorted(p.name for p in (item / "parts").glob("*.pdf")), parts_before)
        self.assertFalse((item / "parts.new").exists())
        r = self.run_cli("bars", "1", stdin="k 2\n\n")           # keep the printed numbers
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(len(pt.load_item(item)["bar_rules"]["bars_ack"]), 1)
        r = self.run_cli("rebuild", "1", stdin="\n\n")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(any((item / "parts").glob("*.pdf")))

    def test_new_build_later(self):
        make_score_pdf(str(self.share / "inbox" / "chorale.pdf"))
        r = self.run_cli("new", stdin="1\n\nTest Chorale\nJ. H. Schein\nSchein\n\nn\n")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        item = next((self.share / "library").iterdir())
        data = pt.load_item(item)
        self.assertEqual(pt.item_status(data), "ready to build")
        self.assertFalse((item / "parts").exists() and any((item / "parts").iterdir()))

    def test_composer_short(self):
        self.assertEqual(pt.composer_surname("Johann Hermann Schein"), "Schein")
        self.assertEqual(pt.composer_surname("J.S. Bach"), "Bach")
        self.assertEqual(pt.composer_surname(""), "")
        data = {"parts": ["A"], "systems": [{"map": ["A"]}], "built": {"parts": []}}
        pt.mark_pending(data, "gap", "gap", "title")
        self.assertEqual(data["pending"], ["gap", "title"])
        self.assertEqual(pt.item_status(data), "changes not built")

    def test_new_stopped_keeps_pdf_in_inbox(self):
        make_score_pdf(str(self.share / "inbox" / "chorale.pdf"))
        r = self.run_cli("new", stdin="1\nq\n")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("stays in the inbox", r.stdout)
        self.assertTrue((self.share / "inbox" / "chorale.pdf").is_file())
        self.assertEqual(list((self.share / "library").iterdir()), [])

    def test_library_folder_not_ready(self):
        (self.share / "library").rmdir()
        r = self.run_cli("list")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("library folder not ready", r.stderr)

    def test_engine_refuses_root(self):
        if os.geteuid() != 0:
            self.skipTest("not root")
        env = {k: v for k, v in os.environ.items() if k != "PARTITOR_ALLOW_ROOT"}
        r = subprocess.run([sys.executable, SRC, "list"], capture_output=True, text=True,
                           env=env)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("does not run as root", r.stderr)


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
        res = pt.analyse_page(pymupdf.open(TestSystemWindow.make_pdf(self.tmp.name))[0], 0, 400, 0)
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


def flow_line(notes, bars, width=200, key=False, first=False, nums=None):
    """Synthetic one-staff line, sp 10: clef strokes (x 6-25, above and
    below the staff), optional key signature strokes (x 36-56), 8x7 note
    heads at (x, y), barlines at bars (2 px), last barline at the end."""
    img = np.zeros((130, width), bool)
    for k in range(5):
        img[40 + 10 * k, :] = True
    for x0 in (6, 13, 20):                       # clef: thin strokes, tall
        img[28:94, x0:x0 + 3] = True
    if key:
        for x0 in (36, 40, 48, 52):
            img[44:62, x0:x0 + 2] = True
    for x, y in notes:
        img[y:y + 7, x:x + 8] = True
    for b in bars:
        img[40:81, b:b + 2] = True
    return pt.Strip(img, 0, 40, 80, 10.0, np.zeros_like(img), bars_x=list(bars),
                    bar_nums=list(nums or range(1, len(bars) + 1)), ends_at_bar=True,
                    movement=first)


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


@contextlib.contextmanager
def mock_attr(obj, name, value):
    old = getattr(obj, name)
    setattr(obj, name, value)
    try:
        yield
    finally:
        setattr(obj, name, old)


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


@needs_deps
class TestClefsAndSpacing(unittest.TestCase):
    """Clef reading (G1/G2, C1-C5, F3-F5), rest brackets, group system gap."""

    def page_with_clef(self, kind, line):
        """A one-staff vector page with a Bravura clef on the given line."""
        font = next((d / "Bravura.otf" for d in pt.font_dirs() if (d / "Bravura.otf").is_file()), None)
        if font is None:
            self.skipTest("Bravura not installed")
        doc = pymupdf.open()
        page = doc.new_page(width=612, height=300)
        top, x0 = 120, 60
        for ln in range(5):
            page.draw_line((x0, top + ln * SP), (560, top + ln * SP), width=0.6)
        for bx in (x0, 300, 560):
            page.draw_line((bx, top), (bx, top + 4 * SP), width=0.8)
        y = top + (5 - line) * SP                 # the clef's line
        page.insert_text((x0 + 4, y), chr(pt.CLEF_GLYPHS[kind]), fontsize=4 * SP,
                         fontname="brav", fontfile=str(font))
        for nx in range(x0 + 60, 540, 40):
            page.draw_oval(pymupdf.Rect(nx, top + SP - 2.6, nx + 7.5, top + SP + 2.6), fill=(0, 0, 0))
        page.insert_text((x0 + 26, top + 2.6 * SP), "\ue08a", fontsize=4 * SP,
                         fontname="brav", fontfile=str(font))     # a common-time sign
        return doc

    def test_clef_kinds_and_lines(self):
        for kind, line in (("G", 2), ("C", 3), ("C", 4), ("C", 1), ("F", 4)):
            with self.subTest(clef=f"{kind}{line}"):
                doc = self.page_with_clef(kind, line)
                res = pt.analyse_page(doc[0], 0, 400, 0)
                self.assertEqual([st.clef for st in res.staves], [f"{kind}{line}"])

    def test_rare_clef_needs_a_lead(self):
        self.assertIn("G2", pt.CLEF_COMMON)
        self.assertNotIn("G1", pt.CLEF_COMMON)
        self.assertGreater(pt.CLEF_RARE_LEAD, 0)

    def test_group_rest_line_keeps_bracket(self):
        a = flow_line([(70, 44), (110, 60)], [100, 198], key=True)
        b = flow_line([(75, 60), (120, 52)], [105, 198], key=True)
        r = pt.fill_rests([a, pt.RestRun(5, 3), b], {})[1]
        r.bracket = True
        self.assertTrue(pt.justify(r, r.img.shape[1] + 40).bracket)

    def test_rest_brackets_visible(self):
        a = flow_line([(70, 44), (110, 60)], [100, 198], key=True)
        b = flow_line([(75, 60), (120, 52)], [105, 198], key=True)
        r = pt.fill_rests([a, pt.RestRun(5, 3), b], {})[1]
        hb = r.img[r.staff_top + 20]
        xs = np.flatnonzero(r.img[r.staff_top + 12, :])     # between line 2 and 3
        # full staff height (line 1 to line 5), 0.5 sp thick
        bracket_cols = [x for x in xs if r.img[r.staff_top:r.staff_top + 41, x].all()]
        self.assertGreaterEqual(len(bracket_cols), 2 * 5)   # two brackets, 5+ px each
        del hb

    def test_cue_and_footer_text(self):
        for t in ("35(Alto I)", "(Canto I)", "Farce I)", "35"):
            self.assertTrue(pt.is_cue_text(t), t)
        for t in ("Sinfonia", "II. Teil", ""):
            self.assertFalse(pt.is_cue_text(t), t)
        for t in ("© 1986 by Bärenreiter-Verlag, Kassel", "@ 1986 by Barenreiter",
                  "254", "*) Das Pausenzeichen gilt nur"):
            self.assertTrue(pt.is_footer_text(t), t)
        for t in ("Concert.", "dar-um freu-et", ""):
            self.assertFalse(pt.is_footer_text(t), t)

    def test_rehearsal_marks_added_and_relettered(self):
        systems = [{"id": "a", "bars": 4}, {"id": "b", "bars": 4}, {"id": "c", "bars": 4}]
        nums = [[1, 2, 3, 4], [5, 6, 7, 8], [9, 10, 11, 12]]
        auto = {"b": [[2, "A"]]}                          # found at bar 7
        out = pt.apply_mark_rules(systems, auto, nums, {"marks_add": [3, 10]})
        self.assertEqual(out, {"a": [[2, "A"]], "b": [[2, "B"]], "c": [[1, "C"]]})
        out = pt.apply_mark_rules(systems, auto, nums, {"marks_add": [10], "marks_drop": [7]})
        self.assertEqual(out, {"c": [[1, "A"]]})
        rules = {}
        for e, n in zip(systems, nums):
            e["bar_nums"] = n
        systems[1]["marks"] = [[2, "A"]]
        self.assertEqual(pt.toggle_mark(rules, systems, 3), "added")
        self.assertEqual(pt.toggle_mark(rules, systems, 7), "removed")
        self.assertEqual(rules, {"marks_add": [3], "marks_drop": [7]})
        with self.assertRaises(ValueError):
            pt.toggle_mark(rules, systems, 99)

    def test_ambitus_pitch_names(self):
        self.assertEqual(pt.pitch_name(30), "E4")
        self.assertEqual(pt.pitch_num("C4"), 28)
        self.assertEqual(pt.pitch_num("g2"), 18)
        with self.assertRaises(ValueError):
            pt.pitch_num("H4")
        # accidentals: parsed, staff position unchanged
        for a, b in (("F#3", "F3"), ("Bb2", "B2"), ("eb4", "E4"),
                     ("C\u266f4", "C4"), ("B\u266d3", "B3"), ("b3", "B3")):
            self.assertEqual(pt.pitch_num(a), pt.pitch_num(b), a)
        self.assertEqual(pt.parse_pitch("F#3"), (24, 1))
        self.assertEqual(pt.parse_pitch("bb3"), (27, -1))
        self.assertEqual(pt.parse_pitch("b3"), (27, 0))
        self.assertEqual(pt.pitch_str(24, 1), "F#3")
        self.assertEqual(pt.pitch_str(27, -1), "Bb3")
        for bad in ("F##3", "Fx3", "F#", "bb"):
            with self.assertRaises(ValueError):
                pt.parse_pitch(bad)
        # bottom lines: treble E4, tenor-8 E3, alto F3, tenor D3, bass G2
        self.assertEqual([pt.pitch_name(pt.CLEF_BOTTOM[c]) for c in ("G2", "G8", "C3", "C4", "F4")],
                         ["E4", "E3", "F3", "D3", "G2"])

    def test_ambitus_from_staves_and_overrides(self):
        data = {"parts": ["Canto", "Alto", "Continuo", "Org"], "skip": ["Org"],
                "systems": [
                    {"id": "p1.s1", "map": ["Canto", "Alto", "Continuo"],
                     "clefs": ["G2", "C3", "F4"], "steps": [[0, 8], [2, 9], [-4, 6]]},
                    {"id": "p1.s2", "map": ["Canto", "Alto", "Continuo"],
                     "clefs": ["G2", "C3", "F4"], "steps": [[-2, 10], None, [-1, 3]]}]}
        amb = pt.refresh_ambitus(data)
        self.assertEqual(amb["Canto"], {"range": "C4-A5", "from": "auto"})
        self.assertEqual(amb["Alto"], {"range": "A3-A4", "from": "auto"})
        self.assertEqual(amb["Continuo"]["from"], "off")      # continuo-like name
        self.assertNotIn("Org", amb)                           # not extracted
        self.assertIsNone(pt.ambitus_for(data, "Continuo"))
        pt.apply_set(data, ["Alto:ambitus=G4-C3", "Continuo:ambitus=on"])
        self.assertEqual(data["ambitus"]["Alto"], {"range": "C3-G4", "from": "operator"})
        self.assertEqual(data["ambitus"]["Continuo"], {"range": "C2-F3", "from": "on"})
        data["systems"][0]["steps"][1] = [0, 0]                # map/steps change: by hand kept
        pt.refresh_ambitus(data)
        self.assertEqual(data["ambitus"]["Alto"]["range"], "C3-G4")
        self.assertEqual(pt.ambitus_for(data, "Alto"), ("C3", 21, 32, 0, 0))
        pt.apply_set(data, ["Alto:ambitus=auto"])
        self.assertEqual(data["ambitus"]["Alto"], {"range": "F3-F3", "from": "auto"})
        for bad in (["Alto:ambitus=C4"], ["Alto:ambitus=X1-C4"]):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                pt.apply_set(data, bad)
        doc = pymupdf.open()
        page = doc.new_page()
        pt.draw_ambitus(page, 50, 100, "F4", 14, 28)           # C2-C4: ledger lines both ways
        pt.draw_ambitus(page, 150, 100, "G8", 23, 30)
        self.assertGreater(len(page.get_drawings()), 5)

    def test_ambitus_clef_smoothing(self):
        def sysm(i, clef, steps):
            return {"id": f"p{i}.s1", "map": ["T"], "clefs": [clef], "steps": [steps]}
        # one misread system (C3 among F4) and a missed tenor 8
        data = {"parts": ["T"], "systems": [sysm(1, "F4", [0, 4]), sysm(2, "C3", [0, 8]),
                                            sysm(3, "F4", [1, 5])]}
        self.assertEqual(pt.refresh_ambitus(data)["T"]["range"], "G2-A3")
        data = {"parts": ["T"], "systems": [sysm(1, "G8", [0, 4]), sysm(2, "G2", [0, 8]),
                                            sysm(3, "G8", [1, 5])]}
        self.assertEqual(pt.refresh_ambitus(data)["T"]["range"], "E3-F4")
        # a real change lasts: C3 then G2 twice
        data = {"parts": ["T"], "systems": [sysm(1, "C3", [0, 2]), sysm(2, "G2", [0, 2]),
                                            sysm(3, "G2", [0, 2])]}
        self.assertEqual(pt.refresh_ambitus(data)["T"]["range"], "F3-G4")

    def test_note_steps_synthetic(self):
        sp, thick, idx = 20, 2, 0
        img = np.zeros((400, 700), bool)
        top = 150
        for k in range(5):
            img[top + k * sp - 1:top + k * sp + 1, 20:680] = True
        line_px = img.copy()
        def head(cx, step):                     # filled notehead at a staff step
            cy = int(top + 4 * sp - step * sp / 2)
            cv2.ellipse(img.view(np.uint8), (cx, cy), (13, 9), -20, 0, 360, 1, -1)
        head(200, 3)
        head(300, 8)
        head(400, -4)                           # C below a bass-like staff: 2 ledgers
        for ls in (-2, -4):
            y = int(top + 4 * sp - ls * sp / 2)
            img[y - 1:y + 1, 400 - 24:400 + 24] = True
        head(500, -4)                           # no ledger lines: lyric-like, ignored
        img[top + 4 * sp + 50:top + 4 * sp + 70, 560:600] = True   # text block below
        owner = np.where(img, idx, pt.OWN_NONE).astype(np.int32)
        st = pt.Staff(0, 0, [top + k * sp for k in range(5)], 20, 680)
        lo, hi, n, *_ = pt.note_steps(owner, line_px, st, idx, float(sp), thick)
        self.assertEqual((lo, hi), (-4, 8))
        self.assertEqual(n, 3)

    def test_ambitus_report_doubts(self):
        def sysm(i, steps):
            return {"id": f"p{i}.s1", "map": ["T"], "clefs": ["G2"], "steps": [steps],
                    "bar_nums": [10 * i, 10 * i + 1]}
        # highs 8, 8, 9 and one 13 (2 ledger lines, 4 beyond the next): doubtful
        data = {"parts": ["T"], "systems": [sysm(1, [2, 8, 0, 0, 0, 1]), sysm(2, [3, 8, 0, 0, 0, 0]),
                                            sysm(3, [2, 9, 0, 0, 1, 1]),
                                            sysm(4, [3, 13, 0, 0, 0, 1])]}
        rp = pt.ambitus_report(data, "T")
        self.assertEqual(rp["high"], [41])
        self.assertEqual(rp["low"], [10, 31])
        self.assertEqual(len(rp["doubts"]), 1)
        self.assertTrue(rp["doubts"][0].startswith("high D6 (bar 41 (page 4, system 1))"))

    def test_ambitus_suggestion(self):
        def sysm(i, steps):
            return {"id": f"p{i}.s1", "map": ["T"], "clefs": ["G2"], "steps": [steps],
                    "bar_nums": [10 * i, 10 * i + 1]}
        data = {"parts": ["T"], "systems": [sysm(1, [2, 8, 0, 0, 0, 1]), sysm(2, [3, 8, 0, 0, 0, 0]),
                                            sysm(3, [2, 9, 0, 0, 1, 1]),
                                            sysm(4, [3, 13, 0, 0, 0, 1])]}
        rp = pt.ambitus_report(data, "T")
        self.assertEqual(rp["suggest"], "G4-G5")          # D6 left out, next highest G5
        self.assertIn("high D6 left out", rp["why"])

    def test_ambitus_noteheads_stacked_cue_size(self):
        doc = pymupdf.open()
        page = doc.new_page(width=200, height=100)
        sp = 4.0
        pt.draw_ambitus(page, 10, 60, "G2", pt.pitch_num("C4"), pt.pitch_num("G5"), sp=sp)
        pt.draw_ambitus(page, 100, 60, "G2", pt.pitch_num("C4"), pt.pitch_num("D4"), sp=sp)
        heads = []
        for b in page.get_text("rawdict")["blocks"]:
            for ln in b.get("lines", []):
                for sp_ in ln["spans"]:
                    for ch in sp_["chars"]:
                        if ch["c"] in ("\ue0a4", "\ue0a2"):
                            heads.append((ch["c"], round(ch["origin"][0], 1), sp_["size"]))
        self.assertEqual(len(heads), 4)
        self.assertTrue(all(h[0] == "\ue0a4" for h in heads))      # black head, not whole
        self.assertTrue(all(abs(h[2] - 0.8 * 4 * sp) < 0.01 for h in heads))   # 80 %
        self.assertEqual(heads[0][1], heads[1][1])                 # a sixth+: one column
        self.assertGreater(heads[3][1], heads[2][1])               # a second: upper head moves

    def _glyphs(self, page, chars):
        out = []
        for b in page.get_text("rawdict")["blocks"]:
            for ln in b.get("lines", []):
                for sp_ in ln["spans"]:
                    for ch in sp_["chars"]:
                        if ch["c"] in chars:
                            out.append((ch["c"], ch["origin"][0], ch["origin"][1], sp_["size"]))
        return out

    def test_ambitus_accidentals_drawn(self):
        doc = pymupdf.open()
        page = doc.new_page(width=300, height=100)
        sp = 4.0
        pt.draw_ambitus(page, 10, 60, "G2", 24, 30, 1, 0, sp=sp)        # one sharp
        pt.draw_ambitus(page, 100, 60, "G2", 24, 40, 1, -1, sp=sp)      # 16 apart: one column
        pt.draw_ambitus(page, 200, 60, "G2", 28, 30, -1, 1, sp=sp)      # close: two columns
        g = self._glyphs(page, ("\ue262", "\ue260"))
        self.assertEqual([c for c, *_ in g], ["\ue262", "\ue260", "\ue262", "\ue262", "\ue260"])
        self.assertTrue(all(abs(h[3] - 0.8 * 4 * sp) < 0.01 for h in g))      # 80 %
        heads = self._glyphs(page, ("\ue0a4",))
        # one sharp: left of its head
        self.assertLess(g[0][1], heads[0][1])
        # far apart: both accidentals in one column
        self.assertAlmostEqual(g[1][1] + pt.text_len(g[1][0], "music", g[1][3]),
                               g[2][1] + pt.text_len(g[2][0], "music", g[2][3]), places=1)
        # close: lower accidental (flat) is left of the upper one (sharp)
        self.assertLess(g[4][1], g[3][1])
        # all accidentals inside the ambitus width
        self.assertLess(max(h[1] for h in heads) + 2 * sp, 200 + pt.ambitus_width(sp))
        self.assertGreater(min(h[1] for h in g[3:]), 200 + 3.0 * sp)           # clear of the clef

    def test_ambitus_accidentals_stored_and_returned(self):
        data = {"parts": ["T"], "systems": [{"id": "p1.s1", "map": ["T"], "clefs": ["C4"],
                                             "steps": [[0, 4]], "bar_nums": [1, 2]}],
                "ambitus": {"T": {"range": "E4-F#3", "from": "operator"}}}
        self.assertEqual(pt.ambitus_for(data, "T"), ("C4", 24, 30, 1, 0))
        data["ambitus"]["T"]["range"] = "Bb2-Bb3"
        self.assertEqual(pt.ambitus_for(data, "T")[1:], (20, 27, -1, -1))

    def test_first_line_ambitus_mark(self):
        a = flow_line([(70, 44), (110, 60)], [100, 198], key=True)
        b = flow_line([(75, 60), (120, 52), (160, 44), (200, 60), (240, 52), (280, 44)],
                      [100, 198, 300, 398], width=400, key=True)
        out = pt.finish_lines([a, b], "Alto", False, amb=("C3", 21, 37))
        self.assertTrue(out[0].ambitus_marks)
        self.assertIsNone(out[0].name_label)

    def test_wide_run(self):
        ink = np.zeros((200, 60), bool)
        ink[50:70, 10:40] = True                  # a head, 20 rows
        ink[70:140, 38:40] = True                 # its stem: narrow
        self.assertLess(pt._wide_run(ink, 10, 50, 30, 20, 20.0, 2), 1.7 * 20)
        ink[:] = False
        ink[40:60, 10:40] = True                  # a digit cut by a staff line
        ink[66:85, 10:40] = True
        self.assertGreaterEqual(pt._wide_run(ink, 10, 66, 30, 19, 20.0, 2), 1.7 * 20)

    def test_note_steps_ignores_letters_and_time_signature(self):
        sp, thick, idx = 20, 2, 0
        img = np.zeros((400, 700), bool)
        top = 150
        for k in range(5):
            img[top + k * sp - 1:top + k * sp + 1, 20:680] = True
        line_px = img.copy()
        # time signature 3/2 right after the clef: two blocks at one x
        img[top + 2:top + 2 * sp - 2, 100:122] = True
        img[top + 2 * sp + 2:top + 4 * sp - 2, 100:122] = True
        # a letter-like blob just above the staff (taller than wide)
        img[top - 22:top - 4, 300:314] = True
        # one real head on the middle line
        cv2.ellipse(img.view(np.uint8), (400, top + 2 * sp), (13, 9), -20, 0, 360, 1, -1)
        owner = np.where(img, idx, pt.OWN_NONE).astype(np.int32)
        st = pt.Staff(0, 0, [top + k * sp for k in range(5)], 20, 680)
        r = pt.note_steps(owner, line_px, st, idx, float(sp), thick, barxs=[])
        self.assertEqual(r[:3], (4, 4, 1))

    def test_group_systems_further_apart_than_staves(self):
        img = np.zeros((300, 400), bool)
        for t in (40, 120, 200):                 # three staves, 40 px apart
            for k in range(5):
                img[t + 10 * k, :] = True
        g = pt.Strip(img, 0, 40, 240, 10.0, np.zeros_like(img))
        g.staff_labels = [("A", 40, 80), ("B", 120, 160), ("C", 200, 240)]
        opts = {**pt.LAYOUT_DEFAULTS, "gap": 6.0}
        p = pt.pitches([g, g], opts)[0]
        between = p - (240 - 40)                 # bottom line to the next top line
        self.assertGreaterEqual(between, 1.5 * 40)  # inner gap 40 px

    def test_group_last_page_spreads_systems(self):
        img = np.zeros((300, 400), bool)
        for t in (40, 120, 200):
            for k in range(5):
                img[t + 10 * k, :] = True
        g = pt.Strip(img, 0, 40, 240, 10.0, np.zeros_like(img))
        g.staff_labels = [("A", 40, 80), ("B", 120, 160), ("C", 200, 240)]
        opts = {**pt.LAYOUT_DEFAULTS, "gap": 6.0}
        def dy():
            pages, _ = pt.plan_pages([g, g], 400, opts, False)
            self.assertEqual(len(pages), 1)
            (_, y0), (_, y1) = pages[0]
            return y1 - y0
        spread = dy()
        old = pt.SYSTEM_GAP_LAST
        try:
            pt.SYSTEM_GAP_LAST = pt.SYSTEM_GAP_FACTOR   # no widening
            plain = dy()
        finally:
            pt.SYSTEM_GAP_LAST = old
        p = pt.pitches([g, g], opts)[0]          # px
        extra_max = (pt.SYSTEM_GAP_LAST - pt.SYSTEM_GAP_FACTOR) * 40
        self.assertGreater(spread, plain)        # room on the page is used
        self.assertLessEqual(spread / plain, (p + extra_max) / p + 1e-6)


# ── Corpus regression (PARTITOR_CORPUS) ─────────────────────────────────────
# Reference values checked by eye against the source pages, 2026-10-22.
# staves per page and system sizes; pages not listed: no music.
CORPUS = {
    "suite1.pdf": {"pages": {1: [5, 5, 5], 2: [5, 5, 5], 3: [5, 5, 5], 4: [5, 5, 5],
                             5: [5, 5], 6: [4, 4, 4], 7: [4, 4, 4]}},
    "no22.pdf": {"pages": {1: [4, 4, 4], 2: [4, 4]}},
    "cesare.pdf": {"pages": {1: [5, 5, 5], 2: [5, 5, 5], 3: [5, 5, 5], 4: [5, 5, 5]}},
    "komm.pdf": {"pages": {p: [8, 8] for p in range(1, 20)}},
    "maria.pdf": {"pages": {7: [3, 4, 3, 8]}},
    "bach.pdf": {"pages": {8: [4, 4, 4], 9: [4, 4, 4], 10: [5, 5]},
                 "nomusic": [1, 2, 3, 4, 5, 6, 7, 18, 52, 66, 67, 68, 70]},
}
CORPUS_DIR = os.environ.get("PARTITOR_CORPUS")


@needs_deps
@unittest.skipUnless(CORPUS_DIR, "PARTITOR_CORPUS not set (slow corpus tests)")
class TestCorpus(unittest.TestCase):
    """Needs the user's own score PDFs (none ship with the repo: copyright).
    A test whose PDF is missing is skipped, not failed."""

    def need(self, *names):
        for n in names:
            if not Path(CORPUS_DIR, n).is_file():
                self.skipTest(f"{n} not in the corpus folder {CORPUS_DIR}")

    def pages(self, name, nums):
        pdf = Path(CORPUS_DIR, name)
        doc = pymupdf.open(pdf)
        for pno in nums:
            yield pt.analyse_page(doc[pno - 1], pno - 1, 400, 0)

    def test_staff_and_system_counts(self):
        found = [n for n in CORPUS if Path(CORPUS_DIR, n).is_file()]
        if not found:
            self.skipTest(f"none of {', '.join(CORPUS)} in the corpus folder {CORPUS_DIR}")
        for name in found:
            ref = CORPUS[name]
            for res in self.pages(name, sorted(ref["pages"])):
                with self.subTest(file=name, page=res.page + 1):
                    self.assertEqual([len(g) for g in res.systems], ref["pages"][res.page + 1])
                    self.assertEqual(res.gate, [])

    def test_titles_composers_and_running_heads(self):
        # title in the same size as other text (Suite 1 p1) is found with
        # its composer line; a running head (p3) is no title (no restart)
        want = {("suite1.pdf", 1): ("Banchetto Musicale", "Johann Hermann Schein"),
                ("suite1.pdf", 3): ("", ""),
                ("bach.pdf", 8): ("Wie sich ein Vat'r erbarmet", "J.S. Bach"),
                # scan page edge at the top is no title (it restarted bars)
                ("maria.pdf", 2): ("", "")}
        want = {k: v for k, v in want.items() if Path(CORPUS_DIR, k[0]).is_file()}
        if not want:
            self.skipTest("no title PDFs in the corpus folder")
        for (name, pno), (title, comp) in want.items():
            res = pt.analyse_page(pymupdf.open(Path(CORPUS_DIR, name))[pno - 1], pno - 1, 400, 0)
            with self.subTest(file=name, page=pno):
                self.assertEqual((res.title, res.composer), (title, comp))

    def test_repeats_and_bar_rules_bach(self):
        self.need("bach.pdf")
        recs = []
        for _res, r in pt.iter_pages(Path(CORPUS_DIR, "bach.pdf"), 400, [7, 8]):
            recs += r
        sy = [{"id": r["id"], "bars": r["nbars"], "widths": r["widths"],
               "repeats": r["repeats"], "anchors": [list(a[:2]) for a in r["anchors"]],
               "restart": r["restart"]} for r in recs]
        rules = pt.propose_bar_rules(sy)
        self.assertEqual((rules["pickup"], rules["split"]), (["p8.s1"], ["p8.s2:2"]))
        self.assertEqual(pt.number_bars(sy, rules)[0], [0, 7, 14, 20, 26, 32])

    def test_bar_counts_with_repeat_barlines_suite1(self):
        self.need("suite1.pdf")
        # repeat barlines the barline rules miss are inserted (p2.s1:
        # ':||' at the line end); ':||:' is one barline; counts agree with
        # the printed numbers
        recs = []
        for _res, r in pt.iter_pages(Path(CORPUS_DIR, "suite1.pdf"), 400, [0, 1, 2]):
            recs += r
        self.assertEqual([r["nbars"] for r in recs], [4, 3, 4, 3, 2, 2, 3, 5, 5])

    def test_no_music_pages_skipped_without_gate(self):
        self.need("bach.pdf")
        ref = CORPUS["bach.pdf"]
        doc = pymupdf.open(Path(CORPUS_DIR, "bach.pdf"))
        for pno in ref["nomusic"]:
            r = pt.analyse_page(doc[pno - 1], pno - 1, 200, 0, ocr=False)
            with self.subTest(page=pno):
                self.assertFalse(r.music)
                self.assertEqual(r.gate, [])

    def test_peak_memory_one_page_at_a_time(self):
        self.need("komm.pdf")
        code = ("import resource,sys;from importlib.machinery import SourceFileLoader as L;"
                f"m=L('p',{SRC!r}).load_module();from pathlib import Path;"
                f"[None for _ in m.iter_pages(Path({os.path.join(CORPUS_DIR, 'komm.pdf')!r}),400,"
                "list(range(19)))];"
                "print(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss//1024)")
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertLess(int(r.stdout.strip().splitlines()[-1]), 1500)


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


if __name__ == "__main__":
    unittest.main()
