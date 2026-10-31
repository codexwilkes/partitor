# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""Tests for the input handling of tools/m0_depmap.py: one file as before, a folder
(every *.py in it, merged), several inputs, and the error for a name defined twice.
The edge logic is not tested here. The run through `main` needs networkx (not a
dependency of partitor) and is skipped without it.

Run: python3 -m unittest -v tests/test_depmap.py
"""
import importlib.util
import json
import os
import shutil
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, "..", "tools", "m0_depmap.py")

try:
    import networkx  # noqa: F401
    HAVE_NX = True
except ImportError:                      # pragma: no cover
    HAVE_NX = False


def load_tool():
    spec = importlib.util.spec_from_file_location("m0_depmap", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestDepmapInputs(unittest.TestCase):
    def setUp(self):
        self.m0 = load_tool()
        self.tmp = tempfile.mkdtemp(prefix="pt-m0-")
        self.pkg = os.path.join(self.tmp, "pkg")
        os.makedirs(self.pkg)
        self.write("pkg/a.py", "LIMIT = 3\n\n\ndef one():\n    return two() + LIMIT\n")
        self.write("pkg/b.py", "def two():\n    return 2\n")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, rel, text):
        with open(os.path.join(self.tmp, rel), "w", encoding="utf-8") as fh:
            fh.write(text)

    def names(self, tree):
        funcs, classes, assigns = self.m0.top_level(tree)
        return sorted(funcs), sorted(classes), sorted(assigns)

    def test_one_file_is_read_as_before(self):
        path = os.path.join(self.pkg, "a.py")
        src, tree = self.m0.load_all(path)
        src0, tree0 = self.m0.load(path)
        self.assertEqual(src, src0)
        self.assertEqual(self.names(tree), self.names(tree0))

    def test_folder_merges_every_py_file(self):
        with open(os.path.join(self.pkg, "notes.txt"), "w") as fh:
            fh.write("def ignored(): pass\n")
        os.makedirs(os.path.join(self.pkg, "sub"))
        self.write("pkg/sub/c.py", "def deeper():\n    pass\n")
        _, tree = self.m0.load_all(self.pkg)
        self.assertEqual(self.names(tree), (["one", "two"], [], ["LIMIT"]))

    def test_folder_and_file_can_be_mixed(self):
        self.write("launcher", "def main():\n    return one()\n")
        _, tree = self.m0.load_all([self.pkg, os.path.join(self.tmp, "launcher")])
        self.assertEqual(self.names(tree)[0], ["main", "one", "two"])

    def test_duplicate_name_in_two_files_stops_with_a_clear_error(self):
        self.write("pkg/c.py", "def two():\n    return 3\n")
        with self.assertRaises(SystemExit) as cm:
            self.m0.load_all(self.pkg)
        self.assertIn("duplicate top-level name 'two'", str(cm.exception))

    def test_empty_folder_and_missing_path_stop_with_an_error(self):
        os.makedirs(os.path.join(self.tmp, "empty"))
        for bad in (os.path.join(self.tmp, "empty"), os.path.join(self.tmp, "nope")):
            with self.subTest(path=os.path.basename(bad)):
                with self.assertRaises(SystemExit):
                    self.m0.load_all(bad)

    @unittest.skipUnless(HAVE_NX, "networkx not installed (not a partitor dependency)")
    def test_main_on_a_folder_finds_the_edge_across_files(self):
        out = os.path.join(self.tmp, "out")
        self.m0.main(self.pkg, out)
        with open(os.path.join(out, "depmap.json"), encoding="utf-8") as fh:
            report = json.load(fh)
        self.assertEqual(report["totals"]["functions"], 2)
        members = [set(c["functions"]) for c in report["clusters"]]
        self.assertIn({"one", "two"}, members)


if __name__ == "__main__":
    unittest.main()
