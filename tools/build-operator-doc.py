#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""Build docs/operator-flow.html from docs/operator/*.md.

Reads docs/operator/guide.md, docs/operator/problems.md, docs/operator/operator.css
and VERSION. Writes docs/operator-flow.html (committed; one self-contained page, no
script, no external request). The rules of the sources are in docs/operator/README.md.

  tools/build-operator-doc.py            write docs/operator-flow.html
  tools/build-operator-doc.py --check    build in memory; exit 1 if the file differs
  --root DIR                             repo root (default: the repo of this file)

Developer tool only. Needs python3 with the packages markdown-it-py and PyYAML
(Ubuntu: apt install python3-markdown-it python3-yaml). Users need nothing new.
Every error names the file and the line.
"""
from __future__ import annotations

import argparse
import html
import re
import sys
from pathlib import Path

try:
    import yaml
    from markdown_it import MarkdownIt
except ImportError as e:                      # pragma: no cover - message only
    sys.exit(f"build-operator-doc: missing {e.name}. Install: apt install "
             "python3-markdown-it python3-yaml")

GUIDE, PROBLEMS, CSS, OUT = ("docs/operator/guide.md", "docs/operator/problems.md",
                             "docs/operator/operator.css", "docs/operator-flow.html")
SECTION_IDS = ["before", "drop", "analyse", "edit", "review", "build"]
BANNER = "GENERATED from docs/operator/*.md by tools/build-operator-doc.py. Do not edit."

INLINE_OK = re.compile(r'^(</?(b|i|code|kbd)>|<span class="pill (wait|act|go|done)">|</span>)$')
BLOCK_OPEN = {'<p class="note">': "</p>", '<p class="note proof">': "</p>",
              '<div class="screen">': "</div>"}
BLOCK_OK = re.compile(r'^(</p>|</div>|<p class="note( proof)?">|<div class="screen">)$')
HEAD_RE = re.compile(r'^(?P<t>.+?)\s*\{#(?P<id>[a-z][a-z0-9-]*)\s+eyebrow="(?P<e>[^"]*)"\}$')
SCHEME_RE = re.compile(r"^([a-z][a-z0-9+.-]*:|//)", re.I)
URL_RE = re.compile(r"https?://", re.I)


class Errors:
    def __init__(self) -> None:
        self.items: list[str] = []

    def add(self, file: str, line: int | None, msg: str) -> None:
        self.items.append(f"{file}:{line}: {msg}" if line else f"{file}: {msg}")


def make_md() -> MarkdownIt:
    md = MarkdownIt("commonmark", {"html": True}).enable("table")
    rules = md.renderer.rules
    rules["bullet_list_open"] = lambda t, i, o, e: '<ul class="plain">\n'
    rules["ordered_list_open"] = lambda t, i, o, e: '<ol class="steps">\n'
    rules["table_open"] = lambda t, i, o, e: '<div class="tablewrap"><table>\n'
    rules["table_close"] = lambda t, i, o, e: "</table></div>\n"
    return md


def split_front(text: str, file: str, err: Errors) -> tuple[dict, str, int]:
    """-> (front matter, body, number of lines before the body)."""
    if not text.startswith("---\n"):
        err.add(file, 1, "the file must start with a front matter line '---'")
        return {}, text, 0
    end = text.find("\n---\n", 3)
    if end < 0:
        err.add(file, 1, "front matter is not closed with '---'")
        return {}, text, 0
    try:
        data = yaml.safe_load(text[4:end + 1]) or {}
    except yaml.YAMLError as e:
        err.add(file, 1, f"front matter is not valid YAML: {e}")
        data = {}
    if not isinstance(data, dict):
        err.add(file, 1, "front matter must be a mapping")
        data = {}
    return data, text[end + 5:], text[:end + 5].count("\n")


def walk(tokens):
    for t in tokens:
        yield t
        if t.children:
            yield from walk(t.children)


def check_tokens(tokens, file: str, base: int, err: Errors, fm_line: int | None = None) -> None:
    """The contract for raw HTML, images and links. base = lines before the body."""
    last = None                                  # the last line seen (table cells have no map)
    for t in walk(tokens):
        if t.map:
            last = base + t.map[0] + 1
        line = fm_line or last
        if t.type == "image":
            err.add(file, line, "image: no images in docs/operator/ (screenshots live in the website repo)")
        elif t.type == "link_open":
            href = t.attrGet("href") or ""
            if SCHEME_RE.match(href):
                err.add(file, line, f"link to an external host: {href}")
        elif t.type in ("text", "code_inline", "fence", "code_block") and URL_RE.search(t.content):
            err.add(file, line, "an external URL is not allowed")
        elif t.type == "html_inline" and not INLINE_OK.match(t.content.strip()):
            err.add(file, line, f"raw HTML not allowed: {t.content.strip()}")
        elif t.type == "html_block":
            body = t.content.strip()
            opener = next((o for o in BLOCK_OPEN if body.startswith(o)), None)
            if opener is None:
                err.add(file, line, "raw HTML block must start with <p class=\"note\">, "
                        "<p class=\"note proof\"> or <div class=\"screen\">")
                continue
            if not body.endswith(BLOCK_OPEN[opener]):
                err.add(file, line, f"raw HTML block must end with {BLOCK_OPEN[opener]}")
            for tag in re.findall(r"<[^>]*>", body):
                if not (INLINE_OK.match(tag) or BLOCK_OK.match(tag)):
                    err.add(file, line, f"raw HTML not allowed: {tag}")


def need(fm: dict, keys, file: str, err: Errors) -> None:
    for k in keys:
        if not isinstance(fm.get(k), str if k != "stages" and k != "columns" else list) or not fm.get(k):
            err.add(file, 1, f"front matter: '{k}' is missing or has the wrong type")


def sections(tokens, file: str, base: int, err: Errors, levels: tuple[int, ...]):
    """Split at level 2 headings -> list of (heading token, inline token, body tokens)."""
    out: list = []
    i = 0
    while i < len(tokens):
        t = tokens[i]
        if t.type == "heading_open":
            lvl = int(t.tag[1])
            if lvl not in levels:
                err.add(file, base + t.map[0] + 1, f"heading level {lvl} is not allowed here")
            if lvl == 2:
                out.append((t, tokens[i + 1], []))
            elif out:
                out[-1][2].extend(tokens[i:i + 3])
            i += 3
            continue
        if not out:
            err.add(file, base + (t.map[0] if t.map else 0) + 1, "text before the first '##' heading")
            i += 1
            continue
        out[-1][2].append(t)
        i += 1
    return out


def build(root: Path) -> tuple[str, list[str]]:
    """-> (html, errors). html is '' when there are errors."""
    err = Errors()
    md = make_md()
    version = (root / "VERSION").read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        err.add("VERSION", 1, f"not a version: {version!r}")
    css = (root / CSS).read_text(encoding="utf-8")

    # ---- guide
    gtext = (root / GUIDE).read_text(encoding="utf-8")
    fm, body, base = split_front(gtext, GUIDE, err)
    need(fm, ("page_title", "title", "lede", "legend", "footer", "stages"), GUIDE, err)
    stages = fm.get("stages") if isinstance(fm.get("stages"), list) else []
    for s in stages:
        if not (isinstance(s, dict) and set(s) == {"id", "num", "name", "what", "long"}
                and isinstance(s["long"], bool)):
            err.add(GUIDE, 1, "each stage needs exactly: id, num, name, what, long (true or false)")
    if [s.get("id") for s in stages if isinstance(s, dict)] != SECTION_IDS[1:]:
        err.add(GUIDE, 1, f"stage ids must be, in order: {', '.join(SECTION_IDS[1:])}")
    for key in ("lede", "legend", "footer"):
        if isinstance(fm.get(key), str):
            check_tokens(md.parseInline(fm[key], {}), GUIDE, base, err, fm_line=1)
    toks = md.parse(body)
    check_tokens(toks, GUIDE, base, err)
    secs = sections(toks, GUIDE, base, err, (2, 3))
    heads = []
    for h, inl, _ in secs:
        m = HEAD_RE.match(inl.content)
        line = base + h.map[0] + 1
        if not m:
            err.add(GUIDE, line, 'a "##" heading must end with {#id eyebrow="text"}')
            heads.append(None)
        else:
            heads.append(m)
    ids = [m["id"] for m in heads if m]
    if ids != SECTION_IDS and all(heads):
        err.add(GUIDE, 1, f"section ids must be, in order: {', '.join(SECTION_IDS)}; found: {', '.join(ids)}")

    # ---- problems
    ptext = (root / PROBLEMS).read_text(encoding="utf-8")
    pfm, pbody, pbase = split_front(ptext, PROBLEMS, err)
    need(pfm, ("title", "eyebrow", "columns"), PROBLEMS, err)
    cols = pfm.get("columns")
    if not (isinstance(cols, list) and len(cols) == 2 and all(isinstance(c, str) for c in cols)):
        err.add(PROBLEMS, 1, "front matter: 'columns' must be a list of two texts")
        cols = ["", ""]
    ptoks = md.parse(pbody)
    check_tokens(ptoks, PROBLEMS, pbase, err)
    psecs = sections(ptoks, PROBLEMS, pbase, err, (2,))
    rows = []
    for h, inl, rest in psecs:
        line = pbase + h.map[0] + 1
        if [t.type for t in rest] != ["paragraph_open", "inline", "paragraph_close"]:
            err.add(PROBLEMS, line, "the answer must be exactly one paragraph")
            continue
        rows.append((md.renderInline(inl.content), md.renderInline(rest[1].content)))
    if not psecs:
        err.add(PROBLEMS, 1, "no problem found")

    if err.items:
        return "", err.items

    # ---- render
    esc = html.escape
    nav = "".join(
        f'    <li><a href="#{s["id"]}"{" class=\"long\"" if s["long"] else ""}>'
        f'<span class="s-num">{s["num"]}</span><span class="s-name">{esc(s["name"])}</span>'
        f'<span class="s-what">{esc(s["what"])}</span></a></li>\n' for s in stages)
    parts = [
        f"<!-- {BANNER} -->\n<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
        f"<title>{esc(fm['page_title'])}</title>\n<style>\n{css}</style>\n</head>\n<body>\n\n"
        '<div class="wrap">\n<header>\n'
        f'  <span class="eyebrow">partitor {version}</span>\n  <h1>{esc(fm["title"])}</h1>\n'
        f'  <p class="lede">{md.renderInline(fm["lede"].strip())}</p>\n</header>\n\n'
        f'<nav aria-label="Stages">\n  <ol class="stages">\n{nav}  </ol>\n'
        f'  <p class="legend">{md.renderInline(fm["legend"].strip())}</p>\n</nav>\n\n'
        '<div class="staff" role="presentation"></div>\n']
    for (h, inl, rest), m in zip(secs, heads):
        parts.append(
            f'\n<section id="{m["id"]}">\n  <div class="sec-head"><span class="eyebrow">{esc(m["e"])}'
            f'</span><h2>{esc(m["t"])}</h2></div>\n'
            f'{md.renderer.render(rest, md.options, {})}</section>\n\n'
            '<div class="staff" role="presentation"></div>\n')
    rowhtml = "".join(f"      <tr><td>{a}</td><td>{b}</td></tr>\n" for a, b in rows)
    footer = md.renderInline(fm["footer"].strip().replace("{version}", version))
    parts.append(
        f'\n<section id="help">\n  <div class="sec-head"><span class="eyebrow">{esc(pfm["eyebrow"])}'
        f'</span><h2>{esc(pfm["title"])}</h2></div>\n  <div class="tablewrap"><table>\n'
        f'    <thead><tr><th>{esc(cols[0])}</th><th>{esc(cols[1])}</th></tr></thead>\n'
        f'    <tbody>\n{rowhtml}    </tbody>\n  </table></div>\n</section>\n\n'
        f'<footer>\n  <div class="staff" role="presentation"></div>\n  <p>{footer}</p>\n</footer>\n'
        '</div>\n</body>\n</html>\n')
    return "".join(parts), []


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build docs/operator-flow.html from docs/operator/*.md")
    ap.add_argument("--check", action="store_true", help="exit 1 if the committed file is not current")
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    a = ap.parse_args(argv)
    out, errors = build(a.root)
    if errors:
        print("build-operator-doc: contract errors:", file=sys.stderr)
        for e in errors:
            print("  " + e, file=sys.stderr)
        return 1
    target = a.root / OUT
    if a.check:
        have = target.read_text(encoding="utf-8") if target.is_file() else ""
        if have != out:
            print(f"build-operator-doc: {OUT} is not current. Run tools/build-operator-doc.py "
                  "and commit the result.", file=sys.stderr)
            return 1
        print("build-operator-doc: ok")
        return 0
    target.write_text(out, encoding="utf-8", newline="\n")
    print(f"build-operator-doc: wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
