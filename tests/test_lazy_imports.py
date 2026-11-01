# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""Tests for the lazy image-library imports (docs/DESIGN.md §12.3).

Commands that never read an image start without cv2, numpy or pymupdf. Each case runs the
launcher in a fresh interpreter and looks at sys.modules. Needs the venv packages for the
heavy-command case; run with the venv interpreter:

    venv/bin/python3 -m unittest -v tests/test_lazy_imports.py
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from support import SRC, LIB, needs_deps, package_holders, setUpModule, tearDownModule  # noqa: E402,F401

HEAVY = ("cv2", "numpy", "pymupdf")

# Run the launcher as the real program does; report the heavy packages that got loaded.
PROBE = (
    "import json, os, runpy, sys\n"
    "sys.argv = ['partitor-engine'] + sys.argv[1:]\n"
    "rc = 0\n"
    "try:\n"
    "    runpy.run_path(%r, run_name='__main__')\n"
    "except SystemExit as e:\n"
    "    rc = e.code\n"
    "except Exception:\n"
    "    import traceback; traceback.print_exc(); rc = 'crash'\n"
    "print(json.dumps({'rc': rc, 'heavy': sorted(m for m in %r if m in sys.modules)}))\n"
)

# Every command that reads only the item file (and the library folders). No image is opened.
LIGHT_COMMANDS = (["--version"], ["--help"], ["list"], ["list", "Schein"], ["show", "1"],
                  ["set", "1", "gap=11"], ["expand", "1"], ["contract", "1"], ["bars", "1"],
                  ["parts", "1"], ["groups", "1"], ["meta", "1"], ["rename", "1"],
                  ["reid", "1"], ["proof", "1"])

# Modules the light commands import. Importing one of them alone must not load an image package.
LIGHT_MODULES = ("config", "console", "model", "mapping", "typography", "bars", "clef", "library",
                 "proof", "cli_common", "cli_bars", "cli_parts", "cli_items", "cli_main")


def run_probe(args, library=None, modules=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith("PARTITOR_")}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    if library:
        env["PARTITOR_LIBRARY"] = str(library)
    if modules is None:
        code = PROBE % (SRC, HEAVY)
    else:
        code = ("import json, sys; sys.path.insert(0, %r)\n"
                "import importlib\n[importlib.import_module('partitor.' + m) for m in %r]\n"
                "print(json.dumps({'rc': 0, 'heavy': sorted(m for m in %r if m in sys.modules)}))\n"
                % (LIB, modules, HEAVY))
    r = subprocess.run([sys.executable, "-c", code] + list(args), capture_output=True, text=True,
                       stdin=subprocess.DEVNULL, env=env, timeout=120)
    try:
        return json.loads(r.stdout.strip().splitlines()[-1]), r
    except (ValueError, IndexError):
        raise AssertionError(f"probe failed: {r.stdout!r} {r.stderr!r}")


@needs_deps
class TestLightCommandsStayLight(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.share = Path(self._tmp.name)
        (self.share / "inbox").mkdir()
        (self.share / "library").mkdir()

    def test_no_command_that_reads_no_image_loads_an_image_package(self):
        if os.geteuid() == 0:
            self.skipTest("the engine refuses root")
        for args in LIGHT_COMMANDS:
            with self.subTest(args=args):
                got, r = run_probe(args, self.share)
                self.assertNotEqual(got["rc"], "crash", r.stderr)
                self.assertEqual(got["heavy"], [], r.stderr)

    def test_the_same_with_one_item_in_the_library(self):
        if os.geteuid() == 0:
            self.skipTest("the engine refuses root")
        from support import pt
        item = self.share / "library" / "2026-10-0001-schein-nun"
        item.mkdir()
        pt.save_item(item, {"id": "2026-10-0001", "slug": "schein-nun", "composer": "Schein",
                            "title": "Nun", "parts": ["A"], "layout": {},
                            "built": {"parts": [{"part": "A", "pages": 2, "staff_mm": 6.0,
                                                 "staff_max_mm": 7.0, "gap": 10.0}]}})
        for args in (["list"], ["show", "1"], ["set", "1", "gap=11"], ["expand", "1"],
                     ["contract", "1"], ["bars", "1"], ["parts", "1"], ["meta", "1"]):
            with self.subTest(args=args):
                got, r = run_probe(args, self.share)
                self.assertNotEqual(got["rc"], "crash", r.stderr)
                self.assertEqual(got["heavy"], [], r.stderr)
        self.assertEqual(run_probe(["show", "1"], self.share)[0]["rc"], 0)
        self.assertIn("Schein", run_probe(["list"], self.share)[1].stdout)

    def test_a_heavy_command_still_loads_the_image_packages(self):
        if os.geteuid() == 0:
            self.skipTest("the engine refuses root")
        got, r = run_probe(["build", os.path.join(self._tmp.name, "none.pdf")], self.share)
        self.assertEqual(got["heavy"], sorted(HEAVY), r.stderr)
        self.assertNotEqual(got["rc"], 0)             # no such PDF: the command ran and failed

    def test_each_light_module_imports_alone_without_an_image_package(self):
        for name in LIGHT_MODULES:
            with self.subTest(module=name):
                got, r = run_probe([], modules=[name])
                self.assertNotEqual(got["rc"], "crash", r.stderr)
                self.assertEqual(got["heavy"], [], r.stderr)


@needs_deps
class TestLazyNames(unittest.TestCase):
    """R1 decisions of this release."""

    def test_paper_is_owned_by_config_and_render_reads_the_same_object(self):
        from partitor import config, render
        self.assertIs(render.PAPER, config.PAPER)
        self.assertEqual(config.PAPER["ledger"], (1224.0, 792.0))
        self.assertEqual(sorted(config.PAPER), ["a4", "ledger", "letter"])

    def test_step_size_is_owned_by_library_and_build_keeps_no_copy(self):
        from partitor import build, library
        holders = package_holders("step_size")
        self.assertIn("partitor.library", holders)
        self.assertNotIn("partitor.build", holders)       # it left build
        self.assertEqual(library.step_size.__module__, "partitor.library")

    def test_the_build_commands_are_read_from_the_build_module_when_they_run(self):
        """main loads build only for pieces, detect and build; a fake build.cmd_build is called."""
        if os.geteuid() == 0:
            self.skipTest("the engine refuses root")
        from partitor import build
        from support import mock_attr, pt
        seen = []
        real_argv = sys.argv
        sys.argv = ["partitor", "build", "x.pdf"]
        try:
            with mock_attr(build, "cmd_build", lambda ns: seen.append(ns.pdf) or 7):
                self.assertEqual(pt.main(), 7)
        finally:
            sys.argv = real_argv
        self.assertEqual(seen, ["x.pdf"])

    def test_the_image_packages_are_imported_inside_functions_not_at_the_top(self):
        """clef, bars, typography, proof, library, cli_items, cli_common and model have no
        top-level import of cv2, numpy (except under TYPE_CHECKING) or pymupdf."""
        import ast
        for name in ("clef", "bars", "typography", "proof", "library", "cli_items", "cli_common",
                     "cli_parts", "cli_bars", "cli_main", "model"):
            with open(os.path.join(LIB, "partitor", name + ".py"), encoding="utf-8") as fh:
                tree = ast.parse(fh.read())
            for node in tree.body:
                mods = []
                if isinstance(node, ast.Import):
                    mods = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and not node.level:
                    mods = [node.module]
                for m in mods:
                    self.assertNotIn(m.split(".")[0], HEAVY, f"{name} imports {m} at the top")
