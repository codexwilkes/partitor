# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""fork_map, job and memory sizing."""
from __future__ import annotations

import contextlib
import io
import os
import pickle
import re
import resource
import shutil
import signal
import sys
import tempfile
import traceback
from pathlib import Path

import cv2

from . import console
from .console import _FAILURES, _WARNINGS, _counts, _reset_counts, _warn


# =============================================================================
# Parallel work (0.3.0-dev.33)
# =============================================================================
# A build spends most of its time on two loops that do not depend on each
# other: the analysis of each page (OCR, staves, ownership) and the rendering
# of each part. fork_map runs such a loop in forked child processes (no
# threads, no pickled inputs: a child sees the parent's memory as it was at the
# fork). Results come back in order, with the text each child printed.
# jobs = 1 runs the loop in this process, as before.
PAGE_WORKER_GB = 1.5      # estimate: peak memory of one page analysis (400 dpi)
RENDER_WORKER_GB = 1.0    # estimate: peak memory of rendering one part
MAIN_GB = 2.0             # estimate: the parent (all strips of the piece, 70 pages)
JOBS_MAX = 6              # auto never starts more children than this
GIB = 1 << 30


def parse_size(text: str) -> int | None:
    """parse_size '8G' | '1500M' | '123456' -> bytes; None for '', infinity or
    anything else (systemd notation, K M G T are powers of 1024)."""
    m = re.fullmatch(r"\s*(\d+)\s*([KMGT]?)B?\s*", str(text or ""), re.I)
    if not m:
        return None
    return int(m.group(1)) * (1024 ** ("", "K", "M", "G", "T").index(m.group(2).upper()))


def mem_available() -> int:
    """mem_available -> bytes of memory the machine can still give (MemAvailable)."""
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    return 4 * GIB


def job_count(requested, worker_gb: float, items: int) -> int:
    """job_count -> number of children to run at once, 1..items.

    requested: --jobs, else PARTITOR_JOBS, else auto. A number is taken as
    it is (the operator knows the machine). auto: one core stays free, at most
    JOBS_MAX, and the memory cap of the run (PARTITOR_MEMORY_MAX, set by the
    wrapper; else 80 % of what the machine has free) less MAIN_GB must hold
    every child at worker_gb."""
    if items <= 1:
        return 1
    req = str(requested if requested is not None
              else os.environ.get("PARTITOR_JOBS", "auto")).strip().lower()
    if req not in ("", "auto"):
        try:
            return max(1, min(int(req), items))
        except ValueError:
            _warn(f"jobs:  '{req}' is not a number or auto; using auto")
    cpus = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else (os.cpu_count() or 1)
    cap = parse_size(os.environ.get("PARTITOR_MEMORY_MAX", ""))
    if cap is None:
        cap = int(mem_available() * 0.8)
    by_mem = int((cap - MAIN_GB * GIB) // (worker_gb * GIB))
    return max(1, min(items, cpus - 1, JOBS_MAX, by_mem))


def worker_peak_mb() -> int:
    """worker_peak_mb -> peak memory (MB) of the largest child that ended so far."""
    return int(resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss / 1024)


def _describe_exit(status: int) -> str:
    if os.WIFSIGNALED(status):
        sig = os.WTERMSIG(status)
        known = {int(x): x.name for x in signal.Signals}
        return f"killed by {known.get(sig, sig)}" + (
            " (out of memory? see PARTITOR_MEMORY_MAX)" if sig == signal.SIGKILL else "")
    return f"exit code {os.WEXITSTATUS(status)}"


def _child_run(fn, item, path: str) -> None:
    """In the child: run fn(item) with its output captured, write the result to path."""
    console._TTY = False                     # no self-overwriting progress lines in captured text
    _reset_counts()
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            payload = ("ok", fn(item))
    except SystemExit as e:
        payload = ("exit", e.code)
    except BaseException:            # noqa: BLE001
        payload = ("error", traceback.format_exc())
    out = (payload, buf.getvalue(), dict(_counts), list(_FAILURES), list(_WARNINGS))
    try:
        blob = pickle.dumps(out, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception:                # noqa: BLE001  (a result that cannot be pickled)
        blob = pickle.dumps((("error", traceback.format_exc()), buf.getvalue(),
                             dict(_counts), list(_FAILURES), list(_WARNINGS)))
    with open(path + ".tmp", "wb") as f:
        f.write(blob)
    os.replace(path + ".tmp", path)


def fork_map(fn, items, jobs: int):
    """fork_map -> generator of fn(item) for each item, in order.

    jobs <= 1 (or one item): fn runs in this process. Else up to `jobs` forked
    children run fn at once. Each child's printed text and check counts are
    replayed here when its result is yielded, so the output keeps the order
    of the items. A child that raises makes this raise RuntimeError with its
    traceback; one that calls _die ends this run the same way; one that is
    killed (out of memory) raises RuntimeError and the others are stopped.
    Close the generator (contextlib.closing) when you stop early."""
    items = list(items)
    if jobs <= 1 or len(items) <= 1:
        for it in items:
            yield fn(it)
        return
    tmp = tempfile.mkdtemp(prefix="partitor-")
    running: dict[int, int] = {}          # pid -> item index
    ended: dict[int, int] = {}            # item index -> wait status
    nxt = ready = 0
    # OpenCV's thread pool does not survive a fork: a child that meets a pool
    # its parent had started waits for ever (seen: setNumThreads in the child,
    # a menu session that analysed before it built). So the parent stops the
    # pool here, before any fork, and starts it again at the end; the children
    # work with one thread each.
    threads = cv2.getNumThreads()
    cv2.setNumThreads(1)
    try:
        sys.stdout.flush()
        sys.stderr.flush()
        while ready < len(items):
            while nxt < len(items) and len(running) < jobs:
                path = os.path.join(tmp, f"{nxt}.pkl")
                try:
                    pid = os.fork()
                except OSError:
                    if not running:
                        raise
                    break                  # no process free: wait for one to end
                if pid == 0:               # child
                    code = 1
                    try:
                        _child_run(fn, items[nxt], path)
                        code = 0
                    finally:
                        os._exit(code)
                running[pid] = nxt
                nxt += 1
            if ready not in ended:
                pid, status = os.wait()
                idx = running.pop(pid, None)
                if idx is not None:
                    ended[idx] = status
                continue
            status = ended.pop(ready)
            path = os.path.join(tmp, f"{ready}.pkl")
            if not os.path.exists(path):
                raise RuntimeError(f"worker for item {ready + 1} of {len(items)} died: "
                                   f"{_describe_exit(status)}")
            with open(path, "rb") as f:
                payload, text, counts, fails, warns = pickle.load(f)
            os.unlink(path)
            sys.stdout.write(text)
            for k_, v_ in counts.items():
                _counts[k_] += v_
            _FAILURES.extend(fails)
            _WARNINGS.extend(warns)
            kind, val = payload
            if kind == "exit":
                raise SystemExit(val)
            if kind == "error":
                raise RuntimeError(f"worker for item {ready + 1} of {len(items)} failed:\n{val}")
            ready += 1
            yield val
    finally:
        for pid in list(running):
            try:
                os.kill(pid, signal.SIGKILL)
                os.waitpid(pid, 0)
            except OSError:
                pass
        shutil.rmtree(tmp, ignore_errors=True)
        cv2.setNumThreads(threads)
