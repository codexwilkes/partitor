<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
<!-- Copyright (C) 2026 Nathan Wilkes and partitor contributors -->
# partitor

Make instrument parts from a score PDF.

Give partitor a PDF of a score, vector or scanned. It finds the staves and
systems, asks you which staff is which part, and writes one PDF per part. It
was made for amateur players with older eyes: you decide how big the music is,
and the parts are laid out so that you can read them on a stand.

Status: early public release. It works for the author, on one setup. Read
`docs/KNOWN-LIMITS.md` before you rely on it.

## What you get

**Parts you can read**
- One PDF per instrument, from a full score. One part can use two staves
  (a keyboard). A group prints several parts as one small score (three
  trombones). You can join or split parts as you like.
- Large print: big staves and a calm layout. A second, larger copy
  (11 x 17 in, or A3) is made next to the normal one.
- Bar numbers on every line, and the rehearsal marks of the score, so the
  conductor's "from bar 45" works for you too.
- The lowest and highest note of the part is printed on the first line, so you
  can see at once if the part fits your instrument or your voice.
- Multi-bar rests are joined, so systems are shorter and the part has fewer pages.
- Cue lines: a small staff of another voice, or a word such as "Canto", above a
  long rest (`partitor cues`). Nothing is added unless you ask.

**Page turns**
- Pages end where you can rest, not in the middle of a passage. You turn at a
  rest.
- `plan` shows what each paper size (Letter, A4, ledger) and staff size does to
  the page count and the turns, so you can choose before you print.
- When no good turn exists, partitor can make a fold-out: a flap that gives you
  three pages with no turn. It writes a short list of steps to cut, fold and
  tape it.
- You can move a system to the next or the previous page by hand, and the
  choice stays.
- Parts of three pages or more get extra margin at the spine, for a punched or
  bound part, printed double-sided.

**Scores that are not clean**
- Works on vector PDFs and on scans, also phone scans (clean scans work best). It straightens a curled
  page.
- Reads staff labels and clefs, and matches them to the parts, also when the
  staff count changes in the piece.
- Lyrics and text stay with the right staff.
- If the score has one piece after another, or a title above the music, it asks
  and you decide what to leave out.

**You stay in control**
- A text menu that you can use over SSH, also from a phone. No web page, no
  account.
- partitor asks when it is not sure. Nothing is guessed silently.
- A proof PDF shows what partitor read: staves, bars, and the lowest and
  highest notes, so you can check before you print.
- You can correct bar numbers, part names, groups, title and the note range.
  Your corrections stay when you analyse again.
- You can rebuild one part, change its paper or staff size, and print again,
  without a new analysis of the whole score.
- Your scores stay on your own computer or your own NAS. There is no network
  use and nothing is sent anywhere.

## What it does not do

partitor makes parts. It does not publish, sync, run a web interface, keep
accounts, store in the cloud, or export notation (MusicXML, MIDI).

## What you need

- Ubuntu 26.04 LTS with systemd (the tested platform).
- Root access. The engine itself never runs as root (`docs/SANDBOX.md`).
- A score PDF that you have the right to copy. This repository has **no** sample
  scores.

## Quick start (Ubuntu)

Four commands set up everything: the packages, a local library, and access
for you. No questions.

```bash
sudo apt install -y git
sudo git clone https://github.com/codexwilkes/partitor /opt/partitor
cd /opt/partitor && sudo git checkout --detach 0.13.2
sudo bin/partitor-quick-install
```

Then log out and log in again. Copy a score PDF into
`/var/lib/partitor/library/inbox/` and run `sudo partitor`. Choose "new from
inbox"; partitor asks which staff is which part. `docs/operator-flow.html`
walks through a piece from start to build.

A NAS as library, other folders, upgrade and removal: `docs/INSTALL.md`.

## Guides

| File | About |
|---|---|
| `docs/operator-flow.html` | Step by step: from a PDF to printed parts (generated from `docs/operator/guide.md`) |
| `docs/operator/advanced.md` | Less common features: groups, cue lines, bar numbers, paper, page turns |
| `docs/OPERATING.md` | Daily use, commands, problems |
| `docs/PLAN-AND-FOLDOUTS.md` | Paper, staff size, page turns, fold-outs; print and assemble |
| `docs/INSTALL.md` | Install, settings, upgrade, uninstall |
| `docs/STORAGE-LOCAL.md`, `docs/STORAGE-SMB.md` | Where your library lives; NAS setup |
| `docs/KNOWN-LIMITS.md` | What partitor gets wrong |

Developers and people who build on partitor: see `CONTRIBUTING.md`.

## Platforms

- **Ubuntu LTS with systemd:** supported as far as the author can test it
  (26.04). Ubuntu 24.04: the pinned packages install as binary wheels on
  Python 3.12 and the tests pass there (checked on CPython 3.12.3; the
  installer itself is not run on 24.04 yet).
- **Windows:** best effort. An experimental console build with an installer,
  not supported: `platforms/windows/README.md`. The start command for PowerShell
  is in the operator guide (`docs/operator/guide.md`).
- **macOS:** best effort. No installer and no sandbox: you run the engine from
  the source in Terminal. The steps are in `docs/operator/advanced.md`. The tests run on
  macOS in CI, and a failure there does not block a release.

## Support

Best effort. Issues and helpful pull requests are welcome. The author does not
log in to other people's systems. Contact: partitor@codexwilkes.com.
Vulnerabilities: `SECURITY.md`.

## Licence

AGPL-3.0-or-later (`LICENSE`). Third-party parts: `NOTICE`. The scores you
process are yours; their copyright is not touched by this licence.
