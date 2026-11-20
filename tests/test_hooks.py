# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""Tests for the platform seam (lib/partitor/hooks.py), lib/partitor/outfile.py and the rules
that keep platform code out of the core (DESIGN.md §12.6). The Windows pack has its own tests
in platforms/windows/tests (loaded by tests/test_packs.py).

    venv/bin/python3 -m unittest -v tests/test_hooks.py
"""
import contextlib
import io
import os
import re
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from support import LIB, config, console, library, needs_deps, parallel, stagecache, vision  # noqa: E402

if LIB not in sys.path:
    sys.path.insert(0, LIB)
from partitor import hooks, outfile  # noqa: E402

PKG = Path(LIB) / "partitor"


def fake_pack(**fns):
    """A pack module with API 1 and the given hooks."""
    m = types.ModuleType("fake_pack")
    m.API = hooks.API
    m.HOOKS = tuple(fns)
    for k, v in fns.items():
        setattr(m, k, v)
    return m


class LinuxDefaultTests(unittest.TestCase):
    """Without a pack the hooks are the Linux behaviour of main."""

    def test_no_pack_on_linux(self):
        self.assertIsNone(hooks.PACK)

    def test_memory_is_memavailable(self):
        if not Path("/proc/meminfo").exists():
            self.skipTest("no /proc")
        got = hooks.available_memory()
        want = next(int(ln.split()[1]) * 1024 for ln in Path("/proc/meminfo").read_text().splitlines()
                    if ln.startswith("MemAvailable:"))
        self.assertLess(abs(got - want), 512 << 20)      # the value moves between two reads

    def test_memory_without_proc_is_four_gib(self):
        with mock.patch.object(Path, "read_text", side_effect=OSError):
            self.assertEqual(hooks.available_memory(), 4 << 30)

    def test_data_hooks_keep_the_core_values(self):
        self.assertIsNone(hooks.tesseract_path())
        self.assertIsNone(hooks.default_library())
        self.assertIsNone(hooks.console_init())
        self.assertEqual(library.LIBRARY_DEFAULT, "/var/lib/partitor/library")

    def test_locked_hint_is_not_about_a_viewer(self):
        self.assertIn("write to the folder", hooks.locked_hint())

    def test_setup_hint_names_partitor_init(self):
        self.assertEqual(hooks.setup_hint(), "Run: partitor-init (see docs/INSTALL.md).")

    def test_library_not_ready_gives_the_platform_hint(self):
        from partitor import cli_common
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(cli_common, "library_root", return_value=Path(d)):
            hooks.install(fake_pack(setup_hint=lambda: "Run the installer again."))
            try:
                err = io.StringIO()
                with contextlib.redirect_stderr(err), self.assertRaises(SystemExit):
                    cli_common._lib_or_die()
            finally:
                hooks.uninstall()
        self.assertIn("needs inbox/ and library/", err.getvalue())
        self.assertIn("Run the installer again.", err.getvalue())
        self.assertNotIn("partitor-init", err.getvalue())


class InstallTests(unittest.TestCase):
    def tearDown(self):
        hooks.uninstall()

    def test_install_replaces_only_the_named_hooks(self):
        hooks.install(fake_pack(locked_hint=lambda: "pack hint"))
        self.assertEqual(hooks.locked_hint(), "pack hint")
        self.assertIsNone(hooks.default_library())          # not named: Linux value
        self.assertIsNotNone(hooks.PACK)

    def test_uninstall_restores_linux(self):
        hooks.install(fake_pack(locked_hint=lambda: "x", available_memory=lambda: 1))
        hooks.uninstall()
        self.assertIsNone(hooks.PACK)
        self.assertIn("write to the folder", hooks.locked_hint())
        self.assertNotEqual(hooks.available_memory(), 1)

    def test_wrong_api_is_refused(self):
        pack = fake_pack()
        pack.API = hooks.API + 1
        with self.assertRaises(hooks.PackError) as cm:
            hooks.install(pack)
        self.assertIn(f"needs API {hooks.API}", str(cm.exception))
        self.assertIsNone(hooks.PACK)

    def test_unknown_hook_name_is_refused(self):
        with self.assertRaises(hooks.PackError) as cm:
            hooks.install(fake_pack(tesseract_paht=lambda: "x"))
        self.assertIn("tesseract_paht", str(cm.exception))
        self.assertIsNone(hooks.PACK)


@needs_deps
class ApplyPackTests(unittest.TestCase):
    """cli_main.apply_pack puts the values of a pack into the core."""

    def setUp(self):
        from partitor import cli_main
        self.cli_main = cli_main
        self.tess = vision._TESS["path"]
        self.lib = library.LIBRARY_DEFAULT

    def tearDown(self):
        hooks.uninstall()
        vision._TESS["path"] = self.tess
        library.LIBRARY_DEFAULT = self.lib

    def test_pack_values_reach_the_core(self):
        calls = []
        hooks.install(fake_pack(console_init=lambda: calls.append("console"),
                                tesseract_path=lambda: "/pack/tesseract",
                                default_library=lambda: "/pack/library"))
        self.cli_main.apply_pack()
        self.assertEqual(calls, ["console"])
        self.assertEqual(vision._TESS["path"], "/pack/tesseract")
        self.assertEqual(library.LIBRARY_DEFAULT, "/pack/library")
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(library.library_root(), Path("/pack/library"))

    def test_pack_without_values_keeps_the_core_values(self):
        hooks.install(fake_pack())
        self.cli_main.apply_pack()
        self.assertEqual(vision._TESS["path"], self.tess)
        self.assertEqual(library.LIBRARY_DEFAULT, self.lib)

    def test_main_applies_the_pack_only_when_one_is_installed(self):
        with mock.patch.object(self.cli_main, "apply_pack") as ap, \
                mock.patch.object(sys, "argv", ["partitor", "--version"]), \
                contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit):
                self.cli_main._main()
            ap.assert_not_called()
            hooks.install(fake_pack())
            with self.assertRaises(SystemExit):
                self.cli_main._main()
            ap.assert_called_once()


class BoundaryTests(unittest.TestCase):
    """The rules of DESIGN.md §12.6, checked on the source."""

    def sources(self):
        return {p.name: p.read_text(encoding="utf-8") for p in sorted(PKG.glob("*.py"))}

    def test_core_has_no_os_checks_and_no_windows_code(self):
        bad = re.compile(r"\bos\.name\b|\bsys\.platform\b|platform\.system|\bmsvcrt\b|\bctypes\b|\bwindll\b|startfile")
        for name, code in self.sources().items():
            self.assertIsNone(bad.search(code), f"{name}: OS check or Windows code in the core")

    def test_core_never_imports_a_platform_pack(self):
        for name, code in self.sources().items():
            self.assertNotRegex(code, r"(import|from)\s+partitor_\w+", name)

    def test_hashed_modules_do_not_import_the_seam(self):
        hashed = stagecache.analysis_modules()
        self.assertNotIn("hooks", hashed)
        self.assertNotIn("outfile", hashed)
        for name in hashed:
            code = (PKG / f"{name}.py").read_text(encoding="utf-8")
            self.assertNotRegex(code, r"from \. import [^\n]*\bhooks\b|from \.hooks import", name)

    def test_hooks_imports_nothing_from_the_package(self):
        code = (PKG / "hooks.py").read_text(encoding="utf-8")
        self.assertNotRegex(code, r"^from \.|^import partitor", )

    def test_every_hook_has_a_linux_default(self):
        for name in hooks.HOOKS:
            self.assertTrue(callable(getattr(hooks, name)), name)

    def test_platform_docs_live_in_their_pack(self):
        root = PKG.parent.parent
        name = re.compile(r"windows|win32|macos|darwin|osx", re.I)
        core_docs = [p for p in (root / "docs").rglob("*") if p.is_file()] + list(root.glob("*.md"))
        for p in core_docs:
            self.assertIsNone(name.search(p.name), f"{p.name}: a platform doc belongs in platforms/<os>/")

    def test_every_pack_has_its_own_readme(self):
        packs = [p for p in (PKG.parent.parent / "platforms").iterdir() if p.is_dir()]
        self.assertTrue(packs)
        for p in packs:
            self.assertTrue((p / "README.md").is_file(), f"{p.name}: no README.md")

    def test_render_and_proof_write_through_outfile(self):
        render = (PKG / "render.py").read_text(encoding="utf-8")
        self.assertNotIn(".save(", render)
        self.assertIn("outfile.save_pdf(", render)
        proof = (PKG / "proof.py").read_text(encoding="utf-8")
        self.assertNotIn("os.replace(tmp", proof)


class OutfileTests(unittest.TestCase):
    def test_replace_file_moves_a_file(self):
        with tempfile.TemporaryDirectory() as td:
            a, b = Path(td, "a"), Path(td, "b")
            a.write_text("1")
            outfile.replace_file(a, b)
            self.assertEqual(b.read_text(), "1")
            self.assertFalse(a.exists())

    def test_replace_file_names_the_file(self):
        with mock.patch.object(outfile.os, "replace", side_effect=PermissionError(13, "x", "/lib/parts/Flute.pdf")):
            with self.assertRaises(outfile.WriteDenied) as cm:
                outfile.replace_file("a.tmp", "Flute.pdf")
        self.assertIn("cannot write Flute.pdf", str(cm.exception))
        self.assertNotIn("/lib/", str(cm.exception))

    def test_replace_file_names_the_folder(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td, "parts")
            src.mkdir()
            with mock.patch.object(outfile.os, "replace", side_effect=PermissionError(13, "x", str(src / "a.pdf"))):
                with self.assertRaises(outfile.WriteDenied) as cm:
                    outfile.replace_file(src, Path(td, "parts.prev"))
        self.assertIn("cannot move the folder parts", str(cm.exception))

    def test_replace_file_passes_other_errors(self):
        with mock.patch.object(outfile.os, "replace", side_effect=FileNotFoundError(2, "x")):
            with self.assertRaises(FileNotFoundError):
                outfile.replace_file("a", "b")

    def test_save_pdf_writes_the_file(self):
        doc = mock.Mock()
        outfile.save_pdf(doc, "a.pdf")
        doc.save.assert_called_once_with("a.pdf", garbage=3, deflate=True)

    def test_save_pdf_names_the_file(self):
        doc = mock.Mock()
        doc.save.side_effect = RuntimeError("code=2: cannot remove file 'parts\\01-Alto.pdf': Permission denied")
        with self.assertRaises(outfile.WriteDenied) as cm:
            outfile.save_pdf(doc, Path("parts/01-Alto.pdf"))
        self.assertIn("cannot write 01-Alto.pdf", str(cm.exception))

    def test_save_pdf_passes_other_errors(self):
        doc = mock.Mock()
        doc.save.side_effect = RuntimeError("disk full")
        with self.assertRaises(RuntimeError) as cm:
            outfile.save_pdf(doc, "a.pdf")
        self.assertNotIsInstance(cm.exception, outfile.WriteDenied)

    def test_save_pdf_on_a_read_only_folder(self):
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            self.skipTest("root can write everywhere")
        import pymupdf
        with tempfile.TemporaryDirectory() as td:
            ro = Path(td, "ro")
            ro.mkdir()
            ro.chmod(0o500)
            try:
                doc = pymupdf.open()
                doc.new_page()
                with self.assertRaises(outfile.WriteDenied):
                    outfile.save_pdf(doc, ro / "a.pdf")
            finally:
                ro.chmod(0o700)


class TextFileNewlineTests(unittest.TestCase):
    """Text files that partitor writes have LF on every system (Windows would write CRLF)."""

    def test_every_write_text_sets_newline(self):
        for path in sorted(PKG.glob("*.py")):
            code = path.read_text(encoding="utf-8")
            for m in re.finditer(r"\.write_text\(", code):
                depth, i = 1, m.end()
                while depth:
                    depth += {"(": 1, ")": -1}.get(code[i], 0)
                    i += 1
                self.assertIn('newline="\\n"', code[m.end():i], f"{path.name}: write_text without newline")

    def test_write_text_with_newline_gives_lf(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td, "a.yaml")
            p.write_text("a: 1\nb: 2\n", encoding="utf-8", newline="\n")
            self.assertEqual(p.read_bytes(), b"a: 1\nb: 2\n")


@needs_deps
class WindowsFileNameTests(unittest.TestCase):
    """The names that partitor writes are safe on Windows without a name function."""
    FORBIDDEN = set('<>:"/\\|?*') | {chr(c) for c in range(32)}
    RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{n}" for n in range(1, 10)),
                *(f"LPT{n}" for n in range(1, 10))}

    def test_slug_has_no_forbidden_character(self):
        for title in ('Sonate: Allegro? "Zürich" <1>*', "a/b\\c|d", "Gegrüßet seist du...  "):
            slug = config.slugify(title)
            self.assertFalse(set(slug) & self.FORBIDDEN, slug)
            self.assertFalse(slug.endswith((".", " ")), slug)

    def test_part_file_name_is_not_a_reserved_name(self):
        for part in ("Con", "NUL", "aux", "Com1", "LPT9", "Flute: I?"):
            name = config.part_file_name(1, part, "")
            self.assertNotIn(name.split(".")[0].upper(), self.RESERVED, name)
            self.assertFalse(set(name) & self.FORBIDDEN, name)

    def test_part_file_name_has_a_number_before_the_slug(self):
        self.assertTrue(config.part_file_name(7, "Con", "").startswith("07-"))


@needs_deps
class CapabilityTests(unittest.TestCase):
    """No fork, no flock, no geteuid: the core checks the capability, not the OS."""

    def setUp(self):
        console._reset_counts()
        parallel._NO_FORK_WARNED.clear()

    def tearDown(self):
        parallel._NO_FORK_WARNED.clear()
        console._reset_counts()

    def no_fork(self):
        return mock.patch.object(parallel, "can_fork", return_value=False)

    def test_no_fork_gives_one_job_and_one_warning(self):
        with self.no_fork(), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(parallel.job_count(None, 1.0, 10), 1)
            self.assertEqual(parallel.job_count("4", 1.0, 10), 1)       # --jobs above 1: the same
            self.assertEqual(parallel.job_count("auto", 1.0, 10), 1)
        self.assertEqual(len(console._WARNINGS), 1)
        self.assertIn("cannot fork", console._WARNINGS[0])

    def test_one_item_needs_no_warning(self):
        with self.no_fork():
            self.assertEqual(parallel.job_count("4", 1.0, 1), 1)
        self.assertEqual(console._WARNINGS, [])

    def test_with_fork_the_count_is_as_before(self):
        with mock.patch.object(parallel, "mem_available", return_value=64 << 30):
            self.assertEqual(parallel.job_count("3", 1.0, 10), 3)
        self.assertEqual(console._WARNINGS, [])

    def test_fork_map_runs_in_this_process_without_fork(self):
        with self.no_fork():
            got = list(parallel.fork_map(lambda x: (x, os.getpid()), [1, 2, 3], 3))
        self.assertEqual(got, [(1, os.getpid()), (2, os.getpid()), (3, os.getpid())])

    def test_memory_comes_from_the_hook(self):
        try:
            hooks.install(fake_pack(available_memory=lambda: 123))
            self.assertEqual(parallel.mem_available(), 123)
        finally:
            hooks.uninstall()

    def test_worker_peak_without_resource_module(self):
        with mock.patch.object(parallel, "resource", None):
            self.assertEqual(parallel.worker_peak_mb(), 0)

    def test_item_lock_without_flock_gives_no_lock(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.object(library, "fcntl", None):
            with library.item_lock(Path(td)):
                pass

    def test_a_denied_output_gives_one_error_with_the_platform_hint(self):
        from partitor import cli_main
        for pack, hint in ((None, "write to the folder"), (fake_pack(locked_hint=lambda: "Close it."), "Close it.")):
            if pack:
                hooks.install(pack)
            try:
                err = io.StringIO()
                with mock.patch.object(cli_main, "_main", side_effect=outfile.WriteDenied("cannot write Flute.pdf: permission denied")), \
                        contextlib.redirect_stderr(err):
                    with self.assertRaises(SystemExit) as cm:
                        cli_main._guarded()
            finally:
                hooks.uninstall()
            self.assertEqual(cm.exception.code, 1)
            self.assertIn("Flute.pdf", err.getvalue())
            self.assertIn(hint, err.getvalue())
            self.assertEqual(err.getvalue().count("ERROR:"), 1)

    def test_swap_parts_reports_a_denied_folder(self):
        with tempfile.TemporaryDirectory() as td:
            item = Path(td)
            (item / "parts").mkdir()
            (item / library.PARTS_NEW).mkdir()
            with mock.patch.object(outfile.os, "replace",
                                   side_effect=PermissionError(13, "x", str(item / "parts" / "Flute.pdf"))):
                with self.assertRaises(outfile.WriteDenied) as cm:
                    library.swap_parts(item)
            self.assertIn("cannot move the folder parts", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
