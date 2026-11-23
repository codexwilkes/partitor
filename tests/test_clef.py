# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""Tests for clef signature, ambitus and spacing.

Needs the venv packages (numpy, opencv, pymupdf, PyYAML); without them every test
is skipped. Run with the venv interpreter:

    venv/bin/python3 -m unittest -v tests/test_clef.py

Shared helpers: tests/support.py.
"""
import inspect
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from support import (  # noqa: E402,F401
    SP,
    clef,
    cv2,
    flow_line,
    needs_deps,
    np,
    pt,
    pymupdf,
    render,
    setUpModule,
    tearDownModule,
)


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
        # bottom lines: treble E4, treble-8 E4 (no transposition), alto F3, tenor D3, bass G2
        self.assertEqual([pt.pitch_name(pt.CLEF_BOTTOM[c]) for c in ("G2", "G8", "C3", "C4", "F4")],
                         ["E4", "E4", "F3", "D3", "G2"])

    def test_template_bitmaps_are_unchanged(self):
        import hashlib
        # values recorded from the code before 0.8.76 (one new document for each template)
        want = {"G": ("5caac028a23901df1f4a26e60e1a88332a2191c8", 101),
                "C": ("5c0ab76a073e681452a59ec6f2205a7d543948c5", 47),
                "F": ("e19dc06633f98635deb36b6d0e15342ba5f3c740", 24)}
        clef._CLEF_TPL.clear()
        for kind, (sha, row) in want.items():
            tpl, ref = clef._clef_template(kind, 23.0, 1.0)
            self.assertEqual((hashlib.sha1(tpl.tobytes()).hexdigest(), ref), (sha, row), kind)

    def test_flute_gets_an_ambitus(self):
        data = {"parts": ["Flute"], "systems": [
            {"id": "p1.s1", "map": ["Flute"], "clefs": ["G2"], "steps": [[0, 8]]}]}
        self.assertEqual(pt.refresh_ambitus(data)["Flute"]["from"], "auto")

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
        pt.draw_ambitus(page, 150, 100, "G8", 30, 37)
        self.assertGreater(len(page.get_drawings()), 5)

    def _eight_staff(self, touching: bool, eight: bool = True):
        """A staff (sp 13) with the ink of a G clef's curl and, below it, a
        ring (the 8). touching: a neck joins the curl and the ring (an
        engraving where the 8 touches the curl)."""
        sp, x0 = 13, 40
        owner = np.full((200, 160), -1, np.int32)
        st = pt.Staff(0, 0, [60 + sp * k for k in range(5)], x0, 150)
        bot = int(st.bottom)
        owner[bot + int(0.6 * sp):bot + int(1.5 * sp), x0 + 18:x0 + 36] = 0   # the curl's ball
        if eight:
            cx, top = x0 + 27, bot + int(1.8 * sp)
            cv2.circle(owner, (cx, top + 6), 5, 0, 2)                         # the 8: ring with a hole
        if touching:
            owner[bot + int(1.4 * sp):bot + int(1.85 * sp), x0 + 26:x0 + 29] = 0
        return owner, st, sp

    def test_eight_below_separate(self):
        owner, st, sp = self._eight_staff(touching=False)
        self.assertTrue(clef._octave_eight_below(owner, st, 0, sp))

    def test_eight_below_touching_the_curl(self):
        # the 8 joined to the curl: one blob in the first window, wider than a digit
        owner, st, sp = self._eight_staff(touching=True)
        self.assertTrue(clef._octave_eight_below(owner, st, 0, sp))

    def test_eight_below_plain_treble(self):
        # a plain treble clef (curl only): no 8
        owner, st, sp = self._eight_staff(touching=False, eight=False)
        self.assertFalse(clef._octave_eight_below(owner, st, 0, sp))

    def test_treble8_ambitus_names_the_staff_pitch(self):
        # the same steps give the same names: no clef transposes
        def sysm(c):
            return {"id": "p1.s1", "map": ["A"], "clefs": [c], "steps": [[4, 9]]}
        _, n2 = pt.part_clef_steps({"parts": ["A"], "systems": [sysm("G2")]}, "A")
        _, n8 = pt.part_clef_steps({"parts": ["A"], "systems": [sysm("G8")]}, "A")
        self.assertEqual([pt.pitch_name(x) for x in n2], ["B4", "G5"])
        self.assertEqual([pt.pitch_name(x) for x in n8], ["B4", "G5"])

    def test_ambitus_clef_smoothing(self):
        def sysm(i, clef, steps):
            return {"id": f"p{i}.s1", "map": ["T"], "clefs": [clef], "steps": [steps]}
        # one misread system (C3 among F4) and a missed tenor 8
        data = {"parts": ["T"], "systems": [sysm(1, "F4", [0, 4]), sysm(2, "C3", [0, 8]),
                                            sysm(3, "F4", [1, 5])]}
        self.assertEqual(pt.refresh_ambitus(data)["T"]["range"], "G2-A3")
        data = {"parts": ["T"], "systems": [sysm(1, "G8", [0, 4]), sysm(2, "G2", [0, 8]),
                                            sysm(3, "G8", [1, 5])]}
        self.assertEqual(pt.refresh_ambitus(data)["T"]["range"], "E4-F5")
        # G2 staves are not changed to G8 when part of the part reads G8
        data = {"parts": ["T"], "systems": [sysm(1, "G8", [0, 4]), sysm(2, "G8", [0, 8]),
                                            sysm(3, "G2", [1, 5]), sysm(4, "G2", [1, 5])]}
        self.assertEqual([it[0] for it in pt.part_clef_seq(data, "T")], ["G8", "G8", "G2", "G2"])
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

    def _stem_staff(self, flag: bool, sharp: bool = False, step: int = 5):
        """A staff (sp 20) with one head on `step` (5) and a stem down from it.
        flag: the curl of an eighth's flag at the stem's foot (narrower
        than a head). sharp: a sharp sign (two thin bars, two slanted
        bars) just left of the head."""
        sp, thick, idx, top = 20, 2, 0, 150
        img = np.zeros((400, 700), bool)
        for k in range(5):
            img[top + k * sp - 1:top + k * sp + 1, 20:680] = True
        line_px = img.copy()
        cx, cy = 300, int(top + 4 * sp - step * sp / 2)
        cv2.ellipse(img.view(np.uint8), (cx, cy), (13, 9), -20, 0, 360, 1, -1)
        img[cy:cy + 3 * sp, cx - 12:cx - 8] = True                 # stem down (left side)
        if flag:
            # a flag curl closes a loop with the stem: the print's hole is filled
            # and the foot of the stem becomes a solid mass 17 px = 0.85 sp wide
            fx0, fx1, fy0, fy1 = cx - 12, cx + 5, cy, cy + 3 * sp
            img[fy0:fy1, fx0:fx0 + 3] = True               # the stem
            img[fy0:fy1, fx1 - 4:fx1] = True               # the curl's outer edge
            img[fy1 - 10:fy1, fx0:fx1] = True              # the curl's foot
        if sharp:
            img[cy - 18:cy + 18, cx - 40:cx - 37] = True
            img[cy - 18:cy + 18, cx - 31:cx - 28] = True
            img[cy - 8:cy - 4, cx - 42:cx - 26] = True
            img[cy + 4:cy + 8, cx - 42:cx - 26] = True
        owner = np.where(img, idx, pt.OWN_NONE).astype(np.int32)
        st = pt.Staff(0, 0, [top + k * sp for k in range(5)], 20, 680)
        return pt.note_steps(owner, line_px, st, idx, float(sp), thick, barxs=[])

    def test_note_steps_flag_is_not_a_head(self):
        # the flag curl of a stem-down eighth is not a second, lower head
        r = self._stem_staff(flag=True)
        self.assertEqual(r[:2], (5, 5))

    def test_note_steps_head_cut_by_a_staff_line_keeps_its_flag_out(self):
        # a head on a line is cut by the removed line into two short runs (8 rows,
        # under 0.45 sp each): the head still counts, the flag curl does not
        r = self._stem_staff(flag=True, step=6)
        self.assertEqual(r[:3], (6, 6, 1))

    def test_note_steps_ledger_heads_when_sp_differs_from_staff_spacing(self):
        # sp (line thickness + gap) is 3-5 % off the real line spacing: the ledger
        # lines must be placed from the staff's own lines (cb-003 Alto: C6 missed)
        spacing, thick, idx, top = 20, 2, 0, 150
        img = np.zeros((400, 700), bool)
        for k in range(5):
            img[top + k * spacing - 1:top + k * spacing + 1, 20:680] = True
        line_px = img.copy()
        bot = top + 4 * spacing
        for step in (10, 12):                       # two ledger lines above the staff
            y = bot - step * spacing // 2
            img[y - 1:y + 1, 270:330] = True
        cy = bot - 12 * spacing // 2
        cv2.ellipse(img.view(np.uint8), (300, cy), (13, 9), -20, 0, 360, 1, -1)
        img[cy:cy + 3 * spacing, 288:292] = True    # stem down
        owner = np.where(img, idx, pt.OWN_NONE).astype(np.int32)
        st = pt.Staff(0, 0, [top + k * spacing for k in range(5)], 20, 680)
        r = pt.note_steps(owner, line_px, st, idx, 21.0, thick, barxs=[])
        self.assertEqual(r[:3], (12, 12, 1))

    def test_note_steps_plain_stem_head(self):
        r = self._stem_staff(flag=False)
        self.assertEqual(r[:3], (5, 5, 1))

    def test_note_steps_sharp_beside_head(self):
        r = self._stem_staff(flag=False, sharp=True)
        self.assertEqual(r[:3], (5, 5, 1))

    def test_note_steps_stacked_heads_still_both_count(self):
        sp, thick, idx, top = 20, 2, 0, 150
        img = np.zeros((400, 700), bool)
        for k in range(5):
            img[top + k * sp - 1:top + k * sp + 1, 20:680] = True
        line_px = img.copy()
        for step in (3, 5):
            cv2.ellipse(img.view(np.uint8), (300, int(top + 4 * sp - step * sp / 2)),
                        (13, 9), -20, 0, 360, 1, -1)
        img[int(top + 4 * sp - 5 * sp / 2):int(top + 4 * sp - 3 * sp / 2), 288:292] = True
        owner = np.where(img, idx, pt.OWN_NONE).astype(np.int32)
        st = pt.Staff(0, 0, [top + k * sp for k in range(5)], 20, 680)
        r = pt.note_steps(owner, line_px, st, idx, float(sp), thick, barxs=[])
        self.assertEqual(r[:2], (3, 5))

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
        old = render.SYSTEM_GAP_LAST             # plan_pages reads it in `render` (rule R1)
        try:
            render.SYSTEM_GAP_LAST = pt.SYSTEM_GAP_FACTOR   # no widening
            self.assertEqual(render.SYSTEM_GAP_LAST, pt.SYSTEM_GAP_FACTOR)   # the fake is in force
            plain = dy()
        finally:
            render.SYSTEM_GAP_LAST = old
        self.assertEqual(render.SYSTEM_GAP_LAST, old)
        p = pt.pitches([g, g], opts)[0]          # px
        extra_max = (render.SYSTEM_GAP_LAST - pt.SYSTEM_GAP_FACTOR) * 40
        self.assertGreater(spread, plain)        # room on the page is used
        self.assertLessEqual(spread / plain, (p + extra_max) / p + 1e-6)


@needs_deps
class TestClefModuleState(unittest.TestCase):
    """Step M2: the clef caches live in `clef`; the script shares the objects (rule R1)."""

    def test_caches_are_changed_in_place_and_shared_with_the_script(self):
        # Never rebound, so the shim import by name stays valid (DESIGN §12.3).
        self.assertIs(pt.CLEF_LAST, clef.CLEF_LAST)
        self.assertIs(pt._CLEF_TPL, clef._CLEF_TPL)
        self.assertIsInstance(clef.CLEF_LAST, dict)
        self.assertIsInstance(clef._CLEF_TPL, dict)
        src = inspect.getsource(clef)
        for name in ("CLEF_LAST", "_CLEF_TPL"):          # no rebinding anywhere in the module
            self.assertIsNone(re.search(rf"(?m)^\s+global {name}\b|^\s*{name}\s*=(?!=)", src.split(
                "\n\n\n", 1)[1].replace(f"{name}: dict = {{}}", "")), name)

    def test_templates_share_one_document(self):
        import pymupdf
        clef._CLEF_TPL.clear()
        clef._TPL_DOC.clear()
        calls = []
        real = pymupdf.open

        def counting(*a, **k):
            calls.append(1)
            return real(*a, **k)

        try:
            pymupdf.open = counting
            for kind in "GCF":
                for sp in (7.0, 8.0, 9.0):
                    self.assertIsNotNone(clef._clef_template(kind, sp, 1.0))
        finally:
            pymupdf.open = real
            clef._CLEF_TPL.clear()
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(clef._TPL_DOC), 1)
        self.assertEqual(clef._TPL_DOC["doc"].page_count, 0)

    def test_refresh_ambitus_has_no_cli_code(self):
        # It stays pure: the menu part (confirm_ambitus) is for cli_parts (step M7).
        src = inspect.getsource(clef.refresh_ambitus)
        self.assertIsNone(re.search(r"\b(ask|yes|_die|_ok|_warn|cmd_set|load_item|input)\(", src))
        self.assertFalse(hasattr(clef, "confirm_ambitus"))

