# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""Tests for tools/move-symbols.py on a synthetic script and a synthetic package in a
temporary repo tree (tools/modules.txt, tests/patchable.txt, lib/partitor-engine). The
tool only parses the script; it imports nothing, so no third-party package is needed.

Run: python3 -m unittest -v tests/test_move_symbols.py
"""
import contextlib
import importlib.util
import io
import json
import os
import shutil
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, "..", "tools", "move-symbols.py")

SCRIPT = '''#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
import os
import re
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
from partitor import VERSION  # noqa: E402

# The limit of a box.
LIMIT = 5
STATE = {"n": 0}       # changed in place
FLAG = True


# Doubles a number.
def double(x):
    return x * 2 + LIMIT


class Box:
    """A box."""
    def get(self):
        return double(1)


def clean(s):
    return re.sub("a", "b", s)


def arr():
    return np.zeros(3)


def flip():
    global FLAG
    FLAG = False


def uses_double():
    return double(2)


def uses_state():
    return STATE["n"] + LIMIT


def main():
    return uses_double() + uses_state() + len(clean("a")) + FLAG
'''

TABLE = "0 low *\n0 other *\n1 high *\n"
MAP = {"symbols": {"low": ["LIMIT", "double", "Box"], "other": ["clean"],
                   "high": ["uses_double"], "np_mod": ["arr"]}}


def load_tool():
    spec = importlib.util.spec_from_file_location("move_symbols", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tool = load_tool()
        self.tmp = tempfile.mkdtemp(prefix="pt-move-")
        for d in ("tools", "tests", os.path.join("lib", "partitor")):
            os.makedirs(os.path.join(self.tmp, d))
        self.put("tools/modules.txt", TABLE + "0 np_mod *\n")
        self.put("tests/patchable.txt", "fork_map\n")
        self.put("lib/partitor/__init__.py", 'VERSION = "0.0.0"\n')
        self.put("lib/partitor-engine", SCRIPT)
        self.pristine = os.path.join(self.tmp, "pristine")
        self.put("pristine", SCRIPT)
        self.map = os.path.join(self.tmp, "map.json")
        with open(self.map, "w", encoding="utf-8") as fh:
            json.dump(MAP, fh)
        self.cfg = None

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def path(self, rel):
        return os.path.join(self.tmp, *rel.split("/"))

    def put(self, rel, text):
        with open(self.path(rel), "w", encoding="utf-8") as fh:
            fh.write(text)

    def get(self, rel):
        with open(self.path(rel), encoding="utf-8") as fh:
            return fh.read()

    def config(self, cfg):
        self.cfg = os.path.join(self.tmp, "config.json")
        with open(self.cfg, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh)

    def run_tool(self, modules, *extra):
        args = ["--root", self.tmp, "--modules", modules, "--map", self.map, *extra]
        if self.cfg:
            args += ["--config", self.cfg]
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = self.tool.main(args)
        return rc, out.getvalue(), err.getvalue()

    def apply(self, modules, *extra):
        rc, out, err = self.run_tool(modules, "--apply", *extra)
        self.assertEqual(rc, 0, out + err)
        return out

    def check(self, modules, *extra):
        return self.run_tool(modules, "--check", "--pristine", self.pristine, *extra)


class TestMove(Fixture):
    def test_dry_run_writes_nothing(self):
        rc, out, _ = self.run_tool("low")
        self.assertEqual(rc, 0, out)
        self.assertFalse(os.path.exists(self.path("lib/partitor/low.py")))
        self.assertEqual(self.get("lib/partitor-engine"), SCRIPT)
        self.assertIn("low: 3 names", out)

    def test_text_is_unchanged_with_decorator_free_comment_above(self):
        self.apply("low")
        low = self.get("lib/partitor/low.py")
        for block in ("# The limit of a box.\nLIMIT = 5\n",
                      "# Doubles a number.\ndef double(x):\n    return x * 2 + LIMIT\n",
                      'class Box:\n    """A box."""\n    def get(self):\n        return double(1)\n'):
            self.assertIn(block, low)
        self.assertEqual(self.check("low")[0], 0)

    def test_header_and_only_the_imports_that_the_code_uses(self):
        self.apply("other")
        text = self.get("lib/partitor/other.py")
        lines = text.splitlines()
        self.assertEqual(lines[0], "# SPDX-License-Identifier: AGPL-3.0-or-later")
        self.assertIn("from __future__ import annotations", lines)
        self.assertIn("import re", lines)
        self.assertNotIn("import os", lines)
        self.assertNotIn("import numpy as np", lines)
        self.assertEqual(text.count('"""'), 2)                     # the one-line docstring

    def test_third_party_import_comes_after_the_standard_library(self):
        self.apply("np_mod")
        text = self.get("lib/partitor/np_mod.py")
        self.assertIn("import numpy as np", text)
        self.assertNotIn("import re", text)

    def test_script_loses_the_block_and_gets_a_shim(self):
        self.apply("low")
        script = self.get("lib/partitor-engine")
        self.assertNotIn("def double", script)
        self.assertNotIn("class Box", script)
        self.assertIn("from partitor.low import", script)
        shim = script.split("from partitor.low import", 1)[1].split("\n\n", 1)[0]
        for name in ("LIMIT", "double", "Box"):
            self.assertIn(name, shim)
        self.assertIn("def clean", script)                          # other code stays
        self.assertNotIn("\n\n\n\n", script)                        # seams keep two blank lines

    def test_a_lower_module_comes_as_from_import(self):
        self.apply("low")
        self.apply("high")
        text = self.get("lib/partitor/high.py")
        self.assertIn("from .low import double", text)

    def test_r1_name_without_an_edit_is_reported_not_moved(self):
        # `double` is patched by tests (R1): no shim copy, so the script code that reads it
        # is reported until a listed edit makes it `low.double`
        self.put("tests/patchable.txt", "fork_map\ndouble\n")
        rc, out, _ = self.run_tool("low")
        self.assertEqual(rc, 1)
        self.assertIn("R1 names (no shim, use module.NAME): double", out)
        self.assertIn("UNRESOLVED script: uses_double: read double", out)
        rc, _, err = self.run_tool("low", "--apply")
        self.assertEqual(rc, 1)
        self.assertIn("unresolved names", err)
        self.assertFalse(os.path.exists(self.path("lib/partitor/low.py")))

    def test_listed_edits_are_applied_and_checked(self):
        self.put("tests/patchable.txt", "fork_map\ndouble\n")
        self.config({"edits": [
            {"step": "low", "file": "script",
             "old": "    return double(2)\n", "new": "    return low.double(2)\n"},
            {"step": "low", "file": "script",
             "old": "from partitor import VERSION  # noqa: E402\n",
             "new": "from partitor import VERSION  # noqa: E402\nfrom partitor import low  # noqa: E402\n"}]})
        self.apply("low")
        script = self.get("lib/partitor-engine")
        self.assertIn("return low.double(2)", script)
        shim = script.split("from partitor.low import", 1)[1].split("\n\n", 1)[0]
        self.assertNotIn("double", shim)
        self.assertIn("LIMIT", shim)
        rc, out, _ = self.check("low")
        self.assertEqual(rc, 0, out)

    def test_an_edit_that_matches_nowhere_is_refused(self):
        self.config({"edits": [{"step": "low", "file": "low", "old": "nothing like this",
                                "new": "x"}]})
        rc, _, err = self.run_tool("low", "--apply")
        self.assertEqual(rc, 1)
        self.assertIn("expected 1 place(s)", err)
        self.assertFalse(os.path.exists(self.path("lib/partitor/low.py")))


class TestRefusals(Fixture):
    def refused(self, modules, text, symbols=None):
        if symbols:
            with open(self.map, "w", encoding="utf-8") as fh:
                json.dump({"symbols": symbols}, fh)
        before = self.get("lib/partitor-engine")
        rc, out, err = self.run_tool(modules, "--apply")
        self.assertEqual(rc, 1, out + err)
        self.assertIn("REFUSED", err)
        self.assertIn(text, err)
        self.assertEqual(self.get("lib/partitor-engine"), before)            # nothing written
        self.assertFalse(os.path.exists(self.path(f"lib/partitor/{modules.split(',')[0]}.py")))

    def test_missing_symbol(self):
        self.refused("low", "'nothing' is not a top-level name",
                     {"low": ["LIMIT", "nothing"]})

    def test_duplicated_symbol(self):
        self.put("lib/partitor-engine", SCRIPT + "\n\ndef double(x):\n    return x\n")
        self.refused("low", "'double' is bound 2 times")

    def test_conditional_symbol(self):
        body = SCRIPT.replace("LIMIT = 5\n", "try:\n    LIMIT = 5\nexcept OSError:\n    LIMIT = 6\n")
        self.put("lib/partitor-engine", body)
        rc, out, err = self.run_tool("low", "--apply")
        self.assertEqual(rc, 1)
        self.assertIn("not a plain def, class or assignment", err)

    def test_statement_that_binds_a_name_of_another_module(self):
        self.put("lib/partitor-engine", SCRIPT.replace("FLAG = True\n", "FLAG = True\nA, B = 1, 2\n"))
        self.refused("low", "also binds B", {"low": ["A"]})

    def test_name_that_stays_in_the_script(self):
        # `double` uses LIMIT, which is not moved yet: refuse, do not move a second symbol
        self.refused("high", "uses double, which stays in the script",
                     {"high": ["uses_double"]})

    def test_upward_dependency(self):
        self.apply("low")
        self.put("tools/modules.txt", "1 low *\n0 other *\n0 high *\n0 np_mod *\n")
        rc, out, err = self.run_tool("high", "--apply")
        self.assertEqual(rc, 1)
        self.assertIn("upward dependency", err)

    def test_a_module_that_is_not_listed(self):
        with open(self.map, "w", encoding="utf-8") as fh:
            json.dump({"symbols": {"ghost": ["LIMIT"]}}, fh)
        rc, _, err = self.run_tool("ghost", "--apply")
        self.assertEqual(rc, 1)
        self.assertIn("not listed in tools/modules.txt", err)

    def test_a_module_without_a_symbol_list(self):
        rc, _, err = self.run_tool("missing", "--apply")
        self.assertEqual(rc, 2)
        self.assertIn("no symbol list", err)

    def test_second_apply_of_the_same_symbols_is_refused(self):
        self.apply("low")
        before = self.get("lib/partitor-engine")
        rc, _, err = self.run_tool("low", "--apply")
        self.assertEqual(rc, 1)
        self.assertIn("exists already", err)
        self.assertEqual(self.get("lib/partitor-engine"), before)

    def test_global_write_of_a_name_that_is_only_imported_is_flagged(self):
        # `flip` writes FLAG with `global`. Once FLAG moves, the script only imports it, so
        # `flip` would write a new variable and change nothing (the _TTY case). The tool
        # reports the name and does not write; a listed edit (module.NAME) resolves it.
        with open(self.map, "w", encoding="utf-8") as fh:
            json.dump({"symbols": {"low": ["FLAG"]}}, fh)
        rc, out, _ = self.run_tool("low")
        self.assertEqual(rc, 1)
        self.assertIn("UNRESOLVED script: flip: global write of an imported name FLAG", out)
        rc, _, err = self.run_tool("low", "--apply")
        self.assertEqual(rc, 1)
        self.assertFalse(os.path.exists(self.path("lib/partitor/low.py")))
        self.config({"attr": ["FLAG"], "edits": [
            {"step": "low", "file": "script",
             "old": "from partitor import VERSION  # noqa: E402\n",
             "new": "from partitor import VERSION  # noqa: E402\nfrom partitor import low  # noqa: E402\n"},
            {"step": "low", "file": "script",
             "old": "    global FLAG\n    FLAG = False\n", "new": "    low.FLAG = False\n"},
            {"step": "low", "file": "script",
             "old": "len(clean(\"a\")) + FLAG\n", "new": "len(clean(\"a\")) + low.FLAG\n"}]})
        self.apply("low")
        self.assertIn("low.FLAG = False", self.get("lib/partitor-engine"))


class TestCheck(Fixture):
    def test_check_passes_after_apply_and_names_each_module(self):
        self.apply("low")
        self.apply("other")
        rc, out, _ = self.check("low,other")
        self.assertEqual(rc, 0, out)
        self.assertIn("CHECK OK (2 module(s)", out)

    def test_check_fails_when_a_moved_text_is_edited(self):
        self.apply("low")
        path = self.path("lib/partitor/low.py")
        self.put("lib/partitor/low.py", self.get("lib/partitor/low.py").replace("x * 2", "x * 3"))
        rc, out, _ = self.check("low")
        self.assertEqual(rc, 1)
        self.assertIn("CHECK FAILED", out)
        self.assertIn("low.py differs from the original text plus the listed edits", out)
        self.assertTrue(os.path.isfile(path))

    def test_check_fails_when_the_script_lost_something_else(self):
        self.apply("low")
        self.put("lib/partitor-engine",
                 self.get("lib/partitor-engine").replace("def arr():", "def arr2():"))
        rc, out, _ = self.check("low")
        self.assertEqual(rc, 1)
        self.assertIn("script differs from the expected result", out)

    def test_check_needs_the_pristine_script(self):
        rc, _, err = self.run_tool("low", "--check")
        self.assertEqual(rc, 2)
        self.assertIn("--check needs --pristine", err)

    def test_final_edits_are_part_of_the_check(self):
        self.config({"edits": [{"step": "final", "file": "script",
                                "old": "FLAG = True\n", "new": "FLAG = False\n"}]})
        self.apply("low", "--final")
        self.assertIn("FLAG = False", self.get("lib/partitor-engine"))
        self.assertEqual(self.check("low", "--final")[0], 0)
        self.assertEqual(self.check("low")[0], 1)                      # without --final: differs


if __name__ == "__main__":
    unittest.main()
