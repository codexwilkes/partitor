<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
<!-- Copyright (C) 2026 Nathan Wilkes and partitor contributors -->
# Contributing

Helpful pull requests are welcome. The maintainer supports what he can test:
Ubuntu LTS on x86-64 with systemd. Other platforms are best effort.

## Rules

- **One change, one pull request.** Say what and why.
- **CHANGELOG.md**: every code change gets an entry under the next version
  (SemVer). Mark breaking changes `BREAKING`. A change to `docs/LIBRARY-LAYOUT.md`
  goes under "Library layout".
- **Tests**: every code change has tests. The number of tests must not fall.
  Compare counts in the same environment: corpus tests need your own PDFs and
  skip without them.
- **Docs match the code.** A document that contradicts the code is a defect.
  When you change behaviour, search `README.md` and `docs/` for the old text and
  fix it in the same pull request.
- **SPDX header** in every file under `bin/`, `lib/`, `tests/`, `tools/`:
  `SPDX-License-Identifier: AGPL-3.0-or-later`. Your contribution is under the
  same licence.
- **No scores, scans or personal data** in the repository, not even one page.
  Tests draw synthetic PDFs. `tools/check-repo.sh` checks this.
- **No private addresses or host names** in code, docs or tests. Use
  `192.0.2.x` or `example.net` for examples.
- **Section numbers** in `docs/DESIGN.md` are stable: the code cites them. Add
  new text as a new subsection.
- Keep English plain and short.

## Run the checks

CI (`.github/workflows/ci.yml`) runs the same checks on every pull request:
the repo gate, shellcheck at warning level, and the tests on Ubuntu 24.04
(Python 3.12 and 3.13). The macOS run is best effort and does not block.

```bash
cd /opt/partitor      # or your clone
venv/bin/python3 -m unittest discover -s tests -v
tools/check-repo.sh                           # also runs tools/check-modules.py --static
shellcheck -S warning bin/partitor bin/partitor-init bin/partitor-install tools/check-repo.sh tools/bench-start.sh   # if installed
```

While you work, run only the tests of the files you touch, for example
`venv/bin/python3 -m unittest -v tests/test_clef.py`. Run the full suite before
you open the pull request.

Corpus tests (slow): `PARTITOR_CORPUS=/path/to/folder venv/bin/python3 -m
unittest -v tests/test_analysis.py`. The folder holds your own PDFs with the
names in the `CORPUS` table of `tests/test_analysis.py`.

For a refactor of the engine, record and check golden renders with
`tools/g0_golden.py` (`DESIGN.md` §10).

## Where does my change go

The engine is one script today (`lib/partitor-engine`). It is moving, step by step, into
the package `lib/partitor/` (`DESIGN.md` §12). Until a module exists, its code is in the
script. The target modules and their import levels:

| Lvl | Module | Put here |
|---|---|---|
| 0 | `console` | Output, colours, prompts |
| 0 | `config` | Tunables, defaults, name helpers |
| 0 | `model` | Data classes |
| 0 | `typography` | Fonts, text measure |
| 0 | `mapping` | Staff label to part map |
| 0 | `bars` | Bar numbers, barline edits |
| 1 | `vision` | Page render, staff and system detect, OCR |
| 1 | `clef` | Clef signature, ambitus |
| 1 | `parallel` | `fork_map`, job sizing |
| 1 | `reflow` | Re-flow of strips |
| 1 | `strips` | Strip build, bar marks, rehearsal boxes |
| 2 | `ownership` | Ink ownership, safety gate |
| 2 | `lines` | Line fitting, multi-bar rests, saved lines |
| 3 | `analysis` | Page loop, preview |
| 3 | `render` | Paper, packing, part drawing |
| 4 | `library` | Item folder, ids, load and save |
| 5 | `build` | `pieces`, `detect`, `build` |
| 5 | `proof` | Proof PDF |
| 6 | `cli_common` | Shared CLI helpers |
| 7 | `cli_bars` | `bars` command |
| 7 | `cli_parts` | `parts`, `groups` commands |
| 8 | `cli_items` | Item commands |
| 9 | `cli_main` | Menu, `main` |

Rules (`tools/check-modules.py` checks them; CI runs it):

- A module imports only from a **strictly lower** level, never in a cycle. Every module
  starts with `from __future__ import annotations` and the SPDX line.
- **R1:** use state that other modules change, and every name in `tests/patchable.txt`,
  as `module.NAME`. Do not write `from module import NAME`: it makes a copy, and a test
  patch or a rebinding then changes only the owner. `global NAME` is allowed only for a
  name that the same module defines.
- **A new patchable name:** when a test replaces a name with `mock_attr` or an
  assignment on `pt`, add the name to `tests/patchable.txt` (one per line) in the same
  change, and make the readers use `module.NAME`.
- At most 1 100 definition lines per module.

Commands:

```bash
python3 tools/check-modules.py --static     # the rules above; no package needed
venv/bin/python3 tools/check-modules.py --import   # each module imports alone
python3 tools/check-modules.py --affected clef     # modules that import clef, and the tests to run
```

`--affected` prints the modules that import the module (also through other modules)
and the test files of those modules and of the module itself (`tools/modules.txt`);
`*` means all tests.

## Version

The version is in `lib/partitor/__init__.py` (the engine reads it) and in the file
`VERSION` (the wrapper and the installer read it). A test checks that they agree.
The maintainer sets it at release.

## Support

Best effort. The maintainer does not log in to your systems. Open an issue with
the output of `partitor --version`, your Ubuntu version, and the failing line.
Security problems: `SECURITY.md`.
