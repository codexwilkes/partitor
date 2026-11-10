<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
<!-- Copyright (C) 2026 Nathan Wilkes and partitor contributors -->
# partitor — design

Status: describes partitor 0.8.10. Section numbers are stable: the code cites
them (`DESIGN.md §5.4`). Do not renumber. Add new text as a new subsection.
Version numbers in this file are not history. The history is in
`CHANGELOG.md`.

partitor makes instrument parts from a score PDF (vector or scanned). Its
first users play in an amateur ensemble with older eyes, so large music and a
calm layout matter more than a low page count, up to the page-turn limit
(§5).

---

## 1. Scope and roles

partitor does one job: a score PDF goes in, part PDFs come out. The PDFs live
in a library folder, local or on an SMB share.

| In scope | Out of scope |
|---|---|
| Analysis, part mapping, layout, build | Publishing, sync, web serving |
| The CLI (menu and commands) | Web UI, accounts, cloud storage |
| Local or SMB library | Notation export (MusicXML, MIDI) |

The library layout and the part file names are a documented contract
(`LIBRARY-LAYOUT.md`). Write your own publishing on top of that contract.

| Role | What it does |
|---|---|
| Host | Runs the CLI and the processing. Keeps code and settings only. |
| Library | Holds all score data (§2): a local folder, or an SMB share mounted on the host. |

Data flow:

```
PDF copied to <library>/inbox/
-> operator runs `sudo partitor` on the host (SSH or console)
-> parts and proof are written to <library>/library/<id>-<slug>/
-> the operator (or a script of the operator) takes the part PDFs from there
```

There is no web application, no upload handler and no network service. The
host is an SMB client (SMB mode) and an SSH server (so the operator can log
in). The engine has no network access at all (§8).

---

## 2. Storage (the library folder)

```
<library>/
  inbox/                                   PDFs waiting for `new`
  library/
    2026-10-0012-composer-title/
      2026-10-0012-source.pdf              moved here from inbox/
      2026-10-0012-score.yaml              written by the CLI only
      2026-10-0012-proof.pdf               analysis preview
      lines/                               saved finished lines and plan data (repage, plan)
      cache/                               page-analysis cache (§12.4); safe to delete
      parts/
        01-canto-Composer-Title--2026-10-0012.pdf
        01-canto-Composer-Title--2026-10-0012-11x17.pdf
        02-alto-Composer-Title--2026-10-0012.pdf
        ...
```

Rules:

- All state is in the library. Rebuild the host and nothing is lost. Back up
  the library folder.
- The PDF moves from `inbox/` into the library item when `new` starts.
  `inbox/` holds only work not started.
- `score.yaml` stays readable for diagnosis. The operator changes it through
  the CLI only (§6). Manual edits are not a supported workflow.
- The folder is set by `PARTITOR_LIBRARY` (default
  `/var/lib/partitor/library`). See `STORAGE-LOCAL.md`, `STORAGE-SMB.md`.

### 2.1 Naming

- ID: `YYYY-MM-NNNN`. Year and month of the extraction, and a serial number
  per year (`2026-10-0012`). A part found out of context tells when it was
  made. Short form on the CLI: `12` means serial 12 of the current year.
  Older items with `YYYY-NNN` ids are still found (`2026-3`); their serials
  count. `partitor reid ID` renames such an item.
- Item files carry the id (`<id>-source.pdf`, `<id>-score.yaml`,
  `<id>-proof.pdf`), so they say what they are outside the folder. Old plain
  names (`score.yaml`) are renamed on first use.
- Slug: `<composer-surname>-<short-title>`. Lowercase ASCII, words joined by
  hyphens, no underscores. German letters become ae, oe, ue, ss; other
  accents are dropped. The slug follows a corrected title or composer only by
  `partitor rename ID`, or by the offer after the `m` edit.
- Part file: `<NN>-<part>-<Composer>-<Title>--<id>.pdf`. Part number in score
  order first, then the part, then the piece (composer surname and first
  title word), then the id. `NN` has two digits so 10 or more parts still
  sort in score order. Groups follow the parts. Large copies add `-11x17` or
  `-A3`.

---

## 3. Settings per item (`score.yaml`)

| Key | Example | Notes |
|---|---|---|
| `id`, `slug` | `2026-10-0012`, `composer-title` | Set by `new`. The id never changes (§2.1). |
| `title`, `subtitle`, `composer`, `composer_short` | | Pre-filled from PDF metadata, the IMSLP file name pattern, the text layer and the staff labels. The operator confirms. `composer_short` defaults to the last word of `composer`. |
| `parts` | `[Canto, Alto, Tenore, Basso]` | Score order. Defines `NN`. |
| `maps` | staff count -> parts | Set by the CLI from choices (§6.2). |
| `paper` | `letter` | `letter` (default), `a4` or `ledger` (17 x 11 in landscape; §5.5). |
| `pages` | `auto` | `auto` or a target page count (§5.2). |
| `range` | `5-8` | Source pages of this piece (multi-work PDFs, §4.3 item 7). |
| `groups` | `{trombones: [Trombone, Basso Trombone I]}` | Named group outputs (§4.3 item 11). |
| `skip` | `[Organ R]` | Parts not extracted (no PDF). They stay in `parts` and in the maps, marked "not extracted". |
| `ink` | `normal` | `normal` or `darker` (§4.3 item 10). |
| `rests` | `compress` | `compress` or `keep`: multi-bar rest lines for left-out staves and for runs of rest-only bars inside a line (§4.2 item 9). |
| `min_staff_mm`, `max_staff_mm` | `5`, `8` | Staff height floor and ceiling in mm (§5.2). |
| `reflow_offer` | `off` | `on`: the CLI offers re-flow after a build when the print is small (§4.2 item 2). `reflow=on` works with either value. |
| `logo` | `on` | `on` or `off`. Draws the logo on title and back pages (§5.5). Needs a logo: `PARTITOR_LOGO` or `logo.png` in the library folder. |
| `scale` | none | Staff size factor against the source. Default: automatic (§5.2). |
| `gap` | `normal` | Staff gap step (§5.3). |
| `group_gap` | `5` | Space between the staves of a group line or of a part on two staves, in staff spaces. Default `source` (§4.3 item 11). |
| `title_page` | `auto` | `auto` or `off`: the title page of layout `2` (§5.4). |
| `turns` | `rest` | `any` (default) or `rest`: page turns only beside a multi-bar rest (§5.4). `repage` sets `rest`. |
| `breaks` | `[45, 60]` | Per part: bar numbers after which a page ends (§5.4). |
| `ambitus` | `{part: {range: C4-F5, from: auto}}` | Lowest and highest note of each part (§4.3 item 13). |
| `page_header_sp` | `6.0` | Analysis tunable. |

`partitor set` rejects unknown keys and changes nothing (§6.2 lists them).
The layout keys are also available per part (`Part:key=value`) where §6.2
says so.

---

## 4. Processing pipeline

### 4.1 Base pipeline

One raster pipeline for vector and scanned pages: render at 400 dpi,
binarize, deskew, find staves (run lengths and line projection), group staves
into systems, remove staff lines and gap connectors (barlines, brackets),
label connected components, give every component one owner (staff, system
header or discard; text lines are decided as a whole), check that no ink is
left without an owner, write strips as 1-bit images.

Rule for every version: **ink is never split** inside a component. A
notehead, slur or word goes whole to one owner.

### 4.2 Layout features

1. **Barline detection.** A vertical item that spans exactly from the top
   line to the bottom line of a staff. Cross-check: the same x on every staff
   of a system. Needed for re-flow and measure numbers.
2. **Re-flow.** Cut a system strip at barlines into shorter lines, so each
   line can be scaled up to the full page width. This is the only way to get
   a staff larger than the source's system width allows. Rules:
   - Cut only at barlines.
   - A continuation line starts with the clef and key signature, copied from
     the start of the source system. The time signature is not repeated.
   - Avoid very short lines (balance the bars over the lines).
   - Experimental. Off by default (`reflow: off`). When the print is small
     (staff below `small_mm`, 6.5 mm, because the page width holds it) and
     `reflow_offer=on`, the CLI offers re-flow after a build. It shows staff
     size, pages and page turns before and after, and asks to keep it. `No`
     restores the build without re-flow. For a larger staff, paper `ledger`
     (§5.5) is the simpler way.
   - Size: with re-flow the staff grows to `max_staff_mm` (8 mm) first; the
     page count follows. `pages=N` sets the page count instead.
   - Prefix (clef + key signature): per movement, lines are compared (staff
     lines removed; a scan's line starts are aligned first). The prefix ends
     at a blank gap that at least half of the movement's lines have at the
     same distance from the clef; a line that lacks the highest such gap
     takes the next lower one it has. A line takes it only when its music
     differs right after the gap, or when a blank of 2.5 sp follows the gap
     (a rest, or a first note far from the key; 0.8.2). A line without the
     gap keeps its own clef in its first bar and borrows the copy from a line
     of the same movement with the same staves, also across a multi-bar rest
     line (0.8.2: a rest line has no staff labels and used to split the
     movement, so a line between two rest lines had no prefix).
   - Lines that cannot be cut safely stay whole: no prefix, not ending at a
     barline, one-line movements, multi-bar rests. A line ends at a barline
     when the last barline found lies within 2.5 sp of the staff end (0.8.2;
     a final or repeat barline is found at its middle, up to 2.2 sp before the
     end, and the old limit of 2.0 sp left every section end whole). A whole line limits the
     size of the part (constant staff size). The build says how many lines
     can be cut, why the others stay whole, and the widest whole line.
   - A movement starts a new line. Bars of two source lines share a line only
     when their prefixes match.
   - A line that starts with a merged multi-bar rest is not a donor of the clef and key (0.8.29):
     its prefix ends after the left bracket of the H-bar, so a copy would bring a stray thick
     barline. The copy comes from the nearest line of the movement, with the same staves and the
     same clef and key, that does not start with a rest.
   - Bar numbers and rehearsal letters move with their bars. Printed mid-line
     source numbers are removed from re-flowed lines. Lines are not
     stretched: ragged right where source bars are wide.
   - Group scores: §4.3 item 11.
3. **Measure numbers** at the start of every line (engraver practice for
   parts). Counted from barlines and checked against the printed bar numbers.
   If the count disagrees with a printed number, the line goes to review. A
   wrong number is worse than no number. Overrides per system for pickup
   bars, repeats and volta endings. The printed source numbers are removed
   from the copied header, so numbers are not duplicated.
4. **Header copy.** Rehearsal letters and movement titles are copied into
   every part. A header that starts left of the staves moves right; the
   staves keep the left margin.
5. **Bar number placement.** Above the staff start, italic, `bar_size` sp
   high (default 2). Baseline at least `bar_raise` sp above the top line
   (default 1) and 0.5 sp above any ink in the number's columns (a C clef
   reaches above the staff). The leading reserves the number's box like
   header ink.
6. **Mensurstriche.** Dotted barlines between the staves count as barlines.
   Their dashes in the gaps are discarded (connectors), so a part keeps only
   what is inside its staff. Not built: drawing a new barline through a staff
   that has no dots inside (it would cross notes that span the bar).
7. **Pickups, repeats and split bars.** partitor cannot count beats, so it
   uses bar widths and repeat signs, and the operator confirms. Full measures
   are counted.
   - Repeat sign: two round dots (staff spaces 2 and 3) beside a repeat
     barline (full-height lines with a thick line), on at least half the
     staves. Dots on a dotted line are a Mensurstrich, not a repeat.
   - Bar widths are compared within a line (justified lines differ in
     spacing). A line with fewer than 3 inner bars uses the geometric mean of
     its own and the movement's median bar.
   - Pickup: the first bar of a movement, less clef and key width, is at
     least 0.4 of a bar short -> bar 0; the next bar is 1.
   - Split bar: the bars before and after a repeat are each at most 0.85 and
     together at most 1.35 of a bar -> one number (the second half keeps the
     number of the first).
   - First and second endings: every printed bar has its own number
     (consecutive).
   - Printed source numbers: when they follow the plain count they are
     converted; when they already follow these rules they are used as they
     are.
   - The CLI asks Y/n for each proposal (`new`). `partitor bars ID` corrects
     by hand: pickup on/off, split on/off, line start fixed (`f 3=16`); the
     lines after it follow.
8. **Rehearsal letters.** A boxed bold letter at the first full bar after
   each repeat (after the completing half of a split bar), A, B, ...
   restarting at A in each movement. Letters printed in the source are copied
   with the header.
9. **Multi-bar rests.** Reduced systems leave out the staves of resting
   parts. Skipping those systems makes a part unplayable and its bar numbers
   jump. Each system without the part's staff is a rest; consecutive ones are
   one line: clef and key signature of the part's nearest line (the next one
   for a rest at the start), an H-bar on the middle line with the bar count
   above it in bold (one bar: a whole rest), a closing barline. Its bar
   number is the first bar of the rest. The count is the difference of the
   line-start numbers when the next system has one (a printed number corrects
   a wrong barline count), else the counted bars. A movement start begins a
   new rest line and keeps the movement title. The H-bar has a bracket at
   each end: full staff height, 0.5 sp thick. "Tacet" is not built.
   Bars of rests inside a line that is printed (0.8.11, `merge_rest_bars` in
   `lines`, before re-flow): a run of 2 or more bars is one measure when every
   staff of the line holds, in that bar, one filled rest block (a whole or half
   rest) and nothing else but staff lines and barlines. The bar becomes an
   H-bar with brackets on each staff and the count above every staff
   (`Strip.rest_labels`); the barlines inside the run go, the merged bar keeps
   the number of its first bar, and the line gets shorter, so re-flow and the
   planner see fewer lines. The test is made for certain: a note, a stem, a
   hollow whole note, a rest of another length, a dot, text, a rehearsal mark
   or a printed number keeps the bar as engraved. A merged rest that starts or ends a line is
   recorded (`Strip.rest_in`, `rest_out`; re-flow gives each piece those of its first and last
   bar) and counts as a rest at a page turn: the planner, `plan` and the turn report take the
   longest of a rest line on either side and these edges, with the same minimum of 2 bars. A single rest-only bar at a line edge, or a line with no
   barline that holds one rest block on every staff, is a one-bar rest there (`rest_in` or `rest_out`
   of 1): the planner calls it a short rest turn, not a bad one. `Strip.rest_counts` keeps the bars of
   rest of each bar so that re-flow can give a cut piece the rest at its edge. Justify gives an H-bar three shares of the
   extra space to a blank gap's one and keeps the count on the middle of its bar; it reads the
   staff-line rows from the staff, since a wide H-bar could be taken for a line. A run whose merge saves
   less than 3 sp is not made. The bar after a clef and key needs the music
   start of its line (re-flow's prefix). `rests: keep` turns it off.
   Re-flow joins two multi-bar rests that meet where two source lines meet (0.8.29): the bars
   of rest of each bar (`rest_counts`) add up, and one H-bar with the sum above it replaces
   both ("2" and "6" give "8"). It joins only rest bars of two or more source lines with at
   least one merged rest among them, and leaves a run that starts at a line with its own clef.

### 4.3 Engine robustness

Ordered by priority. Items 1-3 come before the layout features in §4.2.

1. **No silent loss (safety gate).** "Discard" counts as an owner, so a
   missed staff could be dropped and the run still report ALL OK. Rules:
   - Discard is allowed only for known classes: page title and running header
     zone, footer zone, instrument labels, brackets/braces, gap connectors,
     page-edge artefacts.
   - Discarded ink that holds long horizontal line structure (a missed staff)
     is `_fail`, never discard.
   - Discarded ink outside the header/footer zones above a budget (per page)
     is `_fail`, and `proof.pdf` marks it.
   - Footer: below the last staff of a page, text farther than
     `PAGE_FOOTER_SP` (6 sp) is footer. From `FOOTER_TEXT_SP` (4 sp) on, text
     that reads as copyright, publisher, rights ("droits réservés", "diritti
     riservati", "Rechte vorbehalten"; French, Italian, Spanish, German words,
     matched after accents are folded), footnote ("*) ...") or a page number
     (digits alone, beyond 4.5 sp) is footer too. Staff ink wholly below 6 sp
     (page-edge lines, curl shadows) is footer. A text line 8 sp or wider
     below the last staff, nearer than 4 sp, is read (OCR); one that starts
     with "*" or reads as copyright or publisher is footer.
   - Movement start: a large header text at a system start is not a movement
     when it holds a bracket or is a number alone (a voice cue "35 (Alto I)").
     Such a cue is discarded (label class), not copied into the parts.
   - End barline: a system without a barline at its end (page curl) whose
     last segment is at least 0.75 x the median bar width gets one there.
     A bar number printed next to a cue (the digit touching the bracket) is
     not read; the end barline rule gives the right count there.
2. **Curved and broken staff lines (phone scans).** Detect line pieces in
   vertical bands, link the pieces across bands into one polyline per staff
   line, and fit a smooth curve. Then straighten each staff band (vertical
   shift per column) before ownership. Tolerate broken or faint lines.
   Faint or dotted line starts: the longest solid run of a staff can start
   far right of the real start. `vision.extend_starts` moves the start of a
   staff to the page edge (the first column where the line rows of all staves
   hold ink) when its own 5 line rows hold ink all the way there and the
   spaces between the lines are (nearly) blank. Indents (blank there) and
   labels (text, with ink in the spaces too) keep their start.
3. **Staff plausibility.** Reject false staves: staff space outside a
   plausible range (tables and engravings give absurd sizes), lines without
   noteheads or a clef, table rules. Non-music pages (title, contents,
   introduction, tables) give "no music" and are skipped, not warned about.
4. **Per-system part mapping.** Mapping by staff count is not enough: one
   score can have several different 3-staff systems (voice + continuo, or
   three trombones). Each system gets its own map, suggested from (a) printed
   labels at the staff start read by OCR, (b) the clef and key of each staff,
   matched as an ordered subset of the full system, and (c) continuity with
   the previous system. The CLI asks only about systems whose suggestion is
   uncertain.
   - The reference is the system with the most printed labels (page 1 often
     names every part), not the most staves. Label matching knows continuo
     names as one part (Continuo, Basso continuo, Organo, B.C.) and common
     abbreviations ("Vla I" = Viola I). Labels and part names are compared
     without accents (`mapping.fold_accents`: NFKD, marks dropped, œ æ ß as oe ae
     ss), so "Violoncéllo", "Cör" and "Cœur" equal Violoncello, Cor and Coeur. When the reference's lowest part is a
     continuo, the bottom staff takes it and no other staff does. Bottom
     alignment for an unlabelled staff costs at most 0.9.
   - Systems: a narrow gap without bracket or barline evidence is joined only
     when it has some ink (0.15) at the system start or the page has fewer
     than two bracket-joined gaps; and then it is cut only when no neighbouring
     gap of the same size (within 3%) is joined without ink at the system start
     either; the connector is looked for at the start of the staves as found and
     at the start after `extend_starts` (`Staff.x0_found`, 0.8.23: Biber p17)
     (0.8.22: seven equal gaps on a page without a start connector are one
     system; a neighbour with a bracket makes the blank gap a real break).
     The operator can join two systems the analysis took apart:
     `system_joins` in the layout (`p5:4` = no system ends after staff 4 of
     source page 5; `vision.join_groups`, applied right after `group_systems`).
     Safety gate: a staff track within 1.6 sp of
     an accepted staff counts as that staff.
   - Costs: a part in the previous system -0.4 also when the staff count
     changes; clef of another family +0.8, another line +0.3; two braced
     staves on slots not braced in the reference +1.0, the reverse +0.2. A
     system whose best map is the map of the certain system before it, by a
     margin of 0.3 or more, is taken ("continues previous system"). A voice
     cue in the system header, "(Alto I)", is the top staff's label. A system
     starting 1-4 sp right of the other systems of its page takes their median
     start.
   - Clefs: read as clef and line: G2 (treble), G1, C1 (soprano), C2 (mezzo),
     C3 (alto), C4 (tenor), C5, F3 (baritone), F4 (bass), F5. The clef area
     starts 0.25 sp after the staff start and ends 3.4 sp in. It is compared
     with the Bravura clef glyph at each position, staff lines drawn into
     both, by normalised cross-correlation of slightly blurred images. A G
     clef reaching 1 sp beyond both staff edges is G; two dots one above the
     other at the clef's right end make it F, on the line between them. A
     column with ink through the whole window height is a barline or bracket
     and is removed. The clef is read at start offsets 0, +0.5, +1 sp and the
     best match wins. G8: a G2 clef with a small 8 below (item 13). Rare clefs
     (G1, C2, C5, F3, F5) need a lead of 0.05 over the best common one,
     because scattered misreads break the mapping. A part's clef in the CLI is
     the one read most often over its systems. Without Bravura: shape rules
     (G2, C1-C5, F4).
5. **System grouping without a solid connector.** Mensurstriche (barlines
   only between staves) and dotted lines in scans break the "solid column"
   test. Group by bracket/brace, left barline with holes allowed, and the gap
   pattern of the page.
6. **Text ownership rules.** Lyrics and figured-bass numbers belong to the
   staff above. Applied before the "midpoint" review rule, so a lyric-heavy
   page does not give 30+ review items. An item joins a row when its box
   overlaps the row's band by half its height (descenders, hyphens), not only
   by its centre. A text line (3+ items over a quarter of the staff width)
   belongs to the staff above wherever it sits in the gap. A syllable
   attached earlier to the staff below joins its line when it lies inside the
   line's band and span, is under 2.6 sp high, and does not reach toward the
   lower staff. Preference: the occasional miss on a single word over lines
   of text with missing pieces.
7. **Multi-work PDFs.** A PDF can hold many pieces. `new` lists the pieces
   found (title text above a first system, page ranges), and the operator
   chooses one or more; each becomes its own library item.
8. **Memory.** The engine processes page by page and keeps only compact
   results (strips, or a compressed cache per page, §12.4). `detect` and `build` use
   worker processes (`PARTITOR_JOBS`, `--jobs`; §4.4); the memory cap
   (`PARTITOR_MEMORY_MAX`) covers all workers together.
9. **Page-edge artefacts.** Book-spine shadow, dark scan borders and corner
   marks are found and discarded as a known class.
10. **Scan conditioning (poor scans, light grey print).** The engine tolerates
    poor phone scans (low resolution, uneven light, grey or colour paper,
    light grey print). Steps before staff detection:
    - Flatten the background (remove shading and spine shadow gradient).
    - Local (adaptive) threshold instead of one global threshold.
    - Stroke repair: close small breaks in staff lines and stems; thicken
      strokes thinner than a minimum (a fraction of the staff line
      thickness).
    - Despeckle: remove isolated noise below a size limit relative to the
      staff space, so staccato dots and augmentation dots stay.
    - Output stays pure black on white (1-bit). `ink: darker` makes thin,
      light print bolder.
    The safety gate (item 1) also covers this step: ink removed as noise is
    counted and reported.
11. **Group outputs (for example "Trombones").** Besides one PDF per part, an
    item can define named groups. A group is an ordered list of parts that
    print together as a small score: the selected staves only, joined by a
    bracket, all other staves left out. The layout model (§5) applies to the
    group as a whole.
    - `partitor groups ID` (item menu `g`): `Name=4,5,6` sets a group (part
      numbers; score order kept), `Name=` deletes it. One more PDF per group,
      numbered after the parts. The title band and title page list the
      members.
    - Staff distance: key `group_gap` (staff spaces, bottom line to the next
      top line, 1-40, default `source`) stacks the staves of a group line, and
      of a part on two staves, at that gap. The 0.5 sp ink guard and the
      system gap rule (§5.3) stay. Per group or part:
      `set ID "Trombones:group_gap=5"`.
    - A group line prints only the staves of its parts that the source prints
      there. When the staves change from line to line, each staff is labelled
      with a short name (words of 5+ letters cut to 3 and a full stop) in a
      label column, right-aligned before the bracket, the same width on every
      line. When they never change, the first line has the full names. A
      system without any of the group's staves is one multi-bar rest line.
    - Staves of other parts between the group's staves leave no space: each
      part's staff is cut out alone and stacked at the source's staff
      distance, more only where ink would come closer than 0.5 sp.
    - Re-flow of a group (experimental; `set ID "Trombones:reflow=on"`): cut
      only at barlines that every staff of the group has (the staff's own ink
      through the full staff height at the system barline). A line with no
      common barline at its end stays whole, and the build says why. A
      continuation line copies the clef and key of every staff from a line
      with the same staves at distances within 0.3 sp (0.8.27; scan lines lie
      a few px apart); the copy is moved, staff by staff, to the rows of the
      line it joins. Two lines share an output line only at distances within
      0.07 sp. Lines with other staves, or the same staves at other
      distances, never share a prefix or an output line. A multi-bar rest line is never cut and keeps its
      bracket.
    - Page budget: a group has several staves per line, so pages grow with the
      square of the staff size. With `pages=auto` a re-flowed group may use
      1.5 times the pages it has without re-flow (`GROUP_REFLOW_PAGES`);
      `Name:pages=N` sets the count.
12. **System window.** A staff owns no ink left of its system start - 0.3 sp or
    right of the system's widest staff end + 1.5 sp (one staff's line end can
    be short on a scan, so the widest one counts). Outside: `bracket` (left,
    within 2 sp) or `edge`. A component that reaches from the music into the
    edge is cut at the window; a lone header stroke (narrower than 1 sp)
    outside the window is `edge`. A small speck (under 0.6 sp², under 1 sp)
    wholly right of the widest staff end + 0.25 sp is `edge` too.
13. **Ambitus.** Even one note affects the ambitus, and it decides which
    instrument can play the part. Continuo parts are excluded unless forced.
    Values are stored and correctable.
    - Detection, per staff at analysis: the staff's ink after the clef, staff
      lines removed, gaps up to thick + 2 closed, holes filled (half and whole
      notes), opened with an ellipse 0.8 x 0.7 sp. Blobs 0.9-2.0 sp wide and
      0.7-6 sp high with at least 35 % real ink are noteheads (a taller blob:
      a chord or a head with filled ledger lines; its top and bottom bands of
      real ink 0.45 sp or more high are the heads). A block (fill > 0.88,
      under 0.9 sp) is a rest. Printed bar numbers are blanked.
    - Ring gaps are closed with a 0.4 sp round kernel before the fill; a
      single head is 1.1 times as wide as high or more; 1.2 sp each side of
      every barline and the staff end are blanked; a candidate whose columns
      hold wide ink (0.35 sp) 1.7 sp or more high is a digit; within 7 sp
      after the clef or a barline, a pair at one x or ink filling both staff
      halves in the columns is a time signature. Some whole notes are still
      missed.
    - A head just outside the staff touches the outer line; a head further out
      needs every ledger line between it and the staff, each a thin line
      beside the head on both sides (letters and figures have tall strokes).
    - Each extreme stores its bar index. The proof label, `show` and menu `k`
      give the bar. An extreme seen on one staff only and 3+ steps beyond the
      next, 2+ ledger lines out, or 4+ steps beyond the next, is a doubt,
      asked after an interactive analysis (`confirm_ambitus`; Enter accepts, a
      range or `off` sets it by hand). The question suggests a range without
      the doubtful note.
    - Steps are stored per staff (`systems[].steps`: [lowest, highest] above
      the bottom line). The part's range follows its maps and clefs. Clefs are
      smoothed along the part first: a clef unlike both neighbouring systems,
      which agree, takes theirs; a part with G8 on a quarter or more of its
      staves is G8 where G2 was read. Accidentals are not read: letter names
      only.
    - Clef G8 (treble with an 8 below, vocal tenor): a piece with a hole,
      0.5-1.7 sp high, 1.2-4 sp below the staff, centred under the clef;
      bottom line E3.
    - `score.yaml` `ambitus: {part: {range: C4-F5, from}}`. `from`: `auto`
      (computed, refreshed on every save), `on` (computed for a continuo-like
      part), `operator` (`set ID "Part:ambitus=C4-F5"`, never overwritten),
      `off` (default for names with continuo, b.c., organ, cembalo,
      harpsichord, theorbo, lute, basso generale: figures and realisations
      mislead). `=auto`, `=on`, `=off` change it. `show` lists every part's
      ambitus.
    - Printed in the first-line indent at staff size, in place of the part
      name: a short staff with the clef and the two notes as black noteheads
      without stems, stacked in one column at 80 % size (cue size; a second
      apart: the upper head beside the lower, as in a chord), ledger lines as
      needed. The first line is indented for it when there is room (8 sp + 1.5
      sp), else it stands beside the part name in the heading; on a title page
      under the name. Group scores: the first line shows each staff's ambitus
      in the label column instead of its name; later lines keep the short
      names. When the first line is shorter than the longest line by the width
      of the longest full name (and 4 sp), it is indented and the full names
      stand left of the ambitus; with no such room, only the ambitus shows.
    - Wrong extremes come from clef misreads, lyrics under ledger notes,
      filled ledger lines and staff-line remnants. The operator corrects what
      remains. See `KNOWN-LIMITS.md`.

---

### 4.4 Parallel page analysis

`detect` and `build` analyse the pages in forked worker processes
(`fork_map`; no threads). One worker takes one page. The number of workers is
`--jobs`, else `PARTITOR_JOBS`, else auto (one CPU stays free, at most 6, and
as many as the memory cap holds at about 36 bytes per pixel of the largest page
plus 0.1 GB per worker (A4 at 400 dpi: 0.6 GB; a ledger page: 1.1 GB), plus 2 GB for the
main process). `--jobs 1` runs in one process, page by page.

- **Same output.** Parallel and single-process runs give the same
  `layout.yaml`, preview files, system ids, titles, check counts and printed
  text, in page order. A worker passes system base 0 to the analysis: the
  system index is only a key inside one page (barlines, repeats, system
  window, owner code). Ids and records use the place of the system on its page
  (`p3.s2`), so the parent needs no renumbering.
- **Small results.** A `detect` worker runs the gate line and the preview
  itself and returns only the system records, the preview section, the title
  and the composer. The large owner image never leaves the worker.
- **Progress.** The parent prints one self-overwriting line per page
  ("waiting for its worker"). With workers it ends with the worker count, the
  memory of the largest worker and the analysis time. A single-process run
  prints no such lines.
- **OpenCV.** The parent stops the OpenCV thread pool before the fork and
  starts it again after (a pool copied into a child hangs). `new` analyses and
  builds in one process, so this holds across both steps.
- **Failures.** A worker that raises, calls `_die` or is killed (out of
  memory) ends the run with its message; the other workers are stopped.
- `pieces` still analyses in one process.

---

## 5. Layout model

### 5.1 Page turns decide the page count

| Content pages | Page turns |
|---|---|
| 1-2 | 0 |
| 3-4 | 1 |
| 5-6 | 2 |

Two pages fit on a music stand. A part of 1.3 pages costs the same as a part
of 2 pages, so the space is used for size and clarity. A third page adds a
turn, and paper page turns are hard in performance. Rule: **smaller and 2
pages is better than larger and 3 pages.**

### 5.2 Order of decisions (`pages: auto`)

0. Paper `ledger`: the staff is the largest that the page width and
   `max_staff_mm` allow; steps 1-2 do not apply. Pages and turns follow; the
   gap still tightens toward `gap_min` before a page is added. With `pages=N`
   the size is the largest that fits N pages.
1. Find the smallest number of page turns that can hold the part with staff
   size >= the floor and gap >= the tight floor.
2. Inside that page count, make the staff as large as possible, up to the size
   ceiling.
3. Use the normal gap if it fits. If the last 1-3 lines do not fit, reduce the
   gap step by step toward the tight floor before reducing the size, and
   reduce the size before adding a page turn.
4. A part with an odd page count (for example 3) ends there. There is no blank
   fourth page.
5. The last page holds at least 3 lines: lines move from the pages before it,
   the page count stays. A single line alone on a page looks like an error.

Operator overrides: `pages=N` forces the target, `scale=F` sets the staff size
against the source, `expand` / `contract` move one step (size first, then gap).
Each command reports when the page count changes.

Group re-flow: the largest staff that fits 1.5 times the pages without
re-flow; `pages=N` overrides (§4.3 item 11).

Size ceiling: `max_staff_mm` (default 8 mm). `scale` has no default: the staff
can be larger than in the source, up to the ceiling or the page width,
whichever is smaller.

### 5.3 Staff gap

- A line that starts a movement gets double leading above it, so the eye sees
  where the movement changes.
- One fixed gap for the whole part, on every page, so the eye can predict where
  the next line is. Leftover space goes below the last line.
- The gap has a minimum and a **maximum**: too much space is as bad as too
  little, because the eye loses the next line.
- Skyline nesting is only a fallback, when a part cannot fit its target
  otherwise.
- Defaults: `gap` 10 sp (floor `gap_min` 7 sp; set key `min_gap`). `gap` is the widest leading;
  the layout uses it unless a smaller gap (not below `gap_min`) saves a page
  turn. The values come from test prints. They are estimates, not measured
  preferences.
- Group scores: the gap between systems is at least 1.5 times the space
  between the staves of a system (and at least `gap`), ink at least 3 sp
  apart, so systems stand apart from their staves. On the last page, free
  space goes between the systems, up to 2.0 times the inner space
  (`SYSTEM_GAP_LAST`).

### 5.4 Page-turn layouts (3+ content pages, printed double-sided)

| `turn` | Physical pages | Turn points |
|---|---|---|
| `2` (default) | p1 title page only; p2 + p3 = content 1 + 2 (spread); p4 + p5 = content 3 + 4 | Free turn before the music starts; turn after content 2 |
| `1` | p1 = content 1 with title band; p2 + p3 = content 2 + 3 | Turn after content 1 |

1-2 content pages: single-sided, title band on content page 1, no title page.
Layout `2` is `title_page: auto` (default; `off` keeps the title band). A part
gets the title page when its music fills 3+ pages with the title band and
still 3+ pages without it (content pages then carry only the running head) and
print is double-sided. Title page: title, subtitle, part name, composer, and
the members of a group, centred in the upper third.

Page turns at section boundaries. Page breaks are chosen over the whole part
at once (dynamic programming), not first-fit. A turn follows each recto
(physical page 1, 3, 5; with a title page, page 1 is the title page). A turn
may fall only before a section boundary: a movement start, a line that opens
with a rehearsal letter (a new section after a repeat), or a multi-bar rest on
either side (the player turns while resting). Costs: 100 per turn elsewhere,
30 per page, 50 for a last page under 3 lines, a small cost for unfilled
pages. Both layouts are planned, `2` (title page) and `1` (title band on page
1); fewer bad turns, then fewer pages win, a tie keeps the title page. So a
section that fits on two pages starts on a verso and needs no turn. The layout
is chosen automatically; there is no `turn` key.

Repage and turns while resting. A build saves the finished lines of each part
(`lines/<part>.lines`). `partitor repage ID [part ...]` loads them and runs
`plan_pages` and `render_part` only; nothing is analysed again. It sets
`turns=rest` for the parts. With `turns=rest` a turn (after each recto) is
allowed only where a multi-bar rest line of 2+ bars is the last line of the
page or the first of the next (`rest_turn`). Order of choice: a rest (cost 0),
a movement start with no rest (150, listed as "check attacca"), anything else
(1000, a rehearsal letter too). A turn of the last kind happens only when the
part has no better place; the build and `repage` then warn `turn-while-playing`
with the PDF page and the last bar. The weight against under-filled pages is
40 (squared unfilled share). A manual break (`Part:breaks=45,60`, "break
after bar N") ends a page at that bar; the line must end at the bar. The
planner shifts the earlier pages so that the break falls on a verso when it
can. The report lists each turn: PDF page, last bar, rest length. Only keys
that do not change the lines apply (`turns`, `breaks`, `duplex`, `title_page`);
`group_gap`, `reflow`, `gap`, `pages`, `paper` and margins need `rebuild`,
which also removes the saved lines of the parts it builds and writes new ones.
`rebuild` keeps `turns` and `breaks`. Open: the rest of one bar does not count
as a rest to turn in; a group line counts as rest only when every staff rests.

### 5.5 Page and typography

- Paper: Letter (default), A4, ledger (17 x 11 in, landscape, 1224 x 792 pt)
  for a larger staff. Ledger has the height of Letter and 2.16 x its line
  width (usable 401.8 mm against 185.9 mm at 15 mm margins), so a part held
  small by its source line width can reach `max_staff_mm` (8 mm). Cost: lines
  per page fall by the same ratio, so about twice the pages and more page
  turns. Geometry reads width and height from the paper table; no code assumes
  portrait. Duplex: the spine stays at the left edge of a recto (the 11 in
  short edge) and `gutter` is added there as on Letter; print double-sided,
  flip on the short edge (a printer driver may name the edge by the sheet:
  check the preview). `Name:paper=` sets the paper of one part (0.8.4; the item
  paper is the default). Open: the source
  strips are 1-bit images enlarged about 2.2 x; not measured on a print.
- Small left and right margins, to give the width to the staff. Top and
  bottom margins large enough for the title band and folio. Keys
  `margin_top`, `margin_bottom`, `margin_side` (mm, default 15), floor 5 mm.
  Margins stay inside the printable area of a home printer (about 5 mm); check
  on your printer.
- Double-sided print (`duplex`: `auto` = over 2 pages, `on`, `off`): the spine
  margin is `gutter` mm (default 5) wider than the outer margin (half added at
  the spine, half taken from the outer side), so the text width and the staff
  size are the same on recto and verso. Page 1 is a recto (spine at the left).
  Running head at the outer side.
- Binding allowance (`binding`, mm, default 0 = off; 0.8.4): for a punch or a
  comb binding. The outer margin stays `margin_side` and the spine margin is
  `binding` wider (`gutter` is not used then): `margin_side` 8 and `binding`
  12.7 give 8 mm outside and 20.7 mm at the spine, a text width of 187.2 mm on
  Letter (15 mm and `gutter` 5: 185.9 mm). A part of 3 pages or more is bound
  (`duplex: auto`); a part of 1 or 2 pages prints single-sided, with no
  allowance. The staff is sized as for a bound part unless `duplex` is off, so
  a short part keeps its staff size. Per part: `Name:binding=12.7`,
  `Name:margin_side=8`. The default stays 0, so old items print as before.
  A punch of three holes has its outer holes 4.25 in apart, centred on the 11
  in edge; a hole centred 12 mm from the edge and 8 mm wide ends at 16 mm.
- Size targets: large noteheads. Floor `min_staff_mm` (5 mm), ceiling
  `max_staff_mm` (8 mm), staff height from top line to bottom line. The re-flow
  offer uses `small_mm` (6.5 mm). Estimates, not measured preferences.
- Font: EB Garamond (OFL), embedded. Title page / title band: title centred,
  subtitle below, composer right, part name in SemiBold. Running head on later
  pages: composer (short) — title — part. Folio: n/N. Files: EB Garamond
  Regular, Italic and SemiBold with `OFL.txt`, in `share/fonts/`. Lookup:
  `PARTITOR_FONTS`, then `share/fonts` next to the engine. Missing files:
  Times (built-in PDF font), no failure.
- Look and feel target: modern Bärenreiter / Breitkopf parts.
- Line width: the longest staff of a part sets the width. Shorter lines are
  justified: space is added only in blank gaps between glyphs (columns with
  staff lines only, 0.25 sp or wider; gaps inside text outside the staff band
  do not count, so lyrics and titles stay whole), the same amount in each gap,
  not before the clef end (4.5 sp). Engraved glyphs are never stretched. A
  movement's last line under 60 % of the width stays short. Multi-bar rest
  lines are drawn at the width; the H-bar spans the measure, with a bracket at
  each end (full staff height, 0.5 sp thick). In a group score the rest line
  keeps the system bracket.
- First line: when it is 4 sp or more shorter (the source indents it), it is
  indented by room for the part name (at least the source indent, at most 15 %
  of the width) and justified; the full part name (score.yaml) stands in the
  indent in small caps, centred on the staff. The ambitus replaces the name
  there (§4.3 item 13).
- Multi-bar rest count: Bravura time-signature digits (SMuFL U+E080-E089, 2 sp
  tall, 0.5 sp above the staff), as engravers set it. Bravura is SIL OFL,
  shipped unmodified (Reserved Font Name "Bravura"; a PDF embeds a subset,
  which the OFL allows).
- Composer: read from the first page (right-aligned line below the title); the
  wizard suggests it, else PDF metadata. Printed at the right of the part name
  on page 1.
- Logo (optional): a PNG file (black on alpha works best). Source, in this
  order: `PARTITOR_LOGO` (a file named in the settings); else the file
  `logo.png` in the library folder, next to `inbox/` and `library/` (it travels
  with the library). Neither: no logo, no room kept, no warning. `PARTITOR_LOGO`
  set but the file missing, or a file that is not a readable image: no logo, one
  warning, no failure (when `PARTITOR_LOGO` is set it wins, with no fallback to
  the library file). `logo=off` removes it per piece; it is not a per-part key,
  and there is no per-piece logo file. `partitor-install` warns in advance when
  the file cannot be used (§9).
  - Channel: `render` (level 3) cannot import `library` (level 4). `build` and
    `repage` look up `library_logo(library_root())` and pass the file to `render`
    in the option `_logo_file`. Options that start with `_` are not stored in
    `.lines` files, so a later `repage` looks the library up again. The code never
    sets `PARTITOR_LOGO`.
  - Title page (constructed, 3+ pages, mostly blank): centred on the text
    block, logo centre at 76 % of the page height, 64 pt high.
  - Back page (last page of every part, one page included): centred on the text
    block 10 pt above the folio (4 pt below the last line), up to 44 pt high. It
    needs 28 pt; `plan_pages` charges `LOGO_COST` (20) for a last page without
    that room, so lines move forward before a page is added. If no room is
    left the logo is left out with a warning.
  - Not in the title band of page 1 (the band is crowded).
  - Large copies (§5.6) scale the page, so the logo scales with it.
  - The legibility of a fine wordmark at 44 pt is not checked on paper.

### 5.6 Large-print copy

Some players print on a larger sheet for larger music. For every part a second
PDF (`large: on`, default):

- Letter -> 11x17 (ledger): the Letter page as is, scaled to the 11 in width
  (x1.294), at the top of the sheet; the content is 11 x 14.24 in and about
  2.76 in stays blank at the bottom. The cut line is at 14.24 in from the
  top. Layout key `cutline` (`set ID cutline=...`): `dotted` (default) = one
  dotted grey line across the sheet, for scissors or a knife; `marks` = two
  short crop marks at the side edges, for a paper cutter; `off` = no line.
- A4 -> A3: exact (x1.414), the whole sheet, no cut line.
- File names: `<part>-11x17.pdf`, `<part>-A3.pdf`, next to the part.
- Paper `ledger` has no large-print copy (the sheet is 11x17 already); the build
  says so once: `large copy: skipped (paper ledger is already 11x17)`.

---

### 5.7 Page-turn planner and fold-outs for bound parts (`turnplan`)

`foldouts: on` (layout key, per part too; `set ID "Trombones:foldouts=on"`; default `off`, which keeps
the page plan of §5.4) lets `turnplan` choose the page breaks, the spreads and the fold-outs of a
bound part. It applies to double-sided print only (`duplex` not `off`). `plan_turns` takes the height
of a run of lines, the page height and, for each page break, a `Boundary` (bars of rest next to it, a
movement start, bars one staff rests), and returns a `Plan`: groups of pages, the class of every turn,
the cost. The pure planner is in `turnplan`; `render` feeds it (`plan_faces`, `layout_plan`).

- A bound part (3 or more pages, printed double-sided) is read as spreads: a verso and a recto, a
  turn after each recto. A part without a title page starts with a recto on its own. With
  `title_page: auto` the plan is made with and without a title page; the cheaper one wins.
- Turn classes, cheapest that applies: `rest` (2 bars or more of rest, all staves; 0), `rest1` (one
  bar; 100), `attacca` (a movement starts, no rest; 150), `bridge` (the player is playing, but one
  staff rests next to the turn: tape a few notes over it; 800), `bad` (5000). A turn while playing
  is high but finite: a rehearsal part with a bad turn beats no part. The costs are constants in
  `typography` (`PLAN_*`, `TURN_MOVE`) and a `Costs` value. Today the build gives `rest`, `attacca`
  and `bad` only: `rest1` and `bridge` need rest data the analysis does not keep per staff or per bar.
- A fold-out group has three faces with no turn between them: verso, recto and a flap that folds
  out to the right of the recto (a right fold-out), or flap, verso, recto with the flap to the left
  of the verso (a left fold-out). The stand holds three faces at most. The flap is unfolded at the
  start of the spread and folded in over its page before the turn (an open flap is never turned: it
  would hang off the stand and dip). So the turn before a fold-out group and the turn after it must
  both be rest turns (`rest` or `rest1`); the group costs 300 more (`PLAN_FOLD`). A fold-out is
  chosen only when it lowers the total cost.
- The side is the key `foldside` (`right` default, `left`, `auto`; per part too). `auto` lets the planner
  take either side; the cost is the same, so it takes the right one unless the rules below rule it out.
  A sheet is one leaf, so which faces share it fixes which groups may follow each other: a right
  fold-out cannot be followed by a left one (one leaf would need a flap on each edge), and a left
  fold-out cannot be the first group after a title page (the title page would be on its back).
- Pages and fold-outs are chosen for the whole part at once (dynamic programming), with the page
  costs of §5.4 (`PAGE_COST`, `REPAGE_FILL`, `SHORT_LAST`). Manual breaks (`breaks`) end a page.

Print of a part with fold-outs (`render_plan`). Four files per part (0.8.12). A fold-out is made in
one of two ways, by the printer the person has; both give the same pages:

- `NN-part.pdf`: every leaf on the part's paper (Letter), except the flaps. It is complete: print
  it all for the tape route. A blank page is added when the count would be odd, so the leaves
  print in pairs. Print double-sided and bind.
- `NN-part-foldout-sheets.pdf` (ledger route): one ledger sheet (17 x 11 in) per fold-out, two PDF
  pages: print double-sided (flip on the short edge), cut, fold, and bind it in place of the leaf it
  replaces. The leaf is two consecutive pages of the part file; the assemble text lists the pages
  to print (`Print only these pages: 1-2, 5-32`). The front of each sheet has a line for the
  printer: sheet number, flip edge and the place in the part file.
- `NN-part-foldout-flaps.pdf` (tape route, Letter only): one Letter page per flap, printed on one
  side. The flap sits at the page edge that is its fold edge (left for a right fold-out, right for a
  left one); the cut line (key `cutline`, below) marks the cut, 1/2 in off the free edge, and `tape edge` marks the edge to
  tape to the outer edge of its page in the part file. The same text width and margins as on the sheet.
- `NN-part-assemble.txt`: both ways, step by step, and for each fold-out the part file pages a sheet
  replaces and the page and edge a flap is taped to. Written only when a part has fold-outs, with
  the PDF files; the build and `plan N` name them.
  - The lines are on the front only: a second set on the back would not meet the first on paper.
  - Cut line (layout key `cutline`, as for the large-print copy): `dotted` (default) = a dotted line
    over the full height; `marks` = a short crop mark (0.5 in) at the top and one at the foot;
    `off` = no line, and the printed notes say to trim 1/2 in off the free edge. The fold line is
    always dotted. The notes and `-assemble.txt` name the form chosen.
  - Right fold-out. Front: the bound face (the recto, spine at the left) and the flap. A dotted line
    marks the fold (the middle) and the cut line the cut: 1/2 in off the flap's free edge, so the
    folded flap does not stand out. The staves stop inside the margins, so no line crosses ink.
    Back: the outside of the flap is blank; behind the bound face is the verso that follows (spine at
    the right edge), the first face of the next group. The flap folds forward over the bound face.
  - Left fold-out. Front: the flap (free edge at the left, cut line 1/2 in from it) and the verso
    (spine at the right edge). Back: the last recto of the previous group (spine at the left edge)
    on the left half and the outside of the flap, blank, on the right half. The flap folds forward
    over the verso. Before it is turned the flap is folded in, and the previous recto is read on the
    back of the sheet, before the turn that opens the fold-out.
  - Text width: the flap holds the same text width as every other face. The trimmed panel is 8 in
    wide, so `binding` of about 12.7 mm (the trim) leaves the margin `margin_side` on both sides of the
    flap; a smaller binding leaves less, a larger one more. The build warns when the text is too wide
    for the trimmed flap (lower `binding` or `margin_side`).
  - Page numbers count leaves, not faces: right fold-out, the recto is `7a` and the flap `7b` (`7a/18`,
    `7b/18`), and the next verso is 8; left fold-out, the flap is `6a` and the verso `6b`, and the previous
    recto is 5. Each sheet is one leaf: it replaces two consecutive pages of the part file.
- The record of the part in `score.yaml` (`built`) has `foldout` (the sheet file), `foldouts` (the count),
  `flaps` (the flap file) and `assemble` (the text file).
  `repage` applies `foldouts` without a rebuild.
- Fold-outs need a sheet of two pages side by side: Letter (ledger sheet) and A4 (A3 sheet). On
  ledger paper `foldouts: on` plans the turns with `turnplan` but makes no fold-out.
- Not done yet: the one-bar and per-staff rest data (`bridge_bars`) from the analysis, and the
  3-hole marks on the sheet.

### 5.8 Part planning (`partitor plan`, `partplan`)

`partitor plan ID [PART ...]` shows the options of a part, a group score above all: a table with one
row per paper (Letter, ledger) and staff height (8 to 5 mm, down to `min_staff_mm`), with the pages
of music, the turns by class (§5.7) and the fold-outs. It is read-only and takes a fraction of a
second: nothing is analysed or drawn. Without a part it lists the groups and the parts with a bad turn.
The table is short by default: the row as built (`*`) and the best row of each paper (`best`: the fewest
turns while playing, then the largest staff, then the fewest fold-outs, then the fewest pages);
`--all` shows every row. The row numbers are the same in both views. Columns: `rest` (a rest of two bars
or more at the turn), `short` (a rest of one bar), `attacca`, `fold-out` (the number of sheets), `bad`.

- Source: the build saves the lines of each part before re-flow in its `lines/<part>.lines` file (key
  `plan`; per line: the staff pitch, height, rest bars, movement start and, where the line can be cut, the width
  of each bar and of the clef and key copy a continuation line carries). These are the real widths,
  not estimated from justified lines. A part built before 0.8.6 has none: `plan` then reads its saved
  `.lines` (bars taken as 93 % of their width) when they still hold barlines, else it asks for a
  rebuild of the part.
- Each row cuts the lines at barlines as re-flow does (`reflow._break_lines`) for the text width of
  the paper (margins, `binding` and `gutter` as set for the part: set them first), at the staff
  height of the row, and hands the lines to `turnplan` with and without a title page. A line that
  cannot be cut narrow enough makes the row unavailable and the note says which line and how wide.
  Fold-outs are planned for Letter and A4 only (§5.7).
- A group has a label column (staff names, the ambitus on the first line) that `finish_lines` adds
  after the lines are cut; the staff then shrinks to fit. The row staff is the size that is printed.
  The lines are cut for a staff a little larger (`cap_mm`, what `plan N` sets as `max_staff_mm`) and
  the page budget (`pages`) is the page count at that size, plus 2. The build saves the width of the
  column (`label_px`) with the plan data.
- The estimate of the built layout is printed above the table (`built: ... the estimate for it: N
  pages`): the difference shows how far to trust the rows. Not counted: bridgeable turns (they need
  per-staff rests, §5.7) and one-bar rests; both are 0 in the table.
- `partitor plan ID PART N` sets option N for that part (saved, not built): `paper`,
  `max_staff_mm`, `reflow` (on when the lines are cut), `foldouts=on` and `pages` (the planned
  pages plus 2, at most 99). It also says how many fold-out sheets the option needs. Then `partitor rebuild ID PART` makes it; the build reports the real pages and turns, and
  a row can be chosen again. The numbers of the rows do not change when a choice is made.
- Trial groups: `partitor plan ID --group AltTen=Alto,Tenor [--group TenBas=Tenor,Bass ...]` shows the
  table of groups of parts that the item does not have, to compare the page turns of joining parts. The
  item is copied to a temporary folder, only the trial groups are built there (every part is skipped; the
  page cache is used: a few seconds to a minute), the tables are printed, and the folder is removed.
  The item is not changed. Part names or numbers, top staff first (the score order is kept). The trial
  groups take the layout of the item's first group (`group_gap`, margins, `binding`, ...), so their lines
  are made as that group's are; the table header says `trial build`. To keep a group: `partitor groups`,
  then `rebuild` it. The joint lines count as rest only where every staff rests, so joining parts removes
  turn points: compare the tables with those of the single parts.
- Not done yet: `plan` in the main `--help` (that text is part of the G0 golden: it needs a re-record
  with the operator's word).

### 5.9 The pages table (`partitor pages`, `page_report`)
`page_report` lays a part out as `repage` would (no drawing) and returns one row per face: printed label,
lines `i..j-1`, first and last bar (`line_spans`: a line cut by re-flow has no bar list, so its last bar is
the one before the next line's first, except across a movement), systems, the room at the foot in systems
of that page (its tallest line pitch), the turn after it (`turn_list` or `plan_turn_list`) and whether a
manual break ends it. `partitor pages ID PART` prints it; `--move PAGE=N` turns the move into a
`breaks=+BAR` (and drops the manual break it replaces), calls `repage` for the part and prints the table
again; `--clear` is `breaks=none`. A manual break is only a limit in the planner (no page runs past it), and
the planner optimises the whole part, so one break can change the pages before it. `--move` therefore pins
the ends of the earlier pages that a trial paging would change (extra `breaks=+BAR`). One `--move` for each
call (each move changes the rows after it). `--dry-run` shows the result and saves nothing. If the repage
fails, the settings are put back. A move whose page would not start where it did and end at the new break
(a move up to a full page: the planner would cut the page short) is refused. `plan` keeps the manual
breaks: `read_source` saves the bar span of each line (`span`); `_pieces` gives each cut piece the number of
its last bar (a merged rest holds several; numbers that are not a plain run are unknown); `estimate` forces
a page end after a piece whose last bar has a break, and `Option.lost` lists the breaks that end no piece.
Sections 5.1 to 5.8 keep their numbers.

## 6. CLI

### 6.1 Principles

- Works from a phone over SSH: short prompts, Enter accepts the default, choose
  by number or one letter, **never type a file name**.
- Every change is a CLI action that writes `score.yaml`, and reports the result
  (pages, staff size, review items). Edits are saved; only a build makes PDFs
  (§6.2 stages).
- Output uses a fixed set of glyphs, counters and a summary block.

### 6.2 Commands

```
partitor                       menu: recent items + "new from inbox (N waiting)"
partitor new [n] [--jobs N|auto]   wizard for an inbox PDF
partitor list [words] | show <id>
partitor expand <id> [part] | contract <id> [part]
partitor set <id> pages=2 scale=1.2 gap=11 paper=a4 title="..."
partitor set <id> "Continuo:pages=2"      (one part)
partitor rename <id>           folder name follows title and composer
partitor reid <id>             old YYYY-NNN item -> YYYY-MM-NNNN
partitor rebuild <id> [part ...] [--jobs N|auto]
partitor repage <id> [part ...]           page breaks again from the saved lines
partitor plan <id> [part] [N]             options of a part; with N: set option N
partitor plan <id> --group Name=A,B       try a group of parts in a temporary copy (read-only)
partitor analyse <id> [--yes] [--join pP:N] [--unjoin pP:N] | analyse --all
partitor bars | parts | groups | meta | proof <id>
```

Engine commands that work on a single PDF in the work folder (no library):
`pieces`, `detect`, `build` (`detect` and `build` take `--jobs`, §4.4).

Menu: items are listed newest first under their stable serial (`12` =
`2026-10-0012`; another year: `2025-14`), `PARTITOR_LIST_PAGE` items per page
(default 20), `+` / `-` to page, `/words` filters by id, composer, title or
part, `/` clears. From 9 items on, the five changed last come first as A-E. A
`*` marks work pending.

Details:

- `new`: `--jobs` sets the workers of its detect and build steps (default
  `PARTITOR_JOBS`, else auto). The PDF moves into `library/<id>-<slug>/<id>-source.pdf` once title
  and composer are confirmed (q before that leaves it in the inbox). Part
  names: Enter keeps the suggested names; the same number of names renames; a
  different number runs detect again with `--parts`. Uncertain systems: "parts,
  top first": Enter = suggestion, or part numbers per staff (`2 3 4`; `0` drops
  a staff; `q` stops). An answer that differs from the suggestion becomes the
  suggestion of the systems still to come with the same staff count and clefs.
- `set` and `show`: `set` prints each change as `key: old -> new`. `show`
  lists `settings:` always, then the keys set, then one line per part with its
  own layout.
- Choices need context: each question says where the system is (source page,
  system n of m from the top, proof page), its clefs and printed labels, and the
  suggestion with part numbers. `proof.pdf` names every system (blue), labels
  every staff with its part, frames systems that need a choice in red with
  `? suggestion`, and is redrawn after each answer or rename.
- Part names one at a time: `N=name` (several with `;`), Enter ends; a comma
  list still replaces all. `parts ID` renames later.
- Couple or leave out: `N=-` leaves part N out everywhere (it stays in the
  list, shown as "not extracted"; `N=+` extracts it again). `N+M` joins part N
  into part M as one part on two staves. Example, continuo only from a keyboard
  part: `7=-; 8=Continuo`. In choices, the same number twice = one part on two
  staves. Staff size rules use one staff (4 sp) for such parts.
- `expand` / `contract`: one step. Expand: one more page while a part's staff is
  below its full-width size; then, when the page width holds the staff below
  `max_staff_mm` and re-flow is off, `reflow=on` (§4.2 item 2); else gap +1 sp
  (max 14). Contract: one page less while more than one page, else gap -1 sp
  (not below `min_gap`).
- `set` keys: title, subtitle, composer, composer_short, pages (auto or N), paper (letter, a4 or
  ledger), gap, min_gap, ink, scale, min_staff_mm, margin_top, margin_bottom,
  margin_side, gutter, binding, duplex, bar_numbers, bar_raise, bar_size, large, cutline (dotted, marks or off), logo,
  reflow, reflow_offer, max_staff_mm, title_page, group_gap, rests, turns, foldouts, foldside, and per part
  breaks
  (per part, as `Name:key=value`: pages, gap, min_gap, scale, min_staff_mm, max_staff_mm,
  group_gap, reflow, title_page, bar_raise, bar_size, ink, turns, breaks, and since 0.8.4
  paper, margin_top, margin_bottom, margin_side, gutter, binding, duplex, foldouts, foldside).
  Bad keys or values change nothing.
- `bars ID`: one line per system with its first bar and letters; `p N` pickup
  on/off (movement starts), `s N` split on/off (bars after a repeat), `f N=B`
  line N starts at bar B (`f N=` clears), `m B [B ...]` rehearsal marks on/off
  at the printed bar numbers; Enter saves. Each line shows its bar range ("bars
  93-98") and its marks. An unknown bar names the valid range.
- Rehearsal marks: `bar_rules.marks_add` / `marks_drop` hold bar numbers. The
  marks found after repeats, minus marks_drop, plus marks_add (first bar with
  that number), are lettered A, B, ... in bar order per movement. A mark added
  before others moves their letters on.
- Per-part layout: `layout.parts: {part or group: {key: value}}` over the item
  layout, for pages, gap, min_gap, scale, min_staff_mm, max_staff_mm, reflow,
  title_page, bar_raise, bar_size, ink. `set ID "Continuo:pages=2"`
  (`:pages=auto` clears); `expand ID [part]`, `contract ID [part]`; the menu keys
  `e`, `c`, `p` ask for a part (Enter = all). Build options on the command line
  win. A rename in `parts` moves the part's layout with it.
- Item menu: edits `m` title/composer, `t` part names, `g` groups, `n` bar
  numbers, `e` expand, `c` contract, `p` pages, `a` paper (Letter -> A4 ->
  Ledger -> Letter), `k` ambitus (parts numbered with their range; LOW-HIGH,
  auto, off, on; Enter keeps), `s` set; `v` review, `y` analyse again, `x`
  repage, `r` build, `b` back. The status line shows the changes not built.
- Stages:
  1. Analyse: `new` (or `partitor analyse ID` again) reads the score and writes
     `<id>-proof.pdf` (part per staff, continuity); no part PDFs. Analysing again
     keeps title, composer, settings, the part names, groups, parts not
     extracted and the ambitus set by hand. A system still uncertain suggests its
     previous answer (Enter). Choices and bar corrections are asked again.
     `analyse ID --yes` asks nothing (open choices stay for `rebuild`);
     `analyse ID --join p5:4` says that no system ends after staff 4 of source
     page 5 (two systems taken apart are one; `--unjoin` takes it back): saved
     as `system_joins`, kept by every later analysis, then the analysis runs
     again. In the choices, `j` does the same for the system asked about and
     the one below it, and the questions start over;
     `analyse --all` analyses every library item that way (after an engine
     update); one failure does not stop the rest. The proof rings each part's
     lowest and highest note in green, named with bar, page and system, and page
     1 lists every part's ambitus. A failed analysis still turns its preview into
     the proof (the gate marks in red), so the proof PDF is the one place to
     look. G2 and G8 count as one clef for the part mapping.
  2. Edit, any order, as often as needed: every edit (`set`, `parts`, `groups`,
     `bars`, `meta`, `expand`, `contract`, menu letters) is saved, not built;
     `score.yaml` `pending` lists what changed. The proof is redrawn after part
     names and choices. `--build` builds at once (one-step use on the command
     line).
  3. Review: `partitor show ID` (menu `v`): status, files, title, subtitle,
     composer (full and short), parts (not extracted, two staves), groups, bar
     numbers, open choices, settings, the changes not built, the last build.
  4. Build: `partitor rebuild ID` (menu `r`); clears `pending`. The wizard ends
     with the review and "Build now? [Y/n]"; n keeps the item "ready to build".
  Status: not analysed, needs choices, ready to build, changes not built, built.
- Composer, long and short: `composer` (full name) on the title page or under the
  title band; `composer_short` (default the last word of `composer`) in the
  running head of interior pages. The wizard asks both; `partitor meta ID` (menu
  `m`) edits title, subtitle and both composer forms.

### 6.3 Republish

Not part of partitor (§7). A rebuilt item is a new set of part files in place.
Scripts that copy them elsewhere run again on their own.

---

## 7. Publishing

Out of scope (§1). partitor has no `publish` command, no network code and no
index page. The part files and their names are a stable contract
(`LIBRARY-LAYOUT.md`) so that your own script can sync or publish them.
`OVERLAYS.md` shows where such a script fits.

---

## 8. Security

partitor parses PDFs that come from the internet. MuPDF has a history of
security bugs. So:

- Dedicated system user `partitor`. Never root. The engine refuses root.
- The operator runs `partitor` (the wrapper, `bin/partitor`, as root). The
  wrapper never parses a PDF: it checks paths and the library folder, then
  starts the engine (`lib/partitor-engine`, run by the venv Python of the repo)
  with `systemd-run --uid=partitor` and the sandbox of `SANDBOX.md`.
- The sandbox has no network, a read-only system, no `/home` and `/root`, a
  private `/tmp` and `/dev`, no capabilities, and a memory cap. Writes go only
  below `/var/lib/partitor` and (library commands) the library folder.
- `systemd-run --pipe`, never `--pty`: `--pty` ends the session with ESC[!p
  (soft terminal reset), which clears the screen in some terminals. Colour stays:
  the wrapper sets `PARTITOR_COLOR=1` when its stdout is a terminal (else 0) and
  the engine reads it. The wrapper also sets `PYTHONUNBUFFERED=1` (the pipe would
  block-buffer the output).
- SMB mode: a dedicated NAS user with access to the one share only, a long
  random password, SMB 3.1.1 with encryption (`seal`), and SMB closed to the
  internet. Credentials are in `/etc/partitor/smb.cred` (0600 root). Never in the
  repo, never printed.

Direct mode (no sandbox) is not built. Without systemd (macOS, WSL2 without
systemd) the engine can run by hand; there is then no sandbox (`SECURITY.md`).

---

## 9. Installer

Repeatability rule: no step may live only in documentation. Each step is done
by the installer, or the installer checks it and prints the exact command to
run.

`bin/partitor-init` asks the questions, writes `/etc/default/partitor` and the SMB
credentials (0600 root), and runs `bin/partitor-install --config`. It never
changes the system itself.

`bin/partitor-install` is idempotent. Steps, in order (details in the header of
the script and in `INSTALL.md`):

| Item | Installer action |
|---|---|
| apt packages (`python3-venv`, `tesseract-ocr`; `cifs-utils` in SMB mode) | Check. If missing: FAIL and print the `apt install` command. Not installed automatically (the operator sees dependencies and problems). |
| User `partitor` | Create if missing (system user, no login shell, home `/var/lib/partitor`). |
| State folders | `/var/lib/partitor` and `/var/lib/partitor/work`, 0750. |
| Settings | `--config FILE` is copied to `/etc/default/partitor`. |
| Library folder (local mode) | `<library>`, `inbox/`, `library/` at 2770, owner and group `partitor`. |
| venv `<repo>/venv` | Create if missing (root-owned, read-only for `partitor`). Reinstall the pinned packages when the `requirements.txt` hash changes. |
| Bytecode of `lib/partitor` | Compile as root (`python -m compileall --invalidation-mode checked-hash`) when a `.py` file has no `.pyc` or is newer than it. The service user cannot write the read-only tree, so without the files Python compiles every module in memory at each start. `--check` reports a missing or old file. |
| Package readability | As user `partitor`, every file of `lib/partitor` must be readable and every folder searchable. WARN with the fix command when not. |
| Links | `partitor`, `partitor-init`, `partitor-install` in `/usr/local/sbin` -> `<repo>/bin/<name>`. |
| Logo (optional) | Check `PARTITOR_LOGO` in the settings: WARN when the file is missing, lies where the sandbox cannot see it (`/home`, `/root`, `/run/user`, `/tmp`, `/var/tmp`) or cannot be read by user `partitor`. Check `<library>/logo.png` too, when it exists: WARN when user `partitor` cannot read it (silent when absent). Never a FAIL: without the logo the engine builds as before. |
| Self-test | `partitor --sandbox-check`: every line must be ok. |
| SMB mode: credentials | Check `/etc/partitor/smb.cred` (0600 root:root). |
| SMB mode: units | Mount and automount units for the library folder, written from `share/systemd/*.in`; automount enabled. The share mounts on first use and unmounts when idle; the boot never depends on the NAS. |
| Library check | In the sandbox, as user `partitor`. NAS not reachable: WARN. |

`--check` does the same checks read-only (exit 1 on a difference). `--dry-run`
lists what a run would change (exit 0).

---

## 10. Tests

- The repository has no sample scores. Public tests use synthetic PDFs that the
  tests draw themselves. They cover the logic: staves, systems, ownership,
  layout, CLI, installer.
- The engine tests are split by area: `tests/test_analysis.py`, `test_mapping.py`,
  `test_bars.py`, `test_parallel.py`, `test_layout.py`, `test_render.py`,
  `test_clef.py`, `test_library.py`, `test_cli.py`. Shared helpers (the engine
  loader `pt`, the synthetic score and scan drawers, `mock_attr`, the logo
  fixture) are in `tests/support.py`. A broken import of the engine stops the
  run; only a missing third-party package skips the engine tests.
- Corpus tests run the engine on real scores and compare staff, system and bar
  counts. They need your own PDFs and skip per missing file (`TestCorpus.need()`
  in `tests/test_analysis.py`; the file list is the `CORPUS` table there).
- `tools/g0_golden.py` records and checks "golden" renders: page images at 100
  dpi and normalised text of 50 cases. Use it for a refactor: record before,
  check after (`--tests tests/support.py`, the default). Goldens depend on the
  package versions, so record and check in the same environment.
- `tools/m0_depmap.py` maps the dependencies between functions of the engine
  (one file, or a folder such as `lib/partitor`).
- `tools/check-modules.py` checks the module structure of `lib/partitor` (§12.3).
  `tools/bench-start.sh` measures the start-up time of the engine.
- `tests/test_ci.py` fails when the number of discovered tests falls below
  `MIN_TESTS`. Raise that number with every step that adds tests.
- Layout defaults come from **printed** test pages, not from the screen.

---

## 11. Known limits

See `KNOWN-LIMITS.md`.

---

## 12. Code map

The engine is the package `lib/partitor/`, in 24 modules (the split took the releases
`0.5.0-dev.1` to `0.5.0`). `lib/partitor-engine` is a launcher: it puts `lib/` on the path and
starts `partitor.cli_main.main`; `python -m partitor` starts the same function. Every step of
the split kept the output identical (`tools/g0_golden.py check`). The development history of the
engine is in `HISTORY-ENGINE.md`. The tables below are the map of the code.

### 12.1 Modules and import levels

A module imports only from a **strictly lower** level. `tools/modules.txt` is the
machine-readable list; `tools/check-modules.py` enforces it.

| Lvl | Module | Owns |
|---|---|---|
| 0 | `console` | Output primitives, colours, counters, prompts, `Abort` |
| 0 | `config` | Tunables, `TUNE`, layout and score keys, defaults, paper sizes (`PAPER`), name helpers |
| 0 | `model` | Data classes `Staff`, `PageResult`, `Strip`, `RestRun` |
| 0 | `typography` | Fonts and text measure |
| 0 | `mapping` | Staff label to part map, accent folding (`fold_accents`) |
| 0 | `bars` | Bar numbers, bar marks, barline edits |
| 1 | `vision` | Page render, tracking, dewarp, staff and system detect, OCR |
| 1 | `clef` | Clef signature, notehead steps, ambitus |
| 1 | `parallel` | `fork_map`, job and memory sizing |
| 1 | `reflow` | Re-flow of strips |
| 1 | `strips` | Strip build, group strips, bar marks, rehearsal boxes |
| 1 | `turnplan` | Page-turn planner: spreads, fold-outs, turn classes (§5.7) |
| 2 | `ownership` | Ink ownership, safety gate, barline detect |
| 2 | `lines` | Line fitting, labels, multi-bar rests, saved lines |
| 2 | `stagecache` | Stage cache of the page analysis (§12.4) |
| 3 | `analysis` | Page loop, preview, cache read and write around `analyse_page` |
| 3 | `render` | Packing, page plan, part drawing |
| 4 | `partplan` | Part planning: the options table of `plan` (§5.8) |
| 4 | `library` | Item folder, ids, load and save, parts folder swap, `step_size` |
| 5 | `build` | `pieces`, `detect`, `build`, run and report helpers |
| 5 | `proof` | Proof PDF |
| 6 | `cli_common` | Shared CLI helpers, `set` |
| 7 | `cli_bars` | `bars` command |
| 7 | `cli_parts` | `parts`, `groups`, ambitus menu |
| 8 | `cli_items` | Item commands |
| 9 | `cli_main` | Menu, `main`, sandbox check |

### 12.2 Where a DESIGN section lives

| DESIGN section | Module |
|---|---|
| §2, §2.1 naming, §3 settings | `library`, `config` |
| §4.1 base pipeline | `analysis`, `build` |
| §4.2 items 1, 3, 7 (barlines, numbers, pickups) | `bars` |
| §4.2 item 2 (re-flow) | `reflow` |
| §4.2 items 5, 8 (bar number place, rehearsal letters) | `strips` |
| §4.2 item 9 (multi-bar rests) | `lines` |
| §4.3 items 1, 6, 12 (gate, text ownership, system window) | `ownership` |
| §4.3 items 2, 3, 5, 9, 10 (scan, plausibility, grouping, edges, conditioning) | `vision` |
| §4.3 item 4 (per-system mapping) | `mapping` |
| §4.3 item 13 (ambitus) | `clef` |
| §4.3 items 7, 11 (multi-work, group outputs) | `build`, `strips` |
| §4.4 parallel | `parallel` |
| §12.4 stage cache | `stagecache`, `analysis` |
| §5.1 to 5.4, 5.6 layout | `render` |
| §5.7 page-turn planner | `turnplan` |
| §5.8 part planning | `partplan` |
| §5.5 typography | `typography`, `lines` |
| §6 CLI | `cli_*` |
| §8 security (sandbox check) | `cli_main` |

This map comes from function names and headings. Check it when a module exists.

### 12.3 Rules

- **Levels.** No import of the same or a higher level, no cycle, also not inside a
  function. Every module starts with `from __future__ import annotations` and the SPDX
  line. `lib/partitor/__init__.py` has no imports: every start of the engine reads it.
- **Shared state (R1).** A name that other modules rebind, and every name in
  `tests/patchable.txt`, is used as `owner.NAME` (import the module, not the name).
  `from owner import NAME` makes a copy: a test patch or a rebinding then changes the
  owner and leaves the copy as it was. Today these are `console._TTY` (rebound in a
  worker), `config.TUNE`, `config.SIZE_FIRST`, `parallel.fork_map`, `analysis.analyse_one`
  (patched by tests; no other file has a copy and reads `analysis.analyse_one`),
  `ownership.analyse_page` (patched by tests; `analysis` reads `ownership.analyse_page`),
  `stagecache.ANALYSIS_CACHE_FORMAT` (patched by tests),
  `render.SYSTEM_GAP_LAST` (patched by tests; `plan_pages` reads it in `render`, the script
  has no copy), `build.run_build` and `build.cmd_build` (patched by tests; their readers use
  `build.run_build` and `build.cmd_build`, also the command table of `main`, and
  no other file has a copy), `cli_items.cmd_rebuild` (patched by tests; menu `r` and the
  command table of `main` read `cli_items.cmd_rebuild`, no other file has a copy) and `vision._TESS` (the
  path of the tesseract program; nothing rebinds it, but the plan names the owner, so the
  script reads `vision._TESS["path"]`). An object that is changed in place and never
  rebound (`console._counts`, `_FAILURES`, `_WARNINGS`, `clef.CLEF_LAST`, `clef._CLEF_TPL`,
  `render.LAST_RENDER`, `render._LOGO_WARNED`, `build.LAST_BUILD`) may be imported by name: both names are the
  same object. `console._reset_counts` keeps it so; the two clef caches are private to
  `clef`, and `render` fills `LAST_RENDER` with `.update` and item assignment only;
  `build` fills `LAST_BUILD` with `.clear` and `.append` only. The
  page-turn costs (`TURN_BAD`, `PAGE_COST`, `FILL_COST` and the like) stay constants of
  `typography`; `render` imports them by name. `library` has no name of this kind: it
  keeps no state in memory (it works on files) and no test patches a name of it.
  `check_margins` and `MIN_MARGIN_MM` are in `config` (plan O7): the script and `library`
  use them, `render` does not.
- **Image libraries.** Commands that read no image (`list`, `show`, `set`, `expand`,
  `contract`, `bars`, `parts`, `groups`, `meta`, `rename`, `reid`, `proof`, `--version`,
  `--help`) start without cv2, numpy or pymupdf. Only PyYAML is loaded. So the modules on
  their path (`config`, `console`, `model`, `mapping`, `typography`, `bars`, `clef`,
  `library`, `proof`, `cli_common`, `cli_bars`, `cli_parts`, `cli_items`, `cli_main`) do not
  import cv2, numpy or pymupdf at the top: a function imports the package it uses
  (`import numpy as np` inside the function), and `model` imports numpy under
  `TYPE_CHECKING` for its annotations (they stay strings). The heavy modules (`vision`,
  `strips`, `reflow`, `ownership`, `lines`, `analysis`, `render`, `parallel`, `build`) may
  import them at the top. A light module reaches a heavy one only inside the function that
  needs it (`from .build import run_detect` in `analyse_item`); `main` loads `build` for
  `pieces`, `detect` and `build` only. No test patches `pymupdf`, `cv2` or `np` in a module.
  `tests/test_lazy_imports.py` runs each light command in a fresh interpreter and looks at
  `sys.modules`. `PAPER` is in `config` (the `build` option `--paper` needs it before
  any image library loads) and `step_size` is in `library` (`expand` and `contract` need it).
- **`global`.** `global NAME` is allowed only for a name that the same module assigns
  or defines at top level. For a name of another module write `owner.NAME = value`.
- **Size.** At most 1 100 definition lines per module. One module is exempt
  (`ownership`: `analyse_page` is one function of 852 lines).
- **Pickles.** Saved `.lines` files hold class paths. Files of 0.4.2 say `__main__.Strip`;
  files written since 0.5.0-dev.2 say `partitor.model.Strip`. The reader (`_LinesUnpickler`, in `lines`)
  accepts `__main__`, `partitor`, `pt` and every `partitor.*` path for `Strip` and `RestRun`
  only, and will keep doing so, so a later rename of a module does not break saved files.
  An older engine that reads a new file stops with an unpickling error, which `load_lines`
  turns into "rebuild the part". `LINES_FORMAT` stays 1.
- **Fonts.** `typography.font_dirs` computes the repo folders from its own file
  (`lib/partitor/typography.py`): the order is `PARTITOR_FONTS`, `share/fonts` of the repo,
  `/opt/partitor/fonts`, `lib/fonts`. A test lists them, because a wrong depth falls back to
  the built-in Times without a message.
- **Version.** `VERSION` lives in `lib/partitor/__init__.py`. The file `VERSION` in the
  repo root carries the same number for the wrapper and the installer; a test checks it.
- **Entry point.** `lib/partitor-engine` defines nothing: it puts its own folder on the path
  (`sys.path.insert` from `os.path.realpath(__file__)`, so `python3 -I` and a start through a
  symlink work) and calls `partitor.cli_main.main`. `python -m partitor` (`__main__.py`, with
  `PYTHONPATH=lib`) calls the same function. `bin/partitor`, the sandbox and the file name are
  unchanged.
- **Tests.** `tests/support.py` exports `pt`, a view over the package: a read finds the module
  that defines the name, a write goes to that module (so a patch through `pt` reaches the only
  place that reads the name), and a name that no module defines raises `AttributeError`.
  Tests that patch use the owner module (`build.cmd_build`, `cli_items.cmd_rebuild`).
- **Checks.** `tools/check-modules.py --static` (also in `tools/check-repo.sh` and CI),
  `--import` (each module alone in a fresh interpreter), `--affected MODULE` (the modules
  that import it, and the test files to run).

### 12.4 Stage cache of the page analysis

`detect` and `build` run the same analysis of each page (`ownership.analyse_page`). The
result (`PageResult`, with the owner image) is kept in `cache/` of the item folder, one file
per page (`p0007-<key>.pcache`, gzip level 1 of a pickle, 0.5 to 0.7 MB for a 400 dpi page),
so a `build` after a `detect`, and a second `build` of the same score, read the page instead
of analysing it. The cache holds the result **before** the operator's bar edits; `analyse_one`
applies those edits to every result, read or new.

- **Key.** SHA-256 of: the PDF content hash, page number, dpi, OCR on or off, the system base
  (always 0 with the cache), the operator's system joins on that page (only when there are
  some: a page without joins keeps its entry, 0.8.22), `TUNE["page_header_sp"]`, `ANALYSIS_CACHE_FORMAT`, a
  hash of the source of every module that `ownership` reaches by relative imports
  (so a code change cannot give a stale hit, with or without a new release number), the
  versions of cv2,
  numpy and pymupdf, and the tesseract path, its version line and `TESSDATA_PREFIX`. The
  analysis reads no other setting (`PARTITOR_*` variables do not reach it). The release number
  is not in the key: a release that leaves the analysis code alone keeps the entries (0.7.1).
- **Format.** `ANALYSIS_CACHE_FORMAT` (1) is part of the key and of the file. The reader
  (`_CacheUnpickler`) accepts `Staff`, `PageResult`, numpy array reconstruction and a few
  builtins, and nothing else.
- **A failed read is a miss.** A corrupt, truncated, old-format, wrong-key or refused file is
  deleted and the page is analysed again, with one `cache:` note per process. The output is the
  same as without a cache.
- **Write.** Temp name, then `os.replace`; the other entries of the same page are removed,
  so one entry per page stays. Two processes with the same key write the same bytes. A write
  that fails (read-only folder, full disk) is skipped with one note.
- **Switch.** `PARTITOR_CACHE=0` (also `off`, `no`, `false`) keeps no cache and reads none. The
  wrapper passes the variable into the sandbox.
- **Visible.** When entries exist, `detect` and `build` print one line:
  `analysis cache: N of M page(s) found`. Nothing else in the output changes.
- **Size.** About 0.6 MB per page; a 70-page score about 40 MB. The folder is part of the
  item: `rm -r cache/` is always safe.
