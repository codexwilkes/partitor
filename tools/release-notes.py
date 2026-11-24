#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""Print the release notes of one version: its section of CHANGELOG.md.

Usage: tools/release-notes.py TAG [--changelog FILE] [--version-file FILE]

TAG is a version such as 0.18.5 or 0.19.0-beta.1 (no "v"). The section starts at the line
"## TAG — date" and ends before the next "## " line. The tool exits 1, with a message on
stderr, when the tag is not a version, the heading is missing, the section is empty, or the
file VERSION does not equal TAG. The release workflow (.github/workflows/release.yml) uses it.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TAG_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.]+)?$")


def notes(tag: str, changelog: str, version: str | None = None) -> str:
    """notes -> the text of the section of tag; ValueError says what is wrong."""
    if not TAG_RE.match(tag):
        raise ValueError(f"{tag!r} is not a version (X.Y.Z or X.Y.Z-suffix, no v)")
    if version is not None and version.strip() != tag:
        raise ValueError(f"VERSION is {version.strip()!r}, the tag is {tag!r}")
    lines = changelog.splitlines()
    head = re.compile(r"^## " + re.escape(tag) + r"(\s|$)")
    start = next((i for i, ln in enumerate(lines) if head.match(ln)), None)
    if start is None:
        raise ValueError(f"CHANGELOG.md has no heading '## {tag} — date'")
    body: list[str] = []
    for ln in lines[start + 1:]:
        if ln.startswith("## "):
            break
        body.append(ln)
    text = "\n".join(body).strip()
    if not text:
        raise ValueError(f"the section {tag} of CHANGELOG.md is empty")
    return text + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Print the CHANGELOG section of a version")
    ap.add_argument("tag")
    ap.add_argument("--changelog", default=str(ROOT / "CHANGELOG.md"))
    ap.add_argument("--version-file", default=str(ROOT / "VERSION"))
    a = ap.parse_args(argv)
    try:
        version = Path(a.version_file).read_text(encoding="utf-8")
        out = notes(a.tag, Path(a.changelog).read_text(encoding="utf-8"), version)
    except (ValueError, OSError) as e:
        print(f"release-notes: {e}", file=sys.stderr)
        return 1
    sys.stdout.write(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
