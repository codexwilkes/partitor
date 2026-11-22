# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""Cue lines: small staves of another voice above a rest (docs/DESIGN.md §13)."""
from __future__ import annotations

from dataclasses import dataclass

from typing import TYPE_CHECKING

from .model import Strip   # (numpy and cv2 load inside the functions that need them: the light commands import this module)


if TYPE_CHECKING:
    import numpy as np


class CueError(ValueError):
    """A cue the build cannot place; the text is the message for the operator."""


def split_rest(first: int, count: int, cue_first: int, cue_last: int) -> list[tuple[str, int, int]]:
    """split_rest -> the pieces of a merged rest of `count` bars from bar `first` when a cue holds
    bars cue_first..cue_last: [(kind, first bar, bars)] in bar order, kind "rest" or "cue".
    The bars of the cue are one piece of their own, one multi-bar rest (a whole rest when it is
    one bar) as wide as the cue, so that the barlines of the part and of the cue meet; the bars
    before and after it stay a rest each. A piece of no bars is left out. The bars of the
    pieces add up to `count` and every piece starts at the bar after the one before.
    CueError: the cue is not inside the rest."""
    last = first + count - 1
    if cue_last < cue_first or cue_first < first or cue_last > last:
        raise CueError(f"cue bars {cue_first}-{cue_last} are not inside the rest of bars {first}-{last}")
    out: list[tuple[str, int, int]] = []
    if cue_first > first:
        out.append(("rest", first, cue_first - first))
    out.append(("cue", cue_first, cue_last - cue_first + 1))
    if cue_last < last:
        out.append(("rest", cue_last + 1, last - cue_last))
    return out


NAME_FILL_MIN = 0.3      # text is dense; a slur or a tie, a thin arc, is not


def drop_name_text(ink: "np.ndarray", staff_top: int, sp: float, zone_end: int = 0) -> "np.ndarray":
    """drop_name_text -> `ink` without the printed name of the voice that stands above the
    first staff of a source line, e.g. "(Canto I)": dense pieces of ink (letters, words)
    wholly above the staff, two or more together or one as wide as a word. A slur or a
    tie is a thin arc and stays, so does the top of a clef (it is joined to the clef)
    and a single head on a ledger line. zone_end: column up to which every piece wholly above
    the staff goes (the name and the printed bar number stand there, before the music)."""
    import cv2
    import numpy as np
    n, lab, st, _ = cv2.connectedComponentsWithStats(ink[:max(0, staff_top)].astype(np.uint8), connectivity=8)
    bottom_limit = staff_top - 0.4 * sp
    text = []
    zone = [j for j in range(1, n) if st[j, cv2.CC_STAT_LEFT] < zone_end
            and st[j, cv2.CC_STAT_TOP] + st[j, cv2.CC_STAT_HEIGHT] < bottom_limit]
    for j in range(1, n):
        l, t, w, h, a = (int(v) for v in st[j])
        if (t + h < bottom_limit and 0.5 * sp <= h <= 1.8 * sp and w <= 8 * sp
                and a >= NAME_FILL_MIN * w * h):
            text.append((l, w, j))
    text.sort()
    drop: list[int] = []
    run: list[tuple] = []

    def flush() -> None:
        if len(run) >= 2 or (run and run[0][1] >= 2.5 * sp):
            drop.extend(j for _, _, j in run)
    for item in text:
        if run and item[0] - (run[-1][0] + run[-1][1]) > 1.2 * sp:
            flush()
            run.clear()
        run.append(item)
    flush()
    drop.extend(j for j in zone if j not in drop)
    if not drop:
        return ink
    spans = [(int(st[j, cv2.CC_STAT_LEFT]), int(st[j, cv2.CC_STAT_LEFT] + st[j, cv2.CC_STAT_WIDTH])) for j in drop]
    for j in range(1, n):                      # the brackets round the name: thin, narrow, beside it
        l, t, w, h, _ = (int(v) for v in st[j])
        if (j not in drop and t + h < bottom_limit and h <= 2.6 * sp and w <= 1.0 * sp
                and any(l <= b + sp and l + w >= a - sp for a, b in spans)):
            drop.append(j)
    out = ink.copy()
    out[:max(0, staff_top)][np.isin(lab, drop)] = False
    return out


@dataclass
class CueImg:
    """The ink of a cue at the size of its source."""
    img: "np.ndarray"    # bool, the rows of the source line
    clef_px: int         # width of the clef and key at the left (0: none); the first bar starts after it
    sp: float            # staff space of the source, px
    staff_row: int = 0   # row of the top staff line (to put pieces of two lines on one staff)
    bars: tuple = ()     # column of the barline that ends each bar of the crop

    def width_px(self, scale: float) -> int:
        """The width the bars take at `scale` (target px per source px), without the clef."""
        import math
        return int(math.ceil((self.img.shape[1] - self.clef_px) * scale))


def crop_cue(src: Strip, b_first: int, b_last: int, music_x: int, clef: bool = True) -> CueImg:
    """crop_cue -> the bars b_first..b_last of a source line (index in `bars_x`: bar k
    lies between bars_x[k-1] and bars_x[k]; bar 0 starts where the music starts,
    music_x) as one piece, with its barlines. The part label above the staff and the
    printed bar numbers (`hdr`, `num_mask`) are left out: a cue has none. clef: the
    clef and key of the line (the columns from the staff start to music_x) are put in
    front of a later bar; of the first bar the crop holds them already. A lyric under
    the staff stays. CueError: the bars are not in the line."""
    import numpy as np
    nbar = len(src.bars_x)
    if not 0 <= b_first <= b_last < nbar:
        raise CueError(f"bars {b_first}-{b_last} of the source line are not there (it has {nbar})")
    ink = src.img & ~src.hdr
    if src.num_mask is not None:
        ink = ink & ~src.num_mask
    ink = drop_name_text(ink, int(src.staff_top), float(src.sp), int(music_x + 3 * src.sp))
    xa = music_x if b_first == 0 else int(src.bars_x[b_first - 1])
    xb = int(src.bars_x[b_last]) + 1
    body = ink[:, xa:xb]
    sp = float(src.sp)
    top = int(src.staff_top)
    if not clef:
        return CueImg(body.copy(), 0, sp, top, tuple(int(src.bars_x[k]) - xa for k in range(b_first, b_last + 1)))
    x0 = int(src.staff_x0)
    if b_first == 0:
        return CueImg(ink[:, x0:xb].copy(), music_x - x0, sp, top,
                      tuple(int(src.bars_x[k]) - x0 for k in range(b_first, b_last + 1)))
    pre = music_x - x0
    return CueImg(np.concatenate([ink[:, x0:music_x], body], axis=1), pre, sp, top,
                  tuple(pre + int(src.bars_x[k]) - xa for k in range(b_first, b_last + 1)))


def join_cues(parts: list[CueImg]) -> CueImg:
    """join_cues -> the crops of consecutive bars that stand on different lines of the source
    as one cue: the staves on one row (top line to top line), side by side. The first crop
    keeps its clef; the others were cropped without one and start at their first bar."""
    import numpy as np
    if len(parts) == 1:
        return parts[0]
    above = max(p.staff_row for p in parts)
    below = max(p.img.shape[0] - p.staff_row for p in parts)
    cols, bars, off = [], [], 0
    for p in parts:
        out = np.zeros((above + below, p.img.shape[1]), bool)
        top = above - p.staff_row
        out[top:top + p.img.shape[0]] = p.img
        cols.append(out)
        bars += [off + b for b in p.bars]
        off += p.img.shape[1]
    return CueImg(np.concatenate(cols, axis=1), parts[0].clef_px, parts[0].sp, above, tuple(bars))


@dataclass
class CueSpec:
    """One cue of a part: the voice `src`, whole bars first..last (bar numbers as
    printed in the part). clef: draw the clef and key of the source. label: the
    text above it (None: the name of the voice; "": none)."""
    src: str
    first: int
    last: int
    clef: bool = True
    label: str | None = None
    size: float | None = None    # None: CUE_SIZE_DEFAULT, or CUE_SIZE_FIT when fit or sync is set
    anchor: int | None = None    # the bar whose left barline is pinned to the part's (None: the first bar the part plays)
    fit: bool = False            # the bars from the anchor on are stretched sideways to the bars of the part
    sync: int | None = None      # with fit: the sync-th note of the cue bar at the anchor stands over the part's first note


CUE_SIZE_RANGE = (0.3, 1.0)       # the size of a cue, as a factor of the staff (0.6 default)
CUE_SIZE_DEFAULT = 0.6
CUE_SIZE_FIT = 1.0                # with fit or sync: full size, so that the stretch is small and the notes keep their shape


def cue_size(spec: CueSpec) -> float:
    """cue_size -> the size of a cue as a factor of the staff: the one typed, else full size
    when the cue is fitted to the bars of the part (fit or sync), else the small default."""
    if spec.size is not None:
        return spec.size
    return CUE_SIZE_FIT if spec.fit or spec.sync is not None else CUE_SIZE_DEFAULT


def parse_cues(raw: object, parts: list[str], groups: dict[str, list[str]]) -> tuple[dict, list[str]]:
    """parse_cues -> ({target: [CueSpec]}, notes): the `cues` key of score.yaml,
    {part or group: [{src, bars: [first, last], clef, label, size} or {text, bar}]}.
    An entry that is wrong is left out and named in the notes (never a stop). A text
    mark is a CueSpec with no source (src "")."""
    out: dict[str, list] = {}
    notes: list[str] = []
    if raw in (None, {}, []):
        return out, notes
    if not isinstance(raw, dict):
        return out, ["cues: the key is not a table of parts; ignored"]
    for target, items in raw.items():
        if target not in parts and target not in groups:
            notes.append(f"cues: '{target}' is not a part or a group; its cues are ignored")
            continue
        for it in items if isinstance(items, list) else []:
            try:
                if not isinstance(it, dict):
                    raise ValueError("not a table")
                if "text" in it:
                    bar = int(it["bar"])
                    spec = CueSpec("", bar, bar, False, str(it["text"]), 0.0)
                else:
                    a, b = (int(x) for x in it["bars"])
                    if it["src"] not in parts:
                        raise ValueError(f"'{it['src']}' is not a part")
                    size = None if it.get("size") is None else float(it["size"])
                    if size is not None and not CUE_SIZE_RANGE[0] <= size <= CUE_SIZE_RANGE[1]:
                        raise ValueError(f"size {size} is not in {CUE_SIZE_RANGE[0]}-{CUE_SIZE_RANGE[1]}")
                    if a > b or a < 0:
                        raise ValueError(f"bars {a}-{b}")
                    lab = it.get("label")
                    anc = it.get("anchor")
                    if anc is not None and not a <= int(anc) <= b:
                        raise ValueError(f"anchor {anc} is not in the bars {a}-{b}")
                    spec = CueSpec(str(it["src"]), a, b, bool(it.get("clef", True)),
                                   None if lab is None else str(lab), size,
                                   None if anc is None else int(anc), bool(it.get("fit", False)),
                                   None if it.get("sync") is None else int(it["sync"]))
                    if spec.sync is not None and spec.sync < 1:
                        raise ValueError(f"sync {spec.sync}")
            except (KeyError, ValueError, TypeError) as e:
                notes.append(f"cues: {target}: entry {it!r} is wrong ({e}); left out")
                continue
            out.setdefault(target, []).append(spec)
    return out, notes


def parse_cue_line(parts: list[str], line: str) -> tuple[dict | None, str]:
    """parse_cue_line -> (entry of the `cues` key, "") or (None, the reason). parts: the
    part names in score order (the numbers of the line count from 1).
        3=97-98            the voice of part 3, bars 97 to 98
        Canto=97           by name; one bar
        3=97-98 noclef size=0.5 label=Soprano      options: noclef, nolabel, size=, label=, anchor=, fit, sync=
        "Canto"=97         a word at bar 97, no music"""
    import shlex
    left, eq, right = line.partition("=")
    left = left.strip()
    if not eq or not left:
        return None, 'use 3=97-98 (a voice and its bars) or "Canto"=97 (a word at a bar)'
    import re
    m = re.match(r"\s*(\d+)(?:\s*-\s*(\d+))?", right)
    if not m:
        return None, "give the bars after the =: 3=97-98 or 3=97"
    a = int(m.group(1))
    b = int(m.group(2)) if m.group(2) else a
    opts_txt = right[m.end():]
    if opts_txt and not opts_txt[0].isspace():
        return None, "bars are one number or a range: 97 or 97-98"
    if a > b:
        return None, f"bars {a}-{b}: the first bar comes first"
    try:
        words = shlex.split(opts_txt)
    except ValueError:
        return None, "a quote is not closed"
    if left[0] in "\"'" and left[-1] == left[0] and len(left) > 2:
        if a != b:
            return None, "a word stands at one bar: \"Canto\"=97"
        if words:
            return None, "a word takes no options"
        return {"text": left[1:-1], "bar": a}, ""
    named = [p for p in parts if p != "-"]
    if left.isdigit():
        k = int(left)
        if not 1 <= k <= len(parts):
            return None, f"no part {k} (1 to {len(parts)})"
        src = parts[k - 1]
    else:
        hit = [p for p in named if p.lower() == left.lower()]
        if not hit:
            return None, f"no part '{left}'"
        src = hit[0]
    entry: dict = {"src": src, "bars": [a, b]}
    for w in words:
        if w == "noclef":
            entry["clef"] = False
        elif w == "nolabel":
            entry["label"] = ""
        elif w.startswith("size="):
            try:
                size = float(w[5:])
            except ValueError:
                return None, f"{w}: a number"
            if not CUE_SIZE_RANGE[0] <= size <= CUE_SIZE_RANGE[1]:
                return None, f"size {size}: from {CUE_SIZE_RANGE[0]} to {CUE_SIZE_RANGE[1]}"
            entry["size"] = size
        elif w.startswith("label="):
            entry["label"] = w[6:]
        elif w.startswith("sync="):
            if not w[5:].isdigit() or int(w[5:]) < 1:
                return None, f"{w}: the number of a note of the cue bar, 1 or more"
            entry["sync"] = int(w[5:])
        elif w == "fit":
            entry["fit"] = True
        elif w.startswith("anchor="):
            if not w[7:].isdigit() or not a <= int(w[7:]) <= b:
                return None, f"{w}: a bar of the cue, {a} to {b}"
            entry["anchor"] = int(w[7:])
        else:
            return None, f"'{w}': options are noclef, nolabel, size=0.5, label=Text, anchor=25, fit, sync=3"
    return entry, ""


def entry_text(entry: dict) -> str:
    """entry_text -> a cue of the `cues` key as the line that makes it (for the menu)."""
    if "text" in entry:
        return f'"{entry["text"]}"={entry["bar"]}'
    a, b = entry["bars"]
    out = f"{entry['src']}={a}" + (f"-{b}" if b != a else "")
    if entry.get("clef") is False:
        out += " noclef"
    if "size" in entry:
        out += f" size={entry['size']}"
    if entry.get("label") == "":
        out += " nolabel"
    elif entry.get("label"):
        out += f" label={entry['label']}"
    if "anchor" in entry:
        out += f" anchor={entry['anchor']}"
    if entry.get("fit"):
        out += " fit"
    if entry.get("sync"):
        out += f" sync={entry['sync']}"
    return out


def long_rests(strips: list, min_bars: int) -> list[tuple[int, int, int]]:
    """long_rests -> [(first bar, last bar, bars)] of the rests of a part that last `min_bars`
    or more, read from its finished lines (Strip): the multi-bar rests, and rests that
    meet at the end of one line and the start of the next as one."""
    runs: list[list[int]] = []
    for s in strips:
        if s.rest_src is not None:
            first = s.bar_no if s.bar_no is not None else s.rest_src[2].first
            if first is not None:
                runs.append([first, int(s.rest_src[2].bars)])
            continue
        for k, c in enumerate(s.rest_counts):
            n = s.bar_nums[k] if k < len(s.bar_nums) else None
            if c > 0 and n is not None:
                runs.append([n, c])
            else:
                runs.append([-1, 0])                                 # a bar of music: ends a run
    out: list[list[int]] = []
    for first, c in runs:
        if first < 0:
            out.append([-1, 0])
        elif out and out[-1][0] >= 0 and out[-1][0] + out[-1][1] == first:
            out[-1][1] += c
        else:
            out.append([first, c])
    return [(f, f + c - 1, c) for f, c in out if f >= 0 and c >= min_bars]


def letter_bars(data: dict) -> dict[int, str]:
    """mark_bars -> {bar number: letter} of the rehearsal marks of an item (score.yaml)."""
    out: dict[int, str] = {}
    for e in data.get("systems") or []:
        nums = e.get("bar_nums") or []
        for idx, letter in e.get("marks") or []:
            if 0 <= int(idx) < len(nums):
                out.setdefault(int(nums[int(idx)]), str(letter))
    return out
