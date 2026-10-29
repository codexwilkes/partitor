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
| Barlines, bar count | good | A bar number that touches a cue bracket is not read. The count is checked against printed numbers; a mismatch goes to review. |
| Footer, page edge | good | Marks more than 1 sp past the staff end stay (they could be real). |
| Clefs | about 97 % on real scans | A rare clef (G1, C2, C5, F3, F5) can be read for a common one. G8 is sometimes missed; part mapping treats G2 and G8 as the same clef. |
| Part mapping | good | Systems with only unlabelled staves after a change in staff count ask the operator. A stray "Continuo" label read by OCR on an upper staff can make a system ask. |
| Lyrics, text ownership | good | A single word can land on the wrong staff. |
| Rests | good | Whole-bar rests inside printed staves stay as engraved. "Tacet" is not built. |
| Ambitus | weak: about half of the extremes right in early tests | See below. |
| Page turns | good on groups | Lines that end in rests and final double barlines are not used as turn points when `turns=any`. A one-bar rest is too short to turn on. |

## Ambitus

The lowest and highest note of each part are printed on the first line. Every
note counts, so a false notehead changes the range. Causes seen: a beam or flag
start near a head, a staff-line remnant in an empty stretch, an accidental
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

## Platform

- Tested: Ubuntu 26.04 LTS (CPython 3.14, x86-64) with systemd. This is the
  supported platform.
- Python 3.12 (Ubuntu 24.04): the pinned packages have binary wheels, and the
  test suite passes on CPython 3.12.3. Not checked: the golden renders on 3.12,
  and the installer on a real 24.04 host. CI runs the tests on 24.04 with
  Python 3.12 and 3.13.
- macOS, WSL2 without systemd: not supported in 0.4.0-rc.1. The wrapper needs
  `systemd-run`. A mode without the sandbox is planned (best effort).

Performance: a 70-page score takes minutes to analyse (about 30 minutes on a
slow mini PC); a build of one piece takes minutes. The build runs at low
priority.
