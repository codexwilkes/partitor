# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""Tests for tests/support.py and for how the engine starts: the loader must not hide a
broken engine import, every engine test file must run with the synthetic logo,
`mock_attr` must refuse a name that does not exist, and the engine script must find
its package (also with python -I and in a read-only tree).

Run: venv/bin/python3 -m unittest -v tests/test_support.py
"""
import contextlib
import importlib
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import support  # noqa: E402
from support import HAVE_DEPS, needs_deps  # noqa: E402

ROOT = os.path.abspath(os.path.join(HERE, ".."))
ENGINE_TEST_FILES = ["test_analysis", "test_mapping", "test_bars", "test_parallel", "test_layout",
                     "test_render", "test_clef", "test_library", "test_cli"]


def version():
    with open(os.path.join(ROOT, "VERSION"), encoding="utf-8") as fh:
        return fh.read().strip()


class TestLoader(unittest.TestCase):
    def test_deps_flag_follows_the_four_imports(self):
        """HAVE_DEPS false although the packages import = a hidden import error."""
        try:
            import cv2, numpy, pymupdf, yaml  # noqa: E401,F401
            importable = True
        except ImportError:
            importable = False
        self.assertEqual(support.HAVE_DEPS, importable)
        self.assertEqual(support.pt is not None, importable)

    @needs_deps
    def test_import_error_of_the_engine_itself_is_not_caught(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "tests"))
            os.makedirs(os.path.join(tmp, "lib"))
            shutil.copy(os.path.join(HERE, "support.py"), os.path.join(tmp, "tests", "support.py"))
            with open(os.path.join(tmp, "lib", "partitor-engine"), "w", encoding="utf-8") as fh:
                fh.write('raise ImportError("engine import is broken")\n')
            code = f"import sys; sys.path.insert(0, {os.path.join(tmp, 'tests')!r}); import support"
            r = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True)
            self.assertNotEqual(r.returncode, 0, "support swallowed the engine import error")
            self.assertIn("engine import is broken", r.stderr)

    @needs_deps
    def test_loaded_engine_is_the_repo_engine_with_the_package_version(self):
        self.assertEqual(support.pt.VERSION, version())
        import partitor
        self.assertTrue(os.path.realpath(partitor.__file__).startswith(
            os.path.realpath(os.path.join(ROOT, "lib")) + os.sep))

    def test_tests_dir_is_on_sys_path(self):
        self.assertIn(HERE, sys.path)


class TestMockAttr(unittest.TestCase):
    def test_missing_name_raises(self):
        class Box:
            kept = 1
        with self.assertRaises(AttributeError):
            with support.mock_attr(Box, "gone", 2):
                pass

    def test_value_is_replaced_and_restored(self):
        class Box:
            kept = 1
        with support.mock_attr(Box, "kept", 2):
            self.assertEqual(Box.kept, 2)
        self.assertEqual(Box.kept, 1)
        with contextlib.suppress(RuntimeError):
            with support.mock_attr(Box, "kept", 3):
                raise RuntimeError
        self.assertEqual(Box.kept, 1)


@needs_deps
class TestLogoFixture(unittest.TestCase):
    def test_every_engine_test_file_sets_and_restores_the_logo(self):
        had = os.environ.get("PARTITOR_LOGO")
        for name in ENGINE_TEST_FILES:
            with self.subTest(file=name):
                mod = importlib.import_module(name)
                self.assertIs(mod.setUpModule, support.setUpModule)
                self.assertIs(mod.tearDownModule, support.tearDownModule)
                mod.setUpModule()
                try:
                    logo = os.environ.get("PARTITOR_LOGO")
                    self.assertTrue(logo and os.path.isfile(logo), logo)
                finally:
                    mod.tearDownModule()
                self.assertEqual(os.environ.get("PARTITOR_LOGO"), had)
                if logo:
                    self.assertFalse(os.path.exists(logo))


@needs_deps
class TestEngineStart(unittest.TestCase):
    ENGINE = os.path.join(ROOT, "lib", "partitor-engine")

    def run_engine(self, engine, *args):
        env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
        return subprocess.run([sys.executable, "-I", engine, *args], capture_output=True,
                              text=True, env=env, stdin=subprocess.DEVNULL)

    def test_script_finds_its_package_from_its_own_location_with_python_I(self):
        r = self.run_engine(self.ENGINE, "--version")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), f"partitor {version()}")

    def test_script_started_through_a_symlink_finds_its_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            link = os.path.join(tmp, "engine-link")
            os.symlink(self.ENGINE, link)
            r = self.run_engine(link, "--version")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stdout.strip(), f"partitor {version()}")

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root can write everywhere")
    def test_read_only_tree_starts(self):
        """The service user cannot write __pycache__ (ProtectSystem=strict)."""
        tmp = tempfile.mkdtemp(prefix="pt-ro-")
        try:
            lib = os.path.join(tmp, "lib")
            shutil.copytree(os.path.join(ROOT, "lib"), lib,
                            ignore=shutil.ignore_patterns("__pycache__"))
            for base, dirs, files in os.walk(tmp):
                for n in files:
                    os.chmod(os.path.join(base, n), stat.S_IRUSR | stat.S_IXUSR)
            for base, dirs, files in os.walk(tmp, topdown=False):
                os.chmod(base, stat.S_IRUSR | stat.S_IXUSR)
            r = self.run_engine(os.path.join(lib, "partitor-engine"), "--version")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stdout.strip(), f"partitor {version()}")
            self.assertFalse(os.path.exists(os.path.join(lib, "partitor", "__pycache__")))
        finally:
            for base, dirs, files in os.walk(tmp):
                os.chmod(base, 0o755)
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
