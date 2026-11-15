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


class TestLogCommand(unittest.TestCase):
    """`partitor log`: print, pick, tail, list; it writes no log itself."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="pt-runlog-show-")
        self.addCleanup(lambda: __import__("shutil").rmtree(self.dir, ignore_errors=True))
        for i, (args, code) in enumerate((("detect a.pdf", 0), ("build a.pdf", 1), ("list", 0)), 1):
            with open(os.path.join(self.dir, f"run-20261114-10000{i}-{i}.log"), "w",
                      encoding="utf-8") as fh:
                fh.write(f"     0.0s log partitor 0.8.67\n     0.0s log args: {args}\n"
                         f"     0.1s out line one of {i}\n     0.2s out line two of {i}\n"
                         f"     0.3s log exit: {code}\n")
        env = mock.patch.dict(os.environ, {runlog.LOG_ENV: self.dir})
        env.start()
        self.addCleanup(env.stop)

    def show(self, *args, **kw):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = runlog.show_log(*args, **kw)
        self.assertEqual(rc, 0)
        return out.getvalue()

    def dies(self, *args, **kw):
        err = io.StringIO()
        with contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as cm:
            runlog.show_log(*args, **kw)
        self.assertEqual(cm.exception.code, 1)
        return err.getvalue()

    def test_default_is_the_newest(self):
        text = self.show()
        self.assertIn("line one of 3", text)
        self.assertNotIn("of 2", text)

    def test_number_counts_back_from_the_newest(self):
        self.assertIn("line one of 2", self.show("2"))
        self.assertIn("line one of 1", self.show("3"))

    def test_a_file_name_is_taken(self):
        self.assertIn("line one of 1", self.show("run-20261114-100001-1.log"))

    def test_tail_keeps_the_last_lines(self):
        text = self.show("1", tail=2)
        self.assertEqual(text.count("\n"), 2)
        self.assertIn("exit: 0", text)
        self.assertNotIn("line one", text)

    def test_list_has_number_file_exit_and_arguments(self):
        lines = self.show(listing=True).splitlines()
        self.assertEqual(len(lines), 3)
        self.assertRegex(lines[0], r"^\s+1  run-20261114-100003-3\.log  exit 0  list$")
        self.assertRegex(lines[1], r"exit 1  build a\.pdf$")
        self.assertEqual(len(self.show(listing=True, count=2).splitlines()), 2)

    def test_bad_requests_say_what_is_wrong(self):
        self.assertIn("no run log number 4", self.dies("4"))
        self.assertIn("no run log number 0", self.dies("0"))
        self.assertIn("no run log", self.dies("../etc/passwd"))
        self.assertIn("no run log", self.dies("run-nothing.log"))

    def test_off_and_empty_folder(self):
        with mock.patch.dict(os.environ):
            os.environ.pop(runlog.LOG_ENV)
            self.assertIn("the run log is off", self.dies())
        with tempfile.TemporaryDirectory() as empty, mock.patch.dict(os.environ, {runlog.LOG_ENV: empty}):
            self.assertIn("no run log in", self.dies())
        with mock.patch.dict(os.environ, {runlog.LOG_ENV: os.path.join(self.dir, "none")}):
            self.assertIn("cannot read the run log folder", self.dies())

    def test_the_program_prints_and_adds_no_log(self):
        env = dict(os.environ, PARTITOR_ALLOW_ROOT="1")
        r = subprocess.run([sys.executable, SRC, "log", "2", "--tail", "1"], capture_output=True,
                           text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("exit: 1", r.stdout)
        r = subprocess.run([sys.executable, SRC, "log", "--list"], capture_output=True, text=True,
                           env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(os.listdir(self.dir)), 3)          # the two runs wrote no file
        self.assertEqual(len(r.stdout.splitlines()), 3)

    def test_the_program_says_when_the_log_is_off(self):
        env = {k: v for k, v in os.environ.items() if k != runlog.LOG_ENV}
        env["PARTITOR_ALLOW_ROOT"] = "1"
        r = subprocess.run([sys.executable, SRC, "log"], capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 1)
        self.assertIn("the run log is off", r.stderr)
