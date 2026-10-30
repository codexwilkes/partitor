<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
<!-- Copyright (C) 2026 Nathan Wilkes and partitor contributors -->
# Changelog

Format: [SemVer](https://semver.org). Entries list user-visible changes. The
engine file (`lib/partitor-engine`) keeps the detailed history of the private
development line (0.1.0 to 0.3.0-dev.42) in its header comment.

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
