# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""Item commands."""
from __future__ import annotations

import argparse
import os
import re
import shutil
import time
from pathlib import Path

import yaml

from . import VERSION
from .clef import ambitus_report, part_clefs
from .cli_bars import confirm_bar_rules
from .cli_common import _cmd_step, _item_or_die, _lib_or_die, bar_summary, saved
from .cli_parts import choose_maps, confirm_ambitus, rename_parts
from .config import (
    LAYOUT_DEFAULTS, PART_LAYOUT_KEY, SCORE_FILE, SKIP_KEY, composer_surname, make_slug,
)
from .console import (
    Abort, BOLD, GRN, RST, YLW, _die, _fail, _head, _note, _ok, _reset_counts, _summary, _warn,
    ask, yes,
)
from .library import (
    PARTS_NEW, PARTS_PREV, REPAGE_KEYS, _id_parts, apply_set, build_names, folder_name,
    id_order, inbox_pdfs, item_dirs, item_file, item_id, item_line, item_status,
    keep_other_parts, library_logo, library_root, load_item, mark_pending, merge_item_keys,
    next_id, parse_parts, part_layout, recover_parts, restore_previous_parts, save_item,
    selection_help, set_name, set_value, suggest_meta, swap_parts,
)
from .proof import annotate_proof, proof_from_preview


def cmd_proof(a: argparse.Namespace) -> int:
    """proof <id>: draw proof.pdf again from the saved score.yaml (part
    names, ambitus, bar numbers, barline ticks, rehearsal letters)."""
    start = time.monotonic()
    item = _item_or_die(a.id)
    if not item_file(item, "proof.pdf").is_file():
        _die("no proof.pdf", f"Run: partitor analyse {item_id(item)}")
    t0 = time.monotonic()
    annotate_proof(item)
    _ok(f"proof.pdf drawn again ({time.monotonic() - t0:.1f} s): {item_file(item, 'proof.pdf').name}")
    return _summary(start)


def cmd_new(a: argparse.Namespace) -> int:
    """new [n]: wizard for an inbox PDF (DESIGN.md §6.2). --jobs: workers of the
    detect and build steps (default PARTITOR_JOBS, else auto)."""
    from . import build
    from .analysis import parse_pages
    from .build import build_report, run_detect
    import pymupdf
    start = time.monotonic()
    jobs = getattr(a, "jobs", None)
    share, lib = _lib_or_die()
    pdfs = inbox_pdfs(share)
    print(f"{BOLD}partitor {VERSION} — new{RST}")
    if not pdfs:
        _warn(f"inbox:  no PDF in {share / 'inbox'}")
        return _summary(start)
    try:
        if a.n:
            k = int(a.n)
        else:
            _head(f"Inbox ({len(pdfs)})")
            for i, p in enumerate(pdfs, 1):
                print(f"     {i}  {p.name}")
            k = int(ask("which PDF", "1") or 1)
        if not 1 <= k <= len(pdfs):
            _die(f"no inbox PDF {k} (1-{len(pdfs)})")
        src = pdfs[k - 1]
        npages = pymupdf.open(src).page_count
        _head(f"Source: {src.name}  ({npages} page{'s' * (npages != 1)})")
        rng = ask("pages (Enter = all; a range such as 8-9)", f"1-{npages}")
        parse_pages(rng, npages)
    except Abort:
        _warn("new:  stopped; the PDF stays in the inbox")
        return _summary(start)
    except ValueError as e:
        _die(str(e))
    title0, comp0 = suggest_meta(src)
    now = time.localtime()
    iid = next_id(lib, now.tm_year, now.tm_mon)
    item = lib / f"{iid}-new"
    item.mkdir()                                  # fails if it exists
    os.replace(src, item / f"{iid}-source.pdf")   # same share: atomic move
    keep = {"id": iid, "slug": "new", "created": time.strftime("%Y-%m-%d")}
    save_item(item, {**keep, "source": src.name})
    print(f"\n  {GRN}✔{RST}  item:  {item.name}  (moved {src.name} here)")
    rc = run_detect(item, rng, "", "", jobs=jobs)
    detected = load_item(item) if item_file(item, SCORE_FILE).is_file() else {}
    if rc or "systems" not in detected:
        _reset_counts()
        if (item / "preview").is_dir():
            proof_from_preview(item)       # the proof shows what failed (gate in red)
        _fail(f"detect:  failed for {item.name}")
        _note(f"Item kept. Retry: partitor rebuild {iid}")
        return _summary(start)
    # title and composer: the score's own text first, then PDF metadata
    t_sug = detected.get("title") or title0
    c_sug = detected.get("composer") or comp0
    short = ""
    try:
        _head("Title and composer (Enter accepts)")
        title = ask("title", t_sug)
        composer = ask("composer, full name (page 1)", c_sug)
        short = ask("composer, short (interior pages)", composer_surname(composer))
    except Abort:
        title, composer = t_sug, c_sug
        _warn("new:  stopped; title and composer kept as suggested")
    slug = make_slug(composer, title)
    final = lib / f"{iid}-{slug}"
    os.replace(item, final)
    item = final
    keep.update(slug=slug, title=title, composer=composer)
    if short and short != composer_surname(composer):
        keep["composer_short"] = short
    data = merge_item_keys(item, keep)
    proof_from_preview(item)
    try:
        new = rename_parts(item)
        if new:
            _note(f"{len(new)} names for {len(data.get('parts') or [])} parts: detecting again")
            if run_detect(item, rng, title, composer, ",".join(new), jobs=jobs):
                _die("detect failed", f"partitor rebuild {iid}")
            merge_item_keys(item, keep)
            proof_from_preview(item)
        choose_maps(item)
        confirm_bar_rules(item)
        confirm_ambitus(item)
        # review, then build now or later (groups, settings first)
        _reset_counts()
        _head(f"Review: {item.name}")
        for line in review_lines(item, load_item(item))[1:]:
            print(line)
        go = yes("Build now? (n: edit first — groups, settings — then menu r)", True)
    except Abort:
        _reset_counts()
        _warn(f"new:  stopped; item {iid} kept (status: {item_status(load_item(item))})")
        _note(f"Continue: partitor rebuild {iid}")
        return _summary(start)
    if not go:
        _ok(f"saved:  {item.name} ({item_status(load_item(item))})")
        _note(f"Edit in the menu (g groups, s set, m title/composer), then r to build; "
              f"or: partitor groups {iid}; partitor rebuild {iid}")
        return _summary(start)
    rc = build.run_build(item, jobs=jobs)
    _reset_counts()
    _head(f"Result: {item.name}")
    if rc:
        _fail(f"build:  failed (see above); item kept. Retry: partitor rebuild {iid}")
    else:
        _ok(f"built:  {item_line(item, load_item(item))}")
        build_report(item)
        maybe_offer_reflow(item)
        _note(f"Parts: {item / 'parts'}   Proof: {item_file(item, 'proof.pdf')}")
    return _summary(start)


def item_matches(item: Path, words: str) -> bool:
    """item_matches -> True when every word (case ignored) is in the item's
    id, folder name, composer, short composer, title, subtitle or parts."""
    try:
        data = load_item(item)
    except (OSError, yaml.YAMLError):
        data = {}
    hay = " ".join([item.name, str(data.get("id", "")), str(data.get("composer", "")),
                    str(data.get("composer_short", "")), str(data.get("title", "")),
                    str(data.get("subtitle", ""))] + [str(p) for p in data.get("parts") or []]
                   ).lower()
    return all(w in hay for w in words.lower().split())


def list_page_size() -> int:
    """Items per menu page: PARTITOR_LIST_PAGE (5-200, default 20; set in
    /etc/default/partitor, passed by the wrapper)."""
    try:
        return min(200, max(5, int(os.environ.get("PARTITOR_LIST_PAGE", "20"))))
    except ValueError:
        return 20


def cmd_list(a: argparse.Namespace) -> int:
    """list [words]: all library items, or those matching every word
    (composer, title, part, id)."""
    _, lib = _lib_or_die()
    words = " ".join(getattr(a, "words", None) or [])
    items = sorted((d for d in item_dirs(lib) if not words or item_matches(d, words)),
                   key=id_order, reverse=True)       # newest first, as the menu
    if not items:
        print("  (no item matches)" if words else "  (library empty)")
    for d in items:
        try:
            print(f"  {item_line(d, load_item(d))}")
        except (OSError, yaml.YAMLError):
            print(f"  {d.name} · (no score.yaml)")
    return 0


def review_lines(item: Path, data: dict) -> list[str]:
    """The review screen (DESIGN.md §6.2): everything a build will use."""
    lay = data.get("layout") or {}
    skip = set(data.get(SKIP_KEY) or [])
    clefs = part_clefs(data)
    joined = {p for p, c in clefs.items() if "+" in c}
    out = [f"{BOLD}{item_line(item, data)}{RST}",
           f"  status:    {item_status(data)}",
           f"  folder:    {item}",
           f"  proof:     {item_file(item, 'proof.pdf').name}",
           f"  source:    pages {data.get('pages', '') or 'all'} of {data.get('source', '')}",
           f"  title:     {data.get('title', '')}",
           f"  subtitle:  {data.get('subtitle', '')}",
           f"  composer:  {data.get('composer', '')}",
           f"  short:     {data.get('composer_short') or composer_surname(data.get('composer', ''))}"
           f"{'' if data.get('composer_short') else '  (from the composer)'}",
           "  parts:"]
    for i, p in enumerate(data.get("parts") or [], 1):
        tags = (["not extracted"] if p in skip else []) + (["two staves"] if p in joined else [])
        a_ = (data.get("ambitus") or {}).get(p) or {}
        if p not in skip:
            frm = a_.get("from", "auto")
            extra = ""
            if frm in ("auto", "on") and a_.get("range"):
                rp = ambitus_report(data, p)
                lb = "; ".join(rp["low_at"][:2])
                hb = "; ".join(rp["high_at"][:2])
                extra = f" [low {lb or '?'}; high {hb or '?'}]" + (" ?" if rp["doubts"] else "")
            tags.append(f"ambitus {a_.get('range') or 'none'}{extra}"
                        + ("" if frm == "auto" else f" ({'by hand' if frm == 'operator' else frm})"))
        out.append(f"     {i}  {p}  ({clefs.get(p, '?')}){'  — ' + ', '.join(tags) if tags else ''}")
    nums = {nm: n for n, nm in build_names(data)}
    for g, ps in (data.get("groups") or {}).items():
        out.append(f"  group:     {g}: {', '.join(ps)}"
                   + (f"  (no. {nums[str(g)]})" if str(g) in nums else ""))
    if data.get("systems"):
        out.append(f"  bars:      {bar_summary(data)}")
        open_ = [e["id"] for e in data["systems"] if "?" in (e.get("map") or [])]
        if open_:
            out.append(f"  choices:   {len(open_)} open ({', '.join(open_[:6])}"
                       f"{' …' if len(open_) > 6 else ''})")
    # settings by their `set` names; pages always shown (operator request 2026-10-24:
    # "how do I view the pages=auto or pages=5 setting?")
    item_lay = {k: v for k, v in lay.items() if k != PART_LAYOUT_KEY}
    out.append("  settings:  " + "  ".join(
        [f"pages={set_value('pages', item_lay.get('page_count'))}"] +
        [f"{set_name(k)}={v}" for k, v in item_lay.items() if k != "page_count"]) +
        "  (others default; partitor set <id> key=value)")
    for pname, pl in (lay.get(PART_LAYOUT_KEY) or {}).items():
        out.append(f"  {pname}:  " + "  ".join(
            f"{set_name(k)}={set_value(set_name(k), v)}" for k, v in pl.items()))
    if data.get("pending"):
        out.append(f"  {YLW}not built: {', '.join(data['pending'])}{RST}")
    b = data.get("built") or {}
    if b.get("parts"):
        out.append(f"  built:     {b.get('date', '')}")
        for r in b["parts"]:
            out.append(f"     {r['part']}: {r['pages']} p  staff {r['staff_mm']:.1f} mm  "
                       f"gap {r['gap']:.1f} sp")
    return out


def cmd_show(a: argparse.Namespace) -> int:
    """show <id>: review before a build."""
    item = _item_or_die(a.id)
    for line in review_lines(item, load_item(item)):
        print(line)
    return 0


def edit_metadata(item: Path) -> list[str]:
    """Title, subtitle, composer (full, for page 1) and the short composer
    (interior pages); Enter keeps each. -> changed keys."""
    data = load_item(item)
    _head("Title and composer (Enter keeps)")
    changed = []
    for key, prompt in (("title", "title"), ("subtitle", "subtitle (- = none)"),
                        ("composer", "composer, full name (page 1)")):
        v = ask(prompt, data.get(key, ""))
        v = "" if v == "-" else v
        if v != data.get(key, ""):
            data[key] = v
            changed.append(key)
    short0 = data.get("composer_short") or composer_surname(data.get("composer", ""))
    v = ask("composer, short (interior pages)", short0)
    if v != short0 or (data.get("composer_short") and v != data["composer_short"]):
        data["composer_short"] = v
        changed.append("composer_short")
    if changed:
        mark_pending(data, *changed)
        save_item(item, data)
    return changed


def rename_item(lib: Path, item: Path) -> Path:
    """rename_item -> the item folder renamed to match its composer and
    title (operator request 2026-10-25: a corrected title left the old spelling in
    the folder name). The id stays; the files inside are named by id and
    stay; `slug` follows. Raises ValueError when the name is taken."""
    data = load_item(item)
    dst = lib / folder_name(item, data)
    if dst == item:
        return item
    if dst.exists():
        raise ValueError(f"{dst.name} exists")
    os.replace(item, dst)
    data["slug"] = dst.name[len(item_id(dst)) + 1:]
    save_item(dst, data)
    return dst


def cmd_rename(a: argparse.Namespace) -> int:
    """rename <id>: the folder name follows the composer and title."""
    start = time.monotonic()
    _, lib = _lib_or_die()
    item = _item_or_die(a.id)
    old = item.name
    try:
        dst = rename_item(lib, item)
    except (ValueError, OSError) as e:
        _die(f"rename: {e}")
    if dst == item:
        _ok(f"rename:  {old}  (already matches title and composer)")
    else:
        _ok(f"rename:  {old} -> {dst.name}  (files keep their id names; no build needed)")
    return _summary(start)


def offer_rename(item: Path) -> Path:
    """After a title or composer change: offer the matching folder name."""
    data = load_item(item)
    want = folder_name(item, data)
    if want == item.name:
        return item
    if not yes(f"Folder name: {item.name} -> {want}?", True):
        _note(f"folder kept; later: partitor rename {data.get('id', item_id(item))}")
        return item
    try:
        dst = rename_item(item.parent, item)
    except (ValueError, OSError) as e:
        _warn(f"rename:  {e}")
        return item
    _ok(f"rename:  {item.name} -> {dst.name}")
    return dst


def cmd_meta(a: argparse.Namespace) -> int:
    """meta <id>: title, subtitle, composer, short composer; saved, not
    built. A changed title or composer offers the matching folder name."""
    start = time.monotonic()
    item = _item_or_die(a.id)
    try:
        changed = edit_metadata(item)
    except Abort:
        return 0
    if not changed:
        return 0
    _ok(f"meta:  {', '.join(changed)}")
    try:
        item = offer_rename(item)
    except Abort:
        pass
    return saved(item, a, start)


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


def analyse_item(item: Path, interactive: bool = True) -> int:
    """analyse_item -> 0 or 1: detect again, keep the operator's names,
    groups, skip list, ambitus and settings; previous answers become the
    suggestions of systems still uncertain. Not interactive: no question
    is asked (open choices stay for partitor rebuild)."""
    from .build import run_detect
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
    new = load_item(item)
    open_ = [e["id"] for e in new.get("systems") or [] if "?" in (e.get("map") or [])]
    _ok(f"analysed:  {item.name}  proof {item_file(item, 'proof.pdf').name}"
        + (f"  ({len(open_)} choice(s) open)" if open_ else ""))
    if interactive:
        choose_maps(item)
        confirm_bar_rules(item)
        confirm_ambitus(item)
    elif open_:
        _note(f"choices left open: partitor rebuild {new['id']}")
    return 0


def cmd_analyse(a: argparse.Namespace) -> int:
    """analyse <id> | --all: analyse the source again (new proof, part
    allocation, clefs, ambitus); names, groups, skip list, ambitus set by
    hand, title, composer and settings are kept. --yes: ask nothing (open
    choices stay for rebuild). --all: every library item, as --yes. Not
    built."""
    start = time.monotonic()
    if getattr(a, "all", False):
        _, lib = _lib_or_die()
        items = item_dirs(lib)
        _head(f"Analyse again: {len(items)} item(s)")
        bad = 0
        for item in items:
            try:
                bad += analyse_item(item, interactive=False)
            except Exception as e:          # one bad item does not stop the rest
                _fail(f"analyse:  {item.name}: {e}")
                bad += 1
        _note("not built: review each item (show), then rebuild")
        return _summary(start)
    if not a.id:
        _die("analyse: an item id or --all")
    item = _item_or_die(a.id)
    data = load_item(item)
    quiet = bool(getattr(a, "yes", False))
    try:
        if data.get("systems") and not quiet and not yes(
                "Analyse again? Names, groups and settings are kept; choices and "
                "bar corrections are asked again", False):
            return 0
        if analyse_item(item, interactive=not quiet):
            return _summary(start)
    except Abort:
        _warn("analyse:  stopped; continue with partitor rebuild " + data["id"])
        return _summary(start)
    return saved(item, a, start)


def maybe_offer_reflow(item: Path, only: list[str] | None = None) -> None:
    """After a build: offer_reflow, unless `reflow_offer` is off (the default:
    re-flow is on hold, DESIGN.md §4.2 item 2). `reflow=on` still works."""
    if {**LAYOUT_DEFAULTS, **(load_item(item).get("layout") or {})}.get("reflow_offer") == "on":
        offer_reflow(item, only)


def offer_reflow(item: Path, only: list[str] | None = None) -> None:
    """After a build: when the print is small, offer re-flow (DESIGN.md
    §4.2), build it, show size and pages before and after, keep or undo.
    The trial builds into parts.new/ and the old set stays in parts.prev/:
    undo puts it back (no second build), a failed or killed trial leaves
    parts/ as it was. only: after a build of some parts or groups
    (0.3.0-dev.34): the offer covers those and sets `Name:reflow=on` for
    them, not the item; the trial builds only them. A group's pages grow
    faster than a part's (several staves per line): its page budget is
    GROUP_REFLOW_PAGES times the pages without re-flow (`pages=N` changes it)."""
    from . import build
    from .build import _size_summary, build_report, small_parts
    from .render import GROUP_REFLOW_PAGES, turns
    data = load_item(item)
    small = small_parts(data, only)
    if not small:
        return
    names = [p["part"] for p in small] if only else None
    lay = {**LAYOUT_DEFAULTS, **(data.get("layout") or {})}
    s0, c0 = _size_summary(data["built"], names)
    _head("Small print")
    print(f"     {', '.join(p['part'] for p in small)}: staff {s0:.1f} mm. The source "
          "lines are long, so the page width holds the size.")
    print(f"     Re-flow cuts lines at barlines (clef and key copied to each line): "
          f"up to {lay['max_staff_mm']:.0f} mm, more pages.")
    if any(p.get("group") for p in small):
        print(f"     A group has several staves per line, so its pages grow faster: its "
              f"page budget is {GROUP_REFLOW_PAGES:g} x the pages now "
              "(set \"Name:pages=N\" to change it).")
    before = data                       # layout, pending and built as they were
    swapped = False
    try:
        if not yes("Try re-flow?", True):
            return
        trial = load_item(item)
        apply_set(trial, [f"{n}:reflow=on" for n in names] if names else ["reflow=on"])
        save_item(item, trial)
        rc = build.run_build(item, only=names) if names else build.run_build(item)
        _reset_counts()
        if rc == 0:
            swapped = True
            s1, c1 = _size_summary(load_item(item)["built"], names)
            print(f"     staff {s0:.1f} -> {s1:.1f} mm   pages of music {c0} -> {c1}   "
                  f"page turns {turns(c0)} -> {turns(c1)}")
            if yes("Keep re-flow?", True):
                _ok("re-flow:  on")
                build_report(item)
                return
        else:
            _fail("build:  re-flow failed (see above); the parts are as before")
    except Abort:
        pass
    # undo: the settings as they were and, when the trial replaced the parts,
    # the old set from parts.prev/
    if swapped and restore_previous_parts(item):
        save_item(item, before)
        _ok("re-flow:  off (as before; the earlier parts are back)")
    else:
        data = load_item(item)
        lay_now = data.get("layout") or {}
        if lay_now.get("reflow") == "on" or any(
                (lay_now.get(PART_LAYOUT_KEY) or {}).get(n, {}).get("reflow") == "on"
                for n in names or []):
            apply_set(data, [f"{n}:reflow=off" for n in names] if names else ["reflow=off"])
            data["pending"] = before.get("pending") or []
            if not data["pending"]:
                data.pop("pending")
            save_item(item, data)
            if swapped:                    # the trial's parts stay and no old set to restore
                build.run_build(item, only=names) if names else build.run_build(item)
                _reset_counts()
        _ok("re-flow:  off (the parts are as before)")


def reid_item(lib: Path, item: Path) -> Path:
    """reid_item -> the item under a YYYY-MM-NNNN id (an old YYYY-NNN item;
    operator request 2026-10-25). Month from `created`; the serial is kept when no
    other item of the year has it, else the next free one. The folder,
    the item files and the part PDFs are renamed; nothing is rebuilt."""
    data = load_item(item)
    old = item_id(item)
    ip = _id_parts(old)
    if ip is None or ip[1] is not None:
        raise ValueError(f"{old}: already YYYY-MM-NNNN")
    year, _, serial = ip
    created = str(data.get("created") or "")
    mm = re.match(r"(\d{4})-(\d{2})", created)
    month = int(mm.group(2)) if mm and int(mm.group(1)) == year else time.localtime().tm_mon
    taken = {(_id_parts(d.name) or (0, 0, 0))[2] for d in item_dirs(lib)
             if d != item and (_id_parts(d.name) or (0,))[0] == year}
    new = f"{year}-{month:02d}-{serial:04d}" if serial not in taken else next_id(lib, year, month)
    dst = lib / f"{new}-{data.get('slug') or 'item'}"
    if dst.exists():
        raise ValueError(f"{dst.name} exists")
    for kind in (SCORE_FILE, "source.pdf", "proof.pdf"):   # old plain names first
        if (item / kind).exists() and not (item / f"{old}-{kind}").exists():
            os.replace(item / kind, item / f"{old}-{kind}")
    for f in item.iterdir():
        if f.is_file() and f.name.startswith(f"{old}-"):
            os.replace(f, item / (new + f.name[len(old):]))
    pdir = item / "parts"
    if pdir.is_dir():
        for f in pdir.iterdir():
            if old in f.name:
                os.replace(f, pdir / f.name.replace(old, new))
    os.replace(item, dst)
    data = load_item(dst)
    data["id"] = new
    if str(data.get("source", "")).startswith(f"{old}-") or data.get("source") == "source.pdf":
        data["source"] = f"{new}-source.pdf"
    for p_ in (data.get("built") or {}).get("parts") or []:
        for k in ("file", "large"):
            if k in p_:
                p_[k] = str(p_[k]).replace(old, new)
    save_item(dst, data)
    return dst


def cmd_reid(a: argparse.Namespace) -> int:
    """reid <id>: an old YYYY-NNN item gets a YYYY-MM-NNNN id."""
    start = time.monotonic()
    _, lib = _lib_or_die()
    item = _item_or_die(a.id)
    old = item.name
    try:
        dst = reid_item(lib, item)
    except (ValueError, OSError) as e:
        _die(f"reid: {e}")
    _ok(f"reid:  {old} -> {dst.name}  (files and part PDFs renamed; no build needed)")
    return _summary(start)


def cmd_expand(a: argparse.Namespace) -> int:
    return _cmd_step(a, True)


def cmd_contract(a: argparse.Namespace) -> int:
    return _cmd_step(a, False)


PLAN_KEYS = ("margin_top", "margin_bottom", "margin_side", "gutter", "binding", "duplex",
             "title_page", "gap", "gap_min", "clearance")     # layout keys `plan` reads


def plan_names(data: dict, built: dict, words: list[str]) -> list[str]:
    """plan_names -> the parts `plan` shows: the ones named, else the groups and
    the parts with a bad turn."""
    try:
        only = parse_parts(data, words) if words else None
    except ValueError as e:
        _die(f"plan: {e}", f"Parts: {selection_help(data)}")
    names = [nm for _, nm in build_names(data) if nm in built]
    if only is not None:
        return [nm for nm in names if nm in only]
    return [nm for nm in names if built[nm].get("group") or built[nm].get("bad_turns")]


def plan_rows(opts_list: list, old: dict, lay: dict, show_all: bool = True) -> list[str]:
    """plan_rows -> the table of options of one part, as text lines. show_all False: only the
    row as built and the best row of each paper (the numbers of the rows stay)."""
    from .partplan import best_rows
    best = best_rows(opts_list)
    out = [f"  {'#':>2}  {'paper':<6} {'staff':>7} {'pages':>5} {'rest':>5} {'short':>5} {'attacca':>7} "
           f"{'fold-out':>8} {'bad':>4}  note"]
    shown = 0
    for o in opts_list:
        mark = "*" if (o.paper == lay.get("paper") and abs(o.staff_mm - old.get("staff_mm", 0)) <= 0.25) else " "
        if not show_all and mark == " " and o.n not in best:
            continue
        shown += 1
        if not o.ok:
            out.append(f"{mark} {o.n:>2}  {o.paper:<6} {o.staff_mm:>4.1f} mm {'-':>5}  {o.note}")
            continue
        c = o.counts
        note = ", ".join(x for x in ("best" if o.n in best else "", "re-flow" if o.reflow else "",
                                     "no title page" if not o.title_page else "") if x)
        out.append(f"{mark} {o.n:>2}  {o.paper:<6} {o.staff_mm:>4.1f} mm {o.pages:>5} {c.get('rest', 0):>5} "
                   f"{c.get('rest1', 0):>5} {c.get('attacca', 0):>7} {o.folds:>8} "
                   f"{c.get('bad', 0) + c.get('bridge', 0):>4}  {note}")
    if shown < len(opts_list):
        out.append(f"  {len(opts_list) - shown} more options: add --all")
    return out


def trial_data(data: dict, specs: list[str]) -> tuple[dict, list[str]]:
    """trial_data -> (data for a temporary copy of the item, the names of the trial
    groups). specs: 'Name=Alto,Tenor' (part names or numbers, top staff first).
    The copy has only the trial groups; every part is skipped (extracted by no
    one: only the groups are built) and nothing is built yet. The layout of the
    first group of the item (margins, `group_gap`, ...) is the layout of the trial
    groups, so their lines are made as that group's are."""
    out = dict(data)
    groups, names = {}, []
    like = next(iter(data.get("groups") or {}), None)
    for spec in specs:
        name, eq, words = spec.partition("=")
        name = name.strip()
        if not eq or not name or not words.strip():
            raise ValueError(f"{spec}: use Name=Alto,Tenor (part names or numbers)")
        if name in (data.get("parts") or []):
            raise ValueError(f"{name} is already a part name")
        got = parse_parts(data, [w for w in re.split(r"[,\s]+", words) if w])
        if got is None:                            # parse_parts: None = every part
            got = [nm for nm in data.get("parts") or [] if nm not in (data.get(SKIP_KEY) or [])]
        if len(got) < 2:
            raise ValueError(f"{spec}: a group needs two parts or more")
        if len(got) != len(set(got)) or any(g not in (data.get("parts") or []) for g in got):
            raise ValueError(f"{spec}: parts of the item, once each")
        order = {nm: i for i, nm in enumerate(data.get("parts") or [])}
        groups[name] = sorted(got, key=lambda g: order[g])               # score order
        names.append(name)
    out["groups"] = groups
    out[SKIP_KEY] = list(data.get("parts") or [])
    out.pop("built", None)
    out.pop("pending", None)
    lay = {k: v for k, v in (data.get("layout") or {}).items() if k != PART_LAYOUT_KEY}
    plays = (data.get("layout") or {}).get(PART_LAYOUT_KEY) or {}
    if like and plays.get(like):
        lay[PART_LAYOUT_KEY] = {n: dict(plays[like]) for n in names}
    out["layout"] = lay
    return out, names


def plan_table(item: Path, data: dict, built: dict, nm: str, trial: bool = False, show_all: bool = True):
    """plan_table -> the option rows of part (or group) nm, printed as a table; None if
    there is nothing to plan (the reason is printed)."""
    from .lines import lines_path, load_lines
    from .partplan import JUSTIFY_SHARE, Source, estimate, options, read_source
    lay = part_layout(data, nm)
    try:
        pl = load_lines(lines_path(item / "lines", nm))
    except ValueError as e:
        _warn(f"plan:  {nm}: {e}")
        return None
    raw = pl.get("plan")
    try:
        src = Source.from_dict(raw) if raw else None
    except ValueError as e:
        _warn(f"plan:  {nm}: {e}")
        src = None
    if src is None and not any(s.bars_x for s in pl["strips"]):
        _warn(f"plan:  {nm}: no plan data and the saved lines are re-flowed: rebuild the part once "
              f"(partitor rebuild {data['id']} {nm})")
        return None
    if lay.get("duplex") == "off":
        _warn(f"plan:  {nm}: duplex is off (single-sided): page turns follow every page; no plan")
        return None
    o = {**pl["opts"], **{k: lay[k] for k in PLAN_KEYS if lay.get(k) is not None}}
    cur = lay.get("paper") or "letter"
    papers = ("letter", "ledger") + (() if cur in ("letter", "ledger") else (cur,))   # fixed order: the numbers stay
    if src is None:                         # a build before 0.8.6: the justified saved lines
        src = read_source(pl["strips"], o, pl["dpi"], share=JUSTIFY_SHARE)
    rows = options(src, o, papers, floor_mm=float(lay.get("min_staff_mm") or 5.0))
    old = built[nm]
    _head(f"Plan: {nm}")
    c0 = old.get("content_pages", old["pages"])
    est = estimate(src, o, o["paper"], float(old["staff_mm"]))
    _note(f"{'trial build' if trial else 'built'}: "
          f"{o['paper']}, staff {old['staff_mm']} mm, {c0} pages of music, "
          f"{old.get('turns', 0)} turns, {old.get('bad_turns', 0)} while playing"
          + (f"; the estimate for it: {est.pages} pages" if est.ok else ""))
    for line in plan_rows(rows, old, lay, show_all):
        print(line)
    return rows


def plan_trial(item: Path, data: dict, specs: list[str]) -> tuple[Path, dict, list[str]]:
    """plan_trial -> (temporary item folder, its data, the trial group names): a copy of the item
    in which only the trial groups are built (a few seconds to a minute: the page cache is used).
    The caller removes the folder. The item itself is not touched."""
    import contextlib
    import io
    import tempfile
    from . import build            # R1: run_build is patched by tests, read as build.run_build
    tdata, names = trial_data(data, specs)
    tmp = Path(tempfile.mkdtemp(prefix="partitor-plan-"))
    dest = tmp / item.name
    try:
        shutil.copytree(item, dest, ignore=shutil.ignore_patterns(
            "parts", PARTS_PREV, PARTS_NEW, "lines", "lines.new", "*.tmp"))
        save_item(dest, tdata)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            rc = build.run_build(dest)
        if rc != 0:
            print(buf.getvalue())
            raise ValueError("the trial build failed (output above)")
        return tmp, load_item(dest), names
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise


def cmd_plan(a: argparse.Namespace) -> int:
    """plan <id> [part ...] [N] [--group Name=Alto,Tenor ...]: the options of a part (paper,
    staff size) with their page turns, estimated from the saved lines (read-only). `plan <id>
    <part> N` sets option N for that part: paper, largest staff, re-flow, fold-outs and a page
    budget; saved, not built (rebuild applies it). --group: the same for groups of parts that
    the item does not have: built in a temporary copy, shown, thrown away."""
    start = time.monotonic()
    item = _item_or_die(a.id)
    data = load_item(item)
    specs = list(getattr(a, "group", None) or [])
    words = list(getattr(a, "words", None) or [])
    if specs:
        if words:
            _die("plan: --group takes no part names", f"partitor plan {data['id']} --group Name=Alto,Tenor")
        print(f"{BOLD}partitor {VERSION} — plan (trial groups){RST}\n{time.strftime('%Y-%m-%d %H:%M:%S %Z')}")
        _note("building the trial group(s) in a temporary copy of the item; nothing in the item changes")
        try:
            tmp, tdata, names = plan_trial(item, data, specs)
        except ValueError as e:
            _die(f"plan: {e}")
        _reset_counts()                           # the trial build's own warnings are not ours
        try:
            tbuilt = {r["part"]: r for r in (tdata.get("built") or {}).get("parts") or []}
            for nm in names:
                if nm in tbuilt:
                    plan_table(tmp / item.name, tdata, tbuilt, nm, trial=True, show_all=getattr(a, 'all', False))
                else:
                    _warn(f"plan:  {nm}: not built in the trial (see the build report: partitor rebuild)")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        _note(f"to keep a group: partitor groups {data['id']} (Name=4,5,6), then partitor rebuild {data['id']} "
              "NAME, then partitor plan NAME. Compare the groups with the single parts: partitor plan ID PART")
        return _summary(start)
    built = {r["part"]: r for r in (data.get("built") or {}).get("parts") or []}
    if not built:
        _die("plan: nothing built yet", f"Build first: partitor rebuild {data['id']}")
    pick = int(words.pop()) if len(words) >= 2 and words[-1].isdigit() else None
    names = plan_names(data, built, words)
    if not names:
        _die("plan: no part with bad turns and no group", "Name a part: partitor plan "
             f"{data['id']} Trombones   (parts: {selection_help(data)})")
    if pick is not None and len(names) != 1:
        _die("plan: name one part to set an option", f"partitor plan {data['id']} Trombones {pick}")
    print(f"{BOLD}partitor {VERSION} — plan{RST}\n{time.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    eg = None                                   # a part and the number of its best row, for the hint
    for nm in names:
        rows = plan_table(item, data, built, nm, show_all=getattr(a, 'all', False))
        if rows and eg is None:
            from .partplan import best_rows
            good = sorted(best_rows(rows))
            eg = (nm, good[0]) if good else None
        if rows is not None and pick is not None:
            from .partplan import set_pairs
            from .render import sheet_text
            chosen = next((r for r in rows if r.n == pick), None)
            if chosen is None or not chosen.ok:
                _die(f"plan: option {pick}: " + ("no such option" if chosen is None else chosen.note))
            try:
                changes = apply_set(data, set_pairs(nm, chosen))
            except ValueError as e:
                _die(f"plan: {e}")
            mark_pending(data, *(c.split(": ")[0] for c in changes))
            save_item(item, data)
            _ok(f"plan:  {nm}: option {pick} ({chosen.paper}, staff {chosen.staff_mm:g} mm, about "
                f"{chosen.pages} pages); " + "; ".join(changes))
            if chosen.folds:
                _note(f"plan:  {nm}: needs " + sheet_text(chosen.paper, chosen.folds)
                      + "; the build writes the print and assembly steps to a text file next to the PDFs")
    if pick is None:
        _note("estimates from the lines of the last build (no per-staff rests: bridgeable turns are not "
              "counted); a build gives the real numbers. * = as built; best = fewest turns while playing, "
              "then the largest staff, then the fewest fold-outs (one per paper)")
        _note(f"Set an option: partitor plan {data['id']} PART N    then: partitor rebuild {data['id']}")
        if eg:
            _note(f"For example: partitor plan {data['id']} {eg[0]} {eg[1]}")
        return _summary(start)
    return saved(item, a, start)


def cmd_repage(a: argparse.Namespace) -> int:
    """repage <id> [part ...]: new page breaks for built parts from the lines
    saved by the last build (no analysis, no build). Sets turns=rest for the
    parts (kept by later builds); breaks, duplex and title_page are taken
    from the layout. Writes through parts.new/ like a build."""
    from .lines import count_bad_turns, lines_path, load_lines, turn_text
    from .render import LARGE, LAST_RENDER, large_copy, render_part, sheet_text, turns
    start = time.monotonic()
    item = _item_or_die(a.id)
    recover_parts(item)
    data = load_item(item)
    built = {r["part"]: r for r in (data.get("built") or {}).get("parts") or []}
    if not built:
        _die("repage: nothing built yet", f"Build first: partitor rebuild {data['id']}")
    words = list(getattr(a, "parts", None) or [])
    try:
        only = parse_parts(data, words) if words else None
    except ValueError as e:
        _die(f"repage: {e}", f"Parts: {selection_help(data)}")
    names = [nm for _, nm in build_names(data) if nm in built and (only is None or nm in only)]
    if not names:
        _die("repage: none of those parts is built")
    print(f"{BOLD}partitor {VERSION} — repage{RST}\n{time.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    stage = item / PARTS_NEW
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir()
    done, recs, report = [], {}, []
    set_now = []
    for nm in names:
        if part_layout(data, nm).get("turns") != "rest":
            set_now.append(f"{nm}:turns=rest")
    if set_now:
        apply_set(data, set_now)
        _note("turns=rest:  set for " + ", ".join(p.split(":")[0] for p in set_now)
              + " (a later build keeps it; set \"Name:turns=any\" to undo)")
    t0 = time.monotonic()
    _head("Pages")
    for nm in names:
        try:
            pl = load_lines(lines_path(item / "lines", nm))
        except ValueError as e:
            _warn(f"repage:  {nm}: {e}")
            continue
        lay = part_layout(data, nm)
        o = {**pl["opts"], **{k: lay.get(k) for k in REPAGE_KEYS}}
        lib_logo = library_logo(library_root())
        if lib_logo:
            o["_logo_file"] = str(lib_logo)
        old = built[nm]
        fn = stage / old["file"]
        try:
            n = render_part(nm, pl["strips"], pl["meta"], pl["dpi"], o, fn)
        except Exception as e:                      # noqa: BLE001  (leave parts/ as it is)
            shutil.rmtree(stage, ignore_errors=True)
            _die(f"repage: {nm}: {e}", "parts/ is unchanged")
        tl = list(LAST_RENDER.get("turns") or [])
        nbad = count_bad_turns(tl, o)
        big = (large_copy(fn, o["paper"])
               if o.get("large") == "on" and o["paper"] in LARGE else None)
        rec = {k: v for k, v in old.items() if k not in ("large", "foldout", "foldouts", "flaps", "assemble")}
        rec.update(pages=n, content_pages=LAST_RENDER.get("content", n),
                   title_page=bool(LAST_RENDER.get("title_page")), turns=len(tl),
                   bad_turns=nbad, **({"large": big.name} if big else {}),
                   **({"foldout": LAST_RENDER["foldout"], "foldouts": LAST_RENDER["foldouts"],
                       "flaps": LAST_RENDER["flaps"], "assemble": LAST_RENDER["assemble"]} if LAST_RENDER.get("foldout") else {}))
        recs[nm] = rec
        c0 = old.get("content_pages", old["pages"])
        _ok(f"{nm}:  pages of music {c0} -> {rec['content_pages']}  "
            f"turns {old.get('turns', turns(c0))} -> {len(tl)}  while playing {nbad}")
        if rec.get("foldout"):
            _note(f"{nm}:  {sheet_text(o['paper'], rec['foldouts'])}: print and assemble as in {rec['assemble']}")
        report.append((nm, tl))
        done.append(nm)
    if not done:
        shutil.rmtree(stage, ignore_errors=True)
        _fail("repage:  nothing done (rebuild the parts once to save their lines)")
        return _summary(start)
    for nm, tl in report:
        _head(f"Turns: {nm}")
        for t in tl:
            line = f"     {turn_text(t)}"
            if t["resting"]:
                print(line)
            elif t.get("movement"):
                _note(line.strip())
            else:
                _warn(f"turn-while-playing:  {nm}  {turn_text(t)}")
    try:
        kept = keep_other_parts(item, data, stage, done)
    except OSError as e:
        shutil.rmtree(stage, ignore_errors=True)
        _die(f"repage:  the other parts could not be kept ({e})", "parts/ is unchanged")
    order = {nm: i for i, (_, nm) in enumerate(build_names(data))}
    new = sorted([recs[nm] for nm in done] + kept, key=lambda r: order.get(r["part"], len(order)))
    swap_parts(item)
    gone = {f"{nm}:{k}" for nm in done for k in REPAGE_KEYS}
    if set(done) >= set(built):
        gone |= set(REPAGE_KEYS)
    left = [x for x in data.get("pending") or [] if x not in gone]
    if left:
        data["pending"] = left
    else:
        data.pop("pending", None)
    data["built"] = {"date": time.strftime("%Y-%m-%d %H:%M"), "parts": new}
    save_item(item, data)
    _note(f"parts:  the set before is kept in {PARTS_PREV}/ until the next good build")
    _note(f"repage took {time.monotonic() - t0:.0f} s")
    return _summary(start)


def cmd_rebuild(a: argparse.Namespace) -> int:
    """rebuild <id>: detect again when score.yaml has no systems (failed
    new), ask open choices, then build."""
    from .build import _rebuild_report, run_detect
    start = time.monotonic()
    item = _item_or_die(a.id)
    data = load_item(item)
    try:
        if "systems" not in data:
            if run_detect(item, data.get("pages"), data.get("title", ""),
                          data.get("composer", "")):
                _reset_counts()
                _fail("detect:  failed (see above)")
                return _summary(start)
            data = merge_item_keys(item, data)
            proof_from_preview(item)
        choose_maps(item)
        confirm_bar_rules(item)
    except Abort:
        _warn("rebuild:  stopped")
        return _summary(start)
    only = None
    words = list(getattr(a, "parts", None) or [])
    if words:
        data = load_item(item)
        try:
            only = parse_parts(data, words)
        except ValueError as e:
            _die(f"rebuild: {e}", f"Parts: {selection_help(data)}")
    data = load_item(item)
    if _rebuild_report(item, data.get("built"), only, getattr(a, "jobs", None)) == 0:
        maybe_offer_reflow(item, only)
    return _summary(start)
