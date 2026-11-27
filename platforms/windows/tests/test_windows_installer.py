# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""Tests for the Windows installer helpers (platforms/windows/installer). They run on Linux with
mocks; no Windows, no network and no Inno Setup are needed. tests/test_packs.py loads them."""
import hashlib
import importlib.util
import io
import re
import struct
import subprocess
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
INST = ROOT / "platforms" / "windows" / "installer"
_spec = importlib.util.spec_from_file_location("partitor_win_bundle", INST / "bundle.py")
bundle = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bundle)


def opener_for(data: bytes):
    def opener(req):
        opener.urls.append(req.full_url)
        opener.agents.append(req.get_header("User-agent"))
        return io.BytesIO(data)
    opener.urls = []
    opener.agents = []
    return opener


def ico_frames(data):
    """{size: rows of grey values on a white ground} of an .ico with 8-bit RGBA PNG frames (no Pillow)."""
    frames = {}
    for i in range(struct.unpack("<H", data[4:6])[0]):
        length, start = struct.unpack("<II", data[14 + 16 * i:22 + 16 * i])
        png, pos, idat = data[start:start + length], 8, b""
        while pos < len(png):
            n, kind = struct.unpack(">I4s", png[pos:pos + 8])
            body, pos = png[pos + 8:pos + 8 + n], pos + 12 + n
            if kind == b"IHDR":
                width, height, depth, colour = struct.unpack(">IIBB", body[:10])
                assert (depth, colour) == (8, 6), "not 8-bit RGBA"
            elif kind == b"IDAT":
                idat += body
        raw, stride, prev, rows = zlib.decompress(idat), 4 * width, bytes(4 * width), []
        for y in range(height):
            mode, line = raw[y * (stride + 1)], bytearray(raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
            for x in range(stride):
                a, b, c = line[x - 4] if x >= 4 else 0, prev[x], prev[x - 4] if x >= 4 else 0
                p = a + b - c
                paeth = min((abs(p - a), 0, a), (abs(p - b), 1, b), (abs(p - c), 2, c))[2]
                line[x] = (line[x] + (0, a, b, (a + b) // 2, paeth)[mode]) & 255
            prev = bytes(line)
            rows.append([255 - (255 - sum(line[x:x + 3]) // 3) * line[x + 3] // 255 for x in range(0, stride, 4)])
        frames[width] = rows
    return frames


class FetchTests(unittest.TestCase):
    def test_pins_are_sha256_hex(self):
        for d in [bundle.TESSERACT_SHA256, *bundle.TESSDATA_SHA256.values()]:
            self.assertRegex(d, r"^[0-9a-f]{64}$")

    def test_language_is_english_only(self):
        """partitor calls tesseract without -l (English); no other language file is bundled."""
        self.assertEqual(set(bundle.TESSDATA_SHA256), {"eng"})

    def test_vision_calls_tesseract_without_a_language(self):
        """The reason for English only: if ocr_line gets -l, the bundle must change with it."""
        src = (Path(__file__).resolve().parents[3] / "lib" / "partitor" / "vision.py").read_text(encoding="utf-8")
        self.assertNotRegex(src, r'"-l"')

    def test_fetch_keeps_a_file_with_the_right_hash(self):
        data = b"abc"
        with tempfile.TemporaryDirectory() as d:
            dest = Path(d) / "x"
            op = opener_for(data)
            bundle.fetch("http://u", dest, hashlib.sha256(data).hexdigest(), op)
            self.assertEqual(dest.read_bytes(), data)
            bundle.fetch("http://u", dest, hashlib.sha256(data).hexdigest(), op)
            self.assertEqual(len(op.urls), 1)             # the second call used the cache

    def test_fetch_names_itself(self):
        data = b"abc"
        with tempfile.TemporaryDirectory() as d:
            op = opener_for(data)
            bundle.fetch("http://u", Path(d) / "x", hashlib.sha256(data).hexdigest(), op)
            self.assertEqual(op.agents, ["partitor-build"])

    def test_fetch_refuses_a_wrong_hash_and_leaves_no_file(self):
        with tempfile.TemporaryDirectory() as d:
            dest = Path(d) / "x"
            with self.assertRaises(bundle.BundleError):
                bundle.fetch("http://u", dest, "0" * 64, opener_for(b"abc"))
            self.assertEqual(list(Path(d).iterdir()), [])

    def test_fetch_replaces_a_cached_file_with_a_wrong_hash(self):
        data = b"good"
        with tempfile.TemporaryDirectory() as d:
            dest = Path(d) / "x"
            dest.write_bytes(b"bad")
            bundle.fetch("http://u", dest, hashlib.sha256(data).hexdigest(), opener_for(data))
            self.assertEqual(dest.read_bytes(), data)


class StageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        # every download is accepted: the pins are replaced by the hash of the fake data
        self.data = b"x"
        self.runs = []
        digest = hashlib.sha256(self.data).hexdigest()
        for target in ("TESSERACT_SHA256",):
            p = mock.patch.object(bundle, target, digest)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(bundle, "TESSDATA_SHA256", {k: digest for k in bundle.TESSDATA_SHA256})
        p.start()
        self.addCleanup(p.stop)

    def fake_run(self, stage, make_exe=True):
        def run(cmd, **kw):
            self.assertEqual(cmd[:3], ["7z", "x", "-y"])
            self.assertEqual(cmd[3], f"-o{stage}")
            self.runs.append(cmd)
            if make_exe:
                (stage / "$PLUGINSDIR").mkdir(parents=True)
                (stage / "tessdata").mkdir()
                (stage / "tesseract.exe").write_bytes(b"MZ")
                (stage / "tesseract-uninstall.exe").write_bytes(b"MZ")
                (stage / "[NSIS].nsi").write_bytes(b"")
                (stage / "libpng16-16.dll").write_bytes(b"MZ")
                (stage / "lstmtraining.exe").write_bytes(b"MZ")
                (stage / "tesseract.1.html").write_bytes(b"")
                (stage / "doc").mkdir()
                for n in ("LICENSE", "AUTHORS", "README.md"):
                    (stage / "doc" / n).write_bytes(b"")
                (stage / "tessdata" / "ScrollView.jar").write_bytes(b"")
        return run

    def stage(self, make_exe=True):
        stage = self.root / "dist" / "tesseract"
        return bundle.stage_tesseract(self.root / "cache", stage, "7z", self.fake_run(stage, make_exe),
                                      opener_for(self.data))

    def test_stage_unpacks_with_7zip_and_adds_the_english_language(self):
        stage = self.stage()
        self.assertTrue((stage / "tesseract.exe").is_file())
        for lang in bundle.TESSDATA_SHA256:
            self.assertTrue((stage / "tessdata" / f"{lang}.traineddata").is_file(), lang)

    def test_stage_removes_the_parts_of_the_installer(self):
        stage = self.stage()
        self.assertEqual(sorted(p.name for p in stage.iterdir() if p.name[0] in "$[" or "uninstall" in p.name), [])

    def test_stage_keeps_only_what_ocr_needs(self):
        stage = self.stage()
        self.assertEqual(sorted(p.name for p in stage.iterdir()),
                         ["doc", "libpng16-16.dll", "tessdata", "tesseract.exe"])
        self.assertEqual(sorted(p.name for p in (stage / "doc").iterdir()), ["AUTHORS", "LICENSE"])
        self.assertFalse(list((stage / "tessdata").glob("*.jar")))

    def test_stage_never_runs_the_installer(self):
        self.stage()
        self.assertEqual(len(self.runs), 1)
        self.assertEqual(self.runs[0][0], "7z")

    def test_stage_fails_when_the_archive_has_no_program(self):
        with self.assertRaises(bundle.BundleError):
            self.stage(make_exe=False)

    def test_check_accepts_the_pinned_version_and_languages(self):
        outs = iter([" ".join(["List of available languages (6):", *bundle.TESSDATA_SHA256]),
                     "tesseract v5.4.0.20240606\n leptonica"])
        run = lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, stdout=next(outs))  # noqa: E731
        bundle.check_tesseract(self.root, run)

    def test_check_refuses_a_missing_language(self):
        run = lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, stdout="osd")  # noqa: E731
        with self.assertRaises(bundle.BundleError):
            bundle.check_tesseract(self.root, run)

    def test_check_refuses_another_version(self):
        outs = iter([" ".join(bundle.TESSDATA_SHA256), "tesseract v5.3.4"])
        run = lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, stdout=next(outs))  # noqa: E731
        with self.assertRaises(bundle.BundleError):
            bundle.check_tesseract(self.root, run)


class SevenZipTests(unittest.TestCase):
    def test_program_files_is_found_first(self):
        with tempfile.TemporaryDirectory() as d:
            exe = Path(d) / "7-Zip" / "7z.exe"
            exe.parent.mkdir()
            exe.write_bytes(b"")
            self.assertEqual(bundle.find_7z({"ProgramFiles": d}, lambda n: None), str(exe))

    def test_path_is_the_last_choice(self):
        self.assertEqual(bundle.find_7z({}, lambda n: "X:\\7z.exe" if n == "7z" else None), "X:\\7z.exe")
        self.assertIsNone(bundle.find_7z({}, lambda n: None))


class IsccTests(unittest.TestCase):
    def test_per_user_install_is_found_first(self):
        with tempfile.TemporaryDirectory() as d:
            exe = Path(d) / "Programs" / "Inno Setup 6" / "ISCC.exe"
            exe.parent.mkdir(parents=True)
            exe.write_bytes(b"")
            self.assertEqual(bundle.find_iscc({"LOCALAPPDATA": d}, lambda n: None), str(exe))

    def test_path_is_the_last_choice(self):
        self.assertEqual(bundle.find_iscc({}, lambda n: "X:\\ISCC.exe"), "X:\\ISCC.exe")
        self.assertIsNone(bundle.find_iscc({}, lambda n: None))


class WorkflowTests(unittest.TestCase):
    """The Windows release workflow runs by hand only and cannot block Linux."""

    def setUp(self):
        import yaml
        self.path = ROOT / ".github" / "workflows" / "windows-release.yml"
        self.wf = yaml.safe_load(self.path.read_text(encoding="utf-8"))
        self.on = self.wf.get("on", self.wf.get(True))     # YAML reads `on` as True

    def test_it_starts_by_hand_only(self):
        self.assertEqual(list(self.on), ["workflow_dispatch"])

    def test_it_asks_for_a_tag(self):
        self.assertTrue(self.on["workflow_dispatch"]["inputs"]["tag"]["required"])

    def test_the_tag_is_not_pasted_into_a_script(self):
        text = self.path.read_text(encoding="utf-8")
        self.assertNotIn("run: ${{", text)
        self.assertNotRegex(text, r"\$\{\{\s*inputs\.tag\s*\}\}[^\n]*\n(?=\s+(run|shell))")
        for step in self.wf["jobs"]["build"]["steps"]:
            self.assertNotIn("inputs.", step.get("run", ""))

    def test_a_new_release_is_a_draft(self):
        self.assertIn("--draft", self.path.read_text(encoding="utf-8"))

    def test_it_builds_with_the_pack_script(self):
        self.assertIn("platforms\\windows\\build-windows.py --installer", self.path.read_text(encoding="utf-8"))


class ScriptTests(unittest.TestCase):
    """The Inno Setup script keeps the decisions of the maintainer."""

    def setUp(self):
        self.iss = (INST / "partitor.iss").read_text(encoding="utf-8")

    def test_per_user_without_admin(self):
        self.assertIn("PrivilegesRequired=lowest", self.iss)
        self.assertRegex(self.iss, r"DefaultDirName=\{autopf\}\\partitor")

    def test_library_is_never_removed(self):
        for line in re.findall(r'^Name: "\{code:LibDir\}[^\n]*', self.iss, re.M):
            self.assertIn("uninsneveruninstall", line)

    def test_library_default_is_documents_partitor(self):
        self.assertIn(r"{userdocs}\partitor", self.iss)

    def test_path_and_variable_are_set_for_the_user_only(self):
        self.assertIn("HKCU", self.iss)
        self.assertNotIn("HKLM", self.iss)
        self.assertIn("PARTITOR_LIBRARY", self.iss)

    def test_no_brace_comment_holds_a_constant(self):
        """In Inno Pascal a `{ ... }` comment ends at the first `}`: `{app}` inside one breaks the build."""
        code = self.iss.split("[Code]", 1)[1]
        for line in code.splitlines():
            if line.lstrip().startswith("{"):
                self.assertNotIn("{", line.lstrip()[1:], line)

    def test_icon_file_has_the_sizes(self):
        data = (INST / "partitor.ico").read_bytes()
        reserved, kind, count = struct.unpack("<HHH", data[:6])
        self.assertEqual((reserved, kind), (0, 1))
        sizes = {data[6 + 16 * i] or 256 for i in range(count)}
        self.assertEqual(sizes, {16, 24, 32, 48, 64, 128, 256})

    def test_icon_stroke_is_thin_and_flush_right_at_every_size(self):
        """The stroke under the rectangle ends on the same pixel column as the rectangle."""
        frames = ico_frames((INST / "partitor.ico").read_bytes())
        for size in (16, 24, 32, 48, 64, 128, 256):
            with self.subTest(size=size):
                grey = frames[size]
                runs = []                           # first run of ink from the left, per row
                for y in range(size):
                    ink = [x for x in range(size) if grey[y][x] < 250]
                    if ink and ink[0] < size * 45 // 100:  # rows of the rectangle and of the stroke
                        end = ink[0]
                        while end + 1 in ink:
                            end += 1
                        runs.append((ink[0], end))
                left = min(a for a, _ in runs)
                rect = [r for r in runs if r[0] == left]
                stroke = [r for r in runs if r[0] != left]
                self.assertTrue(rect and stroke, runs)
                self.assertEqual(len({b for _, b in runs}), 1, runs)
                self.assertEqual(len(set(stroke)), 1, runs)
                width = stroke[0][1] - stroke[0][0] + 1
                self.assertLessEqual(width, max(2, size // 40), runs)

    def test_installer_and_program_use_the_icon(self):
        self.assertIn("SetupIconFile=partitor.ico", self.iss)
        build = (ROOT / "platforms" / "windows" / "build-windows.py").read_text(encoding="utf-8")
        self.assertIn("platforms/windows/installer/partitor.ico", build)

    def test_script_has_an_spdx_line(self):
        self.assertIn("SPDX-License-Identifier: AGPL-3.0-or-later", self.iss.splitlines()[0])
