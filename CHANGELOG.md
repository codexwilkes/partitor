<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
<!-- Copyright (C) 2026 Nathan Wilkes and partitor contributors -->
# Changelog

Format: [SemVer](https://semver.org). Entries list user-visible changes. The
engine file (`lib/partitor-engine`) keeps the detailed history of the private
development line (0.1.0 to 0.3.0-dev.42) in its header comment.


## 0.8.39 — 2026-11-11

### Changed
- `pages --move` keeps the pages before the moved page with pins, and pins are now apart from your
  manual breaks. Before, they were saved as breaks: one move saved three breaks, and after a
  rebuild at another staff size or with re-flow they still held old page ends ("break after bar
  35: bar is inside a line", short pages). Now the move saves one break and the pins on their own
  (`[pin]` in the `pages` table, `pins=[...]` in `show`). A rebuild or `repage` whose lines changed
  drops the pins, keeps the breaks and says so. `--clear` drops both. Items from before keep their
  breaks as they are. The page breaks of a part without pins do not change.

## 0.8.38 — 2026-11-11

### Fixed
- Two commands on one item at the same time: a `set` while a rebuild ran was saved, and the rebuild
  then marked it built, although the parts used the old value (`show` said `built`). Two rebuilds
  of one item could also remove each other's new set. A command that reads or changes an item now
  holds a lock on it while it runs; a second one stops at once with "item ID is in use: another
  partitor command is working on it" and changes nothing. `show` and `list` are not blocked. On a
  file system without locks (some SMB mounts) the commands work as before.

## 0.8.37 — 2026-11-10

### Fixed
- A rebuild or `repage` of some parts lost the fold-out files of the other parts: their
  `-foldout-sheets.pdf`, `-foldout-flaps.pdf`, `-foldout-flaps-11x17.pdf` and `-assemble.txt` were
  not copied into the new set, while `score.yaml` still named them (they stayed in `parts.prev/`
  until the next build). Every file of a part record is now kept, and a set that misses one of
  them is built whole. `reid` renames these files in the record too.

## 0.8.36 — 2026-11-10

### Fixed
- The large-print copy (`-11x17.pdf`, `-A3.pdf`) of a part with fold-outs had no flaps: it is made
  from the part file, and the flaps are in their own files, so the music of every flap was missing
  at the large size. The flaps now get a large file too, `-foldout-flaps-11x17.pdf` (`-A3.pdf`):
  one flap per sheet, printed on one side, cut, and taped to its page of the large copy. There is
  no large fold-out sheet (no normal paper holds two 11x17 pages side by side).
  `-assemble.txt` gives this as a third way (C), and the `built` record has `large_flaps`.
  A partial rebuild and `reid` keep the new file as they keep the large copy.

## 0.8.35 — 2026-11-10

### Changed
- Faster commands on large items: `score.yaml` and `layout.yaml` are read with the C loader of
  libyaml (part of PyYAML) when it is there, else as before. A rebuild reads `score.yaml` about 11
  times; for a 70-page score that took 30 s and now takes about 3 s. The data read is the same; the
  files are written as before.

## 0.8.34 — 2026-11-10

### Changed
- Faster build and `plan` data: the search for the clef and key signature of each line (used by
  re-flow, rest merging and the plan data) made the ink band of a line once for each line it was
  compared with, about 15 times per line. It now makes it once per line. Same result; on the saved
  lines of four scores (40 parts) the search took 34 s instead of 72 s.

## 0.8.33 — 2026-11-10

### Changed
- Faster build when the pages are in the analysis cache. The build cut each strip (one part, one
  system) by reading the whole page image; it now reads only the box of that part's staves (one pass
  per page finds the box of every staff and header). On a 70-page score with 17 parts this was about
  200 s of a build whose pages were all in the cache. The parts are the same.

## 0.8.32 — 2026-11-10

### Fixed
- Re-flow and `plan`: a line whose clef is damaged on a faded or dotted scan stayed whole and held
  the staff of the whole part small. Its clef and key signature did not match any other line pixel
  for pixel, so no prefix was found. On the trombone group that showed it, two lines (bars 37-40
  and 58-60) allowed Letter only at 5.0 mm; now every size from 8.0 mm down is possible.
  Such a line now takes the clef and key of its neighbours when its key signature agrees with the
  two nearest lines of its own segment (same staves, no rest line between), staff by staff. The
  clef itself is not compared. A key change, an accidental more or less on any staff, or other
  staves, still leaves the line whole.

### Changed
- The build says which lines took a prefix ("prefix borrowed: bars 37-40 take the clef and key of
  bars 41-44") and which stay whole for lack of one ("no clef and key to copy: bars ... stay one
  piece"), each with its bar numbers.
- `partitor plan`: a row that is not possible names the bars of the line that cannot be cut
  ("line 6 cannot be cut: 300 mm of music (bars 37-40)").

## 0.8.31 — 2026-11-10

### Changed
- The H-bar of a multi-bar rest now follows the Bravura restHBar (SMuFL): a bar 1 sp thick on
  the middle line, with a thin serif (0.16 sp, as a barline) at each end from line 2 to line 4.
  Before, each end had a bracket 0.5 sp thick over the full staff height.
- One function (`draw_hbar`) now draws every H-bar: a rest line, a merged measure inside a line
  and a measure joined by re-flow.

### Added
- Layout key `rest_bar` (`--rest-bar`, `set ID rest_bar=...`): `engraved` (default), `bold`
  (serifs 0.35 sp, full staff height, for a faint print or scan) or `heavy` (the look of
  0.8.11 to 0.8.30).

## 0.8.30 — 2026-11-10

### Added

- Group score: the short form of a staff label can be set per part. `partitor set ID
  "Alto Trombone:short=A. Tbn."` (at most 24 characters; `short=auto` brings the rule
  back), or the item menu key `h` (the parts of the groups, numbered, with their short
  form; a new text, or `auto`). The rule stays the default: words of 5 or more
  letters cut to 3 and a full stop. The value is kept in `layout.parts` of the item,
  so it moves with a rename of the part and stays when the score is analysed again.
  The label column is as wide as the longest short form.


## 0.8.29 — 2026-11-09

### Fixed

- Re-flow: two multi-bar rests that meet at the break of two source lines stayed
  as two, "2" and "6" side by side. They are one rest now ("8"). Only rests of two
  or more source lines are joined; a rest inside one source line was merged before.
- Re-flow: a line cut from a source line that starts with a multi-bar rest got a
  stray thick barline after its clef and key, with an empty stretch after it. The
  clef and key of such a line end after the left bracket of its rest, and the copy
  brought the bracket. The copy now comes from a line of the movement that does
  not start with a rest.
- A group score kept the printed instrument label of some staves on its first
  line, and lost the label of the others (Schein, Trombones: "Alto Trombone"
  and "Basso Trombone grosso" stayed, the two tenor labels did not). A
  two-line label left of a staff has ink on all 5 line rows, and in the spaces
  between them. `vision.extend_starts` took it for a faint, dotted line start
  and moved the staff start left onto the label, so the label counted as part
  of the staff. A staff start now moves only when the spaces between its lines
  are (nearly) blank over the stretch.

### Added

- Group score, first line: the full staff names stand left of the ambitus when the
  first line is short enough to hold them (the line is indented, as for a single
  part). The ambitus always shows. With no room, nothing changes: only the ambitus.

### Changed

- Docs: `OPERATING.md` has the steps to change the paper or the staff size of
  one part, and why a low page limit gives a very small staff.

## 0.8.28 — 2026-11-09

### Fixed

- Re-flow stopped with `ValueError: operands could not be broadcast together`
  when the first barline of a line lay inside its clef and key prefix (a bar cut
  by a line break leaves no music after the key signature). The bar had a negative
  width. It now has no width. The error showed in 0.8.27 on a group score, where a
  line that used to stay whole is now cut. The same input stops 0.8.26 too.


## 0.8.27 — 2026-11-09

### Fixed

- Re-flow of a group score: one line could stay whole only because its staves
  lay 2 to 3 px (0.2 sp) off the staves of every other line of the scan. No line
  could lend it a clef and key prefix, and its width capped the staff of the whole
  part (Letter: 4.2 mm instead of about 6 mm or more). A line now borrows a prefix
  from a line whose staves lie within 0.3 sp, and the copied clef and key are moved,
  staff by staff, to the rows of the line that takes them. Two lines still share
  an output line only within 0.07 sp. Parts without this case build the same as
  0.8.26. Rebuild a part whose `plan` says `line N cannot be cut`.


## 0.8.26 — 2026-11-08

### Changed

- The layout key `cutline` now also sets the cut line of the fold-out sheets
  and flaps. `dotted` (default, as before): a dotted line. `marks`: a short
  crop mark at the top and one at the foot. `off`: no line; the notes say to
  trim 1/2 in off the free edge. The notes on the pages and `-assemble.txt`
  name the form chosen. The fold line stays dotted. Rebuild to apply it.


## 0.8.25 — 2026-11-08

### Added

- Layout key `cutline` (`partitor set ID cutline=dotted|marks|off`) for the cut
  line of the large-print copy. `dotted` (default, as 0.8.24): one dotted line
  across the sheet, for scissors or a knife. `marks`: two short crop marks at
  the side edges, for a paper cutter. `off`: no line. Rebuild to apply it.
- `CONTRIBUTING.md` has a section on how to add a choice, and a test checks
  that every choice key is set, described and documented.

### Changed

- The layout file help now describes `foldouts` and `foldside`.

## 0.8.24 — 2026-11-08

### Changed

- The large-print copy (`-11x17`) shows the cut line as one dotted grey line
  across the full sheet, at the foot of the scaled page (14.24 in from the
  top). It replaces the two short crop marks at the side edges. The pages are
  the same.


## 0.8.23 — 2026-11-08

### Fixed

- Biber page 17 was still cut into two systems (3 + 13 staves instead of 16)
  after 0.8.22. The staves start where the system barline stands; the start was
  moved to the page edge (0.8.1) and the barline was looked for left of it.
  The connector is now also looked for at the start as found. Over the 70 pages
  of the Biber, the systems are the same as without that move. Analyse such an
  item again.

### Changed

- Help texts. `partitor analyse --help` lists `--join` and `--unjoin`. Every
  command, option and argument now has a description: `show`, `pieces`,
  `detect` and `build` (all options, with their defaults), `set`, `reid`,
  `rename`, and the commands `expand`, `contract`, `bars`, `parts`, `groups`
  and `meta`, which shared one line. The layout file explains `system_joins`.
  A test fails when a command, option or argument has no description.
  Builds are the same as 0.8.22.

## 0.8.22 — 2026-11-08

### Fixed

- A page with seven equal gaps between staves and no connector at the system
  start was cut into two systems (Biber, pages 5 to 12 and 14: 4 + 13 staves
  instead of 17). Since 0.8.1 the staff start moves to the page edge, and the
  connector is looked for at that place. A gap with no ink at the system start
  now stays joined when a neighbouring gap of the same size is joined and has no
  ink there either. A gap next to a bracket or barline is still a break.
  The effect was a wrong part suggestion and bar numbers counted twice on those
  pages. Analyse such an item again.

### Added

- `partitor analyse ID --join p5:4` (and `--unjoin`): no system ends after staff
  4 of source page 5, for two systems the analysis took apart. In the choices,
  answer `j` to join the system asked about with the one below it; the analysis
  runs again and the questions start over. The join is saved as `system_joins`
  and kept by every later analysis. The options are not in `--help` yet: that
  text is part of the G0 golden.

## 0.8.21 — 2026-11-07

### Changed

- `partitor plan` keeps the manual page breaks in its estimates: a break after
  bar N ends a page where a line ends after bar N. A row says "N break(s) end no
  line" when a break falls inside a line at that size. The plan data of a part
  now holds the bar numbers of its lines; a part built before this release says
  so and needs one rebuild.

### Fixed

- `pages --move` up to a page with no room did nothing useful: the page got
  shorter. It is now refused, with a message.

## 0.8.20 — 2026-11-07

### Fixed

- `partitor pages --move` kept the pages before the moved page only by chance:
  the planner could page the whole part again. The ends of the earlier pages that
  a move would change are now saved as manual breaks too. The guide said this
  already.
- `pages` with `all` stopped with a Python error. It now asks for one part.
- A failed repage after `pages --move` left the new breaks in the settings. They
  are put back now.
- `plan` took `foldside` from the last build, not from the settings.
- The mark `<- move a system?` showed when the next page had no room.
- A test of the analysis cache failed when the clock changed to the next minute
  between two builds (the saved build time was compared). It now ignores the time.

### Changed

- `pages --move`: one move for each call. A second `--move` was computed from the
  old pages.
- `pages` says when settings are not built yet. `plan` says that it does not use
  manual page breaks, and `plan ID PART N` warns when the part has them.

### Added

- `pages --dry-run`: show the pages after `--move`, save nothing.
- Menu key `l` asks for a move after the table.

## 0.8.19 — 2026-11-06

### Added

- `partitor pages ID PART`: one line for each page of a built part: its bars,
  its systems, the room left at the foot (in systems) and the turn after it
  (`PLAYING` for a turn while the player plays). `--move PAGE=N` moves the last
  N systems of a page to the next page (a negative N brings systems up); the
  part is paged again and the table shown again. `--clear` drops the manual
  breaks. Menu key `l`. The guide has a section "Fix a bad turn by hand".

### Fixed

- `partitor plan` (0.8.6 and later) could not reach the library through the
  root front end `bin/partitor`: it was missing from the list of library
  commands, so it ran without the library folder. `plan` and `pages` are now on
  the list.
- A page break set after a bar (`Part:breaks=45`) did nothing on a part with
  re-flow: a cut line has no list of bar numbers. The last bar of such a line is
  now the bar before the first bar of the next line.

## 0.8.18 — 2026-11-06

### Fixed

- A bar of rests on every staff that stands alone at the start or the end of a
  line, or a line with no barline of its own that holds one rest on each staff,
  was not seen as a rest at a page turn, so the planner called the turn a bad
  one. It is now a one-bar rest ("short rest" in the plan table). Each bar keeps
  its count of rest bars (`rest_counts`), so a line cut by re-flow gets the rest
  of its first and last bar. On the Trombones test part both fold sides now have
  no turn while playing.
- A barline that crosses every staff of a group is found before the staff
  lines are cleared (it was missed when the staves were many).
- Saved lines from before this release load without a rebuild.

## 0.8.17 — 2026-11-06

### Changed

- A page turn is reported as the player reads it: the printed page and the next
  bar ("page 26/30, before bar 45"). Before, the report said "PDF page 27 (after
  bar None)": the PDF page is one more than the printed page when the part has a
  title page, and the bar was often unknown. `repage` and the build warning use
  the new text; turns saved by an older build say "(PDF page N)".
- `plan` is listed in `partitor --help` and in the item menu (key `f`), and in
  the command table of `OPERATING.md` and in the operator flow.
- Docs: the plan guide has a "Which command?" table and no longer uses the word
  "leaf".

## 0.8.16 — 2026-11-06

### Fixed

- A merged multi-bar rest (0.8.11) at the start or the end of a line was not
  seen as a rest at a page turn. The page planner, `plan` and the turn report
  looked only at lines that are all rest. A page could end in a bad turn when
  moving one line would have ended it on a rest. A rest of 2 bars or more at a
  line edge now counts, and re-flow gives each cut line the rest of its first and
  last bar.
- Saved lines from before this release load without a rebuild (the two new
  values default to 0, so they keep their old turns until the part is rebuilt).

## 0.8.15 — 2026-11-06

### Fixed

- A merged multi-bar rest (0.8.11) on a line that was mostly rest was stretched
  wrongly when the line was justified: its H-bar was taken for a staff line, the
  space went into the blanks around it, the bar looked short and the count
  stood left of its middle. The staff lines are now read from the staff, the
  H-bar takes most of the extra space, and the count stays on its middle.

## 0.8.14 — 2026-11-06

### Fixed

- A merged multi-bar rest inside a line of a group score (0.8.11) showed its
  count above the top staff only. It now shows the count above every staff. A
  line saved by 0.8.11 to 0.8.13 still loads (its count stays above the top
  staff until the part is rebuilt).

## 0.8.13 — 2026-11-06

### Changed

- The help of `--rests` and the comment on `rests` in `layout.yaml` and
  `score.yaml` now say that a run of bars with only rests on every staff is also
  merged into one multi-bar rest (0.8.11). Text only.

## 0.8.12 — 2026-11-06

### Added

- A second way to make a fold-out, for a printer without ledger paper. A part
  with fold-outs now has a file `NN-part-foldout-flaps.pdf`: one Letter page per
  flap, printed on one side. Cut at the dotted line and tape the flap to the
  outer edge of its page.
- `NN-part-assemble.txt` describes both ways (A: ledger sheets, cut and fold;
  B: Letter flaps, cut and tape), the pages of the part file to print for way A,
  and for each flap the page and edge it is taped to.

### Changed

- The part file is complete: it holds every leaf except the flaps. Print all of
  it for the tape route, or only the listed pages for the ledger route (a ledger
  sheet replaces two consecutive pages). Before, the file had gaps.
- `plan` and the build name both ways: "2 fold-out sheets (17 x 11 in), or 2
  Letter flaps to tape". The record of the part in `score.yaml` has `flaps`.
- Docs: the guide, DESIGN §5.7 and the library layout describe the four files.

## 0.8.11 — 2026-11-06

### Added

- Rest merging inside a line (`rests: compress`, the default). A run of 2 bars
  or more that hold only measure rests on every staff of a part or group line
  becomes one multi-bar rest, with the count above the top staff. A bar with
  a note, a stem, a hollow whole note, a rest of another length, text, a
  rehearsal mark or a printed number is never merged. `rests: keep` turns it
  off. The lines are shorter, so re-flow and `plan` see fewer lines and pages.
- Saved lines (`.lines`) from before this release load without a rebuild: the
  new field `rest_labels` gets its default. A file with any other unknown
  field is still refused.

### Changed

- The page budget and the page turns of parts with long rests move: some
  parts need fewer pages or fewer fold-outs. Run `partitor rebuild` to apply.

## 0.8.10 — 2026-11-06

Change: `partitor plan` and the fold-out print are easier to follow (DESIGN.md §5.7, §5.8).

- `plan` shows a short table: the row as built and the best row of each paper (the fewest turns while
  playing, then the largest staff, then the fewest fold-outs). `--all` shows every row. The row numbers
  do not change. The column `1 bar` is now `short`.
- `plan` ends with a real example command (`plan ID PART N`, the best row).
- `plan PART N` says how many fold-out sheets the option needs, and the build says so too.
- A part with fold-outs gets `NN-...-assemble.txt`: what to print, the flip edge of each file, how to
  cut and fold, and for each sheet its place in the part file.
- Each sheet page has a line for the printer: the sheet number, the flip edge and the place.
- The sheet file is now `NN-...-foldout-sheets.pdf` (was `-foldout.pdf`). Build records have a new key,
  `assemble`.
- The dotted fold and cut lines are on the front of a sheet only. A second set on the back never met the
  first when printed (duplex registration).
- Fix: a justified line no longer pulls a final barline or double bar apart (the gap between the thin and
  the thick line was stretched, so the last bar looked as if it had an extra barline).
- The build warns when a font file is not found (the fallback has no music glyphs: an ambitus then has no clef).
- New guide `docs/PLAN-AND-FOLDOUTS.md`: use `plan`, print and assemble.


## 0.8.9 — 2026-11-05

Add: `partitor plan ID --group Name=Alto,Tenor`: the options of a group of parts that the item does not
have (DESIGN.md §5.8).

- The item is copied to a temporary folder, only the trial groups are built there (every part is skipped,
  the page cache is used), the tables are printed and the folder is removed. The item is not changed.
  Part names or numbers, repeat `--group` for more groups; the score order is kept.
- The trial groups take the layout of the item's first group (`group_gap`, margins, `binding`), and the
  table says `trial build`. Compare the tables with those of the single parts: joining parts removes
  turn points, because a joint line rests only where every staff rests.
- Internal: `cli_items.plan_table` and `plan_trial`; `plan` without `--group` is unchanged.


## 0.8.8 — 2026-11-05

Add: left fold-outs (DESIGN.md §5.7). Layout key `foldside`: `right` (default), `left` or `auto`.

- A left fold-out has the flap to the left of the verso (flap, verso, recto). Its sheet holds the flap
  and the verso on one side and the last recto of the previous group on the other. The flap is numbered
  `6a`, the verso `6b`.
- The planner follows the physical rules: a right fold-out cannot be followed by a left one, and a left
  fold-out cannot open the part after a title page. `auto` takes the right side unless the rules
  forbid it (the cost is the same).
- The sheet file and its cut and fold lines are as for the right fold-out. `repage` applies `foldside`.
- With `foldouts: off` or `foldside: right` output is the same as 0.8.7.


## 0.8.7 — 2026-11-05

Fix: `plan` models the label column of a group score, so the staff of a row is the staff that is printed.

- A group's lines get a label column (staff names, ambitus) after they are cut, and the staff shrinks
  to fit; a row of 6.5 mm built as 6.0 mm. `plan` now cuts for the larger size, lays the pages out at the
  printed size and sets `max_staff_mm` and `pages` so that the build reaches the row. The build saves the
  column width with the plan data (`label_px`).
- `lines.label_column`: the width of the column, taken out of `finish_lines` (output unchanged).
- Output of builds is the same as 0.8.6.


## 0.8.6 — 2026-11-05

Add: `partitor plan ID [PART ...] [N]`, the options of a part (DESIGN.md §5.8).

- A table of paper (Letter, ledger) and staff height (8 to 5 mm) with the pages, the turns by class and the
  fold-outs, from the lines of the last build (read-only, a fraction of a second). Without a part:
  the groups and the parts with a bad turn.
- `plan ID PART N` sets option N for that part (`paper`, `max_staff_mm`, `reflow`, `foldouts`,
  `pages`); `rebuild` makes it. The numbers of the rows stay the same after a choice.
- The build saves the lines before re-flow, with their real bar widths, in `lines/<part>.lines` (key `plan`).
  Parts built earlier are read from their saved lines (an estimate) or need a rebuild.
- `pages` accepts 1 to 99 (was 20): a Letter part of a group score can need 30 pages.
- Fold-outs are planned for Letter and A4 only: a sheet of two pages side by side.
- The command is not in `partitor --help` yet: that text is part of the G0 golden.
- Output of builds is the same as 0.8.5.


## 0.8.5 — 2026-11-05

Add: fold-outs. `foldouts: on` (per part: `set ID "Trombones:foldouts=on"`) plans the pages of a
bound part with `turnplan` and prints the fold-outs as ledger sheets (DESIGN.md §5.7). Default `off`: output is the same as 0.8.4.

- Page breaks, spreads and fold-outs are chosen for the whole part at once. A fold-out (verso, recto,
  flap) starts and ends at a rest turn; it costs less than a turn while playing.
- The part PDF holds the Letter pages; `NN-part-foldout.pdf` holds one ledger sheet per fold-out
  (front: the recto and the flap, with a dotted fold line and a dotted cut line 1/2 in off the flap;
  back: the outside of the flap, blank, and the verso that follows). Page numbers count leaves:
  `7a` the recto, `7b` the flap. The flap holds the same text width as the other pages.
- The report lists the class of each turn; a turn while playing is still a warning.
- `repage` applies `foldouts` without a rebuild. The part's record in `score.yaml` has `foldout` and
  `foldouts`.
- Internal: `render.draw_face` draws one page anywhere on a sheet; `render.page_lines` places the
  lines of a page. Output with `foldouts: off` is the same as 0.8.4.


## 0.8.4 — 2026-11-05

Add: a part can have its own paper, and a binding allowance at the spine.

- `Name:paper=letter|a4|ledger`: one part (a group) on its own paper while the item uses another. The
  build already applied a part's layout over the item's; `set` now accepts the key per part. Also per
  part: `margin_top`, `margin_bottom`, `margin_side`, `gutter`, `duplex`.
- `binding` (mm, default 0 = off; `set binding=12.7`, no command-line option): in double-sided print the
  outer margin stays `margin_side` and the spine margin is `binding` wider, for a punch or a comb
  binding. `gutter` is not used then. The staff is sized for the text width that remains. Parts of 1
  or 2 pages print single-sided without it. With the default 0, output is the same as 0.8.3.
- `set` also checks the margins of each part's own layout.


## 0.8.3 — 2026-11-05

Add: `turnplan`, a page-turn planner for bound parts. No user-visible change yet: the build does not
use it (DESIGN.md §5.7).

- `turnplan.plan_turns`: spreads (verso and recto, a turn after each recto) and fold-out groups
  (three faces, no turn between them), chosen for the whole part at once. Turn classes: rest (2
  bars or more), rest1 (one bar), attacca, bridge (one staff rests next to the turn) and bad. A
  fold-out must start and end at a rest turn: the flap is unfolded and folded in during the rest.
- Turn costs `PLAN_REST_ONE`, `PLAN_FOLD`, `PLAN_BRIDGE` and `PLAN_BAD` in `typography`.
- Output with the existing `plan_pages` is the same as 0.8.2.


## 0.8.2 — 2026-11-05

Fix: re-flow cuts every music line of a group score, so the staff can grow when long source
lines held it small.

- `reflow.find_prefixes`: a multi-bar rest line has no staff labels and split a movement into
  segments; a line alone in its segment had no clef and key prefix and stayed whole. Such a line now
  borrows the prefix of a line of the same movement with the same staves, by the same test as before
  (it must look like the donor up to the donor's prefix).
- `reflow.find_prefixes`: a line that lacks the highest common gap takes the next lower one it has,
  instead of staying whole.
- `reflow.find_prefixes`: the "same music after the gap" test no longer rejects a line when a blank
  of 2.5 sp follows the gap (a rest, or a first note far from the key), and it allows 1.2 sp of
  equal ink (a note head) instead of 0.5 sp.
- `strips.BAR_END_SP` (2.5 sp, was 2.0): a final or repeat barline is found at its middle, up to
  2.2 sp before the staff end; such lines (section ends) counted as not ending at a barline and
  stayed whole.
- On a real three-staff group score (62 lines) all 50 music lines are now cut (before: 41 of 62
  lines, 9 music lines whole), and the staff grows from 3.7 mm to the limit of the page budget.
  Output with `reflow: off` (the default) is the same as 0.8.1.


## 0.8.1 — 2026-11-02

Fix: scans with faded, dotted staff-line starts no longer split systems, and `detect` no longer stops
with `ValueError: min() iterable argument is empty`.

- `vision.extend_starts`: a staff whose line starts are dotted takes the page's left edge as its
  start when all 5 of its line rows hold ink there. Before, the longest solid run set the start, the
  staves of one system started at scattered x, and `group_systems` split the system. Indents and
  staves with a label to the left keep their start.
- `ownership.align_system_start`: if no staff of a system lies within 4 sp of the median start, the
  staves keep their own start. Before, `analyse_page` raised.
- A wrong start on a last staff (pages with a faint bass line) is now corrected. Output can differ
  from 0.8.0 on such pages.


## 0.8.0 — 2026-11-01

Staff labels with accents map to the right part, and publisher and rights lines in French,
Italian, Spanish and German are footer text. G0 output is unchanged.

- `mapping.fold_accents` folds accents (NFKD, combining marks dropped; `œ`, `æ`, `ß` written as
  `oe`, `ae`, `ss`; other letters stay). Label matching uses it: "Cör", "Cœur", "Violoncéllo"
  and "Basse continue" no longer lose points for an accent. Before, "Cör" against "Cor" scored
  0.67, below the 0.7 match limit.
- Footer text: the words `edizioni`, `ediciones`, `éditeur`, `editrice` and the rights phrases
  `droits réservés`, `diritti riservati`, `derechos reservados`, `Rechte vorbehalten` are
  footer. `Éditions` (with the accent) is now footer, as `Editions` was. Text is matched after
  accents are folded.
- The page-analysis cache is renewed once: the analysis code changed, so old entries are not used.

## 0.7.3 — 2026-11-01

A build or detect starts more page workers on a machine with little memory. No change in output.

- The memory one page analysis needs is now estimated from the size of the largest page and the
  dpi (about 36 bytes per pixel plus 0.1 GB), not set at 1.5 GB. Measured: 0.46 GB for A4 at
  400 dpi, 0.89 GB at twice the pixels. The estimate is 0.6 GB and 1.1 GB. On a machine with
  7 GB, a 60-page analysis now runs with 4 workers, not 1.
- `--jobs` and `PARTITOR_JOBS` still set the count by hand, and `PARTITOR_MEMORY_MAX` still sets
  the cap.

## 0.7.2 — 2026-11-01

The page analysis is much faster on scans with dust or specks. The result is the same, byte for byte.

- The step that gives a small unowned component to the owned component next to it compared each
  one with every owned component in a Python loop. On a page with many specks that was most of
  the time (one scanned page: 43 s, now 3 s; other pages 1.5 to 15 times faster). It now tests all
  owned boxes at once with numpy and keeps the same order of choice, so every owner is the same.
- The first run after this update analyses the pages again: the analysis source changed, so the
  cache key changed once.

## 0.7.1 — 2026-11-01

The page-analysis cache survives releases that do not touch the analysis. No change in output.

- The program version is no longer part of the cache key. The key already holds a hash of the
  analysis source, the cv2, numpy and pymupdf versions and the tesseract version, so a change
  to anything that can alter the result still gives a new analysis. A release that changes
  only other code, or only documents, keeps the entries.
- The first run after this update analyses again (the key text changed once); later releases
  do not.

## 0.7.0 — 2026-11-01

A rebuild no longer analyses the pages again when nothing that affects the result has changed.
The output, the messages (except one new line) and the exit codes are the same as before.

- New: `detect` and `build` keep the result of the page analysis in `cache/` in the item
  folder (one file per page, about 0.6 MB at 400 dpi) and read it back. Measured on a
  70-page score, part-only build of one group (60 pages analysed, one worker): 31 minutes
  without the cache, 31 seconds with it. The parts are pixel-identical and the saved lines
  are equal.
- The entry is keyed by the PDF content, page, dpi, OCR, the page header limit, the program
  version, the source of the analysis code, the cv2, numpy and pymupdf versions and the
  tesseract program and version. A changed input gives a new analysis, never an old result.
  An unreadable or old entry is deleted and the page is analysed again, with one `cache:` note.
  One entry per page stays.
- One new line when entries are found: `analysis cache: N of M page(s) found`.
- `PARTITOR_CACHE=0` keeps no cache and reads none. The wrapper passes it into the sandbox.
  `rm -r cache/` in an item folder is always safe.
- `detect` with one job now analyses each page with system base 0, as the workers do, when the
  cache is on, so that `detect` and `build` share the entries. The result is the same.
- New module `stagecache` (level 2), 35 new tests. Documented in `DESIGN.md` §12.4.

## 0.6.3 — 2026-11-01

- The `logo` line in the settings help of `layout.yaml` and `score.yaml` now says where the
  logo comes from: the file of `PARTITOR_LOGO`, else `logo.png` in the library folder. No
  change in behaviour. Existing files keep the old text until they are written again.

## 0.6.2 — 2026-11-01

Item commands start faster. No change in output, messages or exit codes.

- `list`, `show`, `set`, `expand`, `contract`, `bars`, `parts`, `groups`, `meta`, `rename`,
  `reid`, `proof`, `--version` and `--help` no longer load cv2, numpy or pymupdf. The
  engine imports them in the functions that use them, and `main` loads the build code for
  `pieces`, `detect` and `build` only.
- `PAPER` (paper sizes) moved from `render` to `config`; `step_size` (used by `expand` and
  `contract`) moved from `build` to `library`. Both are unchanged.

## 0.6.1 — 2026-11-01

- `partitor-install` step 6b (package readable by the service user) runs from `/`. It
  gave a false "package not readable" when run from a folder the service user cannot
  enter, such as `/root`, because `runuser` keeps the folder of the caller.

## 0.6.0 — 2026-11-01

The logo for title and back pages can live in the library.

- The engine looks for the file `logo.png` in the library folder (next to `inbox/` and
  `library/`). It is used when `PARTITOR_LOGO` is not set; `PARTITOR_LOGO` wins when both
  exist. No logo file at all: output is unchanged (no logo, no room kept, no warning).
- `logo=off` still removes the logo per piece. There is no per-piece logo file.
- A logo file that is not a readable image (library or `PARTITOR_LOGO`) gives one warning
  and the build goes on without the logo; before, a `PARTITOR_LOGO` file of that kind
  stopped the build.
- `build` and `repage` look up the library file and pass it to the page renderer in the
  option `_logo_file`. It is not stored in `.lines` files.
- `partitor-install` also checks that the service user can read `<library>/logo.png`
  (a warning only; silent when there is no file). `partitor-init` tells whether the
  library has a logo when you answer `none`.
- Docs: `docs/DESIGN.md` §5.5 and §9, `docs/INSTALL.md`.

## 0.5.0 — 2026-10-31

The engine is now the package `lib/partitor/`, in 23 modules with a fixed import order
(plan: `docs/DESIGN.md` §12). `lib/partitor-engine` is a launcher. Same commands, same
options, same output, same sandbox: 50 golden cases checked with `tools/g0_golden.py`.

### Added

- Module `cli_main` (the menu, `main` and the sandbox check; level 9; about 300 definition
  lines): the last module of the split.
- `python -m partitor` (with `PYTHONPATH=lib`) starts the same function as the launcher.
- `docs/HISTORY-ENGINE.md`: the development history of the engine, newest first. It was the
  header comment of `lib/partitor-engine`; the text is unchanged except one reference to a
  note that is not in this repository.
- 6 new tests: 521 are found now (see Removed). They cover the launcher (it defines nothing
  and starts `cli_main.main`), `python -m partitor` and equal `--help` text, the levels and
  the module reads of `cli_main`, and the test view `pt` (a write reaches the owner module,
  a name that no module defines is refused, no name is defined twice).

### Changed

- `lib/partitor-engine` shrank from about 9 800 lines (0.4.2) to 163: the usage text and about
  6 lines of code. The shim imports of the moved names are gone.
- The test view `pt` is now built from the package modules instead of loading the script.
  Tests that read the script as text or loaded it as a module read the package instead.
- Docs: `docs/DESIGN.md` §12, `CONTRIBUTING.md` and the README tag example describe the final
  layout.

### Removed

- `tools/move-symbols.py` and its 25 tests (`tests/test_move_symbols.py`): the tool moved code
  from the script into modules and has no use now. The minimum test count (`MIN_TESTS`) falls
  once, from 540 to 521: the 25 tests of the tool leave and 6 new tests join. It only rises
  from here.

## 0.5.0-dev.8 — 2026-10-31

Seventh move of engine code (plan: `docs/DESIGN.md` §12). Four modules leave the engine
script and go to the package `lib/partitor/`. No behaviour change: the output is the same
(50 golden cases checked with `tools/g0_golden.py`).

### Added

- Modules `cli_common` (the shared CLI helpers and the `set` command; level 6), `cli_bars`
  (the `bars` command) and `cli_parts` (the `parts` and `groups` commands, the ambitus menu;
  both level 7), and `cli_items` (the item commands; level 8) in `lib/partitor/`, about
  1 350 definition lines in all. The six CLI helpers that call each other in a ring
  (`saved`, `_item_or_die`, `_lib_or_die`, `cmd_set`, `_cmd_step`, `bar_summary`) are
  together in `cli_common`. The script imports the names, so commands, options and output
  stay as they were.
- `cmd_rebuild` is patched by tests, so it has no shim in the script: menu `r` and the
  command table of `main` read `cli_items.cmd_rebuild`.
- 5 new tests: 540 are found now (535 before). They cover the levels and the imports of the
  four modules (no `global`, no import between `cli_bars` and `cli_parts`), that
  `cmd_rebuild` has no shim and is not imported by name, that `main` and menu `r` call the
  `cmd_rebuild` of `cli_items` (a fake is called), and that the ring helpers are the
  objects of `cli_common`.

### Changed

- Tests that replaced `cmd_rebuild` on the script now replace it on `cli_items`.
- The test of the `partitor-init` hint reads the package modules too, because the hint
  moved with the CLI. The test that the wrapper lists every library command accepts a
  command table entry of the form `module.cmd_name`.
- `tools/modules.txt` maps the four modules to the test files that use their names.
- Docs: `docs/DESIGN.md` §12 and `CONTRIBUTING.md` list the 22 modules that exist.

## 0.5.0-dev.7 — 2026-10-31

Sixth move of engine code (plan: `docs/DESIGN.md` §12). Two modules leave the engine
script and go to the package `lib/partitor/`. No behaviour change: the output is the same
(50 golden cases checked with `tools/g0_golden.py`).

### Added

- Modules `build` (the `pieces`, `detect` and `build` commands, `run_detect`, `run_build`,
  build reports, size steps; about 840 definition lines) and `proof` (the proof PDF; about
  180 definition lines) in `lib/partitor/`. Both sit on level 5 and import nothing from each
  other. The script imports their names, so commands, options and output stay as they were.
- `run_build` and `cmd_build` are patched by tests, so they have no shim in the script: the
  script reads them as `build.run_build` and `build.cmd_build` (the command table of `main`
  too). `LAST_BUILD` is changed in place only; the script and `build` share one list.
- 6 new tests: 535 are found now (529 before). They cover the level and the imports of
  `build` and `proof`, that `run_build` and `cmd_build` have no shim and are not imported
  by name, that `run_build` and `main` call the `cmd_build` of `build` (a fake is called),
  and that `LAST_BUILD` is one list.

### Changed

- Tests that replaced `run_build` or `cmd_build` on the script now replace them on `build`,
  and assert that the fake was called.
- `tools/modules.txt` maps `build` to the test files that use its names.
- Docs: `docs/DESIGN.md` §12 and `CONTRIBUTING.md` list the 18 modules that exist.

## 0.5.0-dev.6 — 2026-10-31

Fifth move of engine code (plan: `docs/DESIGN.md` §12). One module leaves the engine
script and goes to the package `lib/partitor/`. No behaviour change: the output is the same
(50 golden cases checked with `tools/g0_golden.py`).

### Added

- Module `library` (item folder, ids, load and save, set keys, parts folder swap) in
  `lib/partitor/` (about 500 definition lines). The script imports its names, so commands,
  options and output stay as they were. No test patches a name of `library`, so no name
  needs a read through the module.
- 3 new tests: 529 are found now (526 before). They cover the level and the imports of
  `library` (it has no `global` and imports no patched name by name), and that
  `check_margins` is one object in `config` and `library` and is no longer in `render`.

### Changed

- `check_margins` and `MIN_MARGIN_MM` moved from `render` to `config`: only the build
  command and `library` use them, `render` does not. The code is unchanged.
- `tools/modules.txt` maps `library` to the test files that use its names.
- Docs: `docs/DESIGN.md` §12 and `CONTRIBUTING.md` list the 16 modules that exist.

## 0.5.0-dev.5 — 2026-10-31

Fourth move of engine code (plan: `docs/DESIGN.md` §12). Two modules leave the engine
script and go to the package `lib/partitor/`. No behaviour change: the output is the same
(50 golden cases checked with `tools/g0_golden.py`); saved `.lines` files still load.

### Added

- Modules `lines` (line fitting, labels, multi-bar rests, saved `.lines` files) and
  `render` (paper, packing, page plan, part drawing) in `lib/partitor/` (about 1 000
  definition lines). The script imports their names, so commands, options and output stay
  as they were. The page-turn costs stay in `typography`; `render` imports them.
- 6 new tests: 526 are found now (520 before). They cover that a change of
  `render.SYSTEM_GAP_LAST` reaches the page plan and that a name set on the script does
  not, that `render.LAST_RENDER` is the one dict the script shares and `render_part` fills
  in place, that the `.lines` reader and writer belong to `lines` and accept the new
  class paths, that the turn costs are the objects of `typography`, and the levels and
  imports of the two modules.

### Changed

- Tests patch `render.SYSTEM_GAP_LAST` (the script has no copy of it).

## 0.5.0-dev.4 — 2026-10-31

Third move of engine code (plan: `docs/DESIGN.md` §12). Three modules leave the engine
script and go to the package `lib/partitor/`. No behaviour change: the output is the same
(50 golden cases checked with `tools/g0_golden.py`); saved `.lines` files still load.

### Added

- Modules `reflow` (re-flow of strips), `ownership` (ink ownership, safety gate, barline
  detection) and `analysis` (page loop and preview) in `lib/partitor/` (about 1 560
  definition lines). The script imports their names, so commands, options and output stay
  as they were. `ownership` is the one module above the usual size limit.
- 8 new tests: 520 are found now (512 before). They cover that `analyse_one` is reached
  through the `analysis` module (one job, workers, build), that the script keeps no copy of
  it, the levels and imports of the three modules, that `ownership` reads `config.TUNE`,
  and that `PROOF_H` is data of `analysis` that no other file sets.

### Changed

- The script reads `analysis.analyse_one` (tests patch that name, so it has no copy in the
  script).
- The comment on `PROOF_H` no longer says that `preview_page` sets it: nothing does.
- `tests/test_analysis.py::TestDetectParallel` no longer depends on a terminal: the helper
  that runs `detect` sets `console._TTY` to false, so one job and workers print the same
  text (before, the test failed when run on a terminal). No engine code changed for this.
- Docs: `docs/DESIGN.md` §12 and `CONTRIBUTING.md` list the 13 modules that exist.

## 0.5.0-dev.3 — 2026-10-31

Second move of engine code (plan: `docs/DESIGN.md` §12). Three modules leave the engine
script and go to the package `lib/partitor/`. No behaviour change: the output is the same
(50 golden cases checked with `tools/g0_golden.py`); saved `.lines` files still load.

### Added

- Modules `vision` (page render, staff and system detection, OCR), `clef` (clef
  signature, note steps, ambitus maths) and `strips` (strip build, bar marks, rehearsal
  boxes) in `lib/partitor/` (about 1 410 definition lines). The script imports their
  names, so commands, options and output stay as they were.
- 8 new tests: 512 are found now (504 before). They cover the OCR state in `vision`, the
  clef caches, that `refresh_ambitus` has no menu code, that the three new modules do not
  import each other or a patched name, that they import alone, and the move tool check
  against a script that already holds shims of an earlier step.

### Changed

- The script reads the path of tesseract as `vision._TESS["path"]`. The key `"warned"`
  of that dictionary was never used and is removed.
- `tools/move-symbols.py --check` now counts the modules of earlier steps as existing, so
  it can check a step against the script of the last release. The file has the executable
  mode.
- Docs: `docs/DESIGN.md` §12 and `CONTRIBUTING.md` list the 10 modules that exist.

## 0.5.0-dev.2 — 2026-10-31

First move of engine code (plan: `docs/DESIGN.md` §12). Seven modules leave the engine
script and go to the package `lib/partitor/`. No behaviour change: the output is the same
(50 golden cases checked with `tools/g0_golden.py`); saved `.lines` files of earlier
versions still load.

### Added

- Modules `console`, `config`, `model`, `typography`, `mapping`, `bars` and `parallel` in
  `lib/partitor/` (about 1 120 definition lines). The script imports their names, so
  commands, options and output stay as they were.
- `tools/move-symbols.py`: moves named top-level code from the script to a module, text
  unchanged, with a check that proves it. It is temporary and goes away in the last step.
- `tests/data/lines-0.4.2.lines`: a saved-lines file written before the move; a test loads
  it. `tools/check-repo.sh` skips the licence-line check for binary fixtures in
  `tests/data/`.
- 40 new tests: 504 are found now (464 before). They cover the move tool, the font search
  path, the progress-line switch in a worker, the colour setting of the console module,
  saved-lines compatibility, results that workers return, and that every module imports
  alone.

### Changed

- The reader of saved lines (`.lines`) also accepts class paths below `partitor.`. Files
  written from now on name `partitor.model.Strip`; an older engine that reads one asks for
  a rebuild of the part. `LINES_FORMAT` stays 1.
- Tests that replace `fork_map` or `SIZE_FIRST` now replace the name in its module
  (`parallel`, `config`) and check that the replacement was called. `tests/test_docs.py`
  reads the script and all package files as engine text, closes the files it opens, and
  skips the one line of the NAS guide that names its example vendor instead of naming that
  vendor in the test.
- Docs: `docs/DESIGN.md` §12 and `CONTRIBUTING.md` list the modules that exist, the
  exact rule for shared state, the reader of saved lines and the move tool. The header of
  `lib/partitor-engine` names the right install path and the package.

## 0.5.0-dev.1 — 2026-10-31

Start of the modular split of the engine (plan: `docs/DESIGN.md` §12). This step moves
no engine code. No behaviour change: the output is the same (50 golden cases checked
with `tools/g0_golden.py`).

### Added

- Package `lib/partitor/`. For now it holds only `VERSION`; the engine code follows in
  small steps.
- `tools/check-modules.py` with the list `tools/modules.txt`: checks the module structure
  (import levels, cycles, file headers, `global` use, names that tests patch, module size,
  leftover files). `--import` imports each module alone; `--affected MODULE` lists the
  modules that import it and the tests to run. It runs in `tools/check-repo.sh` and in CI.
- `tests/patchable.txt`: the names that tests replace at run time. No module may import
  one of them with `from ... import NAME`.
- `tests/support.py`: the shared test helpers, with the engine loader. An import error of
  the engine now stops the test run; before, it skipped all engine tests without notice.
- `partitor-install` compiles the bytecode of `lib/partitor` as root, so the read-only
  service user does not compile every module in memory at each start. It also warns when
  the service user cannot read the package.
- `tools/bench-start.sh [N]`: wall time of `partitor-engine --version`, with the median.
- A test fails when fewer tests are found than before (`MIN_TESTS` in `tests/test_ci.py`).
- 62 new tests: 464 are found now (402 before). They cover the module checks, the test
  support, the engine start, the installer steps, `m0_depmap` input handling, the start
  script, and the match of `docs/DESIGN.md` §12 and `CONTRIBUTING.md` with
  `tools/modules.txt`.
- `docs/DESIGN.md` §12 (code map: modules, import levels, where a DESIGN section lives,
  rules); `CONTRIBUTING.md` "Where does my change go".

### Changed

- `VERSION` of the engine now lives in `lib/partitor/__init__.py`; the script imports it.
  The file `VERSION` stays for the wrapper and the installer, and a test checks that both
  agree.
- `tests/test_partitor.py` is split into nine files by area (`test_analysis.py`,
  `test_mapping.py`, `test_bars.py`, `test_parallel.py`, `test_layout.py`,
  `test_render.py`, `test_clef.py`, `test_library.py`, `test_cli.py`). The 292 tests are
  the same.
- `tools/g0_golden.py`: the default of `--tests` is `tests/support.py`.
- `tools/m0_depmap.py` reads a folder or several inputs. A name defined in two files stops
  the run. One file is read as before. `networkx` is imported only when the map is built.
- CI: the best-effort macOS job runs on `macos-15` (GitHub retires the `macos-14` image on
  2026-11-02); the gate job runs `tools/check-modules.py --static`; the Ubuntu job also
  runs `tools/check-modules.py --import`; shellcheck covers `tools/bench-start.sh`.
- Docs: `docs/DESIGN.md` §9 and §10, `docs/INSTALL.md`, `docs/SANDBOX.md` and
  `CONTRIBUTING.md` describe the new files and installer steps.

## 0.4.2 — 2026-10-30

### Added

- `new --jobs N|auto`: workers for the analysis and the build steps of the
  wizard. `PARTITOR_JOBS` still applies when the option is absent.
- `partitor-install` warns when `PARTITOR_LOGO` names a file that is missing,
  that lies where the sandbox cannot see it (`/home`, `/root`, `/run/user`,
  `/tmp`, `/var/tmp`), or that the service user cannot read. It is a warning
  only: without the logo the engine builds as before.

### Changed

- CI uses `actions/checkout@v6` and `actions/setup-python@v6`, which run on
  Node 24 (the Node 20 deprecation notices go away).

### Fixed

- Docs: the README status line and a line in `KNOWN-LIMITS.md` named
  0.4.0 release candidates. `docs/DESIGN.md` now describes the parallel
  analysis (new §4.4), `--jobs` for `new`, `detect` and `rebuild`, and the
  installer's logo check.

## 0.4.1 — 2026-10-30

### Changed

- `detect` (and `new`, which runs it) analyses the pages in parallel worker
  processes, as `build` does. Before, one process analysed the pages one by
  one, so a long score took much longer in `detect` than in `build`. The
  output is the same as with one process: the same `layout.yaml`, preview
  files, system ids, titles, check counts and printed text, in page order.
- With workers, `detect` prints the worker count, the memory of the largest
  worker, and the analysis time.

### Added

- `detect --jobs N|auto`. `PARTITOR_JOBS` applies to `detect` and `new` too.
  `--jobs 1` keeps the single-process loop.

## 0.4.0 — 2026-10-29

First public release. Same code as 0.4.0-rc.2; checked on the production host (50 golden cases, parts identical).

## 0.4.0-rc.2 — 2026-10-29

First public release candidate. The private line was 0.3.0-dev.42. The engine's
processing is unchanged: a golden test of 50 cases gives identical PDF pages
before and after the move.

### Added

- `bin/partitor-install`: installer (local or SMB library), with
  `--check`, `--dry-run` and `--config FILE`.
- `bin/partitor-init`: guided setup. Asks for storage mode, library path, SMB
  host, share, user and password (silent), memory cap and logo; writes the
  settings file and credentials; runs the installer. `--yes` for no questions.
- The installer also links `partitor-init` and `partitor-install` in
  `/usr/local/sbin`.
- Local library mode (default `/var/lib/partitor/library`).
- `PARTITOR_MEMORY_MAX=auto` (70 % of the memory, at least 1G) is the default.
- `PARTITOR_LOGO`: an optional PNG file for title and back pages.
- Documentation: `README.md`, `docs/` (install, storage, operating, sandbox,
  design, library layout, known limits, overlays), `SECURITY.md`,
  `CONTRIBUTING.md`, `NOTICE`.
- `docs/operator-flow.html`: step-by-step guide for an operator.
- CI (`.github/workflows/ci.yml`): repo gate and shellcheck; tests on Ubuntu
  24.04 with Python 3.12 and 3.13; best-effort tests on macOS. Dependabot for
  the actions; issue and pull request templates.
- `tools/check-repo.sh` (repo gate), `tools/g0_golden.py` (golden renders),
  `tools/m0_depmap.py` (function dependency map).
- One version for engine, wrapper and installer: the file `VERSION`. A test
  checks that they agree.

### Fixed

- Made CPU-count and OpenCV thread-restoration tests portable across macOS and
  OpenCV builds.

### Changed — BREAKING (for the private line)

- `PARTITOR_SHARE` is now `PARTITOR_LIBRARY`. Default
  `/var/lib/partitor/library` (was `/mnt/partitor`).
- `PARTITOR_NAS` is now `PARTITOR_SMB_HOST`, with `PARTITOR_SMB_SHARE`
  (default `partitor`). The mount point is `PARTITOR_LIBRARY`.
- `setup` is now `bin/partitor-install`. The repository is the install: the
  venv is `venv/` in the clone, and `/usr/local/sbin/partitor` is a link to
  `bin/partitor`.
- Mount units are written from templates (`share/systemd/*.in`). The old
  drop-in `10-nas.conf` is no longer used.
- `partitor --sandbox-check --share` is now `--sandbox-check --library`.
- The logo is optional. Without `PARTITOR_LOGO` there is no logo, no space kept
  for it and no warning.

### Removed

- Publishing to a web server. It is out of scope (`README.md`, Scope).

### Library layout

No change to the contract in `docs/LIBRARY-LAYOUT.md` (it is first written
down in this release; the layout is that of the private line).

### Known limits

See `docs/KNOWN-LIMITS.md`. Not checked: golden renders on Python 3.12, the
installer on Ubuntu 24.04, macOS.
