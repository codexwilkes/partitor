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
tools/check-repo.sh
shellcheck bin/partitor bin/partitor-init bin/partitor-install tools/check-repo.sh   # if installed
```

Corpus tests (slow): `PARTITOR_CORPUS=/path/to/folder venv/bin/python3 -m
unittest -v tests/test_partitor.py`. The folder holds your own PDFs with the
names in the `CORPUS` table of `tests/test_partitor.py`.

For a refactor of the engine, record and check golden renders with
`tools/g0_golden.py` (`DESIGN.md` §10).

## Version

One version for engine, wrapper and installer: the file `VERSION`. A test checks
that they agree. The maintainer sets it at release.

## Support

Best effort. The maintainer does not log in to your systems. Open an issue with
the output of `partitor --version`, your Ubuntu version, and the failing line.
Security problems: `SECURITY.md`.
