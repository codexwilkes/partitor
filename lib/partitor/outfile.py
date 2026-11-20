# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""Writes of output files that a user may hold open, with one clear error (DESIGN.md §12.6).

A part PDF, the proof PDF and the parts folder can be held by another program (a PDF viewer on
Windows) or sit in a folder without write access. Then the write fails with "permission denied".
WriteDenied names the file; cli_main prints it as one ERROR line with the hint of the platform
(hooks.locked_hint). No retry. Other errors pass unchanged."""
from __future__ import annotations

import os
from pathlib import Path


class WriteDenied(OSError):
    """An output file or folder could not be written: permission denied."""


def replace_file(src, dst) -> None:
    """replace_file: os.replace(src, dst); PermissionError becomes WriteDenied."""
    try:
        os.replace(src, dst)
    except PermissionError as e:
        if Path(str(src)).is_dir():             # a folder cannot move while a file in it is open
            raise WriteDenied(f"cannot move the folder {Path(str(src)).name}: permission denied "
                              f"(a file in it may be open in another program)") from e
        raise WriteDenied(f"cannot write {Path(str(e.filename or dst)).name}: permission denied") from e


def save_pdf(doc, path) -> None:
    """save_pdf: doc.save(path) of an output PDF (pymupdf); "permission denied" becomes WriteDenied."""
    try:
        doc.save(path, garbage=3, deflate=True)
    except Exception as e:
        if isinstance(e, PermissionError) or "permission denied" in str(e).lower():
            raise WriteDenied(f"cannot write {Path(str(path)).name}: permission denied") from e
        raise
