# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""Tests for tools/check-modules.py. Each rule gets a small synthetic package in a
temporary repo tree (tools/modules.txt, tests/patchable.txt, lib/partitor/*.py);
the real repo must pass `--static`. No third-party package is needed.

Run: python3 -m unittest -v tests/test_modules.py
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
TOOL = os.path.join(ROOT, "tools", "check-modules.py")

HEADER = ("# SPDX-License-Identifier: AGPL-3.0-or-later\n"
          "# Copyright (C) 2026 Nathan Wilkes and partitor contributors\n")
FUTURE = "from __future__ import annotations\n\n"


def module(body="", future=True, spdx=True):
    return (HEADER if spdx else "# no licence line here\n") + (FUTURE if future else "") + body


class Fixture(unittest.TestCase):
    """A synthetic repo: low (level 0) <- mid (level 1) <- top (level 2)."""

    TABLE = "0 low low_test.py\n1 mid mid_test.py\n2 top top_test.py,low_test.py\n"

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pt-mods-")
        self.pkg = os.path.join(self.tmp, "lib", "partitor")
        os.makedirs(self.pkg)
        os.makedirs(os.path.join(self.tmp, "tools"))
        os.makedirs(os.path.join(self.tmp, "tests"))
        self.table(self.TABLE)
        self.patch("fork_map\n")
        self.put("__init__", HEADER + '"""Package."""\n\nVERSION = "0.0.0"\n')
        self.put("low", module("def f():\n    return 1\n"))
        self.put("mid", module("from .low import f\n\n\ndef g():\n    return f()\n"))
        self.put("top", module("from . import mid\n\n\ndef h():\n    return mid.g()\n"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def table(self, text):
        with open(os.path.join(self.tmp, "tools", "modules.txt"), "w", encoding="utf-8") as fh:
            fh.write(text)
        for line in text.splitlines():           # every listed test file exists
            f = line.split()
            if len(f) >= 3 and f[2] != "*":
                for t in f[2].split(","):
                    open(os.path.join(self.tmp, "tests", t), "a").close()

    def patch(self, text):
        with open(os.path.join(self.tmp, "tests", "patchable.txt"), "w", encoding="utf-8") as fh:
            fh.write(text)

    def put(self, name, text):
        with open(os.path.join(self.pkg, name + ".py"), "w", encoding="utf-8") as fh:
            fh.write(text)

    def run_tool(self, *args):
        r = subprocess.run([sys.executable, "-I", TOOL, "--root", self.tmp, *args],
                           capture_output=True, text=True)
        return r.returncode, r.stdout + r.stderr


class TestStaticRules(Fixture):
    def test_clean_package_passes(self):
        rc, out = self.run_tool("--static")
        self.assertEqual(rc, 0, out)
        self.assertIn("3 of 3 listed modules exist", out)
        self.assertIn("fan-in", out)

    def test_cycle_is_reported(self):
        self.put("low", module("from . import mid\n"))
        rc, out = self.run_tool("--static")
        self.assertEqual(rc, 1, out)
        self.assertIn("cycle: low -> mid -> low", out)

    def test_upward_import_fails(self):
        self.put("low", module("from .top import h\n"))
        rc, out = self.run_tool("--static")
        self.assertEqual(rc, 1, out)
        self.assertIn("upward import: low (level 0) imports top (level 2)", out)
        self.assertIn("low.py:5", out)

    def test_same_level_import_and_import_in_a_function_fail(self):
        self.table(self.TABLE + "1 twin mid_test.py\n")
        self.put("twin", module("def f():\n    import partitor.mid\n"))
        rc, out = self.run_tool("--static")
        self.assertEqual(rc, 1, out)
        self.assertIn("same-level import: twin (level 1) imports mid (level 1)", out)

    def test_absolute_import_forms_are_followed(self):
        self.put("low", module("import partitor.top\n"))
        rc, out = self.run_tool("--static")
        self.assertEqual(rc, 1, out)
        self.assertIn("upward import: low", out)
        self.put("low", module("from partitor import top\n"))
        rc, out = self.run_tool("--static")
        self.assertIn("upward import: low", out)

    def test_unknown_module_import_fails(self):
        self.put("mid", module("from .nowhere import x\n"))
        rc, out = self.run_tool("--static")
        self.assertEqual(rc, 1, out)
        self.assertIn("unknown module 'nowhere'", out)

    def test_missing_future_import_fails(self):
        self.put("low", module("X = 1\n", future=False))
        rc, out = self.run_tool("--static")
        self.assertEqual(rc, 1, out)
        self.assertIn("missing 'from __future__ import annotations'", out)

    def test_missing_spdx_fails(self):
        self.put("low", module("X = 1\n", spdx=False))
        rc, out = self.run_tool("--static")
        self.assertEqual(rc, 1, out)
        self.assertIn("no SPDX-License-Identifier", out)

    def test_init_with_an_import_fails(self):
        self.put("__init__", HEADER + "import os\nVERSION = '0'\n")
        rc, out = self.run_tool("--static")
        self.assertEqual(rc, 1, out)
        self.assertIn("__init__.py must have no imports", out)

    def test_stray_global_fails_own_global_passes(self):
        self.put("low", module("_N = 0\n\n\ndef bump():\n    global _N\n    _N += 1\n"))
        rc, out = self.run_tool("--static")
        self.assertEqual(rc, 0, out)
        self.put("low", module("def bump():\n    global _N\n    _N = 1\n"))
        rc, out = self.run_tool("--static")
        self.assertEqual(rc, 1, out)
        self.assertIn("'global _N' in bump(): is not a top-level name of this module", out)

    def test_global_of_an_imported_name_fails(self):
        self.put("mid", module("from .low import f\n\n\ndef g():\n    global f\n    f = None\n"))
        rc, out = self.run_tool("--static")
        self.assertEqual(rc, 1, out)
        self.assertIn("is imported here, so it is a copy", out)

    def test_stale_file_fails(self):
        self.put("leftover", module("X = 1\n"))
        rc, out = self.run_tool("--static")
        self.assertEqual(rc, 1, out)
        self.assertIn("lib/partitor/leftover.py: stale file", out)

    def test_listed_test_file_must_exist(self):
        os.remove(os.path.join(self.tmp, "tests", "mid_test.py"))
        rc, out = self.run_tool("--static")
        self.assertEqual(rc, 1, out)
        self.assertIn("tests/mid_test.py does not exist", out)

    def test_syntax_error_fails(self):
        self.put("low", module("def f(:\n"))
        rc, out = self.run_tool("--static")
        self.assertEqual(rc, 1, out)
        self.assertIn("syntax error", out)

    def test_from_import_of_a_patched_name_fails(self):
        self.put("low", module("def fork_map():\n    pass\n"))
        self.put("mid", module("from .low import fork_map\n"))
        rc, out = self.run_tool("--static")
        self.assertEqual(rc, 1, out)
        self.assertIn("'fork_map' is patched by tests", out)
        self.assertIn("mid.py:5", out)
        self.put("mid", module("from . import low\n\n\ndef g():\n    return low.fork_map()\n"))
        rc, out = self.run_tool("--static")
        self.assertEqual(rc, 0, out)

    def test_patched_name_in_the_launcher_script_fails(self):
        with open(os.path.join(self.tmp, "lib", "partitor-engine"), "w", encoding="utf-8") as fh:
            fh.write("from partitor.low import fork_map as fm\n")
        rc, out = self.run_tool("--static")
        self.assertEqual(rc, 1, out)
        self.assertIn("lib/partitor-engine:1", out)

    def test_long_module_fails_unless_exempt(self):
        self.put("low", module("def f():\n" + "    pass\n" * 1100))
        rc, out = self.run_tool("--static")
        self.assertEqual(rc, 1, out)
        self.assertIn("1101 definition lines, limit 1100", out)
        self.table(self.TABLE.replace("0 low low_test.py", "0 low low_test.py exempt"))
        rc, out = self.run_tool("--static")
        self.assertEqual(rc, 0, out)

    def test_bad_table_line_is_a_usage_error(self):
        self.table("zero low low_test.py\n")
        rc, out = self.run_tool("--static")
        self.assertEqual(rc, 2, out)
        self.assertIn("want 'LEVEL MODULE TESTS [exempt]'", out)


class TestAffected(Fixture):
    def test_dependents_are_transitive_and_tests_are_a_union(self):
        rc, out = self.run_tool("--affected", "low")
        self.assertEqual(rc, 0, out)
        self.assertIn("modules: mid top", out)
        self.assertIn("tests: low_test.py mid_test.py top_test.py", out)
        rc, out = self.run_tool("--affected", "top")
        self.assertIn("modules: (none)", out)
        self.assertIn("tests: low_test.py top_test.py", out)

    def test_star_means_all_tests(self):
        self.table(self.TABLE.replace("1 mid mid_test.py", "1 mid *"))
        rc, out = self.run_tool("--affected", "low")
        self.assertIn("tests: *", out)

    def test_unknown_module_is_a_usage_error(self):
        rc, out = self.run_tool("--affected", "nope")
        self.assertEqual(rc, 2, out)


class TestImportMode(Fixture):
    def test_import_mode_imports_each_module_alone(self):
        rc, out = self.run_tool("--import")
        self.assertEqual(rc, 0, out)
        for m in ("low", "mid", "top"):
            self.assertIn(f"import partitor.{m}: ok", out)

    def test_import_error_in_a_module_fails(self):
        self.put("low", module('raise RuntimeError("boom in low")\n'))
        rc, out = self.run_tool("--import")
        self.assertEqual(rc, 1, out)
        self.assertIn("boom in low", out)


class TestRealRepo(unittest.TestCase):
    def test_repo_passes_static_checks(self):
        r = subprocess.run([sys.executable, "-I", TOOL, "--static"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_repo_modules_table_has_25_modules_with_known_levels(self):
        r = subprocess.run([sys.executable, "-I", TOOL, "--affected", "console"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("tests: *", r.stdout)
        with open(os.path.join(ROOT, "tools", "modules.txt"), encoding="utf-8") as fh:
            rows = [ln.split() for ln in fh if ln.strip() and not ln.startswith("#")]
        self.assertEqual(len(rows), 25)
        self.assertEqual(sorted({int(r[0]) for r in rows}), [0, 1, 2, 3, 4, 5, 6, 7, 8, 9])

    def test_every_existing_module_imports_alone(self):
        """A fresh interpreter, no other module loaded first: a hidden import order fails here."""
        try:
            import cv2, numpy, pymupdf, yaml  # noqa: E401,F401
        except ImportError:
            self.skipTest("the venv packages are not installed")
        lib = os.path.join(ROOT, "lib")
        with open(os.path.join(ROOT, "tools", "modules.txt"), encoding="utf-8") as fh:
            listed = [ln.split()[1] for ln in fh if ln.strip() and not ln.startswith("#")]
        present = [m for m in listed if os.path.isfile(os.path.join(lib, "partitor", m + ".py"))]
        for m in ("console", "config", "model", "typography", "mapping", "bars", "parallel"):
            self.assertIn(m, present)              # moved in step M1
        for m in ("vision", "clef", "strips"):
            self.assertIn(m, present)              # moved in step M2
        for m in ("reflow", "ownership", "analysis"):
            self.assertIn(m, present)              # moved in step M3
        for m in ("lines", "render"):
            self.assertIn(m, present)              # moved in step M4
        self.assertIn("library", present)          # moved in step M5
        for m in ("build", "proof"):
            self.assertIn(m, present)              # moved in step M6
        for m in ("cli_common", "cli_bars", "cli_parts", "cli_items"):
            self.assertIn(m, present)              # moved in step M7
        self.assertIn("cli_main", present)         # moved in step M8
        self.assertIn("turnplan", present)         # added in 0.8.3
        self.assertEqual(len(present), len(listed))    # all 25 modules exist (23 of the plan, stagecache in 0.7.0, turnplan in 0.8.3)
        for m in present:
            with self.subTest(module=m):
                code = f"import sys; sys.path.insert(0, {lib!r}); import partitor.{m}"
                r = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True,
                                   text=True, stdin=subprocess.DEVNULL)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertEqual(r.stdout, "")             # importing prints nothing

    def test_m2_modules_are_one_level_and_do_not_import_each_other(self):
        """vision, clef and strips sit on level 1: none may import another (plan section 3)."""
        import ast
        level1 = ("vision", "clef", "strips")
        for m in level1:
            path = os.path.join(ROOT, "lib", "partitor", m + ".py")
            self.assertTrue(os.path.isfile(path), m)
            with open(path, encoding="utf-8") as fh:
                tree = ast.parse(fh.read())
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and (node.level or node.module == "partitor"):
                    got = {a.name for a in node.names} if not node.module else {node.module}
                    got = {g.split(".")[-1] for g in got}
                    self.assertFalse(got & (set(level1) - {m}), f"{m} imports {got}")

    def test_m2_modules_import_no_patched_name_by_name(self):
        """No name of tests/patchable.txt is imported with `from .x import NAME` (rule R1)."""
        import ast
        with open(os.path.join(ROOT, "tests", "patchable.txt"), encoding="utf-8") as fh:
            patched = {ln.strip() for ln in fh if ln.strip() and not ln.startswith("#")}
        for m in ("vision", "clef", "strips"):
            with open(os.path.join(ROOT, "lib", "partitor", m + ".py"), encoding="utf-8") as fh:
                tree = ast.parse(fh.read())
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.level:
                    self.assertFalse({a.name for a in node.names} & patched, m)

    def test_m3_modules_sit_on_their_levels_and_import_only_lower_ones(self):
        """reflow (1), ownership (2) and analysis (3): imports go to strictly lower levels (plan 3)."""
        import ast
        level = {"console": 0, "config": 0, "model": 0, "typography": 0, "mapping": 0, "bars": 0,
                 "parallel": 1, "reflow": 1, "strips": 1, "vision": 1, "clef": 1,
                 "ownership": 2, "stagecache": 2, "analysis": 3}
        for m in ("reflow", "ownership", "analysis"):
            with open(os.path.join(ROOT, "lib", "partitor", m + ".py"), encoding="utf-8") as fh:
                tree = ast.parse(fh.read())
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.level:
                    got = {node.module} if node.module else {a.name for a in node.names}
                    for g in got:
                        self.assertLess(level[g], level[m], f"{m} imports {g}")

    def test_m3_modules_import_no_patched_name_by_name(self):
        """analyse_one is patched by tests: analysis defines it, no module imports it by name."""
        import ast
        with open(os.path.join(ROOT, "tests", "patchable.txt"), encoding="utf-8") as fh:
            patched = {ln.strip() for ln in fh if ln.strip() and not ln.startswith("#")}
        self.assertIn("analyse_one", patched)
        for m in ("reflow", "ownership", "analysis"):
            with open(os.path.join(ROOT, "lib", "partitor", m + ".py"), encoding="utf-8") as fh:
                tree = ast.parse(fh.read())
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.level:
                    self.assertFalse({a.name for a in node.names} & patched, m)

    def test_m4_modules_sit_on_their_levels_and_import_only_lower_ones(self):
        """lines (2) and render (3): imports go to strictly lower levels (plan 3)."""
        import ast
        level = {"console": 0, "config": 0, "model": 0, "typography": 0, "mapping": 0, "bars": 0,
                 "parallel": 1, "reflow": 1, "strips": 1, "vision": 1, "clef": 1,
                 "lines": 2, "ownership": 2, "stagecache": 2, "render": 3, "turnplan": 1}
        for m in ("lines", "render"):
            with open(os.path.join(ROOT, "lib", "partitor", m + ".py"), encoding="utf-8") as fh:
                tree = ast.parse(fh.read())
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.level:
                    got = {node.module} if node.module else {a.name for a in node.names}
                    for g in got:
                        if g != "VERSION":                   # `from . import VERSION`: the package itself
                            self.assertLess(level[g], level[m], f"{m} imports {g}")

    def test_m4_modules_import_no_patched_name_by_name(self):
        """SYSTEM_GAP_LAST is patched by tests: render defines it, no module imports it by name."""
        import ast
        with open(os.path.join(ROOT, "tests", "patchable.txt"), encoding="utf-8") as fh:
            patched = {ln.strip() for ln in fh if ln.strip() and not ln.startswith("#")}
        self.assertIn("SYSTEM_GAP_LAST", patched)
        for m in ("lines", "render"):
            with open(os.path.join(ROOT, "lib", "partitor", m + ".py"), encoding="utf-8") as fh:
                tree = ast.parse(fh.read())
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.level:
                    self.assertFalse({a.name for a in node.names} & patched, m)
        with open(os.path.join(ROOT, "lib", "partitor-engine"), encoding="utf-8") as fh:
            script = ast.parse(fh.read())
        for node in ast.walk(script):
            if isinstance(node, ast.ImportFrom):
                self.assertNotIn("SYSTEM_GAP_LAST", {a.name for a in node.names})   # no shim

    def test_m5_library_sits_on_level_4_and_imports_only_lower_ones(self):
        """library (4): imports go to strictly lower levels; it has no `global` and no render import."""
        import ast
        level = {"console": 0, "config": 0, "bars": 0, "clef": 1, "render": 3, "library": 4}
        with open(os.path.join(ROOT, "lib", "partitor", "library.py"), encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        got_all = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level:
                got = {node.module} if node.module else {a.name for a in node.names}
                got_all |= got
                for g in got:
                    self.assertLess(level[g], level["library"], f"library imports {g}")
            self.assertNotIsInstance(node, ast.Global)   # the module keeps no state of its own
        self.assertEqual(got_all, {"bars", "clef", "config", "console"})

    def test_m5_library_imports_no_patched_name_by_name(self):
        """No name tests replace (patchable.txt) is imported by name by library, and none has a shim."""
        import ast
        with open(os.path.join(ROOT, "tests", "patchable.txt"), encoding="utf-8") as fh:
            patched = {ln.strip() for ln in fh if ln.strip() and not ln.startswith("#")}
        with open(os.path.join(ROOT, "lib", "partitor", "library.py"), encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level:
                self.assertFalse({a.name for a in node.names} & patched)
            if isinstance(node, (ast.FunctionDef, ast.Assign)):
                bound = {node.name} if isinstance(node, ast.FunctionDef) else {
                    t.id for t in node.targets if isinstance(t, ast.Name)}
                self.assertFalse(bound & patched, "library must not own a patched name")

    def test_m6_build_and_proof_are_level_5_and_do_not_import_each_other(self):
        """build and proof (both 5): lower imports only, none between them, no `global`."""
        import ast
        level = {"console": 0, "config": 0, "model": 0, "typography": 0, "mapping": 0, "bars": 0,
                 "parallel": 1, "reflow": 1, "strips": 1, "vision": 1, "clef": 1,
                 "lines": 2, "ownership": 2, "stagecache": 2, "analysis": 3, "render": 3, "library": 4,
                 "build": 5, "proof": 5}
        for m in ("build", "proof"):
            with open(os.path.join(ROOT, "lib", "partitor", m + ".py"), encoding="utf-8") as fh:
                tree = ast.parse(fh.read())
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.level:
                    got = {node.module} if node.module else {a.name for a in node.names}
                    for g in got:
                        if g != "VERSION":
                            self.assertLess(level[g], level[m], f"{m} imports {g}")
                self.assertNotIsInstance(node, ast.Global)

    def test_m6_run_build_and_cmd_build_are_read_as_build_names(self):
        """Patched names: build defines them, no module imports them by name, the script has
        no shim and its readers use build.run_build and build.cmd_build."""
        import ast
        with open(os.path.join(ROOT, "tests", "patchable.txt"), encoding="utf-8") as fh:
            patched = {ln.strip() for ln in fh if ln.strip() and not ln.startswith("#")}
        mine = {"run_build", "cmd_build"}
        self.assertLessEqual(mine, patched)
        for m in ("build", "proof"):
            with open(os.path.join(ROOT, "lib", "partitor", m + ".py"), encoding="utf-8") as fh:
                tree = ast.parse(fh.read())
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.level:
                    self.assertFalse({a.name for a in node.names} & patched, m)
        # the readers: cli_items (cmd_new, offer_reflow) and cli_main (the command table of main)
        reads = set()
        for path in (os.path.join(ROOT, "lib", "partitor-engine"),
                     os.path.join(ROOT, "lib", "partitor", "cli_items.py"),
                     os.path.join(ROOT, "lib", "partitor", "cli_main.py")):
            with open(path, encoding="utf-8") as fh:
                tree = ast.parse(fh.read())
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    self.assertFalse({a.name for a in node.names} & mine)        # no shim
                if isinstance(node, ast.Name):
                    self.assertNotIn(node.id, mine)                              # no bare read
                if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                        and node.value.id == "build" and node.attr in mine):
                    reads.add(node.attr)
        self.assertEqual(reads, mine)

    def test_m7_cli_modules_sit_on_their_levels_and_keep_no_state(self):
        """cli_common (6), cli_bars and cli_parts (7), cli_items (8): lower imports only, so
        cli_bars and cli_parts do not import each other; no `global`."""
        import ast
        level = {"console": 0, "config": 0, "model": 0, "typography": 0, "mapping": 0, "bars": 0,
                 "parallel": 1, "reflow": 1, "strips": 1, "vision": 1, "clef": 1,
                 "lines": 2, "ownership": 2, "stagecache": 2, "analysis": 3, "render": 3, "library": 4,
                 "build": 5, "proof": 5, "cli_common": 6, "cli_bars": 7, "cli_parts": 7,
                 "cli_items": 8}
        for m in ("cli_common", "cli_bars", "cli_parts", "cli_items"):
            with open(os.path.join(ROOT, "lib", "partitor", m + ".py"), encoding="utf-8") as fh:
                tree = ast.parse(fh.read())
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.level:
                    got = {node.module} if node.module else {a.name for a in node.names}
                    for g in got:
                        if g != "VERSION":
                            self.assertLess(level[g], level[m], f"{m} imports {g}")
                self.assertNotIsInstance(node, ast.Global)

    def test_m7_cmd_rebuild_is_read_as_a_cli_items_name(self):
        """cmd_rebuild is patched by tests: cli_items defines it, no module imports it by name,
        the script has no shim; cli_main reads cli_items.cmd_rebuild (menu r and the command table)."""
        import ast
        with open(os.path.join(ROOT, "tests", "patchable.txt"), encoding="utf-8") as fh:
            patched = {ln.strip() for ln in fh if ln.strip() and not ln.startswith("#")}
        self.assertIn("cmd_rebuild", patched)
        for m in ("cli_common", "cli_bars", "cli_parts", "cli_items"):
            with open(os.path.join(ROOT, "lib", "partitor", m + ".py"), encoding="utf-8") as fh:
                tree = ast.parse(fh.read())
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.level:
                    self.assertFalse({a.name for a in node.names} & patched, m)
        reads = 0
        for name in ("partitor-engine", os.path.join("partitor", "cli_main.py")):
            with open(os.path.join(ROOT, "lib", name), encoding="utf-8") as fh:
                tree = ast.parse(fh.read())
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    self.assertNotIn("cmd_rebuild", {a.name for a in node.names})  # no shim
                if isinstance(node, ast.Name):
                    self.assertNotEqual(node.id, "cmd_rebuild")                     # no bare read
                if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                        and node.value.id == "cli_items" and node.attr == "cmd_rebuild"):
                    reads += 1
        self.assertEqual(reads, 2)

    def test_m8_cli_main_is_level_9_and_reads_the_r1_names_through_modules(self):
        """cli_main (9) imports lower modules only and has no `global`. Its command table is built
        per call and reads build.cmd_build and cli_items.cmd_rebuild as module attributes."""
        import ast
        level = {"console": 0, "config": 0, "model": 0, "typography": 0, "mapping": 0, "bars": 0,
                 "parallel": 1, "reflow": 1, "strips": 1, "vision": 1, "clef": 1,
                 "lines": 2, "ownership": 2, "stagecache": 2, "analysis": 3, "render": 3, "library": 4,
                 "build": 5, "proof": 5, "cli_common": 6, "cli_bars": 7, "cli_parts": 7,
                 "cli_items": 8, "cli_main": 9}
        with open(os.path.join(ROOT, "lib", "partitor", "cli_main.py"), encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        reads = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level:
                got = {node.module} if node.module else {a.name for a in node.names}
                for g in got:
                    if g != "VERSION":
                        self.assertLess(level[g], level["cli_main"], f"cli_main imports {g}")
            self.assertNotIsInstance(node, ast.Global)
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                reads.add((node.value.id, node.attr))
        self.assertLessEqual({("build", "cmd_build"), ("cli_items", "cmd_rebuild")}, reads)

    def test_m8_the_script_is_a_thin_launcher(self):
        """lib/partitor-engine defines nothing: it puts lib/ on the path and starts cli_main.main.
        python -m partitor (__main__.py) starts the same function."""
        import ast
        with open(os.path.join(ROOT, "lib", "partitor-engine"), encoding="utf-8") as fh:
            text = fh.read()
        tree = ast.parse(text)
        self.assertEqual([n for n in tree.body
                          if isinstance(n, (ast.FunctionDef, ast.ClassDef, ast.Assign))], [])
        imported = {(n.module or "", a.name) for n in tree.body if isinstance(n, ast.ImportFrom)
                    for a in n.names}
        self.assertEqual(imported, {("partitor.cli_main", "main")})
        self.assertEqual({a.name for n in tree.body if isinstance(n, ast.Import) for a in n.names},
                         {"os", "sys"})
        self.assertLess(len(tree.body), 8)
        self.assertIn("sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))", text)
        with open(os.path.join(ROOT, "lib", "partitor", "__main__.py"), encoding="utf-8") as fh:
            self.assertIn("from partitor.cli_main import main", fh.read())

    def test_check_margins_lives_in_config_and_render_does_not_keep_it(self):
        """O7: check_margins and MIN_MARGIN_MM belong to config; library reads them from there."""
        code = ("import sys; sys.path.insert(0, %r); from partitor import config, library, render; "
                "print(library.check_margins is config.check_margins, "
                "hasattr(render, 'check_margins'), hasattr(render, 'MIN_MARGIN_MM'), "
                "config.MIN_MARGIN_MM)" % os.path.join(ROOT, "lib"))
        r = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True,
                           stdin=subprocess.DEVNULL)
        if r.returncode != 0 and "No module named" in r.stderr:
            self.skipTest("the venv packages are not installed")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.split(), ["True", "False", "False", "5.0"])

    def test_ownership_reaches_tune_through_config(self):
        """TUNE is changed in place by the script and read by ownership as config.TUNE (R1)."""
        import ast
        with open(os.path.join(ROOT, "lib", "partitor", "ownership.py"), encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        self.assertNotIn("TUNE", names)                  # no name of its own, no copy
        attrs = {(n.value.id, n.attr) for n in ast.walk(tree)
                 if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)}
        self.assertIn(("config", "TUNE"), attrs)

    def test_proof_h_is_read_only_data_of_the_analysis_module(self):
        """PROOF_H = 1400 lives in analysis; no other file binds it (nothing sets it at run time)."""
        import ast
        import glob
        files = sorted(glob.glob(os.path.join(ROOT, "lib", "partitor", "*.py")))
        files.append(os.path.join(ROOT, "lib", "partitor-engine"))
        for path in files:
            with open(path, encoding="utf-8") as fh:
                tree = ast.parse(fh.read())
            binds = [n for n in ast.walk(tree)
                     if (isinstance(n, ast.Name) and n.id == "PROOF_H"
                         and isinstance(n.ctx, (ast.Store, ast.Del)))
                     or (isinstance(n, ast.Attribute) and n.attr == "PROOF_H"
                         and isinstance(n.ctx, (ast.Store, ast.Del)))
                     or (isinstance(n, ast.Global) and "PROOF_H" in n.names)]
            if os.path.basename(path) == "analysis.py":
                self.assertEqual(len(binds), 1, path)    # the one assignment at top level
            else:
                self.assertEqual(binds, [], path)
        code = ("import sys; sys.path.insert(0, %r); from partitor import analysis; "
                "print(analysis.PROOF_H)" % os.path.join(ROOT, "lib"))
        r = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True,
                           stdin=subprocess.DEVNULL)
        if r.returncode != 0 and "No module named" in r.stderr:
            self.skipTest("the venv packages are not installed")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "1400")


if __name__ == "__main__":
    unittest.main()
