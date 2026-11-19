# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""Tests for bin/partitor-quick-install: apt, partitor-init and the group are stubs."""
import os
import shutil
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
QUICK = os.path.join(ROOT, "bin", "partitor-quick-install")


class QuickInstall(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pt-quick-")
        self.bin = os.path.join(self.tmp, "stubs")
        os.makedirs(self.bin)
        self.log = os.path.join(self.tmp, "calls.log")
        self.pfx = os.path.join(self.tmp, "root")
        os.makedirs(os.path.join(self.pfx, "etc", "default"))
        self.stub("apt-get", 'echo "apt-get $*" >> "$STUB_LOG"; exit "${STUB_APT_RC:-0}"')
        self.stub("usermod", 'echo "usermod $*" >> "$STUB_LOG"')
        self.stub("dpkg-query", 'echo "${STUB_DPKG:-}"')
        self.stub("partitor-init", 'echo "init $*" >> "$STUB_LOG"; exit "${STUB_INIT_RC:-0}"')

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def stub(self, name, body):
        path = os.path.join(self.bin, name)
        with open(path, "w") as f:
            f.write("#!/bin/sh\n" + body + "\n")
        os.chmod(path, 0o755)

    def run_q(self, *args, **env):
        e = dict(os.environ, PATH=self.bin + os.pathsep + os.environ["PATH"],
                 PARTITOR_PREFIX=self.pfx, PARTITOR_ROOT=ROOT, PARTITOR_TEST_NONROOT="1",
                 PARTITOR_INIT=os.path.join(self.bin, "partitor-init"), STUB_LOG=self.log)
        e.pop("SUDO_USER", None)
        e.update(env)
        r = subprocess.run(["bash", QUICK, *args], env=e, capture_output=True, text=True)
        calls = ""
        if os.path.exists(self.log):
            with open(self.log) as f:
                calls = f.read()
        return r, calls

    def test_installs_missing_packages_then_init_then_group(self):
        r, calls = self.run_q(SUDO_USER="anna")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("apt-get install -y python3-venv tesseract-ocr", calls)
        self.assertIn("init --yes", calls)
        self.assertIn("usermod -aG partitor anna", calls)
        self.assertLess(calls.index("apt-get"), calls.index("init"))
        self.assertIn("/var/lib/partitor/library/inbox/", r.stdout)

    def test_no_apt_when_packages_are_there(self):
        r, calls = self.run_q(STUB_DPKG="install ok installed", SUDO_USER="anna")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("apt-get", calls)

    def test_options_go_to_init(self):
        r, calls = self.run_q("--library", "/data/scores", SUDO_USER="anna")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("init --yes --library /data/scores", calls)

    def test_library_from_settings_file_is_named(self):
        with open(os.path.join(self.pfx, "etc", "default", "partitor"), "w") as f:
            f.write('PARTITOR_LIBRARY="/data/scores"\n')
        r, _ = self.run_q(SUDO_USER="anna")
        self.assertIn("/data/scores/inbox/", r.stdout)

    def test_no_sudo_user_prints_the_command(self):
        r, calls = self.run_q()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("usermod", calls)
        self.assertIn("sudo usermod -aG partitor", r.stdout)

    def test_apt_failure_stops_before_init(self):
        r, calls = self.run_q(STUB_APT_RC="1", SUDO_USER="anna")
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn("init", calls)

    def test_init_failure_stops(self):
        r, calls = self.run_q(STUB_INIT_RC="3", SUDO_USER="anna")
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn("usermod", calls)

    def test_needs_root(self):
        e = dict(os.environ, PARTITOR_ROOT=ROOT)
        e.pop("PARTITOR_TEST_NONROOT", None)
        if os.geteuid() == 0:
            self.skipTest("running as root")
        r = subprocess.run(["bash", QUICK], env=e, capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("run as root", r.stderr)


if __name__ == "__main__":
    unittest.main()
