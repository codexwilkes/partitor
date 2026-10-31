# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""Staff label to part map."""
from __future__ import annotations

import difflib
import itertools
import re


_NUMERALS = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "1": 1, "2": 2,
             "3": 3, "4": 4, "5": 5}


def norm_tokens(text: str) -> list[str]:
    t = re.sub(r"[^\w\s]", " ", text.lower())
    return [x for x in t.split() if x]


def label_match(label: str, name: str) -> float:
    """label_match -> 0..1 similarity of a printed label and a part name.

    Numbers (I/II/III, 1/2/3) must agree when both have one. A short label
    (T1, A, B) matches by first letter plus number."""
    lt, nt = norm_tokens(label), norm_tokens(name)
    if not lt or not nt:
        return 0.0
    # continuo names are one part: Continuo, Basso continuo, Organo, B.C.
    # (Biber: "Continuo" on later systems, "Organo BC" on page 1)
    if CONTINUO_RE.search(label) and CONTINUO_RE.search(name):
        return 1.0
    ln = {_NUMERALS[x] for x in lt if x in _NUMERALS}
    nn = {_NUMERALS[x] for x in nt if x in _NUMERALS}
    m = re.fullmatch(r"([a-z]+)(\d)", lt[0])
    if m:                                   # "t1" -> letter t, number 1
        ln.add(int(m.group(2)))
        lt = [m.group(1)] + lt[1:]
    if ln and nn and ln != nn:
        return 0.0
    if len(lt[0]) <= 2 and nt[0].startswith(lt[0]):
        return 0.9 if (ln == nn) else 0.6
    words = [x for x in lt if x not in _NUMERALS]
    names = [x for x in nt if x not in _NUMERALS]
    if not words or not names:
        return 0.0
    best = max(difflib.SequenceMatcher(None, a, b).ratio()
               for a in words for b in names)
    # an abbreviation: its letters in order in a name word with the same
    # first letter ("Vla" Viola, "Cornet" Cornetto), or the end of a
    # compound ("Pos" in "Altposaune"; numbers or the staff order decide)
    for a in words:
        for b in names:
            if len(a) >= 2 and a[0] == b[0] and _subseq(a, b):
                best = max(best, 0.8)
            elif len(a) >= 3 and a in b and not b.startswith(a):
                best = max(best, 0.7)
    return best if (ln == nn or not ln or not nn) else best * 0.8


def _subseq(a: str, b: str) -> bool:
    """True when the letters of a stand in b in the same order."""
    it = iter(b)
    return all(ch in it for ch in a)


CONTINUO_RE = re.compile(r"continuo|\bb\.?\s*c\.?\b|organ|cembalo|harpsichord|"
                         r"theorb|lute|basso\s+generale", re.IGNORECASE)


# =============================================================================
# Part mapping (per system)
# =============================================================================
def build_reference(sysrecs: list[dict], parts: list[str]) -> tuple[list[str], list[str], dict]:
    """build_reference -> (slot names, slot clefs, reference system record).

    The reference is the system with the most printed labels, then the
    most staves, then the first. Slot names come
    from --parts (one per staff; a repeated name = a two-staff part), else
    from its labels (a repeated label gets a number: two parts); an
    unlabeled staff in the same brace as a labeled one takes that name
    (a two-staff part); else "Staff N"."""
    # the system with the most printed labels (page 1 names every part),
    # then the most staves: a stray system with an extra staff (Biber p53,
    # small systems joined) no longer names the parts (0.3.0-dev.21)
    ref = max(sysrecs, key=lambda r: (sum(1 for x in r["labels"] if x.strip()),
                                      len(r["staves"]), -sysrecs.index(r)))
    n = len(ref["staves"])
    if parts and len(parts) == n:
        names = list(parts)
    else:
        names = [lbl.strip() for lbl in ref["labels"]]
        # Two staves with the same printed label (e.g. "Basso Trombone" and
        # "[Basso] Trombone") are two parts: number them.
        seen: dict[str, int] = {}
        for nm in names:
            if nm:
                seen[nm] = seen.get(nm, 0) + 1
        count: dict[str, int] = {}
        for i, nm in enumerate(names):
            if nm and seen[nm] > 1:
                count[nm] = count.get(nm, 0) + 1
                names[i] = f"{nm} {count[nm]}"
        for i, nm in enumerate(names):
            if not nm and ref["braces"][i] >= 0:
                for j, other in enumerate(names):
                    if other and ref["braces"][j] == ref["braces"][i]:
                        names[i] = other
                        break
        names = [nm if nm else f"Staff {i + 1}" for i, nm in enumerate(names)]
    return names, list(ref["clefs"]), ref


def map_system(rec: dict, slots: list[str], slot_clefs: list[str],
               prev: list[int] | None, slot_braces: list[int] | None = None
               ) -> tuple[list[int], float, float]:
    """map_system -> (slot index per staff, best cost, second-best cost).

    Tries every ordered subset of the reference slots (a reduced system
    keeps score order). Cost per staff: label mismatch 2.0 (no label 0.3
    plus 0.3 per position away from bottom alignment, at most 0.9:
    continuo and bass sit at the bottom), clefs a hint (below), same
    slot as the previous system -0.2; a part in the previous system -0.4
    (also when the staff count changes; 0.3.0-dev.12); clef of another
    family +0.8, another line of the same clef +0.3 (clefs are often
    misread); a braced pair on slots not braced in the reference +1.0, the
    reverse +0.2 (braces are often missed); when the reference's lowest
    part is a continuo, a bottom staff on another part +1.0 and the
    continuo on a higher staff +1.0 (0.3.0-dev.21)."""
    n, m = len(rec["staves"]), len(slots)
    if n > m:
        return [], float("inf"), float("inf")
    # the continuo (Continuo, Basso continuo, Organo, B.C.) is the lowest
    # staff of a system (operator request 2026-10-25): the bottom staff takes it,
    # no other staff does
    cont = m - 1 if CONTINUO_RE.search(slots[-1] or "") else None
    costs = []
    for combo in itertools.combinations(range(m), n):
        c = 0.0
        if cont is not None:
            if combo[-1] != cont:
                c += 1.0
            if cont in combo[:-1]:
                c += 1.0
        for k, j in enumerate(combo):
            lbl = rec["labels"][k]
            if lbl:
                c += 0.0 if label_match(lbl, slots[j]) >= 0.7 else 2.0
            else:
                # bottom alignment, capped: in a short system it outweighed
                # the labels below (Biber p46: violins above "Vla I")
                c += 0.3 + min(0.9, 0.3 * abs((n - 1 - k) - (m - 1 - j)))
            ck, cj = rec["clefs"][k], slot_clefs[j]
            if not _clef_same(ck, cj):
                # another clef family (G / C / F) weighs more than another
                # line of the same clef (often a misread)
                c += 0.8 if ck[:1] != cj[:1] else 0.3
            if prev is not None:
                if len(prev) == n and prev[k] == j:
                    c -= 0.2
                if j in prev:           # the part goes on from the system before
                    c -= 0.4
        # braces: two staves in one brace (keyboard, continuo) map to two
        # slots in one brace of the reference, and the reverse (Schein Nun
        # p3.s1: misread clefs took the braced continuo for two trombones)
        rb = rec.get("braces") or []
        if slot_braces and len(rb) == n:
            for k in range(n - 1):
                br = rb[k] >= 0 and rb[k] == rb[k + 1]
                j1, j2 = combo[k], combo[k + 1]
                bs = slot_braces[j1] >= 0 and slot_braces[j1] == slot_braces[j2]
                if br and not bs:
                    c += 1.0            # a brace found is a strong sign
                elif bs and not br:
                    c += 0.2            # a brace missed is common
        costs.append((c, combo))
    costs.sort(key=lambda t: t[0])
    best = costs[0]
    second = costs[1][0] if len(costs) > 1 else float("inf")
    return list(best[1]), best[0], second


def _clef_same(x: str, y: str) -> bool:
    """Same clef for the mapping: '?' is any; G2 and G8 are one (the 8 is
    often missed; Maria p3.s1 G2 after G8 asked again)."""
    g = {"G2", "G8"}
    return x == "?" or y == "?" or x == y or (x in g and y in g)


def clefs_compatible(a: list[str], b: list[str]) -> bool:
    """True when no staff has two different, both-read clefs ('?' = any)."""
    return len(a) == len(b) and all(_clef_same(x, y) for x, y in zip(a, b))


def assign_maps(sysrecs: list[dict], parts: list[str]) -> tuple[list[str], list[dict]]:
    """assign_maps -> (part names in score order, system entries for the
    layout). Uncertain systems get map '?' entries plus `suggest`."""
    slots, slot_clefs, ref = build_reference(sysrecs, parts)
    out = []
    prev = None
    prev_rec: dict | None = None
    prev_certain = False
    for rec in sysrecs:
        n = len(rec["staves"])
        entry = {"id": rec["id"], "staves": n}
        same_as_prev = (prev_rec is not None and prev_certain and prev is not None
                        and len(prev_rec["staves"]) == n
                        and clefs_compatible(rec["clefs"], prev_rec["clefs"])
                        and not any(rec["labels"]))
        if rec is ref:
            idx = list(range(n))
            entry["map"] = [slots[j] for j in idx]
            entry["why"] = "reference"
        elif same_as_prev:
            # continuity: same staff count, compatible clefs, no new labels
            # (editions print a label when the part on a staff changes)
            idx = list(prev)
            entry["map"] = [slots[j] for j in idx]
            entry["why"] = "same as previous system"
        else:
            idx, best, second = map_system(rec, slots, slot_clefs, prev,
                                           ref.get("braces"))
            if not idx:
                entry["map"] = ["?"] * n
                entry["why"] = f"more staves than the reference ({len(slots)})"
                idx = None
            else:
                names = [slots[j] for j in idx]
                labelled = [k for k, lb in enumerate(rec["labels"]) if lb]
                all_match = bool(labelled) and all(
                    label_match(rec["labels"][k], names[k]) >= 0.7 for k in labelled)
                certain = (n == len(slots)) or (second - best >= 1.0) or \
                          (all_match and second - best >= 0.25)
                # the same parts as the certain system before (one clef
                # misread breaks "same as previous"; Schein Nun p3, p6-p7)
                goes_on = (not certain and prev_certain and prev is not None
                           and idx == list(prev) and second - best >= 0.3)
                if certain or goes_on:
                    entry["map"] = names
                    entry["why"] = ("continues previous system" if goes_on else
                                    "labels/clefs" if any(rec["labels"]) else "clefs/order")
                else:
                    entry["map"] = ["?"] * n
                    entry["suggest"] = names
                    entry["why"] = f"uncertain (cost {best:.1f} vs {second:.1f})"
        if rec["labels"] and any(rec["labels"]):
            entry["labels"] = rec["labels"]
        entry["clefs"] = rec["clefs"]
        out.append(entry)
        prev = idx
        prev_rec = rec
        prev_certain = idx is not None and "?" not in entry["map"]
    return list(dict.fromkeys(slots)), out
