<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
<!-- Copyright (C) 2026 Nathan Wilkes and partitor contributors -->
# Releases and versions

partitor follows [Semantic Versioning 2.0.0](https://semver.org). This page says
what that means here.

## The public surface

A change to one of these is a change of the public surface:

- the commands, options and menu keys (`docs/COMMANDS.md`, `docs/cli.json`);
- the settings keys and their values;
- the folder and file-name contract (`docs/LIBRARY-LAYOUT.md`);
- the sources of the operator guide (`docs/operator/README.md`);
- the platform hook API (`lib/partitor/hooks.py`).

The text of a message, the look of a proof and the layout of a part are not
public surface. A change there is a fix or a feature by its size.

## Which number rises

| Change | Number | Example |
|---|---|---|
| Fix with no change to the public surface | PATCH | 0.10.1 |
| New command, option, key, setting or document; a visible change of a message | MINOR | 0.10.0 |
| A change that breaks the public surface (remove or rename; a changed meaning) | MAJOR; before 1.0.0, MINOR and marked `BREAKING` | 1.0.0 |

Before 1.0.0 the surface may change at a MINOR release. Mark every such change
`BREAKING` in `CHANGELOG.md`. The version 1.0.0 is for the day the surface is
stable; from then on a break needs a MAJOR number.

A PATCH release never adds to the surface. When a fix needs a new option, it is a MINOR release.

## Pre-releases (beta)

A version that is not ready for everyone is a pre-release:

```
0.10.0-beta.1   0.10.0-beta.2   0.10.0-rc.1   0.10.0
```

- The suffix is `-beta.N` or `-rc.N`. SemVer orders them below `0.10.0`.
- A pre-release is a GitHub Release with the pre-release flag set. A stable release has no suffix and no flag.
- `main` is the development line. It always carries the next version in `VERSION`.
- A pre-release has the same gates as a stable one. Only the promise differs: the surface may still change before the stable tag.
- A tag is never moved and never reused. A defect in a tag is fixed by a new tag.

## What a tag must contain

The gate `tools/check-repo.sh` fails when one of these is wrong:

- `VERSION`, `lib/partitor/__init__.py`, the tag example in `README.md` and `docs/INSTALL.md`, and the newest release in `CHANGELOG.md` carry the same version;
- `docs/COMMANDS.md` and `docs/cli.json` match the code;
- `docs/operator-flow.html` matches `docs/operator/`.

The tag has no `v`. It is annotated. The tag points to the commit that passed CI.

## Procedure

The steps are in the maintainer's release procedure. In short: green CI on `main`, release edit (version, CHANGELOG heading,
generated docs), all gates on the final tree, one release commit, push, wait for CI, push the tag, read the draft release,
publish it. Windows is separate: the setup program is built with the manual workflow only when someone needs it.

## Release notes

- The notes of a release are its section in `CHANGELOG.md` (`## X.Y.Z — date`), written for users. Commit messages are not used.
- After CI succeeds for a pushed tag, `.github/workflows/release.yml` makes a **draft** release with those notes (`tools/release-notes.py TAG`). A tag with a suffix (`0.19.0-beta.1`) is flagged as a pre-release. A release that exists is not changed.
- The tool fails, and no release is made, when the CHANGELOG has no section for the tag, the section is empty, or `VERSION` differs from the tag. Read the draft, then publish it on GitHub.
- To see the notes before you tag: `tools/release-notes.py <version>`.

## Windows builds

- A Windows setup program is built on request, never by a tag. The workflow `windows-release` is started by hand with an existing tag (`platforms/windows/README.md`). Windows has no users now, and an automatic build would only use runner time on every tag.
- The setup file is an asset of the release of the same tag. There is no separate Windows tag or release.
- A stable release keeps its Windows assets, so that the download links stay valid. The site links the newest stable release only. A release without a Windows asset shows no Windows download.
- A tag or a release is never deleted for this (R9). Only the Windows assets of a pre-release may be removed with `gh release delete-asset`.

## Gates by kind of change

CI runs the full test suite on every push. The local gate depends on what the change touches.

| Change | Local gate | Tag |
|---|---|---|
| Only `README.md`, `CHANGELOG.md`, `VERSION`, `docs/` and the version line of `lib/partitor/__init__.py` | `tools/doc-gate.sh` (about 1 minute): the tests that read docs, and `tools/check-repo.sh` | After green CI on the commit |
| Anything under `lib/`, `tests/` or `tools/`, or a change to the help text (it changes `docs/cli.json` and `docs/COMMANDS.md`) | The full suite, `bash -n` and `shellcheck` for Bash, and the G0 checks | After green CI on the commit |

`tools/doc-gate.sh` refuses a change outside the first row. `tests/test_ci.py` checks that every test that reads `docs/` is on its list.

## Websites and other readers

A reader that shows "the current version" uses the newest stable release. It may offer the newest pre-release as a separate
choice. It reads the documents at the tag, not at `main`.
