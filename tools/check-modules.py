#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""Check the module structure of the partitor package (lib/partitor). Stdlib only.

Usage:
  check-modules.py [--static]        checks that need no third-party package (default)
  check-modules.py --import          --static, then import every module alone
  check-modules.py --affected MODULE modules that import MODULE (transitively) and the
                                     test files to run: theirs and those of MODULE itself
  option --root DIR                  repo root (default: the folder above tools/)

Input files:
  tools/modules.txt    one line per module: LEVEL MODULE TESTS [exempt]
                       TESTS = file names in tests/ (comma separated) or * (all tests);
                       exempt = no line limit. Lines starting with # are comments.
  tests/patchable.txt  names that tests replace with mock_attr (one per line)

Static checks (exit 1 on any finding, with a message that names file and line):
  1. Stale file: a lib/partitor/*.py file (not __init__ or __main__) that is not in
     modules.txt. A listed module that exists must parse. A listed test file must exist.
  2. Import levels: a module imports only modules of a strictly lower level. Every
     import statement counts, also inside a function. A cycle is reported.
  3. Header: SPDX line in the first 6 lines of every file; `from __future__ import
     annotations` in every module (not __init__ or __main__). __init__.py has no imports.
  4. `global NAME` only for a name that the same module assigns or defines at top level.
     A name that the module imports is not its own: write `owner.NAME = ...` instead.
  5. Patch registry: no module and not the script lib/partitor-engine imports a name of
     tests/patchable.txt with `from ... import NAME`. Use `module.NAME` (rule R1).
  6. Definition lines per module (top-level def and class spans) not above LIMIT,
     unless the module is exempt.
  7. Information only: size and fan-in (how many modules import it) per module.

--import needs the venv for modules that import third-party packages; each module is
imported in a fresh `python -I` process. It also checks that `import partitor` finds
the package under lib/ and not another installed package of the same name.

Exit codes: 0 ok; 1 findings; 2 usage or input error.
"""
import argparse
import ast
import os
import subprocess
import sys

LIMIT = 1100                       # definition lines per module (plan v2, section 8)
PKG = "partitor"
SPDX = "SPDX-License-Identifier: AGPL-3.0-or-later"
NO_FUTURE = ("__init__", "__main__")


class Findings:
    def __init__(self):
        self.items = []

    def add(self, where, msg):
        self.items.append(f"check-modules: FAIL {where}: {msg}")

    def __bool__(self):
        return bool(self.items)


def read_table(path):
    """modules.txt -> {name: (level, [tests] or ['*'], exempt)}, in file order."""
    table = {}
    with open(path, encoding="utf-8") as fh:
        for no, raw in enumerate(fh, 1):
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            f = line.split()
            if len(f) not in (3, 4) or not f[0].isdigit() or (len(f) == 4 and f[3] != "exempt"):
                raise ValueError(f"{path}:{no}: want 'LEVEL MODULE TESTS [exempt]': {raw.strip()}")
            if f[1] in table:
                raise ValueError(f"{path}:{no}: module listed twice: {f[1]}")
            table[f[1]] = (int(f[0]), f[2].split(","), len(f) == 4)
    return table


def read_names(path):
    with open(path, encoding="utf-8") as fh:
        return [ln.split("#", 1)[0].strip() for ln in fh if ln.split("#", 1)[0].strip()]


def parse(path):
    with open(path, encoding="utf-8") as fh:
        src = fh.read()
    return src, ast.parse(src, filename=path)


def imported_modules(tree, table):
    """[(lineno, module)] for imports of modules of the package (names in `table`).
    Unknown module names are returned too, with the marker None as module."""
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                parts = a.name.split(".")
                if parts[0] == PKG and len(parts) > 1:
                    out.append((n.lineno, parts[1]))
        elif isinstance(n, ast.ImportFrom):
            if n.level == 1 and n.module is None:                  # from . import x
                out += [(n.lineno, a.name) for a in n.names if a.name in table]
            elif n.level == 1:                                     # from .x import y
                out.append((n.lineno, n.module.split(".")[0]))
            elif n.level == 0 and n.module == PKG:                 # from partitor import x
                out += [(n.lineno, a.name) for a in n.names if a.name in table]
            elif n.level == 0 and n.module and n.module.split(".")[0] == PKG:
                out.append((n.lineno, n.module.split(".")[1]))     # from partitor.x import y
            elif n.level > 1:
                out.append((n.lineno, None))                       # leaves the package
    return out


def imported_names(tree):
    """[(lineno, name)] for every `from ... import name` (alias ignored)."""
    return [(n.lineno, a.name) for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)
            for a in n.names]


def own_top_level_names(tree):
    """Names that the module itself assigns or defines at top level (not imports)."""
    names = set()

    def targets(t):
        for x in ast.walk(t):
            if isinstance(x, ast.Name) and isinstance(x.ctx, ast.Store):
                names.add(x.id)

    def visit(body):
        for s in body:
            if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(s.name)
            elif isinstance(s, ast.Assign):
                for t in s.targets:
                    targets(t)
            elif isinstance(s, (ast.AnnAssign, ast.AugAssign)):
                targets(s.target)
            elif isinstance(s, (ast.For, ast.AsyncFor)):
                targets(s.target)
                visit(s.body + s.orelse)
            elif isinstance(s, (ast.If, ast.While)):
                visit(s.body + s.orelse)
            elif isinstance(s, (ast.With, ast.AsyncWith)):
                for item in s.items:
                    if item.optional_vars is not None:
                        targets(item.optional_vars)
                visit(s.body)
            elif isinstance(s, ast.Try):
                visit(s.body + s.orelse + s.finalbody)
                for h in s.handlers:
                    visit(h.body)

    visit(tree.body)
    return names


def imported_top_level_names(tree):
    names = set()

    def visit(body):
        for s in body:
            if isinstance(s, (ast.Import, ast.ImportFrom)):
                for a in s.names:
                    names.add((a.asname or a.name).split(".")[0])
            elif isinstance(s, (ast.If, ast.For, ast.While, ast.With)):
                visit(s.body + getattr(s, "orelse", []))
            elif isinstance(s, ast.Try):
                visit(s.body + s.orelse + s.finalbody)
                for h in s.handlers:
                    visit(h.body)

    visit(tree.body)
    return names


def def_lines(tree):
    total = 0
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            start = min([n.lineno] + [d.lineno for d in n.decorator_list])
            total += n.end_lineno - start + 1
    return total


def find_cycle(graph):
    """One cycle as a list of names, or None. graph: {module: set(modules)}."""
    state = {}
    stack = []

    def dfs(m):
        state[m] = 1
        stack.append(m)
        for d in sorted(graph.get(m, ())):
            if state.get(d) == 1:
                return stack[stack.index(d):] + [d]
            if d not in state:
                found = dfs(d)
                if found:
                    return found
        stack.pop()
        state[m] = 2
        return None

    for m in sorted(graph):
        if m not in state:
            found = dfs(m)
            if found:
                return found
    return None


class Repo:
    def __init__(self, root):
        self.root = os.path.abspath(root)
        self.lib = os.path.join(self.root, "lib")
        self.pkg = os.path.join(self.lib, PKG)
        self.table_path = os.path.join(self.root, "tools", "modules.txt")
        self.patch_path = os.path.join(self.root, "tests", "patchable.txt")
        self.script = os.path.join(self.lib, "partitor-engine")
        self.table = read_table(self.table_path)
        self.files = {}                      # module -> path of existing files
        if os.path.isdir(self.pkg):
            for fn in sorted(os.listdir(self.pkg)):
                if fn.endswith(".py"):
                    self.files[fn[:-3]] = os.path.join(self.pkg, fn)

    def rel(self, path):
        return os.path.relpath(path, self.root)

    def modules_present(self):
        return [m for m in self.table if m in self.files]

    def graph(self):
        """{module: {imported module}} for modules that exist and parse; syntax errors are skipped."""
        g = {}
        for m in self.modules_present():
            try:
                _, tree = parse(self.files[m])
            except SyntaxError:
                continue
            g[m] = {d for _, d in imported_modules(tree, self.table) if d in self.table}
        return g


def run_static(repo, out):
    # 1. stale files, parse, listed test files
    for m, path in repo.files.items():
        if m not in NO_FUTURE and m not in repo.table:
            out.add(repo.rel(path), "stale file: not listed in tools/modules.txt "
                    "(a leftover after a rename? remove it or list it)")
    tests_dir = os.path.join(repo.root, "tests")
    for m, (_, tests, _) in repo.table.items():
        for t in tests:
            if t != "*" and not os.path.isfile(os.path.join(tests_dir, t)):
                out.add("tools/modules.txt", f"module {m}: test file tests/{t} does not exist")
    trees = {}
    for m, path in repo.files.items():
        try:
            trees[m] = parse(path)
        except SyntaxError as e:
            out.add(f"{repo.rel(path)}:{e.lineno}", f"syntax error: {e.msg}")
    # 3. header (every file), future import (modules), no imports in __init__
    for m, (src, tree) in trees.items():
        rel = repo.rel(repo.files[m])
        if not any(SPDX in ln for ln in src.splitlines()[:6]):
            out.add(rel, "no SPDX-License-Identifier line in the first 6 lines")
        if m in NO_FUTURE:
            if m == "__init__":
                for n in ast.walk(tree):
                    if isinstance(n, (ast.Import, ast.ImportFrom)):
                        out.add(f"{rel}:{n.lineno}", "__init__.py must have no imports")
            continue
        has_future = any(isinstance(n, ast.ImportFrom) and n.module == "__future__"
                         and any(a.name == "annotations" for a in n.names) for n in tree.body)
        if not has_future:
            out.add(rel, "missing 'from __future__ import annotations'")
    # 2. levels and cycles
    graph = {}
    for m in repo.modules_present():
        if m not in trees:
            continue
        _, tree = trees[m]
        rel = repo.rel(repo.files[m])
        graph[m] = set()
        for lineno, d in imported_modules(tree, repo.table):
            if d is None:
                out.add(f"{rel}:{lineno}", "relative import leaves the package")
            elif d not in repo.table:
                out.add(f"{rel}:{lineno}", f"imports unknown module '{d}' (not in tools/modules.txt)")
            else:
                graph[m].add(d)
                lm, ld = repo.table[m][0], repo.table[d][0]
                if m == d:
                    out.add(f"{rel}:{lineno}", "module imports itself")
                elif ld >= lm:
                    kind = "same-level" if ld == lm else "upward"
                    out.add(f"{rel}:{lineno}", f"{kind} import: {m} (level {lm}) imports {d} "
                            f"(level {ld}); only a lower level is allowed")
    cyc = find_cycle(graph)
    if cyc:
        out.add("import graph", "cycle: " + " -> ".join(cyc))
    # 4. global rule
    for m, (_, tree) in trees.items():
        rel = repo.rel(repo.files[m])
        own, imported = own_top_level_names(tree), imported_top_level_names(tree)
        for fn in ast.walk(tree):
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for g in ast.walk(fn):
                    if isinstance(g, ast.Global):
                        for name in g.names:
                            if name in own:
                                continue
                            why = ("is imported here, so it is a copy; write owner.%s = ... instead" % name
                                   if name in imported else "is not a top-level name of this module")
                            out.add(f"{rel}:{g.lineno}", f"'global {name}' in {fn.name}(): {why}")
    # 5. patch registry
    if not os.path.isfile(repo.patch_path):
        out.add("tests/patchable.txt", "file missing")
        patch = []
    else:
        patch = read_names(repo.patch_path)
    checked = [(repo.rel(repo.files[m]), t) for m, (_, t) in trees.items()]
    if os.path.isfile(repo.script):
        try:
            checked.append((repo.rel(repo.script), parse(repo.script)[1]))
        except SyntaxError as e:
            out.add(f"{repo.rel(repo.script)}:{e.lineno}", f"syntax error: {e.msg}")
    for rel, tree in checked:
        for lineno, name in imported_names(tree):
            if name in patch:
                out.add(f"{rel}:{lineno}", f"'{name}' is patched by tests (tests/patchable.txt): "
                        f"import the module and use module.{name}")
    # 6. size
    for m, (_, tree) in trees.items():
        if m in NO_FUTURE or m not in repo.table:
            continue
        n = def_lines(tree)
        if n > LIMIT and not repo.table[m][2]:
            out.add(repo.rel(repo.files[m]), f"{n} definition lines, limit {LIMIT} "
                    "(split the module; 'exempt' in tools/modules.txt needs a reason in DESIGN.md)")
    # 7. information
    fan_in = {m: 0 for m in repo.table}
    for m, deps in graph.items():
        for d in deps:
            fan_in[d] += 1
    present = repo.modules_present()
    print(f"check-modules: {len(present)} of {len(repo.table)} listed modules exist")
    for m in present:
        if m in trees:
            print(f"  {m:<12} level {repo.table[m][0]}  def lines {def_lines(trees[m][1]):>5}  "
                  f"fan-in {fan_in[m]}")


def run_import(repo, out):
    code = ("import sys; sys.path.insert(0, %r); import partitor, os; "
            "p = os.path.realpath(partitor.__file__); l = os.path.realpath(%r); "
            "sys.exit('partitor found at ' + p + ' (want under ' + l + ')') "
            "if not p.startswith(l + os.sep) else None" % (repo.lib, repo.lib))
    r = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True)
    if r.returncode:
        out.add("import partitor", (r.stderr.strip().splitlines() or ["failed"])[-1])
    for m in repo.modules_present():
        code = f"import sys; sys.path.insert(0, {repo.lib!r}); import {PKG}.{m}"
        r = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True)
        if r.returncode:
            out.add(f"import {PKG}.{m}", (r.stderr.strip().splitlines() or ["failed"])[-1])
        else:
            print(f"  import {PKG}.{m}: ok")


def run_affected(repo, module):
    if module not in repo.table:
        print(f"check-modules: unknown module '{module}' (not in tools/modules.txt)", file=sys.stderr)
        return 2
    graph = repo.graph()
    reverse = {}
    for m, deps in graph.items():
        for d in deps:
            reverse.setdefault(d, set()).add(m)
    seen, todo = set(), [module]
    while todo:
        for m in reverse.get(todo.pop(), ()):
            if m not in seen:
                seen.add(m)
                todo.append(m)
    seen.discard(module)
    tests = []
    for m in [module] + sorted(seen):
        for t in repo.table[m][1]:
            if t not in tests:
                tests.append(t)
    print("modules: " + (" ".join(sorted(seen)) or "(none)"))
    print("tests: " + ("*" if "*" in tests else (" ".join(sorted(tests)) or "(none)")))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Check the module structure of lib/partitor.")
    ap.add_argument("--static", action="store_true", help="checks without third-party packages (default)")
    ap.add_argument("--import", dest="do_import", action="store_true",
                    help="also import every module alone in a fresh interpreter")
    ap.add_argument("--affected", metavar="MODULE", help="modules that import MODULE, and their tests")
    ap.add_argument("--root", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    help="repo root (default: the folder above tools/)")
    a = ap.parse_args(argv)
    try:
        repo = Repo(a.root)
    except (OSError, ValueError) as e:
        print(f"check-modules: {e}", file=sys.stderr)
        return 2
    if a.affected:
        return run_affected(repo, a.affected)
    out = Findings()
    run_static(repo, out)
    if a.do_import:
        run_import(repo, out)
    for line in out.items:
        print(line)
    if out:
        print(f"check-modules: {len(out.items)} finding(s)")
        return 1
    print("check-modules: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
