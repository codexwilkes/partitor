# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""The parts and groups commands, the ambitus menu and the short-name menu."""
from __future__ import annotations

import argparse
import re
import time
from pathlib import Path

from .clef import ambitus_report, part_clefs
from .cli_common import _item_or_die, cmd_set, saved
from .config import PART_LAYOUT_KEY, SKIP_KEY
from .console import Abort, DIM, RST, YLW, _die, _fail, _head, _ok, _reset_counts, _warn, ask
from .library import item_file, load_item, mark_pending, merge_item_keys, part_names, save_item
from .mapping import clefs_compatible
from .proof import _proof_pages, annotate_proof, proof_from_preview


def reference_names(data: dict) -> str:
    """reference_names -> --parts for detect: one name per staff of the
    fullest system, from its map ('-' for a staff left out, a name twice
    for a two-staff part). The parts list alone has fewer names when a
    staff is left out or joined, and detect then fell back to the printed
    labels (Maria: "Canto I Yoce"; the operator's names, groups lost)."""
    systems = data.get("systems") or []
    if systems:
        ref = max(systems, key=lambda e: (len(e.get("map") or []), -systems.index(e)))
        m = ref.get("map") or []
        if m and "?" not in m:
            return ",".join(m)
    return ",".join(data.get("parts") or [])



def reanalyse(item: Path) -> int:
    """reanalyse -> 0 or 1: detect again and put back the operator's names,
    groups, skip list, ambitus, settings and system joins; previous answers
    become the suggestions of systems still uncertain. No question is asked.
    A failure is reported and the proof is drawn for it."""
    from .build import run_detect          # lazy: light commands load no image package
    data = load_item(item)
    rc = run_detect(item, data.get("pages"), data.get("title", ""),
                    data.get("composer", ""), reference_names(data))
    if rc:
        _reset_counts()
        if (item / "preview").is_dir():
            proof_from_preview(item)       # one place to look, also after a failure
        _fail(f"analyse:  {item.name} failed (see above; proof: "
              f"{item_file(item, 'proof.pdf').name})")
        return 1
    keep = {**data}
    if data.get("built"):
        keep["pending"] = list(data.get("pending") or []) + ["analysed again"]
    merge_item_keys(item, keep, again=True)
    proof_from_preview(item)
    _reset_counts()
    return 0


def system_cut(data: dict, system_id: str) -> str:
    """system_cut -> 'p5:4' for the end of a system: the page and the number of
    staves down to its last staff (from the top, from 1), the form of
    `system_joins`. '' when the id is unknown or no system follows it on the
    page (a join needs the system below)."""
    m = re.fullmatch(r"p(\d+)\.s(\d+)", system_id or "")
    if not m:
        return ""
    pno, sno = int(m.group(1)), int(m.group(2))
    on_page = [x for x in data.get("systems") or [] if x.get("id", "").startswith(f"p{pno}.")]
    if not 1 <= sno < len(on_page):
        return ""
    return f"p{pno}:{sum(int(x.get('staves') or 0) for x in on_page[:sno])}"


def set_join(item: Path, cut: str, on: bool = True) -> str:
    """set_join -> '' or an error: add (on) or remove a join ('p5:4') in the
    item's `system_joins`. The analysis is not run here."""
    if not re.fullmatch(r"p[1-9]\d*:[1-9]\d*", cut or ""):
        return f"not a join: {cut!r} (p5:4 = no system ends after staff 4 of page 5)"
    data = load_item(item)
    joins = list(data.get("system_joins") or [])
    if on and cut in joins:
        return f"{cut} is joined already"
    if not on and cut not in joins:
        return f"{cut} is not joined"
    if on:
        joins.append(cut)
    else:
        joins.remove(cut)
    if joins:
        data["system_joins"] = sorted(joins, key=lambda t: tuple(int(x) for x in t[1:].split(":")))
    else:
        data.pop("system_joins", None)
    save_item(item, data)
    return ""


def confirm_ambitus(item: Path) -> None:
    """After an analysis (interactive): each part with a doubtful computed
    extreme is shown with its bars (ringed on the proof); Enter accepts,
    or a range (G3-E5), off or auto. Answers are kept as by hand."""
    data = load_item(item)
    asks = []
    for part, a_ in (data.get("ambitus") or {}).items():
        if a_.get("from") not in ("auto", "on"):
            continue
        rep_ = ambitus_report(data, part)
        if rep_["doubts"]:
            asks.append((part, a_.get("range") or "none", rep_))
    if not asks:
        return
    _head(f"Ambitus: {len(asks)} part(s) to check (green rings on the proof)")
    for part, rng, rep_ in asks:
        print(f"\n  {part}: {rng} as read")
        for d_ in rep_["doubts"]:
            print(f"     {YLW}? {d_}{RST}")
        sug = rep_.get("suggest")
        if sug:
            print(f"     suggested: {sug}  ({rep_['why']})")
            v = ask(f"Enter = {sug}, k = keep {rng}, or the range (e.g. G3-E5), off", "")
            if not v:
                v = sug
            elif v.lower() == "k":
                continue
        else:
            v = ask("Enter = accept, or the range (e.g. G3-E5), off", "")
        if v:
            try:
                cmd_set(argparse.Namespace(id=data["id"], pairs=[f"{part}:ambitus={v}"],
                                           build=False))
            except SystemExit:
                pass


def show_parts(data: dict) -> None:
    clefs = part_clefs(data)
    skip = set(data.get(SKIP_KEY) or [])
    for i, p in enumerate(data.get("parts") or [], 1):
        note = f"  {DIM}— not extracted{RST}" if p in skip else ""
        print(f"     {i}  {p}  ({clefs.get(p, '?')} clef){note}")


def system_where(data: dict, e: dict) -> str:
    """'source page 8, system 2 of 3 (proof page 1)' for a system entry."""
    m = re.fullmatch(r"p(\d+)\.s(\d+)", e.get("id", ""))
    if not m:
        return e.get("id", "")
    pno, sno = int(m.group(1)), int(m.group(2))
    n_on = sum(1 for x in data.get("systems") or [] if x.get("id", "").startswith(f"p{pno}."))
    pages = _proof_pages(data)
    pp = f" (proof page {pages.index(pno) + 1})" if pno in pages else ""
    return f"source page {pno}, system {sno} of {n_on} from the top{pp}"


def choose_maps(item: Path) -> bool:
    """Ask for every system marked '?'. For each: where it is (source and
    proof page, red frame on the proof), its clefs and printed labels, and
    the suggestion. Answer: Enter = suggestion, or one part number per
    staff, top staff first ('2 3 4'; 0 leaves a staff out), or j: the
    system and the one below it on the page are one system (the analysis
    took them apart; it is run again and the questions start over). True
    when all systems are set."""
    while True:
        again = _choose_maps(item)
        if again is not None:
            return again


def _choose_maps(item: Path) -> bool | None:
    """One round of choose_maps: True when all are set; None when the
    operator joined two systems and the analysis ran again."""
    data = load_item(item)
    parts = data.get("parts") or []
    todo = [s_ for s_ in data.get("systems", []) if "?" in s_.get("map", [])]
    if not todo:
        return True
    _head(f"Choices: {len(todo)} system(s) need their parts")
    print("     proof.pdf (item folder) frames these systems in red and labels")
    print("     every staff with its part. Parts and their clefs:")
    show_parts(data)
    for k, s_ in enumerate(todo, 1):
        n = s_["staves"]
        sug = s_.get("suggest") or []
        clefs = s_.get("clefs") or []
        labels = [x for x in (s_.get("labels") or []) if x]
        while True:
            print(f"\n  [{k}/{len(todo)}] {s_['id']}: {system_where(data, s_)}")
            print(f"     {n} staves, clefs top to bottom: {' '.join(clefs) or '?'}"
                  + (f"; printed labels: {', '.join(labels)}" if labels else ""))
            if len(sug) == n:
                nums = [str(parts.index(x) + 1) if x in parts else ("0" if x == "-" else "?")
                        for x in sug]
                shown = ["(left out)" if x == "-" else x for x in sug]
                print(f"     suggestion: {', '.join(shown)}  (= {' '.join(nums)})")
            ans = ask(f"part number for each of the {n} staves, top first "
                      "(Enter = suggestion; 0 = leave out; same number twice = "
                      "one part on two staves; j = join with the system below; "
                      "q = stop, continue later with rebuild)")
            if ans.strip().lower() == "j":
                cut = system_cut(data, s_["id"])
                if not cut:
                    print(f"     {YLW}no system below {s_['id']} on its page to join{RST}")
                    continue
                err = set_join(item, cut)
                if err:
                    print(f"     {YLW}{err}{RST}")
                    continue
                _ok(f"join:  {s_['id']} and the system below it are one system ({cut}); "
                    "analysing again")
                if reanalyse(item):
                    raise Abort()
                return None
            if not ans and len(sug) == n:
                s_["map"] = list(sug)
                break
            nums = ans.replace(",", " ").split()
            if len(nums) == n and all(x.isdigit() and int(x) <= len(parts) for x in nums):
                s_["map"] = [parts[int(x) - 1] if int(x) else "-" for x in nums]
                break
            sn = [str(parts.index(x) + 1) if x in parts else ("0" if x == "-" else "?")
                  for x in sug] if len(sug) == n else []
            ex = " ".join(sn) if sn and "?" not in sn else " ".join(["1"] * n)
            print(f"     {YLW}need {n} numbers from 0 to {len(parts)}, one per staff, "
                  f"e.g. {ex} (0 = staff left out), or j to join{RST}")
        # the answer becomes the suggestion for the systems still to come
        # with the same staff count and clefs (operator request 2026-10-24: they kept
        # the wrong suggestion)
        if s_["map"] != sug:
            for later in todo[k:]:
                if later["staves"] == n and clefs_compatible(later.get("clefs") or [], clefs):
                    later["suggest"] = list(s_["map"])
        save_item(item, data)
    annotate_proof(item)
    return True


PART_OPS = re.compile(r"^\s*(\d+)\s*(?:(\+)\s*(\d+)|=\s*(.+?))\s*$")


def apply_part_ops(data: dict, line: str) -> str:
    """apply_part_ops -> '' or an error. One line of operations on the
    parts list, separated by ';', all numbered as the list is now:
      N=name   rename part N
      N=-      do not extract part N (no PDF); it stays in the list, so
               its staves can still be identified in choices
      N=+      extract part N again
      N+M      join part N into part M: one part on two staves (piano,
               organ); M keeps its name
    Maps and suggestions follow; nothing changes when one item is bad."""
    parts = list(data.get("parts") or [])
    ren: dict[int, str] = {}
    drop: set[int] = set()
    undrop: set[int] = set()
    join: dict[int, int] = {}
    for op in (x for x in line.split(";") if x.strip()):
        m = PART_OPS.match(op)
        if not m:
            return f"not understood: {op.strip()} (N=name, N=-, N+M)"
        n = int(m.group(1))
        if not 1 <= n <= len(parts):
            return f"no part {n} (1-{len(parts)})"
        if m.group(2):
            t = int(m.group(3))
            if not 1 <= t <= len(parts) or t == n:
                return f"cannot join {n} into {t}"
            join[n - 1] = t - 1
        elif m.group(4).strip() == "-":
            drop.add(n - 1)
        elif m.group(4).strip() == "+":
            undrop.add(n - 1)
        else:
            ren[n - 1] = m.group(4).strip()
    if set(join) & set(join.values()) or drop & undrop:
        return "a part cannot be joined twice, or left out and extracted at once"
    keep = [k for k in range(len(parts)) if k not in join]
    new_name = {k: ren.get(k, parts[k]) for k in keep}
    if len(set(new_name.values())) != len(new_name):
        return "two parts would have the same name"
    skipped = {k for k in keep if parts[k] in set(data.get(SKIP_KEY) or [])}
    skipped = (skipped | drop) - undrop
    if not [k for k in keep if k not in skipped]:
        return "at least one part must be extracted"
    target = {parts[k]: new_name[k] for k in keep}
    for k, t in join.items():
        target[parts[k]] = new_name.get(t, parts[t])
    data["parts"] = [new_name[k] for k in keep]
    data[SKIP_KEY] = [new_name[k] for k in keep if k in skipped]
    if not data[SKIP_KEY]:
        data.pop(SKIP_KEY)
    for s_ in data.get("systems") or []:
        s_["map"] = [target.get(x, x) for x in s_.get("map") or []]
        if s_.get("suggest"):
            s_["suggest"] = [target.get(x, x) for x in s_["suggest"]]
    pl = (data.get("layout") or {}).get(PART_LAYOUT_KEY)
    if pl:                                  # per-part layout follows a rename
        data["layout"][PART_LAYOUT_KEY] = {
            (new_name[parts.index(n)] if n in parts and parts.index(n) in new_name else n): v
            for n, v in pl.items()}
    return ""


def rename_parts(item: Path) -> list[str] | None:
    """Part names: operations as in apply_part_ops (rename, leave out,
    join two staves into one part), shown again after each line; a comma
    list replaces all names; Enter = done. A comma list with a different
    number of names needs detect again: returns that list then (the
    caller re-runs detect), else None."""
    data = load_item(item)
    while True:
        _head("Parts (names come from the printed labels)")
        show_parts(data)
        print("     N=name rename   N=- do not extract   N=+ extract again   "
              "N+M join N into M (two staves, e.g. piano)   ; between several")
        ans = ask("change (Enter = done)", "")
        if not ans:
            break
        if any(c in ans for c in "=+"):
            err = apply_part_ops(data, ans)
            if err:
                print(f"     {YLW}{err}{RST}")
                data = load_item(item)
                continue
        else:
            parts = list(data.get("parts") or [])
            new = [x.strip() for x in ans.split(",") if x.strip()]
            if len(new) != len(parts):
                return new
            err = apply_part_ops(data, ";".join(f"{k}={v}" for k, v in
                                                enumerate(new, 1)))
            if err:
                print(f"     {YLW}{err}{RST}")
                data = load_item(item)
                continue
        save_item(item, data)
    annotate_proof(item)
    return None


def cmd_parts(a: argparse.Namespace) -> int:
    """parts <id>: rename parts one at a time; saved, not built."""
    start = time.monotonic()
    item = _item_or_die(a.id)
    before = load_item(item)
    try:
        new = rename_parts(item)
    except Abort:
        return 0
    if new:
        _die(f"{len(new)} names for {len(before.get('parts') or [])} parts",
             "Rename with number=name; a different number of parts needs "
             "partitor rebuild after detect (new item).")
    data = load_item(item)
    if data.get("parts") == before.get("parts") and data.get(SKIP_KEY) == before.get(SKIP_KEY):
        return 0
    mark_pending(data, "part names")
    save_item(item, data)
    _ok(f"parts:  {', '.join(data['parts'])}")
    return saved(item, a, start)


def apply_group_op(data: dict, line: str) -> str:
    """apply_group_op -> '' or an error. 'Name=4,5,6' sets group Name to
    parts 4, 5, 6 (numbers of the parts list; score order is kept);
    'Name=' deletes it."""
    name, eq, nums = line.partition("=")
    name = name.strip()
    if not eq or not name:
        return "use Name=4,5,6 (or Name= to delete)"
    parts = data.get("parts") or []
    groups = dict(data.get("groups") or {})
    if not nums.strip():
        if name not in groups:
            return f"no group {name}"
        groups.pop(name)
    else:
        try:
            ks = sorted({int(x) for x in nums.replace(" ", ",").split(",") if x.strip()})
        except ValueError:
            return "part numbers, e.g. 4,5,6"
        if not ks or not all(1 <= k <= len(parts) for k in ks):
            return f"part numbers from 1 to {len(parts)}"
        if name in parts:
            return f"{name} is already a part name"
        groups[name] = [parts[k - 1] for k in ks]
    data["groups"] = groups
    if not groups:
        data.pop("groups")
    return ""


def cmd_groups(a: argparse.Namespace) -> int:
    """groups <id>: group scores (DESIGN.md §4.3 item 11): a group prints
    the staves of its parts together, joined by a bracket (for example the
    trombones without voices and organ). Saved, not built."""
    start = time.monotonic()
    item = _item_or_die(a.id)
    data = load_item(item)
    before = dict(data.get("groups") or {})
    try:
        while True:
            _head(f"Groups: {data.get('id')}")
            show_parts(data)
            for gname, ps in (data.get("groups") or {}).items():
                print(f"     group {gname}: {', '.join(ps)}")
            print("     Name=4,5,6 set a group   Name= delete   Enter = done")
            ans = ask("change", "")
            if not ans:
                break
            err = apply_group_op(data, ans)
            if err:
                print(f"     {YLW}{err}{RST}")
    except Abort:
        return 0
    if (data.get("groups") or {}) == before:
        return 0
    mark_pending(data, "groups")
    save_item(item, data)
    _ok(f"groups:  {', '.join(data.get('groups') or {}) or '(none)'}")
    return saved(item, a, start)


def ask_part(data: dict) -> str | None:
    """ask_part -> one part or group by number, None for all (Enter)."""
    names = part_names(data)
    print("  " + "  ".join(f"{i} {n}" for i, n in enumerate(names, 1)))
    while True:
        v = ask("part (Enter = all parts)", "")
        if not v:
            return None
        if v.isdigit() and 1 <= int(v) <= len(names):
            return names[int(v) - 1]
        if v in names:
            return v
        _warn(f"part:  no part {v}")


def ambitus_menu(data: dict) -> None:
    """Menu key k: each part's ambitus, numbered; pick one and give
    LOW-HIGH (C4-F5, F#3-Bb4; # sharp, b flat), auto (read from the notes), off or on (a continuo
    part). Saved, not built; the proof is redrawn."""
    amb = data.get("ambitus") or {}
    names = [p for p in data.get("parts") or [] if p in amb]
    if not names:
        _warn("ambitus:  none yet (analyse again with partitor 0.3.0-dev.15 or later)")
        return
    for i, p_ in enumerate(names, 1):
        a_ = amb[p_]
        frm = a_.get("from", "auto")
        rp = ambitus_report(data, p_) if frm in ("auto", "on") else {"low": [], "high": [],
                                                                     "doubts": [], "low_at": []}
        bars = (f"  low {'; '.join(rp.get('low_at', [])[:2]) or '?'}; high "
                f"{'; '.join(rp.get('high_at', [])[:2]) or '?'}") if rp.get("low_at") else ""
        print(f"  {i}  {p_}: {a_.get('range') or 'none'}{bars}"
              + ("" if frm == "auto" else f"  ({'by hand' if frm == 'operator' else frm})"))
        for d_ in rp["doubts"]:
            print(f"       {YLW}? {d_}{RST}")
        if rp.get("suggest"):
            print(f"       suggested: {rp['suggest']}  ({rp['why']})")
    while True:
        v = ask("part (Enter = done)", "")
        if not v:
            return
        part = names[int(v) - 1] if v.isdigit() and 1 <= int(v) <= len(names) else (
            v if v in names else None)
        if part is None:
            _warn(f"ambitus:  no part {v}")
            continue
        val = ask(f"{part}: LOW-HIGH (e.g. C4-F5, F#3-Bb4), auto, off or on (Enter = no change)", "")
        if not val:
            continue
        cmd_set(argparse.Namespace(id=data["id"], pairs=[f"{part}:ambitus={val}"], build=False))
        data = load_item(_item_or_die(data["id"]))
        amb = data.get("ambitus") or {}


def short_menu(data: dict) -> None:
    """Menu key h: the short form of each group staff label, numbered (the
    custom form, else the rule's); pick one and give the new text, or auto
    for the rule. Saved, not built (`set ID "Part:short=..."`)."""
    from .lines import short_name          # here: lines needs numpy and cv2, light commands do not
    members = []
    for g_ in (data.get("groups") or {}).values():
        members += [p_ for p_ in g_ if p_ not in members]
    names = members or [p_ for p_ in data.get("parts") or [] if p_ != "-"]
    if not names:
        _warn("short:  no parts")
        return

    def show(d: dict) -> None:
        own = {n_: (v_ or {}).get("short") for n_, v_ in
               ((d.get("layout") or {}).get(PART_LAYOUT_KEY) or {}).items()}
        for i, p_ in enumerate(names, 1):
            cur = own.get(p_)
            print(f"  {i}  {p_}: {short_name(p_, cur)}" + ("  (by hand)" if cur else "  (rule)"))
    show(data)
    while True:
        v = ask("part (Enter = done)", "")
        if not v:
            return
        part = names[int(v) - 1] if v.isdigit() and 1 <= int(v) <= len(names) else (
            v if v in names else None)
        if part is None:
            _warn(f"short:  no part {v}")
            continue
        val = ask(f"{part}: short form (auto = the rule; Enter = no change)", "")
        if not val:
            continue
        cmd_set(argparse.Namespace(id=data["id"], pairs=[f"{part}:short={val}"], build=False))
        data = load_item(_item_or_die(data["id"]))
        show(data)
