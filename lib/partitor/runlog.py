# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""Run log: a plain-text record of one CLI run, for diagnosis (DESIGN.md §12.5).

Off unless PARTITOR_LOG_DIR names a folder. Then every run writes one file there
(`run-<date>-<time>-<pid>.log`): a header, every line the program prints to stdout
or stderr (colour removed, each with the seconds since the start), the answers to
the prompts, a traceback if the run crashes, and the exit code. A log that cannot
be written never stops a run: one line on stderr, then the run goes on."""
from __future__ import annotations

import os
import re
import sys
import time
import traceback
from datetime import datetime

from . import VERSION, console

LOG_ENV = "PARTITOR_LOG_DIR"
_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")

_fd: int | None = None
_t0 = 0.0
_saved: tuple | None = None


def _emit(tag: str, line: str) -> None:
    """One line into the log; a single os.write on an O_APPEND file, so the lines of forked
    workers do not mix inside a line."""
    if _fd is None:
        return
    try:
        os.write(_fd, f"{time.monotonic() - _t0:8.1f}s {tag:<3} {line}\n".encode("utf-8", "replace"))
    except OSError:
        pass


class _Tee:
    """A stdout or stderr that also writes whole lines into the log. A progress line (it
    starts over with a carriage return) keeps only its last state."""

    def __init__(self, real, tag: str):
        self._real = real
        self._tag = tag
        self._buf = ""

    def write(self, s):
        n = self._real.write(s)
        self._buf += s
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            self._line(line)
        return len(s) if n is None else n

    def _line(self, line: str) -> None:
        text = _ANSI.sub("", line).rsplit("\r", 1)[-1]
        if text.strip():
            _emit(self._tag, text)

    def drain(self) -> None:
        """The text without a newline (a prompt waiting for an answer) becomes a line."""
        buf, self._buf = self._buf, ""
        if buf:
            self._line(buf)

    def __getattr__(self, name):
        return getattr(self._real, name)


def _answer(prompt: str, answer: str) -> None:
    for t in (sys.stdout, sys.stderr):
        if isinstance(t, _Tee):
            t.drain()
    _emit("in", f"{prompt.strip()} -> {answer!r}")


def start(argv: list[str]) -> None:
    """Open the log when PARTITOR_LOG_DIR is set, and tee stdout and stderr into it."""
    global _fd, _t0, _saved
    folder = os.environ.get(LOG_ENV, "")
    if not folder or _fd is not None:
        return
    now = datetime.now()
    path = os.path.join(folder, f"run-{now:%Y%m%d-%H%M%S}-{os.getpid()}.log")
    try:
        _fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    except OSError as e:
        print(f"partitor: run log off: {e.strerror}: {folder}", file=sys.stderr)
        return
    _t0 = time.monotonic()
    _emit("log", f"partitor {VERSION}  {now:%Y-%m-%d %H:%M:%S}  pid {os.getpid()}")
    _emit("log", "args: " + " ".join(argv))
    _emit("log", f"cwd: {os.getcwd()}")
    _emit("log", f"python: {sys.version.split()[0]}")
    for k in sorted(os.environ):
        if k.startswith("PARTITOR_"):
            _emit("log", f"env: {k}={os.environ[k]}")
    _saved = (sys.stdout, sys.stderr)
    sys.stdout, sys.stderr = _Tee(sys.stdout, "out"), _Tee(sys.stderr, "err")
    console._ANSWER_LOG.append(_answer)


def _logs(folder: str) -> list[str]:
    """The log files of a folder, newest first (the names sort by date and time)."""
    try:
        names = [n for n in os.listdir(folder) if n.startswith("run-") and n.endswith(".log")]
    except OSError as e:
        console._die(f"cannot read the run log folder: {e.strerror}: {folder}")
    return sorted(names, reverse=True)


def _read(folder: str, name: str) -> str:
    try:
        with open(os.path.join(folder, name), encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError as e:
        console._die(f"cannot read the run log: {e.strerror}: {name}")
    return ""


def _log_summary(text: str) -> tuple[str, str]:
    """(arguments, exit code) of a log: its header line `args:` and its last line `exit:`."""
    args = status = "?"
    for line in text.splitlines():
        if " log args: " in line and args == "?":
            args = line.split(" log args: ", 1)[1] or "(none)"
        if " log exit: " in line:
            status = line.split(" log exit: ", 1)[1]
    return args, status


def show_log(which: str = "1", tail: int = 0, listing: bool = False, count: int = 20) -> int:
    """`partitor log`: print a run log of the folder PARTITOR_LOG_DIR. which: a number (1 = the
    newest, 2 = the one before) or a file name of the folder; tail: only the last N lines;
    listing: one line per log (the newest `count`) instead. The command writes no log itself."""
    folder = os.environ.get(LOG_ENV, "")
    if not folder:
        console._die("the run log is off", f"Set {LOG_ENV}=<folder> (docs/OPERATING.md), then run again.")
    names = _logs(folder)
    if not names:
        console._die(f"no run log in {folder}", "A run writes one when it starts; run a command first.")
    if listing:
        for i, n in enumerate(names[:count], 1):
            args, status = _log_summary(_read(folder, n))
            print(f"{i:>3}  {n}  exit {status}  {args}")
        return 0
    if which.isdigit():
        if not 1 <= int(which) <= len(names):
            console._die(f"no run log number {which}: the folder has {len(names)}", "partitor log --list")
        name = names[int(which) - 1]
    elif "/" not in which and which in names:
        name = which
    else:
        console._die(f"no run log {which!r} in the folder", "partitor log --list")
    lines = _read(folder, name).splitlines()
    for line in lines[-tail:] if tail > 0 else lines:
        print(line)
    return 0


def crash() -> None:
    """The traceback of the exception being handled, as log lines."""
    for line in traceback.format_exc().splitlines():
        _emit("err", line)


def finish(status) -> None:
    """End of the run: the open lines, the exit code; stdout and stderr are as before."""
    global _fd, _saved
    if _fd is None:
        return
    for t in (sys.stdout, sys.stderr):
        if isinstance(t, _Tee):
            t.drain()
    _emit("log", f"exit: {status}")
    if _saved is not None:
        sys.stdout, sys.stderr = _saved
    if _answer in console._ANSWER_LOG:
        console._ANSWER_LOG.remove(_answer)
    os.close(_fd)
    _fd, _saved = None, None
