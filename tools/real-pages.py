#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""Real pages: single scan pages that once showed a defect, kept outside the repo.

The repo ships no score (copyright). The operator keeps a folder of one-page PDFs, cut from
the library, each with the values the engine must give for it. The tests read the folder
when PARTITOR_REAL_PAGES names it (tests/test_real_pages.py) and skip without it. The folder
also feeds the golden check (`g0_golden.py --corpus DIR`: the file is a G0 corpus manifest).

The expected values record what the engine gives NOW, after a person has looked at the page
and found it right. They are not a proof that the engine is right: it can still be wrong on
other pages, and a later fix can change a value. Then the value is changed in the same
release, with a CHANGELOG line. See docs/DESIGN.md section 10.

Folder `DIR`:
  corpus.yaml     the manifest (below); G0 reads `name`, `pdf` and `build` from it
  <name>.pdf      one page each (made by `extract`)

Manifest, one entry per page:
  items:
    - name: scan-two-sizes          neutral slug: no title, no composer
      pdf: scan-two-sizes.pdf       default <name>.pdf
      item: 2026-11-0010-...        library item folder (name or its start); only `extract` reads it
      page: 4                       page of the item's source PDF (from 1)
      fixed_in: 0.8.65              release that fixed what this page showed (a note for people)
      note: one line                what the page shows
      expect:
        systems: [4, 4, 4]          staves of each system, top first (checked by eye)
        title_above: [3]            systems (from 1) with a title above them; default []
        x0_spread_max: 0            optional: no system has staves whose start differs more (px at 400 dpi)

Usage:
  real-pages.py extract --library DIR --pages DIR [--only NAME,...]
        cut the pages of the manifest from the library items (the source PDF of each item)
  real-pages.py probe   --pages DIR [--only NAME,...] [--png DIR]
        analyse each page as the engine does and print the measured values next to
        the expected ones; --png writes a 60 dpi picture of each page, to look at it
        before you write an `expect`. Exit 1 when a value differs.
"""
import argparse
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DPI = 400                       # as tests/test_analysis.py TestCorpus


def load_items(pages_dir):
    man = Path(pages_dir) / "corpus.yaml"
    if not man.is_file():
        raise SystemExit(f"real-pages: no corpus.yaml in {pages_dir}")
    items = (yaml.safe_load(man.read_text()) or {}).get("items", [])
    for it in items:
        if "name" not in it:
            raise SystemExit("real-pages: an item has no name")
        it.setdefault("pdf", f"{it['name']}.pdf")
    return items


def select(items, only):
    if not only:
        return items
    keys = only.split(",")
    return [it for it in items if any(it["name"].startswith(k) for k in keys)]


def find_source(library, item):
    """The source PDF of the library item whose folder name is `item` or starts with it."""
    lib = Path(library)
    hits = sorted(d for d in lib.iterdir() if d.is_dir() and d.name.startswith(item))
    if len(hits) != 1:
        return None
    src = sorted(hits[0].glob("*-source.pdf"))
    return src[0] if len(src) == 1 else None


def extract(library, pages_dir, only=None):
    """Cut one page per item. -> list of lines to print (errors start with 'missing')."""
    import pymupdf
    out = []
    for it in select(load_items(pages_dir), only):
        if "item" not in it or "page" not in it:
            out.append(f"missing {it['name']}: the entry has no item or page")
            continue
        src = find_source(library, it["item"])
        if src is None:
            out.append(f"missing {it['name']}: no single source PDF for item {it['item']}")
            continue
        doc = pymupdf.open(src)
        n = int(it["page"])
        if not 1 <= n <= len(doc):
            out.append(f"missing {it['name']}: page {n} of {len(doc)}")
            continue
        doc.select([n - 1])
        doc.save(str(Path(pages_dir) / it["pdf"]), garbage=3, deflate=True)
        out.append(f"{it['name']}: page {n} of {src.parent.name} -> {it['pdf']}")
    return out


def measure(res):
    """The values the manifest checks, from a PageResult (ownership.analyse_page_mixed)."""
    sys.path.insert(0, str(ROOT / "lib"))
    from partitor import ownership
    titled = ownership.header_titles(res)
    return {
        "systems": [len(g) for g in res.systems],
        "title_above": [j + 1 for j, g in enumerate(res.systems) if g[0].system in titled],
        "x0_spread": [max(s.x0 for s in g) - min(s.x0 for s in g) for g in res.systems],
        "gate": list(res.gate),
    }


def compare(expect, got):
    """-> list of differences (empty: the page gives the expected values)."""
    bad = []
    if got["gate"]:
        bad.append(f"gate failed: {got['gate']}")
    if got["systems"] != expect.get("systems"):
        bad.append(f"systems {expect.get('systems')} -> {got['systems']}")
    if got["title_above"] != expect.get("title_above", []):
        bad.append(f"title_above {expect.get('title_above', [])} -> {got['title_above']}")
    cap = expect.get("x0_spread_max")
    if cap is not None and max(got["x0_spread"], default=0) > cap:
        bad.append(f"x0_spread {got['x0_spread']} is over {cap}")
    return bad


def analyse(pdf):
    """Analyse page 1 of a one-page PDF as the engine does (two staff sizes allowed)."""
    sys.path.insert(0, str(ROOT / "lib"))
    import pymupdf
    from partitor import ownership
    doc = pymupdf.open(pdf)
    return ownership.analyse_page_mixed(doc[0], 0, DPI, 0)


def probe(pages_dir, only=None, png=None):
    import pymupdf
    rc = 0
    for it in select(load_items(pages_dir), only):
        pdf = Path(pages_dir) / it["pdf"]
        if not pdf.is_file():
            print(f"{it['name']}: no PDF (run extract)")
            rc = 1
            continue
        got = measure(analyse(pdf))
        line = f"{it['name']}: systems {got['systems']} title_above {got['title_above']} x0_spread {got['x0_spread']}"
        if png:
            Path(png).mkdir(parents=True, exist_ok=True)
            pymupdf.open(pdf)[0].get_pixmap(dpi=60).save(str(Path(png) / f"{it['name']}.png"))
        if "expect" in it:
            bad = compare(it["expect"], got)
            line += "  OK" if not bad else "  DIFFERS: " + "; ".join(bad)
            rc = 1 if bad else rc
        else:
            line += "  (no expect yet)"
        print(line)
    return rc


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("mode", choices=["extract", "probe"])
    ap.add_argument("--pages", required=True)
    ap.add_argument("--library")
    ap.add_argument("--only")
    ap.add_argument("--png")
    a = ap.parse_args()
    if a.mode == "extract":
        if not a.library:
            ap.error("extract needs --library")
        lines = extract(a.library, a.pages, a.only)
        print("\n".join(lines))
        return 1 if any(x.startswith("missing") for x in lines) else 0
    return probe(a.pages, a.only, a.png)


if __name__ == "__main__":
    sys.exit(main())
