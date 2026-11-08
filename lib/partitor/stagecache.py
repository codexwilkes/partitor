# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""Stage cache: the PageResult of a page, stored in the item folder (cache/).

`detect` and `build` run the same page analysis. An entry is keyed by every
input of the analysis (DESIGN.md §12.4). A read that fails is a miss, never
an error and never a wrong result."""
from __future__ import annotations

import ast
import gzip
import hashlib
import os
import pickle
import subprocess
from pathlib import Path

from . import VERSION, config, vision
from .console import _note
from .model import PageResult, Staff

ANALYSIS_CACHE_FORMAT = 1
CACHE_DIR = "cache"
CACHE_SUFFIX = ".pcache"
CACHE_ENV = "PARTITOR_CACHE"

_PKG = Path(__file__).resolve().parent
_CACHE_NP_OK = {"_reconstruct", "ndarray", "dtype", "scalar", "_frombuffer"}


class _CacheUnpickler(pickle.Unpickler):
    """Only the data classes of the analysis, numpy arrays and a few builtins."""

    def find_class(self, module: str, name: str):
        if module == Staff.__module__ and name in ("Staff", "PageResult"):
            return {"Staff": Staff, "PageResult": PageResult}[name]
        if module.split(".")[0] == "numpy" and name in _CACHE_NP_OK:
            return super().find_class(module, name)
        if module == "builtins" and name in ("set", "frozenset", "slice", "complex"):
            return super().find_class(module, name)
        raise pickle.UnpicklingError(f"not allowed in a cache file: {module}.{name}")


def cache_enabled() -> bool:
    """PARTITOR_CACHE=0 (or off, no, false) turns the cache off."""
    return os.environ.get(CACHE_ENV, "1").strip().lower() not in ("0", "off", "no", "false")


def analysis_modules(root: str = "ownership") -> list[str]:
    """analysis_modules -> sorted names of the package modules that the page
    analysis can reach: the closure of the relative imports of `root`."""
    seen: set[str] = set()
    todo = [root]
    while todo:
        name = todo.pop()
        if name in seen or not (_PKG / f"{name}.py").is_file():
            continue
        seen.add(name)
        tree = ast.parse((_PKG / f"{name}.py").read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level == 1:
                if node.module:
                    todo.append(node.module.split(".")[0])
                else:
                    todo.extend(a.name for a in node.names)
    return sorted(seen)


def source_hash() -> str:
    """source_hash -> hash of the code that decides the pixels, so a code
    change without a version bump cannot give a stale hit."""
    h = hashlib.sha256()
    for name in analysis_modules():
        h.update(name.encode() + b"\0" + (_PKG / f"{name}.py").read_bytes() + b"\0")
    return h.hexdigest()


def tesseract_id() -> str:
    """tesseract_id -> path and version line of tesseract, 'none' when missing."""
    path = vision._TESS["path"]
    if path is None:
        return "none"
    try:
        r = subprocess.run([path, "--version"], capture_output=True, timeout=30)
        ver = (r.stdout or r.stderr).decode("utf-8", "replace").splitlines()[:1]
    except (OSError, subprocess.TimeoutExpired):
        ver = ["?"]
    return f"{path} {' '.join(ver)} tessdata={os.environ.get('TESSDATA_PREFIX', '')}"


def environment_id() -> str:
    """environment_id -> what can change pixels or text: the format, the analysis
    source and the versions of the libraries and of tesseract. Not the release
    number: a release that leaves the analysis code alone keeps the cache."""
    import cv2
    import numpy
    import pymupdf
    return "|".join([f"format={ANALYSIS_CACHE_FORMAT}", f"src={source_hash()}",
                     f"cv2={cv2.__version__}", f"numpy={numpy.__version__}",
                     f"pymupdf={pymupdf.version[0]}", f"tesseract={tesseract_id()}"])


class StageCache:
    """One cache folder for one source PDF, dpi and OCR setting."""

    def __init__(self, folder: Path, pdf_sha: str, dpi: int, ocr: bool, env: str) -> None:
        self.folder = folder
        self.base = f"{pdf_sha}|dpi={dpi}|ocr={int(ocr)}|{env}"
        self._noted = False

    def key(self, pno: int, sys_base: int, joins: tuple[int, ...] = ()) -> str:
        """key -> hash of every input of analyse_page for this page. The
        page header limit is read now: detect and build set it first. joins
        (the operator's system joins on this page) are part of the key only
        when there are some, so a page without them keeps its entry."""
        raw = f"{self.base}|page={pno}|sys_base={sys_base}|" \
              f"header_sp={config.TUNE['page_header_sp']!r}"
        if joins:
            raw += f"|joins={','.join(str(j) for j in sorted(joins))}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def path(self, pno: int, sys_base: int, joins: tuple[int, ...] = ()) -> Path:
        return self.folder / f"p{pno + 1:04d}-{self.key(pno, sys_base, joins)[:32]}{CACHE_SUFFIX}"

    def present(self, pages: list[int], sys_base: int = 0,
                joins: "dict[int, tuple[int, ...]] | None" = None) -> int:
        """present -> how many of the pages have an entry for the current key."""
        return sum(1 for p in pages
                   if self.path(p, sys_base, (joins or {}).get(p, ())).is_file())

    def _note_once(self, text: str) -> None:
        if not self._noted:
            self._noted = True
            _note(text)

    def get(self, pno: int, sys_base: int, joins: tuple[int, ...] = ()) -> PageResult | None:
        """get -> the stored PageResult, or None (a miss)."""
        path = self.path(pno, sys_base, joins)
        if not path.is_file():
            return None
        try:
            with gzip.open(path, "rb") as f:
                d = _CacheUnpickler(f).load()
            if not isinstance(d, dict) or d.get("format") != ANALYSIS_CACHE_FORMAT \
               or d.get("key") != self.key(pno, sys_base, joins) \
               or not isinstance(d.get("result"), PageResult):
                raise ValueError("wrong format or key")
            return d["result"]
        except (OSError, EOFError, pickle.UnpicklingError, AttributeError, ValueError,
                ImportError, IndexError, TypeError, KeyError) as e:
            self._note_once(f"cache:  page {pno + 1}: entry not used ({type(e).__name__}); "
                            "analysed again")
            try:
                path.unlink()
            except OSError:
                pass
            return None

    def put(self, pno: int, sys_base: int, res: PageResult, joins: tuple[int, ...] = ()) -> None:
        """put: write the entry (temp name, then rename) and remove the other
        entries of this page. A write that fails is skipped, with one note."""
        path = self.path(pno, sys_base, joins)
        tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            payload = {"format": ANALYSIS_CACHE_FORMAT, "key": self.key(pno, sys_base, joins),
                       "version": VERSION, "result": res}
            with gzip.GzipFile(tmp, "wb", compresslevel=1) as f:
                pickle.dump(payload, f, protocol=pickle.HIGHEST_PROTOCOL)
            os.replace(tmp, path)
            for old in self.folder.glob(f"p{pno + 1:04d}-*{CACHE_SUFFIX}"):
                if old != path:
                    old.unlink(missing_ok=True)
        except OSError as e:
            self._note_once(f"cache:  not written ({e.__class__.__name__}); continuing")
            try:
                tmp.unlink()
            except OSError:
                pass


def open_cache(out: Path, pdf_sha: str, dpi: int, ocr: bool = True) -> StageCache | None:
    """open_cache -> the cache of the item folder `out`, None when switched off."""
    if not cache_enabled():
        return None
    return StageCache(Path(out) / CACHE_DIR, pdf_sha, dpi, ocr, environment_id())
