# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""Real pages (tools/real-pages.py): the helpers, tested on synthetic pages, and the check of the
operator's folder of real scan pages.

The repo ships no score (copyright). PARTITOR_REAL_PAGES names a folder of one-page PDFs with a
corpus.yaml of expected values (see the header of tools/real-pages.py); without it the real-page
class is skipped. The expected values record what the engine gives now, after a person looked
at each page. They do not prove that the engine is right: it can still be wrong on other
pages. When a fix changes a value, change the value in the same release (CHANGELOG line).

Run: PARTITOR_REAL_PAGES=~/scratch/partitor/real-pages python3 -m unittest -v tests/test_real_pages.py
"""
import importlib.util
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from support import make_score_pdf, needs_deps, pymupdf, yaml  # noqa: E402

TOOL = os.path.join(HERE, "..", "tools", "real-pages.py")
REAL_DIR = os.environ.get("PARTITOR_REAL_PAGES")


def load_tool():
    spec = importlib.util.spec_from_file_location("real_pages", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Base(unittest.TestCase):
    def setUp(self):
        self.rp = load_tool()
        self.tmp = tempfile.mkdtemp(prefix="pt-rp-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def manifest(self, items):
        folder = Path(self.tmp, "pages")
        folder.mkdir(exist_ok=True)
        (folder / "corpus.yaml").write_text(yaml.safe_dump({"items": items}))
        return folder


@needs_deps
class TestRealPagesHelpers(Base):
    def library(self):
        lib = Path(self.tmp, "lib")
        for item in ("2026-11-0001-first", "2026-11-0002-second"):
            (lib / item).mkdir(parents=True)
            doc = pymupdf.open()
            for n in (1, 2, 3):
                doc.new_page().insert_text((50, 50), f"{item} page {n}")
            doc.save(str(lib / item / f"{item[:12]}-source.pdf"))
        return lib

    def test_items_get_a_default_pdf_name(self):
        folder = self.manifest([{"name": "scan-a"}, {"name": "scan-b", "pdf": "other.pdf"}])
        self.assertEqual([i["pdf"] for i in self.rp.load_items(folder)], ["scan-a.pdf", "other.pdf"])

    def test_a_folder_without_manifest_or_an_item_without_name_stops(self):
        with self.assertRaises(SystemExit):
            self.rp.load_items(self.tmp)
        with self.assertRaises(SystemExit):
            self.rp.load_items(self.manifest([{"pdf": "x.pdf"}]))

    def test_select_by_name_start(self):
        items = [{"name": "scan-a"}, {"name": "scan-b"}, {"name": "vector-a"}]
        self.assertEqual([i["name"] for i in self.rp.select(items, "scan,vector-a")],
                         ["scan-a", "scan-b", "vector-a"])
        self.assertEqual(self.rp.select(items, "scan-b"), [items[1]])
        self.assertEqual(self.rp.select(items, None), items)

    def test_find_source_takes_one_item_by_the_start_of_its_name(self):
        lib = self.library()
        self.assertEqual(self.rp.find_source(lib, "2026-11-0002").name, "2026-11-0002-source.pdf")
        self.assertIsNone(self.rp.find_source(lib, "2026-11"))          # two items
        self.assertIsNone(self.rp.find_source(lib, "2027"))             # none

    def test_extract_cuts_the_page_and_reports_what_is_missing(self):
        lib = self.library()
        folder = self.manifest([
            {"name": "scan-ok", "item": "2026-11-0002", "page": 2},
            {"name": "scan-page", "item": "2026-11-0001", "page": 9},
            {"name": "scan-item", "item": "2030", "page": 1},
            {"name": "scan-none"}])
        lines = self.rp.extract(lib, folder)
        self.assertIn("scan-ok: page 2 of 2026-11-0002-second -> scan-ok.pdf", lines[0])
        self.assertEqual([x.split(":")[0] for x in lines if x.startswith("missing")],
                         ["missing scan-page", "missing scan-item", "missing scan-none"])
        doc = pymupdf.open(str(folder / "scan-ok.pdf"))
        self.assertEqual(len(doc), 1)
        self.assertIn("2026-11-0002-second page 2", doc[0].get_text())
        self.assertFalse((folder / "scan-page.pdf").exists())

    def test_compare_names_each_difference(self):
        got = {"systems": [4, 4], "title_above": [], "x0_spread": [0, 3], "gate": []}
        self.assertEqual(self.rp.compare({"systems": [4, 4]}, got), [])
        self.assertEqual(self.rp.compare({"systems": [4, 4], "x0_spread_max": 3}, got), [])
        bad = self.rp.compare({"systems": [4, 5], "title_above": [2], "x0_spread_max": 2}, got)
        self.assertEqual(len(bad), 3)
        self.assertTrue(bad[0].startswith("systems [4, 5] -> [4, 4]"))
        self.assertTrue(any("title_above [2] -> []" in b for b in bad))
        self.assertTrue(any("over 2" in b for b in bad))
        self.assertIn("gate failed", self.rp.compare({"systems": [4, 4]}, dict(got, gate=["x"]))[0])

    def test_measure_a_synthetic_page(self):
        pdf = Path(self.tmp, "s.pdf")
        make_score_pdf(str(pdf), systems=2, staves=3)
        got = self.rp.measure(self.rp.analyse(pdf))
        self.assertEqual(got["systems"], [3, 3])
        self.assertEqual(got["title_above"], [])
        self.assertEqual(got["gate"], [])
        self.assertEqual(len(got["x0_spread"]), 2)

    def test_probe_runs_a_page_against_its_expectation(self):
        folder = self.manifest([{"name": "synth-ok", "expect": {"systems": [3, 3]}},
                                {"name": "synth-bad", "pdf": "synth-ok.pdf", "expect": {"systems": [3]}},
                                {"name": "synth-none", "pdf": "synth-ok.pdf"},
                                {"name": "synth-gone"}])
        make_score_pdf(str(folder / "synth-ok.pdf"), systems=2, staves=3)
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = self.rp.probe(folder, png=str(Path(self.tmp, "png")))
        out = buf.getvalue()
        self.assertEqual(rc, 1)
        self.assertIn("synth-ok: systems [3, 3]", out)
        self.assertRegex(out, r"synth-ok: .*  OK")
        self.assertIn("DIFFERS: systems [3] -> [3, 3]", out)
        self.assertIn("(no expect yet)", out)
        self.assertIn("synth-gone: no PDF (run extract)", out)
        self.assertTrue(Path(self.tmp, "png", "synth-ok.png").is_file())


@needs_deps
@unittest.skipUnless(REAL_DIR, "PARTITOR_REAL_PAGES not set (real scan pages, kept outside the repo)")
class TestRealPages(Base):
    """One subtest per page of the folder. A page whose PDF is missing is skipped, not failed.
    The values are what the engine gives now, checked by eye; the engine can still be wrong
    on other pages."""

    def test_pages_give_the_expected_values(self):
        items = [i for i in self.rp.load_items(REAL_DIR) if "expect" in i]
        found = [i for i in items if Path(REAL_DIR, i["pdf"]).is_file()]
        if not found:
            self.skipTest(f"no page with an expectation in {REAL_DIR}")
        for it in found:
            with self.subTest(page=it["name"]):
                got = self.rp.measure(self.rp.analyse(Path(REAL_DIR, it["pdf"])))
                self.assertEqual(self.rp.compare(it["expect"], got), [],
                                 f"{it['name']} (fixed in {it.get('fixed_in', '?')})")


if __name__ == "__main__":
    unittest.main()
