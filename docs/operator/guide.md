---
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
page_title: partitor Operator Flow
title: From score to parts
lede: >-
  Turn a score PDF into large-print parts. You work in a terminal. Make every
  change first, review, then build once. Only the build takes long.
stages:
  - {id: drop, num: 1, name: Drop, what: PDF into the inbox, long: false}
  - {id: analyse, num: 2, name: Analyse, what: "proof of who plays what, 1–5 min", long: true}
  - {id: edit, num: 3, name: Edit, what: "names, choices, groups, layout", long: false}
  - {id: review, num: 4, name: Review, what: "one screen, every setting", long: false}
  - {id: build, num: 5, name: Build, what: "the part PDFs, minutes", long: true}
legend: >-
  Dashed: the stages that take time. You can go back from Review to Edit as
  often as you like. Nothing is built until you build.
footer: >-
  partitor {version}. Install: `INSTALL.md`; Windows: `platforms/windows/README.md`. Storage: `STORAGE-LOCAL.md`,
  `STORAGE-SMB.md`. Every command: `COMMANDS.md`. Design: `DESIGN.md`. Less common features: [Advanced](advanced.md).
---

## What you need {#before eyebrow="Before you start"}

- A score PDF: vector (from notation software) or a scan. Scans at 300 dpi greyscale work best.
- A library folder with two folders inside, `inbox` and `library`. You put score PDFs in `inbox`. partitor writes everything else in `library`. See `STORAGE-LOCAL.md` or `STORAGE-SMB.md`.

| System | Status | Start command |
|---|---|---|
| Linux (Ubuntu LTS) | supported | `sudo partitor` (`partitor` as root) |
| Windows (PowerShell) | experimental | `partitor` |
| macOS (Terminal) | best effort | see [Advanced](advanced.md) |

Windows and macOS have no sandbox: open only PDFs you trust. Install once: `INSTALL.md` on Linux, the setup program from the Download page on Windows. Where this guide says “run `partitor`”, use the start command of your system. On Windows, type `\` in paths.

Linux library: `/var/lib/partitor/library`. Windows library: `Documents\partitor`.

<p class="note"><b>One command.</b> Type <code>partitor</code> and press Enter. Everything else is a menu: answer with a number or a letter. <kbd>Enter</kbd> accepts the value in [brackets]. <kbd>q</kbd> stops and keeps what is done.</p>

## Drop the PDF in the inbox {#drop eyebrow="Stage 1"}

1. Copy the score PDF into `inbox`.
2. Run `partitor`. The menu lists the pieces, newest first, and `n  new from inbox (1 waiting)`.
3. Press <kbd>n</kbd>, the number of the PDF, then the pages of the piece. <kbd>Enter</kbd> takes all pages. Type a range such as `8-9` when the PDF holds several pieces.

The PDF moves into a new item folder in the library, named by its id: `2026-10-0001` (year, month, number).

## Analyse and check the proof {#analyse eyebrow="Stage 2 · takes 1–5 minutes"}

partitor reads every page. It makes no parts yet. When it ends, open the proof:

```
library/2026-10-0001-bach-example-piece/2026-10-0001-proof.pdf
```

### The proof

- Each proof page is a score page.
- Each system has a blue name, for example `p8.s2` (page 8, system 2).
- Each staff shows its part. Follow one part down the pages: it must continue without gaps.

<p class="note proof"><b>Red frame.</b> partitor is not sure of a system in a red frame. Its staves show <code>? name</code>, the suggestion. You answer these in stage 3.</p>

To analyse again, press <kbd>y</kbd> in the item menu, or run `partitor analyse ID`.

## Edit: names, choices, layout {#edit eyebrow="Stage 3"}

The wizard asks these in order. Each answer is saved at once. Nothing is built. Press <kbd>q</kbd> to stop and come back later.

### Title and composer

Title, composer (full name, as printed on page 1), then the short form for the page heads (suggested: the surname). Change them later with <kbd>m</kbd>.

### Part names

The names come from the printed staff labels. Type one change at a time. Press <kbd>Enter</kbd> when done.

| Type | Does |
|---|---|
| `7=Organ` | renames part 7 |
| `7=-` | no PDF for part 7 (listed as “not extracted”) |
| `7=+` | makes the PDF for part 7 again |
| `7+8` | joins part 7 into part 8: one part on two staves |
| `7=-; 8=Continuo` | several changes in one line |

### Choices for the red systems

For each uncertain system the wizard shows its position, its clefs and labels, and the suggestion as part numbers. Type one part number per staff, top staff first.

<div class="screen">  [1/9] p8.s2: source page 8, system 2 of 4 from the top (proof page 8)
     3 staves, clefs top to bottom: F4 G2 F4
     suggestion: Bass Trombone, Continuo, Continuo  (= 6 7 7)
  part number for each of the 3 staves, top first (Enter = suggestion;
  0 = leave out; same number twice = one part on two staves; j = join with the system below): <b>6 7 7</b></div>

| Answer | Does |
|---|---|
| <kbd>Enter</kbd> | takes the suggestion |
| `0` | leaves the staff out |
| same number twice | one part on two staves |
| <kbd>j</kbd> | joins this system with the one below |
| <kbd>d</kbd> | drops the whole system |
| <kbd>q</kbd> | stops. Continue with <kbd>r</kbd> in the item menu |

A corrected answer becomes the suggestion for the next systems with the same clefs. The proof is drawn again after each answer. More: [Advanced](advanced.md).

### Bar numbers

The wizard asks only when it needs to. After a short first bar: <kbd>p</kbd> pickup (<kbd>Enter</kbd>), <kbd>i</kbd> incipit, <kbd>n</kbd> neither. When a repeat splits a bar: <kbd>Y</kbd> or <kbd>n</kbd>. Check a few numbers against the proof. Corrections: [Advanced](advanced.md).

### The item menu

Open it at any time: run `partitor`, then type the number of the item. The status line lists what changed since the last build.

| Key | Edit (saved, not built) |
|---|---|
| <kbd>m</kbd> | title, subtitle, composer |
| <kbd>t</kbd> | part names |
| <kbd>g</kbd> | groups |
| <kbd>n</kbd> | bar numbers and rehearsal marks |
| <kbd>e</kbd> / <kbd>c</kbd> | larger / smaller staves |
| <kbd>p</kbd> | number of pages |
| <kbd>a</kbd> | paper: Letter, A4, Ledger |
| <kbd>k</kbd> | ambitus of a part |
| <kbd>h</kbd> | short names of staves in a group score |
| <kbd>u</kbd> | cue lines |
| <kbd>s</kbd> | any setting as `key=value` |

| Key | Other |
|---|---|
| <kbd>v</kbd> | review (stage 4) |
| <kbd>y</kbd> | analyse again. Names, groups and settings stay |
| <kbd>f</kbd> | fit: paper and staff size for the best page turns |
| <kbd>l</kbd> | pages of a built part, with the turn after each |
| <kbd>x</kbd> | repage: new page breaks, no new analysis |
| <kbd>r</kbd> | build (stage 5) |
| <kbd>b</kbd> | back to the list |

Details of these keys: [Advanced](advanced.md).

## Review everything {#review eyebrow="Stage 4"}

Press <kbd>v</kbd> in the item menu, or run `partitor show ID`. The wizard shows this screen before “Build now?”.

### The review screen

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

Check the parts, the groups and the title. If something is wrong, go back to stage 3. Nothing is built yet.

**Ambitus.** The lowest and highest note of each part, printed before the first line. The proof rings them in green, with bar, page and system. Check them. Fix a wrong value with <kbd>k</kbd>.

| Status | Means | Next |
|---|---|---|
| <span class="pill wait">not analysed</span> | the analysis did not finish | <kbd>y</kbd> or <kbd>r</kbd> |
| <span class="pill act">needs choices</span> | red systems still open | <kbd>r</kbd> asks them first |
| <span class="pill go">ready to build</span> | all set, never built | <kbd>r</kbd> |
| <span class="pill act">changes not built</span> | edits since the last build | <kbd>v</kbd>, then <kbd>r</kbd> |
| <span class="pill done">built</span> | the PDFs match the settings | print |

## Build and print {#build eyebrow="Stage 5 · takes minutes"}

Press <kbd>r</kbd>. partitor writes one PDF per part, one per group, and a large-print copy of each. A long score takes several minutes. Other services on the host keep running.

To build only some parts, type `r Trombones` or `r 2 4`. The other files stay.

### The part files

The parts are in the `parts` folder of the item. The name starts with the part:

```
06-bass-trombone-Bach-Example--2026-10-0001.pdf
06-bass-trombone-Bach-Example--2026-10-0001-11x17.pdf
08-trombones-Bach-Example--2026-10-0001.pdf
```

- **Normal copy:** Letter (or A4), double-sided.
- **Large-print copy** (`-11x17`): print on 11×17 in (ledger) paper at 100 %. Cut at the dotted line. A4 scores give an `-A3` copy instead, with no cut.

Other paper and print options: [Advanced](advanced.md).
