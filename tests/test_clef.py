# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""Tests for clef signature, ambitus and spacing.

Needs the venv packages (numpy, opencv, pymupdf, PyYAML); without them every test
is skipped. Run with the venv interpreter:

    venv/bin/python3 -m unittest -v tests/test_clef.py

Shared helpers: tests/support.py.
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from support import (  # noqa: E402,F401
    SP,
    cv2,
    flow_line,
    needs_deps,
    np,
    pt,
    pymupdf,
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
