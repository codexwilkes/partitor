<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
<!-- Copyright (C) 2026 Nathan Wilkes and partitor contributors -->
# Library layout — the stable contract

Write scripts against this page. Everything else in the library is internal.
A change to this contract is listed in `CHANGELOG.md` under "Library layout"
and needs a minor version at least (a major version after 1.0.0).

## Stable

```
<library>/inbox/                                       PDFs waiting
<library>/library/<id>-<slug>/                         one folder per piece
<library>/library/<id>-<slug>/parts/<file>.pdf         the part files
```

- `<library>` is `PARTITOR_LIBRARY`.
- `<id>` is `YYYY-MM-NNNN` (for example `2026-10-0012`). It never changes
  for a piece. Older items may have `YYYY-NNN`.
- A part file is named `<NN>-<part>-<Composer>-<Title>--<id>.pdf`.
  - `NN`: two digits, the part number in score order. Groups come after the
    parts.
  - The large-print copy adds a suffix before `.pdf`: `-11x17` or `-A3`.
- To find a piece: match the folder by the prefix `<id>-`. To find its part
  files: match `*--<id>.pdf` (normal copy) and `*--<id>-11x17.pdf` /
  `*--<id>-A3.pdf` (large copy).
- Part PDFs are normal PDF files (Letter, A4 or Ledger pages).

## May change without notice

- The slug (the folder name after the id). `partitor rename` changes it when
  the title or composer changes.
- The text between `NN` and `--<id>`: part names, composer and title can be
  corrected by the operator.
- The set of files in `parts/`: an operator can leave parts out, or add
  groups.

## Replaced as a whole

A build writes `parts.new/`, then swaps it for `parts/` with two renames (the
old set goes to `parts.prev/`). So `parts/` is always a complete set, but the
folder is a new directory after each build. A sync script must not keep the
directory open, and must read the folder again after a build. A partial rebuild
(`rebuild ID Trombones`) keeps the other part files in the new set.

## Internal (do not depend on it)

`<id>-score.yaml`, `<id>-source.pdf`, `<id>-proof.pdf`, `lines/`,
`parts.new/`, `parts.prev/`, `work/`, and every key in `score.yaml`.
