<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
<!-- Copyright (C) 2026 Nathan Wilkes and partitor contributors -->
# Plan a part: page size, page turns and fold-outs

Use `partitor plan` to choose the paper and the staff size of a part before
you print it. It shows what each choice does to the page turns. This page
shows how to use it, and how to print and assemble a part that has fold-outs.
The rules behind it are in `docs/DESIGN.md` §5.7 and §5.8.

## Why

A part for a group score (for example three trombones on one system) is easy
to read at ledger size (17 × 11 in) but does not fit a music stand well.
Letter pages give the same staff size on a stand, but the part has more pages
and more page turns. `plan` helps you find the best trade.

A part of three pages or more is bound (3-hole punch or comb). It is printed
double-sided. The planner adds extra margin at the spine and puts the page
turns where the player rests.

## Quick start

1. Build the item once: `partitor rebuild 12`.
2. Look at the options: `partitor plan 12 Trombones`.
3. Choose one: `partitor plan 12 Trombones 4` (option 4).
4. Apply it: `partitor rebuild 12 Trombones`.
5. Print. If the part has fold-outs, open the file that ends in `-assemble.txt`.

`plan` changes nothing until you choose a number. A choice is saved as
settings of that part only, and `plan` marks it. You can choose again at any
time. `partitor plan 12` with no part shows the groups and the parts that have
a bad turn.

## Read the table

The table is short. It shows the option as built (`*`) and the best option of
each paper (`best`). Add `--all` to see every option. The option numbers are
the same in both views. The last line of `plan` gives a ready command for the
best option.

Example (the numbers are only an example):

```
  built: letter, staff 6.0 mm, 28 pages of music, 3 turns, 1 while playing
     #  paper    staff pages  rest short attacca fold-out  bad  note
   * 5  letter  6.0 mm    28    11     1       0        0    1  re-flow
     4  letter  6.5 mm    30     9     2       0        1    0  best, re-flow
     2  ledger  8.0 mm    18     6     0       1        0    0  best
     12 more options: add --all
```

| Column | Meaning |
|---|---|
| `#` | Option number. `*` marks the option as built. |
| `paper`, `staff` | Paper and staff height. |
| `pages` | Pages of music (a fold-out flap counts as a page). |
| `rest` | Page turns where the player rests 2 bars or more. Best. |
| `short` | Turns where the rest is one bar. Good. |
| `attacca` | Turns at the start of a movement. Fair. |
| `fold-out` | Number of fold-out sheets. A fold-out gives 3 pages without a turn. |
| `bad` | Turns while the player plays. Avoid these. |
| `note` | `best`: see below. `re-flow`: lines are cut at barlines for a narrower page. |

`best` means, for that paper: the fewest turns while playing, then the largest
staff, then the fewest fold-outs, then the fewest pages. It is a good first
choice, not a rule. Look at the other rows if you want a bigger staff and can
accept one bad turn, or fewer sheets to assemble.

- A fold-out is chosen only when it removes a bad turn. Each fold-out means
  one more sheet to assemble.
- The numbers are estimates. The build gives the real numbers and prints a
  warning for each turn while playing.

When you choose an option that needs fold-outs, `plan` says so:

```
plan:  Trombones: needs 2 fold-out sheets (17 x 11 in), or 2 Letter flaps to tape; the build writes the print and assembly steps to a text file next to the PDFs
```

## Try a group of parts

Joining parts removes turn points: a turn counts as a rest only when every
staff rests. To see the effect before you change the item:

```
partitor plan 12 --group AltTen=Alto,Tenor
```

The item is copied to a temporary folder, the group is built there, and the
table is shown. The item does not change. To keep a group, define it with
`partitor groups` and rebuild.

## Print and assemble

A part with fold-outs has four files in `parts/`:

- the part file: every page on Letter, except the flaps;
- a file that ends in `-foldout-sheets.pdf`: one ledger sheet (17 × 11 in) for
  each fold-out. A sheet is two PDF pages: front, then back;
- a file that ends in `-foldout-flaps.pdf`: one Letter page for each flap;
- a file that ends in `-assemble.txt`: the steps below, with the pages and
  places of your part.

Make each fold-out one of two ways. The pages are the same. Use the way your
printer allows. Different people can print different parts in different ways.

**A. Ledger printer (cut and fold).**

1. Part file: double-sided, flip on the long edge. Print only the pages that
   `-assemble.txt` lists (the sheets replace the others).
2. Sheet file: ledger paper, double-sided, flip on the short edge.
3. Cut each sheet along the dotted "cut" line. This takes about ½ in off the
   free edge of the flap.
4. Fold along the dotted line in the middle. The flap folds forward over its page.
5. Put each sheet in the place that `-assemble.txt` gives ("in place of pages
   3 and 4 of the part file").

**B. Letter printer only (cut and tape).**

1. Part file: double-sided, flip on the long edge, all pages.
2. Flap file: Letter, one side only. Each page is one flap.
3. Cut each flap along the dotted "cut" line (about ½ in off the free edge).
4. Put the flap next to its page, edge to edge. The page and edge are on the
   flap ("Tape the left edge of this page to the right edge of page 2a/30")
   and in `-assemble.txt`. Tape the joint on the back with narrow tape. Fold the
   flap forward over its page.

Then punch or bind the stack.

Each sheet page and each flap page has a line at the foot with its number, the
print setting and the place. If a page comes out wrong, you can read it there.

A sheet is one leaf. Its flap is on the outer edge. Its other face (the back
of the bound half) is a normal page of the part. A fold-out has three faces
that you see without a turn: unfold the flap at the start, fold it in before
the turn. The player must rest at both ends.

On the stand, open fold-outs are about 25 in wide. Check your stand. Staves
stop inside the cut line, so no dotted line touches music.

## Settings

Set with `partitor set ID PART:key=value`. `plan PART N` sets `paper`,
`max_staff_mm`, `reflow`, `foldouts` and `pages` for you. All keys: `paper`, `max_staff_mm`, `reflow`, `foldouts` (`on` or `off`),
`foldside` (`right`, `left`, `auto`), `binding` (mm at the spine), `pages`
(page limit), `duplex`. A part with `duplex=off` is single-sided and has no
plan.

## Rests

Bars that hold only rests on every staff are merged into one multi-bar rest
(count above every staff) before the lines are cut and paged. This makes
lines shorter and gives the planner more turn points. A bar with a note, a
rehearsal mark or a printed number is never merged. Set `rests: keep` to print
every bar as engraved.

## Limits

- A fold-out needs a rest at both ends. If the music has none, the plan keeps
  a bad turn and the build warns about it.
- A right fold-out cannot be followed by a left one. A left fold-out cannot
  follow a title page.
- A line that cannot be cut narrow enough makes an option unavailable. The
  note says which line.
- Per-staff rests are not used yet: a turn where one staff rests is counted
  as bad.
