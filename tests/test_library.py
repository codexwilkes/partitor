# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""Tests for the library, safe builds and partial builds.

Needs the venv packages (numpy, opencv, pymupdf, PyYAML); without them every test
is skipped. Run with the venv interpreter:

    venv/bin/python3 -m unittest -v tests/test_library.py

Shared helpers: tests/support.py.
"""
import argparse
import builtins
import contextlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from support import (  # noqa: E402,F401
    LIB,
    SRC,
    build,
    cli_items,
    cli_parts,
    cv2,
    make_score_pdf,
    mock_attr,
    needs_deps,
    np,
    package_holders,
    pt,
    pymupdf,
    setUpModule,
    tearDownModule,
)


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
        self.real = build.cmd_build
        self.mode = "ok"
        self.calls = 0
        build.cmd_build = self.fake

    def tearDown(self):
        build.cmd_build = self.real
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
        build.LAST_BUILD.clear()
        build.LAST_BUILD.append({"part": "A", "pages": 2, "content_pages": 2, "staff_mm": 6.0,
                              "staff_max_mm": 6.0, "width_mm": 6.0, "gap": 10.0,
                              "file": f"01-a-gen{self.calls}.pdf"})
        return 0

    def names(self, sub="parts"):
        d = self.item / sub
        return sorted(p.name for p in d.iterdir()) if d.is_dir() else None

    def build(self):
        before = self.calls
        with open(os.devnull, "w") as dn, contextlib.redirect_stdout(dn):
            rc = build.run_build(self.item)
        self.assertEqual(self.calls, before + 1)         # run_build reached the fake cmd_build
        return rc

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
        self.real = build.cmd_build
        self.gen = 0
        self.asked = []
        self.folds: set = set()                                # parts that get fold-out files
        build.cmd_build = self.fake
        self.build()                                           # the first, full build

    def tearDown(self):
        build.cmd_build = self.real
        self.tmp.cleanup()

    def fake(self, ns):
        """A build that writes one file per part asked for (all when only is None)."""
        self.gen += 1
        self.asked.append(ns.only)
        d = Path(ns.parts_dir)
        d.mkdir(exist_ok=True)
        build.LAST_BUILD.clear()
        data = pt.load_item(self.item)
        for num, nm in pt.build_names(data):
            if ns.only and nm not in ns.only:
                continue
            fn = pt.part_file_name(num, nm, ns.tail)
            (d / fn).write_bytes(f"g{self.gen}".encode())            # the generation is the content
            (d / fn.replace(".pdf", "-11x17.pdf")).write_bytes(f"g{self.gen}".encode())
            rec = {"part": nm, "pages": 2, "content_pages": 2, "staff_mm": 6.0,
                   "staff_max_mm": 6.0, "width_mm": 6.0, "gap": 10.0,
                   "file": fn, "large": fn.replace(".pdf", "-11x17.pdf")}
            if nm in self.folds:
                stem = fn[:-4]
                more = {"foldout": f"{stem}-foldout-sheets.pdf", "flaps": f"{stem}-foldout-flaps.pdf",
                        "assemble": f"{stem}-assemble.txt", "large_flaps": f"{stem}-foldout-flaps-11x17.pdf"}
                for f in more.values():
                    (d / f).write_bytes(f"g{self.gen}".encode())
                rec.update(foldouts=1, **more)
            build.LAST_BUILD.append(rec)
        return 0

    def build(self, only=None):
        before = len(self.asked)
        with open(os.devnull, "w") as dn, contextlib.redirect_stdout(dn):
            rc = build.run_build(self.item, only)
        self.assertEqual(len(self.asked), before + 1)    # run_build reached the fake cmd_build
        return rc

    def files(self, sub="parts"):
        return sorted(p.name for p in (self.item / sub).iterdir())

    def gens(self, sub="parts"):
        """{part file: generation that wrote it}, large copies left out."""
        return {f.split("--")[0]: (self.item / sub / f).read_text()
                for f in self.files(sub) if "11x17" not in f}

    def test_a_partial_build_keeps_the_fold_out_files_of_the_other_parts(self):
        """0.8.37: keep_other_parts copied `file` and `large` only; the fold-out sheet, flap and
        assembly files of the other parts were lost, while their records still named them."""
        self.folds = {"C"}
        self.build()                                           # full: C gets its fold-out files
        c_files = [f for f in self.files() if f.startswith("03-c-")]
        self.assertEqual(len(c_files), 6, c_files)
        self.build(["A"])
        self.assertEqual(self.asked[-1], ["A"])                # a partial build, not a full one
        self.assertEqual([f for f in self.files() if f.startswith("03-c-")], c_files)
        rec = {r["part"]: r for r in pt.load_item(self.item)["built"]["parts"]}["C"]
        for k in pt.PART_FILE_KEYS:
            self.assertTrue((self.item / "parts" / rec[k]).is_file(), k)

    def test_a_build_drops_the_pins_of_a_part_whose_lines_changed(self):
        """0.8.39: emit marks the record (pins_dropped) when the pins were made for other lines;
        run_build then removes the pins from the settings, keeps the breaks, and the mark."""
        d = pt.load_item(self.item)
        pt.apply_set(d, ["A:breaks=5"])
        pt.set_pins(d, "A", [3, 4], "old-lines")
        pt.set_pins(d, "B", [7], "old-lines")
        pt.save_item(self.item, d)
        real = self.fake

        def fake(ns):
            rc = real(ns)
            for r in build.LAST_BUILD:
                if r["part"] == "A":
                    r["pins_dropped"] = True
            return rc
        build.cmd_build = fake
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            build.run_build(self.item, ["A"])
        d = pt.load_item(self.item)
        self.assertIsNone(pt.part_pins(d, "A"))
        self.assertEqual(d["layout"]["parts"]["A"]["breaks"], [5])
        self.assertEqual(pt.part_pins(d, "B")["bars"], [7])               # another part: kept
        self.assertFalse(any("pins_dropped" in r for r in d["built"]["parts"]))
        self.assertIn("A: the lines changed", out.getvalue())

    def test_set_pins_and_part_pins(self):
        d = {"layout": {}}
        pt.set_pins(d, "A", [9, 3, 3], "sig")
        self.assertEqual(pt.part_pins(d, "A"), {"bars": [3, 9], "lines": "sig"})
        pt.set_pins(d, "A", [])
        self.assertIsNone(pt.part_pins(d, "A"))
        self.assertEqual(d["layout"], {})                                 # nothing empty is left

    def test_a_missing_fold_out_file_makes_the_build_whole(self):
        self.folds = {"C"}
        self.build()
        next(f for f in (self.item / "parts").iterdir() if f.name.endswith("-assemble.txt")).unlink()
        self.build(["A"])
        self.assertIsNone(self.asked[-1])                      # a set that cannot keep C: built whole

    def test_part_file_keys_name_every_file_of_a_record(self):
        """Every file a build or repage records (render_plan, large_copies) is a PART_FILE_KEY."""
        import re
        src = "".join(Path(SRC).parent.joinpath("partitor", m + ".py").read_text(encoding="utf-8")
                      for m in ("build", "render", "cli_items"))
        named = set(re.findall(r'"(\w+)": (?:LAST_RENDER\["\w+"\]|fn\.name|large_copy\()', src))
        named |= {"large", "large_flaps"}
        self.assertTrue({"file", "foldout", "flaps", "assemble"} <= named, named)
        self.assertTrue(named - {"foldouts"} <= set(pt.PART_FILE_KEYS), named - set(pt.PART_FILE_KEYS))

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
        build.cmd_build = lambda ns: self.asked.append(ns.only) or 1     # fails, and is seen
        self.assertEqual(self.build(["B"]), 1)
        self.assertEqual(self.asked[-1], ["B"])
        self.assertEqual(self.files(), before)

    def test_menu_r_with_words(self):
        calls = []
        real = cli_items.cmd_rebuild
        cli_items.cmd_rebuild = lambda ns: calls.append((ns.parts, ns.jobs)) or 0
        answers = iter(["r Trombones 2-3", "R", "b"])
        real_in = builtins.input
        builtins.input = lambda prompt="": next(answers)
        try:
            with open(os.devnull, "w") as dn, contextlib.redirect_stdout(dn):
                pt.item_menu(self.item)
        finally:
            builtins.input = real_in
            cli_items.cmd_rebuild = real
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
                    self.assertEqual(build.run_build(item), 0)
                    serial = self.sig(item)
                    os.environ["PARTITOR_JOBS"] = "2"
                    self.assertEqual(build.run_build(item), 0)
                    self.assertEqual(self.sig(item), serial)             # workers: the same files
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    self.assertEqual(build.run_build(item, ["Alto"]), 0)
                self.assertIn("analysing 2 of 3 page(s)", buf.getvalue())   # page 2 only rests
                self.assertEqual(self.sig(item), serial)                 # Alto the same, Bass kept
            finally:
                if env is None:
                    os.environ.pop("PARTITOR_JOBS", None)
                else:
                    os.environ["PARTITOR_JOBS"] = env

    def test_a_short_name_reaches_the_group_part(self):
        """`Part:short=...` is in the labels of the group's later lines (the build
        passes it to finish_lines); without it the rule's form stands."""
        with tempfile.TemporaryDirectory() as tmp:
            one = Path(tmp, "page.pdf")
            make_score_pdf(str(one), systems=1, staves=2,
                           labels=("Alto Trombone", "Bass Trombone"), title="")
            doc = pymupdf.open()
            for _ in range(3):
                doc.insert_pdf(pymupdf.open(str(one)))
            item = Path(tmp, "2026-10-0001-c-t")
            item.mkdir()
            doc.save(str(item / "2026-10-0001-source.pdf"))
            pt.save_item(item, {"id": "2026-10-0001", "slug": "c-t", "created": "2026-10-26"})
            env = os.environ.get("PARTITOR_JOBS")
            os.environ["PARTITOR_JOBS"] = "1"
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(pt.run_detect(item, None, "T", "C D"), 0)
                    d = pt.load_item(item)
                    d["groups"] = {"Duo": list(d["parts"])}
                    self.assertEqual(d["parts"], ["Alto Trombone", "Bass Trombone"])
                    pt.save_item(item, d)
                    self.assertEqual(build.run_build(item, ["Duo"]), 0)
                    rule = self.text(item, "duo")
                    pt.apply_set(d, ["Alto Trombone:short=A. Tbn."])
                    pt.save_item(item, d)
                    self.assertEqual(build.run_build(item, ["Duo"]), 0)
                    own = self.text(item, "duo")
            finally:
                if env is None:
                    os.environ.pop("PARTITOR_JOBS", None)
                else:
                    os.environ["PARTITOR_JOBS"] = env
        self.assertIn("Alto Tro.", rule)
        self.assertNotIn("A. Tbn.", rule)
        self.assertIn("A. Tbn.", own)
        self.assertNotIn("Alto Tro.", own)
        self.assertIn("Bass Tro.", own)                      # the other staff keeps the rule

    @staticmethod
    def text(item, name):
        f = next(p for p in sorted((item / "parts").glob(f"*-{name}-*.pdf"))
                 if "11x17" not in p.name)
        return " ".join(pg.get_text() for pg in pymupdf.open(str(f)))

    @staticmethod
    def sig(item):
        import hashlib
        return {p.name: [hashlib.md5(pg.get_pixmap(dpi=40).samples).hexdigest()
                         for pg in pymupdf.open(str(p))]
                for p in sorted((item / "parts").glob("*.pdf"))}


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

    def test_apply_set_part_paper_and_binding(self):
        data = {"title": "A", "layout": {}, "parts": ["Trombones"]}
        pt.apply_set(data, ["Trombones:paper=letter", "Trombones:binding=12.7",
                            "Trombones:margin_side=8", "paper=ledger", "binding=0"])
        self.assertEqual(data["layout"]["paper"], "ledger")
        self.assertEqual(data["layout"]["binding"], 0.0)
        self.assertEqual(data["layout"][pt.PART_LAYOUT_KEY]["Trombones"],
                         {"paper": "letter", "binding": 12.7, "margin_side": 8.0})
        pt.apply_set(data, ["Trombones:foldside=left", "Trombones:foldouts=on"])
        self.assertEqual(data["layout"][pt.PART_LAYOUT_KEY]["Trombones"]["foldside"], "left")
        for bad in (["Trombones:paper=a3"], ["Trombones:binding=x"], ["Trombones:binding=-2"],
                    ["Trombones:foldside=up"], ["foldside=up"]):
            with self.subTest(bad=bad):
                before = repr(data["layout"])
                with self.assertRaises(ValueError):
                    pt.apply_set(data, bad)
                self.assertEqual(repr(data["layout"]), before)

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

    def test_apply_set_short_name(self):
        data = {"parts": ["Alto", "Org R", "Continuo"], "skip": ["Org R"],
                "groups": {"Trbs": ["Alto"]}, "layout": {}}
        self.assertEqual(pt.apply_set(data, ["Alto:short=A. Tbn."]), ["Alto:short: auto -> A. Tbn."])
        self.assertEqual(data["layout"]["parts"], {"Alto": {"short": "A. Tbn."}})
        # a part not extracted on its own (a group member) can have one too
        pt.apply_set(data, ["Org R:short=Org."])
        self.assertEqual(data["layout"]["parts"]["Org R"], {"short": "Org."})
        self.assertEqual(pt.apply_set(data, ["Alto:short=auto"]), ["Alto:short: A. Tbn. -> auto"])
        self.assertNotIn("Alto", data["layout"]["parts"])          # back to the rule, nothing kept
        for bad in (["Nobody:short=x"], ["short=x"], ["Alto:short=" + "x" * 25],
                    ["Alto:short=a\nb"]):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                pt.apply_set(data, bad)
        self.assertIn("short", pt.PART_SET_KEYS)

    def test_short_name_follows_a_rename(self):
        data = {"parts": ["S", "A", "Org R"], "layout": {"parts": {"A": {"short": "Alt."}}},
                "systems": [{"map": ["S", "A", "Org R"], "clefs": ["G", "C3", "G"]}]}
        self.assertEqual(pt.apply_part_ops(data, "2=Altus"), "")
        self.assertEqual(data["layout"]["parts"], {"Altus": {"short": "Alt."}})

    def test_short_menu_sets_and_clears(self):
        item = self.item_with_choice()
        data = pt.load_item(item)
        data["groups"] = {"Low": ["Tenor", "Bass"]}
        pt.save_item(item, data)
        env = {"PARTITOR_LIBRARY": str(self.share)}
        with mock.patch.dict(os.environ, env):
            _, out = self.quiet_input(["1", "Te.", "", ""], cli_parts.short_menu, data)
        self.assertEqual(pt.load_item(item)["layout"]["parts"], {"Tenor": {"short": "Te."}})
        self.assertIn("Tenor: Ten.  (rule)", out)             # shown by the rule first
        self.assertIn("Tenor: Te.  (by hand)", out)
        data = pt.load_item(item)
        with mock.patch.dict(os.environ, env):
            self.quiet_input(["Tenor", "auto", ""], cli_parts.short_menu, data)
        self.assertNotIn("parts", pt.load_item(item).get("layout") or {})

    def test_item_menu_key_h_sets_a_short_name(self):
        item = self.item_with_choice()
        data = pt.load_item(item)
        data["groups"] = {"Low": ["Tenor", "Bass"]}
        pt.save_item(item, data)
        with mock.patch.dict(os.environ, {"PARTITOR_LIBRARY": str(self.share)}):
            self.quiet_input(["h", "2", "B.", "", "b"], pt.item_menu, item)
        self.assertEqual(pt.load_item(item)["layout"]["parts"], {"Bass": {"short": "B."}})

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
        for bad in (["Nobody:gap=9"], ["Canto:large=off"], ["Canto:title=x"]):
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

    def test_system_cut_and_set_join(self):
        item = self.share / "library" / "2026-004-j"
        item.mkdir()
        pt.save_item(item, {"id": "2026-004", "slug": "j", "parts": ["A", "B"],
                            "systems": [{"id": "p5.s1", "staves": 4, "map": ["?"] * 4},
                                        {"id": "p5.s2", "staves": 13, "map": ["B"] * 13},
                                        {"id": "p6.s1", "staves": 17, "map": ["B"] * 17}]})
        data = pt.load_item(item)
        self.assertEqual(pt.system_cut(data, "p5.s1"), "p5:4")
        self.assertEqual(pt.system_cut(data, "p5.s2"), "")        # nothing below it
        self.assertEqual(pt.system_cut(data, "p6.s1"), "")
        self.assertEqual(pt.system_cut(data, "p9.s1"), "")
        self.assertEqual(pt.system_cut(data, "nonsense"), "")
        self.assertEqual(pt.set_join(item, "p5:4"), "")
        self.assertEqual(pt.set_join(item, "p2:3"), "")
        self.assertEqual(pt.load_item(item)["system_joins"], ["p2:3", "p5:4"])   # page order
        self.assertIn("already", pt.set_join(item, "p5:4"))
        self.assertIn("not a join", pt.set_join(item, "5:4"))
        self.assertEqual(pt.set_join(item, "p5:4", False), "")
        self.assertIn("not joined", pt.set_join(item, "p5:4", False))
        self.assertEqual(pt.set_join(item, "p2:3", False), "")
        self.assertNotIn("system_joins", pt.load_item(item))

    def drop_item(self):
        item = self.share / "library" / "2026-006-d"
        item.mkdir()
        sysd = lambda i, m, **kw: {"id": i, "staves": 2, "map": m, "clefs": ["G2", "F4"],   # noqa: E731
                                   "bars": 4, "widths": [20.0] * 4, **kw}
        pt.save_item(item, {"id": "2026-006", "slug": "d", "parts": ["A", "B"],
                            "systems": [sysd("p1.s1", ["A", "B"]), sysd("p1.s2", ["A", "B"]),
                                        sysd("p1.s3", ["A", "B"])]})
        return item

    def test_set_drop_and_undrop(self):
        item = self.drop_item()
        self.assertEqual(pt.set_drop(item, ["p1.s1", "p1.s2"]), "")
        data = pt.load_item(item)
        self.assertEqual(data["systems_drop"], ["p1.s1", "p1.s2"])
        self.assertEqual(data["systems"][0]["map"], ["-", "-"])
        self.assertEqual(data["systems"][2]["bar"], 1)               # the count starts here
        self.assertIn("systems left out", data["pending"])
        self.assertIn("dropped already", pt.set_drop(item, ["p1.s1"]))
        self.assertIn("no such system", pt.set_drop(item, ["p9.s1"]))
        self.assertEqual(pt.set_drop(item, ["p1.s2"], False), "")
        data = pt.load_item(item)
        self.assertEqual(data["systems_drop"], ["p1.s1"])
        self.assertEqual(data["systems"][1]["map"], ["?", "?"])
        self.assertEqual(data["systems"][1]["suggest"], ["A", "B"])   # the map of a like system
        self.assertEqual(data["systems"][2]["bar"], 5)
        self.assertIn("is not dropped", pt.set_drop(item, ["p1.s2"], False))
        self.assertEqual(pt.set_drop(item, ["p1.s1"], False), "")
        self.assertNotIn("systems_drop", pt.load_item(item))

    def test_dropped_systems_survive_a_new_analysis(self):
        item = self.drop_item()
        self.assertEqual(pt.set_drop(item, ["p1.s1"]), "")
        keep = pt.load_item(item)
        fresh = {"id": "2026-006", "slug": "d", "parts": ["A", "B"],
                 "systems": [{"id": "p1.s1", "staves": 2, "map": ["A", "B"], "clefs": ["G2", "F4"],
                              "bars": 4, "widths": [20.0] * 4},
                             {"id": "p1.s2", "staves": 2, "map": ["A", "B"], "clefs": ["G2", "F4"],
                              "bars": 4, "widths": [20.0] * 4}]}
        pt.save_item(item, fresh)
        data = pt.merge_item_keys(item, keep, again=True)
        self.assertEqual(data["systems_drop"], ["p1.s1"])
        self.assertEqual(data["systems"][0]["map"], ["-", "-"])
        self.assertEqual(data["systems"][1]["bar"], 1)

    def test_choose_maps_d_and_all_zeros_drop_without_a_suggestion(self):
        item = self.share / "library" / "2026-007-e"
        item.mkdir()
        q = lambda i: {"id": i, "staves": 2, "map": ["?", "?"], "clefs": ["G2", "F4"],  # noqa: E731
                       "bars": 4, "widths": [20.0] * 4}
        pt.save_item(item, {"id": "2026-007", "slug": "e", "parts": ["A", "B"],
                            "systems": [q("p1.s1"), q("p1.s2"), q("p1.s3")]})
        answers = iter(["d", "0 0", "1 2"])
        real = builtins.input
        builtins.input = lambda prompt="": next(answers)
        try:
            with open(os.devnull, "w") as devnull, contextlib.redirect_stdout(devnull):
                self.assertTrue(pt.choose_maps(item))
        finally:
            builtins.input = real
        data = pt.load_item(item)
        self.assertEqual([s["map"] for s in data["systems"]], [["-", "-"], ["-", "-"], ["A", "B"]])
        self.assertEqual(data["systems_drop"], ["p1.s1", "p1.s2"])
        self.assertEqual(data["systems"][2]["bar"], 1)

    def test_choose_maps_j_joins_and_asks_again(self):
        item = self.share / "library" / "2026-005-k"
        item.mkdir()
        pt.save_item(item, {"id": "2026-005", "slug": "k", "parts": ["A", "B", "C"],
                            "systems": [{"id": "p1.s1", "staves": 1, "map": ["?"],
                                         "suggest": ["C"]},
                                        {"id": "p1.s2", "staves": 2, "map": ["A", "B"]}]})
        calls = []

        def fake_reanalyse(it):
            # what the real analysis gives after the join: one system of three staves
            calls.append(pt.load_item(it).get("system_joins"))
            d = pt.load_item(it)
            d["systems"] = [{"id": "p1.s1", "staves": 3, "map": ["?"] * 3,
                             "suggest": ["A", "B", "C"]}]
            pt.save_item(it, d)
            return 0
        with mock_attr(cli_parts, "reanalyse", fake_reanalyse):
            # j on the one-staff system; then Enter on the joined system
            _, out = self.quiet_input(["j", ""], pt.choose_maps, item)
        self.assertEqual(calls, [["p1:1"]])          # the join was stored before the analysis
        self.assertIn("p1.s1 and the system below it are one system (p1:1)", out)
        data = pt.load_item(item)
        self.assertEqual([s["map"] for s in data["systems"]], [["A", "B", "C"]])
        self.assertEqual(data["system_joins"], ["p1:1"])

    def test_choose_maps_j_on_the_last_system_is_refused(self):
        item = self.share / "library" / "2026-006-l"
        item.mkdir()
        pt.save_item(item, {"id": "2026-006", "slug": "l", "parts": ["A", "B"],
                            "systems": [{"id": "p1.s1", "staves": 2, "map": ["?", "?"],
                                         "suggest": ["A", "B"]}]})
        with mock_attr(cli_parts, "reanalyse", lambda it: self.fail("no analysis")):
            _, out = self.quiet_input(["j", ""], pt.choose_maps, item)
        self.assertIn("no system below p1.s1 on its page to join", out)
        self.assertEqual(pt.load_item(item)["systems"][0]["map"], ["A", "B"])
        self.assertNotIn("system_joins", pt.load_item(item))

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

    def test_proof_labels_are_large(self):
        # part names 13 pt, system ids 14 pt (they were 9 and 11)
        item = self.item_with_choice()
        pt.proof_from_preview(item)
        sizes = {}
        for blk in pymupdf.open(pt.item_file(item, "proof.pdf"))[0].get_text("dict")["blocks"]:
            for ln in blk.get("lines", []):
                for sp_ in ln["spans"]:
                    sizes[sp_["text"].strip()] = sp_["size"]
        self.assertGreaterEqual(sizes["p3.s1"], 14.0)
        self.assertGreaterEqual(sizes["Alto"], 13.0)
        self.assertGreaterEqual(sizes["? Tenor"], 13.0)

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

    def test_keep_one_staff_of_a_two_staff_part(self):
        # Riccio La Pichi: Violin, Trombone and the organ twice (right and left hand);
        # only the left hand (the continuo line) is wanted
        data = {"parts": ["Violin", "Trombone", "Organ"],
                "systems": [{"map": ["Violin", "Trombone", "Organ", "Organ"]},
                            {"map": ["?", "?", "?"], "suggest": ["Trombone", "Organ", "Organ"]},
                            {"map": ["Violin", "Trombone", "Organ"]}]}
        d1 = __import__("copy").deepcopy(data)
        self.assertEqual(pt.apply_part_ops(d1, "3/last"), "")
        self.assertEqual(d1["systems"][0]["map"], ["Violin", "Trombone", "-", "Organ"])
        self.assertEqual(d1["systems"][1]["suggest"], ["Trombone", "-", "Organ"])
        self.assertEqual(d1["systems"][2]["map"], ["Violin", "Trombone", "Organ"])   # one staff: kept
        d2 = __import__("copy").deepcopy(data)
        self.assertEqual(pt.apply_part_ops(d2, "3/1; 3=Continuo"), "")
        self.assertEqual(d2["systems"][0]["map"], ["Violin", "Trombone", "Continuo", "-"])
        for bad in ("3/0", "3/x", "9/1"):
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

    def test_analyse_join_and_unjoin_end_to_end(self):
        # two systems of three staves; `analyse --join p1:3` makes one of six,
        # every later analysis keeps it, `--unjoin` takes it back
        make_score_pdf(str(self.share / "inbox" / "chorale.pdf"))
        r = self.run_cli("new", stdin="1\n\nTest Chorale\nJ. H. Schein\n\nA,T,B\n\n\n")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        item = next((self.share / "library").iterdir())
        self.assertEqual([s["staves"] for s in pt.load_item(item)["systems"]], [3, 3])
        r = self.run_cli("analyse", "1", "--join", "p1:3", "--yes")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("join:  p1:3 joined", r.stdout)
        data = pt.load_item(item)
        self.assertEqual([s["staves"] for s in data["systems"]], [6])
        self.assertEqual(data["system_joins"], ["p1:3"])
        r = self.run_cli("analyse", "1", "--yes")                  # kept by a later analysis
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("1 join(s) kept", r.stdout)
        data = pt.load_item(item)
        self.assertEqual([s["staves"] for s in data["systems"]], [6])
        self.assertEqual(data["system_joins"], ["p1:3"])
        r = self.run_cli("analyse", "1", "--join", "p1:3")          # twice: refused
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("joined already", r.stdout + r.stderr)
        r = self.run_cli("analyse", "1", "--unjoin", "p1:3", "--yes")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        data = pt.load_item(item)
        self.assertEqual([s["staves"] for s in data["systems"]], [3, 3])
        self.assertNotIn("system_joins", data)

    def test_analyse_drop_and_undrop_end_to_end(self):
        # `analyse --drop p1.s1` leaves the system out without an analysis, every later
        # analysis keeps it, the next system starts at bar 1; `--undrop` puts it back
        make_score_pdf(str(self.share / "inbox" / "chorale.pdf"))
        r = self.run_cli("new", stdin="1\n\nTest Chorale\nJ. H. Schein\n\nA,T,B\n\n\n")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        item = next((self.share / "library").iterdir())
        r = self.run_cli("analyse", "1", "--drop", "p1.s1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("drop:  p1.s1 left out", r.stdout)
        data = pt.load_item(item)
        self.assertEqual(data["systems_drop"], ["p1.s1"])
        self.assertEqual(data["systems"][0]["map"], ["-", "-", "-"])
        self.assertEqual(data["systems"][1]["bar"], 1)
        r = self.run_cli("analyse", "1", "--yes", stdin="\n")          # kept by a later analysis
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        data = pt.load_item(item)
        self.assertEqual(data["systems_drop"], ["p1.s1"])
        self.assertEqual(data["systems"][0]["map"], ["-", "-", "-"])
        r = self.run_cli("analyse", "1", "--drop", "p1.s1")             # twice: refused
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("dropped already", r.stdout + r.stderr)
        r = self.run_cli("analyse", "1", "--drop", "p9.s1")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("no such system", r.stdout + r.stderr)
        r = self.run_cli("analyse", "1", "--undrop", "p1.s1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        data = pt.load_item(item)
        self.assertNotIn("systems_drop", data)
        self.assertNotIn("-", data["systems"][0]["map"])

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

    def test_new_jobs_reaches_the_detect_and_build_steps(self):
        one = self.share / "one.pdf"
        make_score_pdf(str(one))
        doc = pymupdf.open()
        for _ in range(2):
            doc.insert_pdf(pymupdf.open(str(one)))
        doc.save(str(self.share / "inbox" / "chorale.pdf"))
        one.unlink()
        r = self.run_cli("new", "--jobs", "2", stdin="1\n\nTest Chorale\nJ. H. Schein\n\nA,T,B\n\n\n")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("analysing 2 page(s) with 2 worker(s)", r.stdout)     # detect
        self.assertIn("analysing 2 of 2 page(s) with 2 worker(s)", r.stdout)  # build
        item = next((self.share / "library").iterdir())
        self.assertEqual(pt.item_status(pt.load_item(item)), "built")
        h = self.run_cli("new", "--help")
        self.assertIn("--jobs", h.stdout)

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


@needs_deps
class TestItemLock(unittest.TestCase):
    """item_lock and locks_item (0.8.38): one command at a time on one item."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "inbox").mkdir()
        self.item = self.root / "library" / "2026-10-0007-x"
        self.item.mkdir(parents=True)
        pt.save_item(self.item, {"id": "2026-10-0007", "slug": "x", "parts": ["A"], "layout": {}})
        self.env = mock.patch.dict(os.environ, {"PARTITOR_LIBRARY": str(self.root)})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def holder(self):
        """A second process that holds the lock of the item until it is stopped."""
        code = ("import fcntl, os, sys, time; fd = os.open(sys.argv[1], os.O_RDONLY); "
                "fcntl.flock(fd, fcntl.LOCK_EX); print('held', flush=True); time.sleep(60)")
        p = subprocess.Popen([sys.executable, "-c", code, str(self.item)], stdout=subprocess.PIPE, text=True)
        self.addCleanup(self.stop, p)
        self.assertEqual(p.stdout.readline().strip(), "held")
        return p

    @staticmethod
    def stop(p):
        p.kill()
        p.wait()
        p.stdout.close()

    def test_a_second_process_cannot_take_the_lock(self):
        self.holder()
        with self.assertRaises(pt.ItemBusy) as cm:
            with pt.item_lock(self.item):
                self.fail("got the lock")
        self.assertEqual(str(cm.exception), "2026-10-0007")

    def test_the_same_process_may_lock_again_and_the_lock_ends_with_the_outer_one(self):
        lib = sys.modules["partitor.library"]
        with pt.item_lock(self.item):
            with pt.item_lock(self.item):
                self.assertEqual(len(lib._LOCKS), 1)
            self.assertEqual(len(lib._LOCKS), 1)
        self.assertEqual(lib._LOCKS, {})
        code = ("import fcntl, os, sys; fd = os.open(sys.argv[1], os.O_RDONLY); "
                "fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB); print('free')")
        r = subprocess.run([sys.executable, "-c", code, str(self.item)], capture_output=True, text=True)
        self.assertEqual(r.stdout.strip(), "free", r.stderr)

    def test_set_on_an_item_in_use_stops_and_changes_nothing(self):
        """A `set` during a rebuild was saved, then marked built by the rebuild (0.8.38)."""
        self.holder()
        before = Path(self.item, "2026-10-0007-score.yaml").read_text(encoding="utf-8")
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            with self.assertRaises(SystemExit):
                pt.cmd_set(argparse.Namespace(id="2026-10-0007", pairs=["gap=12"], build=False))
        self.assertIn("item 2026-10-0007 is in use", out.getvalue())
        self.assertEqual(Path(self.item, "2026-10-0007-score.yaml").read_text(encoding="utf-8"), before)

    def test_without_locks_on_the_file_system_the_command_goes_on(self):
        lib = sys.modules["partitor.library"]

        def no_locks(fd, op):
            raise OSError(95, "Operation not supported")
        with mock.patch.object(lib.fcntl, "flock", no_locks):
            with contextlib.redirect_stdout(io.StringIO()):
                rc = pt.cmd_set(argparse.Namespace(id="2026-10-0007", pairs=["gap=12"], build=False))
        self.assertEqual(rc, 0)
        self.assertEqual(pt.load_item(self.item)["layout"]["gap"], 12.0)

    def test_set_with_no_pairs_lists_every_key_and_changes_nothing(self):
        """0.8.46 (F9): `set ID` alone listed nothing (a usage error); now every key of `set`."""
        data = pt.load_item(self.item)
        data["layout"] = {"gap": 12.0, "parts": {"A": {"page_count": 4, "foldouts": "on"}}}
        pt.save_item(self.item, data)
        before = Path(self.item, "2026-10-0007-score.yaml").read_text(encoding="utf-8")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = pt.cmd_set(argparse.Namespace(id="2026-10-0007", pairs=[], build=False))
        self.assertEqual(rc, 0)
        text = out.getvalue()
        for name, (lk, _) in pt.SET_KEYS.items():
            if lk is not None:
                self.assertRegex(text, rf"\n[ *] {name} ", name)
        self.assertRegex(text, r"\n\* gap +12\.0 +10\.0 +number")
        self.assertIn("foldouts       off        off        off | on", text)
        self.assertIn("A: pages=4, foldouts=on", text)                       # the names `set` takes
        self.assertEqual(Path(self.item, "2026-10-0007-score.yaml").read_text(encoding="utf-8"), before)
        r = subprocess.run([sys.executable, str(Path(LIB, "partitor-engine")), "set", "--help"],
                           capture_output=True, text=True, env={**os.environ, "PARTITOR_ALLOW_ROOT": "1"})
        self.assertIn("none: list every key", " ".join(r.stdout.split()))

    def test_every_command_that_changes_an_item_holds_its_lock(self):
        for name in ("cmd_set", "cmd_rebuild", "cmd_repage", "cmd_pages", "cmd_plan", "cmd_parts",
                     "cmd_groups", "cmd_bars", "cmd_meta", "cmd_analyse", "cmd_proof", "cmd_rename",
                     "cmd_reid", "cmd_expand", "cmd_contract"):
            self.assertTrue(hasattr(getattr(pt, name), "__wrapped__"), name)
        self.assertFalse(hasattr(pt.cmd_show, "__wrapped__"))


class TestYamlLoad(unittest.TestCase):
    """config.yaml_load (0.8.35): the C loader of libyaml, the same data as yaml.safe_load."""

    DATA = {"id": "2026-10-0001", "title": "Maria, gegreüsset — “seist” du", "pages": "1-12",
            "dpi": 400, "gap": 10.0, "zero": "08", "flag": "on", "none": None, "date": "2026-10-28 00:05",
            "map": ["Alto", "-", "?"], "nested": {"Trombones": {"breaks": [35, 61], "short": "Trb."}},
            "built": {"parts": [{"part": "A", "staff_mm": 5.56, "reflow": False}]}}

    def test_same_data_as_safe_load_on_a_saved_item(self):
        import yaml
        with tempfile.TemporaryDirectory() as d:
            item = Path(d, "2026-10-0001-x")
            item.mkdir()
            pt.save_item(item, dict(self.DATA))
            text = Path(item, "2026-10-0001-score.yaml").read_text(encoding="utf-8")
            self.assertEqual(pt.yaml_load(text), yaml.safe_load(text))
            self.assertEqual(pt.load_item(item), yaml.safe_load(text))

    def test_uses_the_c_loader_when_there_is_one(self):
        import yaml
        if not getattr(yaml, "CSafeLoader", None):
            self.skipTest("PyYAML without libyaml")
        seen = []
        real = yaml.load

        def spy(text, Loader):
            seen.append(Loader)
            return real(text, Loader=Loader)
        with mock.patch.object(yaml, "load", spy):
            pt.yaml_load("a: 1\n")
        self.assertEqual(seen, [yaml.CSafeLoader])

    def test_pure_python_loader_without_libyaml_and_no_unsafe_tags(self):
        import yaml
        saved = getattr(yaml, "CSafeLoader", None)
        try:
            if hasattr(yaml, "CSafeLoader"):
                delattr(yaml, "CSafeLoader")
            self.assertEqual(pt.yaml_load("a: [1, 2]\n"), {"a": [1, 2]})
        finally:
            if saved is not None:
                yaml.CSafeLoader = saved
        with self.assertRaises(yaml.YAMLError):          # safe: no Python objects
            pt.yaml_load("x: !!python/object/apply:os.system ['true']\n")

    def test_load_item_reads_through_yaml_load(self):
        cfg = sys.modules["partitor.config"]
        seen = []
        real = cfg.yaml_load
        with tempfile.TemporaryDirectory() as d:
            item = Path(d, "2026-10-0001-x")
            item.mkdir()
            pt.save_item(item, {"id": "2026-10-0001"})
            with mock_attr(cfg, "yaml_load", lambda t: seen.append(1) or real(t)):
                pt.load_item(item)
        self.assertEqual(seen, [1])


class TestBuildModule(unittest.TestCase):
    """build owns run_build and cmd_build (R1 names, no shim) and the LAST_BUILD list."""

    def test_patched_names_are_held_by_the_build_module_only(self):
        self.assertEqual(package_holders("run_build"), ["partitor.build"])    # no copy anywhere
        self.assertEqual(package_holders("cmd_build"), ["partitor.build"])
        self.assertEqual(build.run_build.__module__, "partitor.build")
        self.assertEqual(build.cmd_build.__module__, "partitor.build")
        self.assertIs(pt.run_detect, build.run_detect)         # the view finds it on its owner
        self.assertIs(pt.annotate_proof, sys.modules["partitor.proof"].annotate_proof)

    def test_last_build_is_one_list_changed_in_place(self):
        self.assertIs(pt.LAST_BUILD, build.LAST_BUILD)
        build.LAST_BUILD.clear()
        build.LAST_BUILD.append({"part": "A"})
        self.assertEqual(pt.LAST_BUILD, [{"part": "A"}])
        build.LAST_BUILD.clear()
        self.assertIs(pt.LAST_BUILD, build.LAST_BUILD)

    def test_run_build_calls_the_cmd_build_of_the_build_module(self):
        seen = []
        real = build.cmd_build

        def spy(ns):
            seen.append(ns.parts_dir)
            return 1
        with tempfile.TemporaryDirectory() as tmp:
            item = Path(tmp, "2026-10-0007-x")
            item.mkdir()
            pt.save_item(item, {"id": "2026-10-0007", "slug": "x", "composer": "Schein",
                                "title": "Nun", "parts": ["A"], "layout": {}})
            (item / "2026-10-0007-source.pdf").write_bytes(b"%PDF")
            build.cmd_build = spy
            try:
                with open(os.devnull, "w") as dn, contextlib.redirect_stdout(dn):
                    rc = build.run_build(item)
            finally:
                build.cmd_build = real
        self.assertEqual(rc, 1)
        self.assertEqual(len(seen), 1)
        self.assertIs(build.cmd_build, real)

    def test_main_dispatches_build_through_the_module(self):
        if os.geteuid() == 0:
            self.skipTest("the engine refuses root")
        seen = []
        real_argv = sys.argv
        real = build.cmd_build
        build.cmd_build = lambda ns: seen.append(ns.pdf) or 7
        sys.argv = ["partitor", "build", "x.pdf"]
        try:
            rc = pt.main()
        finally:
            sys.argv = real_argv
            build.cmd_build = real
        self.assertEqual(rc, 7)
        self.assertEqual(seen, ["x.pdf"])


@needs_deps
class TestCliModules(unittest.TestCase):
    """The CLI helpers sit in cli_common; cmd_rebuild (an R1 name) sits in cli_items."""

    RING = ("saved", "_item_or_die", "_lib_or_die", "cmd_set", "_cmd_step", "bar_summary")

    def test_ring_helpers_are_one_set_of_objects_in_cli_common(self):
        common = sys.modules["partitor.cli_common"]
        for name in self.RING:
            with self.subTest(name=name):
                self.assertEqual(getattr(common, name).__module__, "partitor.cli_common")
                self.assertIs(getattr(pt, name), getattr(common, name))        # the view finds it
        for mod in ("cli_bars", "cli_parts", "cli_items"):
            m = sys.modules["partitor." + mod]
            for name in self.RING:
                self.assertNotIn(name, vars(m).get("__annotations__", {}))
                if name in vars(m):
                    self.assertIs(vars(m)[name], getattr(common, name))        # imported, not copied

    def test_cmd_rebuild_is_held_by_cli_items_only_and_main_dispatches_to_it(self):
        self.assertEqual(package_holders("cmd_rebuild"), ["partitor.cli_items"])
        self.assertEqual(cli_items.cmd_rebuild.__module__, "partitor.cli_items")
        if os.geteuid() == 0:
            self.skipTest("the engine refuses root")
        seen = []
        real_argv = sys.argv
        real = cli_items.cmd_rebuild
        cli_items.cmd_rebuild = lambda ns: seen.append(ns.id) or 5
        sys.argv = ["partitor", "rebuild", "2026-10-0001"]
        try:
            rc = pt.main()
        finally:
            sys.argv = real_argv
            cli_items.cmd_rebuild = real
        self.assertEqual(rc, 5)
        self.assertEqual(seen, ["2026-10-0001"])

    def test_the_menu_command_r_calls_the_cmd_rebuild_of_cli_items(self):
        seen = []
        real = cli_items.cmd_rebuild
        cli_items.cmd_rebuild = lambda ns: seen.append(ns.id) or 0
        answers = iter(["r", "b"])
        real_in = builtins.input
        builtins.input = lambda prompt="": next(answers)
        with tempfile.TemporaryDirectory() as tmp:
            item = Path(tmp, "2026-10-0008-x")
            item.mkdir()
            pt.save_item(item, {"id": "2026-10-0008", "slug": "x", "composer": "Schein",
                                "title": "Nun", "parts": ["A"], "layout": {}})
            try:
                with open(os.devnull, "w") as dn, contextlib.redirect_stdout(dn):
                    pt.item_menu(item)
            finally:
                builtins.input = real_in
                cli_items.cmd_rebuild = real
        self.assertEqual(seen, ["2026-10-0008"])
