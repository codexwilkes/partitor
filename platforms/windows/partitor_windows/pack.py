# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""The hooks of the Windows pack (partitor.hooks, DESIGN.md §12.6). Windows code lives only here.

API must equal partitor.hooks.API; HOOKS names the hooks this pack replaces."""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

API = 2
HOOKS = ("available_memory", "console_init", "tesseract_path", "default_library", "locked_hint",
         "setup_hint")
_GIB = 1 << 30


def available_memory() -> int:
    """available_memory -> free physical memory (GlobalMemoryStatusEx); 4 GiB on an error."""
    try:
        import ctypes

        class _Status(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        st = _Status()
        st.dwLength = ctypes.sizeof(_Status)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):  # type: ignore[attr-defined]
            return int(st.ullAvailPhys)
    except (OSError, AttributeError, ImportError):
        pass
    return 4 * _GIB


def console_init() -> None:
    """console_init: VT (ANSI colour) mode on stdout and stderr, and UTF-8 output. An error is
    ignored (an old console then shows the escape codes as text)."""
    try:
        import ctypes
        k32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        for std in (-11, -12):                        # STD_OUTPUT_HANDLE, STD_ERROR_HANDLE
            h = k32.GetStdHandle(std)
            mode = ctypes.c_ulong()
            if k32.GetConsoleMode(h, ctypes.byref(mode)):
                k32.SetConsoleMode(h, mode.value | 0x0004)   # ENABLE_VIRTUAL_TERMINAL_PROCESSING
    except (OSError, AttributeError, ImportError):
        pass
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")       # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass


def tesseract_path() -> str | None:
    """tesseract_path -> tesseract next to partitor.exe (a bundled copy), then on PATH, then in
    the folder of the UB Mannheim installer. None when not found."""
    exe_dir = Path(sys.executable).parent
    for cand in (exe_dir / "tesseract" / "tesseract.exe",):
        if cand.is_file():
            return str(cand)
    found = shutil.which("tesseract")
    if found:
        return found
    cand = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Tesseract-OCR" / "tesseract.exe"
    return str(cand) if cand.is_file() else None


def default_library() -> str:
    """default_library -> Documents\\partitor of the user."""
    home = os.environ.get("USERPROFILE") or str(Path.home())
    return str(Path(home) / "Documents" / "partitor")


def locked_hint() -> str:
    """locked_hint -> Windows locks a file that a viewer has open."""
    return "Close the file in your PDF viewer, then run the command again."


def setup_hint() -> str:
    """setup_hint -> the installer makes inbox and library; partitor-init is a Linux tool."""
    return ("Run the installer again, or make the folders inbox and library in the library folder "
            "(PARTITOR_LIBRARY).")
