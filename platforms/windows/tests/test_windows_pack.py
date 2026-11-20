# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""Tests for the Windows pack (platforms/windows/partitor_windows). They run on Linux with mocks
(ctypes.windll, environment, PATH); no Windows is needed. tests/test_packs.py loads them.

    venv/bin/python3 -m unittest -v tests/test_packs.py
"""
import ctypes
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
for p in (ROOT / "lib", ROOT / "platforms" / "windows"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from partitor import hooks  # noqa: E402
from partitor_windows import pack  # noqa: E402


class PackShapeTests(unittest.TestCase):
    def test_pack_fits_the_core(self):
        self.assertEqual(pack.API, hooks.API)
        self.assertTrue(set(pack.HOOKS) <= set(hooks.HOOKS))
        for name in pack.HOOKS:
            self.assertTrue(callable(getattr(pack, name)), name)

    def test_install_and_uninstall(self):
        try:
            hooks.install(pack)
            self.assertIs(hooks.PACK, pack)
            self.assertIn("PDF viewer", hooks.locked_hint())
        finally:
            hooks.uninstall()
        self.assertIsNone(hooks.PACK)

    def test_entry_point_installs_the_pack_before_the_cli(self):
        from partitor_windows import __main__ as entry
        seen = []
        with mock.patch.object(entry.cli_main, "main", side_effect=lambda: seen.append(hooks.PACK) or 0):
            try:
                self.assertEqual(entry.main(), 0)
            finally:
                hooks.uninstall()
        self.assertEqual(seen, [pack])


class MemoryTests(unittest.TestCase):
    def test_memory_from_the_system_call(self):
        def fake(ref):
            ref._obj.ullAvailPhys = 123456
            return 1
        win = mock.Mock()
        win.kernel32.GlobalMemoryStatusEx.side_effect = fake
        with mock.patch.object(ctypes, "windll", win, create=True):
            self.assertEqual(pack.available_memory(), 123456)

    def test_memory_falls_back_to_four_gib(self):
        win = mock.Mock()
        win.kernel32.GlobalMemoryStatusEx.return_value = 0
        with mock.patch.object(ctypes, "windll", win, create=True):
            self.assertEqual(pack.available_memory(), 4 << 30)
        if not hasattr(ctypes, "windll"):                    # Linux: no windll at all
            self.assertEqual(pack.available_memory(), 4 << 30)


class ConsoleTests(unittest.TestCase):
    def test_console_init_sets_vt_mode_and_utf8(self):
        k32 = mock.Mock()
        k32.GetConsoleMode.side_effect = lambda h, ref: (setattr(ref._obj, "value", 3), 1)[1]
        out, err = mock.Mock(), mock.Mock()
        with mock.patch.object(ctypes, "windll", mock.Mock(kernel32=k32), create=True), \
                mock.patch.object(sys, "stdout", out), mock.patch.object(sys, "stderr", err):
            pack.console_init()
        self.assertEqual([c.args[1] for c in k32.SetConsoleMode.call_args_list], [3 | 4, 3 | 4])
        out.reconfigure.assert_called_once_with(encoding="utf-8")
        err.reconfigure.assert_called_once_with(encoding="utf-8")

    def test_console_init_without_a_console(self):
        k32 = mock.Mock()
        k32.GetConsoleMode.return_value = 0                   # output is a pipe or a file
        with mock.patch.object(ctypes, "windll", mock.Mock(kernel32=k32), create=True), \
                mock.patch.object(sys, "stdout", mock.Mock()), mock.patch.object(sys, "stderr", mock.Mock()):
            pack.console_init()
        k32.SetConsoleMode.assert_not_called()


class TesseractTests(unittest.TestCase):
    def test_bundled_copy_wins(self):
        with tempfile.TemporaryDirectory() as td:
            exe = Path(td, "tesseract", "tesseract.exe")
            exe.parent.mkdir()
            exe.write_bytes(b"")
            with mock.patch.object(sys, "executable", str(Path(td, "partitor.exe"))), \
                    mock.patch.object(pack.shutil, "which", return_value="/x/tesseract"):
                self.assertEqual(pack.tesseract_path(), str(exe))

    def test_path_then_installer_folder(self):
        with tempfile.TemporaryDirectory() as td:
            exe = Path(td, "Tesseract-OCR", "tesseract.exe")
            exe.parent.mkdir()
            exe.write_bytes(b"")
            with mock.patch.object(sys, "executable", "/none/partitor.exe"), \
                    mock.patch.dict(os.environ, {"ProgramFiles": td}):
                with mock.patch.object(pack.shutil, "which", return_value="/x/tesseract"):
                    self.assertEqual(pack.tesseract_path(), "/x/tesseract")
                with mock.patch.object(pack.shutil, "which", return_value=None):
                    self.assertEqual(pack.tesseract_path(), str(exe))

    def test_not_found(self):
        with mock.patch.object(sys, "executable", "/none/partitor.exe"), \
                mock.patch.object(pack.shutil, "which", return_value=None), \
                mock.patch.dict(os.environ, {"ProgramFiles": "/nonexistent"}):
            self.assertIsNone(pack.tesseract_path())


class LibraryAndHintTests(unittest.TestCase):
    def test_default_library_is_in_documents(self):
        with mock.patch.dict(os.environ, {"USERPROFILE": "/u/me"}):
            self.assertEqual(Path(pack.default_library()), Path("/u/me/Documents/partitor"))

    def test_setup_hint_does_not_name_a_linux_tool(self):
        self.assertNotIn("partitor-init", pack.setup_hint())
        self.assertIn("installer", pack.setup_hint())

    def test_locked_hint_names_the_viewer(self):
        self.assertIn("Close the file", pack.locked_hint())


if __name__ == "__main__":
    unittest.main()
