# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""Tests for name helpers and the staff-to-part mapping.

Needs the venv packages (numpy, opencv, pymupdf, PyYAML); without them every test
is skipped. Run with the venv interpreter:

    venv/bin/python3 -m unittest -v tests/test_mapping.py

Shared helpers: tests/support.py.
"""
import os
import sys
import unittest
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from support import (  # noqa: E402,F401
    needs_deps,
    pt,
    setUpModule,
    tearDownModule,
)


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
