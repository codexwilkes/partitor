#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""Move top-level symbols from the engine script to modules of lib/partitor, byte for byte.

Temporary tool of the modular split (docs/DESIGN.md §12). It is removed in step M8.

Usage:
  move-symbols.py --modules console,config [options]              dry run: print the plan
  move-symbols.py --modules console,config --apply [options]      write modules and script
  move-symbols.py --modules console,config --check --pristine F   prove the result (below)
options:
  --root DIR       repo root (default: the folder above tools/)
  --script FILE    engine script (default: lib/partitor-engine under the root)
  --map FILE       module-map.json; its "symbols" table lists the names of each module
  --config FILE    JSON: {"docs": {module: one-line docstring}, "attr": [names],
                   "edits": [{"step": module, "file": "script" or module, "old": text,
                   "new": text, "count": n (default 1)}]}
  --pristine FILE  the engine script before the first move (for --check)
  --final          also apply the edits of step "final" (text of the script that belongs to
                   the release, not to one module); give it to the last --apply and --check

What it does, per module (in the order given):
  1. Finds the top-level statement of every name in the map. Refuses a name that is
     missing, bound twice, bound inside try/if/for/with, or bound by a statement that
     also binds a name of another module.
  2. Moves each statement with its decorators and the comment block directly above
     it, text unchanged, in the original order, into lib/partitor/<module>.py.
  3. Writes the module header (SPDX, copyright, docstring, `from __future__ import
     annotations`) and only the imports that the moved code uses. A name of a lower
     module comes as `from .x import NAME`; a name that tests patch (tests/patchable.txt)
     or a name in "attr" comes as `from . import x` and must be used as `x.NAME` (rule R1).
  4. Removes the statements from the script and adds one shim import per module after
     `from partitor import VERSION` (rule R5), except the R1 names.
  5. Applies the listed edits of this step ("forced edits": the only text that differs
     from the original), each exactly `count` times.
  6. Refuses when a moved statement reads a name that stays in the script, or that
     belongs to a module of the same or a higher level (tools/modules.txt), or when a
     name stays undefined in the module or in the script after the edits.
--apply refuses a module whose file exists already.
--check rebuilds the expected result from --pristine and compares it with the files on
disk: module text equals the original text plus the listed edits; the script equals the
original minus the moved statements plus shims and listed edits. Exit 1 on a difference.

Exit codes: 0 ok; 1 refusal or difference; 2 usage or input error.
"""
import argparse
import ast
import builtins
import difflib
import json
import os
import re
import symtable
import sys

PKG = "partitor"
ANCHOR = "from partitor import VERSION  # noqa: E402"
SHIM_MARK = "# Shim imports of moved names (plan R5). Step M8 removes them."
SPDX = ["# SPDX-License-Identifier: AGPL-3.0-or-later",
        "# Copyright (C) 2026 Nathan Wilkes and partitor contributors"]
MOVABLE = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Assign, ast.AnnAssign)
MODULE_GLOBALS = {"__file__", "__name__", "__doc__"}
WIDTH = 96


class Refusal(Exception):
    pass


# ── source analysis ─────────────────────────────────────────────────────────

def bound_names(node):
    """Names that a top-level statement binds in module scope."""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return [node.name]
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        return [(a.asname or a.name).split(".")[0] for a in node.names]
    out, stack = [], [node]
    while stack:
        for c in ast.iter_child_nodes(stack.pop()):
            if isinstance(c, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                out.append(c.name)
                continue
            if isinstance(c, ast.Lambda):
                continue
            if isinstance(c, ast.Name) and isinstance(c.ctx, (ast.Store, ast.Del)):
                out.append(c.id)
            if isinstance(c, (ast.Import, ast.ImportFrom)):
                out += bound_names(c)
            stack.append(c)
    return out


class Source:
    """A parsed python file: its lines and its top-level statements."""

    def __init__(self, text, name="<src>"):
        self.text = text
        self.lines = text.split("\n")
        self.tree = ast.parse(text, filename=name)
        self.stmts = []
        for idx, n in enumerate(self.tree.body):
            start = min([n.lineno] + [d.lineno for d in getattr(n, "decorator_list", [])])
            top = start
            while top > 1 and self.lines[top - 2].lstrip().startswith("#"):
                top -= 1                                  # comment block directly above
            self.stmts.append({"idx": idx, "node": n, "start": start, "top": top,
                               "end": n.end_lineno, "bound": bound_names(n)})

    def block(self, st):
        return "\n".join(self.lines[st["top"] - 1:st["end"]])

    def reads(self, st):
        """(names read from module scope, names assigned through `global`) of a statement."""
        seg = "\n".join(self.lines[st["start"] - 1:st["end"]])
        table = symtable.symtable(seg, "<seg>", "exec")
        own = set(st["bound"])
        reads, writes = set(), set()

        def walk(tab, top):
            for s in tab.get_symbols():
                nm = s.get_name()
                if top:
                    if s.is_referenced() and not s.is_assigned() and not s.is_imported() \
                            and nm not in own:
                        reads.add(nm)
                    continue
                glob = s.is_global() and not s.is_parameter() and not s.is_local()
                if glob or s.is_declared_global():
                    if s.is_referenced() and nm not in own:
                        reads.add(nm)
                    if s.is_assigned() and s.is_declared_global():
                        writes.add(nm)
            for c in tab.get_children():
                walk(c, False)

        walk(table, True)
        return {n for n in reads if n not in dir(builtins)} - MODULE_GLOBALS, writes

    def toplevel_names(self):
        return {b for st in self.stmts for b in st["bound"]}

    def defined_names(self):
        """Top-level names that are not bound by an import statement."""
        return {b for st in self.stmts
                if not isinstance(st["node"], (ast.Import, ast.ImportFrom)) for b in st["bound"]}

    def imports(self):
        """bound name -> (statement node) for every top-level import statement."""
        return {b: st["node"] for st in self.stmts
                if isinstance(st["node"], (ast.Import, ast.ImportFrom)) for b in st["bound"]}


def undefined_names(src):
    """[(statement name, name, kind, lines)] for names that nothing in `src` defines, and
    for `global NAME` of a name that the module only imports (it would write a new variable)."""
    have = src.toplevel_names()
    own = src.defined_names()
    bad = []
    for st in src.stmts:
        reads, writes = src.reads(st)
        label = st["bound"][0] if st["bound"] else f"line {st['start']}"
        for n, kind in ([(n, "read") for n in sorted(reads - have)]
                        + [(n, "global write") for n in sorted(writes - have)]
                        + [(n, "global write of an imported name")
                           for n in sorted(writes & (have - own))]):
            hit = [str(i) for i in range(st["start"], st["end"] + 1)
                   if re.search(r"\b" + re.escape(n) + r"\b", src.lines[i - 1])]
            bad.append((label, n, kind, ",".join(hit)))
    return bad


# ── inputs ──────────────────────────────────────────────────────────────────

def read_table(path):
    table = {}
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            f = raw.split("#", 1)[0].split()
            if len(f) >= 3 and f[0].isdigit():
                table[f[1]] = int(f[0])
    return table


def read_names(path):
    if not os.path.isfile(path):
        return []
    with open(path, encoding="utf-8") as fh:
        return [ln.split("#", 1)[0].strip() for ln in fh if ln.split("#", 1)[0].strip()]


def read_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


# ── the move ────────────────────────────────────────────────────────────────

def pick_statements(src, module, names):
    """The statements to move: ordered list of statement dicts."""
    chosen = {}
    for name in names:
        hits = [st for st in src.stmts if name in st["bound"]]
        if not hits:
            raise Refusal(f"{module}: '{name}' is not a top-level name of the script")
        if len(hits) > 1:
            lines = ", ".join(str(h["start"]) for h in hits)
            raise Refusal(f"{module}: '{name}' is bound {len(hits)} times (lines {lines})")
        st = hits[0]
        if not isinstance(st["node"], MOVABLE):
            raise Refusal(f"{module}: '{name}' is bound by a {type(st['node']).__name__} "
                          f"statement (line {st['start']}), not a plain def, class or assignment")
        chosen[st["idx"]] = st
    out = sorted(chosen.values(), key=lambda s: s["start"])
    for st in out:
        extra = [b for b in st["bound"] if b not in names]
        if extra:
            raise Refusal(f"{module}: the statement at line {st['start']} also binds "
                          f"{', '.join(extra)}, which is not in the list of {module}")
    return out


def resolve_dependencies(src, package, module, level, levels, moving):
    """Classify every name that the moving statements read. Refuse what cannot move."""
    own = {b for st in moving for b in st["bound"]}
    headers = src.imports()
    owner = {}
    for mod, psrc in package.items():
        for name in psrc.defined_names():
            owner.setdefault(name, mod)
    from_header, from_pkg, from_init = set(), {}, set()
    for st in moving:
        reads, writes = src.reads(st)
        label = st["bound"][0]
        for n in sorted(reads | writes):
            if n in own:
                continue
            node = headers.get(n)
            if isinstance(node, ast.ImportFrom) and node.module == PKG and n not in owner:
                if levels.get(n, -1) >= level:
                    raise Refusal(f"{module}: {label} uses module {n} (level {levels[n]}), "
                                  f"not below level {level}: upward dependency")
                from_init.add(n)                      # `from partitor import n` in the script
            elif n in headers and n not in owner:
                from_header.add(n)
            elif n in owner:
                m = owner[n]
                if levels.get(m, 99) >= level:
                    raise Refusal(f"{module}: {label} uses {n} of {m} (level {levels.get(m)}), "
                                  f"not below level {level}: upward dependency")
                from_pkg.setdefault(m, set()).add(n)
            elif n in src.toplevel_names():
                raise Refusal(f"{module}: {label} uses {n}, which stays in the script "
                              f"(not moved yet): move it first or change the order")
            else:
                raise Refusal(f"{module}: {label} uses {n}, which nothing defines")
    return from_header, from_pkg, from_init


def header_lines(src, used):
    """Import lines for the header names in `used`, in the order of the script."""
    std, third = [], []
    seen = set()
    for st in src.stmts:
        node = st["node"]
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        if isinstance(node, ast.ImportFrom) and node.module == PKG:
            continue
        keep = [a for a in node.names if (a.asname or a.name).split(".")[0] in used]
        if not keep:
            continue
        for a in keep:
            seen.add((a.asname or a.name).split(".")[0])
        spec = ", ".join(a.name + (f" as {a.asname}" if a.asname else "") for a in keep)
        line = f"from {node.module} import {spec}" if isinstance(node, ast.ImportFrom) \
            else f"import {spec}"
        top = (node.module if isinstance(node, ast.ImportFrom) else node.names[0].name)
        (std if top.split(".")[0] in sys.stdlib_module_names else third).append(line)
    missing = used - seen
    if missing:
        raise Refusal(f"no import in the script for: {', '.join(sorted(missing))}")
    return std, third


def wrap_import(prefix, names, tail=""):
    one = f"{prefix} {', '.join(names)}{tail}"
    if len(one) <= WIDTH:
        return [one]
    out = [f"{prefix} ({tail}"] if tail else [f"{prefix} ("]
    line = "   "
    for n in names:
        piece = f" {n},"
        if len(line) + len(piece) > WIDTH:
            out.append(line)
            line = "   "
        line += piece
    out.append(line)
    out.append(")")
    return out


def join_blocks(src, moving):
    """Moved text: original blocks. Neighbours keep their original blank lines; others get
    two blank lines around a def or class, one between plain statements."""
    parts, prev = [], None
    for st in moving:
        if prev is not None:
            between = src.lines[prev["end"]:st["top"] - 1]
            if st["idx"] == prev["idx"] + 1 and all(not ln.strip() for ln in between):
                gap = len(between)
            elif isinstance(st["node"], (ast.FunctionDef, ast.ClassDef)) or isinstance(
                    prev["node"], (ast.FunctionDef, ast.ClassDef)):
                gap = 2
            else:
                gap = 1
            parts.append("\n" * (gap + 1))
        parts.append(src.block(st))
        prev = st
    return "".join(parts)


def module_text(src, module, doc, moving, from_header, from_pkg, from_init, r1):
    std, third = header_lines(src, from_header)
    pkg_lines, attr_mods = [], []
    for m in sorted(from_pkg):
        plain = sorted(n for n in from_pkg[m] if n not in r1)
        if plain:
            pkg_lines += wrap_import(f"from .{m} import", plain)
        if any(n in r1 for n in from_pkg[m]):
            attr_mods.append(m)
    attr_mods = sorted(set(attr_mods) | from_init)
    if attr_mods:                                  # `from . import x` sorts before `from .x import`
        pkg_lines.insert(0, f"from . import {', '.join(attr_mods)}")
    text = "\n".join(SPDX + [f'"""{doc}"""', "from __future__ import annotations"]) + "\n"
    for group in (std, third, pkg_lines):
        if group:
            text += "\n" + "\n".join(group) + "\n"
    return text + "\n\n" + join_blocks(src, moving) + "\n"


def remove_blocks(src, moving):
    """Script lines without the moved blocks. At each seam the blank lines are the larger
    of the two original gaps, two at most."""
    kill = set()
    for st in moving:
        kill.update(range(st["top"], st["end"] + 1))
    out, i, n = [], 1, len(src.lines)
    while i <= n:
        if i not in kill:
            out.append(src.lines[i - 1])
            i += 1
            continue
        before = 0
        while out and not out[-1].strip():
            out.pop()
            before += 1
        after = 0
        while i <= n and (i in kill or not src.lines[i - 1].strip()):
            after = after + 1 if i not in kill else 0
            i += 1
        if out and i <= n:
            out += [""] * min(2, max(before, after))
    return out


def shim_stanza(module, names):
    return wrap_import(f"from {PKG}.{module} import", sorted(names), "  # noqa: E402,F401")


def add_shim(lines, module, names):
    if not names:
        return lines
    text_has = SHIM_MARK in lines
    try:
        at = lines.index(ANCHOR) + 1
    except ValueError:
        raise Refusal(f"script: anchor line not found: {ANCHOR}")
    stanza = shim_stanza(module, names)
    if text_has:
        at = lines.index(SHIM_MARK) + 1
        while at < len(lines) and (lines[at].startswith("from partitor.") or lines[at].startswith("   ")
                                   or lines[at] == ")"):
            at += 1
        return lines[:at] + stanza + lines[at:]
    return lines[:at] + ["", SHIM_MARK] + stanza + lines[at:]


def apply_edits(text, edits, where):
    for e in edits:
        want = e.get("count", 1)
        got = text.count(e["old"])
        if got != want:
            raise Refusal(f"edit in {where}: expected {want} place(s) of {e['old']!r}, found {got}")
        text = text.replace(e["old"], e["new"])
    return text


def simulate(root, script_text, modules, levels, symbols, cfg, patch, existing, final=False):
    """Apply the moves in memory. Returns (script text, {module: text}, report)."""
    cur = script_text
    files = dict(existing)                      # module -> text, already in the package
    report = {}
    r1 = set(patch) | set(cfg.get("attr", []))
    for module in modules:
        if module not in levels:
            raise Refusal(f"{module}: not listed in tools/modules.txt")
        if module in files:
            raise Refusal(f"{module}: lib/{PKG}/{module}.py exists already; "
                          f"the symbols are moved (second --apply)")
        src = Source(cur, "script")
        package = {m: Source(t, m) for m, t in files.items()}
        names = [n for n in symbols[module] if n != "VERSION"]
        moving = pick_statements(src, module, set(names))
        from_header, from_pkg, from_init = resolve_dependencies(
            src, package, module, levels[module], levels, moving)
        doc = cfg.get("docs", {}).get(module, f"The {module} module of the engine "
                                      f"(docs/DESIGN.md §12).")
        mtext = module_text(src, module, doc, moving, from_header, from_pkg, from_init, r1)
        stay = remove_blocks(src, moving)
        shim = [n for n in names if n not in r1]
        stay = add_shim(stay, module, shim)
        stext = "\n".join(stay).rstrip("\n") + "\n"
        steps = [e for e in cfg.get("edits", []) if e.get("step") == module]
        mtext = apply_edits(mtext, [e for e in steps if e["file"] == module], module)
        stext = apply_edits(stext, [e for e in steps if e["file"] == "script"], "script")
        cur, files[module] = stext, mtext
        report[module] = {"statements": len(moving), "names": len(names),
                          "def_lines": sum(s["end"] - s["start"] + 1 for s in moving
                                           if isinstance(s["node"], (ast.FunctionDef, ast.ClassDef))),
                          "from_header": sorted(from_header),
                          "from_pkg": {m: sorted(v) for m, v in from_pkg.items()},
                          "from_init": sorted(from_init),
                          "shim": len(shim), "r1": sorted(set(names) & r1),
                          "edits": len(steps)}
    if final:
        cur = apply_edits(cur, [e for e in cfg.get("edits", []) if e.get("step") == "final"],
                          "script (final)")
    problems = []
    for label, text in [("script", cur)] + sorted(files.items()):
        if label in existing and label != "script":
            continue
        for st, name, kind, where in undefined_names(Source(text, label)):
            problems.append(f"{label}: {st}: {kind} {name} (line {where})")
    return cur, {m: files[m] for m in modules}, report, problems


# ── commands ────────────────────────────────────────────────────────────────

def load_package(pkg_dir, skip=()):
    out = {}
    if os.path.isdir(pkg_dir):
        for fn in sorted(os.listdir(pkg_dir)):
            m = fn[:-3]
            if fn.endswith(".py") and m not in ("__init__", "__main__") and m not in skip:
                with open(os.path.join(pkg_dir, fn), encoding="utf-8") as fh:
                    out[m] = fh.read()
    return out


def show_report(modules, report, problems):
    for m in modules:
        r = report[m]
        print(f"{m}: {r['names']} names in {r['statements']} statements, "
              f"{r['def_lines']} definition lines, {r['shim']} shim names, "
              f"{r['edits']} listed edit(s)")
        print(f"   imports from the script header: {', '.join(r['from_header']) or '-'}")
        if r["from_init"]:
            print(f"   uses modules through `from . import`: {', '.join(r['from_init'])}")
        for dep, names in r["from_pkg"].items():
            print(f"   uses {dep}: {', '.join(names)}")
        if r["r1"]:
            print(f"   R1 names (no shim, use module.NAME): {', '.join(r['r1'])}")
    for p in problems:
        print(f"UNRESOLVED {p}")


def diff_text(a, b, an, bn):
    return "".join(list(difflib.unified_diff(a.splitlines(True), b.splitlines(True),
                                             an, bn, n=1))[:60])


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--modules", required=True)
    ap.add_argument("--root", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    ap.add_argument("--script")
    ap.add_argument("--map")
    ap.add_argument("--symbols", help="comma list of names, for a single module")
    ap.add_argument("--config")
    ap.add_argument("--pristine")
    ap.add_argument("--final", action="store_true",
                    help="also apply the edits of step \"final\" (release text of the script)")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    root = os.path.abspath(a.root)
    script = a.script or os.path.join(root, "lib", "partitor-engine")
    pkg_dir = os.path.join(root, "lib", PKG)
    modules = [m for m in a.modules.split(",") if m]
    try:
        levels = read_table(os.path.join(root, "tools", "modules.txt"))
        patch = read_names(os.path.join(root, "tests", "patchable.txt"))
        cfg = read_json(a.config) if a.config else {}
        if a.symbols:
            if len(modules) != 1:
                raise ValueError("--symbols needs exactly one module")
            symbols = {modules[0]: [n for n in a.symbols.split(",") if n]}
        else:
            symbols = read_json(a.map or os.path.join(root, "tools", "module-map.json"))["symbols"]
        for m in modules:
            if m not in symbols:
                raise ValueError(f"{m}: no symbol list in the map")
    except (OSError, ValueError, KeyError) as e:
        print(f"move-symbols: {e}", file=sys.stderr)
        return 2
    try:
        if a.check:
            if not a.pristine:
                print("move-symbols: --check needs --pristine", file=sys.stderr)
                return 2
            with open(a.pristine, encoding="utf-8") as fh:
                pristine = fh.read()
            exp_script, exp_files, report, problems = simulate(
                root, pristine, modules, levels, symbols, cfg, patch, {}, a.final)
            bad = [f"UNRESOLVED {p}" for p in problems]
            with open(script, encoding="utf-8") as fh:
                now = fh.read()
            if now != exp_script:
                bad.append("script differs from the expected result:\n"
                           + diff_text(exp_script, now, "expected", "script"))
            for m in modules:
                path = os.path.join(pkg_dir, m + ".py")
                have = open(path, encoding="utf-8").read() if os.path.isfile(path) else None
                if have != exp_files[m]:
                    bad.append(f"{m}: lib/{PKG}/{m}.py differs from the original text plus the "
                               f"listed edits:\n" + (diff_text(exp_files[m], have or "",
                                                               "expected", m + ".py")))
            show_report(modules, report, [])
            if bad:
                print("\n".join(bad))
                print("move-symbols: CHECK FAILED")
                return 1
            print(f"move-symbols: CHECK OK ({len(modules)} module(s): moved text equals the "
                  f"original plus the listed edits; script equals the original minus the moved "
                  f"statements plus shims and listed edits)")
            return 0
        with open(script, encoding="utf-8") as fh:
            cur = fh.read()
        existing = load_package(pkg_dir)
        new_script, new_files, report, problems = simulate(
            root, cur, modules, levels, symbols, cfg, patch, existing, a.final)
    except Refusal as e:
        print(f"move-symbols: REFUSED: {e}", file=sys.stderr)
        return 1
    show_report(modules, report, problems)
    if not a.apply:
        print("move-symbols: dry run, nothing written" +
              (f" ({len(problems)} unresolved name(s): fix with listed edits)" if problems else ""))
        return 1 if problems else 0
    if problems:
        print("move-symbols: REFUSED: unresolved names; add edits and run again", file=sys.stderr)
        return 1
    os.makedirs(pkg_dir, exist_ok=True)
    for m in modules:
        with open(os.path.join(pkg_dir, m + ".py"), "w", encoding="utf-8") as fh:
            fh.write(new_files[m])
    with open(script, "w", encoding="utf-8") as fh:
        fh.write(new_script)
    print(f"move-symbols: wrote {len(modules)} module(s) and the script")
    return 0


if __name__ == "__main__":
    sys.exit(main())
