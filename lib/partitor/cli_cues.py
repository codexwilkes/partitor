# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""The cues and cue commands: cues above a rest (docs/DESIGN.md §13)."""
from __future__ import annotations

import argparse
import time

from . import cues
from .cli_common import _item_or_die, locks_item, saved
from .console import Abort, DIM, RST, YLW, _die, _head, _note, _ok, _warn, ask
from .library import load_item, mark_pending, part_names, save_item

LONG_REST_BARS = 6

CUE_OPTIONS = """  options after the bars (3=97-98 size=0.5 noclef):
    size=0.5    size of the cue, 0.3 to 1: 0.6 by default, 1 (full size) with fit or sync
    noclef      no clef at the start          nolabel      no name above          label=Text   another name
    anchor=25   the bar whose left barline meets the part's (default: the bar where the part starts to play)
    fit         stretch the cue bars from the anchor to the bars of the part, so that the barlines meet
    sync=3      fit, and put the 3rd note with a stem of that cue bar over the first note of the part
    align=3     no fit: move the whole cue sideways, its 3rd note with a stem over the first note of the part"""        # the table lists rests of this many bars or more


def _targets(data: dict) -> list[str]:
    return part_names(data)


def _find_target(data: dict, word: str) -> str | None:
    names = _targets(data)
    if word.isdigit() and 1 <= int(word) <= len(names):
        return names[int(word) - 1]
    hit = [n for n in names if n.lower() == word.lower()]
    return hit[0] if hit else None


def add_cue(data: dict, target: str, line: str) -> str:
    """add_cue -> '' or the reason: the cue of `line` is put in the cues of `target`
    (once: the same cue again changes nothing)."""
    entry, err = cues.parse_cue_line(data.get("parts") or [], line)
    if err:
        return err
    if "src" in entry:
        members = (data.get("groups") or {}).get(target) or []
        if entry["src"] == target or entry["src"] in members:
            return f"{entry['src']} cannot cue itself"
    allc = dict(data.get("cues") or {})
    mine = list(allc.get(target) or [])
    if entry not in mine:
        mine.append(entry)
    allc[target] = mine
    data["cues"] = allc
    return ""


def prune_cues(data: dict) -> list[str]:
    """prune_cues -> the cues of names that are no part or group any more are taken out of
    `data` (the menu lists only the names that exist, so they could not be removed); returns a
    line for each."""
    names = set(_targets(data))
    allc = dict(data.get("cues") or {})
    out = []
    for t in [t for t in allc if t not in names]:
        n = len(allc.pop(t) or [])
        out.append(f"'{t}' is not a part or a group any more: its {n} cue(s) are dropped")
    if out:
        if allc:
            data["cues"] = allc
        else:
            data.pop("cues", None)
    return out


def remove_cue(data: dict, target: str, n: int) -> str:
    mine = list((data.get("cues") or {}).get(target) or [])
    if not 1 <= n <= len(mine):
        return f"no cue {n} (1 to {len(mine)})" if mine else "this part has no cues"
    mine.pop(n - 1)
    allc = dict(data["cues"])
    if mine:
        allc[target] = mine
    else:
        allc.pop(target)
    if allc:
        data["cues"] = allc
    else:
        data.pop("cues")
    return ""


def rest_table(item, data: dict, target: str) -> list[str]:
    """rest_table -> the lines of the table of long rests of a built part: bar range, length, and a
    letter that stands inside the rest."""
    from .lines import lines_path, load_lines          # (loads the image packages: only when the table is shown)
    try:
        strips = load_lines(lines_path(item / "lines", target))["strips"]
    except (ValueError, OSError):
        return [f"{DIM}(no built systems of {target} yet: rebuild, then the long rests are listed){RST}"]
    marks = cues.letter_bars(data)
    out = []
    for first, last, n in cues.long_rests(strips, LONG_REST_BARS):
        inside = [f"{m} at bar {b}" for b, m in sorted(marks.items()) if first < b <= last]
        out.append(f"  bars {first}-{last}  ({n} bars)" + (f"   {YLW}holds letter {', '.join(inside)}{RST}" if inside else ""))
    return out or [f"{DIM}(no rest of {LONG_REST_BARS} bars or more){RST}"]


@locks_item
def cmd_cues(a: argparse.Namespace) -> int:
    """cues <id> [part]: the cues of one part or group, in a menu: a table of its long
    rests, its cues numbered, and a line to add one (3=97-98) or a word ("Canto"=97).
    Saved, not built."""
    start = time.monotonic()
    item = _item_or_die(a.id)
    data = load_item(item)
    names = _targets(data)
    target = _find_target(data, a.part) if getattr(a, "part", None) else None
    if getattr(a, "part", None) and target is None:
        _die(f"cues: no part or group '{a.part}'", f"Parts: {', '.join(names)}")
    before = dict(data.get("cues") or {})
    for line in prune_cues(data):
        _warn(f"cues:  {line}")
    try:
        while target is None:
            _head(f"Cues: {data.get('id')}")
            for i, n in enumerate(names, 1):
                c = len((data.get("cues") or {}).get(n) or [])
                print(f"  {i}  {n}" + (f"   {c} cue(s)" if c else ""))
            v = ask("part for the cues (Enter = done)", "")
            if not v:
                break
            target = _find_target(data, v)
            if target is None:
                _warn(f"cues:  no part {v}")
                continue
            _edit_target(data, item, target)
            target = None
        else:
            _edit_target(data, item, target)
    except Abort:
        pass
    if (data.get("cues") or {}) == before:
        return 0
    mark_pending(data, *[f"{t}:cues" for t in set(data.get("cues") or {}) | set(before)
                         if t in names and (data.get("cues") or {}).get(t) != before.get(t)])
    save_item(item, data)
    _ok(f"cues:  saved for {', '.join(data.get('cues') or {}) or '(none)'}")
    return saved(item, a, start)


def _edit_target(data: dict, item, target: str) -> None:
    parts = data.get("parts") or []
    while True:
        _head(f"Cues of {target}")
        print("  parts:  " + "  ".join(f"{i} {p}" for i, p in enumerate(parts, 1) if p != "-"))
        print("  long rests:")
        for t in rest_table(item, data, target):
            print("   " + t)
        mine = (data.get("cues") or {}).get(target) or []
        print("  cues:" + ("" if mine else "  none"))
        for i, e in enumerate(mine, 1):
            print(f"   {i}  {cues.entry_text(e)}")
        print("  VOICE=BARS  e.g. 3=97-98 or Canto=97   \"word\"=97   x N remove   Enter = done")
        print(CUE_OPTIONS)
        ans = ask("cue", "")
        if not ans:
            return
        if ans.startswith("x "):
            err = remove_cue(data, target, int(ans[2:]) if ans[2:].strip().isdigit() else 0)
        else:
            err = add_cue(data, target, ans)
        if err:
            print(f"     {YLW}{err}{RST}")


@locks_item
def cmd_cue(a: argparse.Namespace) -> int:
    """cue <id> LINE... --parts LIST: the same cue(s) for several parts or groups at
    once. LIST: names or numbers, comma separated. Saved, not built."""
    start = time.monotonic()
    item = _item_or_die(a.id)
    data = load_item(item)
    targets = []
    for w in [x.strip() for x in a.parts.split(",") if x.strip()]:
        t = _find_target(data, w)
        if t is None:
            _die(f"cue: no part or group '{w}'", f"Parts: {', '.join(_targets(data))}")
        if t not in targets:
            targets.append(t)
    before = {k: list(v) for k, v in (data.get("cues") or {}).items()}
    for t in targets:
        for line in a.lines:
            had = list((data.get("cues") or {}).get(t) or [])
            err = add_cue(data, t, line)
            if err:
                _die(f"cue: {line}: {err}")
            now = list((data.get("cues") or {}).get(t) or [])
            _ok(f"cue:  {t}: {line}  " + ("added" if len(now) > len(had) else "already there"))
    changed = [t for t in targets if (data.get("cues") or {}).get(t) != before.get(t)]
    if not changed:
        return 0
    mark_pending(data, *[f"{t}:cues" for t in changed])
    save_item(item, data)
    _note("the bars are checked when the part is built; a cue may run on over bars where the part plays; the bars before its anchor must rest")
    return saved(item, a, start)
