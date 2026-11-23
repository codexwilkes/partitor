# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""Tests for cues (small staves of another voice above a rest; docs/DESIGN.md §13).

Run with the venv interpreter:

    venv/bin/python3 -m unittest -v tests/test_cues.py
"""
import argparse
import builtins
import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

sys.path.insert(0, os.path.join(os.path.dirname(HERE), "lib"))

import numpy as np  # noqa: E402

from partitor import cli_cues, cueplace, cues, lines  # noqa: E402
from support import pt  # noqa: E402
from partitor.model import Strip  # noqa: E402


class TestSplitRest(unittest.TestCase):
    """The bars of a cue are one piece of their own, one multi-bar rest as wide as the cue: the
    bars before and after stay a rest each. The counts of the pieces add up to the original
    count and every bar number stays right."""

    def test_cue_in_the_middle_gives_three_pieces(self):
        # bars 9-22 are one rest of 14; the cue holds bars 19-21
        self.assertEqual(cues.split_rest(9, 14, 19, 21),
                         [("rest", 9, 10), ("cue", 19, 3), ("rest", 22, 1)])

    def test_a_one_bar_cue_is_a_bar_of_its_own(self):
        self.assertEqual(cues.split_rest(9, 14, 15, 15),
                         [("rest", 9, 6), ("cue", 15, 1), ("rest", 16, 7)])

    def test_a_cue_at_the_edges_leaves_no_empty_piece(self):
        self.assertEqual(cues.split_rest(9, 14, 9, 10), [("cue", 9, 2), ("rest", 11, 12)])
        self.assertEqual(cues.split_rest(9, 14, 21, 22), [("rest", 9, 12), ("cue", 21, 2)])
        self.assertEqual(cues.split_rest(9, 14, 9, 22), [("cue", 9, 14)])

    def test_the_counts_always_add_up_and_the_numbers_run_on(self):
        for first, count in ((1, 2), (9, 14), (32, 26)):
            for a in range(first, first + count):
                for b in range(a, first + count):
                    parts = cues.split_rest(first, count, a, b)
                    self.assertEqual(sum(n for _, _, n in parts), count)
                    at = first
                    for kind, start, n in parts:
                        self.assertEqual(start, at, (first, count, a, b, kind))
                        self.assertGreater(n, 0)
                        at += n
                    self.assertEqual([p for p in parts if p[0] == "cue"], [("cue", a, b - a + 1)])

    def test_a_cue_outside_the_rest_is_refused_with_a_message(self):
        for a, b in ((8, 10), (20, 23), (3, 4), (12, 11)):
            with self.assertRaises(cues.CueError) as cm:
                cues.split_rest(9, 14, a, b)
            self.assertIn("bar", str(cm.exception))


def make_source(sp=10):
    """A one-staff line of 5 bars: clef block at x 5-24 (music starts at 30), barlines
    at x 100, 200, 300, 400, 500; one 'note' block in the middle of each bar, a bar
    number in bar 3 (num_mask) and a part label above the staff (hdr)."""
    h, w = 80, 520
    img = np.zeros((h, w), bool)
    top = 30
    for k in range(5):
        img[top + k * sp // 2:top + k * sp // 2 + 1, 5:510] = True      # staff lines
    bars = [100, 200, 300, 400, 500]
    for x in bars:
        img[top:top + 2 * sp + 1, x] = True                              # barlines
    img[top + 5:top + 15, 5:24] = True                                   # the clef
    for k, x in enumerate(bars):
        img[top + 8:top + 14, x - 60:x - 50] = True                      # a note, bar k
    num = np.zeros_like(img)
    num[5:15, 205:230] = True                                            # printed bar number, bar 2
    img |= num
    hdr = np.zeros_like(img)
    hdr[2:12, 10:60] = True                                              # the part label
    img |= hdr
    return Strip(img=img, staff_x0=5, staff_top=top, staff_bottom=top + 2 * sp, sp=float(sp), hdr=hdr,
                 bars_x=bars, bar_nums=[1, 2, 3, 4, 5], num_mask=num), 30


class TestCropCue(unittest.TestCase):
    def test_the_crop_holds_the_bars_asked_and_nothing_else(self):
        src, pre = make_source()
        c = cues.crop_cue(src, 1, 2, pre, clef=False)
        self.assertEqual(c.img.shape[0], src.img.shape[0])
        cols = np.nonzero(c.img.any(axis=0))[0]
        self.assertEqual(c.clef_px, 0)
        self.assertEqual(c.img.shape[1], 300 - 100 + 1)               # barline 1 to barline 2, both included
        self.assertTrue(c.img[:, 0].any() and c.img[:, -1].any())      # the barlines
        self.assertEqual(len(cols), c.img.shape[1])                    # staff lines run through

    def test_label_and_printed_numbers_are_left_out_but_notes_stay(self):
        src, pre = make_source()
        c = cues.crop_cue(src, 1, 2, pre, clef=False)
        self.assertFalse(c.img[2:15, :].any())                         # above the staff: label and number were there
        self.assertTrue(c.img[38:44, 40:50].any())                    # the note of bar 2 (x 140-150 of the source)

    def test_the_clef_is_added_in_front_of_a_later_bar(self):
        src, pre = make_source()
        c = cues.crop_cue(src, 2, 2, pre, clef=True)
        self.assertEqual(c.clef_px, 30 - 5)                           # staff start to the music start
        self.assertEqual(c.img.shape[1], c.clef_px + (300 - 200 + 1))
        self.assertTrue(c.img[35:45, :c.clef_px].any())               # the clef ink

    def test_the_first_bar_with_its_clef_has_it_once(self):
        src, pre = make_source()
        c = cues.crop_cue(src, 0, 0, pre, clef=True)
        self.assertEqual(c.clef_px, 30 - 5)
        self.assertEqual(c.img.shape[1], 100 - 5 + 1)

    def test_no_clef_option_leaves_it_out(self):
        src, pre = make_source()
        c = cues.crop_cue(src, 0, 0, pre, clef=False)
        self.assertEqual(c.clef_px, 0)
        self.assertEqual(c.img.shape[1], 100 - 30 + 1)

    def test_bad_bars_are_refused_with_a_message(self):
        src, pre = make_source()
        for a, b in ((-1, 1), (3, 5), (2, 1)):
            with self.assertRaises(cues.CueError) as cm:
                cues.crop_cue(src, a, b, pre)
            self.assertIn("bar", str(cm.exception))


class TestCropGeometry(unittest.TestCase):
    def test_the_width_of_the_bars_is_the_crop_without_the_clef_at_the_scale(self):
        src, pre = make_source()
        c = cues.crop_cue(src, 1, 2, pre, clef=True)
        self.assertEqual(c.width_px(0.5), int(np.ceil((c.img.shape[1] - c.clef_px) * 0.5)))
        self.assertEqual(cues.crop_cue(src, 1, 2, pre, clef=False).width_px(0.5), (300 - 100 + 1 + 1) // 2)

    def test_the_staff_row_is_kept_for_joining(self):
        src, pre = make_source()
        self.assertEqual(cues.crop_cue(src, 1, 1, pre).staff_row, int(src.staff_top))

    def test_a_crop_knows_the_barline_that_ends_each_bar(self):
        src, spre = make_source()
        self.assertEqual(cues.crop_cue(src, 1, 2, spre, clef=False).bars, (100, 200))
        self.assertEqual(cues.crop_cue(src, 0, 1, spre, clef=True).bars, (95, 195))
        self.assertEqual(cues.crop_cue(src, 1, 2, spre, clef=True).bars, (125, 225))     # the clef block is in front

    def test_joined_crops_keep_their_barlines_in_place(self):
        a = cues.CueImg(np.zeros((40, 50), bool), 10, 10.0, 20, (49,))
        b = cues.CueImg(np.zeros((50, 30), bool), 0, 10.0, 15, (29,))
        self.assertEqual(cues.join_cues([a, b]).bars, (49, 79))

    def test_scaled_cue_gives_the_bars_from_a_bar_on_the_widths_asked(self):
        src, spre = make_source()
        cue = cues.crop_cue(src, 0, 1, spre, clef=False)                  # two bars, barlines at 69 and 169
        plain = cueplace.scaled_cue(cue, 0.5)
        fitted = cueplace.scaled_cue(cue, 0.5, 1, [77])
        self.assertEqual(plain.shape[0], fitted.shape[0])                  # the height is the scale's
        self.assertEqual(fitted.shape[1], int(round(71 * 0.5)) + 77)

    def test_crops_of_two_lines_join_on_one_staff(self):
        a = cues.CueImg(np.zeros((40, 50), bool), 10, 10.0, 20)
        b = cues.CueImg(np.zeros((50, 30), bool), 0, 10.0, 15)
        a.img[20, :] = True                                   # the top line of each
        b.img[15, :] = True
        j = cues.join_cues([a, b])
        self.assertEqual((j.clef_px, j.staff_row, j.img.shape), (10, 20, (55, 80)))
        self.assertTrue(j.img[20, :].all())                   # one top line through both
        self.assertIs(cues.join_cues([a]), a)


def rest_line(note_bar=None, staves=1, merge=True):
    """A line of 4 bars (sp 10, music from x 30, barlines 130..430), numbered 10-13, each
    with a whole rest; `note_bar`: a note instead in that bar. Merged as the build does."""
    bars, pre = [130, 230, 330, 430], 30
    h = 40 + 100 * staves
    img = np.zeros((h, 440), bool)
    tops = [40 + 100 * k for k in range(staves)]
    for t0 in tops:
        for k in range(5):
            img[t0 + 10 * k, :] = True
    starts = [pre] + [x + 2 for x in bars[:-1]]
    for k, t0 in enumerate(tops):
        for b in range(4):
            cx = starts[b] + 40
            if b == note_bar:
                img[t0 + 20:t0 + 28, cx:cx + 9] = True
                img[t0 - 5:t0 + 24, cx + 8:cx + 10] = True
            else:
                img[t0 + 11:t0 + 16, cx:cx + 14] = True
    for x in bars:
        img[tops[0]:tops[-1] + 41, x:x + 2] = True
    s = Strip(img, 0, tops[0], tops[0] + 40, 10.0, np.zeros_like(img), bars_x=list(bars),
              bar_nums=[10, 11, 12, 13], ends_at_bar=True)
    if not merge:
        return s, pre
    return lines.merge_rest_bars([s], {"rests": "compress"}, pre=[(pre, 0)])[0], pre


class TestRespan(unittest.TestCase):
    def test_a_merged_rest_is_split_round_the_cue_bars_and_the_counts_add_up(self):
        s, pre = rest_line()
        self.assertEqual(s.rest_counts, [4])
        bars = cueplace.shown_bars(s, pre)
        self.assertEqual([(b.first, b.count) for b in bars], [(10, 4)])
        r = cueplace.respan(s, bars, 0, 0, 11, 12)
        self.assertEqual(r.bar_nums, [10, 11, 13])
        self.assertEqual(r.rest_counts, [1, 2, 1])
        self.assertEqual(len(r.bars_x), 3)
        self.assertEqual([t for _, t, *_ in r.rest_labels], ["2"])      # only a piece of 2+ bars has a count
        self.assertEqual((r.rest_in, r.rest_out), (4, 4))                # still a rest at both edges
        self.assertIsNone(r.rest_src)
        self.assertTrue(all(a < b for a, b in zip(r.bars_x, r.bars_x[1:])))

    def test_a_thick_bar_at_the_start_of_the_rest_is_not_copied_into_the_new_pieces(self):
        s, pre = rest_line()
        s.img[52:59, pre:130] = True                                     # the scan's own H-bar starts at the first bar
        bars = cueplace.shown_bars(s, pre)
        r = cueplace.respan(s, bars, 0, 0, 11, 12)
        for x in (r.bars_x[0] + 6, r.bars_x[1] - 6):                      # at a piece's edge no H-bar is drawn
            self.assertFalse(r.img[52:59, x].any(), x)
            self.assertTrue(r.img[50, x] and r.img[60, x], x)             # the staff lines stand

    def test_a_barline_stands_between_the_pieces(self):
        s, pre = rest_line()
        r = cueplace.respan(s, cueplace.shown_bars(s, pre), 0, 0, 11, 12)
        for x in r.bars_x:
            self.assertTrue(r.img[40:81, x + 1].all(), x)               # the barline is staff high

    def test_printed_rest_bars_under_the_cue_become_one_multi_bar_rest(self):
        s, pre = rest_line(merge=False)                                  # four printed bars of rest
        s.rest_counts = []
        bars = cueplace.shown_bars(s, pre)
        r = cueplace.respan(s, bars, 1, 2, 11, 12)                       # the cue holds bars 11 and 12
        self.assertEqual((r.bar_nums, r.rest_counts), ([10, 11, 13], [1, 2, 1]))
        self.assertEqual([t for _, t, *_ in r.rest_labels], ["2"])

    def test_the_end_of_the_rest_leaves_no_empty_piece(self):
        s, pre = rest_line()
        bars = cueplace.shown_bars(s, pre)
        r = cueplace.respan(s, bars, 0, 0, 12, 13)
        self.assertEqual((r.bar_nums, r.rest_counts), ([10, 12], [2, 2]))
        r = cueplace.respan(s, bars, 0, 0, 10, 10)
        self.assertEqual((r.bar_nums, r.rest_counts), ([10, 11], [1, 3]))

    def test_the_piece_of_the_cue_is_as_wide_as_the_cue(self):
        s, pre = rest_line()
        src, spre = make_source()
        cue = cues.crop_cue(src, 0, 3, spre, clef=True)                  # a wide cue
        r = cueplace.respan(s, cueplace.shown_bars(s, pre), 0, 0, 11, 12, cue, 1.2)
        self.assertGreaterEqual(r.bars_x[1] - r.bars_x[0], cue.width_px(1.2) - 2)
        narrow = cueplace.respan(s, cueplace.shown_bars(s, pre), 0, 0, 11, 12, cue, 0.1)
        self.assertGreaterEqual(narrow.bars_x[1] - narrow.bars_x[0], int(cueplace.CUE_BAR_MIN_SP * 10))

    def test_a_word_between_the_staves_stays(self):
        s, pre = rest_line(staves=2)
        s.img[95:105, 140:170] = True                                    # a printed name between the staves
        r = cueplace.respan(s, cueplace.shown_bars(s, pre), 0, 0, 11, 12)
        self.assertTrue(r.img[95:105, 140:170].all())

    def test_the_bars_of_a_group_line_all_get_their_hbars(self):
        s, pre = rest_line(staves=3)
        r = cueplace.respan(s, cueplace.shown_bars(s, pre), 0, 0, 11, 12)
        self.assertEqual(len(r.rest_labels), 3)                         # one count above each staff

    def test_a_bar_with_notes_is_refused(self):
        s, pre = rest_line(note_bar=1)
        bars = cueplace.shown_bars(s, pre)
        i = cueplace.find_bar(bars, 11)
        with self.assertRaises(cues.CueError) as cm:
            cueplace.respan(s, bars, i, i, 11, 11)
        self.assertIn("plays", str(cm.exception))

    def test_find_bar_reads_merged_bars(self):
        s, pre = rest_line()
        bars = cueplace.shown_bars(s, pre)
        self.assertEqual([cueplace.find_bar(bars, n) for n in (9, 10, 13, 14)], [None, 0, 0, None])


class TestDrawCue(unittest.TestCase):
    def line(self):
        s, pre = rest_line()
        return cueplace.respan(s, cueplace.shown_bars(s, pre), 0, 0, 11, 12), pre

    def test_the_cue_stands_above_the_staff_and_the_rows_are_added(self):
        s, _ = self.line()
        src, spre = make_source()
        cue = cues.crop_cue(src, 1, 1, spre, clef=True)
        r, warns = cueplace.draw_cue(s, cue, int(s.bars_x[0]), 0.6, "Canto")
        self.assertEqual(warns, [])
        pad = r.img.shape[0] - s.img.shape[0]
        self.assertGreater(pad, 0)
        self.assertEqual(r.staff_top, s.staff_top + pad)                  # the staff moved down with its rows
        self.assertTrue(r.img[:int(r.staff_top) - 5, :].any())             # ink above the staff: the cue
        self.assertFalse(s.img[:int(s.staff_top) - 5, :].any())            # (there was none)
        self.assertEqual([t for *_, t in r.cue_labels], ["Canto"])

    def test_the_first_barline_of_the_cue_falls_on_the_barline_of_the_part(self):
        s, _ = self.line()
        src, spre = make_source()
        cue = cues.crop_cue(src, 2, 2, spre, clef=False)                  # one bar: its left barline is its first column
        r, _ = cueplace.draw_cue(s, cue, int(s.bars_x[0]) + 2, 0.6)
        above = r.img[:int(r.staff_top) - 10, :]
        xs = np.flatnonzero(above.any(axis=0))
        self.assertEqual(int(xs.min()), int(s.bars_x[0]) + 2)

    def test_the_clef_hangs_to_the_left_of_the_first_bar(self):
        s, _ = self.line()
        src, spre = make_source()
        cue = cues.crop_cue(src, 2, 2, spre, clef=True)
        r, _ = cueplace.draw_cue(s, cue, int(s.bars_x[0]) + 2, 0.6)
        xs = np.flatnonzero(r.img[:int(r.staff_top) - 10, :].any(axis=0))
        self.assertEqual(int(xs.min()), int(s.bars_x[0]) + 2 - int(round(cue.clef_px * 0.6)))

    def test_without_a_label_no_label_is_kept_and_other_ink_is_not_lost(self):
        s, _ = self.line()
        src, spre = make_source()
        cue = cues.crop_cue(src, 1, 1, spre, clef=False)
        r, _ = cueplace.draw_cue(s, cue, int(s.bars_x[0]) + 2, 0.6)
        self.assertEqual(r.cue_labels, [])
        pad = r.img.shape[0] - s.img.shape[0]
        self.assertTrue(np.array_equal(r.img[pad:, :s.img.shape[1]] & s.img, s.img))   # the line itself is whole

    def test_a_cue_above_ink_is_lifted_and_warned(self):
        s, _ = self.line()
        bx = int(s.bars_x[0])
        s.img[10:20, bx - 5:bx + 5] = True                 # a tall note above the staff in the cue's columns
        src, spre = make_source()
        cue = cues.crop_cue(src, 1, 1, spre, clef=True)
        r, warns = cueplace.draw_cue(s, cue, bx, 0.6)
        self.assertEqual(len(warns), 1)
        self.assertIn("ink", warns[0])

    def test_a_cue_that_starts_left_of_the_line_is_refused(self):
        s, _ = self.line()
        src, spre = make_source()
        cue = cues.crop_cue(src, 0, 3, spre, clef=True)
        with self.assertRaises(cues.CueError) as cm:
            cueplace.draw_cue(s, cue, 5, 0.6)
        self.assertIn("left", str(cm.exception))

    def test_pad_top_moves_every_row_field(self):
        s, _ = self.line()
        s.staff_labels = [("A", 40, 80)]
        s.ambitus_marks = [(10, 70, "G", "C4", "A5")]
        r = cueplace.pad_top(s, 7)
        self.assertEqual((r.staff_top, r.staff_bottom), (s.staff_top + 7, s.staff_bottom + 7))
        self.assertEqual(r.staff_labels, [("A", 47, 87)])
        self.assertEqual(r.ambitus_marks[0][1], 77)
        self.assertIs(cueplace.pad_top(s, 0), s)


class TestApplyCues(unittest.TestCase):
    def setUp(self):
        self.line, self.pre = rest_line()                  # the part: bars 10-13, one merged rest
        self.src, self.spre = make_source()
        self.src.bar_nums = [11, 12, 13, 14, 15]            # the voice: 5 bars, numbered 11-15
        self.sources = {"Canto": ([self.src], {id(self.src): self.spre})}

    def run_cue(self, first, last, **kw):
        spec = cues.CueSpec("Canto", first, last, **kw)
        return cueplace.apply_cues([self.line], [self.pre], [spec], self.sources, "Alto")

    def test_the_bars_of_the_cue_become_one_rest_and_the_cue_is_noted(self):
        out, warns = self.run_cue(11, 12)
        self.assertEqual(warns, [])
        s = out[0]
        self.assertEqual(s.bar_nums, [10, 11, 13])
        self.assertEqual(s.rest_counts, [1, 2, 1])
        self.assertEqual(len(s.cue_todo), 1)
        self.assertEqual(s.cue_todo[0][2:4], (11, "Canto"))        # first bar number and label

    def test_the_cue_is_drawn_above_the_staff(self):
        out, _ = self.run_cue(11, 12)
        drawn, warns = cueplace.draw_cues(out)
        s = drawn[0]
        self.assertEqual(s.cue_todo, [])
        self.assertEqual([t for *_, t in s.cue_labels], ["Canto"])
        self.assertTrue(s.img[:int(s.staff_top) - 5, :].any())

    def test_both_barlines_of_the_cue_meet_those_of_the_part(self):
        out, _ = self.run_cue(11, 12, clef=False)
        s = cueplace.draw_cues(out)[0][0]
        above = np.flatnonzero(s.img[:int(s.staff_top) - 10, :].any(axis=0))
        self.assertEqual(int(above.min()), int(s.bars_x[0]))                 # the left barline of the rest piece
        self.assertLessEqual(abs(int(above.max()) - int(s.bars_x[1])), 2)     # and its right one (rounding of the scale: 2 px)

    def test_the_input_line_is_not_changed(self):
        before = self.line.img.copy()
        self.run_cue(11, 12)
        self.assertTrue(np.array_equal(self.line.img, before))
        self.assertEqual(self.line.cue_todo, [])

    def test_a_cue_runs_on_over_a_bar_the_part_plays(self):
        self.line, self.pre = rest_line(note_bar=2)         # bar 12 has a note: the anchor is its left barline
        before = self.line.img[:, int(self.line.bars_x[-3]):].copy()
        out, warns = self.run_cue(11, 12)
        self.assertEqual(warns, [])
        s = out[0]
        self.assertEqual(s.bar_nums, [10, 11, 12, 13])          # bar 11 split off the rest, bar 12 unchanged
        self.assertEqual(s.rest_counts, [1, 1, 0, 1])
        self.assertEqual(len(s.cue_todo), 1)
        self.assertEqual(s.cue_todo[0][5], None)                # not fitted
        self.assertTrue(np.array_equal(s.img[:, -before.shape[1]:], before))   # the notes are as they were

    def test_a_cue_that_starts_on_a_bar_the_part_plays_changes_nothing(self):
        self.line, self.pre = rest_line(note_bar=2)
        out, warns = self.run_cue(12, 12)
        self.assertEqual(warns, [])
        self.assertTrue(np.array_equal(out[0].img, self.line.img))
        self.assertEqual(len(out[0].cue_todo), 1)
        self.assertEqual(lines._cue_spans(out[0]), [])          # justify may widen a bar that plays

    def test_the_bars_under_a_rest_cue_are_protected_from_justify(self):
        out, _ = self.run_cue(11, 12)
        self.assertEqual(len(lines._cue_spans(out[0])), 1)

    def test_an_anchor_after_a_bar_the_part_plays_is_refused(self):
        self.line, self.pre = rest_line(note_bar=2)
        out, warns = self.run_cue(11, 13, anchor=13)            # bars 11-12 would have to become a rest
        self.assertEqual(out[0].cue_todo, [])
        self.assertIn("plays", warns[0])
        self.assertIn("anchor", warns[0])

    def test_an_anchor_on_a_rest_bar_leaves_the_bars_after_it_as_they_are(self):
        out, warns = self.run_cue(11, 12, anchor=12)
        self.assertEqual(warns, [])
        s = out[0]
        self.assertEqual((s.bar_nums, s.rest_counts), ([10, 11, 12], [1, 1, 2]))   # only bar 11 was split off

    def test_an_anchor_outside_the_cue_is_named(self):
        out, warns = self.run_cue(11, 12, anchor=13)
        self.assertEqual(out[0].cue_todo, [])
        self.assertIn("anchor 13", warns[0])

    def test_fit_gives_the_cue_bar_the_width_of_the_bar_of_the_part(self):
        self.line, self.pre = rest_line(note_bar=2)
        out, warns = self.run_cue(11, 12, clef=False, fit=True)
        self.assertEqual(out[0].cue_todo[0][5], 1)
        s = cueplace.draw_cues(out)[0][0]
        above = np.flatnonzero(s.img[:int(s.staff_top) - 10, :].any(axis=0))
        self.assertEqual(int(above.min()), int(s.bars_x[0]))
        self.assertLessEqual(abs(int(above.max()) - int(s.bars_x[2])), 2)    # the right barline of bar 12 too

    def test_without_fit_the_cue_keeps_its_own_width(self):
        self.line, self.pre = rest_line(note_bar=2)
        out, _ = self.run_cue(11, 12, clef=False)
        s = cueplace.draw_cues(out)[0][0]
        above = np.flatnonzero(s.img[:int(s.staff_top) - 10, :].any(axis=0))
        self.assertGreater(abs(int(above.max()) - int(s.bars_x[2])), 5)

    def test_fit_over_a_merged_rest_is_not_stretched(self):
        out, _ = self.run_cue(11, 12, fit=True)                 # no bar of the part plays: nothing to fit
        self.assertIsNone(out[0].cue_todo[0][5])

    def test_a_bar_the_voice_does_not_have_is_named(self):
        out, warns = self.run_cue(9, 11)
        self.assertEqual(out[0].cue_todo, [])
        self.assertIn("bar 9", warns[0])

    def test_a_bar_outside_the_part_is_named(self):
        out, warns = self.run_cue(14, 15)
        self.assertIn("bar 14", warns[0])
        self.assertIn("Alto", warns[0])

    def test_a_cue_that_cannot_be_placed_does_not_stop_the_others(self):
        specs = [cues.CueSpec("Canto", 14, 15), cues.CueSpec("Canto", 11, 12)]
        out, warns = cueplace.apply_cues([self.line], [self.pre], specs, self.sources, "Alto")
        self.assertEqual(len(warns), 1)
        self.assertEqual(len(out[0].cue_todo), 1)

    def test_a_voice_with_several_staves_is_refused(self):
        self.src.staff_labels = [("a", 0, 10), ("b", 20, 30)]
        out, warns = self.run_cue(11, 12)
        self.assertIn("several staves", warns[0])

    def test_bars_on_two_lines_of_the_source_are_one_cue(self):
        src2, pre2 = make_source()
        src2.bar_nums = [13, 14, 15, 16, 17]                 # the next line of the voice
        self.src.bar_nums = [9, 10, 11, 12, 99]               # bars 11 and 12 end this one
        self.sources = {"Canto": ([self.src, src2], {id(self.src): self.spre, id(src2): pre2})}
        out, warns = self.run_cue(12, 13)
        self.assertEqual(warns, [])
        self.assertEqual(len(out[0].cue_todo), 1)                          # one cue, not two
        img = out[0].cue_todo[0][0]
        one = cues.crop_cue(self.src, 3, 3, self.spre, clef=True)
        two = cues.crop_cue(src2, 0, 0, pre2, clef=False)
        self.assertEqual(img.img.shape[1], one.img.shape[1] + two.img.shape[1])

    def test_a_cue_over_a_rest_line_makes_it_a_line_with_bars(self):
        from partitor.model import RestRun
        s, pre = rest_line()
        s = lines.make_rest_strip(s, s, pre, RestRun(4, 10), {"rest_bar": "engraved"})
        self.assertIsNotNone(s.rest_src)
        out, warns = cueplace.apply_cues([s], [pre], [cues.CueSpec("Canto", 11, 12)],
                                         self.sources, "Alto")
        self.assertEqual(warns, [])
        self.assertIsNone(out[0].rest_src)
        self.assertEqual(out[0].rest_counts, [1, 2, 1])


class TestTextMarkAndConfig(unittest.TestCase):
    def test_a_text_mark_splits_the_rest_and_draws_a_word(self):
        s, pre = rest_line()
        out, warns = cueplace.apply_cues([s], [pre], [cues.CueSpec("", 12, 12, False, "Canto", 0.0)], {}, "Alto")
        self.assertEqual(warns, [])
        self.assertEqual(out[0].bar_nums, [10, 12, 13])
        drawn, w = cueplace.draw_cues(out)
        self.assertEqual(w, [])
        (x, base, fs, text), = drawn[0].cue_labels
        self.assertEqual(text, "Canto")
        self.assertEqual(int(x), int(drawn[0].bars_x[0]))                  # at the start of bar 12
        self.assertGreater(base - 0.8 * fs, -1)                             # inside the image

    def test_a_text_mark_in_a_bar_that_is_not_in_the_part_is_named(self):
        s, pre = rest_line()
        out, warns = cueplace.apply_cues([s], [pre], [cues.CueSpec("", 40, 40, False, "Canto", 0.0)], {}, "Alto")
        self.assertIn("bar 40", warns[0])

    def test_parse_cues_reads_cues_and_marks(self):
        raw = {"Trombones": [{"src": "Canto", "bars": [23, 24]},
                             {"src": "Tenore", "bars": [20, 22], "clef": False, "size": 0.5, "label": "T"},
                             {"text": "Canto", "bar": 97}]}
        got, notes = cues.parse_cues(raw, ["Canto", "Tenore"], {"Trombones": ["Alto"]})
        self.assertEqual(notes, [])
        a, b, c = got["Trombones"]
        self.assertEqual((a.src, a.first, a.last, a.clef, a.label, a.size), ("Canto", 23, 24, True, None, None))
        self.assertEqual(cues.cue_size(a), 0.6)
        self.assertEqual((b.clef, b.size, b.label), (False, 0.5, "T"))
        self.assertEqual((c.src, c.first, c.label), ("", 97, "Canto"))

    def test_parse_cues_names_what_is_wrong_and_goes_on(self):
        raw = {"Ghost": [{"src": "Canto", "bars": [1, 2]}],
               "Alto": [{"src": "Nobody", "bars": [1, 2]}, {"src": "Canto", "bars": [5, 3]},
                        {"src": "Canto", "bars": [1, 2], "size": 5}, "x", {"src": "Canto"},
                        {"src": "Canto", "bars": [7, 8]}]}
        got, notes = cues.parse_cues(raw, ["Canto", "Alto"], {})
        self.assertEqual([c.first for c in got["Alto"]], [7])
        self.assertEqual(len(notes), 6)
        self.assertTrue(all("cues:" in n for n in notes))

    def test_the_anchor_and_fit_are_read_and_checked(self):
        raw = {"Alto": [{"src": "Canto", "bars": [24, 25], "anchor": 25, "fit": True},
                        {"src": "Canto", "bars": [24, 25], "anchor": 30}]}
        got, notes = cues.parse_cues(raw, ["Canto", "Alto"], {})
        self.assertEqual([(c.anchor, c.fit) for c in got["Alto"]], [(25, True)])
        self.assertEqual(len(notes), 1)
        self.assertIn("anchor", notes[0])

    def test_a_cue_line_takes_anchor_and_fit(self):
        entry, why = cues.parse_cue_line(["Canto", "Alto"], "Canto=24-25 anchor=25 fit")
        self.assertEqual((entry, why), ({"src": "Canto", "bars": [24, 25], "anchor": 25, "fit": True}, ""))
        self.assertEqual(cues.entry_text(entry), "Canto=24-25 anchor=25 fit")
        for bad in ("Canto=24-25 anchor=26", "Canto=24-25 anchor=x", "Canto=24-25 anchor="):
            self.assertIsNone(cues.parse_cue_line(["Canto"], bad)[0], bad)

    def test_no_cues_is_no_notes(self):
        self.assertEqual(cues.parse_cues(None, ["A"], {}), ({}, []))
        self.assertEqual(cues.parse_cues({}, ["A"], {}), ({}, []))


class TestCueSize(unittest.TestCase):
    def test_a_cue_is_small_unless_it_is_fitted(self):
        S = cues.CueSpec
        self.assertEqual(cues.cue_size(S("Canto", 1, 2)), 0.6)
        self.assertEqual(cues.cue_size(S("Canto", 1, 2, fit=True)), 1.0)
        self.assertEqual(cues.cue_size(S("Canto", 1, 2, sync=3)), 1.0)
        self.assertEqual(cues.cue_size(S("Canto", 1, 2, size=0.6, fit=True)), 0.6)     # the size typed wins
        self.assertEqual(cues.cue_size(S("Canto", 1, 2, size=0.8, sync=2)), 0.8)

    def test_the_build_scales_a_fitted_cue_at_full_size(self):
        line, pre = rest_line(note_bar=2)
        src, spre = make_source()
        src.bar_nums = [11, 12, 13, 14, 15]
        sources = {"Canto": ([src], {id(src): spre})}
        plain = cueplace.apply_cues([line], [pre], [cues.CueSpec("Canto", 11, 12)], sources, "Alto")[0][0]
        fit = cueplace.apply_cues([line], [pre], [cues.CueSpec("Canto", 11, 12, fit=True)], sources, "Alto")[0][0]
        small = cueplace.apply_cues([line], [pre], [cues.CueSpec("Canto", 11, 12, size=0.6, fit=True)], sources, "Alto")[0][0]
        self.assertEqual((plain.cue_todo[0][1], fit.cue_todo[0][1], small.cue_todo[0][1]), (0.6, 1.0, 0.6))

    def test_the_command_help_lists_every_option(self):
        import contextlib
        import io
        from partitor import cli_main
        for cmd in ("cue", "cues"):
            out = io.StringIO()
            with contextlib.redirect_stdout(out), self.assertRaises(SystemExit):
                cli_main.build_parser().parse_args([cmd, "--help"])
            for word in ("size=", "noclef", "nolabel", "label=", "anchor=", "fit", "sync="):
                self.assertIn(word, out.getvalue(), (cmd, word))


class TestNotesAndSync(unittest.TestCase):
    def staff(self, w=300):
        img = np.zeros((100, w), bool)
        for k in range(5):
            img[30 + 10 * k, :] = True                          # sp 10, top line at row 30
        return img

    def test_notes_with_a_stem_are_found_from_the_left_and_a_rest_is_not(self):
        img = self.staff()
        img[25:65, 105] = True                                    # stem up, head at the bottom left of it
        img[58:67, 95:105] = True
        img[41:46, 145:160] = True                                # a rest: no stem
        img[35:75, 245] = True                                    # stem down, head at the top right of it
        img[34:43, 246:256] = True
        img[30:71, 200] = True                                    # a barline
        got = cueplace.note_xs(img, 30, 10.0, 0, 300, (200,))
        self.assertEqual(len(got), 2)
        self.assertTrue(94 <= got[0] <= 106, got)
        self.assertTrue(244 <= got[1] <= 257, got)

    def test_a_chord_and_a_thick_barline_are_not_counted_twice(self):
        img = self.staff()
        img[25:65, 100] = True
        img[25:65, 104] = True                                    # two stems 4 px apart: one note
        img[30:71, 196:203] = True                                # a thick final barline
        self.assertEqual(len(cueplace.note_xs(img, 30, 10.0, 0, 300, (202,))), 1)

    def cue_and_part(self):
        img = np.zeros((80, 300), bool)
        for k in range(5):
            img[30 + 10 * k // 2 * 2 // 1, :] = True
        for x in (120, 140, 170):
            img[25:60, x] = True                                  # three stems in the second bar of the cue
        cue = cues.CueImg(img, 0, 10.0, 30, (99, 199, 299))
        src, _ = make_source()
        src.img[25:60, 160] = True                                # the part enters at column 160, in its bar 2
        return cue, src

    def test_the_sync_note_of_the_cue_meets_the_first_note_of_the_part(self):
        cue, part = self.cue_and_part()
        got, why = cueplace.sync_split(part, cue, 1, 1, [100], 2)
        self.assertEqual(why, "")
        self.assertEqual(got[0], 140)
        self.assertTrue(abs(got[1] - 59) <= 2, got)             # 160 px less the barline at 100 and its column

    def test_sync_names_why_it_cannot_be_done(self):
        cue, part = self.cue_and_part()
        self.assertIn("3 note", cueplace.sync_split(part, cue, 1, 1, [100], 5)[1])
        part.img[25:60, 160] = False
        self.assertIn("no note", cueplace.sync_split(part, cue, 1, 1, [100], 2)[1])

    def test_scaled_cue_splits_the_first_fitted_bar_at_a_column(self):
        img = np.zeros((40, 200), bool)
        img[:, 150] = True                                        # a mark at column 150, in the bar 100-200
        cue = cues.CueImg(img, 0, 10.0, 10, (99, 199))
        g = cueplace.scaled_cue(cue, 1.0, 1, [100], (150, 30))
        self.assertEqual(g.shape[1], 100 + 100)
        self.assertTrue(g[:, 100 + 30].max() > 100)               # the mark stands 30 px into the bar
        self.assertEqual(cueplace.scaled_cue(cue, 1.0, 1, [100], (50, 30)).shape[1], 200)   # a column outside: no split

    def test_sync_implies_fit_in_the_build_and_a_missing_note_is_a_warning(self):
        line, pre = rest_line(note_bar=2)
        src, spre = make_source()
        src.bar_nums = [11, 12, 13, 14, 15]
        out, warns = cueplace.apply_cues([line], [pre], [cues.CueSpec("Canto", 11, 12, False, None, 0.6, None, False, 1)],
                                         {"Canto": ([src], {id(src): spre})}, "Alto")
        self.assertEqual(warns, [])
        self.assertEqual(out[0].cue_todo[0][5:], (1, 1))          # fit from the second bar, sync 1
        drawn, warns = cueplace.draw_cues(out)
        self.assertTrue(any("sync=1" in w and "without it" in w for w in warns), warns)
        self.assertEqual(drawn[0].cue_todo, [])                   # the cue is drawn all the same

    def test_sync_is_read_and_checked(self):
        entry, why = cues.parse_cue_line(["Canto", "Alto"], "Canto=24-25 sync=3")
        self.assertEqual((entry, why), ({"src": "Canto", "bars": [24, 25], "sync": 3}, ""))
        self.assertEqual(cues.entry_text(entry), "Canto=24-25 sync=3")
        for bad in ("Canto=24-25 sync=0", "Canto=24-25 sync=x", "Canto=24-25 sync="):
            self.assertIsNone(cues.parse_cue_line(["Canto"], bad)[0], bad)
        got, notes = cues.parse_cues({"Alto": [{"src": "Canto", "bars": [24, 25], "sync": 3},
                                               {"src": "Canto", "bars": [24, 25], "sync": 0}]}, ["Canto", "Alto"], {})
        self.assertEqual([c.sync for c in got["Alto"]], [3])
        self.assertEqual(len(notes), 1)


class TestGuessMusicStart(unittest.TestCase):
    def test_the_gap_after_the_clef_is_found(self):
        img = np.zeros((100, 300), bool)
        for k in range(5):
            img[30 + 10 * k, 5:290] = True                 # a staff, sp 10
        img[35:60, 8:30] = True                            # the clef
        img[40:48, 50:60] = True                           # the first note
        src = Strip(img, 5, 30, 70, 10.0, np.zeros_like(img), bars_x=[290], bar_nums=[1])
        x = cueplace.guess_music_x(src)
        self.assertIsNotNone(x)
        self.assertTrue(30 <= x <= 50, x)

    def test_a_count_over_a_rest_lifts_the_cue_and_the_word(self):
        s, pre = rest_line()
        r = cueplace.respan(s, cueplace.shown_bars(s, pre), 0, 0, 10, 12)
        self.assertTrue(r.rest_labels)
        src, spre = make_source()
        cue = cues.crop_cue(src, 0, 1, spre, clef=False)
        x = int(r.rest_labels[0][0]) - 10                # the cue's columns include the centre of the count
        plain, _ = cueplace.draw_cue(r, cue, x, 0.3)
        r2 = cueplace.draw_label(r, x, "Canto")
        top_ink = int(np.flatnonzero(plain.img[:int(plain.staff_top)].any(axis=1)).max())
        self.assertLess(top_ink, int(plain.staff_top) - 10 * 1)           # the cue clears the staff by a gap
        self.assertEqual(len(r2.cue_labels), 1)


class TestLineNotRead(unittest.TestCase):
    def test_a_line_that_does_not_end_at_a_barline_is_read_for_its_rests(self):
        raw, pre = rest_line(merge=False)
        raw.ends_at_bar = False
        self.assertEqual(lines.rest_only_bars(raw, pre), [])                      # merge does not read it
        self.assertEqual(lines.rest_only_bars(raw, pre, need_end=False), [True] * 4)
        self.assertEqual([b.rest for b in cueplace.shown_bars(raw, pre)], [True] * 4)

    def test_a_bar_with_a_note_is_not_a_rest_there_either(self):
        raw, pre = rest_line(note_bar=1, merge=False)
        raw.ends_at_bar = False
        self.assertEqual([b.rest for b in cueplace.shown_bars(raw, pre)], [True, False, True, True])


class TestUnsureBar(unittest.TestCase):
    def raw(self):
        s, pre = rest_line(merge=False)
        s.ends_at_bar = False
        s.img[51:56, 172:186] = False                         # bar 1 (x 132-230): the rest is gone ...
        s.img[53, 180:200] = True                             # ... a 1 px sliver of a faint scan is left
        return s, pre

    def test_a_bar_without_anything_like_a_note_is_a_rest_that_is_not_certain(self):
        s, pre = self.raw()
        bars = cueplace.shown_bars(s, pre)
        self.assertEqual([(b.rest, b.certain) for b in bars][1], (True, False))
        self.assertEqual([b.certain for b in bars][0], True)

    def test_the_cue_is_placed_on_the_word_of_the_operator_and_the_build_is_told(self):
        s, pre = self.raw()
        src, spre = make_source()
        src.bar_nums = [11, 12, 13, 14, 15]
        out, warns = cueplace.apply_cues([s], [pre], [cues.CueSpec("Canto", 11, 11)],
                                         {"Canto": ([src], {id(src): spre})}, "Alto")
        self.assertEqual(len(out[0].cue_todo), 1)
        self.assertEqual(len(warns), 1)
        self.assertIn("could not confirm", warns[0])
        self.assertIn("bar 11", warns[0])

    def test_a_stem_in_a_faint_bar_still_means_the_part_plays(self):
        s, pre = rest_line(note_bar=1, merge=False)
        s.ends_at_bar = False
        self.assertEqual([b.rest for b in cueplace.shown_bars(s, pre)][1], False)


class TestPlaysPerStaff(unittest.TestCase):
    def test_rests_of_two_staves_one_over_the_other_are_not_notes(self):
        s, pre = rest_line(staves=3, merge=False)
        s.ends_at_bar = False
        self.assertEqual([b.rest for b in cueplace.shown_bars(s, pre)], [True] * 4)

    def test_a_note_on_the_lowest_staff_is_found(self):
        s, pre = rest_line(staves=3, merge=False)
        s.ends_at_bar = False
        s.img[240 + 20:240 + 28, 172:181] = True                  # a head over a line of staff 3, bar 1
        s.img[240 - 5:240 + 24, 180:182] = True
        self.assertEqual([b.rest for b in cueplace.shown_bars(s, pre)][1], False)


class TestNameAndDust(unittest.TestCase):
    def source_with_name(self):
        src, pre = make_source()
        for k in range(6):                                   # "(Canto I)": 6 letters above the staff
            src.img[8:17, 40 + k * 8:40 + k * 8 + 6] = True
        src.img[10:12, 120:170] = True                       # a slur: one flat piece above the staff
        return src, pre

    def test_the_printed_name_above_the_staff_is_left_out_but_a_slur_stays(self):
        src, pre = self.source_with_name()
        c = cues.crop_cue(src, 0, 1, pre, clef=True)
        self.assertFalse(c.img[8:17, 40:90].any())
        self.assertTrue(c.img[10:12, 120:170].any())

    def test_one_narrow_piece_is_not_a_name(self):
        src, pre = make_source()
        src.img[8:17, 110:116] = True                         # one head-like piece alone, after the zone of the name
        c = cues.crop_cue(src, 0, 1, pre, clef=True)
        self.assertTrue(c.img[8:17, 110:116].any())

    def test_a_word_set_as_one_wide_piece_is_a_name(self):
        src, pre = make_source()
        src.img[8:17, 40:80] = True                           # "Canto" joined: 4 sp wide, dense
        c = cues.crop_cue(src, 0, 1, pre, clef=True)
        self.assertFalse(c.img[8:17, 40:80].any())

    def test_the_brackets_round_a_name_go_with_it(self):
        src, pre = make_source()
        src.img[8:17, 40:80] = True                           # the word
        src.img[6:24, 32:35] = True                           # "(" : thin, taller than the word
        src.img[6:24, 85:88] = True                           # ")"
        c = cues.crop_cue(src, 0, 1, pre, clef=True)
        self.assertFalse(c.img[6:17, 30:90].any())

    def test_dust_above_the_staff_does_not_lift_the_cue(self):
        s, pre = rest_line()
        r = cueplace.respan(s, cueplace.shown_bars(s, pre), 0, 0, 11, 12)
        r.img[5, int(r.bars_x[0]) + 3] = True                # one speck
        src, spre = make_source()
        cue = cues.crop_cue(src, 1, 1, spre, clef=True)
        _, warns = cueplace.draw_cue(r, cue, int(r.bars_x[0]), 0.6)
        self.assertEqual(warns, [])


PARTS = ["Canto", "Alto Trombone", "Tenore I Voce", "Bass"]


class TestCueLine(unittest.TestCase):
    def test_a_voice_by_number_or_by_name_and_its_bars(self):
        self.assertEqual(cues.parse_cue_line(PARTS, "3=97-98"), ({"src": "Tenore I Voce", "bars": [97, 98]}, ""))
        self.assertEqual(cues.parse_cue_line(PARTS, "canto = 5")[0], {"src": "Canto", "bars": [5, 5]})
        self.assertEqual(cues.parse_cue_line(PARTS, "Tenore I Voce=20 - 22")[0]["bars"], [20, 22])

    def test_options(self):
        e, err = cues.parse_cue_line(PARTS, "1=5-6 noclef size=0.5 label=Soprano")
        self.assertEqual(err, "")
        self.assertEqual(e, {"src": "Canto", "bars": [5, 6], "clef": False, "size": 0.5, "label": "Soprano"})
        self.assertEqual(cues.parse_cue_line(PARTS, "1=5 nolabel")[0]["label"], "")

    def test_a_word_at_a_bar(self):
        self.assertEqual(cues.parse_cue_line(PARTS, '"Canto"=97'), ({"text": "Canto", "bar": 97}, ""))
        self.assertEqual(cues.parse_cue_line(PARTS, "'Quinta Vox'=3")[0], {"text": "Quinta Vox", "bar": 3})
        self.assertIn("one bar", cues.parse_cue_line(PARTS, '"Canto"=97-98')[1])
        self.assertIn("no options", cues.parse_cue_line(PARTS, '"Canto"=97 noclef')[1].replace("takes ", "").replace("a word ", "no "))

    def test_every_mistake_has_a_message(self):
        for line in ("", "3", "=5", "9=1", "Nobody=1", "3=", "3=a", "3=1-2-3", "3=5-4", "3=5 size=9", "3=5 size=x",
                     "3=5 wide", "3=1 -", '"Canto=97'):
            e, err = cues.parse_cue_line(PARTS, line)
            self.assertIsNone(e, line)
            self.assertTrue(err, line)

    def test_a_cue_prints_as_the_line_that_makes_it(self):
        for line in ("3=97-98", "1=5 noclef", "1=5-6 size=0.5 label=Sop", '"Canto"=97'):
            e, _ = cues.parse_cue_line(PARTS, line)
            e2, _ = cues.parse_cue_line(PARTS, cues.entry_text(e).replace(e.get("src", ""), str(PARTS.index(e["src"]) + 1)) if "src" in e else cues.entry_text(e))
            self.assertEqual(e, e2, line)


class TestRestTable(unittest.TestCase):
    def strip(self, **kw):
        s, _ = rest_line()
        return Strip(s.img, 0, s.staff_top, s.staff_bottom, 10.0, s.hdr, **kw)

    def test_rests_that_meet_at_a_line_break_are_one(self):
        a = self.strip(bar_nums=[10, 12], rest_counts=[2, 3], bars_x=[100, 200])     # bars 10-11 | 12-14
        b = self.strip(bar_nums=[15, 20], rest_counts=[1, 0], bars_x=[100, 200])     # bar 15, then music
        self.assertEqual(cues.long_rests([a, b], 3), [(10, 15, 6)])

    def test_music_ends_a_rest_and_short_rests_are_left_out(self):
        a = self.strip(bar_nums=[1, 2, 3], rest_counts=[0, 2, 0], bars_x=[10, 20, 30])
        self.assertEqual(cues.long_rests([a], 2), [(2, 3, 2)])
        self.assertEqual(cues.long_rests([a], 3), [])

    def test_a_rest_line_counts(self):
        from partitor.model import RestRun
        s = self.strip()
        s.rest_src = (None, 0, RestRun(13, 9))
        s.bar_no = 9
        self.assertEqual(cues.long_rests([s], 6), [(9, 21, 13)])

    def test_letters_are_found_by_bar_number(self):
        data = {"systems": [{"bar_nums": [23, 24, 25], "marks": [[2, "A"]]}, {"bar_nums": [26], "marks": []}]}
        self.assertEqual(cues.letter_bars(data), {25: "A"})


class TestCueCommands(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.share = Path(self.tmp.name, "share")
        (self.share / "inbox").mkdir(parents=True)
        self.item = self.share / "library" / "2026-10-0001-s"
        self.item.mkdir(parents=True)
        pt.save_item(self.item, {"id": "2026-10-0001", "slug": "s", "parts": list(PARTS),
                                 "groups": {"Trombones": ["Alto Trombone"]},
                                 "systems": [{"id": "p1.s1", "staves": 4, "map": list(PARTS), "bar": 1, "bars": 3}]})
        self.env = mock.patch.dict(os.environ, {"PARTITOR_LIBRARY": str(self.share)})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def run_cmd(self, fn, answers=(), **kw):
        it = iter(answers)
        real = builtins.input
        builtins.input = lambda prompt="": next(it)
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                rc = fn(argparse.Namespace(id="1", build=False, **kw))
        finally:
            builtins.input = real
        return rc, buf.getvalue()

    def test_one_line_for_several_parts_is_saved_and_the_build_is_told(self):
        self.run_cmd(cli_cues.cmd_cue, lines=["1=97-98"], parts="Bass,3")
        data = pt.load_item(self.item)
        self.assertEqual(data["cues"], {"Bass": [{"src": "Canto", "bars": [97, 98]}],
                                        "Tenore I Voce": [{"src": "Canto", "bars": [97, 98]}]})
        self.assertEqual(sorted(data["pending"]), ["Bass:cues", "Tenore I Voce:cues"])

    def test_the_same_line_twice_changes_nothing(self):
        self.run_cmd(cli_cues.cmd_cue, lines=["1=97"], parts="Bass")
        _, out = self.run_cmd(cli_cues.cmd_cue, lines=["1=97"], parts="Bass")
        self.assertEqual(len(pt.load_item(self.item)["cues"]["Bass"]), 1)
        self.assertIn("already there", out)

    def test_a_group_may_take_a_cue_but_not_from_its_own_member(self):
        self.run_cmd(cli_cues.cmd_cue, lines=["1=5-6"], parts="Trombones")
        self.assertIn("Trombones", pt.load_item(self.item)["cues"])
        with self.assertRaises(SystemExit):
            self.run_cmd(cli_cues.cmd_cue, lines=["2=5"], parts="Trombones")
        with self.assertRaises(SystemExit):
            self.run_cmd(cli_cues.cmd_cue, lines=["1=5"], parts="Canto")          # a part does not cue itself

    def test_an_unknown_part_or_a_bad_line_stops_and_saves_nothing(self):
        for kw in ({"lines": ["1=5"], "parts": "Nobody"}, {"lines": ["1=x"], "parts": "Bass"}):
            with self.assertRaises(SystemExit):
                self.run_cmd(cli_cues.cmd_cue, **kw)
        self.assertNotIn("cues", pt.load_item(self.item))

    def test_the_menu_adds_lists_and_removes(self):
        _, out = self.run_cmd(cli_cues.cmd_cues, ["Bass", "1=5-6", '"Canto"=9', "x 1", "", ""], part=None)
        # (the part prompt takes Bass, then three lines, then Enter ends the part, Enter ends the menu)
        self.assertEqual(pt.load_item(self.item)["cues"], {"Bass": [{"text": "Canto", "bar": 9}]})

    def test_the_menu_shows_a_wrong_line_and_goes_on(self):
        _, out = self.run_cmd(cli_cues.cmd_cues, ["Bass", "9=1", "1=5", "", ""], part=None)
        self.assertIn("no part 9", out)
        self.assertEqual(len(pt.load_item(self.item)["cues"]["Bass"]), 1)

    def test_the_menu_of_the_item_has_key_u(self):
        with contextlib.redirect_stdout(io.StringIO()):
            real = builtins.input
            answers = iter(["u Bass", "1=5", "", "b"])
            builtins.input = lambda prompt="": next(answers)
            try:
                pt.item_menu(self.item)
            finally:
                builtins.input = real
        self.assertIn("Bass", pt.load_item(self.item)["cues"])

    def test_cues_stay_when_the_source_is_analysed_again(self):
        self.run_cmd(cli_cues.cmd_cue, lines=["1=5"], parts="Bass")
        keep = pt.load_item(self.item)
        pt.save_item(self.item, {"id": "2026-10-0001", "slug": "s", "parts": list(PARTS), "systems": []})
        data = pt.merge_item_keys(self.item, keep, again=True)
        self.assertEqual(data["cues"], {"Bass": [{"src": "Canto", "bars": [5, 5]}]})

    def test_a_table_without_built_lines_says_so(self):
        text = "\n".join(cli_cues.rest_table(self.item, pt.load_item(self.item), "Bass"))
        self.assertIn("no built systems", text)


class TestSavedLines(unittest.TestCase):
    def test_lines_saved_before_cues_still_load(self):
        """The new Strip fields have a default, so a .lines file of an earlier release loads."""
        for name in ("cue_labels", "cue_todo"):
            self.assertIn(name, lines._FIELD_DEFAULTS)
            self.assertEqual(lines._FIELD_DEFAULTS[name](), [])

    def test_a_line_without_cues_has_empty_cue_fields(self):
        s, _ = rest_line()
        self.assertEqual((s.cue_labels, s.cue_todo), ([], []))


class TestJustifyKeepsTheCueBars(unittest.TestCase):
    def test_the_bars_under_a_cue_get_no_extra_space_from_justify(self):
        s, pre = rest_line(merge=False)
        s.rest_counts = []
        src, spre = make_source()
        src.bar_nums = [11, 12, 13, 14, 15]
        out, _ = cueplace.apply_cues([s], [pre], [cues.CueSpec("Canto", 11, 12)],
                                     {"Canto": ([src], {id(src): spre})}, "Alto")
        c = out[0]
        width = lambda x: int(x.bars_x[1]) - int(x.bars_x[0])
        j = lines.justify(c, lines.staff_end(c) - int(c.staff_x0) + 120)
        self.assertGreater(lines.staff_end(j), lines.staff_end(c) + 100)       # it was stretched ...
        self.assertEqual(width(j), width(c))                                   # ... but not under the cue

    def test_a_line_with_no_other_room_gives_the_space_to_the_cue_bar(self):
        # every other column holds ink: the bar under the cue is the only place that can take space
        s, pre = rest_line(merge=False)
        s.rest_counts = []
        src, spre = make_source()
        src.bar_nums = [11, 12, 13, 14, 15]
        out, _ = cueplace.apply_cues([s], [pre], [cues.CueSpec("Canto", 11, 12)],
                                     {"Canto": ([src], {id(src): spre})}, "Alto")
        c = out[0]
        pa, pb = lines._cue_spans(c)[0]
        c.img[int(c.staff_top - 10), 5:pa - 1] = True                      # ink in every column outside the cue bar
        c.img[int(c.staff_top - 10), pb + 3:lines.staff_end(c) - 2] = True
        want = lines.staff_end(c) - int(c.staff_x0) + 120
        j = lines.justify(c, want)
        self.assertGreater(lines.staff_end(j), lines.staff_end(c) + 100)   # justified all the same
        self.assertGreater(int(j.bars_x[1]), int(c.bars_x[1]) + 100)       # by the bar under the cue

    def test_a_cue_bar_wider_than_the_cue_keeps_the_cue_barline_on_the_part_barline(self):
        s, pre = rest_line(merge=False)
        s.rest_counts = []
        src, spre = make_source()
        src.bar_nums = [11, 12, 13, 14, 15]
        out, _ = cueplace.apply_cues([s], [pre], [cues.CueSpec("Canto", 11, 12)],
                                     {"Canto": ([src], {id(src): spre})}, "Alto")
        c = out[0]
        pa, pb = lines._cue_spans(c)[0]
        c.img[int(c.staff_top - 10), 5:pa - 1] = True
        c.img[int(c.staff_top - 10), pb + 3:lines.staff_end(c) - 2] = True
        j = lines.justify(c, lines.staff_end(c) - int(c.staff_x0) + 120)
        drawn, _ = cueplace.draw_cues([j])
        d = drawn[0]
        top = d.img.shape[0] - j.img.shape[0]
        cue_rows = d.img[:top + int(j.staff_top) - 14]                       # (above the ink row of this test)
        right = int(np.flatnonzero(cue_rows.any(axis=0)).max())
        self.assertLessEqual(abs(right - int(d.bars_x[1])), 2)               # the last barline of the cue is the part's

    def test_a_cue_over_a_bar_the_part_plays_keeps_its_clef_inside_the_staff(self):
        s, pre = rest_line(note_bar=0)              # bar 10 plays: the cue stands above it, no rest is covered
        src, spre = make_source()
        src.bar_nums = [10, 11, 12, 13, 14]
        out, warns = cueplace.apply_cues([s], [8], [cues.CueSpec("Canto", 10, 11)],
                                         {"Canto": ([src], {id(src): spre})}, "Alto")
        self.assertEqual(len(out[0].cue_todo), 1)
        drawn, dwarns = cueplace.draw_cues(out)
        self.assertFalse([w for w in dwarns if "left of the system" in w], dwarns)     # the music starts at 8 px only
        d = drawn[0]
        top = d.img.shape[0] - s.img.shape[0]
        self.assertTrue(d.img[:top + int(s.staff_top) - 8, int(s.staff_x0):].any())     # the cue is there ...
        self.assertTrue(len(d.cue_labels) == 1 and d.cue_labels[0][0] >= int(s.staff_x0))  # ... right of the staff start

    def test_a_line_without_cues_is_justified_as_before(self):
        s, pre = rest_line()
        self.assertEqual(lines._cue_spans(s), [])

    def test_a_count_of_a_rest_lifts_the_cue_clear_of_its_digits(self):
        s, pre = rest_line()
        r = cueplace.respan(s, cueplace.shown_bars(s, pre), 0, 0, 10, 12)
        src, spre = make_source()
        cue = cues.crop_cue(src, 0, 1, spre, clef=False)
        x = int(r.rest_labels[0][0]) - 5
        out, _ = cueplace.draw_cue(r, cue, x, 0.3)
        box = [b for b in cueplace._count_boxes(out)][0]
        rows = np.flatnonzero(out.img[:, x:x + 40].any(axis=1))
        cue_rows = rows[rows < int(out.staff_top) - 8]
        self.assertLess(int(cue_rows.max()), int(min(box[1], box[3] - 0.75 * box[4])))


class TestCountOffByAPixel(unittest.TestCase):
    def test_a_count_a_pixel_off_the_top_line_still_lifts_the_cue(self):
        s, pre = rest_line()
        r = cueplace.respan(s, cueplace.shown_bars(s, pre), 0, 0, 10, 12)
        r.rest_labels = [(cx, text, 1) for cx, text, _ in r.rest_labels]      # the row of the top line, 1 px off
        self.assertEqual(len(cueplace._count_boxes(r)), 1)
        src, spre = make_source()
        cue = cues.crop_cue(src, 0, 1, spre, clef=False)
        x = int(r.rest_labels[0][0]) - 5
        out, _ = cueplace.draw_cue(r, cue, x, 0.3)
        box = cueplace._count_boxes(out)[0]
        rows = np.flatnonzero(out.img[:, x:x + 40].any(axis=1))
        self.assertLess(int(rows[rows < int(out.staff_top) - 8].max()), int(min(box[1], box[3] - 0.75 * box[4])))


class TestNameZone(unittest.TestCase):
    def test_everything_above_the_staff_before_the_music_goes(self):
        src, pre = make_source()
        src.img[8:20, 40:47] = True                          # a printed bar number, a thin piece
        src.img[10:14, 50:52] = True                         # a bracket
        src.img[10:12, 120:170] = True                       # a slur in the first bar, after the zone
        c = cues.crop_cue(src, 0, 1, pre, clef=True)
        self.assertFalse(c.img[8:20, 40:56].any())
        self.assertTrue(c.img[10:12, 120:170].any())


if __name__ == "__main__":
    unittest.main()
