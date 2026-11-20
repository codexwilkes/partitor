# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""Loads the tests of every platform pack (platforms/<os>/tests/test_*.py), so that
`python -m unittest discover -s tests` runs them and MIN_TESTS counts them (DESIGN.md §12.6).
They run on Linux with mocks. The files are loaded by path (a nested discover with another
top-level folder fails inside the outer discover)."""
import glob
import importlib.util
import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))


def pack_test_files() -> list[str]:
    return sorted(glob.glob(os.path.join(ROOT, "platforms", "*", "tests", "test_*.py")))


def load_tests(loader, standard_tests, pattern):
    suite = unittest.TestSuite()
    for path in pack_test_files():
        pack = os.path.basename(os.path.dirname(os.path.dirname(path)))
        name = f"pack_{pack}_{os.path.splitext(os.path.basename(path))[0]}"
        mod = sys.modules.get(name)
        if mod is None:
            spec = importlib.util.spec_from_file_location(name, path)
            mod = importlib.util.module_from_spec(spec)
            sys.modules[name] = mod
            spec.loader.exec_module(mod)
        suite.addTests(loader.loadTestsFromModule(mod))
    return suite
