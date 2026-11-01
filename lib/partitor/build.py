# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""The pieces, detect and build commands, run helpers and build reports."""
from __future__ import annotations

import argparse
import math
import os
import re
import shutil
import time
from pathlib import Path

import numpy as np
import pymupdf
import yaml

from . import VERSION, analysis, config, parallel, vision
from .analysis import check_page, iter_pages, parse_pages, preview_page, write_preview_index
from .bars import (
    assign_bars, bar_edits_by_system, bar_mismatches, effective_systems, mismatch_text,
    propose_bar_rules, renumber,
)
from .clef import ambitus_for, refresh_ambitus
from .config import (
    LAYOUT_DEFAULTS, LAYOUT_HELP, LINES_NEW, OWN_HEADER_BASE, PAGE_HEADER_SP, PART_LAYOUT_KEY,
    SCORE_FILE, SKIP_KEY, check_margins, file_part_name, part_file_name, sha256,
)
from .console import (
    BOLD, RST, _counts, _die, _fail, _head, _note, _ok, _progress, _progress_end, _reset_counts,
    _skip, _summary, _warn,
)
from .library import (
    PARTS_NEW, PARTS_PREV, build_names, item_file, item_id, item_line, keep_lines,
    keep_other_parts, library_logo, library_root, load_item, part_layout, partial_blocker,
    piece_tag, recover_parts, save_item, score_name, swap_parts,
)
from .lines import count_bad_turns, fill_rests, finish_lines, lines_path, save_lines
from .mapping import assign_maps
from .model import PageResult, RestRun, Strip
from .parallel import PAGE_WORKER_GB, RENDER_WORKER_GB, job_count, worker_peak_mb
from .reflow import find_prefixes, reflow_report
from .render import (
    GROUP_REFLOW_PAGES, LARGE, LAST_RENDER, choose_layout, choose_reflow, fit_scale, large_copy,
    render_part, turns,
)
from .strips import group_strip, make_strip, own_group_gap, set_bar_geometry


# =============================================================================
# Commands
# =============================================================================
LAST_BUILD: list[dict] = []     # per-part results of the last build (library CLI)


def workdir(pdf: Path, out: str | None, pages: str | None = None) -> Path:
    if out:
        return Path(out)
    if pages:
        tag = re.sub(r"\s+", "", pages)
        return pdf.with_name(f"{pdf.stem}.p{tag}.partitor")
    return pdf.with_suffix(".partitor")


def cmd_pieces(a: argparse.Namespace) -> int:
    """List the pieces of a PDF: runs of music pages; a page with a title
    starts a new piece. Analysis at 200 dpi, no label OCR (titles are read
    from the text layer or by OCR)."""
    start = time.monotonic()
    pdf = Path(a.pdf)
    if not pdf.is_file():
        _die(f"input not found: {pdf}")
    print(f"{BOLD}partitor {VERSION} — pieces{RST}\n{time.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    _head(f"Pages: {pdf.name}")
    doc = pymupdf.open(pdf)
    rows: list[tuple[int, bool, str]] = []
    for res, _ in iter_pages(pdf, 200, list(range(doc.page_count)), ocr=False):
        title = res.title
        rows.append((res.page, res.music, title))
        for g in res.gate:
            _warn(f"page {res.page + 1}: {g}")
            _note("Likely an illustration or manuscript facsimile. "
                  "`detect` fails on this page; leave it out with --pages.")
    pieces: list[list] = []
    for pno, music, title in rows:
        if not music:
            continue
        if not pieces or title or pieces[-1][1] != pno - 1:
            pieces.append([pno, pno, title])
        else:
            pieces[-1][1] = pno
    _head("Pieces")
    for k, (p0, p1, title) in enumerate(pieces, 1):
        rng = f"{p0 + 1}" if p0 == p1 else f"{p0 + 1}-{p1 + 1}"
        _ok(f"{k:2d}  pages {rng:7s}  {title or '(no title found)'}")
        _note(f"partitor detect {pdf.name} --pages {rng}")
    skipped = [r[0] + 1 for r in rows if not r[1]]
    if skipped:
        _skip(f"no music: pages {', '.join(map(str, skipped))}")
    return _summary(start)


def cmd_detect(a: argparse.Namespace) -> int:
    """detect: analyse the pages, write layout.yaml and the preview.

    jobs (--jobs, else PARTITOR_JOBS, else auto) > 1: forked workers analyse
    the pages (fork_map, as build); each returns only small data and the
    parent joins it in page order, so the output equals the one-job run.
    One job: this process, page by page (iter_pages)."""
    start = time.monotonic()
    pdf = Path(a.pdf)
    if not pdf.is_file():
        _die(f"input not found: {pdf}")
    doc = pymupdf.open(pdf)
    try:
        pages = parse_pages(a.pages, doc.page_count)
    except ValueError as e:
        _die(str(e))
    out = workdir(pdf, a.out, a.pages)
    out.mkdir(parents=True, exist_ok=True)
    pdir = out / "preview"
    pdir.mkdir(exist_ok=True)
    print(f"{BOLD}partitor {VERSION} — detect{RST}\n{time.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    if vision._TESS["path"] is None:
        _warn("ocr:  tesseract not found; staff labels are not read")
        _note("Fix: apt install tesseract-ocr")
    config.TUNE["page_header_sp"] = a.page_header_sp
    _head(f"Analysis: {pdf.name}  (dpi {a.dpi}, pages {pages[0] + 1}-{pages[-1] + 1})")
    sysrecs: list[dict] = []
    items: list[str] = []
    titles: list[str] = []
    composers: list[str] = []
    t_analysis = time.monotonic()
    jobs = job_count(getattr(a, "jobs", None), PAGE_WORKER_GB, len(pages))

    def page_out(res: PageResult, recs: list[dict]) -> tuple:
        """Gate line and preview of one page -> only small data (system
        records, preview section, title, composer). The PageResult holds the
        large owner image: it stays in the process that made it."""
        check_page(res)
        return recs, preview_page(res, recs, pdir), res.title, res.composer

    if jobs <= 1:
        # one process, as before 0.4.1 (iter_pages carries the system base)
        results = (page_out(res, recs) for res, recs in iter_pages(pdf, a.dpi, pages))
    else:
        _note(f"analysing {len(pages)} page(s) with {jobs} worker(s)")
        wdocs: dict[int, "pymupdf.Document"] = {}

        def page_task(pno: int) -> tuple:
            d_ = wdocs.get(os.getpid())
            if d_ is None:                    # one open document per process
                d_ = wdocs[os.getpid()] = pymupdf.open(pdf)
            # nsys = 0: the system index is a key inside one page (analyse_one)
            res, recs = analysis.analyse_one(d_, pno, a.dpi, 0)
            return page_out(res, recs)

        results = parallel.fork_map(page_task, pages, jobs)
    try:
        for k_, pno in enumerate(pages):
            if jobs > 1:
                _progress(f"page {pno + 1} ({k_ + 1}/{len(pages)}): waiting for its worker")
            recs, item, title, composer = next(results)
            if jobs > 1:
                _progress_end()
            items.append(item)
            sysrecs.extend(recs)
            if title:
                titles.append(title)
            if composer:
                composers.append(composer)
    finally:
        results.close()
    if jobs > 1:
        _note(f"workers: {jobs}; the largest used {worker_peak_mb()} MB "
              f"(estimate for the worker count: {PAGE_WORKER_GB:.1f} GB)")
        _note(f"analysis took {time.monotonic() - t_analysis:.0f} s")
    if not sysrecs:
        _fail("music:  no staves found")
        return _summary(start)
    _head("Systems")
    counts: dict[int, int] = {}
    for r in sysrecs:
        counts[len(r["staves"])] = counts.get(len(r["staves"]), 0) + 1
    for n, c in sorted(counts.items(), reverse=True):
        _ok(f"systems:  {c} with {n} staves")
    parts = [p.strip() for p in a.parts.split(",") if p.strip()] if a.parts else []
    names, entries = assign_maps(sysrecs, parts)
    bars, resync, used = assign_bars(sysrecs)
    for e, r, b in zip(entries, sysrecs, bars):
        e["bar"] = b
        e["bars"] = r["nbars"]
        e["widths"] = r.get("widths", [])
        if r.get("repeats"):
            e["repeats"] = r["repeats"]
        if r.get("anchors"):
            e["anchors"] = [[int(x[0]), int(x[1])] for x in r["anchors"]]
        if any(r.get("steps") or []):
            e["steps"] = r["steps"]
        if r.get("restart"):
            e["restart"] = True
        if r.get("geom"):
            e["geom"] = {"page": int(r["page"]) + 1, **r["geom"]}
    # the operator's bar edits and answers of an earlier analysis stay (each
    # edit only where the line has the bars it had then)
    old_rules: dict = {}
    old_lay = out / getattr(a, "layout_name", "layout.yaml")
    if old_lay.is_file():
        try:
            old_rules = (yaml.safe_load(old_lay.read_text(encoding="utf-8")) or {}
                         ).get("bar_rules") or {}
        except yaml.YAMLError:
            old_rules = {}
    keep_rules = {k: list(old_rules[k]) for k in ("bar_edits", "bars_ack") if old_rules.get(k)}
    edit_notes: list[str] = []
    eff_entries = effective_systems(entries, keep_rules, edit_notes)
    for t in edit_notes:
        _warn(f"bars:  {t}")
    bar_rules = propose_bar_rules(eff_entries)
    bar_rules.update(keep_rules)
    scheme = renumber({"systems": entries, "bar_rules": bar_rules})
    _head("Bar numbers")
    if used:
        _ok(f"bars:  counted from barlines, checked against {used} printed number(s)")
    else:
        _warn("bars:  no printed bar numbers found to check the count")
    if keep_rules.get("bar_edits"):
        _note(f"bars:  {len(keep_rules['bar_edits'])} bar edit(s) kept from the earlier analysis")
    for m in bar_mismatches(effective_systems(entries, bar_rules), bar_rules):
        _warn(f"bars:  {mismatch_text(m)}")
        _note("Check the proof. The parts follow the source score unless you say "
              "otherwise: partitor bars <id> (k keeps the printed numbers; j / a mend "
              "a misread barline)")
    nrep = sum(len(e.get("repeats") or []) for e in entries)
    if nrep:
        _ok(f"repeats:  {nrep} repeat sign(s); rehearsal letters "
            f"{sum(len(e.get('marks') or []) for e in entries)}")
    for sid in bar_rules["pickup"]:
        _warn(f"bars:  pickup at {sid} (first bar short): numbered from 0 — check")
    for key in bar_rules["split"]:
        _warn(f"bars:  bar split by a repeat at {key}: counted once — check")
    if bar_rules["pickup"] or bar_rules["split"]:
        _note(f"printed numbers in the source: {scheme} count. Change: bar_rules in "
              "the layout (partitor bars <id> in the library)")
    ref_n = max(len(r["staves"]) for r in sysrecs)
    if parts and len(parts) != ref_n:
        _warn(f"parts:  {len(parts)} names given, fullest system has {ref_n} staves; "
              "names taken from labels")
    _ok(f"parts:  {', '.join(names)}")
    unresolved = [e["id"] for e in entries if "?" in e["map"]]
    _head("Output")
    lay_path = out / getattr(a, "layout_name", "layout.yaml")
    if lay_path.exists() and not a.force:
        _warn(f"layout:  {lay_path} exists, not overwritten (use --force)")
    else:
        lay = {
            "source": pdf.name, "sha256": sha256(pdf), "dpi": a.dpi,
            "pages": f"{pages[0] + 1}-{pages[-1] + 1}",
            "title": a.title or (titles[0] if titles else ""),
            "subtitle": a.subtitle,
            "composer": a.composer or (composers[0] if composers else ""),
            "parts": names,
            "page_header_sp": config.TUNE["page_header_sp"],
            "bar_rules": bar_rules,
            "bar_rules_status": "proposed",
            "systems": entries,
            "layout": {},
        }
        lay_path.write_text(LAYOUT_HELP + yaml.safe_dump(
            lay, sort_keys=False, allow_unicode=True, default_flow_style=None,
            width=100), encoding="utf-8")
        _ok(f"layout:   {lay_path}")
        if unresolved:
            _warn(f"map:  {len(unresolved)} system(s) uncertain: "
                  f"{', '.join(unresolved[:6])}{' …' if len(unresolved) > 6 else ''}")
            _note(f"Fix: check `suggest` and set `map` in {lay_path}")
    idx = write_preview_index(pdir, items, pdf.name)
    _ok(f"preview:  {idx}")
    return _summary(start)


def load_layout(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


REST_FREE_SP = 14.0     # staff start (clef, key, time) skipped by the empty-staff check
REST_STEM_SP = 2.6      # a vertical ink run this long is a stem, not a rest
REST_BAND_SP = 3.5      # rows checked above and below the staff


def staff_is_empty(res: "PageResult", idx: int) -> bool:
    """staff_is_empty -> True when a staff holds only rests: past its start
    (clef, key, time: 14 sp) and clear of the barlines (0.8 sp), no column
    of its ink has a vertical run of 2.6 sp or more (a stem; an H-bar's
    ends, a rest block, a staff line, text and numbers are shorter)."""
    st = res.staves[idx]
    sp = res.sp
    x1 = int(st.x1)
    x0 = int(st.x0 + min(REST_FREE_SP * sp, 0.4 * (x1 - st.x0)))
    y0 = max(0, int(st.top - REST_BAND_SP * sp))
    y1 = min(res.owner.shape[0], int(st.bottom + REST_BAND_SP * sp))
    if x1 <= x0 or y1 <= y0:
        return True
    ink = res.owner[y0:y1, x0:x1] == idx
    for bx in res.barlines.get(st.system, []):
        ink[:, max(0, int(bx - 0.8 * sp) - x0):max(0, int(bx + 0.8 * sp) - x0 + 1)] = False
    run = np.zeros(ink.shape[1], np.int32)
    best = np.zeros(ink.shape[1], np.int32)
    for r in range(ink.shape[0]):
        run = (run + 1) * ink[r]
        np.maximum(best, run, out=best)
    return not bool((best >= REST_STEM_SP * sp).any())


def cmd_build(a: argparse.Namespace) -> int:
    start = time.monotonic()
    pdf = Path(a.pdf)
    out = workdir(pdf, a.out, a.pages)
    lay_path = out / getattr(a, "layout_name", "layout.yaml")
    if not lay_path.is_file():
        _die(f"layout not found: {lay_path}", f"Run: partitor detect {pdf}")
    lay = load_layout(lay_path)
    print(f"{BOLD}partitor {VERSION} — build{RST}\n{time.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    _head("Layout")
    if lay.get("sha256") != sha256(pdf):
        _die("input PDF changed since detect", f"Run: partitor detect {pdf} --force")
    opts = dict(LAYOUT_DEFAULTS)
    opts.update({k: v for k, v in (lay.get("layout") or {}).items() if k in LAYOUT_DEFAULTS})
    cli_set = set()
    for key in LAYOUT_DEFAULTS:
        v = getattr(a, key, None)
        if v is not None:
            opts[key] = v
            cli_set.add(key)
    err = check_margins(opts)
    if err:
        _die(f"layout: {err}", f"Fix: edit {lay_path} or the build options")
    for key in ("gap", "gap_min", "bar_raise", "bar_size", "max_staff_mm", "small_mm"):
        opts[key] = float(opts[key])
    if opts["gap_min"] > opts["gap"]:
        opts["gap_min"] = opts["gap"]
    lib_logo = library_logo(library_root())
    if lib_logo:                         # render cannot see the library: pass the file (not stored in .lines)
        opts["_logo_file"] = str(lib_logo)
    sysmaps = {}
    bad = False
    for srec in lay["systems"]:
        m = srec.get("map")
        if m is None or len(m) != srec["staves"] or "?" in m:
            _fail(f"map:  {srec['id']}  ({srec['staves']} staves, map {m})")
            bad = True
        sysmaps[srec["id"]] = m
    if bad:
        _note(f"Fix: edit {lay_path}")
        return _summary(start)
    _ok(f"layout:  {lay_path}  ({len(sysmaps)} systems)")

    _head("Analysis")
    dpi = int(lay["dpi"])
    config.TUNE["page_header_sp"] = float(lay.get("page_header_sp", PAGE_HEADER_SP))
    doc = pymupdf.open(pdf)
    pages = parse_pages(lay.get("pages"), doc.page_count)
    expect = {s["id"]: s["staves"] for s in lay["systems"]}
    seen: list[str] = []
    part_strips: dict[str, list] = {p: [] for p in lay["parts"]}   # Strip | RestRun
    lay_sys = {s_["id"]: s_ for s_ in lay["systems"]}
    groups = {str(g): [p for p in (ps or []) if p in lay["parts"]]
              for g, ps in (lay.get("groups") or {}).items()}
    groups = {g: ps for g, ps in groups.items() if ps}
    group_strips: dict[str, list] = {g: [] for g in groups}
    skip = set(lay.get(SKIP_KEY) or [])
    # only: build just these parts / groups (the rest of the parts are not
    # touched; the library keeps the old files of the others)
    only = [str(n) for n in (getattr(a, "only", None) or [])]
    bad_ = [n for n in only if n not in part_strips and n not in groups]
    if bad_:
        _die(f"unknown part or group: {', '.join(bad_)}",
             f"Parts: {', '.join(part_strips)}; groups: {', '.join(groups) or '-'}")
    want_parts = [p for p in part_strips if (not only or p in only) and p not in skip]
    want_groups = [g for g in groups if not only or g in only]
    # parts whose staves this build reads: the parts and the members of the groups
    consumers = set(want_parts) | {x for g in want_groups for x in groups[g]}
    darker = opts["ink"] == "darker"
    # bar number at each line start (not on a movement's first line)
    if lay.get("bar_rules") is not None:
        renumber(lay)                 # bar and marks follow bar_rules
    # bars per system for multi-bar rests: from the line-start numbers when
    # the next system of the movement has one (a printed number corrected a
    # wrong barline count), else the counted bars
    span: dict[str, int] = {}
    edit_notes: list[str] = []
    eff_sys = effective_systems(lay["systems"], lay.get("bar_rules"), edit_notes)
    for t in edit_notes:
        _warn(f"bars:  {t}")
    open_bars = bar_mismatches(eff_sys, lay.get("bar_rules"))
    if open_bars:
        for m in open_bars:
            _fail(f"bars:  {mismatch_text(m)}")
        _note("The parts follow the source score only when you confirm it. Run: "
              "partitor bars <id>  (k N keeps the printed numbers; j / a mend a "
              "misread barline)")
        return _summary(start)
    for k_, s_ in enumerate(eff_sys):
        nb_ = int(s_.get("bars") or 0)
        nx_ = eff_sys[k_ + 1] if k_ + 1 < len(eff_sys) else None
        if nx_ is not None and not nx_.get("restart") and isinstance(s_.get("bar"), int) \
           and isinstance(nx_.get("bar"), int) and nx_["bar"] > s_["bar"]:
            nb_ = nx_["bar"] - s_["bar"]
        span[s_["id"]] = nb_
    bar_of = {}
    marks_of = {s_["id"]: s_.get("marks") or [] for s_ in lay["systems"]}
    nums_of = {s_["id"]: s_.get("bar_nums") or [] for s_ in lay["systems"]}
    if opts["bar_numbers"] == "start":
        for j, srec in enumerate(lay["systems"]):
            b = srec.get("bar")
            if isinstance(b, int) and b >= 1 and j > 0 and not srec.get("restart"):
                bar_of[srec["id"]] = b
    ids_by_page: dict[int, list[str]] = {}
    for s_ in lay["systems"]:
        ids_by_page.setdefault(int(s_["id"].split(".")[0][1:]) - 1, []).append(s_["id"])

    def consume(res, recs):
        """consume -> (strips per part, strips per group, system ids) of one
        page. res None: the page was not analysed (a part-only build: none of
        the wanted parts has a staff on it and no movement starts there, so
        only multi-bar rests are needed)."""
        ap: dict[str, list] = {p: [] for p in want_parts}
        ag: dict[str, list] = {g: [] for g in want_groups}
        ids: list[str] = []
        if res is not None:
            check_page(res)
        for srec in recs:
            ids.append(srec["id"])
            if res is not None and expect.get(srec["id"]) != len(srec["staves"]):
                _die("systems differ from layout", f"Run: partitor detect {pdf} --force")
            m = sysmaps[srec["id"]]
            gsys = res.staves[srec["staves"][0]].system if res is not None else None
            # a part with no staff in this system rests for its bars: a
            # multi-bar rest keeps the part playable and its numbers right
            ls_ = lay_sys[srec["id"]]
            nb_ = span.get(srec["id"], 0)
            b0_ = ls_.get("bar") if isinstance(ls_.get("bar"), int) else None
            # a part whose staves here hold only rests (no noteheads read, no
            # stems): a multi-bar rest too (rests=compress). Not with a
            # rehearsal mark in the system (it would be lost).
            idle: set[str] = set()
            idle_g: set[str] = set()
            if res is not None and nb_ > 0 and opts["rests"] == "compress" \
                    and not marks_of.get(srec["id"]):
                stp_ = ls_.get("steps") or [None] * len(m)
                for part in dict.fromkeys(x for x in m if x != "-" and x in consumers):
                    ii = [i for i, x in enumerate(m) if x == part]
                    if all(i < len(stp_) and not stp_[i] for i in ii):
                        if all(staff_is_empty(res, srec["staves"][i]) for i in ii):
                            idle.add(part)
                        else:
                            _warn(f"rests:  {srec['id']}  {part}: ink that is not a rest, "
                                  "kept as engraved")
            if nb_ > 0:
                hdr_ = None
                if res is not None and gsys in res.restart:        # keep the movement title
                    hm = res.owner == OWN_HEADER_BASE + gsys
                    if hm.any():
                        ys_, xs_ = np.nonzero(hm)
                        sys_st = [st for st in res.staves if st.system == gsys]
                        tst = min(sys_st, key=lambda st: st.top)
                        y0h, y1h = int(ys_.min()), int(ys_.max()) + 1
                        x0h, x1h = int(xs_.min()), int(xs_.max()) + 1
                        hdr_ = (hm[y0h:y1h, x0h:x1h].copy(),
                                x0h - int(min(st.x0 for st in sys_st)),
                                max(0, int(round(tst.top)) - y1h))
                new_move = res is not None and gsys in res.restart
                rest = lambda: RestRun(nb_, b0_, new_move, hdr_)
                for part in ap:
                    if part not in m or part in idle:
                        ap[part].append(rest())
                for gname, gparts in groups.items():
                    if gname not in ag:
                        continue
                    here = [x for x in gparts if x in m]
                    if not here or all(x in idle for x in here):
                        ag[gname].append(rest())
                        idle_g.add(gname)
            if res is None:
                continue
            for part in dict.fromkeys(x for x in m if x != "-" and x not in idle):
                idx = [srec["staves"][i] for i, x in enumerate(m) if x == part]
                if part not in part_strips:
                    _fail(f"map:  {srec['id']}  (unknown part '{part}')")
                    continue
                if part not in ap:
                    continue                  # not wanted in this build
                edges = [min(res.staves[i].x0 for i in idx)] + res.barlines.get(gsys, [])
                mk = [(edges[i], str(t)) for i, t in marks_of.get(srec["id"], [])
                      if 0 <= i < len(edges)]
                gg = own_group_gap(lay, part, opts)
                if gg is not None and len(idx) > 1:       # a part on two staves
                    stp = group_strip(res, srec["staves"], [(part, [i]) for i in idx],
                                      OWN_HEADER_BASE + gsys, darker,
                                      bar_no=bar_of.get(srec["id"]), marks=mk,
                                      movement=gsys in res.restart,
                                      nums=nums_of.get(srec["id"], []), gap_sp=gg,
                                      labels=False)
                else:
                    stp = make_strip(res, idx, OWN_HEADER_BASE + gsys, darker,
                                     bar_no=bar_of.get(srec["id"]), marks=mk,
                                     movement=gsys in res.restart)
                stp.bar_raise, stp.bar_size = opts["bar_raise"], opts["bar_size"]
                set_bar_geometry(stp, res, idx, gsys, nums_of.get(srec["id"], []))
                ap[part].append(stp)
            for gname, gparts in groups.items():
                # a group score: the staves of its parts present in this
                # system, in score order, joined by a bracket
                if gname not in ag:
                    continue
                idx = [srec["staves"][i] for i, x in enumerate(m) if x in gparts]
                if not idx or gname in idle_g:
                    continue
                edges = [min(res.staves[i].x0 for i in idx)] + res.barlines.get(gsys, [])
                mk = [(edges[i], str(t)) for i, t in marks_of.get(srec["id"], [])
                      if 0 <= i < len(edges)]
                order = list(dict.fromkeys(x for x in m if x in gparts))
                runs = [(x, [srec["staves"][i] for i, y in enumerate(m) if y == x])
                        for x in order]
                stp = group_strip(res, srec["staves"], runs, OWN_HEADER_BASE + gsys, darker,
                                  bar_no=bar_of.get(srec["id"]), marks=mk,
                                  movement=gsys in res.restart,
                                  nums=nums_of.get(srec["id"], []),
                                  gap_sp=own_group_gap(lay, gname, opts))
                stp.bar_raise, stp.bar_size = opts["bar_raise"], opts["bar_size"]
                stp.bracket = len(idx) > 1
                ag[gname].append(stp)
        return ap, ag, ids

    def needs_page(pno: int) -> bool:
        """A part-only build analyses a page only when a wanted part has a
        staff on it or a movement starts on it (the title is read from the
        page). Every other page gives multi-bar rests, from the layout."""
        if not only:
            return True
        for sid in ids_by_page.get(pno, []):
            if lay_sys[sid].get("restart") or any(x in consumers for x in sysmaps[sid]):
                return True
        return False

    bar_edits = bar_edits_by_system(lay.get("bar_rules"))
    t_analysis = time.monotonic()
    todo = [pno for pno in pages if needs_page(pno)]
    todo_set = set(todo)
    jobs = job_count(getattr(a, "jobs", None), PAGE_WORKER_GB, len(todo))
    if only or jobs > 1:
        _note(f"analysing {len(todo)} of {len(pages)} page(s) with {jobs} worker(s)"
              + (f"; building {', '.join(only)} only" if only else ""))
    wdocs: dict[int, "pymupdf.Document"] = {}

    def page_task(pno: int):
        d_ = wdocs.get(os.getpid())
        if d_ is None:                    # one open document per process
            d_ = wdocs[os.getpid()] = pymupdf.open(pdf)
        _progress(f"page {pno + 1} ({pages.index(pno) + 1}/{len(pages)}): analysing")
        res, recs = analysis.analyse_one(d_, pno, dpi, 0, ocr=True, bar_edits=bar_edits)
        _progress_end()
        return consume(res, recs)

    # same analysis as detect, OCR included: printed bar numbers and
    # bracketed labels must be removed in build exactly as in detect
    outs = parallel.fork_map(page_task, todo, jobs)
    try:
        for k_, pno in enumerate(pages):
            if pno in todo_set:
                if jobs > 1:
                    _progress(f"page {pno + 1} ({k_ + 1}/{len(pages)}): waiting for its worker")
                ap_, ag_, ids_ = next(outs)
                if jobs > 1:
                    _progress_end()
            else:
                ap_, ag_, ids_ = consume(None, [{"id": sid, "staves": []}
                                                for sid in ids_by_page.get(pno, [])])
            seen.extend(ids_)
            for p_, v_ in ap_.items():
                part_strips[p_].extend(v_)
            for g_, v_ in ag_.items():
                group_strips[g_].extend(v_)
    finally:
        outs.close()
    if jobs > 1:
        _note(f"workers: {jobs}; the largest used {worker_peak_mb()} MB "
              f"(estimate for the worker count: {PAGE_WORKER_GB:.1f} GB)")
    t_render = time.monotonic()
    _note(f"analysis took {t_render - t_analysis:.0f} s")
    if seen != [s["id"] for s in lay["systems"]]:
        _die("systems differ from layout", f"Run: partitor detect {pdf} --force")
    if _counts["fail"]:
        return _summary(start)

    part_strips = {p: fill_rests(v, opts) for p, v in part_strips.items()}
    group_strips = {g: fill_rests(v, opts) for g, v in group_strips.items()}
    for v in group_strips.values():
        for s_ in v:
            if s_.rest_src is not None:
                s_.bracket = True      # a group's rest line keeps the system bracket
                                       # (operator request 2026-10-25: it had none)

    _head("Parts")
    parts_dir = Path(getattr(a, "parts_dir", None) or out / "parts")   # library: parts.new
    parts_dir.mkdir(exist_ok=True)
    tail = getattr(a, "tail", "") or ""       # library: -<piece>--<id>
    lines_dir = Path(a.lines_dir) if getattr(a, "lines_dir", None) else None   # library: lines.new
    if lines_dir is not None:
        lines_dir.mkdir(exist_ok=True)
    if opts.get("large") == "on" and opts["paper"] not in LARGE:
        _note(f"large copy: skipped (paper {opts['paper']} is already 11x17)")
    LAST_BUILD.clear()
    meta = {k: lay.get(k, "") for k in ("title", "subtitle", "composer", "composer_short")}

    plays = (lay.get("layout") or {}).get(PART_LAYOUT_KEY) or {}
    amb_data = {k: lay.get(k) for k in ("parts", "systems", "ambitus", SKIP_KEY)}
    refresh_ambitus(amb_data)
    # group members need their ambitus also when not extracted on their own
    amb_all = {**amb_data, SKIP_KEY: [], "ambitus": dict(amb_data.get("ambitus") or {})}
    refresh_ambitus(amb_all)

    def emit(name: str, strips: list[Strip], num: int, extra: dict, opts: dict = opts
             ) -> dict:
        # -> the record of the part for `built` (a worker returns it to the
        # parent; LAST_BUILD is filled there, in part order)
        # per-part layout (layout.parts) over the item layout; command-line
        # options (already in opts) are not overridden
        own = {k: v for k, v in (plays.get(name) or {}).items()
               if k in LAYOUT_DEFAULTS and k not in cli_set}
        if own:
            opts = {**opts, **own}
            for key in ("gap", "gap_min", "bar_raise", "bar_size", "max_staff_mm"):
                opts[key] = float(opts[key])
            opts["gap_min"] = min(opts["gap_min"], opts["gap"])
            _note(f"{name}: own layout " + " ".join(f"{k}={v}" for k, v in own.items()))
        h_max = 4.0 * strips[0].sp * 72.0 / dpi * fit_scale(strips, dpi, opts) * 25.4 / 72.0
        h_width = 4.0 * strips[0].sp * 72.0 / dpi * fit_scale(
            strips, dpi, {**opts, "scale": 1e9}) * 25.4 / 72.0   # page width only
        nsrc = len(strips)
        group = bool(extra.get("members"))
        if opts.get("reflow") == "on":
            pre = find_prefixes(strips)
            _note(f"{name}: {reflow_report(strips, pre)}")
            o_r, floor = opts, None
            if group and not opts.get("page_count"):
                # a group is several staves per line: its pages grow with the
                # square of the staff size (Biber Trombones: 12 pages at 3.7 mm,
                # about 60 at 8 mm). pages=auto: at most GROUP_REFLOW_PAGES times
                # the pages without re-flow; pages=N sets the count instead.
                base = finish_lines(strips, name, group, extra.get("ambitus"),
                                    extra.get("ambitus_map"))
                n0 = choose_layout(base, dpi, opts)[2]
                o_r = {**opts, "page_count": max(n0, math.ceil(GROUP_REFLOW_PAGES * n0))}
                floor = fit_scale(strips, dpi, {**opts, "scale": 1e9})
                _note(f"{name}: page budget {o_r['page_count']} (pages without re-flow {n0} "
                      f"x {GROUP_REFLOW_PAGES}); set pages=N to change it")
            sc, g, n_est, strips = choose_reflow(strips, dpi, o_r, pre, floor)
            strips = finish_lines(strips, name, group, extra.get("ambitus"),
                                  extra.get("ambitus_map"))
            sc = min(sc, fit_scale(strips, dpi, opts))
        else:
            # one line width, indent, labels: before the layout choice (labels
            # widen the lines)
            strips = finish_lines(strips, name, group, extra.get("ambitus"),
                                  extra.get("ambitus_map"))
            sc, g, n_est = choose_layout(strips, dpi, opts)
        o = {**opts, "scale": sc, "gap": g}
        if sc < fit_scale(strips, dpi, opts) - 1e-6:
            _note(f"{name}: staff reduced to fit {n_est} page(s) (fewer page turns)")
        if opts.get("page_count") and n_est > opts["page_count"]:
            _warn(f"page-count:  {name}  (cannot fit {opts['page_count']} page(s) above "
                  f"{opts['min_staff_mm']} mm staff and gap {opts['gap_min']} sp)")
        h_px = 4.0 * strips[0].sp   # one staff, top line to bottom line
        h_mm = h_px * 72.0 / dpi * sc * 25.4 / 72.0
        fn = parts_dir / (part_file_name(num, name, tail) if tail
                          else f"{num:02d}-{file_part_name(name)}.pdf")
        n = render_part(name, strips, {**meta, **extra}, dpi, o, fn)
        tl = LAST_RENDER.get("turns") or []
        nbad = count_bad_turns(tl, o)
        if o.get("turns", "any") == "rest" and nbad:
            _warn(f"turn-while-playing:  {name}  " + "; ".join(
                f"PDF page {t['pdf_page']} (after bar {t['bar']})" for t in tl
                if not t["resting"] and not t.get("movement"))
                  + "  (no rest to turn in; set breaks or accept)")
        if lines_dir is not None:
            save_lines(lines_path(lines_dir, name), name, dpi, {**meta, **extra}, o, strips)
        big = (large_copy(fn, opts["paper"])
               if opts.get("large") == "on" and opts["paper"] in LARGE else None)
        rec = {"part": name, "pages": n, "reflow": opts.get("reflow") == "on",
               "width_mm": round(h_width, 2),
               "content_pages": LAST_RENDER.get("content", n),
               "title_page": bool(LAST_RENDER.get("title_page")),
               "staff_mm": round(h_mm, 2),
               "staff_max_mm": round(h_max, 2), "gap": round(g, 2),
               "turns": len(tl), "bad_turns": nbad,
               "file": fn.name, **({"large": big.name} if big else {}),
               **({"group": True} if extra.get("members") else {})}
        flow = f" (re-flowed from {nsrc})" if opts.get("reflow") == "on" else ""
        _ok(f"{name}:  {len(strips)} lines{flow}  {n} page(s)  staff {h_mm:.1f} mm  "
            f"gap {g:.2f} sp  -> {fn}")
        if (opts.get("reflow_offer") == "on" and opts.get("reflow") != "on"
                and h_mm < opts["small_mm"] and h_width < opts["small_mm"]):
            _note(f"{name}: small print ({h_mm:.1f} mm, held by the source line width): "
                  f"re-flow can give up to {opts['max_staff_mm']:.0f} mm (--reflow on)")
        return rec

    # the steps in part order: messages, and the parts to render (one worker
    # each when jobs > 1; the numbers NN are those of all parts, also when only
    # some are built)
    steps: list[tuple] = []
    for num, (part, strips) in enumerate(part_strips.items(), 1):
        if only and part not in only:
            continue
        if part in skip:
            steps.append(("skip", f"part:  {part}  (not extracted)"))
        elif not strips:
            steps.append(("warn", f"part:  {part}  (no staves mapped)"))
        else:
            steps.append(("emit", part, strips, num, {"ambitus": ambitus_for(amb_data, part)}))
    for gi, (gname, strips) in enumerate(group_strips.items(), len(part_strips) + 1):
        if only and gname not in only:
            continue
        if not strips:
            steps.append(("warn", f"group:  {gname}  (none of its parts is mapped)"))
        else:
            steps.append(("emit", gname, strips, gi,
                          {"members": " · ".join(groups[gname]),
                           "ambitus_map": {p_: ambitus_for(amb_all, p_) for p_ in groups[gname]}}))
    emits = [st_ for st_ in steps if st_[0] == "emit"]
    rjobs = job_count(getattr(a, "jobs", None), RENDER_WORKER_GB, len(emits))
    if rjobs > 1:
        _note(f"rendering {len(emits)} part(s) with {rjobs} worker(s)")

    def render_task(i: int) -> dict:
        _, name_, strips_, num_, extra_ = emits[i]
        return emit(name_, strips_, num_, extra_)

    results = parallel.fork_map(render_task, range(len(emits)), rjobs)
    try:
        for st_ in steps:
            if st_[0] == "skip":
                _skip(st_[1])
            elif st_[0] == "warn":
                _warn(st_[1])
            else:
                LAST_BUILD.append(next(results))
    finally:
        results.close()
    if rjobs > 1:
        _note(f"workers: {rjobs}; the largest so far used {worker_peak_mb()} MB "
              f"(estimate for the worker count: {RENDER_WORKER_GB:.1f} GB)")
    _note(f"rendering took {time.monotonic() - t_render:.0f} s")
    return _summary(start)


def _engine_step(fn, ns: argparse.Namespace) -> int:
    """Run one engine command in-process with fresh counters; _die
    (SystemExit) becomes exit code 1."""
    _reset_counts()
    try:
        return fn(ns)
    except SystemExit as e:
        return int(e.code or 1) if not isinstance(e.code, str) else 1


def run_detect(item: Path, pages: str | None, title: str, composer: str,
               parts: str = "", jobs: str | None = None) -> int:
    """Run detect for an item (jobs: workers, a number or auto; None = PARTITOR_JOBS)."""
    ns = argparse.Namespace(pdf=str(item_file(item, "source.pdf")), pages=pages,
                            parts=parts, title=title, subtitle="", composer=composer,
                            dpi=400, out=str(item), page_header_sp=PAGE_HEADER_SP,
                            force=True, layout_name=score_name(item), jobs=jobs)
    sf = item_file(item, SCORE_FILE)
    before = load_item(item) if sf.is_file() else {}
    rc = _engine_step(cmd_detect, ns)
    # detect rewrites score.yaml: the item keys go back, also on failure
    if sf.is_file() and before:
        data = load_item(item)
        head = {k: before[k] for k in ("id", "slug", "created", "source") if k in before}
        if any(k not in data for k in head):
            save_item(item, {**head, **data})
    return rc


def run_build(item: Path, only: list[str] | None = None, jobs: str | None = None) -> int:
    """Build into parts.new/; only a build that succeeded replaces parts/
    (the old set stays in parts.prev/ until the next success). Before 0.3.0-dev.32
    the old parts were deleted first: a crash left none.

    only: the parts and groups to build (names, see parse_parts); the other
    parts keep their files, which are copied into the new set. A set that
    cannot keep them (partial_blocker) is built whole. jobs: workers, a
    number or auto."""
    recover_parts(item)
    data = load_item(item)
    iid = item_id(item)
    tail = f"-{piece_tag(data.get('composer', ''), data.get('title', ''))}--{iid}"
    if only:
        why = partial_blocker(item, data, only, tail)
        if why:
            _warn(f"rebuild:  all parts are built, not only {', '.join(only)}: {why}")
            only = None
    stage = item / PARTS_NEW
    shutil.rmtree(stage, ignore_errors=True)            # left by a build that was killed
    lstage = item / LINES_NEW
    shutil.rmtree(lstage, ignore_errors=True)
    ns = argparse.Namespace(pdf=str(item_file(item, "source.pdf")), pages=None,
                            out=str(item), layout_name=score_name(item), tail=tail,
                            parts_dir=str(stage), lines_dir=str(lstage), only=only, jobs=jobs)
    for key in LAYOUT_DEFAULTS:
        setattr(ns, key, None)
    rc = _engine_step(cmd_build, ns)
    if rc == 0 and LAST_BUILD and stage.is_dir():
        data = load_item(item)
        new = [dict(r) for r in LAST_BUILD]
        if only:
            try:
                new += keep_other_parts(item, data, stage, only)
            except OSError as e:
                shutil.rmtree(stage, ignore_errors=True)
                _fail(f"build:  the other parts could not be kept ({e}); parts/ is unchanged")
                return 1
            order = {nm: i for i, (_, nm) in enumerate(build_names(data))}
            new.sort(key=lambda r: order.get(r["part"], len(order)))
        swap_parts(item)
        keep_lines(item)
        _note(f"parts:  the set before is kept in {PARTS_PREV}/ until the next good build")
        data = load_item(item)
        if only:
            left = [x for x in data.get("pending") or []
                    if not any(x.startswith(f"{nm}:") for nm in only)]
            if left:
                data["pending"] = left
                _warn(f"not built in the other parts: {', '.join(left)}")
            else:
                data.pop("pending", None)
        else:
            data.pop("pending", None)
        data["built"] = {"date": time.strftime("%Y-%m-%d %H:%M"), "parts": new}
        save_item(item, data)
    elif rc == 0:
        shutil.rmtree(stage, ignore_errors=True)        # nothing was built
    elif stage.is_dir():
        _warn(f"parts:  the build did not finish: parts/ is unchanged; "
              f"the partial set is in {PARTS_NEW}/ (removed at the next build)")
    return rc


def build_report(item: Path) -> None:
    data = load_item(item)
    for r in (data.get("built") or {}).get("parts", []):
        print(f"     {r['part']}: {r['pages']} p  staff {r['staff_mm']:.1f} mm  "
              f"gap {r['gap']:.1f} sp")


def _rebuild_report(item: Path, before: dict | None, only: list[str] | None = None,
                    jobs: str | None = None) -> int:
    rc = run_build(item, only, jobs)
    _reset_counts()
    data = load_item(item)
    if rc:
        _fail("build:  failed (see above)")
        return 1
    _ok(f"rebuilt:  {item_line(item, data)}")
    if before and before.get("parts"):
        c0 = max(p.get("content_pages", p["pages"]) for p in before["parts"])
        c1 = max(p.get("content_pages", p["pages"]) for p in data["built"]["parts"])
        if c1 != c0:
            _warn(f"pages of music:  {c0} -> {c1}  (page turns {turns(c0)} -> {turns(c1)})")
    build_report(item)
    return 0


def small_parts(data: dict, only: list[str] | None = None) -> list[dict]:
    """Built parts and groups with small print that re-flow can enlarge:
    staff below small_mm because the source line width holds it, re-flow
    off (for the item and for the part). only: those names only (a build
    of some parts)."""
    b = (data.get("built") or {}).get("parts") or []
    lay = {**LAYOUT_DEFAULTS, **(data.get("layout") or {})}
    if lay.get("reflow") == "on":
        return []
    own = lay.get(PART_LAYOUT_KEY) or {}
    return [p for p in b if (only is None or p["part"] in only)
            and (own.get(p["part"]) or {}).get("reflow") != "on"
            and p["staff_mm"] < lay["small_mm"]
            and p.get("width_mm", 99.0) < lay["small_mm"]]


def _size_summary(built: dict, names: list[str] | None = None) -> tuple[float, int]:
    ps = [p for p in built.get("parts") or [] if names is None or p["part"] in names]
    return (min(p["staff_mm"] for p in ps),
            max(p.get("content_pages", p["pages"]) for p in ps))
