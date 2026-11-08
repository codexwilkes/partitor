# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""Tests for the engine commands run as a program.

Needs the venv packages (numpy, opencv, pymupdf, PyYAML); without them every test
is skipped. Run with the venv interpreter:

    venv/bin/python3 -m unittest -v tests/test_cli.py

Shared helpers: tests/support.py.
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from support import (  # noqa: E402,F401
    SRC,
    make_score_pdf,
    needs_deps,
    yaml,
    setUpModule,
    tearDownModule,
)


@needs_deps
class TestCommands(unittest.TestCase):
    def run_cli(self, *args):
        # the engine refuses root (a test harness may run as root); these are
        # synthetic PDFs, so the opt-in is safe here
        env = dict(os.environ, PARTITOR_ALLOW_ROOT="1")
        return subprocess.run([sys.executable, SRC, *args], capture_output=True, text=True,
                              env=env)

    def test_plan_is_listed_in_the_help_and_still_runs_its_own_parser(self):
        r = self.run_cli("--help")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertRegex(r.stdout, r"\n\s+plan\s+choose paper")
        r = self.run_cli("plan", "--help")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("usage: partitor plan", r.stdout)             # the plan parser, not the stub

    @staticmethod
    def _undescribed(text):
        """Names of the options and arguments in an argparse help text that
        have no description (a help line is the name, two spaces or a line
        break, then the text)."""
        bare, name = [], None
        for line in text.splitlines():
            if line.startswith("  ") and not line.startswith("   "):
                if name is not None:
                    bare.append(name)
                body = line.strip()
                parts = __import__("re").split(r"\s{2,}", body, maxsplit=1)
                name = None if len(parts) > 1 else parts[0]
            elif name is not None and line.startswith("   ") and line.strip():
                name = None                      # the description wraps to the next line
            elif not line.strip() or not line.startswith(" "):
                if name is not None:
                    bare.append(name)
                name = None
        if name is not None:
            bare.append(name)
        return [b for b in bare if b not in ("-h, --help",)]

    def test_every_command_option_and_argument_has_a_help_text(self):
        top = self.run_cli("--help").stdout
        cmds = __import__("re").search(r"\{([a-z,]+)\}", top).group(1).split(",")
        self.assertIn("analyse", cmds)
        # the sub-commands listed in the top help have a description each
        listed = [l.split()[0] for l in top.split("positional arguments:")[1].splitlines()
                  if l.startswith("    ") and not l.startswith("     ")]
        self.assertEqual(sorted(listed), sorted(cmds), "a command has no help line")
        for cmd in cmds:
            with self.subTest(cmd=cmd):
                r = self.run_cli(cmd, "--help")
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertEqual(self._undescribed(r.stdout), [], cmd)

    def test_analyse_help_names_the_join_options(self):
        out = self.run_cli("analyse", "--help").stdout
        self.assertIn("--join pP:N", out)
        self.assertIn("--unjoin pP:N", out)

    def test_detect_and_build_end_to_end(self):
        with tempfile.TemporaryDirectory() as d:
            pdf = os.path.join(d, "s.pdf")
            make_score_pdf(pdf)
            r = self.run_cli("detect", pdf, "--dpi", "300")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            lay = yaml.safe_load(Path(d, "s.partitor", "layout.yaml").read_text())
            self.assertEqual(lay["parts"], ["Alto", "Tenor", "Bass"])
            self.assertEqual(lay["layout"], {})     # defaults are not frozen in
            self.assertEqual(lay["title"], "Test Chorale")
            self.assertTrue(all("?" not in s["map"] for s in lay["systems"]))
            r = self.run_cli("build", pdf, "--ink", "darker")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            parts = sorted(p.name for p in Path(d, "s.partitor", "parts").iterdir())
            self.assertEqual(parts, ["01-Alto-11x17.pdf", "01-Alto.pdf", "02-Tenor-11x17.pdf",
                                     "02-Tenor.pdf", "03-Bass-11x17.pdf", "03-Bass.pdf"])

    def test_build_refuses_bad_margins(self):
        with tempfile.TemporaryDirectory() as d:
            pdf = os.path.join(d, "s.pdf")
            make_score_pdf(pdf)
            self.assertEqual(self.run_cli("detect", pdf, "--dpi", "200").returncode, 0)
            r = self.run_cli("build", pdf, "--gutter", "30")
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("outer margin", r.stdout + r.stderr)

    def test_build_refuses_question_marks(self):
        with tempfile.TemporaryDirectory() as d:
            pdf = os.path.join(d, "s.pdf")
            make_score_pdf(pdf)
            self.assertEqual(self.run_cli("detect", pdf, "--dpi", "300").returncode, 0)
            lp = Path(d, "s.partitor", "layout.yaml")
            lay = yaml.safe_load(lp.read_text())
            lay["systems"][1]["map"] = ["?", "?", "?"]
            lp.write_text(yaml.safe_dump(lay))
            r = self.run_cli("build", pdf)
            self.assertEqual(r.returncode, 1)
            self.assertIn("map:", r.stdout)

    def test_pieces_lists_pages(self):
        with tempfile.TemporaryDirectory() as d:
            pdf = os.path.join(d, "s.pdf")
            make_score_pdf(pdf)
            r = self.run_cli("pieces", pdf)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("Test Chorale", r.stdout)
            self.assertIn("--pages 1", r.stdout)

    def test_detect_page_range_out_of_bounds(self):
        with tempfile.TemporaryDirectory() as d:
            pdf = os.path.join(d, "s.pdf")
            make_score_pdf(pdf)
            r = self.run_cli("detect", pdf, "--pages", "2-3")
            self.assertEqual(r.returncode, 1)
