<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
<!-- Copyright (C) 2026 Nathan Wilkes and partitor contributors -->
# Known limits

What the engine gets wrong, or does not do. Check these before you trust a
result. The proof PDF (`<id>-proof.pdf`) is the place to look first.

## Input

- Music with one staff per part on clean vector PDFs works best. Phone scans
  work, but fail more often (curl, shadow, light print).
- Not planned: divisi (two parts on one staff), one-line percussion staves,
  page curl beyond what the straightening step corrects.
- Mensurstriche (barlines only between staves) are handled: the dashes are
  removed. A real barline through such a staff is not drawn.
- A PDF page that is not music but looks like it (a manuscript facsimile) can
  count as music. Leave it out with a page range.

## Analysis

| Step | State | Known failures |
|---|---|---|
| Staves, systems | good | Page curl moves staff ends. |
| Barlines, bar count | good | A bar number that touches a cue bracket is not read. The count is checked against printed numbers; a mismatch goes to review. A movement with a pickup or incipit is not checked; in a movement with a split bar the systems before the first split are. |
| Footer, page edge | good | Marks more than 1 sp past the staff end stay (they could be real). |
| Clefs | about 97 % on real scans | A rare clef (G1, C2, C5, F3, F5) can be read for a common one. G8 is sometimes missed (an 8 that does not touch the clef's curl or sits under it is found; a faded or very small one may not be); a missed 8 shows the part in G2, with the notes at the same staff positions. Part mapping treats G2 and G8 as the same clef. |
| OCR | English only | Tesseract reads the staff names and the bar numbers with its English data. A name in another language can be misread. Correct it by hand (`t` in the item menu). |
| Part mapping | good | Systems with only unlabelled staves after a change in staff count ask the operator. A stray "Continuo" label read by OCR on an upper staff can make a system ask. |
| Lyrics, text ownership | good | A single word can land on the wrong staff. |
| Title below the top of the page | asks, never drops | The question about systems above a title (another piece) is asked only for the first page of the score, and only for a title that is centred, at least 12 sp wide and 1.8 sp high. A title that is left-aligned, small or on a later page is not found; use `analyse ID --drop p1.s1`. |
| Rests | good | Whole-bar rests inside printed staves stay as engraved. "Tacet" is not built. |
| Ambitus | weak: about half of the extremes right in early tests | See below. |
| Page turns | good on groups | Systems that end in rests and final double barlines are not used as turn points when `turns=any`. A one-bar rest is too short to turn on. |

## Ambitus

The lowest and highest note of each part are printed on the first system. Every
note counts, so a false notehead changes the range. Causes seen: a beam or flag
start near a head (the flag curl of a stem-down eighth is dropped by its width, also when a staff line cuts its head in two), a staff-line remnant in an empty stretch, an accidental
counted as a head, a head on a line that is missed (the range narrows). Whole
and half notes on a line can be missed.

The operator is the defence. The proof rings each extreme in green with its bar
and page. `partitor show` lists them, doubtful ones with `?`. Menu `k` sets a
range by hand; a hand value is never overwritten. Accidentals are not read, so
a range has letter names only.

Ideas not built: reject accidentals and beams by shape, require ink on 60 % of
the rows of a blob, a usual range per instrument as a doubt signal only,
per-system consistency.

## Layout

- Re-flow (cutting systems at barlines) is experimental and off by default. It
  did not enlarge some real parts. Use paper `ledger` for a larger staff.
- Ledger output enlarges 1-bit strips about 2.2 times; the quality on a print
  is not measured.
- Margins and sizes are estimates from test prints on a few printers. Check the
  first print of every part.

## Cues

- A cue is whole bars of one voice, with its own clef and key at a small size (0.6 of the staff by
  default). It is never drawn in the staff, only above it, and above the top staff of a group. There is no
  transposition and no note reading: the cue is an image of the source. A voice with several staves is not
  taken.
- The bars under a cue are shown as one multi-bar rest, also when they were printed bar by bar.
- Cues are not made with `reflow=on` (the build says so). `partitor plan` does not count the height a
  cue adds; the build does, and the page turns are planned with it.
- The bars of the part under a cue, before its anchor, must be rests. Where a faint scan does not allow the
  program to read that, the cue is placed on your word and the build warns: look at the part before you
  print it. After the anchor the cue runs over the bars as they are; only the anchor barline meets one of
  the part, unless `fit` stretches the cue (the notes of the cue are then squashed or stretched). `sync=N` lines up one note of the cue with the
  first note of the part; it counts notes with a stem only (a whole note is not found) and reads the top
  staff of a group. `align=N` does the same without stretching: the cue moves sideways as it is, so its
  barline no longer meets the barline of the part; it cannot move left of the start of the staff.
- A bar that a system break cuts keeps its number on both systems; a cue reads the half that stands like the bar of the part (first or last of its line); a bar in the middle of a line of the part is read where it first stands.
- A system with more bar numbers than barlines (a false barline next to the clef, found by `partitor bars`) has no
  bar numbers in the part, and a cue from it is left out; the build names the system. Settle its barlines first.
- No separate proof for cues: build the part (the set before is kept in `parts.prev`) and look at it.
  The size is a factor of the staff: check the print of the large-print copy and of the small one.
- An upbeat before the entry is not cropped (whole bars only). The table of long rests does not name the
  voice that sounds next.

## Platform

- Tested: Ubuntu 26.04 LTS (CPython 3.14, x86-64) with systemd. This is the
  supported platform.
- Python 3.12 (Ubuntu 24.04): the pinned packages have binary wheels, and the
  test suite passes on CPython 3.12.3. Not checked: the golden renders on 3.12,
  and the installer on a real 24.04 host. CI runs the tests on 24.04 with
  Python 3.12 and 3.13.
- macOS, WSL2 without systemd: the wrapper needs `systemd-run`, so it does not run there. On macOS
  you can run the engine directly, without the sandbox (steps in the operator guide; best effort,
  not supported; the CI tests run on macOS and a failure there does not block a release).

Performance: a 70-page score takes minutes to analyse (about 30 minutes on a
slow mini PC); a build of one piece takes minutes. `detect` and `build` analyse
the pages in parallel workers (`PARTITOR_JOBS`, `--jobs`; `--jobs 1` = one
process). The build runs at low priority.
