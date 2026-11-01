# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""Tests for the stage cache of the page analysis (lib/partitor/stagecache.py).

Run with the venv interpreter:

    venv/bin/python3 -m unittest -v tests/test_stagecache.py

Shared helpers: tests/support.py.
"""
import contextlib
import dataclasses
import gzip
import io
import os
import pickle
import re
import shutil
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from support import (  # noqa: E402,F401
    analysis,
    build,
    console,
    cv2,
    make_score_pdf,
    mock_attr,
    needs_deps,
    np,
    ownership,
    package_holders,
    parallel,
    pt,
    pymupdf,
    setUpModule,
    stagecache,
    tearDownModule,
    vision,
)

from partitor import config  # noqa: E402


def same_result(a, b):
    """Two PageResult objects with equal fields (numpy arrays by value)."""
    for f in dataclasses.fields(a):
        x, y = getattr(a, f.name), getattr(b, f.name)
        if isinstance(x, np.ndarray):
            if not (x.dtype == y.dtype and np.array_equal(x, y)):
                return False
        elif x != y:
            return False
    return True


@needs_deps
class TestStageCache(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="stagecache-")
        doc = pymupdf.open()
        for i in range(2):
            one = os.path.join(cls.tmp, f"p{i}.pdf")
            make_score_pdf(one, systems=2, staves=2, labels=("Alto", "Bass"),
                           title="Test Chorale" if i == 0 else "")
            doc.insert_pdf(pymupdf.open(one))
        cls.pdf = os.path.join(cls.tmp, "score.pdf")
        doc.save(cls.pdf)
        cls.doc = pymupdf.open(cls.pdf)
        cls.res = ownership.analyse_page(cls.doc[0], 0, 200, 0, ocr=False)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="sc-", dir=self.tmp)) / "cache"
        self.cache = stagecache.StageCache(self.dir, "a" * 64, 200, False, "env")
        self.old_tune = config.TUNE["page_header_sp"]

    def tearDown(self):
        config.TUNE["page_header_sp"] = self.old_tune
        pt._reset_counts()

    # ── key: one test per input ────────────────────────────────────────────
    def test_key_is_stable(self):
        other = stagecache.StageCache(self.dir, "a" * 64, 200, False, "env")
        self.assertEqual(self.cache.key(0, 0), other.key(0, 0))

    def test_key_changes_with_the_pdf_content(self):
        other = stagecache.StageCache(self.dir, "b" * 64, 200, False, "env")
        self.assertNotEqual(self.cache.key(0, 0), other.key(0, 0))

    def test_key_changes_with_the_page(self):
        self.assertNotEqual(self.cache.key(0, 0), self.cache.key(1, 0))

    def test_key_changes_with_the_system_base(self):
        self.assertNotEqual(self.cache.key(0, 0), self.cache.key(0, 3))

    def test_key_changes_with_the_dpi(self):
        other = stagecache.StageCache(self.dir, "a" * 64, 400, False, "env")
        self.assertNotEqual(self.cache.key(0, 0), other.key(0, 0))

    def test_key_changes_with_ocr(self):
        other = stagecache.StageCache(self.dir, "a" * 64, 200, True, "env")
        self.assertNotEqual(self.cache.key(0, 0), other.key(0, 0))

    def test_key_changes_with_the_page_header_limit(self):
        config.TUNE["page_header_sp"] = 1.5
        k1 = self.cache.key(0, 0)
        config.TUNE["page_header_sp"] = 2.5
        self.assertNotEqual(k1, self.cache.key(0, 0))

    def test_key_changes_with_the_environment(self):
        other = stagecache.StageCache(self.dir, "a" * 64, 200, False, "env2")
        self.assertNotEqual(self.cache.key(0, 0), other.key(0, 0))

    # ── environment_id: what it holds ──────────────────────────────────────
    def test_environment_holds_the_format(self):
        env = stagecache.environment_id()
        self.assertIn(f"format={stagecache.ANALYSIS_CACHE_FORMAT}", env)
        with mock_attr(stagecache, "ANALYSIS_CACHE_FORMAT", 99):
            self.assertNotEqual(env, stagecache.environment_id())

    def test_a_new_program_version_alone_keeps_the_key(self):
        # 0.7.1: the analysis source hash decides, not the release number
        env = stagecache.environment_id()
        key = stagecache.StageCache(self.dir, "a" * 64, 200, False, env).key(0, 0)
        with mock_attr(stagecache, "VERSION", "99.0.0"):
            env2 = stagecache.environment_id()
            self.assertEqual(env, env2)
            self.assertEqual(key, stagecache.StageCache(self.dir, "a" * 64, 200, False,
                                                        env2).key(0, 0))
        self.assertNotIn("partitor=", env)

    def test_an_entry_of_another_version_is_still_read(self):
        # the file records the version that wrote it; the reader does not compare it
        self.cache.put(0, 0, self.res)
        with mock_attr(stagecache, "VERSION", "99.0.0"):
            self.assertTrue(same_result(self.res, self.cache.get(0, 0)))

    def test_environment_changes_with_each_library_version(self):
        env = stagecache.environment_id()
        for mod, name, value in ((cv2, "__version__", "0.0"), (np, "__version__", "0.0"),
                                 (pymupdf, "version", ("0.0", "0", "0"))):
            with mock_attr(mod, name, value):
                self.assertNotEqual(env, stagecache.environment_id(), f"{mod.__name__}.{name}")

    def test_environment_changes_with_the_analysis_source(self):
        pkg = Path(self.tmp, "pkg")
        shutil.copytree(stagecache._PKG, pkg, ignore=shutil.ignore_patterns("__pycache__"))
        with mock_attr(stagecache, "_PKG", pkg):
            h1 = stagecache.source_hash()
            (pkg / "ownership.py").write_text(
                (pkg / "ownership.py").read_text(encoding="utf-8") + "\n# changed\n",
                encoding="utf-8")
            self.assertNotEqual(h1, stagecache.source_hash())
            self.assertEqual(stagecache.source_hash(), stagecache.source_hash())

    def test_source_hash_covers_the_modules_the_analysis_reaches(self):
        mods = stagecache.analysis_modules()
        for name in ("ownership", "vision", "clef", "config", "model", "mapping"):
            self.assertIn(name, mods)
        for name in ("build", "analysis", "cli_main", "render"):
            self.assertNotIn(name, mods)

    def test_environment_changes_with_tesseract(self):
        def fake(version):
            p = Path(self.tmp, f"tess-{version}")
            p.write_text(f"#!/bin/sh\necho 'tesseract {version}'\n", encoding="utf-8")
            p.chmod(p.stat().st_mode | stat.S_IXUSR)
            return str(p)
        with mock_attr(vision, "_TESS", {"path": None}):
            none = stagecache.environment_id()
        with mock_attr(vision, "_TESS", {"path": fake("5.0")}):
            v5 = stagecache.environment_id()
        with mock_attr(vision, "_TESS", {"path": fake("6.0")}):
            v6 = stagecache.environment_id()
        self.assertEqual(len({none, v5, v6}), 3)

    def test_environment_changes_with_the_tesseract_data_folder(self):
        with mock_attr(vision, "_TESS", {"path": "/bin/true"}):
            with mock.patch.dict(os.environ, {"TESSDATA_PREFIX": "/a"}):
                a = stagecache.environment_id()
            with mock.patch.dict(os.environ, {"TESSDATA_PREFIX": "/b"}):
                b = stagecache.environment_id()
        self.assertNotEqual(a, b)

    # ── read and write ─────────────────────────────────────────────────────
    def test_a_hit_returns_an_equal_page_result(self):
        self.cache.put(0, 0, self.res)
        got = self.cache.get(0, 0)
        self.assertIsNot(got, self.res)
        self.assertTrue(same_result(self.res, got))
        staves = {id(s) for s in got.staves}
        self.assertTrue(all(id(s) in staves for g in got.systems for s in g))   # shared Staff objects

    def test_a_missing_entry_is_a_miss_without_a_note(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertIsNone(self.cache.get(0, 0))
        self.assertEqual(buf.getvalue(), "")

    def _bad(self, payload=None, raw=None):
        self.dir.mkdir(parents=True)
        path = self.cache.path(0, 0)
        if raw is not None:
            path.write_bytes(raw)
        else:
            with gzip.open(path, "wb") as f:
                pickle.dump(payload, f)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            got = self.cache.get(0, 0)
            again = self.cache.get(0, 0)
        self.assertIsNone(got)
        self.assertIsNone(again)
        self.assertFalse(path.exists())                  # the bad entry is removed
        self.assertEqual(buf.getvalue().count("cache:"), 1)   # one note, not one per read
        return buf.getvalue()

    def test_a_corrupt_entry_is_a_miss(self):
        self._bad(raw=b"not a gzip file")

    def test_a_truncated_entry_is_a_miss(self):
        self.cache.put(0, 0, self.res)
        data = self.cache.path(0, 0).read_bytes()
        self.cache.path(0, 0).write_bytes(data[:len(data) // 2])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertIsNone(self.cache.get(0, 0))
        self.assertIn("analysed again", buf.getvalue())

    def test_an_old_format_entry_is_a_miss(self):
        self._bad({"format": stagecache.ANALYSIS_CACHE_FORMAT - 1,
                   "key": self.cache.key(0, 0), "result": self.res})

    def test_an_entry_with_another_key_is_a_miss(self):
        self._bad({"format": stagecache.ANALYSIS_CACHE_FORMAT, "key": "other",
                   "result": self.res})

    def test_an_entry_without_a_page_result_is_a_miss(self):
        self._bad({"format": stagecache.ANALYSIS_CACHE_FORMAT,
                   "key": self.cache.key(0, 0), "result": {"a": 1}})

    def test_an_unknown_class_is_refused(self):
        self._bad({"format": stagecache.ANALYSIS_CACHE_FORMAT, "key": self.cache.key(0, 0),
                   "result": mock.Mock})            # a global outside the allowed set

    def test_put_leaves_no_temporary_file(self):
        self.cache.put(0, 0, self.res)
        self.assertEqual([p.name for p in self.dir.iterdir()], [self.cache.path(0, 0).name])

    def test_only_the_newest_entry_of_a_page_stays(self):
        self.cache.put(0, 0, self.res)
        self.cache.put(1, 0, self.res)
        config.TUNE["page_header_sp"] = 9.5            # a new key for the same page
        self.cache.put(0, 0, self.res)
        names = sorted(p.name for p in self.dir.iterdir())
        self.assertEqual(len(names), 2)
        self.assertEqual(sum(n.startswith("p0001-") for n in names), 1)
        self.assertEqual(sum(n.startswith("p0002-") for n in names), 1)
        self.assertTrue(self.cache.path(0, 0).is_file())

    def test_present_counts_the_entries_of_the_current_key(self):
        self.cache.put(0, 0, self.res)
        self.assertEqual(self.cache.present([0, 1]), 1)
        config.TUNE["page_header_sp"] = 9.5
        self.assertEqual(self.cache.present([0, 1]), 0)

    def test_a_write_that_fails_is_skipped_with_one_note(self):
        blocker = Path(self.tmp, "blocker")
        blocker.write_text("a file, not a folder", encoding="utf-8")
        cache = stagecache.StageCache(blocker / "cache", "a" * 64, 200, False, "env")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            cache.put(0, 0, self.res)
            cache.put(1, 0, self.res)
        self.assertEqual(buf.getvalue().count("cache:"), 1)

    def test_two_processes_write_the_same_key(self):
        def writer(i):
            for _ in range(5):
                self.cache.put(0, 0, self.res)
            return i
        self.assertEqual(list(parallel.fork_map(writer, [0, 1], 2)), [0, 1])
        self.assertEqual([p.name for p in self.dir.iterdir()], [self.cache.path(0, 0).name])
        self.assertTrue(same_result(self.res, self.cache.get(0, 0)))

    # ── the off switch ─────────────────────────────────────────────────────
    def test_the_off_switch(self):
        for value, on in (("0", False), ("off", False), ("No", False), ("false", False),
                          ("1", True), ("", True), ("on", True)):
            with mock.patch.dict(os.environ, {"PARTITOR_CACHE": value}):
                self.assertEqual(stagecache.cache_enabled(), on, value)
                got = stagecache.open_cache(self.dir, "a" * 64, 200)
                self.assertEqual(got is not None, on, value)
        with mock.patch.dict(os.environ):
            os.environ.pop("PARTITOR_CACHE", None)
            self.assertTrue(stagecache.cache_enabled())

    # ── analyse_one ────────────────────────────────────────────────────────
    def _spy(self, log):
        real = ownership.analyse_page

        def spy(page, pno, *a, **k):
            with open(log, "a", encoding="utf-8") as fh:        # a counter would stay in a fork
                fh.write(f"{pno}\n")
            return real(page, pno, *a, **k)
        return spy

    @staticmethod
    def _calls(log):
        if not os.path.exists(log):
            return []
        with open(log, encoding="utf-8") as fh:
            return fh.read().split()

    def test_a_hit_skips_the_analysis(self):
        log = os.path.join(self.tmp, "spy-hit.log")
        with mock_attr(ownership, "analyse_page", self._spy(log)):
            r1, rec1 = analysis.analyse_one(self.doc, 1, 200, 0, ocr=False, cache=self.cache)
            self.assertEqual(self._calls(log), ["1"])
            r2, rec2 = analysis.analyse_one(self.doc, 1, 200, 0, ocr=False, cache=self.cache)
            self.assertEqual(self._calls(log), ["1"])           # not called again
            out = list(parallel.fork_map(
                lambda p: analysis.analyse_one(pymupdf.open(self.pdf), p, 200, 0, ocr=False,
                                               cache=self.cache)[1], [1], 1))
            self.assertEqual(self._calls(log), ["1"])           # a worker hits too
        self.assertEqual(rec1, rec2)
        self.assertEqual(out[0], rec1)
        self.assertTrue(same_result(r1, r2))

    def test_without_a_cache_the_analysis_runs_every_time(self):
        log = os.path.join(self.tmp, "spy-nocache.log")
        with mock_attr(ownership, "analyse_page", self._spy(log)):
            analysis.analyse_one(self.doc, 0, 200, 0, ocr=False)
            analysis.analyse_one(self.doc, 0, 200, 0, ocr=False)
        self.assertEqual(self._calls(log), ["0", "0"])

    def test_iter_pages_with_a_cache_uses_base_zero(self):
        got = [res.systems[0][0].system for res, _ in
               analysis.iter_pages(Path(self.pdf), 200, [0, 1], ocr=False, cache=self.cache)]
        self.assertEqual(got, [0, 0])                  # the second page does not start at 2

    # ── R1 ─────────────────────────────────────────────────────────────────
    def test_patched_names_are_held_by_their_owner_only(self):
        self.assertEqual(package_holders("analyse_page"), ["partitor.ownership"])
        self.assertEqual(package_holders("ANALYSIS_CACHE_FORMAT"), ["partitor.stagecache"])

    def test_the_module_imports_alone(self):
        import subprocess
        code = ("import sys; sys.path.insert(0, %r); import partitor.stagecache as m; "
                "print(m.ANALYSIS_CACHE_FORMAT)" % os.path.abspath(os.path.join(HERE, "..", "lib")))
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)


@needs_deps
class TestCacheOutputIsIdentical(unittest.TestCase):
    """detect and build give the same files with a cold cache, a warm cache and no cache."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="sc-out-")
        doc = pymupdf.open()
        for i in range(2):
            one = os.path.join(cls.tmp, f"p{i}.pdf")
            make_score_pdf(one, systems=2, staves=2, labels=("Alto", "Bass"),
                           title="Test Chorale" if i == 0 else "")
            doc.insert_pdf(pymupdf.open(one))
        cls.pdf = os.path.join(cls.tmp, "score.pdf")
        doc.save(cls.pdf)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def tearDown(self):
        pt._reset_counts()

    def item(self, name):
        iid = f"2026-10-{int(name):04d}"
        item = Path(self.tmp, f"{iid}-c-t")
        item.mkdir()
        shutil.copy(self.pdf, item / f"{iid}-source.pdf")
        pt.save_item(item, {"id": iid, "slug": "c-t", "created": "2026-10-30"})
        return item

    def run_item(self, item, again=False, cache="1"):
        """detect then build (the library calls); returns (output text, item)."""
        buf = io.StringIO()
        with mock.patch.dict(os.environ, {"PARTITOR_CACHE": cache, "PARTITOR_JOBS": "1"}), \
                mock_attr(console, "_TTY", False), contextlib.redirect_stdout(buf):
            pt._reset_counts()
            self.assertEqual(pt.run_detect(item, None, "T", "C D"), 0)
            self.assertEqual(build.run_build(item), 0)
        text = buf.getvalue().replace(str(item), "ITEM")
        text = re.sub(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d \w+", "DATE", text)
        text = re.sub(r"elapsed: \d+ms", "elapsed: T", text)
        text = re.sub(r"took \d+ s", "took N s", text)
        return text

    @staticmethod
    def result(item):
        """The layout and the pixels of every part: what the operator gets."""
        lay = next(item.glob("*-score.yaml")).read_text(encoding="utf-8")
        pix = {}
        for p in sorted(item.glob("parts/*.pdf")):
            d = pymupdf.open(p)
            pix[p.name] = [d[i].get_pixmap(dpi=50).samples for i in range(d.page_count)]
        lines = {p.name: gzip.open(p).read() for p in sorted(item.glob("lines/*.lines"))}
        return lay, pix, lines

    def test_cold_warm_and_off_give_the_same_result(self):
        cold_item, off_item = self.item("1"), self.item("2")
        cold_text = self.run_item(cold_item)
        self.assertTrue(list((cold_item / "cache").glob("*.pcache")))   # filled by detect
        cold = self.result(cold_item)
        warm_text = self.run_item(cold_item)              # same item again: every page hits
        warm = self.result(cold_item)
        off_text = self.run_item(off_item, cache="0")
        self.assertFalse((off_item / "cache").exists())
        off = self.result(off_item)
        def norm(r):
            ident = lambda t: re.sub(r"2026-10-000\d", "ID", t)
            return (ident(r[0]), {ident(k): v for k, v in r[1].items()},
                    {ident(k): v for k, v in r[2].items()})
        self.assertEqual(norm(cold), norm(warm))
        self.assertEqual(norm(cold)[1:], norm(off)[1:])
        # the same text, except the one cache note per command
        notes = [l for l in warm_text.split("\n") if "analysis cache:" in l]
        self.assertEqual(len(notes), 2)                   # detect and build
        self.assertIn("2 of 2 page(s) found", notes[0])
        cold_notes = [l for l in cold_text.split("\n") if "analysis cache:" in l]
        self.assertEqual(len(cold_notes), 1)              # build re-uses what detect stored
        self.assertFalse(any("analysis cache:" in l for l in off_text.split("\n")))
        def same_text(t):
            keep = "\n".join(l for l in t.split("\n") if "analysis cache:" not in l)
            return re.sub(r"2026-10-000\d", "ID", keep)
        self.assertEqual(same_text(warm_text), same_text(cold_text))
        self.assertEqual(same_text(off_text), same_text(cold_text))

    def test_a_changed_pdf_does_not_hit(self):
        item = self.item("3")
        self.run_item(item)
        before = sorted(p.name for p in (item / "cache").glob("*.pcache"))
        one = str(Path(self.tmp, "o0.pdf"))
        make_score_pdf(one, systems=3, staves=2, labels=("Alto", "Bass"))
        other = pymupdf.open()
        other.insert_pdf(pymupdf.open(one))
        other.insert_pdf(pymupdf.open(one))
        other.save(str(next(item.glob("*-source.pdf"))), garbage=0)
        text = self.run_item(item)
        detect_text = text.split("— build")[0]
        self.assertNotIn("analysis cache:", detect_text)       # the new PDF has no entries
        self.assertNotEqual(before, sorted(p.name for p in (item / "cache").glob("*.pcache")))


if __name__ == "__main__":
    unittest.main()
