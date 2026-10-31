# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""Tunables, TUNE, layout and score keys, defaults and name helpers."""
from __future__ import annotations

import hashlib
import re
import unicodedata
from pathlib import Path


# =============================================================================
# Analysis tunables (staff spaces unless stated)
# =============================================================================
BAND_MARGIN = 0.25        # staff band extends this far beyond outer lines
CLOSE_SP = 1.0            # gap component this near a staff belongs to it
CHAIN_SP = 1.0            # vertical reach for chaining (ledger stacks)
TEXT_ABOVE_FRAC = 0.6     # text in the upper 60% of a gap: staff above
TEXT_REVIEW_FRAC = 0.07   # |frac - TEXT_ABOVE_FRAC| below this: review
PAGE_HEADER_SP = 6.0      # above first staff, farther than this: discard
                          # (layout key page_header_sp overrides)
PAGE_FOOTER_SP = 6.0      # below last staff, farther than this: discard
FOOTER_TEXT_SP = 4.0      # nearer, from here: discard when the text is a footer
THIN_VERTICAL_SP = 0.6    # multi-staff component narrower than this: barline
BRACKET_MAX_SP = 6.0      # widest left bracket/brace
MAX_SKEW_DEG = 3.0
GROUP_GAP_SP = 1.5        # max horizontal gap inside one text line
SP_MIN_PX, SP_MAX_PX = 10, 70   # plausible staff space at 400 dpi (scaled)
TRACK_BANDS = 16          # vertical bands for staff tracking
NOISE_AREA_SP2 = 0.03     # components smaller than this (sp^2): noise
NOISE_WARN_FRAC = 0.005   # noise above this share of page ink: warning
DEWARP_MIN_PX = 1.5       # straighten when a staff bends more than this
LABEL_ABOVE_SP = 2.5      # label text this near above a staff start
EDGE_LEFT_SP = 0.3        # system window: staff ink left of start - this
EDGE_RIGHT_SP = 1.5       #   or right of the widest staff end + this is not
BRACKET_ZONE_SP = 2.0     #   music: bracket (this near the start) or edge
BARNUM_ZONE_SP = 4.5      # printed bar numbers: this far above the top line
PAPER_GUARD = 230         # local ink must be darker than this (flattened)

TUNE = {'page_header_sp': PAGE_HEADER_SP}   # set from layout / CLI

# Owner codes in the per-pixel owner image. Staff owners are 0..n-1.
OWN_NONE = -1             # must not remain after analysis
OWN_DISCARD = -2          # unclassified discard: must not occur (gate)
D_HEADER = -3             # page title / running header zone
D_FOOTER = -4             # footer zone (page number, copyright)
D_LABEL = -5              # instrument label (left of or above a staff)
D_BRACKET = -6            # bracket / brace at the system start
D_CONNECTOR = -7          # barline / bracket pixels inside a staff gap
D_EDGE = -8               # page-edge artefact (border, spine, corner)
D_NOISE = -9              # despeckled noise
D_NOMUSIC = -10           # page without accepted staves
D_BARNUM = -11            # printed bar number at a system start (replaced)
DUST_AREA_SP2 = 0.15      # a lone header speck below this area (sp^2) is noise
OWN_HEADER_BASE = 100000  # OWN_HEADER_BASE + global system index
DISCARD_NAMES = {OWN_DISCARD: "unclassified", D_HEADER: "header",
                 D_FOOTER: "footer", D_LABEL: "label", D_BRACKET: "bracket",
                 D_CONNECTOR: "connector", D_EDGE: "edge", D_NOISE: "noise",
                 D_NOMUSIC: "no-music", D_BARNUM: "bar-number"}
# Classes that may hide a missed staff: checked by the safety gate.
GATE_CLASSES = (OWN_DISCARD, D_HEADER, D_FOOTER, D_LABEL, D_EDGE, D_NOMUSIC)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# =============================================================================
# Layout file
# =============================================================================
LAYOUT_HELP = """\
# partitor layout file. Edit, then run: partitor build <score.pdf>
# page_header_sp: text above a page's first staff farther than this (staff
#   spaces) is discarded (page title, running header); nearer text (movement
#   title) is copied to every part. Change it, then run detect --force.
# systems[].map: part per staff, top first. A part name twice = a two-staff
#   part. '-' drops a staff. '?' must be replaced before build; `suggest`
#   holds the best guess (copy it to `map` if it is right).
# systems[].bar: number of the first bar of the system (counted from the
#   barlines, checked against printed numbers). Computed: to correct it,
#   use bar_rules (below), not this value.
# layout: settings for build; command-line options override them. Keys left
#   out take the built-in default, so new defaults reach old layouts. Keys
#   (default; build option):
#   paper: letter | a4 | ledger (letter; --paper). ledger = 17 x 11 in
#     landscape, no large-print copy; the staff is chosen
#     as large as possible first (pages and page turns follow)
#   gap: staff spaces between staves, the widest leading (10; --gap)
#   gap_min: smallest leading to save a page turn (7; --min-gap)
#   clearance: least space between ink of two lines, sp (1; --clearance)
#   scale: largest size, 1 = source size (none: up to max_staff_mm; --scale)
#   max_staff_mm: largest staff height (8; --max-staff-mm)
#   turns: any | rest (any; per part; `repage` sets rest). rest = a page turn
#     falls only beside a multi-bar rest line (the player rests); a turn
#     elsewhere is a warning, except a movement start when no rest is near (a
#     note: it may be attacca). any = also at a movement start or a letter.
#   breaks: per part, bar numbers after which a page ends (none; `set ID
#     "Trombones:breaks=45,60"`, `+45` add, `-45` drop, `none`). A line must
#     end at the bar; lines are never cut.
#   group_gap: space between the staves of a group score line, or of a part on
#     two staves, bottom line to top line, staff spaces (source: the distance
#     of the source score; 1-40; `set ID "Trombones:group_gap=5"`)
#   reflow: off | on (experimental, on hold; for a larger staff use
#     paper ledger); on = new lines cut at barlines (clef and key copied),
#     for a staff up to max_staff_mm when the source line width keeps it
#     small; more pages (a group: at most 1.5 x the pages without re-flow
#     when pages=auto). The CLI offers it (off; --reflow)
#   rests: compress | keep; compress = empty staves become multi-bar rests
#     (compress; --rests)
#   title_page: auto | off; auto = a title page for 3+ pages of music
#     printed double-sided (auto; --title-page)
#   logo: on | off; the logo (PARTITOR_LOGO) on the first page and the back page
#     (on; `set ID logo=off`)
#   min_staff_mm: smallest staff height (5; --min-staff-mm)
#   page_count: force this many pages (none; --page-count)
#   margin_top, margin_bottom, margin_side: mm (15, 15, 15; --margin-top,
#     --margin-bottom, --margin-side)
#   gutter: mm added at the spine in double-sided print and taken from
#     the outer margin (5; --gutter)
#   duplex: auto | on | off; auto = double-sided when over 2 pages
#     (auto; --duplex)
#   bar_numbers: start | none (start; --bar-numbers)
#   bar_raise: least height of a bar number baseline above the staff, sp;
#     a number also clears the clef by 0.5 sp (1; --bar-raise)
#   bar_size: bar number size, sp (2; --bar-size)
#   ink: normal | darker (normal; --ink)
#   large: on | off; on = also a large-print copy per part: Letter -> 11x17
#     with crop marks at the cut line, A4 -> A3 (on; --large)
#   small_mm: below this staff height (held by the source line width) the
#     CLI offers re-flow (6.5), when reflow_offer is on
#   reflow_offer: on | off; off = no re-flow question after a build and no
#     small-print note (off: re-flow is on hold; `set ID reflow_offer=on`)
#   parts: {part or group: {key: value}}: layout of one part over the
#     values above (pages, gap, scale, reflow, ...); set with
#     partitor set <id> "Continuo:pages=4" or expand/contract <id> <part>
# skip: parts not extracted (no PDF); they stay in parts and in the maps.
# groups: {name: [parts]}: group scores; the staves of the parts printed
#   together, joined by a bracket, one more PDF per group.
# bar_rules: pickup (movement-first system ids: first bar is bar 0), split
#   ('<system id>:<bar index>': that bar completes the bar before it and
#   keeps its number), fix ({system id: first bar}); bar and marks
#   (rehearsal letters) of every system follow from them at build.
#   marks_add / marks_drop: with / without a rehearsal mark: a bar number
#   (the first bar with that number) or '<system id>:<bar index>' (that bar,
#   index from 0, for a number two bars share); added to / taken from the
#   marks found after repeats; the marks of a movement are lettered A, B,
#   ... in bar order. A split may stand at any bar (a bar cut by a line
#   break, a repeat sign or a change of mensuration).
#   bar_edits: mend a misread barline, one string per edit, applied in order
#   to the detected barlines of a line. "<system id>:j<N>/<R>" joins bar N
#   with the next (a false barline); "<system id>:a<N>@<P>/<R>" adds a
#   barline in bar N at P % of its width (a missed barline). R = bars
#   detected in the line when the edit was made (a join of a clef stub keeps
#   its repeat start, stored as repeats [-1, start]); an edit is skipped (and
#   warned) when the line has another number of bars after a new analysis.
#   Set with partitor bars <id> (j, a, u). bars_ack: printed bar numbers
#   the operator kept where they differ from the barline count (k).
#   bar_rules_status: proposed (by detect) or confirmed (by the CLI).
"""

# Layout defaults (layout.yaml `layout:`; build options override). gap and
# gap_min in staff spaces between one staff's bottom line and the next
# staff's top line. Starting values, to be set from printed test pages.
LAYOUT_DEFAULTS = {"paper": "letter", "scale": None, "gap": 10.0, "gap_min": 7.0,
                   "clearance": 1.0, "page_count": None, "min_staff_mm": 5.0,
                   "ink": "normal", "bar_numbers": "start",
                   "margin_top": 15.0, "margin_bottom": 15.0, "margin_side": 15.0,
                   "gutter": 5.0, "duplex": "auto",
                   "bar_raise": 1.0, "bar_size": 2.0, "large": "on", "logo": "on",
                   "title_page": "auto", "reflow": "off", "rests": "compress", "max_staff_mm": 8.0,
                   "small_mm": 6.5, "group_gap": None, "reflow_offer": "off",
                   "turns": "any", "breaks": None}

HEADER_CLEAR_SP = 2.5  # min clearance above header ink (staff spaces)

SYSTEM_GAP_FACTOR = 1.5   # group score: gap between systems / gap between its staves

SYSTEM_CLEAR_SP = 3.0     # group score: least ink distance between systems (sp)

AMB_SP = 3.4            # ambitus staff space, pt (staff 13.6 pt = 4.8 mm high)

LINES_NEW = "lines.new"


def file_part_name(name: str) -> str:
    """Part name -> file-safe ASCII (hyphens, no spaces)."""
    s = re.sub(r"[^\w\s-]", "", name, flags=re.ASCII).strip()
    return re.sub(r"[\s_]+", "-", s) or "part"


SCORE_FILE = "score.yaml"     # item files are <id>-score.yaml, <id>-source.pdf, <id>-proof.pdf

SIZE_FIRST = {"ledger"}   # paper where the largest staff comes before fewest page turns

PART_LAYOUT_KEY = "parts"   # layout.parts: {part or group: {layout key: value}}


def slugify(text: str, limit: int = 60) -> str:
    """slugify -> lowercase ASCII words joined by hyphens. German letters
    as German writes them without accents (Schütz -> schuetz, gegrüßet ->
    gegruesset; 0.3.0-dev.20: "gegruet" lost the ß); other accents
    dropped (é -> e). Cut at a word boundary within limit characters."""
    t = re.sub(r"['\u2019`]", "", text)          # Vat'r -> vatr
    for a_, b_ in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("Ä", "Ae"), ("Ö", "Oe"),
                   ("Ü", "Ue"), ("ß", "ss")):
        t = t.replace(a_, b_)
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode("ascii")
    words = re.findall(r"[a-z0-9]+", t.lower())
    out = ""
    for w in words:
        nxt = f"{out}-{w}" if out else w
        if len(nxt) > limit:
            break
        out = nxt
    return out or (words[0][:limit] if words else "")


def make_slug(composer: str, title: str) -> str:
    """make_slug -> <composer-surname>-<short-title> (DESIGN.md §2.1). A
    leading number with a dot ("23. Komm ...") is dropped from the title."""
    sur = slugify(composer.split()[-1]) if composer.split() else ""
    t = re.sub(r"^\s*\d+\s*[.)]\s*", "", title)
    short = slugify(t, 40)
    return "-".join(x for x in (sur, short) if x) or "untitled"


def composer_surname(composer: str) -> str:
    """Short composer name for interior pages: the last word ('Johann
    Hermann Schein' -> 'Schein'; 'J.S. Bach' -> 'Bach')."""
    words = re.findall(r"[^\s.]+(?:-[^\s.]+)*", composer.strip())
    return words[-1] if words else ""


def part_file_name(num: int, part: str, tail: str) -> str:
    """Part PDF name: '07-bass-trombone-Schein-Maria--2026-10-0001.pdf':
    part number (2 digits, so 10+ parts sort), part, piece, id; the
    player finds the part first."""
    return f"{num:02d}-{slugify(part)}{tail}.pdf"


SKIP_KEY = "skip"     # score.yaml: part names not extracted (kept in the list)
