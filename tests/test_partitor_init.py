# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""Tests for bin/partitor-init (guided setup). The installer is a stub that
records its arguments and the config file it gets. No root, no systemd.

Run: python3 -m unittest -v tests/test_partitor_init.py
"""
import os
import shutil
import stat
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
INIT = os.path.join(ROOT, "bin", "partitor-init")


class InitFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pt-init-")
        self.pfx = os.path.join(self.tmp, "root")
        os.makedirs(os.path.join(self.pfx, "etc", "default"))
        self.log = os.path.join(self.tmp, "installer.log")
        self.stub = os.path.join(self.tmp, "partitor-install")
        with open(self.stub, "w") as f:
            f.write('#!/bin/sh\n{ echo "args: $*"; [ "$1" = --config ] && cat "$2"; } > "$STUB_LOG"\n'
                    'exit "${STUB_RC:-0}"\n')
        os.chmod(self.stub, 0o755)
        self.defaults = os.path.join(self.pfx, "etc", "default", "partitor")
        self.cred = os.path.join(self.pfx, "etc", "partitor", "smb.cred")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_i(self, answers="", *args, extra=None):
        env = dict(os.environ, PARTITOR_PREFIX=self.pfx, PARTITOR_INSTALL=self.stub,
                   PARTITOR_ROOT=ROOT, PARTITOR_TEST_NONROOT="1", STUB_LOG=self.log)
        env.update(extra or {})
        return subprocess.run(["bash", INIT, *args], env=env, input=answers,
                              capture_output=True, text=True, cwd=self.tmp)

    def logged(self):
        if not os.path.exists(self.log):
            return ""
        with open(self.log, encoding="utf-8") as fh:
            return fh.read()


class TestInit(InitFixture):
    def test_local_defaults_with_yes(self):
        r = self.run_i("", "--yes")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        log = self.logged()
        self.assertIn("args: --config ", log)
        self.assertIn("PARTITOR_LIBRARY=/var/lib/partitor/library", log)
        self.assertIn("PARTITOR_MEMORY_MAX=auto", log)
        self.assertNotIn("PARTITOR_SMB_HOST", log)
        self.assertNotIn("PARTITOR_LOGO", log)

    def test_interactive_local_other_path(self):
        # mode, path, memory, logo, go on
        r = self.run_i("1\n/data/scores\n8G\n\ny\n")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        log = self.logged()
        self.assertIn("PARTITOR_LIBRARY=/data/scores", log)
        self.assertIn("PARTITOR_MEMORY_MAX=8G", log)

    def test_interactive_smb_writes_credentials_not_shown(self):
        # mode, mount point, host, share, user, password, memory, logo, go on
        r = self.run_i("2\n\nnas.example.net\n\nnasuser\ns3cret-pw\n\n\ny\n")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        log = self.logged()
        self.assertIn("PARTITOR_LIBRARY=/mnt/partitor", log)
        self.assertIn("PARTITOR_SMB_HOST=nas.example.net", log)
        self.assertIn("PARTITOR_SMB_SHARE=partitor", log)
        self.assertNotIn("s3cret-pw", log)
        self.assertNotIn("s3cret-pw", r.stdout + r.stderr)
        with open(self.cred, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "username=nasuser\npassword=s3cret-pw\n")
        self.assertEqual(stat.S_IMODE(os.stat(self.cred).st_mode), 0o600)

    def test_existing_credentials_can_be_kept(self):
        os.makedirs(os.path.dirname(self.cred))
        with open(self.cred, "w") as f:
            f.write("username=old\npassword=old-pw\n")
        r = self.run_i("2\n\nnas.example.net\n\ny\n\n\ny\n")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        with open(self.cred) as fh:
            self.assertIn("old-pw", fh.read())

    def test_other_keys_are_kept_and_managed_keys_replaced(self):
        with open(self.defaults, "w") as f:
            f.write("PARTITOR_JOBS=2\nPARTITOR_MEMORY_MAX=3G\nPARTITOR_LIBRARY=/old\n")
        r = self.run_i("", "--yes", "--library", "/new/lib")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        log = self.logged()
        self.assertIn("PARTITOR_JOBS=2", log)
        self.assertIn("PARTITOR_MEMORY_MAX=3G", log)       # current value is the default
        self.assertIn("PARTITOR_LIBRARY=/new/lib", log)
        self.assertNotIn("/old", log)

    def test_existing_smb_host_is_the_default_mode(self):
        with open(self.defaults, "w") as f:
            f.write("PARTITOR_LIBRARY=/mnt/partitor\nPARTITOR_SMB_HOST=192.0.2.10\n")
        os.makedirs(os.path.dirname(self.cred))
        with open(self.cred, "w") as f:
            f.write("username=u\npassword=p\n")
        r = self.run_i("", "--yes")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("PARTITOR_SMB_HOST=192.0.2.10", self.logged())

    def test_bad_values_are_asked_again(self):
        r = self.run_i("1\nrelative/path\n/ok/path\n\n\ny\n")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("absolute path", r.stderr)
        self.assertIn("PARTITOR_LIBRARY=/ok/path", self.logged())

    def test_bad_value_with_yes_fails(self):
        r = self.run_i("", "--yes", "--library", "relative")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(self.logged(), "")

    def test_library_in_home_refused(self):
        r = self.run_i("", "--yes", "--library", "/home/me/scores")
        self.assertEqual(r.returncode, 1)
        self.assertIn("/home", r.stderr)

    def test_no_answer_to_go_on_stops_without_change(self):
        r = self.run_i("1\n\n\n\nn\n")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(self.logged(), "")
        self.assertFalse(os.path.exists(self.cred))

    def test_no_install_writes_the_file_only(self):
        out = os.path.join(self.tmp, "my.conf")
        r = self.run_i("", "--yes", "--no-install", "--out", out, "--memory", "6G")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.logged(), "")
        with open(out) as fh:
            self.assertIn("PARTITOR_MEMORY_MAX=6G", fh.read())
        self.assertIn("--config " + out, r.stdout)

    def test_logo_option_is_written(self):
        logo = os.path.join(self.pfx, "etc", "partitor", "logo.png")
        os.makedirs(os.path.dirname(logo))
        open(logo, "wb").close()
        r = self.run_i("", "--yes", "--logo", "/etc/partitor/logo.png")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("PARTITOR_LOGO=/etc/partitor/logo.png", self.logged())
        self.assertNotIn("WARN", r.stderr)

    def test_missing_logo_gives_a_warning_only(self):
        r = self.run_i("", "--yes", "--logo", "/nope/logo.png")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("WARN logo file not found", r.stderr)

    def test_installer_failure_code_is_passed_on(self):
        r = self.run_i("", "--yes", extra={"STUB_RC": "1"})
        self.assertEqual(r.returncode, 1)

    def test_temp_config_is_removed(self):
        r = self.run_i("", "--yes")
        self.assertEqual(r.returncode, 0)
        conf = [ln for ln in self.logged().splitlines() if ln.startswith("args:")][0].split()[-1]
        self.assertFalse(os.path.exists(conf))

    def test_non_root_refused(self):
        r = self.run_i("", "--yes", extra={"PARTITOR_TEST_NONROOT": "0"})
        if os.geteuid() != 0:
            self.assertEqual(r.returncode, 1)
            self.assertIn("run as root", r.stderr)

    def test_unknown_option_is_usage_error(self):
        r = self.run_i("", "--frobnicate")
        self.assertEqual(r.returncode, 1)
        self.assertIn("usage:", r.stderr)


class TestHints(unittest.TestCase):
    def test_hints_name_an_existing_script(self):
        for f in ("bin/partitor", "lib/partitor-engine"):
            with open(os.path.join(ROOT, f), encoding="utf-8") as fh:
                self.assertIn("partitor-init", fh.read())
        self.assertTrue(os.access(INIT, os.X_OK))

    def test_installer_links_the_three_commands(self):
        with open(os.path.join(ROOT, "bin", "partitor-install"), encoding="utf-8") as fh:
            self.assertIn("for name in partitor partitor-init partitor-install", fh.read())


if __name__ == "__main__":
    unittest.main()
