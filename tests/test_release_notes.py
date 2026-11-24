# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""tools/release-notes.py and .github/workflows/release.yml."""
from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import re
import tempfile
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_spec = importlib.util.spec_from_file_location("release_notes", os.path.join(ROOT, "tools", "release-notes.py"))
rn = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rn)

LOG = """# Changelog

## 0.19.0-beta.1 — 2026-12-01

### Added
- A beta thing.

## 0.18.5 — 2026-11-24

### Fixed
- A fix.

- Second line.

## 0.18.4 — 2026-11-24

### Changed
- Old.
"""


class Extract(unittest.TestCase):
    def test_section_without_heading_and_neighbours(self):
        out = rn.notes("0.18.5", LOG, "0.18.5\n")
        self.assertEqual(out, "### Fixed\n- A fix.\n\n- Second line.\n")

    def test_last_section_runs_to_the_end(self):
        self.assertEqual(rn.notes("0.18.4", LOG), "### Changed\n- Old.\n")

    def test_suffix_version(self):
        self.assertIn("A beta thing.", rn.notes("0.19.0-beta.1", LOG, "0.19.0-beta.1"))

    def test_prefix_of_another_version_does_not_match(self):
        with self.assertRaises(ValueError):
            rn.notes("0.18", LOG)
        with self.assertRaises(ValueError):
            rn.notes("0.18.50", LOG)

    def test_missing_heading(self):
        with self.assertRaisesRegex(ValueError, "no heading"):
            rn.notes("0.18.9", LOG)

    def test_empty_section(self):
        with self.assertRaisesRegex(ValueError, "empty"):
            rn.notes("0.1.0", "## 0.1.0 — 2026-01-01\n\n## 0.0.9 — 2025-12-01\n- x\n")

    def test_not_a_version(self):
        for bad in ("v0.18.5", "latest", "0.18", ""):
            with self.assertRaises(ValueError):
                rn.notes(bad, LOG)

    def test_version_file_must_equal_tag(self):
        with self.assertRaisesRegex(ValueError, "VERSION"):
            rn.notes("0.18.5", LOG, "0.18.4\n")


class Cli(unittest.TestCase):
    def run_main(self, tag, log, ver):
        with tempfile.TemporaryDirectory() as d:
            c, v = os.path.join(d, "CHANGELOG.md"), os.path.join(d, "VERSION")
            for p, t in ((c, log), (v, ver)):
                with open(p, "w", encoding="utf-8") as f:
                    f.write(t)
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                rc = rn.main([tag, "--changelog", c, "--version-file", v])
        return rc, out.getvalue(), err.getvalue()

    def test_ok(self):
        rc, out, err = self.run_main("0.18.5", LOG, "0.18.5\n")
        self.assertEqual((rc, err), (0, ""))
        self.assertTrue(out.startswith("### Fixed"))

    def test_error_exit_code_and_message(self):
        rc, out, err = self.run_main("0.18.9", LOG, "0.18.9\n")
        self.assertEqual((rc, out), (1, ""))
        self.assertIn("release-notes:", err)

    def test_the_real_changelog_has_the_section_of_VERSION(self):
        with open(os.path.join(ROOT, "VERSION"), encoding="utf-8") as f:
            ver = f.read().strip()
        with open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8") as f:
            self.assertTrue(rn.notes(ver, f.read(), ver).strip())


class Workflow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(os.path.join(ROOT, ".github", "workflows", "release.yml"), encoding="utf-8") as f:
            cls.wf = f.read()

    def test_starts_only_after_ci(self):
        self.assertIn("workflow_run:", self.wf)
        self.assertIn("workflows: [ci]", self.wf)
        self.assertIn("conclusion == 'success'", self.wf)
        self.assertNotRegex(self.wf, r"(?m)^\s+(push|pull_request|schedule):")

    def test_release_is_a_draft_and_never_replaced(self):
        self.assertIn("--draft", self.wf)
        self.assertIn("--verify-tag", self.wf)
        self.assertIn("--prerelease", self.wf)
        self.assertIn("gh release view", self.wf)
        self.assertNotIn("--clobber", self.wf)
        self.assertNotIn("delete", self.wf.replace("# ", ""))

    def test_actions_are_pinned_and_use_the_notes_tool(self):
        for m in re.finditer(r"uses:\s*(\S+)", self.wf):
            self.assertRegex(m.group(1), r"@v\d+")
        self.assertIn("tools/release-notes.py", self.wf)


if __name__ == "__main__":
    unittest.main()
