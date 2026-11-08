# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""The menu, main and the sandbox check."""
from __future__ import annotations

import argparse
import os
import shlex
import sys
import time
from pathlib import Path

import yaml

from . import VERSION, cli_items
from .cli_bars import cmd_bars
from .cli_common import _lib_or_die, cmd_set
from .cli_items import (
    cmd_analyse, cmd_contract, cmd_expand, cmd_list, cmd_meta, cmd_new, cmd_proof, cmd_reid,
    cmd_pages, cmd_plan, cmd_rename, cmd_repage, cmd_show, item_matches, list_page_size,
)
from .cli_parts import ambitus_menu, ask_part, cmd_groups, cmd_parts
from .config import LAYOUT_DEFAULTS, PAGE_HEADER_SP, PAPER
from .console import Abort, BOLD, RST, _die, _warn, ask
from .library import (
    PAPER_NEXT, _id_parts, find_item, id_order, inbox_pdfs, item_dirs, item_id, item_line,
    item_mtime, item_status, library_root, load_item, work_mark,
)


def item_menu(item: Path) -> None:
    """Menu for one item (DESIGN.md §6.2 sketch). Letters act at once."""
    iid = item_id(item)
    while True:
        if not item.is_dir():                 # renamed (m, rename): find it by its id
            try:
                item = find_item(item.parent, iid)
            except ValueError:
                return
        data = load_item(item)
        print(f"\n {BOLD}{item_line(item, data)}{RST}")
        st_ = item_status(data)
        print(f"  status: {st_}" + (f" — {', '.join(data['pending'])}" if data.get("pending") else ""))
        print("  edit (saved, not built):  m title/composer  t part names  g groups  "
              "n bar numbers and marks")
        print("                            e expand  c contract  p pages  a paper  k ambitus"
              "  s set")
        print("  v review   y analyse again   r build (r Trombones, r 2-4: only those)")
        print("  f fit (paper, staff size, page turns: f Trombones)   "
              "l pages (see and move page turns: l Trombones)")
        print("  x repage (page turns while resting; x Trombones)   b back")
        try:
            raw = ask(">", "b").strip()
        except Abort:
            return
        k, _, rest = raw.partition(" ")             # r Trombones: a key and its words
        k = k.lower()
        ns = argparse.Namespace(id=data["id"], build=False)
        try:
            if k == "b":
                return
            if k in ("e", "c", "p"):
                part = ask_part(data)
                if k == "e":
                    cmd_expand(argparse.Namespace(id=data["id"], build=False, part=part))
                elif k == "c":
                    cmd_contract(argparse.Namespace(id=data["id"], build=False, part=part))
                else:
                    v = ask("pages (auto or 1-99)", "auto")
                    pre = f"{part}:" if part else ""
                    cmd_set(argparse.Namespace(id=data["id"], pairs=[f"{pre}pages={v}"],
                                               build=False))
            elif k == "k":
                ambitus_menu(data)
            elif k == "a":
                cur = (data.get("layout") or {}).get("paper", LAYOUT_DEFAULTS["paper"])
                new = PAPER_NEXT.get(cur, "letter")
                cmd_set(argparse.Namespace(id=data["id"], pairs=[f"paper={new}"], build=False))
            elif k == "s":
                v = ask("key=value (e.g. gap=11 title=\"…\")", "")
                if v:
                    cmd_set(argparse.Namespace(id=data["id"], pairs=shlex.split(v), build=False))
            elif k == "n":
                cmd_bars(ns)
            elif k == "t":
                cmd_parts(ns)
            elif k == "g":
                cmd_groups(ns)
            elif k == "m":
                cmd_meta(ns)
            elif k == "y":
                cmd_analyse(ns)
            elif k == "r":
                cli_items.cmd_rebuild(argparse.Namespace(id=data["id"], build=False, parts=rest.split(),
                                               jobs=None))
            elif k == "x":
                cmd_repage(argparse.Namespace(id=data["id"], parts=rest.split()))
            elif k == "f":
                cmd_plan(plan_args([str(data["id"]), *rest.split()]))
            elif k == "l":
                part = rest.strip() or ask_part(data)
                if part:
                    cmd_pages(argparse.Namespace(id=data["id"], part=part, move=[], clear=False, dry_run=False))
                    mv = ask("move (PAGE=N, e.g. 26=1; Enter = no)", "").strip()
                    if mv:
                        cmd_pages(argparse.Namespace(id=data["id"], part=part, move=[mv], clear=False,
                                                     dry_run=False))
            elif k == "v":
                cmd_show(ns)
        except SystemExit:            # _die inside a command: stay in the menu
            pass
        except Abort:
            pass


RECENT_KEYS = "ABCDE"     # menu: the five items changed last
RECENT_MIN_ITEMS = 9      # the recent block shows from this many items on


def menu_key(item: Path, year: int) -> str:
    """menu_key -> the item's stable menu number: its serial for this
    year ('12' = 2026-10-0012, as every command takes it), year-serial for
    another year ('2025-14')."""
    ip = _id_parts(item.name)
    if not ip:
        return item.name
    return str(ip[2]) if ip[0] == year else f"{ip[0]}-{ip[2]}"


def cmd_menu(a: argparse.Namespace) -> int:
    """No command: the library, newest first, each item under its stable
    serial number; from RECENT_MIN_ITEMS items on, the five changed last
    first as A-E (operator request 2026-10-25: numbers for muscle memory, letters for
    the piece just worked on). /words filters both, + / - pages, * marks
    work pending, n new from inbox."""
    share, lib = _lib_or_die()
    words, page = "", 0
    size = list_page_size()
    year = time.localtime().tm_year

    def line(key: str, d: Path) -> str:
        try:
            return f"  {work_mark(d)}{key:>7}  {item_line(d, load_item(d))}"
        except (OSError, yaml.YAMLError):
            return f"  *{key:>7}  {d.name} · (no score.yaml)"

    while True:
        allit = sorted(item_dirs(lib), key=id_order, reverse=True)
        items = [d for d in allit if not words or item_matches(d, words)]
        recent = sorted(items, key=item_mtime, reverse=True)[:len(RECENT_KEYS)] \
            if len(allit) >= RECENT_MIN_ITEMS else []
        pages = max(1, -(-len(items) // size))
        page = min(page, pages - 1)
        waiting = len(inbox_pdfs(share))
        print(f"\n{BOLD}partitor {VERSION}{RST}  ({lib})"
              + (f"  filter: {words}  ({len(items)} of {len(allit)})" if words else ""))
        if not items:
            print("  (no item matches)" if words else "  (library empty)")
        if recent:
            print("  recent:")
            for ltr, d in zip(RECENT_KEYS, recent):
                print(line(ltr, d))
            print("  all (newest first):")
        for d in items[page * size:(page + 1) * size]:
            print(line(menu_key(d, year), d))
        nav = []
        if pages > 1:
            nav.append(f"page {page + 1}/{pages}: + next  - back")
        nav.append("/words filter" + ("  / clears" if words else ""))
        print(f"  n  new from inbox ({waiting} waiting)   {'   '.join(nav)}   q quit"
              + ("   * = work pending" if any(work_mark(d) == "*" for d in items[:size]) else ""))
        try:
            k = ask(">", "q").strip()
        except Abort:
            return 0
        if k.startswith("/"):
            words, page = k[1:].strip(), 0
            continue
        if k == "+":
            page = min(page + 1, pages - 1)
            continue
        if k == "-":
            page = max(0, page - 1)
            continue
        if k.lower() == "q":
            return 0
        if k.lower() == "n":
            try:
                cmd_new(argparse.Namespace(n=None))
            except SystemExit:
                pass
            continue
        if len(k) == 1 and k.upper() in RECENT_KEYS and recent:
            i_ = RECENT_KEYS.index(k.upper())
            if i_ < len(recent):
                item_menu(recent[i_])
            continue
        if k:
            try:
                item_menu(find_item(lib, k))      # 12, 2025-14, 2026-10-0012
            except ValueError:
                _warn(f"menu:  no item {k}")


def sandbox_check(library: bool = False) -> int:
    """sandbox_check -> 0 when this process runs as the sandbox expects
    (DESIGN.md §8): not root, no network sockets, read-only system, /root
    hidden, working folder writable; with library: inbox/ and library/ of the
    library folder writable. One line per item; used by the installer."""
    import socket
    import tempfile
    import pwd
    res = []
    user = pwd.getpwuid(os.geteuid()).pw_name
    res.append(("user", user, os.geteuid() != 0))
    try:
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).close()
        res.append(("network", "open", False))
    except OSError:
        res.append(("network", "blocked", True))
    try:
        tempfile.TemporaryFile(dir="/usr").close()
        res.append(("system", "writable", False))
    except OSError:
        res.append(("system", "read-only", True))
    try:
        hidden = not os.listdir("/root")
    except OSError:
        hidden = True
    res.append(("/root", "hidden" if hidden else "visible", hidden))
    try:
        tempfile.TemporaryFile(dir=".").close()
        res.append(("work", "writable", True))
    except OSError:
        res.append(("work", "not writable", False))
    if library:
        root = library_root()
        for sub_ in ("inbox", "library"):
            d = root / sub_
            try:
                tempfile.TemporaryFile(dir=d).close()
                res.append((f"library {sub_}", f"writable ({d})", True))
            except OSError as e:
                res.append((f"library {sub_}", f"not writable ({d}: {e.strerror})", False))
    for name, val, good in res:
        print(f"{'ok  ' if good else 'FAIL'} {name}: {val}")
    return 0 if all(g for _, _, g in res) else 1


def plan_args(argv: list[str]) -> argparse.Namespace:
    """plan_args -> the arguments of `partitor plan`. The command has its own parser and is
    listed in the main --help by a stub parser that is never run."""
    pn = argparse.ArgumentParser(
        prog="partitor plan",
        description="Options of a part: paper, staff size, page turns and fold-outs, estimated "
                    "from the saved lines (read-only). With a part and a number: set that option "
                    "(saved, not built; then partitor rebuild).")
    pn.add_argument("id", help="12 or 2026-10-0012")
    pn.add_argument("words", nargs="*", metavar="PART [N]",
                    help="a part or group, then the option number to set; default: groups "
                         "and parts with a bad turn")
    pn.add_argument("--group", action="append", default=[], metavar="NAME=PARTS",
                    help="try a group the item does not have, e.g. AltTen=Alto,Tenor (part names "
                         "or numbers): built in a temporary copy and shown; repeat for more groups")
    pn.add_argument("--all", action="store_true",
                    help="show every option (default: the option as built and the best of each paper)")
    return pn.parse_args(argv)


def main() -> int:
    if "--sandbox-check" in sys.argv[1:2]:
        return sandbox_check(library="--library" in sys.argv[2:3])
    if os.geteuid() == 0 and os.environ.get("PARTITOR_ALLOW_ROOT") != "1" \
            and sys.argv[1:2] not in (["--version"], ["-h"], ["--help"]):
        _die("the engine does not run as root (it parses PDFs from the internet)",
             "Use /usr/local/sbin/partitor: it runs the engine as user partitor "
             "in a sandbox.")
    if sys.argv[1:2] == ["plan"]:
        return cmd_plan(plan_args(sys.argv[2:]))
    p = argparse.ArgumentParser(prog="partitor", description="Split a score PDF into parts.")
    p.add_argument("--version", action="version", version=f"partitor {VERSION}")
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("menu", help="recent items and new from inbox (default)")
    nw = sub.add_parser("new", help="wizard for an inbox PDF")
    nw.add_argument("n", nargs="?", help="inbox number (default: ask)")
    nw.add_argument("--jobs", help="worker processes of the analysis and the build: a number "
                    "or auto (default: PARTITOR_JOBS, else auto)")
    ls_ = sub.add_parser("list", help="all library items, or those matching words")
    ls_.add_argument("words", nargs="*", help="e.g. Schein (composer, title, part, id)")
    sub.add_parser("show").add_argument("id", help="12 or 2026-10-0012")
    sub.add_parser("plan", help="choose paper, staff size and fold-outs of a part by its page turns "
                   "(read-only until you pick an option; partitor plan --help)")
    rb = sub.add_parser("rebuild", help="build; with parts or groups: only those "
                        "(the other part files stay)")
    rb.add_argument("id", help="12 or 2026-10-0012")
    rb.add_argument("parts", nargs="*", metavar="PART",
                    help="numbers (3, 2-4), names (Trombones, Bass Trombone) or all; "
                         "default: every part")
    rb.add_argument("--jobs", help="worker processes: a number or auto "
                    "(default: PARTITOR_JOBS, else auto)")
    pg = sub.add_parser("pages", help="the pages of a built part and the turn after each; "
                        "--move PAGE=N moves a system to the next page")
    pg.add_argument("id", help="12 or 2026-10-0012")
    pg.add_argument("part", help="one part or group, name or number")
    pg.add_argument("--move", action="append", metavar="PAGE=N",
                    help="move the last N systems of PAGE to the next page (N negative: bring the "
                         "first systems of the next page up); the part is paged again")
    pg.add_argument("--clear", action="store_true", help="drop the manual page breaks of the part")
    pg.add_argument("--dry-run", action="store_true", help="show the pages after --move, save nothing")
    rp = sub.add_parser("repage", help="new page breaks from the saved lines: turns while "
                        "resting, manual breaks (no analysis, no build)")
    rp.add_argument("id", help="12 or 2026-10-0012")
    rp.add_argument("parts", nargs="*", metavar="PART",
                    help="numbers, names or all; default: every built part")
    sub.add_parser("proof", help="draw proof.pdf again (names, ambitus, bar numbers, letters)"
                   ).add_argument("id", help="12 or 2026-10-0012")
    for name in ("expand", "contract", "bars", "parts", "groups", "meta"):
        sp_ = sub.add_parser(name, help="edit; saved, not built (--build: build too)")
        sp_.add_argument("id", help="12 or 2026-10-0012")
        if name in ("expand", "contract"):
            sp_.add_argument("part", nargs="?", help="one part or group only (default: all)")
        sp_.add_argument("--build", action="store_true", help="build after the edit")
    sub.add_parser("reid", help="old YYYY-NNN item: new id YYYY-MM-NNNN (renames files)"
                   ).add_argument("id")
    sub.add_parser("rename", help="folder name follows the title and composer"
                   ).add_argument("id")
    an = sub.add_parser("analyse", help="analyse the source again (proof, allocation)")
    an.add_argument("id", nargs="?", help="12 or 2026-10-0012 (or --all)")
    an.add_argument("--yes", action="store_true", help="ask nothing; open choices stay for rebuild")
    an.add_argument("--all", action="store_true", help="every library item, as --yes")
    # not in --help yet: that text is part of the G0 golden (docs: DESIGN.md, operator-flow.html)
    an.add_argument("--join", action="append", default=[], metavar="pP:N", help=argparse.SUPPRESS)
    an.add_argument("--unjoin", action="append", default=[], metavar="pP:N", help=argparse.SUPPRESS)
    st = sub.add_parser("set", help="change settings; saved, not built (--build: build too)")
    st.add_argument("id")
    st.add_argument("pairs", nargs="+", metavar="key=value")
    st.add_argument("--build", action="store_true", help="build after the change")
    pc = sub.add_parser("pieces")
    pc.add_argument("pdf")
    d = sub.add_parser("detect")
    d.add_argument("pdf")
    d.add_argument("--pages")
    d.add_argument("--parts", default="")
    d.add_argument("--title", default="")
    d.add_argument("--subtitle", default="")
    d.add_argument("--composer", default="")
    d.add_argument("--dpi", type=int, default=400)
    d.add_argument("--page-header-sp", dest="page_header_sp", type=float,
                   default=PAGE_HEADER_SP)
    d.add_argument("--out")
    d.add_argument("--force", action="store_true")
    d.add_argument("--jobs", help="worker processes for the page analysis: a number or auto "
                   "(default: PARTITOR_JOBS, else auto)")
    b = sub.add_parser("build")
    b.add_argument("pdf")
    b.add_argument("--pages")
    b.add_argument("--out")
    b.add_argument("--paper", choices=sorted(PAPER))
    b.add_argument("--scale", type=float)
    b.add_argument("--gap", type=float)
    b.add_argument("--min-gap", dest="gap_min", type=float)
    b.add_argument("--clearance", type=float)
    b.add_argument("--page-count", dest="page_count", type=int)
    b.add_argument("--min-staff-mm", dest="min_staff_mm", type=float)
    b.add_argument("--ink", choices=["normal", "darker"])
    b.add_argument("--bar-numbers", dest="bar_numbers", choices=["start", "none"])
    b.add_argument("--bar-raise", dest="bar_raise", type=float)
    b.add_argument("--bar-size", dest="bar_size", type=float)
    b.add_argument("--margin-top", dest="margin_top", type=float)
    b.add_argument("--margin-bottom", dest="margin_bottom", type=float)
    b.add_argument("--margin-side", dest="margin_side", type=float)
    b.add_argument("--gutter", type=float)
    b.add_argument("--duplex", choices=["auto", "on", "off"])
    b.add_argument("--large", choices=["on", "off"])
    b.add_argument("--reflow", choices=["on", "off"])
    b.add_argument("--max-staff-mm", dest="max_staff_mm", type=float)
    b.add_argument("--title-page", dest="title_page", choices=["auto", "off"])
    b.add_argument("--rests", choices=["compress", "keep"])
    b.add_argument("--jobs", help="worker processes: a number or auto (default: PARTITOR_JOBS, else auto)")
    b.add_argument("--only", nargs="+", metavar="NAME", help="build these parts or groups only")
    a = p.parse_args()
    if a.cmd in ("pieces", "detect", "build"):
        from . import build        # the image libraries load only for these commands
        return {"pieces": build.cmd_pieces, "detect": build.cmd_detect,
                "build": build.cmd_build}[a.cmd](a)
    cmds = {"menu": cmd_menu, "new": cmd_new, "list": cmd_list, "show": cmd_show,
            "set": cmd_set, "expand": cmd_expand, "contract": cmd_contract,
            "rebuild": cli_items.cmd_rebuild, "pages": cmd_pages, "repage": cmd_repage, "bars": cmd_bars, "parts": cmd_parts,
            "proof": cmd_proof,
            "groups": cmd_groups, "meta": cmd_meta, "analyse": cmd_analyse,
            "reid": cmd_reid, "rename": cmd_rename}
    return cmds[a.cmd or "menu"](a)
