<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
<!-- Copyright (C) 2026 Nathan Wilkes and partitor contributors -->
# Operator guide: sources

`guide.md` and `problems.md` are the sources of the operator guide. The tool
`tools/build-operator-doc.py` builds `docs/operator-flow.html` from them and from
`operator.css` and `VERSION`. Do not edit the HTML. The website reads these
files. This file is the contract.

## Build and check

```
tools/build-operator-doc.py            # write docs/operator-flow.html
tools/build-operator-doc.py --check    # exit 1 if the committed file is old
```

Needs `python3` with `markdown-it-py` and `PyYAML` (Ubuntu: `apt install
python3-markdown-it python3-yaml`). Developer machines only. Commit the sources
and the generated file together. `tools/check-repo.sh` runs `--check`.

## guide.md

Front matter (YAML), all keys required:

| Key | Content |
|---|---|
| `page_title` | the `<title>` of the page |
| `title` | the `<h1>` |
| `lede` | the paragraph under the title (inline Markdown) |
| `stages` | list of five: `id`, `num`, `name`, `what`, `long` (`true` shows the dashed marker) |
| `legend` | the line under the stage strip (inline Markdown) |
| `footer` | the footer line; `{version}` becomes the content of `VERSION` |

Never type a version number in a source. The version comes from `VERSION`.

Body: one `##` section per id, in this order: `before`, `drop`, `analyse`,
`edit`, `review`, `build`. The heading line is:

```
## Heading text {#id eyebrow="Stage 2 · takes 1–5 minutes"}
```

`before` has no stage number. The stage ids in the front matter are the ids
`drop` to `build`. Use `###` for sub-headings. No other heading level.

| Need | Write |
|---|---|
| Code, a path, a prompt | a fenced code block or `` `code` `` |
| A key | `<kbd>r</kbd>` |
| A status | `<span class="pill wait">`, `act`, `go` or `done` |
| Bold, italic | `<b>`, `<i>` or Markdown |
| A note | one block `<p class="note">…</p>` or `<p class="note proof">…</p>` |
| A screen sample | one block `<div class="screen">…</div>` (`<b>` and `<i>` inside) |
| A table | a Markdown table |

No other raw HTML. A raw block holds no blank line. Links: `#anchors` and
links into this repo only. No link to an external host. No script.

## problems.md

Front matter: `title`, `eyebrow`, `columns` (two column names). Each `##`
heading is one problem: the text is what the player sees. The body is exactly
one paragraph: what to do. The website uses the pairs as its FAQ.

## Rules for both files

- No image, no image link, no screenshot of a score or part. Screenshots
  belong in the website repo, which keeps a rights ledger. A test fails on an
  image tag or image link in this folder.
- One place per fact. If another doc states a fact, link to it.
- Menu keys: every key in the item-menu tables of `guide.md` is a key of
  `item_menu` in `lib/partitor/cli_main.py`, and the other way round. A test
  checks it.
- Write in ASD-STE100 simplified technical English.
