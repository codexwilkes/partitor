<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
<!-- Copyright (C) 2026 Nathan Wilkes and partitor contributors -->
# Operating

`operator-flow.html` is the step-by-step guide for a piece: drop, analyse, edit,
review, build. Open it in a browser. This page is the short reference.

## Commands

Run as root (`sudo partitor ...`). The engine itself runs as user `partitor` in a
sandbox (`SANDBOX.md`).

| Command | Does |
|---|---|
| `partitor` | Menu: recent items and "new from inbox". |
| `partitor new [n]` | Wizard for a PDF in `inbox/`. |
| `partitor list [words]` | All items, or those that match every word. |
| `partitor show ID` | Review: parts, groups, settings, open choices. |
| `partitor set ID key=value ...` | Change settings (saved, not built). `Part:key=value` for one part. |
| `partitor expand ID [part]`, `contract ID [part]` | One step larger or smaller. |
| `partitor analyse ID [--yes]`, `analyse --all` | Read the score again. |
| `partitor bars`, `parts`, `groups`, `meta`, `proof ID` | Edit bar numbers, part names, groups, title; redraw the proof. |
| `partitor plan ID [part [N]]` | Which paper and staff size give the best page turns? Read-only until you pick an option `N`; then `rebuild`. Guide: `PLAN-AND-FOLDOUTS.md`. |
| `partitor pages ID part [--move PAGE=N] [--dry-run]` | The pages of a built part with the turn after each; move a system to the next page. Guide: `PLAN-AND-FOLDOUTS.md`. |
| `partitor rebuild ID [part ...]` | Build. With names or numbers: only those parts or groups. |
| `partitor repage ID [part ...]` | New page breaks from the saved lines. |
| `partitor rename ID`, `reid ID` | Folder name follows title and composer; old id to new format. |
| `partitor pieces`, `detect`, `build` `FILE` | Work on one PDF in the work folder, without a library. |
| `partitor --version`, `--wrapper-version`, `--help` | Versions and help. |
| `partitor-init`, `partitor-install` | Guided setup; installer (`INSTALL.md`). |
| `partitor --sandbox-check [--library]` | Self-test. |

`ID` is the serial number shown in the menu (`12`) or the full id
(`2026-10-0012`).

## The work folder (no library)

```bash
sudo install -o partitor -g partitor -m 0640 score.pdf /var/lib/partitor/work/
sudo sh -c 'cd /var/lib/partitor/work && partitor detect score.pdf && partitor build score.pdf'
```

The wrapper refuses paths outside `/var/lib/partitor/work`.

## Settings

See `INSTALL.md` (settings file) and `SANDBOX.md` (limits). Piece settings are
the `set` keys (`DESIGN.md` §3 and §6.2).

## Normal work

- **Copy PDFs into `inbox/`** without root, if you are in the group `partitor`
  (local library) or through your NAS tools (SMB library).
- **Take parts** from `library/<id>-<slug>/parts/` (`LIBRARY-LAYOUT.md`).
- **Back up** the library folder. The host holds code and settings only.
- **Build time**: minutes for a long score. The run has a time limit
  (`PARTITOR_RUNTIME_MAX`, default 3600 s) and runs at low priority.

## Change the paper or the staff size of one part

Use this when a part prints too small, or on the wrong paper. Example: item 3,
part Trombones, Letter paper.

1. Show the options: `partitor plan 3 Trombones --all`.
2. Read the table (`PLAN-AND-FOLDOUTS.md`). Each row is a paper and a staff
   size. `pages` is the page count of that row. Pick a row with `bad` = 0 and
   `fold-out` = 0 if you can. Note its number `N`.
3. Choose the row: `partitor plan 3 Trombones N`. This saves paper, staff size,
   re-flow and the page limit for that part. It does not build.
4. Build: `partitor rebuild 3`.

Do not set `pages` by hand. Step 3 sets it to the page count of the row plus
two spare pages.

Why the page limit matters: a part with several staves per line (a group, for
example three trombones) grows fast with the staff size. The build keeps the
page count at or below the limit and shrinks the staff to do it. A small
limit gives a small staff, for example 4 mm. When the build prints
`page budget N`, the staff size follows from N. To get a bigger staff, choose
a row with more pages. The numbers in `plan` are estimates. The build gives
the real numbers.

## Problems

| You see | Do |
|---|---|
| `run as root` | Use `sudo partitor`. |
| `library folder not reachable` | Local: run `partitor-install`; check `inbox/` and `library/` exist. SMB: `STORAGE-SMB.md`, check the NAS and `systemctl status <unit>.automount`. |
| `venv not found`, `engine not found` | Run `sudo /opt/partitor/bin/partitor-install`. |
| `path outside /var/lib/partitor/work` | Copy the PDF into the work folder first. |
| A run stops after an hour | Raise `PARTITOR_RUNTIME_MAX`. |
| Killed during a detect or a build (out of memory) | Lower `PARTITOR_JOBS` or raise `PARTITOR_MEMORY_MAX`. |
| A `build` is slow although only the layout changed | The first `detect` or `build` of a PDF fills `cache/` in the item folder; later ones read it (`analysis cache: N of M page(s) found`). A new PDF, a new dpi, a change of the analysis code or of the cv2, numpy, pymupdf or tesseract version analyses again. `PARTITOR_CACHE=0` turns it off; `rm -r cache/` is safe. |
| A part prints with a very small staff (4 mm) | The page limit is too low. See "Change the paper or the staff size of one part". |
| Wrong parts or bar numbers | `KNOWN-LIMITS.md`; correct in the item menu; check the proof PDF. |

An interrupted build leaves the previous `parts/` set in place; a build that
stopped during the swap is recovered at the next run.
