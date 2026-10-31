# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""Shared helpers for the engine tests (tests/test_*.py) and for tools/g0_golden.py.

What is here: the loader that makes the engine script importable as `pt`, the package
modules that tests patch or read state from (`config`, `console`, `parallel`; patch the
owner, never a copy: rule R1 in CONTRIBUTING.md), `HAVE_DEPS` and `needs_deps`, the synthetic score and scan drawers
(`make_score_pdf`, `rasterize`), `mock_attr`, and the module fixtures
`setUpModule` and `tearDownModule` (a synthetic logo in PARTITOR_LOGO). A test
file imports the two fixture names from here, so every file runs with a logo.

Import errors: only a missing third-party package (cv2, numpy, pymupdf, yaml)
sets HAVE_DEPS to False and skips the engine tests. An import error of the
engine itself is not caught here: it stops the test run.

Run a test file by its path or with `unittest discover -s tests`; both find
this module, because tests/ is put on sys.path.
"""
import contextlib
import importlib.machinery
import importlib.util
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "lib", "partitor-engine")
LIB = os.path.abspath(os.path.join(HERE, "..", "lib"))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

try:
    import cv2  # noqa: F401
    import numpy as np
    import pymupdf
    import yaml  # noqa: F401
    HAVE_DEPS = True
except ImportError:          # system python without the venv packages
    cv2 = np = pymupdf = yaml = None
    HAVE_DEPS = False

pt = config = console = parallel = None
if HAVE_DEPS:
    if LIB not in sys.path:
        sys.path.insert(0, LIB)          # the loader does not run the file as a script
    pt = sys.modules.get("partitor_mod")  # one engine object per process
    if pt is None:
        _loader = importlib.machinery.SourceFileLoader("partitor_mod", SRC)
        _spec = importlib.util.spec_from_loader("partitor_mod", _loader)
        pt = importlib.util.module_from_spec(_spec)
        sys.modules["partitor_mod"] = pt      # dataclasses look the module up
        try:
            _loader.exec_module(pt)           # an import error here must show
        except BaseException:
            sys.modules.pop("partitor_mod", None)
            raise
    # The same objects the script uses: the package is imported once per process.
    from partitor import config, console, parallel  # noqa: E402,F401

needs_deps = unittest.skipUnless(HAVE_DEPS, "partitor venv packages not installed")

_LOGO_TMP = None
_LOGO_OLD = None


def make_logo_png(path, w=400, h=457):
    """Write a plain synthetic PNG (aspect about 0.88, like a tall mark) for the logo tests."""
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, w, h), False)
    pix.set_rect(pix.irect, (20, 20, 20))
    pix.save(str(path))


def setUpModule():
    """The logo is optional (PARTITOR_LOGO). Tests run with a synthetic one;
    LogoOptionalTests removes it for single tests."""
    global _LOGO_TMP, _LOGO_OLD
    _LOGO_OLD = os.environ.get("PARTITOR_LOGO")
    if HAVE_DEPS:
        _LOGO_TMP = tempfile.mkdtemp(prefix="pt-logo-")
        make_logo_png(Path(_LOGO_TMP, "logo.png"))
        os.environ["PARTITOR_LOGO"] = str(Path(_LOGO_TMP, "logo.png"))


def tearDownModule():
    if _LOGO_TMP:
        shutil.rmtree(_LOGO_TMP, ignore_errors=True)
    if _LOGO_OLD is None:
        os.environ.pop("PARTITOR_LOGO", None)
    else:
        os.environ["PARTITOR_LOGO"] = _LOGO_OLD


SP = 6.0          # staff space in points for synthetic pages (~33 px at 400 dpi)


def make_score_pdf(path, systems=2, staves=3, curve=0.0, labels=("Alto", "Tenor", "Bass"),
                   title="Test Chorale", lyrics=True, dot=True, connector="solid",
                   extra=None, quiet=()):
    """Write a synthetic one-page vector score. quiet: {(system, staff)}
    drawn with a half-rest block in each bar instead of notes.

    systems x staves, staff lines 6 pt apart, a bracket and system barline,
    barlines, noteheads, one ledger note above staff 1, a staccato dot, a
    lyric row under staff 1, labels left, a title, a page number. curve
    bends every staff line (pt) to test dewarp on a raster copy."""
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    x0, x1 = 110, 560
    y = 170
    tops = []
    for s in range(systems):
        sys_top = y
        for k in range(staves):
            tops.append(y)
            for ln in range(5):
                yy = y + ln * SP
                if curve:
                    pts = [pymupdf.Point(x, yy + curve * np.sin((x - x0) / (x1 - x0) * np.pi))
                           for x in np.linspace(x0, x1, 40)]
                    page.draw_polyline(pts, width=0.6)
                else:
                    page.draw_line((x0, yy), (x1, yy), width=0.6)
            for bx in (x0 + 170, x0 + 310, x1):
                page.draw_line((bx, y), (bx, y + 4 * SP), width=0.8)
            if (s, k) in quiet:
                for a_, b_ in ((x0, x0 + 170), (x0 + 170, x0 + 310), (x0 + 310, x1)):
                    mid = (a_ + b_) / 2
                    page.draw_rect(pymupdf.Rect(mid - 5, y + 2 * SP - 3, mid + 5, y + 2 * SP),
                                   fill=(0, 0, 0))
            else:
                for nx in range(x0 + 40, x1 - 20, 35):
                    cy = y + ((nx // 35) % 5) * SP
                    page.draw_oval(pymupdf.Rect(nx, cy - 2.6, nx + 7.5, cy + 2.6),
                                   fill=(0, 0, 0))
                    page.draw_line((nx + 7.2, cy), (nx + 7.2, cy - 3.3 * SP), width=0.7)
            if s == 0 and k < len(labels):
                page.insert_text((40, y + 2.5 * SP), labels[k], fontsize=9)
            y += 4 * SP + 9 * SP
        sys_bottom = y - 9 * SP
        if connector == "solid":
            page.draw_line((x0, sys_top), (x0, sys_bottom), width=1.0)
            page.draw_rect(pymupdf.Rect(x0 - 6, sys_top - 2, x0 - 3, sys_bottom + 2), fill=(0, 0, 0))
        elif connector == "dotted":
            yy = sys_top
            while yy < sys_bottom:
                page.draw_line((x0, yy), (x0, min(yy + 3, sys_bottom)), width=1.0)
                yy += 5
        y += 8 * SP
    first = tops[0]
    if title:
        page.insert_text((230, first - 70), title, fontsize=20)
    # ledger note above staff 1 (one ledger line 1 sp above the top line)
    page.draw_line((x0 + 200, first - SP), (x0 + 214, first - SP), width=0.6)
    page.draw_oval(pymupdf.Rect(x0 + 203, first - SP - 2.6, x0 + 210.5, first - SP + 2.6),
                   fill=(0, 0, 0))
    if dot:          # staccato dot just above staff 1 (belongs to staff 1)
        page.draw_circle((x0 + 252, first - 0.8 * SP), 0.9, fill=(0, 0, 0))
    if lyrics:       # lyric row in the upper part of the gap under staff 1
        for i, w in enumerate(["Wie", "sich", "ein", "Vater", "er", "barmt"]):
            page.insert_text((x0 + 40 + i * 60, first + 4 * SP + 2.5 * SP), w, fontsize=8)
    page.insert_text((300, 770), "1", fontsize=9)
    if extra:
        extra(page, tops)
    doc.save(path)
    return tops


def rasterize(src, dst, dpi=200, angle=0.0, curve_px=0):
    """Raster copy of a PDF (scan simulation): grey image, optional
    rotation and vertical sine bend, JPEG-free (PNG) for determinism."""
    s = pymupdf.open(src)
    out = pymupdf.open()
    for p in s:
        pix = p.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)
        g = np.frombuffer(pix.samples, np.uint8).reshape(pix.h, pix.w).copy()
        if angle:
            m = cv2.getRotationMatrix2D((pix.w / 2, pix.h / 2), angle, 1)
            g = cv2.warpAffine(g, m, (pix.w, pix.h), borderValue=255)
        if curve_px:
            h, w = g.shape
            mapx = np.tile(np.arange(w, dtype=np.float32), (h, 1))
            mapy = (np.arange(h, dtype=np.float32)[:, None]
                    + curve_px * np.sin(np.arange(w) / w * np.pi)[None, :]).astype(np.float32)
            g = cv2.remap(g, mapx, mapy, cv2.INTER_LINEAR, borderValue=255)
        ok, png = cv2.imencode(".png", g)
        pg = out.new_page(width=p.rect.width, height=p.rect.height)
        pg.insert_image(pg.rect, stream=png.tobytes())
    out.save(dst)


def flow_line(notes, bars, width=200, key=False, first=False, nums=None):
    """Synthetic one-staff line, sp 10: clef strokes (x 6-25, above and
    below the staff), optional key signature strokes (x 36-56), 8x7 note
    heads at (x, y), barlines at bars (2 px), last barline at the end."""
    img = np.zeros((130, width), bool)
    for k in range(5):
        img[40 + 10 * k, :] = True
    for x0 in (6, 13, 20):                       # clef: thin strokes, tall
        img[28:94, x0:x0 + 3] = True
    if key:
        for x0 in (36, 40, 48, 52):
            img[44:62, x0:x0 + 2] = True
    for x, y in notes:
        img[y:y + 7, x:x + 8] = True
    for b in bars:
        img[40:81, b:b + 2] = True
    return pt.Strip(img, 0, 40, 80, 10.0, np.zeros_like(img), bars_x=list(bars),
                    bar_nums=list(nums or range(1, len(bars) + 1)), ends_at_bar=True,
                    movement=first)


@contextlib.contextmanager
def mock_attr(obj, name, value):
    old = getattr(obj, name)
    setattr(obj, name, value)
    try:
        yield
    finally:
        setattr(obj, name, old)
