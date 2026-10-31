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

    def test_repo_modules_table_has_23_modules_with_known_levels(self):
        r = subprocess.run([sys.executable, "-I", TOOL, "--affected", "console"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("tests: *", r.stdout)
        with open(os.path.join(ROOT, "tools", "modules.txt"), encoding="utf-8") as fh:
            rows = [ln.split() for ln in fh if ln.strip() and not ln.startswith("#")]
        self.assertEqual(len(rows), 23)
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
        for m in present:
            with self.subTest(module=m):
                code = f"import sys; sys.path.insert(0, {lib!r}); import partitor.{m}"
                r = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True,
                                   text=True, stdin=subprocess.DEVNULL)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertEqual(r.stdout, "")             # importing prints nothing


if __name__ == "__main__":
    unittest.main()
