<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
<!-- Copyright (C) 2026 Nathan Wilkes and partitor contributors -->
# partitor — engine history

Development history of the engine, newest first (0.1.0 to 0.5.0). Before 0.5.0 it was the
header comment of `lib/partitor-engine`; the text is unchanged, except that one reference to a
note that is not in this repository is reworded (0.3.0-dev.19). For releases see
`CHANGELOG.md`; for the design see `DESIGN.md`.

```text
  0.5.0 - The engine is the package lib/partitor in 23 modules with a fixed import order.
          lib/partitor-engine is a launcher: it puts lib/ on the path and starts
          partitor.cli_main.main. The shim imports are gone. cli_main (menu, main,
          sandbox check) moved last. This history moved from the header of the launcher to
          this file. Commands, options, output and sandbox unchanged.
  0.5.0-dev.8 - Four modules moved from this file to lib/partitor/: cli_common, cli_bars,
          cli_parts, cli_items. This file imports their names (shim imports). cmd_rebuild is
          patched by tests, so it has no shim and is read as cli_items.cmd_rebuild. Output
          unchanged.
  0.5.0-dev.7 - Two modules moved from this file to lib/partitor/: build, proof. This file
          imports their names (shim imports). run_build and cmd_build are patched by tests, so
          they have no shim and are read as build.run_build and build.cmd_build. Output
          unchanged.
  0.5.0-dev.6 - One module moved from this file to lib/partitor/: library. This file imports
          its names (shim imports). check_margins and MIN_MARGIN_MM moved from render to config.
          Output unchanged.
  0.5.0-dev.5 - Two modules moved from this file to lib/partitor/: lines, render. This
          file imports their names (shim imports). SYSTEM_GAP_LAST is patched by tests, so it
          has no shim and is read as render.SYSTEM_GAP_LAST. The page-turn costs stay in
          typography. Output unchanged.
  0.5.0-dev.4 - Three modules moved from this file to lib/partitor/: reflow, ownership,
          analysis. This file imports their names (shim imports). analyse_one is patched by
          tests, so it has no shim and is reached as analysis.analyse_one. The comment on
          PROOF_H no longer says that preview_page sets it. Output unchanged.
  0.5.0-dev.3 - Three modules moved from this file to lib/partitor/: vision, clef, strips.
          This file imports their names (shim imports). The OCR state _TESS is reached as
          vision._TESS. The unused key "warned" of _TESS is removed. Output unchanged.
  0.5.0-dev.2 - Seven modules moved from this file to lib/partitor/: console, config,
          model, typography, mapping, bars, parallel. This file imports their names (shim
          imports) and reaches shared state as module.NAME. Saved .lines files of earlier
          engines still load. Output unchanged.
  0.5.0-dev.1 - Start of the modular split. VERSION moved to lib/partitor/__init__.py;
          the script imports it. No other change; output unchanged.
  0.4.2 - `new --jobs N|auto` (detect and build steps of the wizard). Output
          unchanged.
  0.4.1 - `detect` (and `new`, which calls it) analyses pages in forked workers,
          as `build` does (fork_map, job_count; --jobs, PARTITOR_JOBS). A worker
          analyses a page with system base 0, runs the gate line and the preview,
          and returns only the system records, the preview section, the title and
          the composer. Output is the same as with one job; --jobs 1 keeps the
          old single-process loop. With workers the run prints the worker count,
          the largest worker's memory and the analysis time.
  0.4.0-rc.1 - Public release candidate. The version is the version of the
          repo (file VERSION); wrapper and installer carry it too. BREAKING:
          PARTITOR_SHARE is now PARTITOR_LIBRARY (default
          /var/lib/partitor/library); PARTITOR_LOGO is a PNG file (was a
          folder with a fixed name), unset = no logo and no room kept for
          it; --sandbox-check --share is now --library. Fonts are found in
          share/fonts of the repo. Output is unchanged for equal settings.
  0.3.0-dev.39 - PARTITOR_COLOR=1 gives colour (and self-overwriting progress
          lines) without a terminal. The wrapper (1.0.10) now always uses
          `systemd-run --pipe`: --pty ended the session with ESC[!p, which
          cleared the screen in some terminals.
  0.3.0-dev.38 - turns=rest: a movement start with no rest is a second choice (cost
          150; marked "check attacca"); a rehearsal letter is not. `repage` works
          from the wrapper (it was missing in the command list of partitor-run).
  0.3.0-dev.37 - `repage ID [part ...]` (menu `x`): plans the page breaks of built
          parts again from the saved lines (lines/), without analysis or
          build. Page turns fall only where the player rests (a multi-bar
          rest line beside the turn); a turn while playing is a warning. A
          medium weight against under-filled pages. New layout keys
          `turns` (any | rest) and per part `breaks` ("break after bar N").
          A build saves the lines; letter and A4 output is unchanged
          (turns=any).
  0.3.0-dev.34 - Re-flow of group scores (`Trombones:reflow=on` works): lines are
          cut only at barlines that every staff of the group has, clef and key
          are copied to each staff, bracket and label column stay. Group page
          budget with pages=auto: 1.5 x the pages without re-flow. The build
          prints a re-flow report (lines cut, lines whole and why, widest
          whole line). The small-print offer sees groups and runs after a
          build of some parts or groups. Output unchanged where nothing is cut.
  0.3.0-dev.33 - `rebuild ID [part ...]` / menu `r [part ...]` builds only the
          parts and groups named (numbers, ranges, names); the other part
          files stay. Page analysis and part rendering run in forked workers
          (PARTITOR_JOBS, --jobs). A part-only build skips pages that none of
          its parts needs. Output is the same as before.
  0.3.0-dev.32 - A build writes into parts.new/ and replaces parts/ only
          when it succeeds; the old set stays in parts.prev/. A crash or
          kill leaves parts/ as it was (before, the old parts were deleted
          first). Re-flow undo restores parts.prev/ (no second build).
  0.3.0-dev.31 - Bars menu: detailed help and `?` with an example; `s N I`
          splits any bar (a bar cut by a line break, repeat or change of
          mensuration), `m N:I` puts a letter on one bar (two bars can
          share a number), `b N` lists the bars with source numbers, splits
          and letters, `v` draws proof.pdf with the unsaved edits. `j N 1`
          on a clef stub before a repeat start keeps the repeat. proof.pdf
          shows barline ticks, bar numbers and rehearsal letters; command
          `proof ID` draws it again.
  0.3.0-dev.30 - Bar edits (`partitor bars`: j join, a add, u undo): the
          operator mends a misread barline; kept over an analysis again.
          Printed bar numbers that differ from the barline count: warned,
          asked (k keeps them), the build stops until settled.
  0.3.0-dev.29 - Fixed: stacked G clefs gave a false barline at 3.65 sp
          (dotted evidence in two gaps) and so a bar too many in a system.
  0.3.0-dev.28 - Empty printed staves (no noteheads read, no stem past the
          start of the staff) become multi-bar rests; a group only when
          all its staves are empty (`rests=compress|keep`, --rests).
  0.3.0-dev.27 - Ambitus draws # and b (80 % size, left of the heads); the
          range keeps them ("F#3-E4"); ambitus_for returns 5 items.
          (dev.26: input accepted # and b, ignored them.)
  0.3.0-dev.25 - Ambitus as two stacked black noteheads at 80 % size
          (was two whole notes side by side); bars menu: each line shows
          its bar range, marks show their real bar number, `m` takes
          several bar numbers, clearer help.
  0.3.0-dev.24 - Ambitus in the first-line indent in place of the name;
          group scores: each staff's ambitus on the first line; doubt
          questions suggest the range without the doubtful note.
  0.3.0-dev.23 - Menu: items newest first under their stable serial;
          five changed last as A-E (from 9 items); * marks work pending.
          list newest first.
  0.3.0-dev.22 - Group rest line keeps the bracket; specks past the right
          staff end cut; ambitus locations with page and system; a
          failed analysis still makes the proof.
  0.3.0-dev.21 - Reference system by printed labels; continuo names and
          abbreviations in label matching; continuo on the bottom staff;
          capped bottom alignment. Small systems not joined without
          bracket evidence. Gate tolerance 1.6 sp (beams).
  0.3.0-dev.20 - Command rename: folder name follows title and composer;
          offered after m; set prints a hint. Slugs write German letters
          as ae/oe/ue/ss.
  0.3.0-dev.19 - Ambitus by hand made easy: bar number of each extreme
          (proof, show, menu k); doubtful extremes flagged and asked
          after an interactive analysis. A note on state extraction added (not in this repository).
  0.3.0-dev.18 - Lyric lines kept whole with the staff above (row by
          band overlap, text line to the staff above, stray syllables
          pulled in). Ambitus: no letters, barlines, repeat dots or time
          signatures; hollow heads found more often.
  0.3.0-dev.17 - Menu and list: composer (short) after the id; menu
          pages (PARTITOR_LIST_PAGE, + / -) and /words filter; list
          [words]. Choices: a staff left out shows as 0, q named, an
          example after a wrong answer.
  0.3.0-dev.16 - Analyse again keeps part names, groups, skip list and
          ambitus by hand (detect gets one name per staff); previous
          answers as suggestions; --yes asks nothing; --all. Menu key k
          (ambitus). Proof rings each part's extremes, lists ambitus.
          G2 and G8 one clef for mapping.
  0.3.0-dev.15 - Ambitus: noteheads per staff at analysis, part range in
          score.yaml (auto / on / operator / off; continuo off), set
          "Part:ambitus=C4-F5", shown in show, printed beside the part
          name. Clef G8 (treble with 8 below).
  0.3.0-dev.14 - Clefs: barline/bracket columns removed, read at start
          offsets 0/+0.5/+1 sp. Voice cues in a system header discarded
          (not copied into parts). Footnote on the figures row discarded.
          New command reid: old YYYY-NNN item -> YYYY-MM-NNNN.
  0.3.0-dev.13 - Item keys (id, slug, created) kept when detect fails;
          a missing id is read from the folder name (menu showed
          "2026-10-").
  0.3.0-dev.12 - Part mapping: a part goes on across staff-count changes,
          clef family weighs more than clef line, braced pairs, voice
          cue in the header as label, "continues previous system";
          system start snapped to the page. CLI: a corrected answer is
          the suggestion of later systems with the same clefs; set/show
          print set names and words (pages: 5 -> auto).
  0.3.0-dev.11 - Footer text (copyright, page number, footnote) and
          page-edge ink below the last staff discarded; a voice cue
          "35 (Alto I)" no longer starts a movement; end barline added on
          curled pages. Rest brackets full staff height. Per-part layout
          (set "Part:key=value", expand/contract <id> <part>). Rehearsal
          marks by bar (bars: m B), lettered in bar order.
  0.3.0-dev.10 - Clefs read with their line (G1/G2, C1-C5, F3-F5) by
          comparing with Bravura glyphs; F by its dots; rare clefs need
          a lead. Rest brackets visible. Group scores: systems apart by
          1.5x their staff gap; up to 2.0x on a last page with room.
  0.3.0-dev.9 - Stages: analyse (proof) / edit (saved, not built;
          pending list) / review (show) / build (rebuild). analyse and
          meta commands; --build on edits; wizard ends with review and
          "Build now?". composer_short in the running head.
  0.3.0-dev.8 - Ids YYYY-MM-NNNN; item files <id>-score.yaml etc.; part
          files NN-<part>-<Composer>-<Title>--<id>.pdf. Group scores:
          left-out staves leave no space, one label column (right edges
          align). H-bar spans the measure. Page breaks planned for the
          whole part: turns at section boundaries (movement, letter,
          rest), title page or not by turn quality.
  0.3.0-dev.7 - Engraved look: every line of a part as wide as the
          longest (space added in blank gaps only; rest lines drawn at
          the width); first line indented with the part name in small
          caps; multi-bar rest count in Bravura time-signature digits;
          group scores label their staves (short names when the staves
          change). Scan dust in headers dropped; system barline in the
          gaps no longer hangs below a staff; a rest line borrows the
          clef of a matching line of another movement.
  0.3.0-dev.6 - Multi-bar rests: a system without a part's staff (the
          source leaves out a resting part) becomes a rest line (clef
          and key, H-bar, count; movement title kept), runs merged, so
          parts stay playable and numbered. A scan's page edge is no
          title (it restarted the numbering). Printed bar numbers up to
          2.4 sp high are read.
  0.3.0-dev.5 - Re-flow (opt-in; offered when the print is small; expand
          steps to it); EB Garamond for all text (installed in
          /opt/partitor/fonts); title page for 3+ pages of music; group
          scores (`partitor groups ID`, bracket); a part not extracted
          stays in the list; default staff ceiling 8 mm. Repeat barlines
          missed by the barline rules are inserted (bar counts).
  0.3.0-dev.4 - Parts: N=- leaves a part out, N+M joins part N into M
          (one part on two staves); two-staff parts show 'G+F'. Staff
          size of a two-staff part is one staff (4 sp), not the system.
  0.3.0-dev.3 - Choices with context (source page, system position,
          clefs, printed labels, suggestion as numbers; part clefs);
          proof.pdf labels systems and parts, red frame for choices,
          redrawn after each change; part names one at a time (N=name);
          `partitor parts ID` (menu t).
  0.3.0-dev.2 - Bar numbers: repeat signs found; pickups and bars split by
          a repeat proposed from bar widths (per line, lines are
          justified), confirmed in the CLI (Y/n), corrected with
          `partitor bars ID` (pickup, split, line-start fix); printed
          numbers that follow the plain count are converted. Rehearsal
          letters (boxed, A.. per movement) at the first full bar after
          each repeat. Double leading before a movement. Composer read
          from the page; title in the size of other text found when a
          composer line stands below it. Bracket hook removed. Large-print
          copies (11x17 with crop marks, A3). Slugs drop apostrophes.
  0.3.0-dev - Library folder and phone CLI (DESIGN.md §2,
          §3, §6): menu, new (wizard: inbox PDF -> library/<id>-<slug>/,
          score.yaml, proof.pdf, parts named <id>-<slug>-NN-<part>.pdf),
          list, show, set, expand, contract, rebuild. Installed as
          /opt/partitor/bin/partitor-engine, run through
          /usr/local/sbin/partitor (systemd-run sandbox, user partitor);
          refuses root. --sandbox-check [--library] for the installer.
  0.2.0-dev.3 - System window: page-edge, spine and bracket ink is no
          staff's (no indent, no right-margin marks). Mensurstrich dashes
          in the gaps discarded. Leading 10 sp (floor 7). Margins, gutter
          and duplex (spine margin) options. Bar numbers clear the clef;
          --bar-raise, --bar-size. layout.yaml no longer freezes defaults.
          Last page holds at least 3 lines. Bar-number zone 4.5 sp.
  0.2.0-dev.2 - Constant leading and page-turn layout choice (gap 8 sp,
          floor 5.5 sp; fewest turns, then staff size, then gap).
          Measure numbers at each line start from barline counts,
          anchored on printed numbers (OCR); printed line-start numbers
          replaced. Staff start refined and shared per system (left
          alignment). build runs OCR like detect. See CHANGELOG.md.
  0.2.0-dev - Engine robustness (DESIGN.md §4.3 items 1-10).
          Scan conditioning: background flattening, local threshold
          (Sauvola) united with Otsu, despeckle (noise is a counted
          discard class). Staff tracking in 16 vertical bands, linked
          into tracks; pages with bent staves are straightened (dewarp)
          before staff detection. Broken staff lines are bridged.
          Plausibility: implausible staff space gives a no-music page.
          Safety gate: discard has classes (header, footer, label,
          bracket, connector, edge, noise, no-music); a staff track that
          is not an accepted staff, or staff-like lines in discarded ink,
          fails the run. System grouping accepts dotted connectors and
          Mensurstriche, else page gap clustering. Lyrics and figures
          belong to the staff above. Page-edge artefacts are discarded.
          Labels left of and above staves are read by OCR (tesseract)
          and discarded. Clef signature per staff. Part map per system
          (labels, clefs, continuity; ordered subset of the fullest
          system); uncertain systems get '?' plus a suggestion.
          `pieces` command and --pages. Pages are processed one at a
          time (memory). Default paper letter. --ink darker.
  0.1.0 - MVP. Raster pipeline for vector and scanned pages: deskew,
          staff detection by run lengths and line projection, system
          grouping by a left connecting line (gap rule fallback), staff
          line and gap-connector removal, connected components,
          text-line grouping, ownership with chaining,
          system header copy, page-top/bottom discard, conservation
          check, skyline packing, title band, HTML preview.
```
