---
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
page_title: partitor Advanced
title: Advanced
lede: >-
  Features you may need after the first parts. The first-time flow is in the
  [guide](guide.md).
---

## Find a piece {#find eyebrow="Menu"}

| Type | Does |
|---|---|
| number | opens the piece. The number is the serial of its id: 12 is 2026-10-0012 |
| `/Bach` | shows only matching pieces (composer, title, part) |
| `/` | shows all pieces again |
| <kbd>+</kbd> / <kbd>-</kbd> | next / previous page of the list |
| <kbd>A</kbd>–<kbd>E</kbd> | the five pieces changed last (with many pieces) |

`*` marks a piece with work pending.

## Analysis {#analysis eyebrow="Commands"}

| Need | Command |
|---|---|
| Analyse every item, with no questions | `partitor analyse --all` |
| Two systems are one (for example 4 staves above 13, on a page of 17) | <kbd>j</kbd> in the choices, or `partitor analyse ID --join p5:4` (no system ends after staff 4 of source page 5) |
| Take a join back | `partitor analyse ID --unjoin p5:4` |
| Drop a system (a title, the end of another piece) | <kbd>d</kbd> in the choices, or `partitor analyse ID --drop p1.s1` |
| Take a drop back | `partitor analyse ID --undrop p1.s1` |
| A scan starts with the end of another piece | The choices ask whether to drop the systems above the title (default: no). Check the proof first. `partitor analyse ID --yes` asks nothing and prints the `--drop` command |

A dropped system counts no bars. The proof marks it “dropped”. Every later analysis keeps it. A failed analysis leaves a proof, with the problem in red.

## Bar numbers {#bars eyebrow="Menu key n"}

| Type | Does |
|---|---|
| `p 1` | pickup on or off |
| `i 1` | incipit on or off |
| `s 22 1` | bar 1 of line 22 completes the bar before it (one number for both halves) |
| `f 3=16` | line 3 starts at bar 16 |
| `j 4 1` | join a false barline |
| `b 4` | list the bars of line 4 |
| `m 95` | rehearsal mark at bar 95, on or off |
| `m 95 110 120` | several marks |
| `m 22:1` | mark at bar 1 of line 22. Letters follow in bar order |
| `?` | help, with an example |
| <kbd>v</kbd> | draw the proof with the edits. Open it, then press <kbd>Enter</kbd> to save |

The proof shows barline ticks, bar numbers (magenta) and rehearsal letters (boxed). `partitor proof 12` draws it again from the saved file.

## Groups {#groups eyebrow="Menu key g"}

A group prints several parts together as a small score.

1. At “Build now?” press <kbd>n</kbd>.
2. In the item menu press <kbd>g</kbd>.
3. Type `Trombones=2,4,5,6` (part numbers).

`Trombones=` deletes the group. The group is one more PDF. Staves of other parts leave no gap. Each staff has a label. To fit more systems on a page: `Trombones:group_gap=5` (staff spaces between the staves of a group, also of a part on two staves).

## Cue lines {#cues eyebrow="Menu key u"}

A cue is a small staff of another voice above a rest, or a word. Nothing is added unless you ask.

1. Press <kbd>u</kbd> (`u Trombones` for one part or group).
2. Pick the part that gets the cue. The table shows its long rests.
3. Type a line, for example `3=97-98`.

| Line | Result |
|---|---|
| `3=97-98` | the music of part 3 (number or name), bars 97 to 98, from the same bars of the source. One bar: `3=97` |
| `"Canto"=97` | the word, at bar 97 |
| `x 2` | takes cue 2 away |

Options after the bars:

| Option | Does |
|---|---|
| `noclef` | no clef at the start |
| `nolabel` | no name above |
| `label=Text` | your own label |
| `size=0.5` | size, 0.3 to 1. Default 0.6; 1 when `fit` or `sync` is set |
| `anchor=25` | the bar where the cue barline meets the part barline |
| `fit` | stretches the cue bars after the anchor to the bars of the part |
| `sync=3` | the 3rd stemmed note of the cue bar is put over the first note of the part in that bar. Implies `fit` |

The cue stands above the staff (above the top staff of a group). The bars under it become one multi-bar rest, as wide as the cue.

- A cue may run over a bar where the part plays: `Canto=24-25` when the part enters in bar 25.
- The cue barline meets the part barline where the part starts, or at the `anchor` bar. The last cue barline stands where it falls.
- The bars before the anchor must be rests.
- `fit` draws the cue at full size unless you type `size=`. At 0.6 the stretch is about 1.7 times. `size=0.8` is a compromise. Use `fit` per cue.
- `sync` counts stemmed notes from the left barline of the cue bar. Rests and whole notes are not counted. A chord is one note. The bar is stretched in two pieces, before and after that note. If the note is not found, the build says so and fits the bar without it.
- Build the part (<kbd>r</kbd>) and look at it. partitor warns when it cannot confirm that the part rests in a bar, or when the cue stands above ink.
- For several parts: `partitor cue ID 3=97-98 --parts Tenore,5`. List cues: `partitor cues ID`.

## Ambitus {#ambitus eyebrow="Menu key k"}

Pick a part. Type its range (`F3-A4`), `auto`, `off` or `on`. <kbd>Enter</kbd> keeps the value. Or use <kbd>s</kbd>: `Alto Trombone:ambitus=F3-A4`.

- `auto` reads the range again from the notes. `off` prints none.
- A doubtful value is marked `?` and asked at the end of the analysis, with a suggested range without the doubtful note. <kbd>Enter</kbd> takes it. <kbd>k</kbd> keeps the value as read.
- `show` and <kbd>k</kbd> give the bars of the extreme notes.
- Continuo parts have none unless `=on`.

## Paper and print {#paper eyebrow="Settings"}

| Setting | Does |
|---|---|
| <kbd>a</kbd> | paper: Letter, A4, Ledger |
| `cutline=marks` | short crop marks on the large-print copy (`off`: none) |
| `gap=7` | space between systems |
| `Trombones:group_gap=5` | staff spaces between the staves of a group |
| `reflow=on` | re-flow (see below) |

**Ledger** (`paper=ledger`): 17×11 in, landscape, staff up to 8 mm (Letter: 3.6–3.8 mm on long lines). Systems are 2.2 times as wide, so there are about twice as many pages. There is no large-print copy. Print double-sided, flip on the short edge. Two-page spreads are wide: check your stand.

**Re-flow** (experimental, off by default): when the lines of the score are long, partitor offers to cut them at barlines, with the clef copied, for a staff up to 8 mm on more pages. It shows the size and pages before and after. You keep it or not. A group is cut only at barlines that all its staves have, and stays within 1.5 times its pages unless you set `pages`. The build prints a `re-flow:` line: how many lines can be cut, and why the others stay whole.

## Page turns {#turns eyebrow="Menu keys f, l, x"}

A page turn falls only beside a multi-bar rest. A turn while playing is a warning, with page and bar. Full guide: `PLAN-AND-FOLDOUTS.md`.

| Need | Do |
|---|---|
| Best paper and staff size for a part | <kbd>f</kbd> `Trombones`. Read-only until you pick: `f Trombones 4`, then <kbd>r</kbd> |
| Try a group the piece does not have | `partitor plan ID --group AltTen=Alto,Tenor` |
| Pages of a built part, with the turn after each | <kbd>l</kbd> `Trombones` |
| Move a system to the next page | `partitor pages ID Trombones --move 26=1`. Add `--dry-run` to save nothing |
| Remove the manual breaks and pins of a part | `partitor pages ID Trombones --clear` |
| New page breaks, no new analysis | <kbd>x</kbd> `Trombones` (needs one build with this version or later) |
| Break a page by hand | <kbd>s</kbd>, `Trombones:breaks=45,60`, then <kbd>x</kbd> `Trombones` |

## Build one part {#rebuild eyebrow="Menu key r"}

| Need | Do |
|---|---|
| Build only some parts | <kbd>r</kbd> `Trombones`, or <kbd>r</kbd> `2 4`. Numbers are those in the file names |
| Same, from the command line | `partitor rebuild ID Trombones` |
| Change a setting and build at once | `partitor set ID key=value --build`. Without `--build` the change is saved, not built |

If a name would change (title, composer, part number), partitor builds all parts and says why. Every command: `COMMANDS.md`.

## Menu keys {#keys eyebrow="Command line"}

Some menu keys have a command-line form.

| Key | Command |
|---|---|
| <kbd>m</kbd> | `partitor meta ID`. After a change partitor offers to rename the folder to match: `partitor rename ID` |
| <kbd>y</kbd> | `partitor analyse ID` |
| <kbd>v</kbd> | `partitor show ID` |
| <kbd>f</kbd> | `partitor plan ID Trombones` |
| <kbd>l</kbd> | `partitor pages ID Trombones` |
| <kbd>h</kbd> | short names: pick a part, type its short form or `auto` |
| <kbd>e</kbd> / <kbd>c</kbd> | one step larger or smaller (pages, then space between staves). Asks for a part; <kbd>Enter</kbd> = all |
| <kbd>p</kbd> | pages: `auto` or 1–99 |

## macOS {#macos eyebrow="Best effort"}

No installer, no sandbox. The tests run on macOS in CI as a best-effort job. Nobody supports it. Open only PDFs you trust. With Homebrew and a clone of the repository (`ADDRESS` is the address in step 2 of `INSTALL.md`):

```
brew install python@3.12 tesseract
git clone ADDRESS ~/partitor
cd ~/partitor
python3.12 -m venv venv
venv/bin/pip install --only-binary=:all: -r requirements.txt
mkdir -p ~/partitor-library/inbox ~/partitor-library/library
export PARTITOR_LIBRARY=~/partitor-library
venv/bin/python lib/partitor-engine
```

Run `export PARTITOR_LIBRARY=~/partitor-library` again in a new Terminal window, or put it in `~/.zshrc`. For a fixed version, run `git checkout --detach TAG` first. Copy PDFs into `~/partitor-library/inbox`.
