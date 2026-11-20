# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""The platform seam (DESIGN.md §12.6): the few places where a platform pack may change the core.

The core is Linux. The functions here are the Linux behaviour. A platform pack (a package in
platforms/<os>/, for example partitor_windows) calls install(pack) at its own entry point, before
cli_main.main(); install replaces these functions with the pack's. The core never imports a pack,
and on Linux no pack is installed (PACK is None).

Rules: this module imports nothing from the package and holds no platform code. Callers use
`hooks.NAME` (rule R1: install rebinds the names). No module of the stage-cache hash
(stagecache.analysis_modules) imports this module, so a pack cannot change the cache key.
A new hook is a change of API: raise API, and update DESIGN.md §12.6."""
from __future__ import annotations

from pathlib import Path

API = 2                          # 2: setup_hint
PACK = None                      # the installed pack (a module or object); None on Linux

_GIB = 1 << 30


def available_memory() -> int:
    """available_memory -> bytes of memory the machine can still give: MemAvailable of
    /proc/meminfo; 4 GiB when it cannot be read."""
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    return 4 * _GIB


def console_init() -> None:
    """console_init: prepare the console before the first output. Linux: nothing."""


def tesseract_path() -> str | None:
    """tesseract_path -> the tesseract program. Linux: None, which keeps the PATH search of
    vision._TESS. A pack gives a path to use instead."""
    return None


def default_library() -> str:
    """default_library -> the library folder when PARTITOR_LIBRARY is not set. Linux: None,
    which keeps library.LIBRARY_DEFAULT."""
    return None


def locked_hint() -> str:
    """locked_hint -> the hint under the error when an output file cannot be written."""
    return "Check that you may write to the folder and that no other program holds the file."


def setup_hint() -> str:
    """setup_hint -> the hint under the error when the library folder lacks inbox/ or library/."""
    return "Run: partitor-init (see docs/INSTALL.md)."


HOOKS = ("available_memory", "console_init", "tesseract_path", "default_library", "locked_hint",
         "setup_hint")
_LINUX = {name: globals()[name] for name in HOOKS}


class PackError(RuntimeError):
    """A platform pack that does not fit this core (API or hook names)."""


def install(pack) -> None:
    """install: use the hooks of pack. pack.API must equal API; every public function of
    the pack whose name is in HOOKS replaces the Linux one. A name that is not a hook is
    an error (a typo would else be silently ignored)."""
    global PACK
    if getattr(pack, "API", None) != API:
        raise PackError(f"platform pack {getattr(pack, '__name__', pack)!r} has API "
                        f"{getattr(pack, 'API', None)}; this partitor needs API {API}")
    names = [n for n in getattr(pack, "HOOKS", ())]
    unknown = sorted(set(names) - set(HOOKS))
    if unknown:
        raise PackError(f"platform pack names unknown hooks: {', '.join(unknown)}")
    for name in names:
        globals()[name] = getattr(pack, name)
    PACK = pack


def uninstall() -> None:
    """uninstall: back to the Linux hooks (tests)."""
    global PACK
    globals().update(_LINUX)
    PACK = None
