<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
<!-- Copyright (C) 2026 Nathan Wilkes and partitor contributors -->
# Changelog

Format: [SemVer](https://semver.org). Entries list user-visible changes. The
engine file (`lib/partitor-engine`) keeps the detailed history of the private
development line (0.1.0 to 0.3.0-dev.42) in its header comment.






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
