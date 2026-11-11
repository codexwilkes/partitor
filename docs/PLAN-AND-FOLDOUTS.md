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

## Which command?

| You want to | Use | Menu key |
|---|---|---|
| choose paper and staff size before a build | `partitor plan ID PART` | `f` |
| see the pages of a built part and move a system to another page | `partitor pages ID PART` | `l` |
| apply a changed setting (turns, breaks, fold-outs) without a new build | `partitor repage ID PART` | `x` |
| change any setting | `partitor set ID PART:key=value` | `s` |
| build or rebuild | `partitor rebuild ID PART` | `r` |

A turn is reported by its printed page number, for example "page 26/30, before
bar 45": the number you read on the sheet.

## Quick start

1. Build the item once: `partitor rebuild 12`.
2. Look at the options: `partitor plan 12 Trombones`.
3. Choose one: `partitor plan 12 Trombones 4` (option 4).
4. Apply it: `partitor rebuild 12 Trombones`.
5. Print. If the part has fold-outs, open the file that ends in `-assemble.txt`.

Step 3 also sets the page limit. Without it, the build can shrink the staff
of a group part to stay inside an old limit (staff 4 mm instead of 6 mm).

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

A part with fold-outs has four files in `parts/` (six with the large-print copy):

- the part file: every page on Letter, except the flaps;
- a file that ends in `-foldout-sheets.pdf`: one ledger sheet (17 × 11 in) for
  each fold-out. A sheet is two PDF pages: front, then back;
- a file that ends in `-foldout-flaps.pdf`: one Letter page for each flap;
- a file that ends in `-assemble.txt`: the steps below, with the pages and
  places of your part;
- with the large-print copy: the large part file (`-11x17.pdf`) and a file that
  ends in `-foldout-flaps-11x17.pdf`: the flaps at the large size (way C below).

Make each fold-out one of two ways (a third, C, at the large size). The pages are the same. Use the way your
printer allows. Different people can print different parts in different ways.

**A. Ledger printer (cut and fold).**

1. Part file: double-sided, flip on the long edge. Print only the pages that
   `-assemble.txt` lists (the sheets replace the others).
2. Sheet file: ledger paper, double-sided, flip on the short edge.
3. Cut each sheet along the dotted "cut" line. This takes about ½ in off the
   free edge of the flap. With `cutline=marks` the sheet has short crop marks
   at the top and foot instead; with `cutline=off` it has no line (trim ½ in
   by eye).
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

**C. Large copy (11 × 17 in, or A3 for A4 parts; cut and tape).** Only when the
large-print copy is on (`large: on`, the default).

1. Large part file (`-11x17.pdf`): 11 × 17 in, double-sided, all pages. Cut off
   the blank strip at the foot at the line across the sheet.
2. Large flap file (`-foldout-flaps-11x17.pdf`): 11 × 17 in, one side only, one
   flap per sheet. Cut off the blank strip at the foot in the same way.
3. Cut each flap along its "cut" line (about 0.65 in off the free edge at this size).
4. Tape each flap to its page as in B. The page numbers are the same.

There is no large fold-out sheet: no normal paper holds two 11 × 17 pages side
by side.

Then punch or bind the stack.

Each sheet page and each flap page has a line at the foot with its number, the
print setting and the place. If a page comes out wrong, you can read it there.

A fold-out gives three pages that you see without a turn: the flap, and the
two pages behind it. Unfold the flap at the start, fold it in before the turn.
The player must rest at both ends. A ledger sheet is one piece of paper that
carries the flap and the page it folds over; its back is the next page.

On the stand, open fold-outs are about 25 in wide. Check your stand. Staves
stop inside the cut line, so no dotted line touches music.

## Fix a bad turn by hand

`partitor pages ID PART` shows one line for each page of a built part: its
bars, its systems, the room left at the foot (in systems) and the turn after
it. A turn while the player plays is marked `PLAYING`.

```
        page  bars      systems   room  turn after it
       25/30  11-27           4    1.0  -
       26/30  28-44           4    0.3  PLAYING  <- move a system?
       27/30  45-58           3    2.0  -
```

To move the last system of page 26 to page 27:

```
partitor pages 12 Trombones --move 26=1
```

`--move 26=-1` brings the first system of the next page up to page 26. The
part is paged again from that page on, and the table is shown again. The break
is saved as a manual page break (`[manual]` in the table) and stays through
later builds. `--clear` drops the manual breaks of the part. `--dry-run` shows
the pages after a move and saves nothing. Use one `--move` for each call.

Use it when the planner could not find a good turn, or when you see a better one
on the page. The pages before the moved page keep their ends: if the planner
would change one, `pages` saves a manual break there too (`[manual]`; the
`breaks:` line lists them). If the next page has no room, the later pages move
on by themselves. The `<- move a system?` mark shows only when the next page has
room for a system. A move pages the part again with `turns=rest` and keeps that
setting; if the repage fails, the settings are put back. In the item menu (key
`l`) `pages` asks for a move after the table.

A move up to a page with no room is refused: a break is a limit, so the page would
only get shorter. Move a system off that page first.

`plan` keeps the manual breaks in its estimates (a break after bar N ends a page
where a line ends after bar N). A row says "N break(s) end no line" when a break
falls inside a line at that size. After `plan ID PART N`, check the breaks with
`pages`; if a break no longer ends a line, drop them with `--clear`. A part built
before 0.8.21 has no bar numbers in its plan data: `plan` says so; rebuild once.

## Settings

Set with `partitor set ID PART:key=value`. `plan PART N` sets `paper`,
`max_staff_mm`, `reflow`, `foldouts` and `pages` for you. All keys: `paper`, `max_staff_mm`, `reflow`, `foldouts` (`on` or `off`),
`cutline` (`dotted`, `marks`, `off`: how the cut is shown, also on the large-print copy),
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
  note says which line, how wide, and its bars (for example "line 6 cannot be
  cut: 300 mm of music (bars 37-40)"). Look at those bars in the proof: a line
  with no clef and key to copy, or one very wide bar, limits the staff size on
  that paper.
- Per-staff rests are not used yet: a turn where one staff rests is counted
  as bad.
