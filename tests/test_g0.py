# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""Tests for the run control of tools/g0_golden.py: the timing table, the order in which cases
start, and the default number of workers. The cases themselves (the engine runs) are not run here.
They need the golden files and take minutes.

Run: python3 -m unittest -v tests/test_g0.py
"""
import importlib.util
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, "..", "tools", "g0_golden.py")

try:
    import pymupdf  # noqa: F401
    import yaml  # noqa: F401
    HAVE_DEPS = True
except ImportError:                      # pragma: no cover
    HAVE_DEPS = False


def load_tool():
    spec = importlib.util.spec_from_file_location("g0_golden", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@unittest.skipUnless(HAVE_DEPS, "pymupdf or yaml missing")
class TestG0RunControl(unittest.TestCase):
    def setUp(self):
        self.g0 = load_tool()

    def test_timed_stores_the_seconds_and_returns_the_result(self):
        sink = {}
        self.assertEqual(self.g0.timed("a", lambda: 7, sink), 7)
        self.assertIn("a", sink)
        self.assertGreaterEqual(sink["a"], 0.0)

    def test_timed_stores_the_seconds_when_the_case_raises(self):
        sink = {}

        def boom():
            raise ValueError("x")
        with self.assertRaises(ValueError):
            self.g0.timed("b", boom, sink)
        self.assertIn("b", sink)

    def test_timing_table_is_slowest_first_with_a_sum_line(self):
        lines = self.g0.format_timings({"fast": 1.0, "slow": 30.0, "mid": 5.0}, 18.0)
        self.assertEqual([l.split()[-1] for l in lines[:3]], ["slow", "mid", "fast"])
        self.assertIn("sum of 3 cases", lines[-1])
        self.assertIn("wall 18.0 s", lines[-1])
        self.assertIn("2.0 at once", lines[-1])

    def test_timing_table_ties_are_ordered_by_name(self):
        lines = self.g0.format_timings({"b": 1.0, "a": 1.0}, 2.0)
        self.assertEqual([l.split()[-1] for l in lines[:2]], ["a", "b"])

    def test_timing_table_with_zero_wall_time_does_not_divide(self):
        self.assertIn("0.0 at once", self.g0.format_timings({"a": 1.0}, 0.0)[-1])

    def test_slow_cases_start_first_and_keep_their_order(self):
        names = ["help:main", "build:base", "build:long-default", "lib:session",
                 "build:long-duplex", "pieces:multi", "lib:reduced"]
        got = [n for n, _ in self.g0.order_cases([(n, None) for n in names])]
        self.assertEqual(got, ["build:long-default", "lib:session", "build:long-duplex",
                               "lib:reduced", "help:main", "build:base", "pieces:multi"])

    def test_order_keeps_every_case_once(self):
        cases = [(f"c{i}", i) for i in range(5)] + [("lib:x", 9)]
        self.assertEqual(sorted(self.g0.order_cases(cases)), sorted(cases))

    def test_default_workers_is_four_and_the_help_says_so(self):
        self.assertEqual(self.g0.DEFAULT_WORKERS, 4)
        self.assertIn("--workers N     cases run in parallel (default 4)", self.g0.__doc__)
        self.assertIn("--timings", self.g0.__doc__)


if __name__ == "__main__":
    unittest.main()
