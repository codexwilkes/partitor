# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""Tests for page analysis (staves, systems, ownership, scans, corpus).

Needs the venv packages (numpy, opencv, pymupdf, PyYAML); without them every test
is skipped. Run with the venv interpreter:

    venv/bin/python3 -m unittest -v tests/test_analysis.py

Corpus regression tests (slow, about 15 min) run only when PARTITOR_CORPUS
names a directory with the reference PDFs (see CORPUS below). The PDFs are
not in the repo (copyright).

Shared helpers: tests/support.py.
"""
import argparse
import contextlib
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from support import (  # noqa: E402,F401
    SP,
    SRC,
    cv2,
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
