# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""Tests for tools/test-parallel.py (the local runner that splits the unit tests over
processes): the split, the weights file, the discovery, and whole runs on small synthetic
test folders (a pass, a failure, a process that dies, a file that does not import).
The real suite is not run here.

Run: python3 -m unittest -v tests/test_parallel_runner.py
"""
import contextlib
import importlib.util
import io
import os
import tempfile
import textwrap
import unittest
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = Path(HERE).parent
TOOL = ROOT / "tools" / "test-parallel.py"

spec = importlib.util.spec_from_file_location("test_parallel_tool", TOOL)
tp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tp)

PASSING = """
import unittest
class TestA(unittest.TestCase):
    def test_one(self): pass
    def test_two(self): pass
class TestB(unittest.TestCase):
    def test_three(self): pass
"""
FAILING = """
import unittest
class TestC(unittest.TestCase):
    def test_bad(self): self.fail("boom")
    def test_good(self): pass
"""
DYING = """
import os, unittest
class TestD(unittest.TestCase):
    def test_exit(self): os._exit(3)
"""
BROKEN = "import module_that_does_not_exist\n"


def make_root(files, weights=None):
    """A temp repo root with tests/<name>.py from the dict `files`; returns (TemporaryDirectory, Path)."""
    tmp = tempfile.TemporaryDirectory(prefix="tp-test-")
    root = Path(tmp.name)
    (root / "tests").mkdir()
    (root / "tools").mkdir()
    for name, text in files.items():
        (root / "tests" / name).write_text(textwrap.dedent(text), encoding="utf-8")
    if weights is not None:
        (root / "tools" / "test-weights.txt").write_text(weights, encoding="utf-8")
    return tmp, root


def run_tool(root, jobs):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = tp.run(root, jobs)
    return rc, buf.getvalue()


class TestSplit(unittest.TestCase):
    COUNTS = {"a.A": 10, "a.B": 4, "b.C": 3, "c.D": 1, "c.E": 1}
    WEIGHTS = {"a.A": 100.0, "a.B": 40.0, "b.C": 30.0, "c.D": 5.0}

    def test_every_class_is_in_exactly_one_bin(self):
        for jobs in (1, 2, 3, 4, 9):
            bins = tp.split(self.COUNTS, self.WEIGHTS, jobs)
            flat = [m for b in bins for m in b]
            self.assertEqual(sorted(flat), sorted(self.COUNTS), jobs)

    def test_bins_are_balanced_and_the_heaviest_class_is_alone(self):
        bins = tp.split(self.COUNTS, self.WEIGHTS, 2)
        self.assertEqual(bins[0], ["a.A"])
        self.assertEqual(sorted(bins[1]), ["a.B", "b.C", "c.D", "c.E"])

    def test_more_jobs_than_classes_drops_empty_bins(self):
        bins = tp.split(self.COUNTS, self.WEIGHTS, 9)
        self.assertEqual(len(bins), len(self.COUNTS))
        self.assertTrue(all(bins))

    def test_a_class_without_weight_counts_a_twentieth_of_a_second_per_test(self):
        # c.E has 1 test and no weight: 0.05 s, so it goes after the weighted ones
        bins = tp.split({"x.X": 1, "x.Y": 100}, {"x.X": 1.0}, 2)
        self.assertEqual(bins, [["x.Y"], ["x.X"]])      # 100 tests = 5.0 s > 1.0 s

    def test_the_split_is_the_same_every_time(self):
        self.assertEqual(tp.split(self.COUNTS, self.WEIGHTS, 3),
                         tp.split(dict(reversed(list(self.COUNTS.items()))), self.WEIGHTS, 3))


class TestWeights(unittest.TestCase):
    def test_read_weights_skips_comments_and_blank_lines(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d, "w.txt")
            p.write_text("# SPDX\n\nm.A 12.5\nm.B 3  # note\nbad line here\n", encoding="utf-8")
            self.assertEqual(tp.read_weights(p), {"m.A": 12.5, "m.B": 3.0})

    def test_a_missing_file_gives_no_weights(self):
        self.assertEqual(tp.read_weights(Path("/nonexistent/weights.txt")), {})

    def test_the_weights_file_of_the_repo_is_well_formed(self):
        w = tp.read_weights(ROOT / "tools" / "test-weights.txt")
        self.assertGreater(len(w), 50)
        self.assertTrue(all("." in k and v > 0 for k, v in w.items()))


class TestDiscover(unittest.TestCase):
    def test_counts_per_class(self):
        tmp, root = make_root({"test_p.py": PASSING})
        with tmp:
            counts, broken = tp.discover(root)
        self.assertEqual(counts, {"test_p.TestA": 2, "test_p.TestB": 1})
        self.assertEqual(broken, [])

    def test_a_file_that_does_not_import_is_reported(self):
        tmp, root = make_root({"test_p.py": PASSING, "test_x.py": BROKEN})
        with tmp:
            counts, broken = tp.discover(root)
        self.assertEqual(len(broken), 1)
        self.assertIn("test_x", broken[0])


class TestRun(unittest.TestCase):
    def test_a_passing_run_counts_every_test(self):
        tmp, root = make_root({"test_p.py": PASSING})
        with tmp:
            rc, out = run_tool(root, 2)
        self.assertEqual(rc, 0, out)
        self.assertIn("Ran 3 tests in", out)
        self.assertIn("\nOK", out)
        self.assertIn("peak memory use", out)

    def test_a_failing_test_fails_the_run_and_shows_its_text(self):
        tmp, root = make_root({"test_p.py": PASSING, "test_f.py": FAILING})
        with tmp:
            rc, out = run_tool(root, 2)
        self.assertEqual(rc, 1)
        self.assertIn("Ran 5 tests in", out)
        self.assertIn("boom", out)
        self.assertIn("FAILED", out)
        self.assertNotIn("\nOK", out)

    def test_a_process_that_dies_fails_the_run(self):
        tmp, root = make_root({"test_p.py": PASSING, "test_d.py": DYING})
        with tmp:
            rc, out = run_tool(root, 2)
        self.assertEqual(rc, 1)
        self.assertIn("died", out)
        self.assertIn("FAILED", out)

    def test_a_file_that_does_not_import_fails_before_any_test_runs(self):
        tmp, root = make_root({"test_p.py": PASSING, "test_x.py": BROKEN})
        with tmp:
            rc, out = run_tool(root, 2)
        self.assertEqual(rc, 1)
        self.assertIn("does not import", out)
        self.assertNotIn("Ran ", out)

    def test_a_lost_test_fails_the_run(self):
        # a split that drops a class: the count that ran differs from discovery
        tmp, root = make_root({"test_p.py": PASSING})
        real = tp.split
        try:
            tp.split = lambda counts, weights, jobs: real(
                {k: v for k, v in counts.items() if k != "test_p.TestB"}, weights, jobs)
            with tmp:
                rc, out = run_tool(root, 2)
        finally:
            tp.split = real
        self.assertEqual(rc, 1)
        self.assertIn("discovery finds 3 tests, 2 ran", out)

    def test_one_job_runs_everything_in_one_process(self):
        tmp, root = make_root({"test_p.py": PASSING})
        with tmp:
            rc, out = run_tool(root, 1)
        self.assertEqual(rc, 0, out)
        self.assertEqual(out.count("process "), 1)

    def test_jobs_below_one_is_an_error(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            tp.main(["--jobs", "0"])


class TestDocs(unittest.TestCase):
    def test_the_runner_is_named_where_the_gate_is_described(self):
        for rel in ("CONTRIBUTING.md", "docs/DESIGN.md"):
            text = (ROOT / rel).read_text(encoding="utf-8")
            self.assertIn("tools/test-parallel.py", text, rel)


if __name__ == "__main__":
    unittest.main()
