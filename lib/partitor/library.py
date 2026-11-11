# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""Item folder, ids, load and save, set keys, parts folder swap."""
from __future__ import annotations

import os
import re
import shutil
import time
import unicodedata
from pathlib import Path

import yaml

from . import config
from .bars import renumber
from .clef import order_pitches, parse_pitch, pitch_str, refresh_ambitus
from .config import (
    LAYOUT_DEFAULTS, LAYOUT_HELP, LINES_NEW, PART_LAYOUT_KEY, SCORE_FILE, SKIP_KEY,
    check_margins, composer_surname, make_slug, part_file_name,
)
from .console import _warn


# =============================================================================
# Library (library folder, DESIGN.md §2-3, §6)
# =============================================================================
# Library layout: <library>/inbox/*.pdf (operator drops PDFs), <library>/library/
# <id>-<slug>/ with <id>-source.pdf, <id>-score.yaml, <id>-proof.pdf, parts/. The library
# folder comes from PARTITOR_LIBRARY (set by the partitor wrapper), default
# /var/lib/partitor/library. The folder is local or an SMB mount: the engine
# does not know which. score.yaml is the engine's layout file plus the item keys
# (id, slug, created, built); the CLI is the only writer.
LIBRARY_DEFAULT = "/var/lib/partitor/library"
# item id: YYYY-MM-NNNN (year and month of the extraction, serial in the
# year); items of 0.3.0-dev.6 and before: YYYY-NNN (still found)
ITEM_RE = re.compile(r"^(\d{4})-(?:(\d{2})-(\d{4})|(\d{3}))(?:-|$)")
ITEM_HELP = """\
# partitor score.yaml — written by the partitor CLI. Change it with
#   partitor set <id> key=value   (or the item menu), not by hand.
#   Edits are saved, not built: `pending` lists them; partitor rebuild <id>
#   builds. composer: full name (page 1); composer_short: interior pages.
"""
PAPER_NEXT = {"letter": "a4", "a4": "ledger", "ledger": "letter"}   # menu `a`
SET_KEYS = {          # set key -> (layout key or None for metadata, parser)
    "title": (None, str), "subtitle": (None, str), "composer": (None, str),
    "composer_short": (None, str),
    "pages": ("page_count", "pages"), "paper": ("paper", ("letter", "a4", "ledger")),
    "gap": ("gap", float), "min_gap": ("gap_min", float),
    "ink": ("ink", ("normal", "darker")), "scale": ("scale", float),
    "min_staff_mm": ("min_staff_mm", float),
    "margin_top": ("margin_top", float), "margin_bottom": ("margin_bottom", float),
    "margin_side": ("margin_side", float), "gutter": ("gutter", float),
    "binding": ("binding", float),
    "duplex": ("duplex", ("auto", "on", "off")),
    "bar_numbers": ("bar_numbers", ("start", "none")),
    "bar_raise": ("bar_raise", float), "bar_size": ("bar_size", float),
    "large": ("large", ("on", "off")),
    "cutline": ("cutline", ("dotted", "marks", "off")),
    "logo": ("logo", ("on", "off")),
    "reflow": ("reflow", ("on", "off")), "reflow_offer": ("reflow_offer", ("on", "off")),
    "max_staff_mm": ("max_staff_mm", float),
    "title_page": ("title_page", ("auto", "off")),
    "group_gap": ("group_gap", "gapsp"),
    "rests": ("rests", ("compress", "keep")),
    "rest_bar": ("rest_bar", ("engraved", "bold", "heavy")),
    "turns": ("turns", ("any", "rest")), "breaks": ("breaks", "breaks"),
    "foldouts": ("foldouts", ("off", "on")), "foldside": ("foldside", ("right", "left", "auto")),
}
GAP_MAX = 14.0        # expand never sets a wider gap (sp)
PART_SET_KEYS = {"pages", "gap", "min_gap", "scale", "min_staff_mm", "max_staff_mm", "group_gap",
                 "reflow", "title_page", "bar_raise", "bar_size", "ink", "turns", "breaks",
                 "paper", "margin_top", "margin_bottom", "margin_side", "gutter", "binding", "duplex",
                 "foldouts", "foldside", "short"}
SHORT_MAX = 24        # longest short form of a part name (`Part:short=...`)
REPAGE_KEYS = ("turns", "breaks", "duplex", "title_page", "foldouts", "foldside")   # `repage` applies these without a rebuild


def set_name(layout_key: str) -> str:
    """set_name -> the `set` key of a layout key (page_count -> pages)."""
    return next((k for k, (lk, _) in SET_KEYS.items() if lk == layout_key), layout_key)


def set_value(key: str, val) -> str:
    """set_value -> a value as `set` takes it; unset pages = auto, other
    unset keys = their default."""
    if val is None:
        if key == "pages":
            return "auto"
        if key == "group_gap":
            return "source"
        if key == "breaks":
            return "none"
        lk = SET_KEYS.get(key, (key, None))[0]
        return f"{LAYOUT_DEFAULTS.get(lk)} (default)"
    return str(val)


def part_names(data: dict) -> list[str]:
    """part_names -> extracted parts (not skipped) and group names."""
    skip = set(data.get(SKIP_KEY) or [])
    return [p for p in data.get("parts") or [] if p not in skip and p != "-"] + \
        list((data.get("groups") or {}).keys())


def part_layout(data: dict, part: str | None) -> dict:
    """part_layout -> layout of the item with the overrides of one part."""
    lay = {k: v for k, v in (data.get("layout") or {}).items() if k != PART_LAYOUT_KEY}
    if part:
        lay.update(((data.get("layout") or {}).get(PART_LAYOUT_KEY) or {}).get(part) or {})
    return {**LAYOUT_DEFAULTS, **lay}


def step_size(data: dict, bigger: bool, part: str | None = None
              ) -> tuple[list[str], str]:
    """step_size -> (set pairs, reason) for one expand/contract step:
    size first (pages +-1), then gap (+-1 sp) (DESIGN.md §5.2). part: that
    part only (pairs 'Part:key=value'), else all parts."""
    b = (data.get("built") or {}).get("parts") or []
    if part:
        b = [p for p in b if p.get("part") == part]
        if not b:
            raise ValueError(f"{part}: not built yet")
    if not b:
        raise ValueError("not built yet")
    lay = part_layout(data, part)
    pre = f"{part}:" if part else ""
    pages = max(p.get("content_pages", p["pages"]) for p in b)
    room = any(p["staff_mm"] < p["staff_max_mm"] - 0.05 for p in b)
    if bigger:
        if room:
            return [f"{pre}pages={pages + 1}"], "larger staff on one more page"
        if lay.get("reflow") != "on" and any(
                p.get("width_mm", 99.0) < lay["max_staff_mm"] - 0.05 for p in b):
            return [f"{pre}reflow=on"], "staff held by the source line width; lines re-flowed"
        if lay["gap"] < GAP_MAX:
            return [f"{pre}gap={min(GAP_MAX, lay['gap'] + 1)}"], "staff at full width; more space"
        raise ValueError("at the largest size and gap")
    if pages > 1:
        return [f"{pre}pages={pages - 1}"], "one page less, smaller staff"
    if lay["gap"] - 1 >= lay["gap_min"]:
        return [f"{pre}gap={lay['gap'] - 1}"], "less space between staves"
    raise ValueError("at the smallest gap on one page")


def library_root() -> Path:
    return Path(os.environ.get("PARTITOR_LIBRARY", LIBRARY_DEFAULT))


LOGO_FILE = "logo.png"      # the library's own logo, next to inbox/ and library/


def library_logo(root: Path) -> Path | None:
    """library_logo -> the logo file of the library at root (DESIGN.md §5.5);
    None when there is none."""
    p = Path(root, LOGO_FILE)
    return p if p.is_file() else None


def item_dirs(lib: Path) -> list[Path]:
    if not lib.is_dir():
        return []
    return sorted(d for d in lib.iterdir() if d.is_dir() and ITEM_RE.match(d.name))


def _id_parts(name: str) -> tuple[int, int | None, int] | None:
    """(year, month or None, serial) of an item folder name or id."""
    m = ITEM_RE.match(name)
    if not m:
        return None
    if m.group(3):
        return int(m.group(1)), int(m.group(2)), int(m.group(3))
    return int(m.group(1)), None, int(m.group(4))


def item_id(item: Path) -> str:
    """The id at the start of an item folder name."""
    m = ITEM_RE.match(item.name)
    if not m:
        raise ValueError(f"not an item folder: {item.name}")
    return m.group(0).rstrip("-")


def next_id(lib: Path, year: int, month: int) -> str:
    """next_id -> 'YYYY-MM-NNNN': one more than the highest serial of the
    year (old YYYY-NNN items count too)."""
    top = 0
    for d in item_dirs(lib):
        ip = _id_parts(d.name)
        if ip and ip[0] == year:
            top = max(top, ip[2])
    if top >= 9999:
        raise ValueError(f"no free id in {year}")
    return f"{year}-{month:02d}-{top + 1:04d}"


def resolve_id(ref: str, year: int) -> tuple[int, int | None, int]:
    """resolve_id '12' | '2026-12' | '2026-10-0012' | '2026-012' ->
    (year, month or None, serial). A serial alone means this year."""
    ref = ref.strip()
    m = re.fullmatch(r"(\d{1,4})", ref)
    if m:
        return year, None, int(m.group(1))
    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,4})", ref)
    if m:
        return int(m.group(1)), int(m.group(2)), int(m.group(3))
    m = re.fullmatch(r"(\d{4})-(\d{1,4})", ref)
    if m:
        return int(m.group(1)), None, int(m.group(2))
    raise ValueError(f"not an id: {ref} (use 12 or 2026-10-0012)")


def find_item(lib: Path, ref: str) -> Path:
    y, mo, n = resolve_id(ref, time.localtime().tm_year)
    hits = [d for d in item_dirs(lib)
            if (ip := _id_parts(d.name)) and ip[0] == y and ip[2] == n
            and (mo is None or ip[1] == mo)]
    if not hits:
        raise ValueError(f"no item {ref} in {lib}")
    return hits[0]


def item_file(item: Path, kind: str) -> Path:
    """item_file(item, 'score.yaml' | 'source.pdf' | 'proof.pdf') -> the
    item's file, named <id>-<kind> so it keeps its id out of the folder
    (operator request 2026-10-24). An old plain-named file is renamed on first use."""
    old = item / kind
    if not ITEM_RE.match(item.name):              # not a library item (tests, scratch)
        return old
    new = item / f"{item_id(item)}-{kind}"
    if not new.exists() and old.exists():
        os.replace(old, new)
    return new


def score_name(item: Path) -> str:
    return item_file(item, SCORE_FILE).name


def piece_tag(composer: str, title: str) -> str:
    """piece_tag -> 'Schein-Maria': composer surname and the first word of
    the title (leading number dropped), ASCII, case kept."""
    fold = lambda t: unicodedata.normalize("NFKD", re.sub(r"['\u2019`]", "", t)) \
        .encode("ascii", "ignore").decode("ascii")
    sur = re.findall(r"[A-Za-z0-9]+", fold(composer.split()[-1]))[:1] if composer.split() else []
    t = re.sub(r"^\s*\d+\s*[.)]\s*", "", title)
    word = re.findall(r"[A-Za-z0-9]+", fold(t))[:1]
    return "-".join(sur + word) or "piece"


def load_item(item: Path) -> dict:
    """load_item -> score.yaml of an item. A missing id comes from the
    folder name (a failed detect left score.yaml without item keys; the
    menu showed "2026-10-", operator request 2026-10-25)."""
    data = config.yaml_load(item_file(item, SCORE_FILE).read_text(encoding="utf-8")) or {}
    if not data.get("id") and ITEM_RE.match(item.name):
        data["id"] = item_id(item)
    return data


def save_item(item: Path, data: dict) -> None:
    """Write <id>-score.yaml atomically (temp file + rename on the share).
    The ambitus of every part follows the maps (refresh_ambitus)."""
    if data.get("systems"):
        refresh_ambitus(data)
    dst = item_file(item, SCORE_FILE)
    tmp = dst.with_name(dst.name + ".tmp")
    tmp.write_text(ITEM_HELP + LAYOUT_HELP + yaml.safe_dump(
        data, sort_keys=False, allow_unicode=True, default_flow_style=None, width=100),
        encoding="utf-8")
    os.replace(tmp, dst)


def natural_key(name: str) -> list:
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


def inbox_pdfs(share: Path) -> list[Path]:
    inbox = share / "inbox"
    if not inbox.is_dir():
        return []
    return sorted((p for p in inbox.iterdir()
                   if p.is_file() and p.suffix.lower() == ".pdf"),
                  key=lambda p: natural_key(p.name))


def suggest_meta(pdf: Path) -> tuple[str, str]:
    """suggest_meta -> (title, composer) from PDF metadata, else the file
    name (IMSLP pattern 'IMSLP123-PMLP45-Composer_Title.pdf' handled)."""
    import pymupdf
    title = composer = ""
    try:
        md = pymupdf.open(pdf).metadata or {}
        title = (md.get("title") or "").strip()
        composer = (md.get("author") or "").strip()
    except Exception:          # metadata is only a suggestion
        pass
    if not title:
        stem = re.sub(r"^IMSLP\d+-(PMLP\d+-)?", "", pdf.stem)
        title = re.sub(r"[_]+", " ", stem).strip()
    return title, composer


def item_status(data: dict) -> str:
    """not analysed | needs choices | ready to build | changes not built |
    built (DESIGN.md §6.2: edits are saved; only a build makes PDFs)."""
    if "systems" not in data:
        return "not analysed"
    if any("?" in (s.get("map") or ["?"]) for s in data.get("systems", [])):
        return "needs choices"
    if not data.get("built"):
        return "ready to build"
    if data.get("pending"):
        return "changes not built"
    return "built"


def mark_pending(data: dict, *what: str) -> None:
    """Note edits since the last build (shown in review; cleared by a build)."""
    pend = list(data.get("pending") or [])
    for w in what:
        if w and w not in pend:
            pend.append(w)
    if pend:
        data["pending"] = pend


def item_line(item: Path, data: dict) -> str:
    """One-line summary: id · composer (short) · title · parts · pages · staff."""
    b = data.get("built") or {}
    parts = data.get("parts") or []
    out = [p for p in parts if p not in set(data.get(SKIP_KEY) or [])]
    comp = data.get("composer_short") or composer_surname(data.get("composer", ""))
    bits = [data.get("id") or item_id(item)] + ([comp] if comp else []) + \
        [data.get("title") or "(no title)", f"{len(out)} parts"]
    if b.get("parts"):
        pages = max(p["pages"] for p in b["parts"])
        staff = min(p["staff_mm"] for p in b["parts"])
        bits += [f"{pages} page{'s' * (pages != 1)}", f"staff {staff:.1f} mm"]
        if data.get("pending"):
            n = len(data["pending"])
            bits.append(f"{n} change{'s' * (n != 1)} not built")
    else:
        bits.append(item_status(data))
    return " · ".join(str(x) for x in bits)


PARTS_NEW, PARTS_PREV = "parts.new", "parts.prev"


def recover_parts(item: Path) -> None:
    """A build that stopped between the two renames of swap_parts left no
    parts folder: put the previous set back (it is complete)."""
    if not (item / "parts").exists() and (item / PARTS_PREV).is_dir():
        os.replace(item / PARTS_PREV, item / "parts")
        _warn(f"parts:  a build stopped while it swapped the folders; the previous parts "
              f"are back in parts/")


def swap_parts(item: Path) -> None:
    """After a build that succeeded: parts/ -> parts.prev/ (the set before; the
    one before that goes now), parts.new/ -> parts/. A build that fails or
    is killed never reaches here, so parts/ is always a complete set."""
    new, cur, prev = item / PARTS_NEW, item / "parts", item / PARTS_PREV
    shutil.rmtree(prev, ignore_errors=True)
    if cur.exists():
        os.replace(cur, prev)
    os.replace(new, cur)


def keep_lines(item: Path) -> None:
    """After a good build: the lines of the parts built now (lines.new/) go
    into lines/; the lines of parts not built now stay. A failed build never
    reaches here, so lines/ always match a set of parts."""
    new, cur = item / LINES_NEW, item / "lines"
    if not new.is_dir():
        return
    cur.mkdir(exist_ok=True)
    for f in new.glob("*.lines"):
        os.replace(f, cur / f.name)
    shutil.rmtree(new, ignore_errors=True)


def restore_previous_parts(item: Path) -> bool:
    """Undo the last swap: parts.prev/ becomes parts/ again (the trial set
    goes). False when there is no previous set."""
    cur, prev = item / "parts", item / PARTS_PREV
    if not prev.is_dir():
        return False
    shutil.rmtree(cur, ignore_errors=True)
    os.replace(prev, cur)
    shutil.rmtree(item / "lines", ignore_errors=True)   # they match the set that went
    return True


def build_names(data: dict) -> list[tuple[int, str]]:
    """build_names -> (NN, name) of every output in file order: the parts (also
    those not extracted: they keep their number), then the groups that have
    a member. NN is the number in the part file name (cmd_build uses the same)."""
    parts = list(data.get("parts") or [])
    groups = [g for g, ps in (data.get("groups") or {}).items()
              if any(p in parts for p in (ps or []))]
    return list(enumerate(parts + [str(g) for g in groups], 1))


def selection_help(data: dict) -> str:
    skip = set(data.get(SKIP_KEY) or [])
    nparts = len(data.get("parts") or [])
    return "  ".join(f"{n} {nm}{' (not extracted)' if nm in skip else ''}"
                     f"{' (group)' if n > nparts else ''}"
                     for n, nm in build_names(data) if nm != "-")


def parse_parts(data: dict, words: list[str]) -> list[str] | None:
    """parse_parts -> the parts and groups named by `words`, in file order; None
    when they are every part (a full build). Each word is a number (the NN of
    the part file and of `show`; groups come after the parts), a range
    (2-4), a name (not case sensitive; several words make one name: Bass
    Trombone Grosso) or the start of a name that no other name starts with.
    `all` is every part. Commas and semicolons separate like spaces.
    Raises ValueError (what is wrong), never builds."""
    outs = [(n, nm) for n, nm in build_names(data) if nm != "-"]
    if not outs:
        raise ValueError("no parts yet (analyse first)")
    by_num = dict(outs)
    names = [nm for _, nm in outs]
    low = {nm.casefold(): nm for nm in names}
    skip = set(data.get(SKIP_KEY) or [])
    toks = re.sub(r"[,;]", " ", " ".join(words)).split()
    chosen: list[str] = []
    i = 0
    while i < len(toks):
        hit = None
        for j in range(len(toks), i, -1):               # the longest name first
            cand = " ".join(toks[i:j]).casefold()
            if cand in low:
                hit = (j, low[cand])
                break
        if hit:
            chosen.append(hit[1])
            i = hit[0]
            continue
        t = toks[i]
        i += 1
        if t.casefold() == "all":
            chosen.extend(nm for nm in names if nm not in skip)
            continue
        m = re.fullmatch(r"(\d+)(?:-(\d+))?", t)
        if m:
            lo, hi = int(m.group(1)), int(m.group(2) or m.group(1))
            if lo > hi:
                raise ValueError(f"{t}: the range runs backwards")
            for n in range(lo, hi + 1):
                if n not in by_num:
                    raise ValueError(f"no part number {n}")
                chosen.append(by_num[n])
            continue
        pre = [nm for nm in names if nm.casefold().startswith(t.casefold())]
        if len(pre) == 1:
            chosen.append(pre[0])
        elif pre:
            raise ValueError(f"{t}: more than one part starts so ({', '.join(pre)})")
        else:
            raise ValueError(f"no part or group {t}")
    if not chosen:
        raise ValueError("no part named")
    gone = [nm for nm in dict.fromkeys(chosen) if nm in skip]
    if gone:
        raise ValueError(f"not extracted: {', '.join(gone)} (menu t: N=+ extracts it)")
    ordered = [nm for nm in names if nm in set(chosen)]
    if set(ordered) >= {nm for nm in names if nm not in skip}:
        return None
    return ordered


def partial_blocker(item: Path, data: dict, names: list[str], tail: str) -> str | None:
    """partial_blocker -> why a build of `names` only cannot leave the other parts
    as they are (None: it can). The other parts keep their files only when
    each is built, its file is there, and the name a full build would give it
    now (number, piece, id) is the name it has."""
    built = {r["part"]: r for r in (data.get("built") or {}).get("parts") or []}
    pdir = item / "parts"
    if not built or not pdir.is_dir():
        return "nothing built yet"
    skip = set(data.get(SKIP_KEY) or [])
    for num, nm in build_names(data):
        if nm in names or nm == "-" or nm in skip or nm not in built:
            continue
        r = built[nm]
        want = part_file_name(num, nm, tail)
        if r.get("file") != want:
            return f"the file name of {nm} would change ({r.get('file')} -> {want})"
        for k in ("file", "large", "large_flaps"):
            if r.get(k) and not (pdir / r[k]).is_file():
                return f"{r[k]} is not in parts/"
    return None


def keep_other_parts(item: Path, data: dict, stage: Path, names: list[str]) -> list[dict]:
    """keep_other_parts -> the `built` records of the parts not in `names`, after
    copying their files from parts/ into the stage (the new set is then
    complete, so parts.prev/ keeps the whole old set for an undo)."""
    cur = {nm for _, nm in build_names(data)}
    keep = []
    for r in (data.get("built") or {}).get("parts") or []:
        if r["part"] in names or r["part"] not in cur:
            continue
        for k in ("file", "large", "large_flaps"):
            if r.get(k):
                shutil.copy2(item / "parts" / r[k], stage / r[k])
        keep.append(dict(r))
    return keep


def merge_item_keys(item: Path, keep: dict, again: bool = False) -> dict:
    """After detect rewrote score.yaml: put back the item keys and settings.
    again (an analysis again): also the operator's part list, groups, skip
    list and ambitus (when the staves carry the same names), and the
    previous answer as the suggestion of a system still uncertain."""
    data = load_item(item)
    head = {k: keep[k] for k in ("id", "slug", "created") if k in keep}
    data = {**head, **data}
    if keep.get("layout"):
        data["layout"] = dict(keep["layout"])
    kr = keep.get("bar_rules") or {}
    if kr.get("marks_add") or kr.get("marks_drop"):   # marks set by the operator
        br = dict(data.get("bar_rules") or {})
        for k in ("marks_add", "marks_drop"):
            if kr.get(k):
                br[k] = list(kr[k])
        data["bar_rules"] = br
        renumber(data)
    for k in ("title", "subtitle", "composer", "composer_short", "pending"):
        if keep.get(k):
            data[k] = keep[k]
    # an analysis again keeps groups and parts not extracted when the
    # part names are the same
    if again and keep.get("parts"):
        named = [p for p in data.get("parts") or [] if p != "-"]
        if set(named) <= set(keep["parts"]):
            data["parts"] = list(keep["parts"])      # the operator's order and names
        old = {e["id"]: e for e in keep.get("systems") or []}
        for e in data.get("systems") or []:
            o = old.get(e["id"])
            if o and "?" in (e.get("map") or []) and len(o.get("map") or []) == len(e["map"]) \
                    and "?" not in o["map"]:
                e["suggest"] = list(o["map"])        # Enter takes the previous answer
        if keep.get("ambitus"):
            data["ambitus"] = {p: dict(v) for p, v in keep["ambitus"].items()}
    if keep.get("parts") == data.get("parts"):
        for k in ("groups", SKIP_KEY):
            if keep.get(k):
                data[k] = keep[k]
    save_item(item, data)
    return data


def folder_name(item: Path, data: dict) -> str:
    """folder_name -> the folder name the item's composer and title give:
    <id>-<composer surname>-<short title> (DESIGN.md §2.1)."""
    return f"{item_id(item)}-{make_slug(data.get('composer', ''), data.get('title', ''))}"


def apply_set(data: dict, pairs: list[str]) -> list[str]:
    """apply_set -> changes made ('key: old -> new'). Raises ValueError on a
    bad key or value; nothing is changed then."""
    lay = dict(data.get("layout") or {})
    plays = {n: dict(v) for n, v in (lay.get(PART_LAYOUT_KEY) or {}).items()}
    amb = {n: dict(v) for n, v in (data.get("ambitus") or {}).items()}
    meta = {}
    done = []
    for pr in pairs:
        if "=" not in pr:
            raise ValueError(f"not key=value: {pr}")
        k, v = (x.strip() for x in pr.split("=", 1))
        part = None
        if ":" in k:                       # "Continuo:pages=4": one part only
            part, k = (x.strip() for x in k.rsplit(":", 1))
            if k == "short":
                # the short form of a group staff label (0.8.30): any part of
                # the score, also one not extracted on its own (a group member)
                known = [p_ for p_ in data.get("parts") or [] if p_ != "-"]
                if part not in known:
                    raise ValueError(f"unknown part: {part} (parts: {', '.join(known)})")
                pl = plays.setdefault(part, {})
                was = pl.get("short")
                vl = v.strip()
                if vl.lower() in ("", "auto", "none", "off"):
                    pl.pop("short", None)           # back to the rule (short_name)
                else:
                    if len(vl) > SHORT_MAX or any(c in vl for c in "\n\r\t"):
                        raise ValueError(f"short: at most {SHORT_MAX} characters on one line, or auto")
                    pl["short"] = vl
                done.append(f"{part}:short: {was or 'auto'} -> {pl.get('short') or 'auto'}")
                continue
            if part not in part_names(data):
                raise ValueError(f"unknown part: {part} (parts: {', '.join(part_names(data))})")
            if k == "ambitus":
                # "Alto I:ambitus=C4-F5" (by hand, kept), auto, on (a
                # continuo-like part too), off
                was = amb.get(part) or {}
                vl = v.strip()
                if vl.lower() in ("auto", "on", "off"):
                    amb[part] = {"range": "", "from": vl.lower()}
                else:
                    lo_, sep, hi_ = vl.partition("-")
                    if not sep:
                        raise ValueError("ambitus: LOW-HIGH (e.g. C4-F5, F#3-Bb4; # sharp, b flat), auto, on or off")
                    a_, b_ = order_pitches(parse_pitch(lo_), parse_pitch(hi_))
                    amb[part] = {"range": f"{pitch_str(*a_)}-{pitch_str(*b_)}",
                                 "from": "operator"}
                done.append(f"{part}:ambitus: {was.get('range') or was.get('from') or 'auto'}"
                            f" -> {amb[part]['range'] or amb[part]['from']}")
                continue
            if k not in PART_SET_KEYS:
                raise ValueError(f"{k}: not a per-part key (keys: {', '.join(sorted(PART_SET_KEYS))})")
        if k not in SET_KEYS:
            raise ValueError(f"unknown key: {k} (keys: {', '.join(sorted(SET_KEYS))})")
        lk, kind = SET_KEYS[k]
        if lk is None:
            meta[k] = v
            done.append(f"{k}: {data.get(k, '')!r} -> {v!r}")
            continue
        if kind == "pages":
            val = None if v.lower() == "auto" else int(v)
            if val is not None and not 1 <= val <= 99:
                raise ValueError("pages: auto or 1-99")
        elif kind == "breaks":
            if part is None:
                raise ValueError("breaks: per part only (\"Trombones:breaks=45,60\")")
            cur = [int(x) for x in (plays.get(part) or {}).get("breaks") or []]
            vl = v.strip().lower()
            if vl in ("none", "off", "auto", ""):
                val, nums = None, []
            else:
                try:
                    nums = [int(x) for x in re.split(r"[,\s]+", vl.lstrip("+-")) if x]
                except ValueError:
                    raise ValueError("breaks: bar numbers after which a page ends: "
                                     "45,60 (replace), +45 (add), -45 (drop), none")
                if vl.startswith("+"):
                    val = sorted(set(cur) | set(nums))
                elif vl.startswith("-"):
                    val = sorted(set(cur) - set(nums))
                else:
                    val = sorted(set(nums))
            if val is not None and any(b < 0 for b in val):
                raise ValueError("breaks: bar numbers are 0 or more")
            val = val or None
        elif kind == "gapsp":
            val = None if v.lower() in ("auto", "source", "none") else float(v)
            if val is not None and not 1.0 <= val <= 40.0:
                raise ValueError("group_gap: 1-40 staff spaces, or source")
        elif isinstance(kind, tuple):
            if v not in kind:
                raise ValueError(f"{k}: one of {', '.join(kind)}")
            val = v
        else:
            val = kind(v)
        if part is not None:
            pl = plays.setdefault(part, {})
            done.append(f"{part}:{k}: {set_value(k, pl.get(lk, lay.get(lk)))} -> "
                        f"{set_value(k, val)}")
            if val is None:
                pl.pop(lk, None)
            else:
                pl[lk] = val
            continue
        done.append(f"{k}: {set_value(k, lay.get(lk))} -> {set_value(k, val)}")
        if val is None:
            lay.pop(lk, None)
        else:
            lay[lk] = val
    base = {k: v for k, v in lay.items() if k != PART_LAYOUT_KEY}
    err = check_margins({**LAYOUT_DEFAULTS, **lay})
    for nm, pl in plays.items():              # a part's own margins (0.8.4)
        e_ = check_margins({**LAYOUT_DEFAULTS, **base, **pl})
        err = err or (f"{nm}: {e_}" if e_ else "")
    if err:
        raise ValueError(err)
    plays = {n: v for n, v in plays.items() if v}
    if plays:
        lay[PART_LAYOUT_KEY] = plays
    else:
        lay.pop(PART_LAYOUT_KEY, None)
    data.update(meta)
    data["layout"] = lay
    if amb:
        data["ambitus"] = amb
        if data.get("systems"):
            refresh_ambitus(data)
    return done


def id_order(item: Path) -> tuple[int, int]:
    ip = _id_parts(item.name) or (0, None, 0)
    return ip[0], ip[2]


def item_mtime(item: Path) -> float:
    f = item_file(item, SCORE_FILE)
    return f.stat().st_mtime if f.exists() else 0.0


def work_mark(item: Path) -> str:
    """'*' when the item has work pending (choices, changes not built,
    not analysed), else ' '."""
    try:
        st_ = item_status(load_item(item))
    except (OSError, yaml.YAMLError):
        return "*"
    return " " if st_ in ("built", "ready to build") else "*"
