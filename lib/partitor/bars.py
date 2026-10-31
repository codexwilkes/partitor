# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""Bar numbers, bar marks and barline edits."""
from __future__ import annotations

import re

import numpy as np


# =============================================================================
# Bar numbers
# =============================================================================
def assign_bars(sysrecs: list[dict]) -> tuple[list[int], list[str], int]:
    """assign_bars -> (first bar number per system, ids of systems whose
    number differs from the plain count, number of printed numbers used).

    Count: a system with m barlines (after its start) holds m bars (a bar
    cut by the line break keeps its number). Numbering restarts at 1 at a
    movement start. Printed numbers (anchors: bars before it in its
    system, value) are trusted (misreads are filtered at detection): a
    system starts at its first anchor's value minus the bars before it;
    otherwise the count continues from the last anchor. An anchor more than
    3 bars away from the count needs a second anchor that agrees. A first
    anchor 1-3 bars below the count means a pickup bar: the systems before
    it count back from it (movement start = bar 0)."""
    changed: list[str] = []
    used = 0
    segs: list[list[int]] = []
    for i, r in enumerate(sysrecs):
        if not segs or r.get("restart"):
            segs.append([i])
        else:
            segs[-1].append(i)
    out = [0] * len(sysrecs)
    for seg in segs:
        nb = [sysrecs[i].get("nbars", 0) for i in seg]
        anc = [sorted((a[0], a[1]) for a in sysrecs[i].get("anchors", [])) for i in seg]
        # starts implied by each anchor, in order (system pos, start value)
        implied = [(k, n - before) for k in range(len(seg)) for before, n in anc[k]]
        used += len(implied)
        starts: list[int | None] = [None] * len(seg)
        proj: int = 1                       # next start from the count
        plain = [1 + sum(nb[:k]) for k in range(len(seg))]
        first_k = None
        for k in range(len(seg)):
            cand = None
            for j, (kk, sv) in enumerate(implied):
                if kk != k:
                    continue
                ok = abs(sv - proj) <= 3 or any(
                    sv2 == sv + sum(nb[k:kk2]) for kk2, sv2 in implied[j + 1:])
                if ok:
                    cand = sv
                    break
            if cand is not None:
                starts[k] = cand
                first_k = k if first_k is None else first_k
            else:
                starts[k] = proj
            # end of this system: from its last trusted anchor, else count
            end = starts[k] + nb[k]
            for before, n in anc[k][::-1]:
                if abs((n - before) - starts[k]) <= 3:
                    end = n - before + nb[k]
                    break
            proj = end
        # a first printed number 1-3 bars below the count means a pickup
        # bar: count back from it to the movement start (bar 0)
        if first_k is not None and -3 <= starts[first_k] - plain[first_k] < 0:
            for k in range(first_k - 1, -1, -1):
                starts[k] = starts[k + 1] - nb[k]
            starts[0] = max(0, min(1, starts[0]))
        for k, i in enumerate(seg):
            out[i] = int(starts[k])
            if out[i] != plain[k]:
                changed.append(sysrecs[i]["id"])
    return out, changed, used


PICKUP_SHORT = 0.4    # a first bar this many bars short is a pickup
SPLIT_PART = 0.85     # each half of a split bar is at most this of a bar
SPLIT_SUM = 1.35      # ... and both halves together at most this


def _movements(systems: list[dict]) -> list[list[int]]:
    segs: list[list[int]] = []
    for i, r in enumerate(systems):
        if not segs or r.get("restart"):
            segs.append([i])
        else:
            segs[-1].append(i)
    return segs


def _flat_bars(systems: list[dict], seg: list[int]) -> list[tuple[int, int]]:
    """Bars of one movement in order: (system index, bar index in system)."""
    return [(k, i) for k in seg for i in range(int(systems[k].get("bars", 0) or 0))]


def _boundaries(systems: list[dict], seg: list[int], flat: list[tuple[int, int]]) -> list[int]:
    """Flat indices of the bars that follow a repeat sign (end or start)."""
    pos = {fb: b for b, fb in enumerate(flat)}
    out = set()
    for k in seg:
        nb = int(systems[k].get("bars", 0) or 0)
        for idx, _kind in systems[k].get("repeats") or []:
            j = int(idx) + 1                      # bar after the repeat barline
            if j < nb:
                b = pos.get((k, j))
            else:                                 # first bar of the next system
                nxt = [kk for kk in seg if kk > k]
                b = pos.get((nxt[0], 0)) if nxt else None
            if b is not None and 0 < b < len(flat):
                out.add(b)
    return sorted(out)


def propose_bar_rules(systems: list[dict]) -> dict:
    """propose_bar_rules -> {'pickup': [movement-first system ids],
    'split': ['<system id>:<bar index>' of the bar that completes the bar
    before a repeat]} from bar widths (DESIGN.md §4.2 item 7). A first bar
    whose music is PICKUP_SHORT of a bar or more narrower than usual is a
    pickup; two short bars around a repeat are one bar."""
    rules: dict = {"pickup": [], "split": [], "fix": {}}
    all_int = [w for r in systems for w in (r.get("widths") or [])[1:]]
    if not all_int:
        return rules
    for seg in _movements(systems):
        flat = _flat_bars(systems, seg)
        if not flat:
            continue
        m_seg = float(np.median([w for k in seg for w in (systems[k].get("widths") or [])[1:]]
                                or all_int))

        def own(k: int) -> float | None:
            inner = (systems[k].get("widths") or [])[1:]
            return float(np.median(inner)) if inner else None

        def typical(k: int) -> float:
            """A full bar in line k. Lines are justified, so spacing differs
            per line: the line's own median from 3 inner bars; with 1-2 the
            mean (geometric) of the line's and the movement's median, so one
            unusually wide bar does not decide alone."""
            inner = (systems[k].get("widths") or [])[1:]
            if len(inner) >= 3:
                return float(np.median(inner))
            return float(np.sqrt(own(k) * m_seg)) if inner else m_seg

        # clef + key (+ time) width: first bar minus the line's own median
        # bar, over the lines that do not start the movement
        def pre_of(ks) -> list[float]:
            return [systems[k]["widths"][0] - own(k) for k in ks
                    if systems[k].get("widths") and own(k) is not None]
        pre = pre_of(seg[1:]) or pre_of([k for k in range(len(systems)) if k not in seg[:1]])
        if not pre:
            continue
        prefix = max(0.0, float(np.median(pre)))

        def content(k: int, i: int) -> float:
            w = (systems[k].get("widths") or [])[i]
            return ((w - prefix) if i == 0 else w) / typical(k)

        k0 = seg[0]
        if systems[k0].get("widths") and content(k0, 0) <= 1.0 - PICKUP_SHORT:
            rules["pickup"].append(systems[k0]["id"])
        for b in _boundaries(systems, seg, flat):
            before, after = content(*flat[b - 1]), content(*flat[b])
            if before <= SPLIT_PART and after <= SPLIT_PART and before + after <= SPLIT_SUM:
                k, i = flat[b]
                rules["split"].append(f"{systems[k]['id']}:{i}")
    return rules


def number_bars(systems: list[dict], rules: dict | None) -> tuple[list[int], dict, str]:
    """number_bars -> (first bar number per system, rehearsal marks
    {system id: [[bar index, letter], ...]}, anchor scheme).

    Without rules: assign_bars (plain count, printed numbers). With rules:
    a pickup is bar 0; the bar that completes a split bar keeps the number
    of the bar before it; endings count on (each printed bar its own
    number). Printed numbers that follow the plain count ('naive' source)
    are converted; numbers that already follow these rules ('standard')
    are used as they are. `fix` {system id: n} sets a system's first bar;
    the systems after it in the movement follow. Marks: A, B, ... per
    movement at the first full bar after each repeat."""
    rules = rules or {}
    pick = set(rules.get("pickup") or [])
    split = set(rules.get("split") or [])
    fix = {str(k): int(v) for k, v in (rules.get("fix") or {}).items()}
    marks: dict[str, list[list]] = {}
    scheme = "none"
    if not pick and not split:
        recs = [{**e, "nbars": int(e.get("bars", e.get("nbars", 0)) or 0),
                 "anchors": [(int(x[0]), int(x[1])) for x in e.get("anchors") or []]}
                for e in systems]
        starts = assign_bars(recs)[0]
    else:
        starts = [0] * len(systems)
        cn = cs = 0
        per_seg = []
        for seg in _movements(systems):
            flat = _flat_bars(systems, seg)
            off, o = [], 1 if systems[seg[0]]["id"] in pick else 0
            for b, (k, i) in enumerate(flat):
                if b > 0 and f"{systems[k]['id']}:{i}" in split:
                    o += 1
                off.append(o)
            first = {k: next((b for b, (kk, _) in enumerate(flat) if kk == k), None) for k in seg}
            anc = []
            for k in seg:
                for a in systems[k].get("anchors") or []:
                    b = (first[k] or 0) + int(a[0])
                    if first[k] is not None and b < len(flat):
                        anc.append((b, int(a[1])))
                        cn += int(a[1]) == b + 1
                        cs += int(a[1]) == b + 1 - off[b]
            per_seg.append((seg, flat, off, first, anc))
        scheme = "standard" if cs > cn else "naive"
        for seg, flat, off, first, anc in per_seg:
            num = [b + 1 - off[b] for b in range(len(flat))]
            # printed numbers resync the count from their system on
            shifts = []
            for b, n in sorted(anc):
                want = n if scheme == "standard" else n - off[b]
                shifts.append((flat[b][0], want - num[b]))
            for k in seg:
                if first[k] is None:
                    starts[k] = starts[k - 1] if k else 0
                    continue
                sh = 0
                for kk, d in shifts:
                    if kk <= k and abs(d) <= 3:
                        sh = d
                starts[k] = num[first[k]] + sh
            # rehearsal letters
            letter = 0
            used = set()
            for b in _boundaries(systems, seg, flat):
                k, i = flat[b]
                if f"{systems[k]['id']}:{i}" in split:
                    b += 1
                if b >= len(flat) or b in used:
                    continue
                used.add(b)
                k, i = flat[b]
                marks.setdefault(systems[k]["id"], []).append([i, chr(ord("A") + letter % 26)])
                letter += 1
    if fix:
        for seg in _movements(systems):
            delta = 0
            for k in seg:
                sid = systems[k]["id"]
                if sid in fix:
                    delta = fix[sid] - starts[k]
                starts[k] += delta
    if not pick and not split:
        for seg in _movements(systems):        # letters without bar rules
            flat = _flat_bars(systems, seg)
            for n_, b in enumerate(_boundaries(systems, seg, flat)):
                k, i = flat[b]
                marks.setdefault(systems[k]["id"], []).append([i, chr(ord("A") + n_ % 26)])
    return [int(x) for x in starts], marks, scheme


def bar_numbers(systems: list[dict], starts: list[int], rules: dict | None
                ) -> list[list[int]]:
    """Number of every bar of every system: the system's first bar number,
    +1 per bar, except a bar that completes a split bar (keeps the number
    of the bar before it). Used by re-flow for the new line starts."""
    split = set((rules or {}).get("split") or [])
    out = []
    for e, st in zip(systems, starts):
        nums, n = [], int(st)
        for i in range(int(e.get("bars", 0) or 0)):
            if i > 0 and f"{e['id']}:{i}" not in split:
                n += 1
            nums.append(n)
        out.append(nums)
    return out


def mark_items(items) -> tuple[set[int], set[tuple[str, int]]]:
    """mark_items -> (bar numbers, {(system id, bar index)}) of a marks_add /
    marks_drop list. An entry is a bar number (12) or '<system id>:<bar
    index>' ('p8.s1:0': that very bar, index from 0); unreadable entries
    are left out."""
    nums: set[int] = set()
    spots: set[tuple[str, int]] = set()
    for x in items or []:
        if isinstance(x, int):
            nums.add(x)
            continue
        t = str(x).strip()
        if t.lstrip("-").isdigit():
            nums.add(int(t))
        elif ":" in t and t.rsplit(":", 1)[1].isdigit():
            spots.add((t.rsplit(":", 1)[0], int(t.rsplit(":", 1)[1])))
    return nums, spots


def apply_mark_rules(systems: list[dict], marks: dict, nums: list[list[int]],
                     rules: dict | None) -> dict:
    """apply_mark_rules -> marks with the operator's changes: bar_rules
    marks_add (a bar number: a mark at the first bar with that number; or
    '<system id>:<bar index>': a mark at that bar, for a number two bars
    share) and marks_drop (the same forms: no mark there). All marks of a
    movement are then lettered A, B, ... in bar order, so a mark added
    between two others moves the letters after it on."""
    add_n, add_p = mark_items((rules or {}).get("marks_add"))
    drop_n, drop_p = mark_items((rules or {}).get("marks_drop"))
    if not (add_n or add_p or drop_n or drop_p):
        return marks
    pos: set[tuple[int, int]] = set()
    for k, e in enumerate(systems):
        for i, _ in marks.get(e["id"]) or []:
            if i < len(nums[k]) and nums[k][i] not in drop_n and (e["id"], int(i)) not in drop_p:
                pos.add((k, int(i)))
    for b in sorted(add_n):
        hit = next(((k, i) for k in range(len(systems))
                    for i, n in enumerate(nums[k]) if n == b), None)
        if hit is not None:
            pos.add(hit)
    index = {e["id"]: k for k, e in enumerate(systems)}
    for sid, i in sorted(add_p):
        k = index.get(sid)
        if k is not None and i < len(nums[k]):
            pos.add((k, i))
    out: dict[str, list[list]] = {}
    for seg in _movements(systems):
        for n_, (k, i) in enumerate(sorted(p for p in pos if p[0] in seg)):
            out.setdefault(systems[k]["id"], []).append([i, chr(ord("A") + n_ % 26)])
    return out


def mark_bars(systems: list[dict]) -> list[int]:
    """mark_bars -> bar numbers that carry a rehearsal mark (after renumber)."""
    return [int(e["bar_nums"][m[0]]) for e in systems for m in e.get("marks") or []
            if m[0] < len(e.get("bar_nums") or [])]


def _mark_sorted(items: list) -> list:
    """Bar numbers first (ascending), then 'id:index' entries, for the yaml."""
    return sorted(items, key=lambda x: (isinstance(x, str), x if isinstance(x, str) else int(x)))


def toggle_mark(rules: dict, systems: list[dict], bar) -> str:
    """toggle_mark -> 'added' or 'removed': a mark at bar on or off in
    rules (marks_add / marks_drop). bar: a bar number, or a tuple (system
    id, bar index from 0) for one bar of two that share a number.
    systems: renumbered with rules. ValueError when there is no such bar."""
    add = list(rules.get("marks_add") or [])
    drop = list(rules.get("marks_drop") or [])
    if isinstance(bar, tuple):
        sid, i = bar
        key = f"{sid}:{i}"
        e = next((e for e in systems if e["id"] == sid), None)
        if e is None or not 0 <= i < len(e.get("bar_nums") or []):
            raise ValueError(f"no bar {i + 1} in {sid}")
        if any(m[0] == i for m in e.get("marks") or []):
            if key in add:
                add.remove(key)
            else:
                drop.append(key)
            done = "removed"
        else:
            if key in drop:
                drop.remove(key)
            else:
                add.append(key)
            done = "added"
    else:
        if bar in mark_bars(systems):
            if bar in add:
                add.remove(bar)
            else:
                drop.append(bar)
            done = "removed"
        else:
            if not any(bar in (e.get("bar_nums") or []) for e in systems):
                raise ValueError(f"no bar {bar}")
            if bar in drop:
                drop.remove(bar)
            else:
                add.append(bar)
            done = "added"
    rules["marks_add"], rules["marks_drop"] = _mark_sorted(add), _mark_sorted(drop)
    for k in ("marks_add", "marks_drop"):
        if not rules[k]:
            rules.pop(k)
    return done


# ── Bar edits: the operator corrects a misread barline (bar_rules.bar_edits) ─
# One string per edit, applied in order to the detected barlines of a line:
#   "<system id>:j<N>/<R>"        join bar N with the next one (a false barline)
#   "<system id>:a<N>@<P>/<R>"    add a barline in bar N at P % of its width
#                                 (a missed barline)
# N counts the bars of the line from 1 as they stand when the edit is made;
# R is the number of bars detected in the line when the edit was made. An
# edit whose R no longer fits (the line was detected again, the engine
# changed) is skipped with a warning: it would mend a bar that is right.
BAR_EDIT_RE = re.compile(r"^(?P<sid>[^:]+):(?P<op>[ja])(?P<n>\d+)(?:@(?P<pct>\d+))?/(?P<raw>\d+)$")


def parse_bar_edit(text: str) -> dict | None:
    """parse_bar_edit 'p4.s1:j1/3' -> {sid, op, n, pct, raw, text}, or None."""
    m = BAR_EDIT_RE.match(str(text).strip())
    if not m:
        return None
    pct = int(m.group("pct")) if m.group("pct") else None
    if (m.group("op") == "a") != (pct is not None):
        return None
    return {"sid": m.group("sid"), "op": m.group("op"), "n": int(m.group("n")),
            "pct": pct, "raw": int(m.group("raw")), "text": str(text).strip()}


def format_bar_edit(sid: str, op: str, n: int, raw: int, pct: int | None = None) -> str:
    return f"{sid}:{op}{n}" + (f"@{pct}" if op == "a" else "") + f"/{raw}"


def bar_edits_by_system(rules: dict | None) -> dict[str, list[dict]]:
    """bar_edits_by_system -> {system id: [edit, ...]} in order; unreadable
    strings are left out."""
    out: dict[str, list[dict]] = {}
    for t in (rules or {}).get("bar_edits") or []:
        ed = parse_bar_edit(t)
        if ed:
            out.setdefault(ed["sid"], []).append(ed)
    return out


def edit_bars(e: dict, edits: list[dict]) -> tuple[dict, list[str]]:
    """edit_bars -> (copy of the system entry with its bars, widths,
    anchors and repeats edited, notes of edits not applied)."""
    out = dict(e)
    notes: list[str] = []
    if not edits:
        return out, notes
    raw = int(e.get("bars", e.get("nbars", 0)) or 0)
    widths = [float(w) for w in e.get("widths") or []]
    if len(widths) != raw:
        widths = []
    anchors = [(int(a[0]), int(a[1])) for a in e.get("anchors") or []]
    repeats = [(int(r[0]), r[1]) for r in e.get("repeats") or []]
    nb = raw
    for ed in edits:
        if ed["raw"] != raw:
            notes.append(f"{e.get('id')}: edit {ed['text']} not applied: the line has {raw} "
                         f"bar(s) now, it had {ed['raw']}")
            continue
        n = ed["n"]
        if ed["op"] == "j":
            if not 1 <= n <= nb - 1:
                notes.append(f"{e.get('id')}: edit {ed['text']} not applied: no bar {n} "
                             f"with a bar after it")
                continue
            d = n - 1                                   # the barline between bar n, n+1
            if widths:
                widths[d:d + 2] = [widths[d] + widths[d + 1]]
            anchors = [(b if b <= d else b - 1, v) for b, v in anchors]
            stub = [(-1, k) for x, k in repeats if x == d == 0 and k == "start"]
            repeats = sorted([(x if x < d else x - 1, k) for x, k in repeats if x != d] + stub)
            nb -= 1
        else:
            if not 1 <= n <= nb or not 5 <= ed["pct"] <= 95:
                notes.append(f"{e.get('id')}: edit {ed['text']} not applied: no bar {n}, "
                             "or a place outside 5-95 %")
                continue
            b, pc = n - 1, ed["pct"] / 100.0
            if widths:
                w = widths[b]
                widths[b:b + 1] = [w * pc, w * (1 - pc)]
            anchors = [(bb if bb <= b else bb + 1, v) for bb, v in anchors]
            repeats = [(x if x < b else x + 1, k) for x, k in repeats]
            nb += 1
    out["bars"] = nb
    if "nbars" in out:
        out["nbars"] = nb
    if widths or "widths" in e:
        out["widths"] = [round(w, 2) for w in widths] if widths else list(e.get("widths") or [])
    if e.get("anchors") is not None:
        out["anchors"] = [[b, v] for b, v in anchors]
    if e.get("repeats") is not None:
        out["repeats"] = [[x, k] for x, k in repeats]
    return out, notes


def effective_systems(systems: list[dict], rules: dict | None,
                      notes: list[str] | None = None) -> list[dict]:
    """effective_systems -> the systems with the operator's bar edits applied
    (copies; the stored detection stays as detected)."""
    by = bar_edits_by_system(rules)
    if not by:
        return list(systems)
    out = []
    for e in systems:
        ne, nt = edit_bars(e, by.get(e["id"], []))
        out.append(ne)
        if notes is not None:
            notes.extend(nt)
    return out


def edit_barlines(edits: list[dict], barlines: list[int], x0: int,
                  repeats: list | None = None, mensur: list | None = None
                  ) -> tuple[list[int], list, list, list[str]]:
    """edit_barlines -> (barlines, repeats, mensur, notes) of one system
    with the same edits as edit_bars applied to the detected positions.
    x0: where the system's staves start (the left edge of bar 1)."""
    bl = [int(x) for x in barlines]
    rp = [(int(r[0]), r[1]) for r in repeats or []]
    mn = [int(x) for x in mensur or []]
    notes: list[str] = []
    raw = len(bl)
    for ed in edits:
        if ed["raw"] != raw:
            notes.append(f"{ed['sid']}: edit {ed['text']} not applied: the line has {raw} "
                         f"bar(s) now, it had {ed['raw']}")
            continue
        n = ed["n"]
        if ed["op"] == "j":
            if not 1 <= n <= len(bl) - 1:
                continue
            d = n - 1
            x = bl.pop(d)
            mn = [m for m in mn if m != x]
            stub = [(-1, k) for i, k in rp if i == d == 0 and k == "start"]
            rp = sorted([(i if i < d else i - 1, k) for i, k in rp if i != d] + stub)
        else:
            if not 1 <= n <= len(bl) or not 5 <= ed["pct"] <= 95:
                continue
            b = n - 1
            left = bl[b - 1] if b > 0 else int(x0)
            bl.insert(b, int(round(left + ed["pct"] / 100.0 * (bl[b] - left))))
            rp = [(i if i < b else i + 1, k) for i, k in rp]
    return bl, [[i, k] for i, k in rp], mn, notes


def bar_mismatches(systems: list[dict], rules: dict | None) -> list[dict]:
    """bar_mismatches -> the places where the printed bar numbers of the
    source disagree with the count of barlines: [{id, prev, counted,
    printed, key}], one per change of the difference. systems: effective.
    Movements with a pickup or split bar rule are left out (their numbers
    differ from the count on purpose). Answers already given
    (bar_rules.bars_ack, the key of each) are left out."""
    rules = rules or {}
    pick = set(rules.get("pickup") or [])
    split = {str(k).split(":")[0] for k in rules.get("split") or []}
    recs = [{**e, "nbars": int(e.get("bars", e.get("nbars", 0)) or 0),
             "anchors": [(int(x[0]), int(x[1])) for x in e.get("anchors") or []]}
            for e in systems]
    ack = set(rules.get("bars_ack") or [])
    out: list[dict] = []
    starts = assign_bars(recs)[0] if recs else []
    for seg in _movements(systems):
        if any(systems[k]["id"] in pick or systems[k]["id"] in split for k in seg):
            continue
        plain, delta = 1, 0
        for j, k in enumerate(seg):
            d = int(starts[k]) - plain
            if d != delta:
                m = {"id": systems[k]["id"], "prev": systems[seg[j - 1]]["id"] if j else None,
                     "counted": plain, "printed": int(starts[k])}
                m["key"] = f"{m['id']}:{m['counted']}:{m['printed']}"
                if m["key"] not in ack:
                    out.append(m)
                delta = d
            plain += recs[k]["nbars"]
    return out


def mismatch_text(m: dict) -> str:
    where = f" (after {m['prev']})" if m.get("prev") else ""
    return (f"{m['id']}{where}: the barlines count bar {m['counted']}, the printed "
            f"numbers of the source say bar {m['printed']}")


def renumber(lay: dict) -> str:
    """Set `bar` and `marks` of every system in a layout from its stored
    widths, repeats, anchors and `bar_rules` (with the bar edits applied).
    Returns the anchor scheme."""
    systems = lay.get("systems") or []
    eff = effective_systems(systems, lay.get("bar_rules"))
    starts, marks, scheme = number_bars(eff, lay.get("bar_rules"))
    nums = bar_numbers(eff, starts, lay.get("bar_rules"))
    marks = apply_mark_rules(eff, marks, nums, lay.get("bar_rules"))
    for e, b, bn in zip(systems, starts, nums):
        e["bar"] = b
        e["bar_nums"] = bn
        m = marks.get(e["id"])
        if m:
            e["marks"] = m
        else:
            e.pop("marks", None)
    return scheme
