#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""Check docs/ARCHITECTURE.md against the code. Stdlib only.

Usage:
  check-architecture.py          exit 1 when the document is stale or a diagram is wrong
  check-architecture.py --write  rewrite the generated block (module levels) from tools/modules.txt
  option --root DIR              repo root (default: the folder above tools/)

Checks:
  1. The generated block (between the GENERATED markers) equals the module levels of
     tools/modules.txt, for the modules that exist in lib/partitor/.
  2. Every ```mermaid block uses only the subset that the website draws (see the contract in
     ARCHITECTURE.md): `flowchart TB|LR`, `subgraph ID["Title"]` ... `end`, `ID["Label"]`,
     `A --> B`, `A <--> B`, `A -->|"text"| B`, `A -.-> B`, `A ~~~ B`, `%%` comments.
  3. Every repo path in the text (a `backtick` span or the first word of a node label that starts
     with bin/, lib/, docs/, tools/ or platforms/) exists.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

BEGIN = "<!-- BEGIN GENERATED: module-levels (tools/check-architecture.py --write) -->"
END = "<!-- END GENERATED -->"
PATH_RE = re.compile(r"^(?:bin|lib|docs|tools|platforms)/[\w./-]*[\w/-]$")
ID = r"[A-Za-z][A-Za-z0-9_]*"
NODE = re.compile(rf'^({ID})\["([^"\n]+)"\]$')
SUB = re.compile(rf'^subgraph ({ID})\["([^"\n]+)"\]$')
EDGE = re.compile(rf'^({ID})(?:\["[^"\n]+"\])? (<-->|-->|-\.->|~~~)(?:\|"([^"\n]+)"\|)? ?({ID})(?:\["[^"\n]+"\])?$')


def modules(root: Path) -> list[tuple[int, str]]:
    out = []
    for ln in (root / "tools" / "modules.txt").read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        lvl, name = ln.split()[:2]
        if (root / "lib" / "partitor" / f"{name}.py").is_file():
            out.append((int(lvl), name))
    return out


def generated(root: Path) -> str:
    mods = modules(root)
    levels = sorted({lvl for lvl, _ in mods}, reverse=True)
    L = ["```mermaid", "flowchart TB"]
    first = []
    for lvl in levels:
        L.append(f'  subgraph L{lvl}["Level {lvl}"]')
        names = [n for v, n in mods if v == lvl]
        for n in names:
            L.append(f'    {n}["{n}"]')
        L.append("  end")
        first.append(names[0])
    for a, b in zip(first, first[1:]):
        L.append(f"  {a} ~~~ {b}")
    L += ["```"]
    return "\n".join(L)


def mermaid_blocks(text: str):
    """Yield (first line number, [lines]) of each mermaid block."""
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        if lines[i].strip() == "```mermaid":
            j = i + 1
            while j < len(lines) and lines[j].strip() != "```":
                j += 1
            yield i + 2, lines[i + 1:j]
            i = j
        i += 1


def check_block(start: int, lines: list[str], root: Path, where: str) -> list[str]:
    errs = []
    if not lines or not re.fullmatch(r"flowchart (TB|LR)", lines[0].strip()):
        return [f"{where}:{start}: a diagram starts with `flowchart TB` or `flowchart LR`"]
    depth = 0
    for k, raw in enumerate(lines[1:], start + 1):
        ln = raw.strip()
        if not ln or ln.startswith("%%"):
            continue
        if SUB.match(ln):
            depth += 1
        elif ln == "end":
            depth -= 1
            if depth < 0:
                errs.append(f"{where}:{k}: `end` without `subgraph`")
        elif NODE.match(ln):
            label = NODE.match(ln).group(2)
            first = label.split()[0].strip(":,;")
            if re.match(r"^(bin|lib|docs|tools|platforms)/", first) and not (root / first.rstrip("/")).exists():
                errs.append(f"{where}:{k}: the path {first} in the label does not exist")
        elif not EDGE.match(ln):
            errs.append(f"{where}:{k}: not in the drawable subset: {ln}")
    if depth:
        errs.append(f"{where}:{start}: a `subgraph` has no `end`")
    return errs


def check(root: Path, doc: Path) -> list[str]:
    where = str(doc.relative_to(root))
    text = doc.read_text(encoding="utf-8")
    errs = []
    if BEGIN not in text or END not in text:
        return [f"{where}: the GENERATED markers are missing"]
    cur = text.split(BEGIN, 1)[1].split(END, 1)[0].strip("\n")
    if cur != generated(root):
        errs.append(f"{where}: the generated module-level block is old (run tools/check-architecture.py --write)")
    for start, lines in mermaid_blocks(text):
        errs += check_block(start, lines, root, where)
    for n, ln in enumerate(text.splitlines(), 1):
        for span in re.findall(r"`([^`]+)`", ln):
            if PATH_RE.match(span) and not (root / span.rstrip("/")).exists():
                errs.append(f"{where}:{n}: the path `{span}` does not exist")
    return errs


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--root", default=str(Path(__file__).resolve().parent.parent))
    a = ap.parse_args()
    root = Path(a.root)
    doc = root / "docs" / "ARCHITECTURE.md"
    if a.write:
        t = doc.read_text(encoding="utf-8")
        pre, rest = t.split(BEGIN, 1)
        _, post = rest.split(END, 1)
        doc.write_text(f"{pre}{BEGIN}\n{generated(root)}\n{END}{post}", encoding="utf-8")
        return 0
    errs = check(root, doc)
    for e in errs:
        print(f"check-architecture: FAIL {e}")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
