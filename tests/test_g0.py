# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""Tests for the run control of tools/g0_golden.py: the timing table, the order in which cases
start, and the default number of workers. The cases themselves (the engine runs) are not run here.
They need the golden files and take minutes.

Run: python3 -m unittest -v tests/test_g0.py
"""
import hashlib
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, "..", "tools", "g0_golden.py")

try:
    import pymupdf  # noqa: F401
    import yaml  # noqa: F401
    HAVE_DEPS = True
except ImportError:                      # pragma: no cover
    HAVE_DEPS = False


def load_tool():
    spec = importlib.util.spec_from_file_location("g0_golden", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@unittest.skipUnless(HAVE_DEPS, "pymupdf or yaml missing")
class TestG0RunControl(unittest.TestCase):
    def setUp(self):
        self.g0 = load_tool()

    def test_timed_stores_the_seconds_and_returns_the_result(self):
        sink = {}
        self.assertEqual(self.g0.timed("a", lambda: 7, sink), 7)
        self.assertIn("a", sink)
        self.assertGreaterEqual(sink["a"], 0.0)

    def test_timed_stores_the_seconds_when_the_case_raises(self):
        sink = {}

        def boom():
            raise ValueError("x")
        with self.assertRaises(ValueError):
            self.g0.timed("b", boom, sink)
        self.assertIn("b", sink)

    def test_timing_table_is_slowest_first_with_a_sum_line(self):
        lines = self.g0.format_timings({"fast": 1.0, "slow": 30.0, "mid": 5.0}, 18.0)
        self.assertEqual([l.split()[-1] for l in lines[:3]], ["slow", "mid", "fast"])
        self.assertIn("sum of 3 cases", lines[-1])
        self.assertIn("wall 18.0 s", lines[-1])
        self.assertIn("2.0 at once", lines[-1])

    def test_timing_table_ties_are_ordered_by_name(self):
        lines = self.g0.format_timings({"b": 1.0, "a": 1.0}, 2.0)
        self.assertEqual([l.split()[-1] for l in lines[:2]], ["a", "b"])

    def test_timing_table_with_zero_wall_time_does_not_divide(self):
        self.assertIn("0.0 at once", self.g0.format_timings({"a": 1.0}, 0.0)[-1])

    def test_slow_cases_start_first_and_keep_their_order(self):
        names = ["help:main", "build:base", "build:long-default", "lib:session",
                 "build:long-duplex", "pieces:multi", "lib:reduced"]
        got = [n for n, _ in self.g0.order_cases([(n, None) for n in names])]
        self.assertEqual(got, ["build:long-default", "lib:session", "build:long-duplex",
                               "lib:reduced", "help:main", "build:base", "pieces:multi"])

    def test_order_keeps_every_case_once(self):
        cases = [(f"c{i}", i) for i in range(5)] + [("lib:x", 9)]
        self.assertEqual(sorted(self.g0.order_cases(cases)), sorted(cases))

    def test_default_workers_is_four_and_the_help_says_so(self):
        self.assertEqual(self.g0.DEFAULT_WORKERS, 4)
        self.assertIn("--workers N     cases run in parallel (default 4)", self.g0.__doc__)
        self.assertIn("--timings", self.g0.__doc__)


def _png(path, w, h, fill, box=None, dark=0):
    """A grey page image: fill everywhere, `dark` inside box (x0, y0, x1, y1)."""
    import pymupdf
    px = bytearray([fill]) * (w * h)
    if box:
        for y in range(box[1], box[3]):
            for x in range(box[0], box[2]):
                px[y * w + x] = dark
    pymupdf.Pixmap(pymupdf.csGRAY, w, h, bytes(px), False).save(str(path))


@unittest.skipUnless(HAVE_DEPS, "pymupdf or yaml missing")
class TestG0PageImages(unittest.TestCase):
    def setUp(self):
        self.g0 = load_tool()
        self.tmp = tempfile.mkdtemp(prefix="pt-g0-")
        self.addCleanup(__import__("shutil").rmtree, self.tmp, True)
        self.ref, self.run, self.out = (Path(self.tmp, n) for n in ("ref", "run", "out"))
        self.ref.mkdir()
        self.run.mkdir()

    def golden(self, *hashes, case="build:x", art="pdf:a.pdf"):
        return {"cases": {case: {"artifacts": {art: {"pdf": [[10, 10, h] for h in hashes]}}}}}

    def test_page_changes_lists_only_the_pages_that_differ(self):
        old, new = self.golden("a", "b", "c"), self.golden("a", "x", "c")
        self.assertEqual(self.g0.page_changes(old, new), [("build:x", "pdf:a.pdf", 2, "b", "x")])

    def test_page_changes_ignores_a_changed_page_count_and_errors(self):
        self.assertEqual(self.g0.page_changes(self.golden("a"), self.golden("a", "b")), [])
        err = {"cases": {"build:x": {"error": "boom"}}}
        self.assertEqual(self.g0.page_changes(self.golden("a"), err), [])

    def test_diff_image_counts_changed_pixels_and_gives_the_box(self):
        _png(self.ref / "a.png", 40, 30, 255)
        _png(self.run / "b.png", 40, 30, 255, box=(5, 6, 9, 8), dark=0)
        info = self.g0.diff_image(self.ref / "a.png", self.run / "b.png", self.out.with_suffix(".png"))
        self.assertIn("8 px differ", info)
        self.assertIn("box x 5-8, y 6-7", info)
        import pymupdf
        pix = pymupdf.Pixmap(str(self.out.with_suffix(".png")))
        self.assertEqual((pix.width, pix.height), (40 * 3 + 8, 30))   # three panels, two gaps

    def test_diff_image_of_two_sizes_shows_the_sizes_and_two_panels(self):
        _png(self.ref / "a.png", 40, 30, 255)
        _png(self.run / "b.png", 50, 20, 255)
        info = self.g0.diff_image(self.ref / "a.png", self.run / "b.png", self.out.with_suffix(".png"))
        self.assertEqual(info, "size 40x30 -> 50x20")
        import pymupdf
        self.assertEqual(pymupdf.Pixmap(str(self.out.with_suffix(".png"))).width, 40 + 4 + 50)

    def test_write_diff_images_names_the_file_and_reports_a_missing_page(self):
        _png(self.ref / "a.png", 20, 20, 255)
        _png(self.run / "b.png", 20, 20, 0)
        ch = [("build:x", "pdf:p/a.pdf", 2, "a", "b"), ("build:x", "pdf:p/a.pdf", 3, "zz", "b")]
        lines, n = self.g0.write_diff_images(ch, self.ref, self.run, self.out)
        self.assertEqual(n, 1)
        self.assertTrue((self.out / "build_x-pdf_p_a.pdf-p2.png").is_file())
        self.assertIn("400 px differ", lines[0])
        self.assertIn("no image (golden page not stored)", lines[1])

    def test_keep_page_stores_by_hash_once_and_only_when_a_store_is_set(self):
        import pymupdf
        pix = pymupdf.Pixmap(pymupdf.csGRAY, 4, 4, bytes([7]) * 16, False)
        self.g0.PAGE_STORE = None
        self.g0.keep_page("h1", pix)
        self.assertEqual(list(self.ref.iterdir()), [])
        self.g0.PAGE_STORE = self.ref
        self.addCleanup(setattr, self.g0, "PAGE_STORE", None)
        self.g0.keep_page("h1", pix)
        self.g0.keep_page("h1", pix)
        self.assertEqual([f.name for f in self.ref.iterdir()], ["h1.png"])

    def test_pdf_hash_keeps_the_image_named_by_the_hash_it_returns(self):
        import pymupdf
        doc = pymupdf.open()
        doc.new_page(width=200, height=100).insert_text((20, 50), "g0")
        pdf = Path(self.tmp, "t.pdf")
        doc.save(str(pdf))
        self.g0.PAGE_STORE = self.ref
        self.addCleanup(setattr, self.g0, "PAGE_STORE", None)
        h = self.g0.pdf_hash(pdf)["pdf"][0][2]
        png = self.ref / f"{h}.png"
        self.assertTrue(png.is_file())
        self.assertEqual(hashlib.sha256(pymupdf.Pixmap(str(png)).samples).hexdigest(), h)

    def test_prune_store_drops_pages_that_are_not_in_the_golden(self):
        for h in ("a", "b", "stale"):
            _png(self.ref / f"{h}.png", 4, 4, 255)
        kept, missing = self.g0.prune_store(self.ref, self.golden("a", "b", "c"))
        self.assertEqual((kept, missing), (2, 1))
        self.assertEqual(sorted(f.stem for f in self.ref.glob("*.png")), ["a", "b"])

    def test_corpus_item_without_pdf_key_uses_the_name(self):
        from types import SimpleNamespace
        from unittest import mock
        corpus = Path(self.tmp, "corpus")
        corpus.mkdir()
        (corpus / "corpus.yaml").write_text(
            "items:\n  - {name: scan-a}\n  - {name: scan-b, note: x, expect: {systems: [3]}}\n")
        (corpus / "scan-b.pdf").write_bytes(b"%PDF-1.4\n")
        args = SimpleNamespace(corpus=str(corpus), only=None)
        cases = dict(self.g0.build_cases(args, Path("fx"), ["engine"]))
        self.assertEqual(cases["corpus:scan-a"](), {"skipped": "pdf not present"})
        with mock.patch.object(self.g0, "case_build", return_value={"ran": 1}) as cb:
            self.assertEqual(cases["corpus:scan-b"](), {"ran": 1})
        self.assertEqual(Path(cb.call_args.args[1]).name, "scan-b.pdf")

    def test_the_new_options_are_in_the_help_text(self):
        self.assertIn("--diff-dir", self.g0.__doc__)
        self.assertIn("pages     --engine", self.g0.__doc__)


if __name__ == "__main__":
    unittest.main()
