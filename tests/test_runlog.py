# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""Tests for the run log (lib/partitor/runlog.py, docs/DESIGN.md §12.5).

    venv/bin/python3 -m unittest -v tests/test_runlog.py
"""
import contextlib
import glob
import io
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from support import LIB, SRC, setUpModule, tearDownModule  # noqa: E402,F401

if LIB not in sys.path:
    sys.path.insert(0, LIB)
from partitor import console, runlog  # noqa: E402


class TestRunLog(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="pt-runlog-")
        self.addCleanup(lambda: __import__("shutil").rmtree(self.dir, ignore_errors=True))
        self.out, self.err = io.StringIO(), io.StringIO()
        self.addCleanup(runlog.finish, "cleanup")           # a failed test must not leave the tee
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(contextlib.redirect_stdout(self.out))
        stack.enter_context(contextlib.redirect_stderr(self.err))

    def log(self):
        files = glob.glob(os.path.join(self.dir, "run-*.log"))
        self.assertEqual(len(files), 1, files)
        with open(files[0], encoding="utf-8") as fh:
            return fh.read()

    def start(self, **env):
        with mock.patch.dict(os.environ, {runlog.LOG_ENV: self.dir, **env}):
            runlog.start(["list", "x"])

    def test_off_without_the_variable(self):
        with mock.patch.dict(os.environ):
            os.environ.pop(runlog.LOG_ENV, None)
            before = sys.stdout
            runlog.start(["list"])
            self.assertIs(sys.stdout, before)
            print("hello")
            runlog.finish(0)
        self.assertEqual(os.listdir(self.dir), [])
        self.assertEqual(self.out.getvalue(), "hello\n")

    def test_header_output_without_colour_and_exit_code(self):
        self.start(PARTITOR_JOBS="3")
        console._head("Step one")
        console._ok("page 1 found")
        print("\033[0;33m⚠\033[0m  warned", file=sys.stderr)
        runlog.finish(7)
        text = self.log()
        self.assertIn("partitor ", text)
        self.assertIn("args: list x", text)
        self.assertIn("cwd: ", text)
        self.assertIn("env: PARTITOR_JOBS=3", text)
        self.assertIn(" out ", text)
        self.assertIn("══ Step one", text)
        self.assertIn("✔  page 1 found", text)
        self.assertRegex(text, r"err +⚠  warned\n")
        self.assertNotIn("\033", text)
        self.assertTrue(text.rstrip().endswith("exit: 7"), text)
        self.assertRegex(text, r"^ +\d+\.\ds log ")

    def test_screen_output_is_unchanged_and_streams_come_back(self):
        before = (sys.stdout, sys.stderr)
        self.start()
        print("a line")
        print("an error", file=sys.stderr)
        runlog.finish(0)
        self.assertEqual((sys.stdout, sys.stderr), before)
        self.assertEqual(self.out.getvalue(), "a line\n")
        self.assertEqual(self.err.getvalue(), "an error\n")

    def test_a_progress_line_keeps_its_last_state(self):
        self.start()
        sys.stdout.write("\r  · page 1/9\033[K\r  · page 2/9\033[K\r\033[K")
        print("done")
        runlog.finish(0)
        text = self.log()
        self.assertIn("done", text)
        self.assertNotIn("page 1/9", text)

    def test_prompt_and_answer_are_logged(self):
        self.start()
        with mock.patch("builtins.input", side_effect=lambda p: (sys.stdout.write(p), "Quartet")[1]):
            self.assertEqual(console.ask("Title", "Piece"), "Quartet")
        print("after")
        runlog.finish(0)
        text = self.log()
        self.assertRegex(text, r"in +Title -> 'Quartet'")
        self.assertRegex(text, r"out +Title \[Piece\]:")
        self.assertLess(text.index("Title [Piece]:"), text.index("-> 'Quartet'"))
        self.assertEqual(console._ANSWER_LOG, [])

    def test_unwritable_folder_stops_nothing(self):
        missing = os.path.join(self.dir, "no", "such")
        with mock.patch.dict(os.environ, {runlog.LOG_ENV: missing}):
            before = sys.stdout
            runlog.start(["list"])
            self.assertIs(sys.stdout, before)
        self.assertIn("run log off", self.err.getvalue())
        runlog.finish(0)

    def test_crash_writes_the_traceback(self):
        self.start()
        try:
            raise ValueError("bad page")
        except ValueError:
            runlog.crash()
        runlog.finish("exception")
        text = self.log()
        self.assertRegex(text, r"err +Traceback")
        self.assertIn("ValueError: bad page", text)
        self.assertTrue(text.rstrip().endswith("exit: exception"))

    def test_two_runs_two_files(self):
        self.start()
        runlog.finish(0)
        with mock.patch("os.getpid", return_value=424242):
            self.start()
        runlog.finish(0)
        self.assertEqual(len(glob.glob(os.path.join(self.dir, "run-*.log"))), 2)


class TestRunLogProgram(unittest.TestCase):
    """The launcher as a program: --version with the log on, and with it off."""

    def run_engine(self, folder):
        env = dict(os.environ, PARTITOR_ALLOW_ROOT="1")
        env.pop(runlog.LOG_ENV, None)
        if folder:
            env[runlog.LOG_ENV] = folder
        return subprocess.run([sys.executable, SRC, "--version"], capture_output=True, text=True,
                              env=env)

    def test_version_run_is_logged_with_exit_code(self):
        with tempfile.TemporaryDirectory() as d:
            r = self.run_engine(d)
            self.assertEqual(r.returncode, 0, r.stderr)
            (name,) = os.listdir(d)
            with open(os.path.join(d, name), encoding="utf-8") as fh:
                text = fh.read()
            self.assertIn("args: --version", text)
            self.assertIn("out partitor ", text)
            self.assertTrue(text.rstrip().endswith("exit: 0"), text)

    def test_nothing_is_written_when_off(self):
        r = self.run_engine("")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(r.stdout.startswith("partitor "))
