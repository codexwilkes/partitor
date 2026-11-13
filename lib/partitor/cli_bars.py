# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""The bars command."""
from __future__ import annotations

import argparse
import time
from pathlib import Path

from .bars import (
    _boundaries, _flat_bars, _movements, bar_mismatches, effective_systems, format_bar_edit,
    mismatch_text, parse_bar_edit, renumber, toggle_mark,
)
from .cli_common import _item_or_die, bar_summary, locks_item, saved
from .console import Abort, RST, YLW, _head, _note, _ok, _warn, ask, yes
from .library import item_file, load_item, mark_pending, save_item
from .proof import _proof_pages, annotate_proof


def confirm_bar_mismatches(item: Path) -> None:
    """Where the printed bar numbers of the source disagree with the count
    of barlines, ask the operator, one place at a time. The parts should
    follow the source score: Y keeps the printed numbers (recorded, not
    asked again); n leaves it open (the build stops until it is settled:
    mend the barlines with `partitor bars`, or keep the printed numbers)."""
    data = load_item(item)
    rules = dict(data.get("bar_rules") or {})
    ms = bar_mismatches(effective_systems(data.get("systems") or [], rules), rules)
    if not ms:
        return
    _head("Bar numbers: the barline count and the printed numbers differ")
    ack = list(rules.get("bars_ack") or [])
    for m in ms:
        _warn(f"bars:  {mismatch_text(m)}")
        if yes(f"{m['id']}: keep the printed numbers (the source's own numbering)?"):
            ack.append(m["key"])
        else:
            _note(f"{m['id']}: left open. Mend the barlines (partitor bars: j join, a add) "
                  "or keep the printed numbers (k); the build stops until then")
    if ack != list(rules.get("bars_ack") or []):
        rules["bars_ack"] = ack
        data["bar_rules"] = rules
        mark_pending(data, "bar numbers")
        save_item(item, data)


def confirm_bar_rules(item: Path) -> None:
    """Ask about each proposed pickup (a pickup, an incipit or neither) and
    split bar (detect proposes them from bar widths), then renumber and save."""
    confirm_bar_mismatches(item)
    data = load_item(item)
    rules = data.get("bar_rules") or {"pickup": [], "split": [], "fix": {}}
    if data.get("bar_rules_status") == "confirmed":
        return
    keep_p, keep_s = [], []
    keep_i = list(rules.get("incipit") or [])
    if rules.get("pickup") or rules.get("split"):
        _head("Bar numbers (see proof.pdf)")
        for sid in rules.get("pickup") or []:
            ans = ask(f"{sid}: the first bar is short. p = a pickup (bar 0, the next bar is 1); "
                      "i = an incipit (the original notation: kept in the part, no number, "
                      "the next bar is 1); n = neither  [P/i/n]", "p").lower()
            if ans.startswith("i"):
                keep_i.append(sid)
            elif not ans.startswith("n"):
                keep_p.append(sid)
        for key in rules.get("split") or []:
            sid, i = key.split(":")
            if yes(f"{sid}, bar {int(i) + 1}: after a repeat, completes the short bar "
                   "before it. Count the two as one bar?"):
                keep_s.append(key)
    data["bar_rules"] = {**rules, "pickup": keep_p, "split": keep_s,
                         "fix": rules.get("fix") or {}}
    if keep_i:
        data["bar_rules"]["incipit"] = keep_i
    data["bar_rules_status"] = "confirmed"
    renumber(data)
    save_item(item, data)
    print(f"     bars: {bar_summary(data)}")


STUB_SP = 8.0     # a first bar this narrow (a clef, no music) before a repeat start is a stub

BARS_HELP = """\
  Line numbers (N) are the numbers in the list. Bars of a line (I): b N lists them.
  NUMBERS
    k N        keep the printed numbers of the source at line N (when the count
               and the source differ and the source is right)
    f N=B      line N starts at bar B; the lines after it follow (f N= clears)
    p N        pickup: the movement that starts at line N begins at bar 0
    i N        incipit: the first bar of the movement at line N shows the original
               notation. It stays in the part with no number; the next bar is 1.
               (p and i on the same line replace each other; the same command = off)
    s N I      bar I of line N completes the bar before it: both keep one number
               (a bar cut by a line break, a repeat sign or a change of mensuration).
               The same command again = off.   s K  = bar after repeat sign K (below)
  BARLINES (when the proof shows a wrong barline: v)
    j N I      join bar I of line N with the next (remove a false barline).
               A clef stub before a repeat sign (a first bar under 8 sp wide):
               j N 1 - the repeat sign stays.
    a N I [P]  add a barline in bar I of line N, P % from its left edge (50)
    u N        undo the last j / a of line N         b N   list the bars of line N
  REHEARSAL LETTERS (A, B, ... in bar order in each movement)
    m B [B..]  letter on/off at bar number B (the first bar with that number)
    m N:I      letter on/off at bar I of line N (for a number two bars share)
  CHECK
    v [N]      draw proof.pdf now with these edits (not saved yet): bar numbers
               in magenta above the top staff, a tick at each barline, boxed
               letters. N: tells the proof page of line N.
    ?          help with an example            Enter = save and finish
"""

BARS_EXAMPLE = """\
  Example: the last bar of line 21 (p7.s4) is a half bar. Its other half is the
  first bar after the clef and the repeat sign on line 22 (p8.s1, a new
  mensuration). Both halves are bar 48. A letter E marks the start of line 22.
    b 22      bar 1 is only 5.7 sp wide: a clef stub, not a bar
    j 22 1    join the stub with the next bar (the repeat sign stays)
    s 22 1    bar 1 of line 22 completes the bar before it (both are 48)
    m 22:1    letter at bar 1 of line 22 (m 48 would mark the half bar of line 21)
    m 22:2    the automatic letter after a repeat sign now stands on bar 2 of
              line 22 (the first full bar): remove it. The list below each m
              shows where the letters stand.
    v         draw proof.pdf, look at the proof page, then Enter to save
"""


def bar_span_text(nums: list[int]) -> str:
    """'bars 48-50' for counting numbers, 'bars 48 48 49 50' otherwise."""
    if not nums:
        return ""
    if len(nums) == 1:
        return f"bar {nums[0]}"
    if all(b - a == 1 for a, b in zip(nums, nums[1:])):
        return f"bars {nums[0]}-{nums[-1]}"
    return "bars " + " ".join(str(n) for n in nums)


def stub_bar(e: dict) -> bool:
    """A system's first bar is a stub: under STUB_SP wide and ending at a
    repeat start (the clef before the repeat sign, no music)."""
    w = e.get("widths") or []
    return bool(w) and float(w[0]) < STUB_SP and any(
        int(r[0]) == 0 and r[1] == "start" for r in e.get("repeats") or [])


def bars_listing(sy: dict, ef: dict, rules: dict, ln: int) -> list[str]:
    """Lines of `b N`: every bar of line ln with its number, width, printed
    number of the source, split and letter. sy: stored entry (renumbered);
    ef: the entry with the bar edits applied."""
    nums = sy.get("bar_nums") or []
    wd = ef.get("widths") or []
    printed = {int(a[0]): int(a[1]) for a in ef.get("anchors") or []}
    marks = {int(m[0]): m[1] for m in sy.get("marks") or []}
    raw, cur = int(sy.get("bars") or 0), int(ef.get("bars") or 0)
    out = [f"line {ln} {sy['id']}: {cur} bar(s)"
           + (f" (detected {raw})" if raw != cur else "")]
    for i, num in enumerate(nums):
        tags = []
        if f"{sy['id']}:{i}" in (rules.get("split") or []):
            tags.append("completes the bar before it")
        if i in printed:
            tags.append(f"source prints {printed[i]}")
        if i in marks:
            tags.append(f"letter {marks[i]}")
        if i == 0 and stub_bar(ef):
            tags.append(f"clef stub: j {ln} 1")
        out.append(f"   {i + 1}: bar {num}  width {wd[i]:g}" if i < len(wd)
                   else f"   {i + 1}: bar {num}")
        if tags:
            out[-1] += "   " + "; ".join(tags)
    return out


@locks_item
def cmd_bars(a: argparse.Namespace) -> int:
    """bars <id>: set pickups, split bars, barlines, line-start numbers and
    rehearsal letters by hand; saved, not built. v draws proof.pdf with the
    unsaved edits. Each line: one key and a value."""
    start = time.monotonic()
    item = _item_or_die(a.id)
    data = load_item(item)
    systems = data.get("systems") or []
    rules = data.get("bar_rules") or {}
    rules = {**rules, "pickup": list(rules.get("pickup") or []),
             "incipit": list(rules.get("incipit") or []),
             "split": list(rules.get("split") or []), "fix": dict(rules.get("fix") or {}),
             "bar_edits": list(rules.get("bar_edits") or []),
             "bars_ack": list(rules.get("bars_ack") or [])}
    movement_first = [e["id"] for k, e in enumerate(systems) if k == 0 or e.get("restart")]
    line_of = {e["id"]: n_ for n_, e in enumerate(systems, 1)}
    changed = False
    try:
        while True:
            data["bar_rules"] = rules
            renumber(data)
            edit_notes: list[str] = []
            eff = effective_systems(systems, rules, edit_notes)
            cands = []                   # bars after a repeat sign: split candidates
            for seg in _movements(eff):
                flat = _flat_bars(eff, seg)
                for b in _boundaries(eff, seg, flat):
                    k, i = flat[b]
                    cands.append(f"{eff[k]['id']}:{i}")
            ms = bar_mismatches(eff, rules)
            _head(f"Bar numbers: {data.get('id')}")
            for t in edit_notes:
                _warn(f"bars:  {t}")
            for n_, e in enumerate(systems, 1):
                tags = []
                if e["id"] in rules["pickup"]:
                    tags.append("pickup")
                if e["id"] in rules["incipit"]:
                    tags.append("incipit")
                if e["id"] in rules["fix"]:
                    tags.append("fixed")
                if any(parse_bar_edit(t) and parse_bar_edit(t)["sid"] == e["id"]
                       for t in rules["bar_edits"]):
                    tags.append("bars edited")
                bn_ = e.get("bar_nums") or []
                if any(k_.startswith(e["id"] + ":") for k_ in rules["split"]):
                    tags.append("split bar")
                tags += [f"mark {m[1]} at bar {bn_[m[0]]}" for m in (e.get("marks") or [])
                         if m[0] < len(bn_)]
                span = bar_span_text(bn_) if bn_ else f"starts at bar {e['bar']}"
                print(f"  {n_:2d}  {e['id']:7s} {span}"
                      f"{'  (' + ', '.join(tags) + ')' if tags else ''}")
            if ms:
                print(f"  {YLW}The barline count and the printed numbers of the source differ:{RST}")
                for m in ms:
                    ln_ = line_of.get(m['id'], '?')
                    print(f"     line {ln_}: {mismatch_text(m)}")
                    ef_ = eff[ln_ - 1] if isinstance(ln_, int) else {}
                    if ef_ and stub_bar(ef_):
                        print(f"     its first bar is only {float(ef_['widths'][0]):g} sp wide "
                              f"(a clef before a repeat sign, no music): j {ln_} 1 joins it")
                print("     The parts should follow the source. k N keeps the printed numbers; "
                      "j / a mend a barline; s N I joins the two halves of a split bar. "
                      "The build stops until each is settled. ? = help with an example.")
            print(BARS_HELP, end="")
            if cands:
                print("  Repeat signs (s K): " +
                      "  ".join(f"{j}={c}{'*' if c in rules['split'] else ''}"
                                for j, c in enumerate(cands, 1)) + "   (* = on)")
            cmd = ask(">", "").strip()
            if not cmd:
                break
            op, _, arg = cmd.partition(" ")
            try:
                if op == "?":
                    print(BARS_EXAMPLE, end="")
                    continue
                if op == "v":
                    ln_ = int(arg) if arg.strip() else None
                    if not item_file(item, "proof.pdf").is_file():
                        print(f"     {YLW}no proof.pdf: analyse again makes it{RST}")
                        continue
                    annotate_proof(item, data)
                    g_ = (systems[ln_ - 1].get("geom") or {}).get("page") if ln_ else None
                    first_ = (_proof_pages(data) or [1])[0]
                    _ok("proof.pdf drawn with the edits (not saved yet)"
                        + (f": line {ln_} is on proof page {int(g_) - first_ + 1} "
                           f"(source page {g_})" if g_ else ""))
                    continue
                if op == "p":
                    sid = systems[int(arg) - 1]["id"]
                    if sid not in movement_first:
                        print(f"     {YLW}line {arg} does not start a movement{RST}")
                        continue
                    if sid in rules["incipit"]:
                        rules["incipit"].remove(sid)
                    if sid in rules["pickup"]:
                        rules["pickup"].remove(sid)
                    else:
                        rules["pickup"].append(sid)
                elif op == "i":
                    sid = systems[int(arg) - 1]["id"]
                    if sid not in movement_first:
                        print(f"     {YLW}line {arg} does not start a movement{RST}")
                        continue
                    if sid in rules["pickup"]:
                        rules["pickup"].remove(sid)
                    if sid in rules["incipit"]:
                        rules["incipit"].remove(sid)
                    else:
                        rules["incipit"].append(sid)
                elif op == "s":
                    w_ = arg.split()
                    if len(w_) == 2:                       # s N I: bar I of line N
                        ln, i = int(w_[0]), int(w_[1])
                        sy, ef = systems[ln - 1], eff[ln - 1]
                        cur = int(ef.get("bars") or 0)
                        if not 1 <= i <= cur:
                            print(f"     {YLW}line {ln} has {cur} bar(s): bar 1-{cur}{RST}")
                            continue
                        if i == 1 and (ln == 1 or sy.get("restart")):
                            print(f"     {YLW}line {ln} starts a movement: no bar before it{RST}")
                            continue
                        if i == 2 and stub_bar(ef):
                            print(f"     {YLW}bar 1 of line {ln} is a clef stub: join it first "
                                  f"(j {ln} 1), then s {ln} 1{RST}")
                            continue
                        key = f"{sy['id']}:{i - 1}"
                    elif len(w_) == 1 and cands:           # s K: bar after repeat sign K
                        key = cands[int(w_[0]) - 1]
                    else:
                        raise ValueError(arg)
                    if key in rules["split"]:
                        rules["split"].remove(key)
                        print(f"     split off: {key}")
                    else:
                        rules["split"].append(key)
                        print(f"     split on: {key} completes the bar before it")
                elif op == "m":
                    words_ = arg.replace(",", " ").split()
                    if not words_:
                        raise ValueError(arg)
                    for w_ in words_:
                        if ":" in w_:                      # m N:I
                            ln, _, i = w_.partition(":")
                            tgt = (systems[int(ln) - 1]["id"], int(i) - 1)
                            label = f"bar {int(i)} of line {int(ln)}"
                        else:
                            tgt, label = int(w_), f"bar {int(w_)}"
                        try:
                            res = toggle_mark(rules, systems, tgt)
                        except ValueError:
                            print(f"     {YLW}no {label} (bars "
                                  f"{min(min(e.get('bar_nums') or [0]) for e in systems)}-"
                                  f"{max(max(e.get('bar_nums') or [0]) for e in systems)}){RST}")
                            continue
                        print(f"     mark at {label}: {res}")
                        data["bar_rules"] = rules
                        renumber(data)          # the next bar sees the new letters
                        changed = True
                        print("     letters now: " + (", ".join(
                            f"{m_[1]} = bar {e_['bar_nums'][m_[0]]} (line {n_}, bar {m_[0] + 1})"
                            for n_, e_ in enumerate(systems, 1) for m_ in e_.get("marks") or []
                            if m_[0] < len(e_.get("bar_nums") or [])) or "none"))
                elif op in ("j", "a"):
                    w_ = arg.split()
                    ln, n = int(w_[0]), int(w_[1])
                    sy = systems[ln - 1]
                    raw = int(sy.get("bars") or 0)
                    cur = int(eff[ln - 1].get("bars") or 0)
                    if op == "j":
                        if not 1 <= n <= cur - 1:
                            print(f"     {YLW}line {ln} has {cur} bar(s): join needs a bar "
                                  f"1-{cur - 1}{RST}")
                            continue
                        if n == 1 and stub_bar(eff[ln - 1]):
                            print(f"     clef stub joined; the repeat sign stays at the start "
                                  f"of bar 1")
                        rules["bar_edits"].append(format_bar_edit(sy["id"], "j", n, raw))
                    else:
                        pc = int(w_[2]) if len(w_) > 2 else 50
                        if not 1 <= n <= cur or not 5 <= pc <= 95:
                            print(f"     {YLW}line {ln} has {cur} bar(s); place 5-95 %{RST}")
                            continue
                        rules["bar_edits"].append(format_bar_edit(sy["id"], "a", n, raw, pc))
                elif op == "u":
                    sid = systems[int(arg) - 1]["id"]
                    mine = [t for t in rules["bar_edits"]
                            if parse_bar_edit(t) and parse_bar_edit(t)["sid"] == sid]
                    if not mine:
                        print(f"     {YLW}no bar edit on line {arg}{RST}")
                        continue
                    rules["bar_edits"].remove(mine[-1])
                elif op == "b":
                    ln = int(arg)
                    for t_ in bars_listing(systems[ln - 1], eff[ln - 1], rules, ln):
                        print(f"     {t_}")
                    continue
                elif op == "k":
                    sid = systems[int(arg) - 1]["id"]
                    hit = [m for m in ms if m["id"] == sid]
                    if not hit:
                        print(f"     {YLW}no difference at line {arg}{RST}")
                        continue
                    rules["bars_ack"].extend(m["key"] for m in hit)
                elif op == "f":
                    ln, _, val = arg.partition("=")
                    sid = systems[int(ln) - 1]["id"]
                    if val.strip():
                        rules["fix"][sid] = int(val)
                    else:
                        rules["fix"].pop(sid, None)
                else:
                    print(f"     {YLW}unknown: {cmd}   (? = help){RST}")
                    continue
                changed = True
            except (ValueError, IndexError):
                print(f"     {YLW}not understood: {cmd}   (? = help){RST}")
    except Abort:
        pass
    if not changed:
        return 0
    for k_ in ("bar_edits", "bars_ack", "incipit"):
        if not rules.get(k_):
            rules.pop(k_, None)
    data["bar_rules"] = rules
    data["bar_rules_status"] = "confirmed"
    renumber(data)
    mark_pending(data, "bar numbers")
    save_item(item, data)
    annotate_proof(item)                 # proof.pdf shows the saved numbers and letters
    _ok(f"bars:  {bar_summary(data)}")
    return saved(item, a, start)
