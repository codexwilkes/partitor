<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
<!-- Copyright (C) 2026 Nathan Wilkes and partitor contributors -->
# partitor

Make instrument parts from a score PDF.

Give partitor a PDF of a score, vector or scanned. It finds the staves and
systems, asks you which staff is which part, and writes one PDF per part, in
large print if you want it: big staves, a calm layout, page turns at rests,
bar numbers, rehearsal marks. It was made for amateur players with older eyes.

Status: first public release line (0.4). It works for the author, on one setup. Read
`docs/KNOWN-LIMITS.md` before you rely on it.

## Scope

- **In:** analysis of a score PDF, mapping staves to parts, layout, build, a
  text menu (works over SSH, also from a phone), a local or SMB library.
- **Out:** publishing, sync, a web interface, accounts, cloud storage, notation
  export (MusicXML, MIDI).

If you write your own publishing, use the documented, stable file layout
(`docs/LIBRARY-LAYOUT.md`). `docs/OVERLAYS.md` has an unsupported sample.

## What you need

- Ubuntu 26.04 LTS with systemd (the tested platform).
- Root access. The engine itself never runs as root (`docs/SANDBOX.md`).
- A score PDF that you have the right to copy. This repository has **no** sample
  scores.

## Quick start (local library)

```bash
sudo apt install git python3-venv tesseract-ocr
sudo git clone https://github.com/codexwilkes/partitor /opt/partitor
cd /opt/partitor && sudo git checkout --detach 0.4.0
sudo bin/partitor-init                      # guided; --yes takes the defaults
sudo usermod -aG partitor "$USER"          # log in again afterwards
cp score.pdf /var/lib/partitor/library/inbox/
sudo partitor
```

The menu offers "new from inbox". `docs/operator-flow.html` walks through a piece
from start to build. `docs/INSTALL.md` has the details, the upgrade and the
removal.

## Documents

| File | About |
|---|---|
| `docs/INSTALL.md` | Install, settings, upgrade, uninstall |
| `docs/STORAGE-LOCAL.md`, `docs/STORAGE-SMB.md` | Where the library lives; NAS setup |
| `docs/OPERATING.md`, `docs/operator-flow.html` | Daily use |
| `docs/SANDBOX.md`, `SECURITY.md` | What the sandbox does; reporting problems |
| `docs/LIBRARY-LAYOUT.md` | The stable folder and file-name contract |
| `docs/KNOWN-LIMITS.md` | What the engine gets wrong |
| `docs/DESIGN.md` | Rules and algorithms |
| `docs/OVERLAYS.md` | Wrap the installer for a site |
| `CONTRIBUTING.md`, `CHANGELOG.md`, `NOTICE` | Contributing, history, third-party licences |

## Platforms

- **Ubuntu LTS with systemd:** supported as far as the author can test it
  (26.04). Ubuntu 24.04: the pinned packages install as binary wheels on
  Python 3.12 and the tests pass there (checked on CPython 3.12.3; the
  installer itself is not run on 24.04 yet).
- **macOS:** not in this release. A mode without the sandbox is planned, as
  community best effort.

## Support

Best effort. Issues and helpful pull requests are welcome. The author does not
log in to other people's systems. Contact: partitor@codexwilkes.com.
Vulnerabilities: `SECURITY.md`.

## Licence

AGPL-3.0-or-later (`LICENSE`). Third-party parts: `NOTICE`. The scores you
process are yours; their copyright is not touched by this licence.
