---
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
page_title: partitor Operator Flow
title: From score to parts
lede: >-
  How to turn a score PDF into large-print parts for your ensemble. You work on
  your phone or PC over SSH; partitor runs on your partitor host and keeps
  everything in the library folder (local, or on a NAS). Only the build takes a
  long time, so you make every change first, review it, and build once.
stages:
  - {id: drop, num: 1, name: Drop, what: PDF into the inbox, long: false}
  - {id: analyse, num: 2, name: Analyse, what: "proof of who plays what, 1–5 min", long: true}
  - {id: edit, num: 3, name: Edit, what: "names, choices, groups, layout", long: false}
  - {id: review, num: 4, name: Review, what: "one screen, every setting", long: false}
  - {id: build, num: 5, name: Build, what: "the part PDFs, minutes", long: true}
legend: >-
  Dashed: the steps that take time. You can go back from Review to Edit as
  often as you like; nothing is printed until you build.
footer: >-
  partitor {version}. Install: `INSTALL.md`. Storage: `STORAGE-LOCAL.md`,
  `STORAGE-SMB.md`. Every command: `COMMANDS.md`. Design: `DESIGN.md`.
---

## What you need {#before eyebrow="Before you start"}

- An SSH app on your phone or PC, logged in to your partitor host as a user that can use `sudo`. Run `partitor` with `sudo` if you are not root.
- Access to the library folder (see `STORAGE-LOCAL.md` or `STORAGE-SMB.md`): a folder you can open with your file manager, SFTP or a NAS app. It has two folders: `inbox` and `library`.
- A score PDF: a vector PDF (from notation software) or a scan. Scans at 300 dpi greyscale work best.

<p class="note"><b>One command.</b> Type <code>partitor</code> and press Enter. Everything else is a menu: you answer with a number or a letter. <kbd>Enter</kbd> accepts the value shown in [brackets]; <kbd>q</kbd> stops and keeps what is done.</p>

## Drop the PDF in the inbox {#drop eyebrow="Stage 1"}

1. Copy the score PDF into the `inbox` folder of the library.
2. On the partitor host, run `partitor`. The menu shows the pieces newest first, each under its own fixed number (the serial of its id: 12 is 2026-10-0012, the same number the commands take) and `n  new from inbox (1 waiting)`. With many pieces, the five changed last come first as <kbd>A</kbd>–<kbd>E</kbd>; `*` marks a piece with work pending. `/Bach` shows only matching pieces (composer, title, part), `/` shows all again, <kbd>+</kbd> and <kbd>-</kbd> turn the page.
3. Press <kbd>n</kbd>, then the number of the PDF, then the pages of the piece (<kbd>Enter</kbd> for all pages, or a range such as `8-9` when the PDF holds several pieces).

The PDF moves out of the inbox into a new folder in the library, named by its id, for example `2026-10-0001` (year, month, number).

## Analyse and check the proof {#analyse eyebrow="Stage 2 · takes 1–5 minutes"}

partitor reads every page: staves, systems, barlines, bar numbers, staff labels. It does not make any parts yet. When it finishes, open the proof in the item folder:

```
library/2026-10-0001-bach-example-piece/2026-10-0001-proof.pdf
```

- Each page of the proof is a page of the score.
- Each system has its name in blue, for example `p8.s2` (page 8, system 2).
- Each staff shows the part it goes to. Follow one part down the pages to check that it continues without jumps.

<p class="note proof"><b>Red frame.</b> A system in a red frame is one partitor is not sure of. Its staves show <code>? name</code>, the suggestion. You answer these in stage 3.</p>

If the analysis itself is wrong (wrong pages, a staff missed), you can run it again later with <kbd>y</kbd> in the item menu, or `partitor analyse ID`. `partitor analyse --all` runs it for every item, and asks nothing (open choices stay for the build). A failed analysis also leaves a proof, with the problem marked in red.

## Edit: names, choices, groups, layout {#edit eyebrow="Stage 3"}

The wizard asks these in order. Every answer is saved at once but nothing is built, so you can stop with <kbd>q</kbd> and come back later.

### Title and composer

Title, then the composer's full name (printed on page 1), then a short form for the head of the inside pages (suggested: the surname). Change them later with <kbd>m</kbd>.

### Part names

The names come from the printed staff labels. Change one at a time, then <kbd>Enter</kbd> when done:

| Type | Does |
|---|---|
| `7=Organ` | renames part 7 |
| `7=-` | no PDF for part 7; it stays in the list, marked “not extracted” |
| `7=+` | makes the PDF for part 7 again |
| `7+8` | joins part 7 into part 8: one part on two staves (a keyboard) |
| `7=-; 8=Continuo` | several in one line: basso continuo only, from a keyboard part |

### Choices for the red systems

For each uncertain system the wizard shows where it is (source page, system from the top, proof page), its clefs and labels, and the suggestion as part numbers. Answer with one part number per staff, top staff first:

<div class="screen">  [1/9] p8.s2: source page 8, system 2 of 4 from the top (proof page 8)
     3 staves, clefs top to bottom: F4 G2 F4
     suggestion: Bass Trombone, Continuo, Continuo  (= 6 7 7)
  part number for each of the 3 staves, top first (Enter = suggestion;
  0 = leave out; same number twice = one part on two staves; j = join with the system below): <b>6 7 7</b></div>

- <kbd>Enter</kbd> takes the suggestion.
- A corrected answer becomes the suggestion for the next systems with the same clefs: press <kbd>Enter</kbd> there.
- `0` leaves a staff out (a staff you left out shows as “(left out)” and 0 in the suggestion); the same number twice puts one part on two staves.
- <kbd>j</kbd> says that this system and the one below it on the page are one system (the analysis took them apart: a system of 4 staves above one of 13 on a page that has 17). The analysis runs again and the questions start over; the join is kept by every later analysis. From the command line: `partitor analyse ID --join p5:4` (no system ends after staff 4 of source page 5; `--unjoin p5:4` takes it back).
- <kbd>d</kbd> (or `0` for every staff) leaves the whole system out: a title, or the end of another piece above the music. A dropped system counts no bars, the proof marks it “dropped”, and every later analysis keeps it. From the command line: `partitor analyse ID --drop p1.s1` (no analysis is run); `--undrop p1.s1` puts it back and the choices ask for its parts.
- A scan that begins with the end of another piece: when a title stands low on the first page, above a system, and systems lie above it, the choices first ask whether those systems are to be dropped (default: no). Look at the proof or at the score before you answer. `partitor analyse ID --yes` asks nothing and prints the `--drop` command instead.
- <kbd>q</kbd> stops the questions; continue later with <kbd>r</kbd> in the item menu.
- The proof is drawn again after each answer.

### Bar numbers

When a piece starts with a short bar, the wizard asks: <kbd>p</kbd> a pickup (<kbd>Enter</kbd>), <kbd>i</kbd> an incipit (the original notation of the opening: it stays in the part, has no number, and the next bar is 1) or <kbd>n</kbd> neither. When a repeat splits a bar, it asks <kbd>Y</kbd>/<kbd>n</kbd>. Check a few numbers against the proof. Correct later with <kbd>n</kbd>: `p 1` pickup on or off, `i 1` incipit on or off, `s 22 1` bar 1 of line 22 completes the bar before it (a half bar over a line break; both halves keep one number), `f 3=16` line 3 starts at bar 16, `j 4 1` join a false barline, `b 4` list the bars of line 4. The proof shows the barline ticks, the bar numbers (magenta) and the rehearsal letters (boxed): press <kbd>v</kbd>, open the proof, and press <kbd>Enter</kbd> to save. `partitor proof 12` draws it again from the saved file.

### Groups (optional)

A group prints several parts together as a small score, for example the four trombones. Press <kbd>n</kbd> at “Build now?”, then <kbd>g</kbd> in the item menu, and type `Trombones=2,4,5,6` (part numbers). `Trombones=` deletes the group. The group becomes one more PDF; staves of other parts leave no gap, and each staff is labelled.

### The item menu

Open it any time: `partitor`, then the item's number. The status line lists what has changed since the last build.

| Key | Edit (saved, not built) |
|---|---|
| <kbd>m</kbd> | title, subtitle, composer (full and short; `partitor meta ID` from the command line); after a change it offers to rename the folder to match (`partitor rename ID` does the same) |
| <kbd>t</kbd> | part names, not extracted, joined |
| <kbd>g</kbd> | groups |
| <kbd>n</kbd> | bar numbers and rehearsal marks (`m 95`: mark at bar 95 on/off; `m 95 110 120`: several; `m 22:1`: bar 1 of line 22; letters follow in bar order). `?` shows the help with an example; `v` draws the proof with the edits |
| <kbd>e</kbd> / <kbd>c</kbd> | expand / contract: one step larger or smaller (pages, then space between staves); asks for a part, Enter = all parts |
| <kbd>p</kbd> | number of pages (`auto` or 1–99) |
| <kbd>a</kbd> | paper: Letter → A4 → Ledger (17×11 landscape) → Letter |
| <kbd>k</kbd> | ambitus: pick a part, type its range (`F3-A4`), `auto`, `off` or `on`; Enter keeps it |
| <kbd>h</kbd> | short names: the short form of each staff label in a group score. Pick a part, type its short form or `auto` (the rule); Enter keeps it |
| <kbd>s</kbd> | any setting as `key=value`, e.g. `gap=11`, `reflow=on`, `large=off` |

| Key | Other |
|---|---|
| <kbd>v</kbd> | review (stage 4) |
| <kbd>y</kbd> | analyse again (new proof; names, groups and settings kept; choices and bar numbers asked again, the previous answers offered) |
| <kbd>f</kbd> | fit: which paper and staff size give the best page turns for a part (`f Trombones`; `f Trombones 4` picks option 4, then <kbd>r</kbd>). Read-only until you pick. `partitor plan ID --group AltTen=Alto,Tenor` tries a group the piece does not have. Guide: `PLAN-AND-FOLDOUTS.md` |
| <kbd>l</kbd> | pages: one line for each page of a built part with the turn after it (`l Trombones`). Move a system to the next page: `partitor pages ID Trombones --move 26=1`; add `--dry-run` to see the pages and save nothing; `partitor pages ID Trombones --clear` drops the manual page breaks and pins of that part. Guide: `PLAN-AND-FOLDOUTS.md` |
| <kbd>x</kbd> | repage: new page breaks from the lines of the last build, no new analysis (`x Trombones`). A page turn falls only beside a multi-bar rest; a turn while playing is a warning with page and bar. Break a page by hand: <kbd>s</kbd>, `Trombones:breaks=45,60`, then <kbd>x Trombones</kbd>. Needs one build with this version or later |
| <kbd>r</kbd> | build (stage 5). `r Trombones` or `r 2-4` builds only those parts or groups (numbers as in the file names); the other part files stay |
| <kbd>b</kbd> | back to the list |

## Review everything {#review eyebrow="Stage 4"}

Press <kbd>v</kbd> in the item menu (or `partitor show ID`). The wizard also shows this screen before it asks “Build now?”.

<div class="screen"><b>2026-10-0001 · Example piece · 7 parts · ready to build</b>
  status:    ready to build
  title:     Example piece
  composer:  J. S. Bach
  short:     Bach  <i>(from the composer)</i>
  parts:
     1  Canto  (G2)  — ambitus E4-G5
     2  Alto Trombone  (C3)  — ambitus F3-A4
     4  Tenor Trombone I  (C4)  — ambitus C3-F4 (by hand)
     7  Continuo  (G2+F4)  — two staves, ambitus none (off)
  group:     Trombones: Alto Trombone, Tenor Trombone I, …
  bars:      line starts 1, 3, 6, 9 …; letters A (p10.s3)
  settings:  paper=letter</div>

Check the parts list, the groups and the title. If something is wrong, go back to stage 3; nothing has been built yet.

**Ambitus.** Each part's lowest and highest note, printed in place of the part name at the start of the first line (in a group score, one per staff), as two stacked black noteheads at 80 % size, as in engravings. Every note counts, so check it: the proof rings each part's lowest and highest note in green, with its bar, page and system; `show` and <kbd>k</kbd> give the bars too, and a doubtful value is marked `?` and asked at the end of the analysis, with a suggested range without the doubtful note (Enter takes it, <kbd>k</kbd> keeps the value as read). A wrong value is fixed with <kbd>k</kbd> (or `s` and `Alto Trombone:ambitus=F3-A4`); `=auto` reads it again from the notes, `=off` prints none. Continuo parts have none unless `=on`.

| Status | Means | Next |
|---|---|---|
| <span class="pill wait">not analysed</span> | the analysis did not finish | <kbd>y</kbd> or <kbd>r</kbd> |
| <span class="pill act">needs choices</span> | red systems still open | <kbd>r</kbd> asks them first |
| <span class="pill go">ready to build</span> | all set, never built | <kbd>r</kbd> |
| <span class="pill act">changes not built</span> | edits since the last build | <kbd>v</kbd>, then <kbd>r</kbd> |
| <span class="pill done">built</span> | the PDFs match the settings | print |

## Build and print {#build eyebrow="Stage 5 · takes minutes"}

Press <kbd>r</kbd>. partitor reads the pages again and writes one PDF per part, one per group, and a large-print copy of each. A long score takes several minutes (the pages are read by several workers at once); other services on the host keep running (the build runs at low priority).

From the command line: `partitor rebuild ID` is the same as <kbd>r</kbd> (`partitor rebuild ID Trombones` builds only that part). `partitor set ID key=value --build` changes a setting and builds at once; without `--build` the change is saved, not built. `partitor plan ID Trombones` is the same as <kbd>f</kbd>. Every command and option is in `COMMANDS.md`.

To change one part (a new gap, a corrected ambitus), edit it, then press <kbd>r</kbd> followed by its name or number, for example <kbd>r Trombones</kbd> or <kbd>r 2 4</kbd>. Only those parts are written again; the other files in `parts` are not touched. If a name in the list would change (title, composer, part number), partitor builds all parts and says why.

The parts are in the item's `parts` folder. The name starts with the part so a player finds it first:

```
06-bass-trombone-Bach-Example--2026-10-0001.pdf
06-bass-trombone-Bach-Example--2026-10-0001-11x17.pdf
08-trombones-Bach-Example--2026-10-0001.pdf
```

- **Normal copy:** Letter (or A4), printed double-sided. Page turns fall at movement starts, new sections or rests; a section that fits on two pages stands on a facing pair.
- **Large-print copy** (`-11x17`): print on 11×17 (ledger) paper at 100 %, then cut at the dotted line (set `cutline=marks` for short crop marks, `off` for none). A4 scores give an `-A3` copy instead, no cutting. Paper `ledger` gives no large copy: the sheet is 11×17 already.
- **Ledger** (`paper=ledger`, menu <kbd>a</kbd>): 17×11 in, landscape, for a larger staff (up to 8 mm; Letter holds 3.6–3.8 mm on long lines). The lines are 2.2 times as wide, so there are about twice as many pages. Print double-sided, flip on the short edge (the 11 in side, like a book). Stands for two pages side by side are wide: check the stand first. The staff is as large as the page allows (up to 8 mm) and the pages follow. To fit more systems on a page, set `Trombones:group_gap=5` (staff spaces between the staves of a group; also a part on two staves) or `gap=7` (space between lines).

<p class="note"><b>Small print.</b> When the score's lines are long, the staff can come out small. partitor then offers re-flow (experimental, off by default; for a larger staff use <code>paper=ledger</code>): lines cut at barlines with the clef copied, for a staff up to 8 mm, on more pages. It shows the size and pages before and after; you keep it or not. A group (for example the trombones) is cut only at barlines that all its staves have, and stays within 1.5 times its pages unless you set <code>pages</code>. The build prints a <code>re-flow:</code> line: how many lines can be cut and why the others stay whole.</p>
