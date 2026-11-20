<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
<!-- Copyright (C) 2026 Nathan Wilkes and partitor contributors -->
# Windows

**Experimental. Not supported.** This is a spike. Linux is the supported system (`INSTALL.md`).

## What works

- A console program `partitor.exe` with the same commands as on Linux.
- The commands that take a score from PDF to parts (`new`, `detect`, `build`) on a vector score
  and on a scan. Scans need an installed tesseract.
- Colour and UTF-8 output in Windows Terminal.

Test status: the tests in `platforms/windows/tests/` run on Linux with mocks (`tests/test_packs.py`
loads them). The program itself has had a short smoke test.

## Limits

- **One job.** No fork on Windows. `--jobs` has no effect. A run gives one `jobs:` warning.
  Detect and build are slower than on Linux.
- **No sandbox.** The program runs with your rights. Do not use it on PDFs you do not trust
  (`SANDBOX.md`).
- **No item lock.** Do not run two partitor commands on the same item.
- **Not signed.** Windows SmartScreen may show "Windows protected your PC" for the installer and
  for `partitor.exe` (a file you built yourself usually does not). Click "More info", then "Run anyway". Code signing waits until the project
  has donations to pay for it.
- **OCR can differ from Linux.** The installer bundles Tesseract 5.4.0. Linux (Ubuntu 24.04) has
  5.3.4. The language data is the same files. On 2 of 10 real scan pages the two versions read a
  staff label differently (`[I]` against `[II]`, and `fay` against a staff number). Every
  Windows installation has the same OCR, but Windows and Linux may not. Check the staff names in
  `partitor show` after a scan. The program that you build from source uses an installed Tesseract
  (`PATH`, or `C:\Program Files\Tesseract-OCR`), and then the version is yours.
- **Open files.** If a viewer holds a part PDF open, a build stops with one error that names the
  file (or the folder, when the part set moves). Close the file and run the command again.
- **Library.** The default folder is `Documents\partitor`. Set `PARTITOR_LIBRARY` to change it.
- No GUI, no Windows CI.

## Install (users)

Run `partitor-<version>-setup.exe`. It needs no administrator rights.

- The program goes to `%LOCALAPPDATA%\Programs\partitor`. Tesseract and the language data (deu, eng,
  fra, ita, lat, osd) are inside it.
- The wizard asks for the library folder. The default is `Documents\partitor`. A folder on a network
  share also works. The installer makes `inbox` and `library` in it and sets the user variable
  `PARTITOR_LIBRARY`.
- `partitor` is on your PATH (open a new terminal) and the Start menu has an entry that opens the menu.
- **Update:** run the new installer. It replaces the program and keeps your library.
- **Uninstall:** Settings, Apps, partitor. It removes the program, the PATH entry and the variable.
  **It never removes the library.**

## Build the installer (maintainers)

Needs Inno Setup 6 (tested: 6.7.3) and 7-Zip:

```
winget install --id JRSoftware.InnoSetup -e
winget install --id 7zip.7zip -e
```

```
py -3.12 platforms\windows\build-windows.py --installer
```

The script builds the program (below), downloads the Tesseract installer and the language data, checks
each file against the SHA-256 in `installer\bundle.py`, opens the Tesseract installer with 7-Zip into `dist\partitor\tesseract`
(the installer is never run: no administrator prompt, nothing is installed on the build machine), checks that it runs and lists the six languages, then writes
`dist\partitor-<version>-setup.exe`. The pins are `TESSERACT_SHA256` and `TESSDATA_SHA256`; to change
the version, change the pins in the same commit. The language files are the same as the Ubuntu
packages `tesseract-ocr-<lang>` 1:4.1.0-2.

The icon (`installer\partitor.ico`) is made from the neume of the author's logo (`installer\neume.png`).
The design is the author's own. It is here as the icon of partitor; the AGPL licence of the
code does not cover it. `installer\make-icon.py` makes the icon again (needs Pillow).

## Build the program

Use the Windows Python 3.12 (not a `\\wsl$\` path). Copy the repository to a folder on a Windows
drive, then run from that folder:

```
py -3.12 platforms\windows\build-windows.py
```

The script makes a venv, installs `requirements.txt` and a pinned PyInstaller, and builds the
folder `dist\partitor\` with `partitor.exe`. Check it with `dist\partitor\partitor.exe --version`.

## Run from the source tree

In PowerShell, from the root of the repository (Python 3.12 and `requirements.txt` installed):

```
$env:PYTHONPATH = "lib;platforms\windows"
py -3.12 -m partitor_windows --version
```

## Work on the Windows pack

The Windows pack is separate from the engine (`docs/DESIGN.md` §12.6):

- Linux is the primary system. Windows is best effort.
- Change only files in `platforms/windows/`. The engine in `lib/partitor/` has no Windows code.
  A change to the engine is right only when it is better for every system, Linux included; send it
  as its own pull request.
- The pack replaces the hooks in `lib/partitor/hooks.py` (`HOOKS` in `partitor_windows/pack.py`).
  If you need a hook that does not exist, open a separate pull request for the hook only.
- Tests go in `platforms/windows/tests/`. They must run on Linux with mocks: CI runs them there.
- Windows docs go in this folder, not in `docs/`. The folder can then move to its own repository.
- Run the checks of `CONTRIBUTING.md` before a pull request.

## Planned: more than one job

Deferred (2026-11-19). Windows has no fork, so detect and build run one page at a time. On a
14-page score on Linux, 3 jobs instead of 1 made detect 1.6 times and build 1.4 times faster. The
stage cache makes a second run fast without it.

If Windows users need it, the plan is:

- **Engine (small):** split the child and the parent half of `parallel.fork_map` into two functions
  (run one item and collect its output; replay the output in the parent), take a snapshot of the
  worker state (`config.TUNE`, the console mode), and add one hook `spawn_map` (it raises the hook `API`).
  The task functions in `build` and `analysis` do not change, and Linux keeps fork.
- **Pack:** a pool with `multiprocessing` in spawn mode. The tasks are closures, so the pack sends
  them with `cloudpickle` (in the build venv only). Each child installs the pack and the state
  snapshot. `partitor.exe` calls `multiprocessing.freeze_support()`.
- **Costs:** about 1 s start per worker; a render worker gets the strips of its part (about 37 MB
  on the 14-page score).
- **Check:** on Linux, the same build with fork and with the spawn pool gives the same files.

## Source (AGPL)

partitor is under AGPL-3.0-or-later. `dist\partitor\SOURCE.txt` names the source repository. If you
give the program to other people, you must give them the source of the same version.
