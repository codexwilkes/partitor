# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""Build-time helpers of the Windows installer (platforms/windows/README.md, "Installer").

Used by build-windows.py. They pin Tesseract and its language data by SHA-256, so every build and
every installed copy has the same OCR program. Only the standard library is used. The functions that
touch the network or run programs take the work as arguments, so tests can run them on Linux."""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import urllib.request
from pathlib import Path

TESSERACT_VERSION = "5.4.0.20240606"
TESSERACT_URL = ("https://digi.bib.uni-mannheim.de/tesseract/"
                 f"tesseract-ocr-w64-setup-{TESSERACT_VERSION}.exe")
TESSERACT_SHA256 = "c885fff6998e0608ba4bb8ab51436e1c6775c2bafc2559a19b423e18678b60c9"

# tessdata_fast 4.1.0: the same file as the Ubuntu package tesseract-ocr-eng 1:4.1.0-2.
# English only: partitor calls Tesseract without -l (lib/partitor/vision.py ocr_line), so no other language is used.
TESSDATA_URL = "https://github.com/tesseract-ocr/tessdata_fast/raw/4.1.0/{lang}.traineddata"
TESSDATA_SHA256 = {
    "eng": "7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2",
}
INNO_VERSION = "6.7.3"
# The Tesseract server answers 403 to the default Python User-Agent.
USER_AGENT = "partitor-build"


class BundleError(RuntimeError):
    """A pinned file does not match, or a step failed."""


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def fetch(url: str, dest: Path, sha256: str, opener=urllib.request.urlopen) -> Path:
    """fetch url to dest and check sha256. A cached file with the right hash is kept. A file with
    a wrong hash is deleted and BundleError is raised: it is never used."""
    if dest.is_file() and sha256_of(dest) == sha256:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with opener(req) as resp, open(tmp, "wb") as out:
        shutil.copyfileobj(resp, out)
    got = sha256_of(tmp)
    if got != sha256:
        tmp.unlink()
        raise BundleError(f"{url}: SHA-256 is {got}, expected {sha256}")
    os.replace(tmp, dest)
    return dest


def find_7z(env=os.environ, which=shutil.which) -> str | None:
    """7-Zip (7z.exe): Program Files, then per-user, then PATH."""
    for key, sub in (("ProgramFiles", "7-Zip"), ("ProgramFiles(x86)", "7-Zip"),
                     ("LOCALAPPDATA", "Programs/7-Zip")):
        if env.get(key):
            cand = Path(env[key]) / sub / "7z.exe"
            if cand.is_file():
                return str(cand)
    return which("7z") or which("7zz")


def prune(stage: Path) -> None:
    """Keep what OCR needs: tesseract.exe, the DLLs, tessdata, and the licence files. Drop the training
    tools, the manuals, the Java files and the parts of the installer (about 200 MB)."""
    for path in list(stage.iterdir()):
        name = path.name
        keep = (name == "tesseract.exe" or name.lower().endswith(".dll") or name == "tessdata"
                or name == "doc")
        if not keep:
            shutil.rmtree(path) if path.is_dir() else path.unlink()
    for path in list((stage / "doc").glob("*")):
        if path.name not in ("LICENSE", "AUTHORS"):
            shutil.rmtree(path) if path.is_dir() else path.unlink()
    for path in (stage / "tessdata").glob("*.jar"):
        path.unlink()


def stage_tesseract(cache: Path, stage: Path, sevenzip: str, run=subprocess.run,
                    opener=urllib.request.urlopen) -> Path:
    """Put the pinned Tesseract and the English language file into stage (the folder `tesseract` of
    the program folder). The NSIS installer of Tesseract is opened as an archive with 7-Zip; it is
    never run, so no administrator rights are needed and nothing is installed on this machine.
    Returns stage."""
    setup = fetch(TESSERACT_URL, cache / "tesseract-setup.exe", TESSERACT_SHA256, opener)
    shutil.rmtree(stage, ignore_errors=True)
    stage.parent.mkdir(parents=True, exist_ok=True)
    run([sevenzip, "x", "-y", f"-o{stage}", str(setup)], check=True, capture_output=True)
    exe = stage / "tesseract.exe"
    if not exe.is_file():
        raise BundleError(f"unpacking the Tesseract installer did not make {exe}")
    prune(stage)
    (stage / "tessdata").mkdir(exist_ok=True)
    for lang, digest in TESSDATA_SHA256.items():
        fetch(TESSDATA_URL.format(lang=lang), cache / f"{lang}.traineddata", digest, opener)
        shutil.copy2(cache / f"{lang}.traineddata", stage / "tessdata" / f"{lang}.traineddata")
    return stage


def check_tesseract(stage: Path, run=subprocess.run) -> None:
    """The staged program runs, has the pinned version and lists the English language."""
    out = run([str(stage / "tesseract.exe"), "--list-langs"], check=True, capture_output=True,
              text=True, env={**os.environ, "TESSDATA_PREFIX": str(stage / "tessdata")}).stdout
    missing = sorted(set(TESSDATA_SHA256) - set(out.split()))
    if missing:
        raise BundleError(f"staged tesseract lacks languages: {', '.join(missing)}")
    ver = run([str(stage / "tesseract.exe"), "--version"], check=True, capture_output=True,
              text=True).stdout.splitlines()[0]
    if TESSERACT_VERSION.rsplit(".", 1)[0] not in ver:
        raise BundleError(f"staged tesseract is {ver!r}, expected {TESSERACT_VERSION}")


def find_iscc(env=os.environ, which=shutil.which) -> str | None:
    """The Inno Setup compiler: per-user install, then Program Files, then PATH."""
    cands = [Path(env.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
             Path(env.get("ProgramFiles(x86)", "")) / "Inno Setup 6" / "ISCC.exe",
             Path(env.get("ProgramFiles", "")) / "Inno Setup 6" / "ISCC.exe"]
    for c in cands:
        if c.name == "ISCC.exe" and c.parent.name and c.is_file():
            return str(c)
    return which("ISCC")
