# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""Proof PDF: bar marks, rings and the ambitus on the preview pages."""
from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

from .bars import effective_systems, renumber, system_dropped
from .clef import extreme_bar, part_extremes, pitch_name
from .config import SCORE_FILE
from .library import item_file, load_item, natural_key


def proof_from_preview(item: Path) -> Path | None:
    """Join preview/page-*.png into proof.pdf (one page each), remove
    preview/, then label it (annotate_proof). proof.pdf opens in File
    Station and on a phone."""
    import pymupdf
    pdir = item / "preview"
    pngs = sorted(pdir.glob("page-*.png"), key=lambda p: natural_key(p.name))
    if not pngs:
        return None
    doc = pymupdf.open()
    for png in pngs:
        img = pymupdf.open(png)
        r = img[0].rect
        page = doc.new_page(width=r.width, height=r.height)
        page.insert_image(page.rect, filename=str(png))
    out = item_file(item, "proof.pdf")
    tmp = out.with_name(out.name + ".tmp")
    doc.save(tmp, garbage=3, deflate=True)
    os.replace(tmp, out)
    shutil.rmtree(pdir, ignore_errors=True)
    annotate_proof(item)
    return out


def _proof_pages(data: dict) -> list[int]:
    """Source page numbers (1-based) of the proof pages, in order."""
    m = re.fullmatch(r"\s*(\d+)\s*-\s*(\d+)\s*", str(data.get("pages") or ""))
    return list(range(int(m.group(1)), int(m.group(2)) + 1)) if m else []


PROOF_BAR = (0.62, 0.0, 0.62)       # bar numbers and barline ticks (magenta)
PROOF_LETTER = (0.85, 0.38, 0.0)    # rehearsal letters (orange)
NAME_FS = 13.0     # part name above a staff (pt)
BAR_FS = 11.0      # bar numbers
LETTER_FS = 12.0   # rehearsal letters
ID_FS = 14.0       # system id (p3.s1)


def proof_bars(page, e: dict, ef: dict, rules: dict, f: float, sts: list) -> None:
    """Draw the bars of one system on a proof page: a tick at each barline
    above the top staff, the bar number after it (magenta; '48 cont.' for a
    bar that completes the bar before it) and a boxed rehearsal letter
    (orange). Barlines: the system's widths (staff spaces from the staff
    start, bar edits applied) times the staff space. The first bar's number
    stands right of the part name above the staff."""
    import pymupdf
    g = e["geom"]
    nums = e.get("bar_nums") or []
    wd = [float(w) for w in ef.get("widths") or []]
    if not nums or len(wd) != len(nums) or not sts:
        return
    x0 = min(float(st[0]) for st in g["staves"])
    top, bot = float(g["staves"][0][1]), float(g["staves"][0][2])
    sp = (bot - top) / 4.0
    ty = top * f                                  # top line of the top staff
    letters = {int(m[0]): m[1] for m in e.get("marks") or []}
    split = set(rules.get("split") or [])
    incipit = set(rules.get("incipit") or [])
    maps = e.get("map") or []
    nm = maps[0] if maps else ""
    name_w = pymupdf.get_text_length(nm if nm not in ("?", "-") else "(left out)",
                                     fontname="helv", fontsize=NAME_FS) + 8
    edge = x0
    for i, n in enumerate(nums):
        left = edge * f
        edge += wd[i] * sp
        if i > 0:                                 # tick at the barline before bar i
            page.draw_line((left, ty - 9), (left, ty - 1), color=PROOF_BAR, width=1.0)
        lab = str(n) + (" cont." if f"{e['id']}:{i}" in split else "")
        if i == 0 and e["id"] in incipit:
            lab = "inc."                           # an incipit has no number
        x = left + 2 + (name_w if i == 0 else 0)
        if i in letters:
            fs = LETTER_FS
            tw = pymupdf.get_text_length(letters[i], fontname="hebo", fontsize=fs)
            box = pymupdf.Rect(x, ty - 11 - fs - 3, x + tw + 6, ty - 10)
            page.draw_rect(box, color=PROOF_LETTER, fill=(1, 1, 1), width=1.2)
            page.insert_text((x + 3, ty - 12.0), letters[i], fontsize=fs, fontname="hebo",
                             color=PROOF_LETTER)
            x = box.x1 + 2
        lw = pymupdf.get_text_length(lab, fontname="hebo", fontsize=BAR_FS)
        page.draw_rect(pymupdf.Rect(x - 1, ty - 11 - BAR_FS, x + lw + 1, ty - 10), color=None,
                       fill=(1, 1, 1), fill_opacity=0.6)
        page.insert_text((x, ty - 12.0), lab, fontsize=BAR_FS, fontname="hebo", color=PROOF_BAR)


def annotate_proof(item: Path, data: dict | None = None) -> None:
    """Redraw proof.pdf from its page images with labels from score.yaml:
    a header per page (source page), each system's name (p8.s2) in blue,
    each staff's part above its start in black; a system that needs a
    choice gets a red frame and '? suggestion' per staff; each part's
    lowest and highest note is ringed in green and named; the bars of each
    system: a tick at each barline, the bar number (magenta) and the
    rehearsal letters (orange, boxed), as the parts will print them; and
    page 1 lists the ambitus of every part. Run after detect and again
    after every change to the maps, part names, ambitus or bar rules.
    data: the layout to draw (the bars menu shows edits not yet saved);
    default: the saved score.yaml."""
    import pymupdf
    proof = item_file(item, "proof.pdf")
    if not proof.is_file() or not item_file(item, SCORE_FILE).is_file():
        return
    if data is None:
        data = load_item(item)
    rules_ = data.get("bar_rules") or {}
    renumber(data)                      # bar numbers and letters follow the bar rules
    eff_ = {e["id"]: e for e in effective_systems(data.get("systems") or [], rules_)}
    src = pymupdf.open(proof)
    pages = _proof_pages(data)
    out = pymupdf.open()
    by_page: dict[int, list[dict]] = {}
    for e in data.get("systems") or []:
        g = e.get("geom")
        if g:
            by_page.setdefault(int(g["page"]), []).append(e)
    # ambitus: where each part's lowest and highest note stands (checked on
    # the proof before printing; operator request 2026-10-25)
    amb = data.get("ambitus") or {}
    ext: dict[tuple[str, int], list[tuple[str, str, int]]] = {}
    for part, a_ in amb.items():
        if a_.get("from") == "off":
            continue
        for sid, kk, which, xx, d in part_extremes(data, part):
            ext.setdefault((sid, kk), []).append((part, which, xx, d))
    amb_line = "ambitus: " + "  ·  ".join(
        f"{p_} {a_.get('range') or 'none'}" + (" (by hand)" if a_.get("from") == "operator" else "")
        for p_, a_ in amb.items() if a_.get("from") != "off")
    for k, sp_page in enumerate(src):
        imgs = sp_page.get_images(full=True)
        if not imgs:
            continue
        pix = pymupdf.Pixmap(src, imgs[0][0])
        page = out.new_page(width=sp_page.rect.width, height=sp_page.rect.height)
        page.insert_image(page.rect, pixmap=pix)
        pno = pages[k] if k < len(pages) else k + 1
        need = [e for e in by_page.get(pno, []) if "?" in (e.get("map") or [])]
        head = (f"source page {pno}" + (f"  -  {len(need)} system(s) to choose (red)"
                                         if need else "")
                + "  |  bars: magenta numbers, boxed letters")
        hw = pymupdf.get_text_length(head, fontname="hebo", fontsize=12)
        hfs = min(12.0, 12.0 * (page.rect.width - 16) / max(hw, 1.0))
        page.insert_text((8, 16), head, fontsize=hfs, fontname="hebo",
                         color=(0.8, 0, 0) if need else (0, 0, 0.6))
        if k == 0 and amb:
            aw = pymupdf.get_text_length(amb_line, fontname="helv", fontsize=9)
            afs = min(9.0, 9.0 * (page.rect.width - 16) / max(aw, 1.0))
            page.insert_text((8, 28), amb_line, fontsize=afs, fontname="helv",
                             color=(0, 0.45, 0))
        for e in by_page.get(pno, []):
            g = e["geom"]
            f = page.rect.height / float(g["h"])
            sts = [(x0 * f, t * f, b * f) for x0, t, b in g["staves"]]
            uncertain = "?" in (e.get("map") or [])
            col = (0.8, 0, 0) if uncertain else (0, 0, 0.6)
            hgt = max(4.0, sts[0][2] - sts[0][1])
            if uncertain:
                x0 = min(s_[0] for s_ in sts) - 0.6 * hgt
                page.draw_rect(pymupdf.Rect(x0, sts[0][1] - 1.2 * hgt,
                                            page.rect.width - 4, sts[-1][2] + 0.5 * hgt),
                               color=col, width=2)
            page.insert_text((max(2.0, sts[0][0] - 3.2 * hgt), sts[0][1] - 0.5 * hgt),
                             e["id"] + (" dropped" if system_dropped(e) else ""),
                             fontsize=ID_FS, fontname="hebo", color=col)
            maps = e.get("map") or []
            sug = e.get("suggest") or []
            proof_bars(page, e, eff_.get(e["id"], e), rules_, f, sts)
            for j, (x0, t, b) in enumerate(sts):
                name = maps[j] if j < len(maps) else "?"
                if name == "?":
                    txt = f"? {sug[j]}" if j < len(sug) else "?"
                elif name == "-":
                    txt = "(left out)"
                else:
                    txt = name
                fs = NAME_FS
                w = pymupdf.get_text_length(txt, fontname="helv", fontsize=fs)
                r = pymupdf.Rect(x0 + 2, t - fs - 3, x0 + w + 6, t - 1)
                page.draw_rect(r, color=None, fill=(1, 1, 1), fill_opacity=0.85)
                page.insert_text((x0 + 4, t - 3), txt, fontsize=fs, fontname="helv",
                                 color=(0.8, 0, 0) if name == "?" else (0, 0, 0))
                st_ = (e.get("steps") or [None] * (j + 1))[j] if j < len(e.get("steps") or []) else None
                for part, which, xx, d in ext.get((e["id"], j), []):
                    if not st_ or not xx:
                        continue
                    stp = st_[0] if which == "low" else st_[1]
                    cx, cy = xx * f, b - stp * (b - t) / 8.0
                    rad = max(3.0, 0.22 * (b - t))
                    page.draw_circle((cx, cy), rad, color=(0, 0.55, 0), width=1.5)
                    bn = extreme_bar(data, e["id"], st_, which)
                    lbl = (f"{part} {which} {pitch_name(d)}" + (f", bar {bn}" if bn else "")
                           + f" ({e['id']})")
                    ly = cy + rad + 8 if which == "low" else cy - rad - 3
                    lw_ = pymupdf.get_text_length(lbl, fontname="helv", fontsize=7.5)
                    page.draw_rect(pymupdf.Rect(cx - 1, ly - 7.5, cx + lw_ + 3, ly + 2),
                                   color=None, fill=(1, 1, 1), fill_opacity=0.85)
                    page.insert_text((cx + 1, ly), lbl, fontsize=7.5, fontname="helv",
                                     color=(0, 0.45, 0))
    tmp = proof.with_name(proof.name + ".tmp")
    out.save(tmp, garbage=3, deflate=True)
    src.close()
    os.replace(tmp, proof)
