# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""docs/ARCHITECTURE.md is checked against the code by tools/check-architecture.py."""
from __future__ import annotations

import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("check_architecture", ROOT / "tools" / "check-architecture.py")
ca = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ca)


class ArchitectureTest(unittest.TestCase):
    def test_the_document_is_current(self):
        r = subprocess.run([sys.executable, "-I", str(ROOT / "tools" / "check-architecture.py")], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_every_existing_module_is_in_the_generated_block_at_its_level(self):
        text = (ROOT / "docs" / "ARCHITECTURE.md").read_text(encoding="utf-8")
        block = text.split(ca.BEGIN)[1].split(ca.END)[0]
        for lvl, name in ca.modules(ROOT):
            sub = re.search(rf'subgraph L{lvl}\["Level {lvl}"\](.*?)\n  end', block, re.S)
            self.assertIsNotNone(sub, f"level {lvl}")
            self.assertIn(f'{name}["{name}"]', sub.group(1), name)
        listed = {n for _, n in ca.modules(ROOT)}
        files = {p.stem for p in (ROOT / "lib" / "partitor").glob("*.py") if p.stem not in ("__init__", "__main__")}
        self.assertEqual(files, listed)

    def test_the_document_has_the_three_hand_written_diagrams(self):
        text = (ROOT / "docs" / "ARCHITECTURE.md").read_text(encoding="utf-8")
        self.assertGreaterEqual(len(list(ca.mermaid_blocks(text))), 4)

    def _doc(self, body):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, True)
        (d / "tools").mkdir()
        (d / "lib" / "partitor").mkdir(parents=True)
        (d / "docs").mkdir()
        (d / "bin").mkdir()
        (d / "bin" / "partitor").write_text("x")
        (d / "tools" / "modules.txt").write_text("0 alpha x\n1 beta x\n2 gone x\n")
        for n in ("alpha", "beta"):
            (d / "lib" / "partitor" / f"{n}.py").write_text("x")
        doc = d / "docs" / "ARCHITECTURE.md"
        doc.write_text(f"{body}\n{ca.BEGIN}\n{ca.generated(d)}\n{ca.END}\n")
        return d, doc

    def test_a_clean_document_passes_and_a_planned_module_is_skipped(self):
        d, doc = self._doc("```mermaid\nflowchart TB\n  a[\"bin/partitor: x\"]\n```".replace("a[", "a["))
        self.assertEqual(ca.check(d, doc), [])
        self.assertNotIn("gone", doc.read_text())

    def test_a_new_module_makes_the_block_old(self):
        d, doc = self._doc("text")
        (d / "lib" / "partitor" / "gone.py").write_text("x")
        self.assertTrue(any("generated module-level block is old" in e for e in ca.check(d, doc)))

    def test_syntax_outside_the_subset_fails_with_the_line(self):
        d, doc = self._doc("```mermaid\nflowchart TB\n  a[\"x\"]\n  click a href \"u\"\n```")
        e = ca.check(d, doc)
        self.assertEqual(len(e), 1)
        self.assertIn("ARCHITECTURE.md:4: not in the drawable subset", e[0])

    def test_unbalanced_subgraph_and_missing_flowchart_line_fail(self):
        d, doc = self._doc("```mermaid\nflowchart TB\n  subgraph s[\"S\"]\n  a[\"x\"]\n```")
        self.assertTrue(any("has no `end`" in e for e in ca.check(d, doc)))
        d, doc = self._doc("```mermaid\ngraph TD\n  a[\"x\"]\n```")
        self.assertTrue(any("starts with `flowchart" in e for e in ca.check(d, doc)))

    def test_a_path_that_does_not_exist_fails_in_text_and_in_a_label(self):
        d, doc = self._doc("See `lib/nothing.py`.\n```mermaid\nflowchart TB\n  a[\"bin/missing: x\"]\n```")
        e = " ".join(ca.check(d, doc))
        self.assertIn("`lib/nothing.py` does not exist", e)
        self.assertIn("bin/missing in the label does not exist", e)

    def test_check_repo_runs_the_check(self):
        self.assertIn("check-architecture.py", (ROOT / "tools" / "check-repo.sh").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
