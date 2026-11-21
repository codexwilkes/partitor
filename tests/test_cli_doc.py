# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""docs/COMMANDS.md and docs/cli.json are generated from the code (tools/build-cli-doc.py)."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
from partitor import cli_main  # noqa: E402


def read(*p):
    with open(os.path.join(ROOT, *p), encoding="utf-8") as f:
        return f.read()


class CliDocTest(unittest.TestCase):
    def test_generated_files_are_current(self):
        r = subprocess.run([sys.executable, "-I", os.path.join(ROOT, "tools", "build-cli-doc.py"), "--check"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_json_lists_every_command_of_the_parser(self):
        import argparse
        p = cli_main.build_parser()
        sub = next(a for a in p._actions if isinstance(a, argparse._SubParsersAction))
        d = json.loads(read("docs", "cli.json"))
        self.assertEqual([c["name"] for c in d["commands"]], list(sub.choices))
        self.assertEqual(d["version"], read("VERSION").strip())

    def test_plan_has_its_own_options(self):
        d = json.loads(read("docs", "cli.json"))
        plan = next(c for c in d["commands"] if c["name"] == "plan")
        flags = {f for a in plan["args"] for f in a["flags"]}
        self.assertTrue({"--group", "--all"} <= flags, flags)

    def test_every_option_is_in_the_reference(self):
        d = json.loads(read("docs", "cli.json"))
        md = read("docs", "COMMANDS.md")
        for c in d["commands"]:
            self.assertIn(f"## `partitor {c['name']}`", md)
            for a in c["args"]:
                for f in a["flags"]:
                    self.assertIn(f"`{f}`", md, f"{c['name']} {f}")

    def test_menu_keys_are_exported(self):
        d = json.loads(read("docs", "cli.json"))
        self.assertGreaterEqual(len(d["menu_keys"]), 15)
        self.assertIn("r", d["menu_keys"])

    def test_one_version(self):
        ver = read("VERSION").strip()
        self.assertEqual(re.search(r'^VERSION = "(.*)"', read("lib", "partitor", "__init__.py"), re.M).group(1), ver)
        for doc in (("README.md",), ("docs", "INSTALL.md")):
            m = re.search(r"git checkout --detach (\S+)", read(*doc))
            self.assertEqual(m and m.group(1), ver, doc)
        m = re.search(r"^## (\S+) — ", read("CHANGELOG.md"), re.M)
        self.assertEqual(m and m.group(1), ver)

    def test_check_repo_checks_the_version(self):
        t = read("tools", "check-repo.sh")
        self.assertIn("git checkout --detach", t)
        self.assertIn("build-cli-doc.py --check", t)


if __name__ == "__main__":
    unittest.main()
