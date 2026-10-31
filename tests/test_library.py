# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""Tests for the library, safe builds and partial builds.

Needs the venv packages (numpy, opencv, pymupdf, PyYAML); without them every test
is skipped. Run with the venv interpreter:

    venv/bin/python3 -m unittest -v tests/test_library.py

Shared helpers: tests/support.py.
"""
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

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from support import (  # noqa: E402,F401
    SRC,
    cv2,
    make_score_pdf,
    needs_deps,
    np,
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
