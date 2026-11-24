# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""Output primitives, colours, counters, prompts and Abort."""
from __future__ import annotations

import os
import sys
import time


# ── Output primitives (CLI-STYLE-GUIDE §4, Python port) ─────────────────────
# PARTITOR_COLOR=1 forces colour and progress lines when stdout is no terminal:
# the wrapper runs the engine through a pipe (`systemd-run --pipe`) and sets it
# when its own stdout is a terminal (0.3.0-dev.39). Anything else: colour only
# on a terminal.
_TTY = sys.stdout.isatty() or os.environ.get("PARTITOR_COLOR") == "1"
RED, GRN, YLW, BLU, DIM, BOLD, RST = (
    ("\033[0;31m", "\033[0;32m", "\033[0;33m", "\033[0;34m", "\033[2m",
     "\033[1m", "\033[0m") if _TTY else ("",) * 7)
_counts = {"pass": 0, "fail": 0, "warn": 0}
_FAILURES: list[str] = []
_WARNINGS: list[str] = []
_ANSWER_LOG: list = []      # callbacks (prompt, answer) of the run log (runlog.py), changed in place


def _ok(msg: str) -> None:
    _counts["pass"] += 1
    print(f"  {GRN}✔{RST}  {msg}")


def _fail(msg: str) -> None:
    _counts["fail"] += 1
    _FAILURES.append(msg)
    print(f"  {RED}✘{RST}  {msg}")


def _warn(msg: str) -> None:
    _counts["warn"] += 1
    _WARNINGS.append(msg)
    print(f"  {YLW}⚠{RST}  {msg}")


def _note(msg: str) -> None:
    print(f"     {DIM}{msg}{RST}")


def _skip(msg: str) -> None:
    print(f"  ⊘  {msg}")


def _head(msg: str) -> None:
    print(f"\n{BOLD}{BLU}══ {msg}{RST}")


def _progress(msg: str) -> None:
    """Self-overwriting single-line progress indicator (TTY only)."""
    if _TTY:
        print(f"\r  {DIM}·{RST}  {msg}\033[K", end="", flush=True)


def _progress_end() -> None:
    if _TTY:
        print("\r\033[K", end="", flush=True)


def _die(msg: str, hint: str = "") -> None:
    print(f"\n{BOLD}{RED}ERROR:{RST} {msg}", file=sys.stderr)
    if hint:
        print(f"     {DIM}{hint}{RST}", file=sys.stderr)
    sys.exit(1)


def _reset_counts(keep_warnings: bool = False) -> None:
    """Zero the counters (the library CLI runs several steps in one process). keep_warnings: the
    warnings of the step stay (count and text), so the summary of the command after a build step
    says them again and does not end with ALL OK (0.8.45)."""
    for k in _counts:
        if not (keep_warnings and k == "warn"):
            _counts[k] = 0
    _FAILURES.clear()
    if not keep_warnings:
        _WARNINGS.clear()


def _summary(start: float, quiet: bool = False) -> int:
    """The verdict. Nothing wrong: one line, `ALL OK (12 s)`, no counts. A warning or a failure:
    the counts and the text of each. quiet: print nothing when nothing failed (an inner step of a
    command that prints the verdict itself; its warnings are kept and said again there)."""
    secs = time.monotonic() - start
    took = f"{secs:.1f} s" if secs < 10 else f"{secs:.0f} s"
    if not _counts["fail"] and not _counts["warn"]:
        if not quiet:
            print(f"\n{GRN}{BOLD}ALL OK{RST}  {DIM}({took}){RST}\n")
        return 0
    if quiet and not _counts["fail"]:
        return 0
    print(f"\n{BOLD}══ Summary{RST}")
    print(f"  {GRN}PASS: {_counts['pass']}{RST}   {RED}FAIL: {_counts['fail']}{RST}"
          f"   {YLW}WARN: {_counts['warn']}{RST}   ({took})\n")
    if _FAILURES:
        print(f"{BOLD}{RED}Failed checks:{RST}")
        for f in _FAILURES:
            print(f"  {RED}✘{RST}  {f}")
        print()
    if _WARNINGS:
        print(f"{BOLD}{YLW}Warnings:{RST}")
        for w in _WARNINGS:
            print(f"  {YLW}⚠{RST}  {w}")
        print()
    if _counts["fail"]:
        print(f"{RED}{BOLD}NOT OK — {_counts['fail']} check(s) failed{RST}\n")
        return 1
    print(f"{YLW}{BOLD}OK with {_counts['warn']} warning(s){RST}\n")
    return 0


def columns(left: list[str], right: list[str], width: int = 40) -> str:
    """Two aligned columns, one entry per row, for a menu help (80 characters in all)."""
    rows = []
    for i in range(max(len(left), len(right))):
        l_ = left[i] if i < len(left) else ""
        r_ = right[i] if i < len(right) else ""
        rows.append(f"  {l_:<{width - 2}}{r_}".rstrip())
    return "\n".join(rows)


class Abort(Exception):
    """Operator stopped a wizard (q, Ctrl-C or end of input)."""


def ask(prompt: str, default: str = "") -> str:
    """ask -> the answer, or default on Enter. q stops (Abort)."""
    shown = f" [{default}]" if default else ""
    try:
        ans = input(f"  {prompt}{shown}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        raise Abort()
    for log in _ANSWER_LOG:
        log(prompt, ans)
    if ans.lower() == "q":
        raise Abort()
    return ans or default


def yes(prompt: str, default: bool = True) -> bool:
    d = "Y/n" if default else "y/N"
    ans = ask(f"{prompt} [{d}]").lower()
    return default if not ans else ans.startswith("y")
