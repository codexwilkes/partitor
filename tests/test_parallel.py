# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""Tests for fork_map and the part selection.

Needs the venv packages (numpy, opencv, pymupdf, PyYAML); without them every test
is skipped. Run with the venv interpreter:

    venv/bin/python3 -m unittest -v tests/test_parallel.py

Shared helpers: tests/support.py.
"""
import contextlib
import io
import os
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from support import (  # noqa: E402,F401
    cv2,
    needs_deps,
    np,
    pt,
    setUpModule,
    tearDownModule,
)


@needs_deps
class TestSelection(unittest.TestCase):
    """rebuild <id> [parts]: which parts and groups a build is asked for."""

    DATA = {"parts": ["Canto", "Alto", "Tenor", "Bass Trombone", "Continuo"],
            "skip": ["Continuo"], "groups": {"Trombones": ["Tenor", "Bass Trombone"]}}

    def p(self, *words):
        return pt.parse_parts(self.DATA, list(words))

    def test_numbers_ranges_and_names(self):
        # numbers are those of the part files and of `show`: parts, then groups
        self.assertEqual(self.p("6"), ["Trombones"])
        self.assertEqual(self.p("2-3"), ["Alto", "Tenor"])
        self.assertEqual(self.p("3,1"), ["Canto", "Tenor"])              # file order, once each
        self.assertEqual(self.p("trombones"), ["Trombones"])
        self.assertEqual(self.p("Bass", "Trombone", "Alto"), ["Alto", "Bass Trombone"])
        self.assertEqual(self.p("Can"), ["Canto"])                         # a start no other name has
        self.assertEqual(self.p("Alto", "2"), ["Alto"])

    def test_all_and_everything_are_a_full_build(self):
        self.assertIsNone(self.p("all"))
        self.assertIsNone(self.p("1-4", "Trombones"))

    def test_errors_name_the_problem(self):
        for words, text in ((("7",), "no part number 7"), (("Tenorr",), "no part or group"),
                            (("T",), "more than one"), (("5",), "not extracted"),
                            (("4-2",), "backwards"), ((), "no part named")):
            with self.subTest(words=words):
                with self.assertRaises(ValueError) as cm:
                    self.p(*words)
                self.assertIn(text, str(cm.exception))

    def test_numbers_keep_not_extracted_parts(self):
        d = {**self.DATA, "skip": ["Alto"]}
        self.assertEqual(pt.parse_parts(d, ["3"]), ["Tenor"])             # NN as in the file name
        self.assertIn("2 Alto (not extracted)", pt.selection_help(d))
        self.assertIn("6 Trombones (group)", pt.selection_help(d))

    def test_job_count(self):
        env = dict(os.environ)
        try:
            os.environ["PARTITOR_MEMORY_MAX"] = "8G"
            os.environ.pop("PARTITOR_JOBS", None)
            cpus = (len(os.sched_getaffinity(0))
                    if hasattr(os, "sched_getaffinity")
                    else (os.cpu_count() or 1))
            self.assertEqual(pt.job_count(None, 1.5, 1), 1)                  # one item: no workers
            self.assertEqual(pt.job_count("3", 1.5, 10), 3)                  # a number is taken as it is
            self.assertEqual(pt.job_count("9", 1.5, 4), 4)                   # never more than the items
            self.assertEqual(pt.job_count("1", 1.5, 10), 1)
            self.assertEqual(pt.job_count(None, 1.5, 10), max(1, min(cpus - 1, 4)))   # (8-2)/1.5
            os.environ["PARTITOR_MEMORY_MAX"] = "3G"
            self.assertEqual(pt.job_count("auto", 1.5, 10), 1)               # the cap holds one
            os.environ["PARTITOR_JOBS"] = "2"
            self.assertEqual(pt.job_count(None, 1.5, 10), 2)
            self.assertEqual(pt.parse_size("1500M"), 1500 * 1024 ** 2)
            self.assertIsNone(pt.parse_size("infinity"))
        finally:
            os.environ.clear()
            os.environ.update(env)


@needs_deps
class TestForkMap(unittest.TestCase):
    """Workers: order, replayed output, failures."""

    def run_map(self, fn, items, jobs):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            out = list(pt.fork_map(fn, items, jobs))
        return out, buf.getvalue()

    def setUp(self):
        self.counts = dict(pt._counts)

    def tearDown(self):
        pt._reset_counts()

    def test_results_in_order_with_their_output_and_counts(self):
        def fn(i):
            time.sleep(0.05 * (4 - i))            # the last item ends first
            pt._ok(f"item {i}")
            if i == 2:
                pt._warn("two")
            return i * i
        pt._reset_counts()
        out, text = self.run_map(fn, range(4), 3)
        self.assertEqual(out, [0, 1, 4, 9])
        self.assertEqual([l.split()[-1] for l in text.splitlines()], ["0", "1", "2", "two", "3"])
        self.assertEqual((pt._counts["pass"], pt._counts["warn"]), (4, 1))
        self.assertEqual(pt._WARNINGS, ["two"])

    def test_children_work_after_the_parent_used_opencv_threads(self):
        # A fork copies OpenCV's thread pool without its threads: a child that
        # then used OpenCV waited for ever once (cv2 setNumThreads in the child
        # of a process that had analysed before). Timing decides, so this is a
        # guard, not a proof; fork_map stops the pool in the parent before it forks.
        import signal as sg
        img = (np.random.rand(3000, 3000) * 255).astype(np.uint8)
        cv2.setNumThreads(4)
        expected_threads = cv2.getNumThreads()
        cv2.GaussianBlur(img, (0, 0), 3)                  # the parent starts the pool

        def fn(i):
            return int(cv2.GaussianBlur(img, (0, 0), 3).sum() % 7) + i * 0

        def late(*_):
            raise AssertionError("worker hangs")
        sg.signal(sg.SIGALRM, late)
        sg.alarm(60)
        try:
            out, _ = self.run_map(fn, range(3), 2)
        finally:
            sg.alarm(0)
        self.assertEqual(len(out), 3)
        self.assertEqual(cv2.getNumThreads(), expected_threads)  # pool size restored to what this build accepted

    def test_one_job_runs_here(self):
        pid = os.getpid()
        out, _ = self.run_map(lambda i: os.getpid() == pid, range(3), 1)
        self.assertEqual(out, [True] * 3)
        out, _ = self.run_map(lambda i: os.getpid() == pid, range(3), 2)
        self.assertEqual(out, [False] * 3)

    def test_a_failing_worker_raises_with_its_traceback(self):
        def fn(i):
            if i == 1:
                raise KeyError("boom")
            return i
        with self.assertRaises(RuntimeError) as cm:
            self.run_map(fn, range(3), 2)
        self.assertIn("KeyError", str(cm.exception))
        self.assertIn("item 2 of 3", str(cm.exception))

    def test_die_in_a_worker_ends_the_run(self):
        def fn(i):
            if i == 1:
                raise SystemExit(1)
            return i
        with self.assertRaises(SystemExit):
            self.run_map(fn, range(3), 2)

    def test_a_killed_worker_is_named(self):
        def fn(i):
            if i == 1:
                os.kill(os.getpid(), 9)
            return i
        with self.assertRaises(RuntimeError) as cm:
            self.run_map(fn, range(3), 2)
        self.assertIn("killed by SIGKILL", str(cm.exception))
        self.assertIn("PARTITOR_MEMORY_MAX", str(cm.exception))

    def test_closing_early_stops_the_workers_and_cleans_up(self):
        def tmp_dirs():
            return {d for d in os.listdir(tempfile.gettempdir()) if d.startswith("partitor-")}
        before = tmp_dirs()
        t = time.monotonic()
        with contextlib.redirect_stdout(io.StringIO()):
            gen = pt.fork_map(lambda i: i if i == 0 else (time.sleep(30), i)[1], range(3), 2)
            self.assertEqual(next(gen), 0)
            gen.close()                      # item 1 still sleeps: its worker is stopped
        self.assertLess(time.monotonic() - t, 5)
        self.assertEqual(tmp_dirs(), before)
