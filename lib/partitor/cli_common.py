# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""Shared CLI helpers and the set command."""
from __future__ import annotations

import argparse
import functools
import time
from pathlib import Path

from .console import _die, _note, _ok, _summary, _warn
from .library import (
    ItemBusy, apply_set, find_item, folder_name, item_id, item_lock, item_status, library_root,
    load_item, mark_pending, save_item, step_size,
)
from .proof import annotate_proof


def bar_summary(data: dict) -> str:
    """'line starts 0, 7, 14 …; letters A (p8.s2)' for the CLI."""
    sy = data.get("systems") or []
    starts = ", ".join(str(e.get("bar")) for e in sy[:8]) + (" …" if len(sy) > 8 else "")
    lets = [f"{m[1]} ({e['id']})" for e in sy for m in (e.get("marks") or [])]
    return f"line starts {starts}" + (f"; letters {', '.join(lets)}" if lets else "")


def saved(item: Path, a: argparse.Namespace, start: float) -> int:
    """After an edit: the change is saved, not built (operator request 2026-10-24:
    make all edits, review, then build). --build builds at once."""
    data = load_item(item)
    if getattr(a, "build", False):
        if item_status(data) == "needs choices":
            _warn(f"map:  systems need choices first: partitor rebuild {data['id']}")
        else:
            from .build import _rebuild_report
            _rebuild_report(item, data.get("built"))
        return _summary(start)
    _note(f"saved, not built ({item_status(data)}). Review: partitor show {data['id']}"
          f"   Build: partitor rebuild {data['id']} (menu r)")
    return _summary(start)


# ── Library commands ────────────────────────────────────────────────────────
def _lib_or_die() -> tuple[Path, Path]:
    root = library_root()
    lib = root / "library"
    if not (root / "inbox").is_dir() or not lib.is_dir():
        _die(f"library folder not ready: {root} needs inbox/ and library/",
             "Run: partitor-init (see docs/INSTALL.md).")
    return root, lib


def _item_or_die(ref: str) -> Path:
    _, lib = _lib_or_die()
    try:
        return find_item(lib, ref)
    except ValueError as e:
        _die(str(e))
    raise AssertionError


def locks_item(fn):
    """locks_item: the command holds the lock of its item (`a.id`) while it runs (0.8.38), so a
    second command on the same item stops at once, before it reads or writes anything (a `set`
    during a rebuild was saved, then shown as built). No id (`analyse --all`): no lock here."""
    @functools.wraps(fn)
    def run(a: argparse.Namespace) -> int:
        ref = getattr(a, "id", None)
        if not ref:
            return fn(a)
        item = _item_or_die(ref)
        try:
            with item_lock(item):
                return fn(a)
        except ItemBusy as e:
            _die(f"item {e} is in use: another partitor command is working on it",
                 "Wait until it ends, then run this command again")
            raise AssertionError from e
    return run


@locks_item
def cmd_set(a: argparse.Namespace) -> int:
    start = time.monotonic()
    item = _item_or_die(a.id)
    data = load_item(item)
    try:
        changes = apply_set(data, a.pairs)
    except ValueError as e:
        _die(f"set: {e}")
    mark_pending(data, *(c.split(": ")[0] for c in changes))
    save_item(item, data)
    for c in changes:
        _ok(f"set:  {c}")
    if any(":ambitus:" in c for c in changes):
        annotate_proof(item)                   # the proof lists and rings the ambitus
    if folder_name(item, data) != item.name and any(
            c.startswith(("title:", "composer:")) for c in changes):
        _note(f"folder name follows with: partitor rename {data.get('id', item_id(item))}")
    return saved(item, a, start)


def _cmd_step(a: argparse.Namespace, bigger: bool) -> int:
    start = time.monotonic()
    item = _item_or_die(a.id)
    data = load_item(item)
    try:
        pairs, why = step_size(data, bigger, getattr(a, "part", None))
        changes = apply_set(data, pairs)
    except ValueError as e:
        _die(f"{'expand' if bigger else 'contract'}: {e}")
    if data.get("pending"):
        _warn("expand/contract:  sizes are from the last build; other changes are not built yet")
    mark_pending(data, *(c.split(": ")[0] for c in changes))
    save_item(item, data)
    _ok(f"{'expand' if bigger else 'contract'}:  {why} ({'; '.join(changes)})")
    return saved(item, a, start)
