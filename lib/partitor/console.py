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


def _reset_counts() -> None:
    """Zero the counters (the library CLI runs several steps in one process)."""
    for k in _counts:
        _counts[k] = 0
    _FAILURES.clear()
    _WARNINGS.clear()


def _summary(start: float) -> int:
    ms = int((time.monotonic() - start) * 1000)
    print(f"\n{BOLD}══ Summary{RST}")
    print(f"  {GRN}PASS: {_counts['pass']}{RST}   {RED}FAIL: {_counts['fail']}{RST}"
          f"   {YLW}WARN: {_counts['warn']}{RST}   (elapsed: {ms}ms)\n")
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
    if _counts["warn"]:
        print(f"{YLW}{BOLD}OK with {_counts['warn']} warning(s){RST}\n")
    else:
        print(f"{GRN}{BOLD}ALL OK{RST}\n")
    return 0


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
    if ans.lower() == "q":
        raise Abort()
    return ans or default


def yes(prompt: str, default: bool = True) -> bool:
    d = "Y/n" if default else "y/N"
    ans = ask(f"{prompt} [{d}]").lower()
    return default if not ans else ans.startswith("y")
