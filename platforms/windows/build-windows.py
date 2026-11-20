# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""Build the experimental Windows console program and its installer (platforms/windows/README.md).

Run it with the Windows Python, from the root of a copy of the repository on a Windows drive
(not a \\\\wsl$\\ path):   py -3.12 platforms\\windows\\build-windows.py

Steps: make the venv `build-venv`, install requirements.txt and a pinned PyInstaller,
build the folder dist/partitor/ (partitor.exe), copy LICENSE and write SOURCE.txt.
With --installer: also fetch the pinned Tesseract and language data (SHA-256 checked, installer/bundle.py),
put them in dist/partitor/tesseract/, and make dist/partitor-<version>-setup.exe with Inno Setup.
Only the standard library is used here. Exit codes: 0 ok; 1 a step failed; 2 not Windows."""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

PYINSTALLER = "pyinstaller==6.16.0"
SOURCE_URL = "https://github.com/codexwilkes/partitor"
ROOT = Path(__file__).resolve().parents[2]       # repository root (this file: platforms/windows/)
sys.path.insert(0, str(Path(__file__).resolve().parent / "installer"))
import bundle  # noqa: E402


def run(cmd: list[str]) -> None:
    print("+", " ".join(cmd), flush=True)
    if subprocess.run(cmd, cwd=ROOT).returncode:
        sys.exit(1)


def build_installer(out: Path) -> Path:
    """Stage Tesseract into out/tesseract, then compile installer/partitor.iss. Returns the setup file."""
    iscc = bundle.find_iscc()
    if iscc is None:
        print(f"build-windows: Inno Setup {bundle.INNO_VERSION} not found "
              "(winget install --id JRSoftware.InnoSetup -e)", file=sys.stderr)
        sys.exit(1)
    sevenzip = bundle.find_7z()
    if sevenzip is None:
        print("build-windows: 7-Zip not found (winget install 7zip.7zip -e)", file=sys.stderr)
        sys.exit(1)
    try:
        bundle.stage_tesseract(ROOT / "build-cache", out / "tesseract", sevenzip)
        bundle.check_tesseract(out / "tesseract")
    except (bundle.BundleError, OSError, subprocess.SubprocessError) as e:
        print(f"build-windows: {e}", file=sys.stderr)
        sys.exit(1)
    version = (ROOT / "VERSION").read_text().strip()
    run([iscc, f"/DAppVersion={version}", f"/DDistDir={out}",
         str(ROOT / "platforms" / "windows" / "installer" / "partitor.iss")])
    return ROOT / "dist" / f"partitor-{version}-setup.exe"


def main() -> int:
    ap = argparse.ArgumentParser(description="Build partitor.exe for Windows")
    ap.add_argument("--installer", action="store_true", help="also build the setup program (Inno Setup)")
    args = ap.parse_args()
    if os.name != "nt":
        print("build-windows: run this with the Windows Python", file=sys.stderr)
        return 2
    venv = ROOT / "build-venv"
    if not venv.exists():
        run([sys.executable, "-m", "venv", str(venv)])
    py = str(venv / "Scripts" / "python.exe")
    run([py, "-m", "pip", "install", "-r", "requirements.txt", PYINSTALLER])
    run([py, "-m", "pip", "freeze"])                       # records the versions in the log
    for d in ("build", "dist"):
        shutil.rmtree(ROOT / d, ignore_errors=True)
    sep = os.pathsep                                        # ';' on Windows
    run([py, "-m", "PyInstaller", "--noconfirm", "--clean", "--console", "--name", "partitor",
         "--icon", "platforms/windows/installer/partitor.ico",
         "--paths", "lib", "--paths", "platforms/windows",
         "--add-data", f"share/fonts{sep}fonts",           # typography.font_dirs: <package folder>/fonts
         "--add-data", f"lib/partitor/*.py{sep}partitor",  # stagecache hashes the source files
         "--add-data", f"VERSION{sep}.",
         "--exclude-module", "tkinter",
         "platforms/windows/partitor_windows/__main__.py"])
    out = ROOT / "dist" / "partitor"
    shutil.copy2(ROOT / "LICENSE", out / "LICENSE")
    (out / "SOURCE.txt").write_text(
        f"partitor is free software under AGPL-3.0-or-later.\nSource: {SOURCE_URL}\n"
        f"Version: {(ROOT / 'VERSION').read_text().strip()}\n", encoding="utf-8")
    print(f"build-windows: ok  {out / 'partitor.exe'}")
    if args.installer:
        print(f"build-windows: ok  {build_installer(out)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
