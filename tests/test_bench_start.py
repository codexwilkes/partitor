# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""Tests for tools/bench-start.sh. A temporary tree holds a copy of the script and a
stub venv python, so the run is fast and needs no package.

Run: python3 -m unittest -v tests/test_bench_start.py
"""
import os
import re
import shutil
import stat
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
SCRIPT = os.path.join(ROOT, "tools", "bench-start.sh")


class TestBenchStart(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pt-bench-")
        os.makedirs(os.path.join(self.tmp, "tools"))
        os.makedirs(os.path.join(self.tmp, "venv", "bin"))
        os.makedirs(os.path.join(self.tmp, "lib"))
        self.script = os.path.join(self.tmp, "tools", "bench-start.sh")
        shutil.copy(SCRIPT, self.script)
        self.py = os.path.join(self.tmp, "venv", "bin", "python")
        with open(self.py, "w", encoding="utf-8") as fh:
            fh.write("#!/bin/sh\necho \"$@\" > \"$(dirname \"$0\")/args\"\nexit 0\n")
        os.chmod(self.py, 0o755)
        open(os.path.join(self.tmp, "lib", "partitor-engine"), "w").close()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_b(self, *args):
        return subprocess.run(["bash", self.script, *args], capture_output=True, text=True)

    def test_script_is_executable_and_parses(self):
        self.assertTrue(os.stat(SCRIPT).st_mode & stat.S_IXUSR)
        self.assertEqual(subprocess.run(["bash", "-n", SCRIPT]).returncode, 0)

    def test_prints_each_run_and_the_median_and_nothing_else(self):
        r = self.run_b("4")
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = r.stdout.splitlines()
        self.assertEqual(len(lines), 5, r.stdout)
        for i, line in enumerate(lines[:4], 1):
            self.assertRegex(line, rf"^run {i}: \d+\.\d{{3}} s$")
        self.assertRegex(lines[4], r"^median: \d+\.\d{3} s$")
        with open(os.path.join(self.tmp, "venv", "bin", "args"), encoding="utf-8") as fh:
            self.assertEqual(fh.read().split(), [os.path.join(self.tmp, "lib", "partitor-engine"),
                                                 "--version"])

    def test_default_is_five_runs(self):
        r = self.run_b()
        self.assertEqual(len(re.findall(r"^run \d+:", r.stdout, re.M)), 5)

    def test_median_lies_between_the_smallest_and_the_largest_run(self):
        r = self.run_b("3")
        runs = [float(x) for x in re.findall(r"^run \d+: ([\d.]+) s$", r.stdout, re.M)]
        median = float(re.search(r"^median: ([\d.]+) s$", r.stdout, re.M).group(1))
        self.assertEqual(median, sorted(runs)[1])

    def test_bad_count_is_a_usage_error(self):
        for bad in ("0", "-1", "x", "2.5"):
            with self.subTest(arg=bad):
                r = self.run_b(bad)
                self.assertEqual(r.returncode, 2)
                self.assertEqual(r.stdout, "")

    def test_missing_venv_python_fails(self):
        os.remove(self.py)
        r = self.run_b("1")
        self.assertEqual(r.returncode, 1)
        self.assertIn("no venv python", r.stderr)


if __name__ == "__main__":
    unittest.main()
