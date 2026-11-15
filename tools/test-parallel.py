#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""Run the unit tests in N processes (local gate only; CI stays serial).

Usage:
  tools/test-parallel.py [--jobs N] [--root DIR]     (run from anywhere; default N=4)

Same discovery as CI (`unittest discover -s tests`). The test CLASSES are split over N
processes, the slowest first, by the seconds in tools/test-weights.txt (a class that is
not listed counts 0.05 second per test). One class is never split, so setUpClass runs
once per class, as in a serial run. setUpModule runs once per process that holds a class
of that file.

The run fails (exit 1) when a test fails or errors, when a child process dies, or when
the number of tests that ran differs from the number that discovery finds: no test may
fall out of a split. Output ends like unittest: `Ran N tests in Ts` and `OK` or `FAILED`.
It also prints the time of each process and the peak memory use of the machine.

Tests of different files must not share a temp or library folder: every test makes its
own with tempfile. This is checked by running them in parallel.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

MARK = "TEST-PARALLEL-RESULT "


def discover(root: Path) -> tuple[dict[str, int], list[str]]:
    """discover -> ({`module.Class`: number of tests}, ids of files that do not import),
    found as CI finds them."""
    tests = root / "tests"
    before = set(sys.modules)
    sys.path.insert(0, str(tests))
    try:
        suite = unittest.defaultTestLoader.discover(str(tests), top_level_dir=str(tests))
    finally:
        sys.path.remove(str(tests))
        for name in set(sys.modules) - before:           # leave no test module behind
            f = getattr(sys.modules[name], "__file__", None) or ""
            if f.startswith(str(tests) + os.sep):
                del sys.modules[name]
    counts: dict[str, int] = {}
    broken: list[str] = []

    def walk(s):
        for t in s:
            if isinstance(t, unittest.TestSuite):
                walk(t)
            elif type(t).__name__ == "_FailedTest":
                broken.append(t.id())
            else:
                key = ".".join(t.id().split(".")[:2])
                counts[key] = counts.get(key, 0) + 1

    walk(suite)
    return counts, broken


def read_weights(path: Path) -> dict[str, float]:
    """read_weights -> {`module.Class`: seconds}; lines `name seconds`, # starts a comment."""
    out: dict[str, float] = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.split("#", 1)[0].split()
            if len(line) == 2:
                out[line[0]] = float(line[1])
    return out


def split(counts: dict[str, int], weights: dict[str, float], jobs: int) -> list[list[str]]:
    """split -> `jobs` lists of `module.Class` names, balanced by weight (largest first, each
    to the lightest list). An empty list is dropped. Every class is in exactly one list."""
    bins: list[list[str]] = [[] for _ in range(max(1, jobs))]
    load = [0.0] * len(bins)
    for mod in sorted(counts, key=lambda m: (-weights.get(m, 0.05 * counts[m]), m)):
        i = min(range(len(bins)), key=lambda k: (load[k], k))
        bins[i].append(mod)
        load[i] += weights.get(mod, 0.05 * counts[mod])
    return [b for b in bins if b]


def child(root: Path, modules: list[str]) -> int:
    """Run the test classes in this process. Print one result line for the parent."""
    tests = root / "tests"
    sys.path.insert(0, str(tests))
    suite = unittest.defaultTestLoader.loadTestsFromNames(modules)
    res = unittest.TextTestRunner(stream=sys.stderr, verbosity=0).run(suite)
    print(MARK + json.dumps({"ran": res.testsRun, "skipped": len(res.skipped),
                             "failures": len(res.failures), "errors": len(res.errors)}))
    return 0 if res.wasSuccessful() else 1


def mem_used_mb() -> float:
    """mem_used_mb -> MemTotal minus MemAvailable, in MB (0.0 where /proc is missing)."""
    try:
        kb = {}
        for line in Path("/proc/meminfo").read_text().splitlines():
            k, _, v = line.partition(":")
            kb[k] = int(v.split()[0])
        return (kb["MemTotal"] - kb["MemAvailable"]) / 1024
    except (OSError, KeyError, ValueError):
        return 0.0


def run(root: Path, jobs: int) -> int:
    counts, broken = discover(root)
    if broken:
        print("FAILED: a test file does not import: " + ", ".join(broken))
        return 1
    expected = sum(counts.values())
    bins = split(counts, read_weights(root / "tools" / "test-weights.txt"), jobs)
    peak = [mem_used_mb()]
    stop = threading.Event()

    def sample():
        while not stop.wait(1.0):
            peak[0] = max(peak[0], mem_used_mb())

    threading.Thread(target=sample, daemon=True).start()
    base = peak[0]
    t0 = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="test-parallel-") as tmp:
        procs = []
        for i, mods in enumerate(bins):
            log = open(os.path.join(tmp, f"{i}.log"), "w+", encoding="utf-8")
            p = subprocess.Popen([sys.executable, os.path.abspath(__file__), "--root", str(root),
                                  "--child", *mods], cwd=root, stdout=log, stderr=subprocess.STDOUT,
                                 text=True)
            procs.append((i, mods, p, log, time.perf_counter()))
        done: dict[int, float] = {}
        while len(done) < len(procs):                    # poll: each process gets its own time
            for i, mods, p, log, started in procs:
                if i not in done and p.poll() is not None:
                    done[i] = time.perf_counter() - started
            time.sleep(0.2)
        results = []
        for i, mods, p, log, started in procs:
            log.seek(0)
            text = log.read()
            log.close()
            res = None
            for line in text.splitlines():
                if line.startswith(MARK):
                    res = json.loads(line[len(MARK):])
            results.append((i, mods, p.returncode, done[i], res, text))
    stop.set()
    total = time.perf_counter() - t0
    ran = skipped = bad = 0
    for i, mods, rc, took, res, text in results:
        print(f"process {i}: {took:6.1f} s  {len(mods)} class(es)")
        if res is None:
            bad += 1
            print(f"process {i} died (exit {rc}) without a result:\n{text}")
            continue
        ran += res["ran"]
        skipped += res["skipped"]
        if rc != 0 or res["failures"] or res["errors"]:
            bad += res["failures"] + res["errors"] or 1
            print(text.replace(MARK + json.dumps(res), "").rstrip())
    print(f"peak memory use: {max(peak[0] - base, 0.0) / 1024:.1f} GB above the start")
    print("-" * 70)
    print(f"Ran {ran} tests in {total:.3f}s")
    if ran != expected:
        print(f"FAILED: discovery finds {expected} tests, {ran} ran")
        return 1
    if bad:
        print(f"FAILED ({bad} problem(s))")
        return 1
    print("OK" + (f" (skipped={skipped})" if skipped else ""))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Run the unit tests in N processes.")
    ap.add_argument("--jobs", type=int, default=4, help="processes (default 4)")
    ap.add_argument("--root", default=str(Path(__file__).resolve().parent.parent),
                    help="repo root (default: the folder above tools/)")
    ap.add_argument("--child", nargs="+", metavar="MODULE.CLASS", help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    root = Path(a.root).resolve()
    if a.child:
        return child(root, a.child)
    if a.jobs < 1:
        ap.error("--jobs must be 1 or more")
    return run(root, a.jobs)


if __name__ == "__main__":
    sys.exit(main())
