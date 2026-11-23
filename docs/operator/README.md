<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
<!-- Copyright (C) 2026 Nathan Wilkes and partitor contributors -->
# Operator guide: sources

`guide.md`, `advanced.md` and `problems.md` are the sources of the operator guide. The tool
`tools/build-operator-doc.py` builds `docs/operator-flow.html` from them and from
`operator.css` and `VERSION`. Do not edit the HTML. The website reads these
files. This file is the contract. `guide.md` is the first-time flow only.
`advanced.md` holds the features a new user does not need. The tool does not
put `advanced.md` in the HTML file; the website shows it as its own page.

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

## advanced.md

Front matter (YAML), all keys required: `page_title`, `title`, `lede`.

Body: any number of `##` sections, each with a different id. The heading line
is the same as in `guide.md`: `## Heading text {#id eyebrow="Menu key g"}`.
Use `###` for sub-headings. The same rules for code, keys, tables, links and
raw HTML apply. Link to the first-time flow with `[guide](guide.md)`, and to
this file with `[Advanced](advanced.md)`.

Every command and option of `partitor` that a user needs is named in
`guide.md` or `advanced.md`.

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
- Write in simplified technical English (ASD-STE100 rules for sentences; no
  fixed word list). One idea in a sentence.
- The readers are professional musicians. Do not explain a musical term.
  Do not explain how parts are made. Say what to type and what happens.
- One word for one thing: bar (not measure), system, staff (not stave),
  part, group. A test fails on the other words.
- A table for keys, options and commands. A paragraph is at most 120 words.
