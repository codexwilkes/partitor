# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""Tests for the partitor wrapper (bin/partitor) and the installer
(bin/partitor-install).

No root, no systemd, no venv packages: systemd-run, dpkg-query, getent,
useradd, python3 (venv) and pip are stubs; paths live in a temp tree
(PARTITOR_STATE / PARTITOR_PREFIX). The live sandbox is checked by
the installer self-test (partitor --sandbox-check).

Run: python3 -m unittest -v tests/test_partitor_setup.py
"""
import os
import shutil
import stat
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
WRAPPER = os.path.join(ROOT, "bin", "partitor")
SETUP = os.path.join(ROOT, "bin", "partitor-install")
ME = subprocess.check_output(["id", "-un"], text=True).strip()


def write(path, text, mode=0o755):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.chmod(path, mode)


class TestWrapper(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pt-wrap-")
        self.state = os.path.join(self.tmp, "state")
        self.work = os.path.join(self.state, "work")
        os.makedirs(self.work)
        self.engine = os.path.join(self.tmp, "engine")
        write(self.engine, "#!/bin/sh\nexit 0\n")
        self.args_log = os.path.join(self.tmp, "args")
        self.stub = os.path.join(self.tmp, "systemd-run")
        write(self.stub, "#!/bin/sh\nprintf '%s\\n' \"$@\" > \"$STUB_LOG\"\n"
                         "exit \"${STUB_RC:-0}\"\n")
        write(os.path.join(self.work, "score.pdf"), "%PDF-1.4\n", 0o644)
        write(os.path.join(self.tmp, "outside.pdf"), "%PDF-1.4\n", 0o644)
        self.share = os.path.join(self.tmp, "share")
        self.meminfo = os.path.join(self.tmp, "meminfo")
        write(self.meminfo, "MemTotal: 16777216 kB\n", 0o644)

    def make_share(self):
        for d in ("inbox", "library"):
            os.makedirs(os.path.join(self.share, d), exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_w(self, *args, cwd=None, extra=None):
        env = dict(os.environ, PARTITOR_TEST_NONROOT="1", PARTITOR_SYSTEMD_RUN=self.stub,
                   PARTITOR_ENGINE=self.engine, PARTITOR_STATE=self.state,
                   PARTITOR_DEFAULTS=os.path.join(self.tmp, "none"), STUB_LOG=self.args_log,
                   PARTITOR_LIBRARY=self.share, PARTITOR_MEMINFO=self.meminfo)
        env.update(extra or {})
        return subprocess.run(["bash", WRAPPER, *args], cwd=cwd or self.work, env=env,
                              capture_output=True, text=True, stdin=subprocess.DEVNULL)

    def args(self):
        with open(self.args_log, encoding="utf-8") as fh:
            return fh.read().splitlines()

    def test_sandbox_properties_and_engine_command(self):
        r = self.run_w("detect", "score.pdf", "--pages", "2-3")
        self.assertEqual(r.returncode, 0, r.stderr)
        a = self.args()
        for want in ("--uid=partitor", "--gid=partitor", "--wait", "--collect",
                     f"--working-directory={os.path.realpath(self.work)}",
                     "ProtectSystem=strict", "ProtectHome=yes", "PrivateNetwork=yes",
                     "PrivateTmp=yes", "NoNewPrivileges=yes", "CapabilityBoundingSet=",
                     "RestrictAddressFamilies=AF_UNIX", f"ReadWritePaths={self.state}",
                     "MemoryMax=11468M", "CPUWeight=20", "IOWeight=20"):
            self.assertIn(want, a)
        self.assertEqual(a[a.index("--"):], ["--", self.engine, "detect", "score.pdf",
                                             "--pages", "2-3"])

    def test_pipe_mode_without_terminal(self):
        self.run_w("--version")
        self.assertIn("--pipe", self.args())
        self.assertNotIn("--pty", self.args())

    def test_never_pty_and_color_follows_stdout(self):
        # 1.0.10: systemd-run --pty ends the session with ESC[!p (some terminals clear the screen)
        self.run_w("--version")
        a = self.args()
        self.assertNotIn("--pty", a)
        self.assertIn("--pipe", a)
        self.assertIn("--setenv=PARTITOR_COLOR=0", a)        # stdout is a pipe here
        self.assertIn("--setenv=PYTHONUNBUFFERED=1", a)      # a pipe would block-buffer the output
        import pty
        master, slave = pty.openpty()
        try:
            env = dict(os.environ, PARTITOR_TEST_NONROOT="1", PARTITOR_SYSTEMD_RUN=self.stub,
                       PARTITOR_ENGINE=self.engine, PARTITOR_STATE=self.state,
                       PARTITOR_DEFAULTS=os.path.join(self.tmp, "none"),
                       STUB_LOG=self.args_log, PARTITOR_LIBRARY=self.share)
            r = subprocess.run(["bash", WRAPPER, "--version"], cwd=self.work, env=env,
                               stdin=slave, stdout=slave, stderr=subprocess.PIPE, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
        finally:
            os.close(master)
            os.close(slave)
        a = self.args()
        self.assertNotIn("--pty", a)                         # also with a terminal on stdin and stdout
        self.assertIn("--pipe", a)
        self.assertIn("--setenv=PARTITOR_COLOR=1", a)

    def test_wrapper_header_has_no_pty_mode(self):
        with open(WRAPPER, encoding="utf-8") as fh:
            txt = fh.read()
        self.assertNotIn('mode="--pty"', txt)

    def test_refuses_outside_work_folder(self):
        r = self.run_w("detect", "outside.pdf", cwd=self.tmp)
        self.assertEqual(r.returncode, 2)
        self.assertIn("inside", r.stderr)
        self.assertFalse(os.path.exists(self.args_log))

    def test_refuses_absolute_and_escaping_paths(self):
        for args in (("detect", os.path.join(self.tmp, "outside.pdf")),
                     ("detect", "../../outside.pdf"),
                     ("build", "score.pdf", "--out=/etc/x"),
                     ("build", "score.pdf", "--out", "/etc/x")):
            with self.subTest(args=args):
                r = self.run_w(*args)
                self.assertEqual(r.returncode, 2, r.stderr)
                self.assertIn("outside", r.stderr)

    def test_version_runs_from_anywhere_in_work_folder(self):
        r = self.run_w("--version", cwd=self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(f"--working-directory={os.path.realpath(self.work)}", self.args())

    def test_engine_exit_code_passed_through(self):
        r = self.run_w("detect", "score.pdf", extra={"STUB_RC": "3"})
        self.assertEqual(r.returncode, 3)

    def test_defaults_file_overrides_limits(self):
        d = os.path.join(self.tmp, "defaults")
        write(d, "PARTITOR_MEMORY_MAX=1500M\nPARTITOR_CPU_WEIGHT=10\n", 0o644)
        self.run_w("--version", extra={"PARTITOR_DEFAULTS": d})
        self.assertIn("MemoryMax=1500M", self.args())
        self.assertIn("CPUWeight=10", self.args())

    def test_missing_work_folder_refused(self):
        shutil.rmtree(self.work)
        r = self.run_w("--version", cwd=self.tmp)
        self.assertEqual(r.returncode, 2)
        self.assertIn("partitor-install", r.stderr)

    def test_no_command_opens_menu_with_share_writable(self):
        self.make_share()
        r = self.run_w(cwd=self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr)
        a = self.args()
        self.assertIn(f"ReadWritePaths={self.state} {self.share}", a)
        self.assertIn(f"--setenv=PARTITOR_LIBRARY={self.share}", a)
        self.assertEqual(a[a.index("--"):], ["--", self.engine, "menu"])

    def test_library_command_needs_share(self):
        r = self.run_w("list", cwd=self.tmp)
        self.assertEqual(r.returncode, 2)
        self.assertIn("library folder not reachable", r.stderr)
        self.assertFalse(os.path.exists(self.args_log))

    def test_reid_and_analyse_all_need_share(self):
        # wrapper 1.0.4: reid (partitor 0.3.0-dev.14) failed on without the library folder;
        # 1.0.7: proof
        for cmd in (["reid", "2026-001"], ["analyse", "--all"], ["rename", "12"], ["proof", "12"]):
            with self.subTest(cmd=cmd):
                r = self.run_w(*cmd, cwd=self.tmp)
                self.assertEqual(r.returncode, 2)
                self.assertIn("library folder not reachable", r.stderr)

    def test_list_page_passed_and_checked(self):
        self.make_share()
        self.run_w("list", cwd=self.tmp)
        self.assertIn("--setenv=PARTITOR_LIST_PAGE=20", self.args())

    def test_jobs_and_memory_cap_passed_to_the_engine(self):
        # wrapper 1.0.9: workers of a build; a bad value falls back to auto
        self.make_share()
        self.run_w("list", cwd=self.tmp)
        a = self.args()
        self.assertIn("--setenv=PARTITOR_JOBS=auto", a)
        self.assertIn("--setenv=PARTITOR_MEMORY_MAX=11468M", a)
        d = os.path.join(self.tmp, "defaults")
        for given, want in (("4", "4"), ("x7", "auto"), ("auto", "auto")):
            with self.subTest(given=given):
                write(d, f"PARTITOR_JOBS={given}\n", 0o644)
                self.run_w("list", cwd=self.tmp, extra={"PARTITOR_DEFAULTS": d})
                self.assertIn(f"--setenv=PARTITOR_JOBS={want}", self.args())

    def test_rebuild_parts_are_words_not_paths(self):
        self.make_share()
        r = self.run_w("rebuild", "12", "Trombones", "2-4", "--jobs", "3", cwd=self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.args()[-6:], ["rebuild", "12", "Trombones", "2-4", "--jobs", "3"])

    def test_library_values_are_not_paths(self):
        self.make_share()
        r = self.run_w("set", "12", "title=/etc/x", cwd=self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.args()[-3:], ["set", "12", "title=/etc/x"])

    def test_engine_commands_keep_share_closed(self):
        self.make_share()
        self.run_w("detect", "score.pdf")
        self.assertIn(f"ReadWritePaths={self.state}", self.args())

    def test_sandbox_check_library_flag(self):
        self.make_share()
        self.run_w("--sandbox-check", "--library", cwd=self.tmp)
        self.assertIn(f"ReadWritePaths={self.state} {self.share}", self.args())

    def test_memory_cap_auto_is_70_percent_of_the_machine(self):
        self.make_share()
        mi = os.path.join(self.tmp, "meminfo2")
        for kb, want in ((16777216, "11468M"), (1048576, "1024M"), (None, "2867M")):
            with self.subTest(kb=kb):
                write(mi, f"MemTotal: {kb} kB\n" if kb else "garbage\n", 0o644)
                self.run_w("list", cwd=self.tmp, extra={"PARTITOR_MEMINFO": mi})
                a = self.args()
                self.assertIn(f"--setenv=PARTITOR_MEMORY_MAX={want}", a)
                self.assertIn(f"MemoryMax={want}", a)

    def test_explicit_memory_cap_wins(self):
        self.make_share()
        d = os.path.join(self.tmp, "defaults")
        write(d, "PARTITOR_MEMORY_MAX=8G\n", 0o644)
        self.run_w("list", cwd=self.tmp, extra={"PARTITOR_DEFAULTS": d})
        self.assertIn("--setenv=PARTITOR_MEMORY_MAX=8G", self.args())

    def test_library_from_defaults_file_and_env_wins(self):
        other = os.path.join(self.tmp, "other")
        for d in ("inbox", "library"):
            os.makedirs(os.path.join(other, d))
        df = os.path.join(self.tmp, "defaults")
        write(df, f"PARTITOR_LIBRARY={other}\n", 0o644)
        self.run_w("list", cwd=self.tmp, extra={"PARTITOR_DEFAULTS": df, "PARTITOR_LIBRARY": ""})
        self.assertIn(f"--setenv=PARTITOR_LIBRARY={other}", self.args())
        self.make_share()
        self.run_w("list", cwd=self.tmp, extra={"PARTITOR_DEFAULTS": df})
        self.assertIn(f"--setenv=PARTITOR_LIBRARY={self.share}", self.args())

    def test_library_must_be_absolute(self):
        r = self.run_w("list", cwd=self.tmp, extra={"PARTITOR_LIBRARY": "rel/path"})
        self.assertEqual(r.returncode, 2)
        self.assertIn("absolute", r.stderr)

    def test_logo_passed_only_when_set(self):
        self.make_share()
        self.run_w("list", cwd=self.tmp)
        self.assertFalse([x for x in self.args() if "PARTITOR_LOGO" in x])
        self.run_w("list", cwd=self.tmp, extra={"PARTITOR_LOGO": "/opt/x/logo.png"})
        self.assertIn("--setenv=PARTITOR_LOGO=/opt/x/logo.png", self.args())

    def test_smb_host_gives_mount_hint_local_gives_init_hint(self):
        r = self.run_w("list", cwd=self.tmp)
        self.assertIn("partitor-init", r.stderr)
        df = os.path.join(self.tmp, "defaults")
        write(df, "PARTITOR_SMB_HOST=nas.example.net\n", 0o644)
        r = self.run_w("list", cwd=self.tmp, extra={"PARTITOR_DEFAULTS": df})
        self.assertIn("automount", r.stderr)

    def test_default_engine_is_venv_python_with_repo_engine(self):
        repo = os.path.join(self.tmp, "repo")
        for d in ("bin", "lib", "venv/bin"):
            os.makedirs(os.path.join(repo, d))
        shutil.copy(WRAPPER, os.path.join(repo, "bin", "partitor"))
        write(os.path.join(repo, "lib", "partitor-engine"), "# engine\n", 0o644)
        env = dict(os.environ, PARTITOR_TEST_NONROOT="1", PARTITOR_SYSTEMD_RUN=self.stub,
                   PARTITOR_STATE=self.state, PARTITOR_DEFAULTS=os.path.join(self.tmp, "none"),
                   STUB_LOG=self.args_log, PARTITOR_LIBRARY=self.share,
                   PARTITOR_MEMINFO=self.meminfo)
        env.pop("PARTITOR_ENGINE", None)
        cmd = ["bash", os.path.join(repo, "bin", "partitor"), "--version"]
        r = subprocess.run(cmd, cwd=self.work, env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)                       # no venv python yet
        self.assertIn("venv not found", r.stderr)
        write(os.path.join(repo, "venv", "bin", "python3"), "#!/bin/sh\n")
        r = subprocess.run(cmd, cwd=self.work, env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        a = self.args()
        real = os.path.realpath(repo)
        self.assertEqual(a[a.index("--"):], ["--", f"{real}/venv/bin/python3",
                                             f"{real}/lib/partitor-engine", "--version"])

    @unittest.skipIf(os.geteuid() == 0, "running as root")
    def test_non_root_refused(self):
        env = dict(os.environ, PARTITOR_SYSTEMD_RUN=self.stub, PARTITOR_ENGINE=self.engine,
                   PARTITOR_STATE=self.state)
        r = subprocess.run(["bash", WRAPPER, "--version"], env=env, capture_output=True,
                           text=True)
        self.assertEqual(r.returncode, 2)
        self.assertIn("root", r.stderr)


class TestVersion(unittest.TestCase):
    def test_one_version_for_repo_engine_and_wrapper(self):
        with open(os.path.join(ROOT, "VERSION"), encoding="utf-8") as fh:
            ver = fh.read().strip()
        with open(os.path.join(ROOT, "lib", "partitor-engine"), encoding="utf-8") as fh:
            self.assertIn(f'VERSION = "{ver}"', fh.read())
        env = dict(os.environ, PARTITOR_TEST_NONROOT="1")
        r = subprocess.run(["bash", WRAPPER, "--wrapper-version"], env=env,
                           capture_output=True, text=True)
        self.assertEqual(r.stdout.strip(), f"partitor wrapper {ver}")


class SetupFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pt-setup-")
        self.pfx = os.path.join(self.tmp, "root")
        self.opt = os.path.join(self.pfx, "opt", "partitor")          # the repo folder
        os.makedirs(self.opt)
        os.makedirs(os.path.join(self.opt, "share", "systemd"))
        for kind in ("mount", "automount"):
            shutil.copy(os.path.join(ROOT, "share", "systemd", f"library.{kind}.in"),
                        os.path.join(self.opt, "share", "systemd"))
        os.makedirs(os.path.join(self.pfx, "var", "lib"))
        self.req = os.path.join(self.opt, "requirements.txt")
        write(self.req, "numpy==2.5.3\n", 0o644)
        self.stubs = os.path.join(self.tmp, "stubs")
        os.makedirs(self.stubs)
        self.log = os.path.join(self.tmp, "calls")
        self.passwd = os.path.join(self.tmp, "passwd")
        write(os.path.join(self.stubs, "dpkg-query"),
              "#!/bin/sh\nfor a; do pkg=$a; done\n"
              "for p in $STUB_MISSING; do [ \"$p\" = \"$pkg\" ] && exit 1; done\n"
              "printf 'install ok installed'\n")
        write(os.path.join(self.stubs, "getent"),
              "#!/bin/sh\n[ -f \"$STUB_PASSWD\" ] && grep \"^$2:\" \"$STUB_PASSWD\" || exit 2\n")
        write(os.path.join(self.stubs, "useradd"),
              "#!/bin/sh\necho \"useradd $*\" >> \"$STUB_LOG\"\n"
              "for a; do last=$a; done\n"
              "echo \"$last:x:999:999::$STUB_HOME:/usr/sbin/nologin\" > \"$STUB_PASSWD\"\n")
        write(os.path.join(self.stubs, "python3"),
              "#!/bin/sh\necho \"python3 $*\" >> \"$STUB_LOG\"\nv=$3\nmkdir -p \"$v/bin\"\n"
              "printf '#!/bin/sh\\nexit 0\\n' > \"$v/bin/python3\"\n"
              "printf '#!/bin/sh\\necho \"pip $*\" >> \"$STUB_LOG\"\\nexit 0\\n' > \"$v/bin/pip\"\n"
              "chmod 755 \"$v/bin/python3\" \"$v/bin/pip\"\n")

        write(os.path.join(self.stubs, "systemctl"),
              "#!/bin/sh\necho \"systemctl $*\" >> \"$STUB_LOG\"\n"
              "[ \"$1\" = is-enabled ] && exit \"${STUB_ENABLED_RC:-1}\"\nexit 0\n")
        self.defaults = os.path.join(self.pfx, "etc", "default", "partitor")
        self.cred = os.path.join(self.pfx, "etc", "partitor", "smb.cred")
        self.units = os.path.join(self.pfx, "etc", "systemd", "system")
        self.libdir = os.path.join(self.pfx, "mnt", "partitor")        # smb library (mount point)
        self.locallib = os.path.join(self.pfx, "var", "lib", "partitor", "library")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def configure(self, smb=True, cred=True, mode=0o600, extra=""):
        """Write /etc/default/partitor (smb: host and library /mnt/partitor) and the credentials."""
        os.makedirs(os.path.dirname(self.defaults), exist_ok=True)
        text = "PARTITOR_MEMORY_MAX=3G\n"
        if smb:
            text += "PARTITOR_LIBRARY=/mnt/partitor\nPARTITOR_SMB_HOST=192.0.2.10\n"
        write(self.defaults, text + extra, 0o644)
        if cred:
            os.makedirs(os.path.dirname(self.cred), exist_ok=True)
            write(self.cred, "username=partitor\npassword=secret-not-shown\n", mode)

    def run_s(self, *args, extra=None):
        grp = subprocess.check_output(["id", "-gn"], text=True).strip()
        env = dict(os.environ, PATH=self.stubs + os.pathsep + os.environ["PATH"],
                   PARTITOR_PREFIX=self.pfx, PARTITOR_ROOT=self.opt, PARTITOR_SVC_USER=ME,
                   PARTITOR_SKIP_SELFTEST="1", STUB_LOG=self.log, STUB_PASSWD=self.passwd,
                   STUB_HOME=os.path.join(self.pfx, "var", "lib", "partitor"), STUB_MISSING="",
                   PARTITOR_SYSTEMCTL="systemctl", PARTITOR_CRED_OWNER=f"{ME}:{grp}")
        env.update(extra or {})
        return subprocess.run(["bash", SETUP, *args], env=env, capture_output=True, text=True)

    def calls(self):
        if not os.path.exists(self.log):
            return ""
        with open(self.log, encoding="utf-8") as fh:
            return fh.read()


class TestSetup(SetupFixture):
    def test_missing_apt_package_stops_with_command(self):
        r = self.run_s(extra={"STUB_MISSING": "tesseract-ocr"})
        self.assertEqual(r.returncode, 1)
        self.assertIn("Run: sudo apt install tesseract-ocr", r.stdout)
        self.assertEqual(self.calls(), "")

    def test_cifs_utils_needed_only_in_smb_mode(self):
        r = self.run_s(extra={"STUB_MISSING": "cifs-utils"})
        self.assertEqual(r.returncode, 0, r.stdout)
        self.configure(cred=False)
        r = self.run_s(extra={"STUB_MISSING": "cifs-utils"})
        self.assertEqual(r.returncode, 1)
        self.assertIn("Run: sudo apt install cifs-utils", r.stdout)

    def test_fresh_system_created_then_idempotent(self):
        r = self.run_s()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        c = self.calls()
        self.assertIn("useradd --system --user-group", c)
        self.assertIn("--shell /usr/sbin/nologin", c)
        self.assertIn("python3 -m venv", c)
        self.assertIn("pip install", c)
        for d in ("var/lib/partitor", "var/lib/partitor/work"):
            st = os.stat(os.path.join(self.pfx, d))
            self.assertEqual(stat.S_IMODE(st.st_mode), 0o750)
        for d in ("", "inbox", "library"):                  # local library, group-writable, setgid
            st = os.stat(os.path.join(self.locallib, d))
            self.assertEqual(stat.S_IMODE(st.st_mode), 0o2770, d)
        for name in ("partitor", "partitor-init", "partitor-install"):
            link = os.path.join(self.pfx, "usr", "local", "sbin", name)
            self.assertEqual(os.readlink(link), os.path.join(self.opt, "bin", name))
        os.remove(self.log)
        r = self.run_s()
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertEqual(self.calls(), "")
        self.assertIn("ok   venv packages match requirements.txt", r.stdout)
        self.assertIn("storage mode: local", r.stdout)

    def test_changed_requirements_reinstall(self):
        self.run_s()
        os.remove(self.log)
        write(self.req, "numpy==2.5.4\n", 0o644)
        self.run_s()
        self.assertIn("pip install", self.calls())
        self.assertNotIn("useradd", self.calls())

    def test_check_changes_nothing_and_fails(self):
        r = self.run_s("--check")
        self.assertEqual(r.returncode, 1)
        self.assertIn("FAIL user", r.stdout)
        self.assertEqual(self.calls(), "")
        self.assertFalse(os.path.exists(os.path.join(self.pfx, "var", "lib", "partitor")))

    def test_check_passes_after_setup(self):
        self.run_s()
        r = self.run_s("--check")
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_dry_run_lists_todo_changes_nothing_exits_0(self):
        r = self.run_s("--dry-run")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("todo user", r.stdout)
        self.assertIn("todo folder", r.stdout)
        self.assertIn("todo venv missing", r.stdout)
        self.assertNotIn("FAIL", r.stdout)
        self.assertEqual(self.calls(), "")
        self.assertFalse(os.path.exists(os.path.join(self.pfx, "var", "lib", "partitor")))
        self.run_s()
        r = self.run_s("--dry-run")
        self.assertNotIn("todo", r.stdout)

    def test_login_shell_is_reported(self):
        write(self.passwd, f"{ME}:x:999:999::{self.pfx}/var/lib/partitor:/bin/bash\n", 0o644)
        r = self.run_s()
        self.assertEqual(r.returncode, 1)
        self.assertIn("usermod -s /usr/sbin/nologin", r.stdout)

    def logo_run(self, logo, make=True, unreadable=False, smb=False):
        """Install with PARTITOR_LOGO=logo in the config; a runuser stub stands for the service user."""
        self.configure(smb=smb, extra=f"PARTITOR_LOGO={logo}\n")
        write(os.path.join(self.stubs, "runuser"),
              "#!/bin/sh\n[ -n \"$STUB_LOGO_UNREADABLE\" ] && exit 1\n"
              "shift 2; [ \"$1\" = -- ] && shift; exec \"$@\"\n")
        if make:
            path = self.pfx + logo
            os.makedirs(os.path.dirname(path), exist_ok=True)
            write(path, "png", 0o644)
        return self.run_s(extra={"STUB_LOGO_UNREADABLE": "1" if unreadable else ""})

    def test_logo_readable_is_ok(self):
        r = self.logo_run("/etc/partitor/logo.png")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("ok   logo readable by", r.stdout)

    def test_logo_not_readable_warns_and_does_not_fail(self):
        r = self.logo_run("/etc/partitor/logo.png", unreadable=True)
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("WARN logo not readable by", r.stdout)
        self.assertIn("chmod o+r /etc/partitor/logo.png", r.stdout)

    def test_logo_where_the_sandbox_cannot_see_it_warns(self):
        for where in ("/home/ann/logo.png", "/root/logo.png", "/tmp/logo.png", "/var/tmp/l.png"):
            with self.subTest(where=where):
                r = self.logo_run(where)
                self.assertEqual(r.returncode, 0, r.stdout)
                self.assertIn(f"WARN logo {where} is hidden in the sandbox", r.stdout)

    def test_logo_missing_or_relative_warns(self):
        r = self.logo_run("/etc/partitor/none.png", make=False)
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("WARN logo file not found: /etc/partitor/none.png", r.stdout)
        r = self.logo_run("logo.png", make=False)
        self.assertIn("WARN PARTITOR_LOGO is not an absolute path", r.stdout)

    def test_no_logo_or_none_says_nothing(self):
        self.configure(smb=False)
        self.assertNotIn("logo", self.run_s().stdout)
        r = self.logo_run("none", make=False)
        self.assertNotIn("logo", r.stdout.replace("PARTITOR_LOGO=none", ""))

    def test_logo_check_runs_with_check_and_changes_nothing(self):
        self.logo_run("/etc/partitor/logo.png")
        r = self.run_s("--check", extra={"STUB_LOGO_UNREADABLE": "1"})
        self.assertIn("WARN logo not readable by", r.stdout)

    def test_self_test_result_decides(self):
        self.run_s()
        w = os.path.join(self.tmp, "wrapper")
        for rc, want in ((0, 0), (1, 1)):
            write(w, f"#!/bin/sh\necho 'ok   user: partitor'\nexit {rc}\n")
            r = self.run_s(extra={"PARTITOR_SKIP_SELFTEST": "0", "PARTITOR_WRAPPER": w})
            with self.subTest(rc=rc):
                self.assertEqual(r.returncode, want, r.stdout)
                self.assertIn("ok   user: partitor", r.stdout)

    def test_local_library_is_checked_in_the_sandbox(self):
        self.run_s()
        w = os.path.join(self.tmp, "wrapper")
        write(w, "#!/bin/sh\necho \"wrapper $*\" >> \"$STUB_LOG\"\nexit 0\n")
        r = self.run_s(extra={"PARTITOR_SKIP_SELFTEST": "0", "PARTITOR_WRAPPER": w})
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("wrapper --sandbox-check --library", self.calls())

    def test_wrong_library_folder_mode_is_corrected_or_reported(self):
        self.run_s()
        os.chmod(os.path.join(self.locallib, "inbox"), 0o755)
        r = self.run_s("--check")
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("inbox is 755", r.stdout)
        r = self.run_s()
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(self.locallib, "inbox")).st_mode), 0o2770)

    def test_other_local_library_path_from_config(self):
        os.makedirs(os.path.dirname(self.defaults))
        write(self.defaults, "PARTITOR_LIBRARY=/srv/scores\n", 0o644)
        r = self.run_s()
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertTrue(os.path.isdir(os.path.join(self.pfx, "srv", "scores", "inbox")))

    def test_bad_library_path_refused(self):
        os.makedirs(os.path.dirname(self.defaults))
        for bad in ("relative/dir", "/srv/my scores", "/srv/x;y"):
            write(self.defaults, f"PARTITOR_LIBRARY={bad}\n", 0o644)
            with self.subTest(bad=bad):
                r = self.run_s()
                self.assertEqual(r.returncode, 1, r.stdout)
                self.assertIn("PARTITOR_LIBRARY must be", r.stdout)
        self.assertEqual(self.calls(), "")

    def test_config_option_installs_the_file(self):
        cfg = os.path.join(self.tmp, "site.conf")
        write(cfg, "PARTITOR_LIBRARY=/srv/lib2\n", 0o644)
        r = self.run_s("--check", "--config", cfg)
        self.assertEqual(r.returncode, 1)
        self.assertIn("differs from", r.stdout)
        self.assertFalse(os.path.exists(self.defaults))
        r = self.run_s("--config", cfg)
        self.assertEqual(r.returncode, 0, r.stdout)
        with open(self.defaults, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "PARTITOR_LIBRARY=/srv/lib2\n")
        self.assertTrue(os.path.isdir(os.path.join(self.pfx, "srv", "lib2", "inbox")))
        r = self.run_s("--check", "--config", cfg)
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_config_file_missing_fails(self):
        r = self.run_s("--config", os.path.join(self.tmp, "nope.conf"))
        self.assertEqual(r.returncode, 1)
        self.assertIn("not readable", r.stdout)

    def test_link_to_a_foreign_file_is_not_replaced(self):
        link = os.path.join(self.pfx, "usr", "local", "sbin", "partitor")
        os.makedirs(os.path.dirname(link))
        write(link, "#!/bin/sh\n")
        r = self.run_s()
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("is not a link to", r.stdout)
        self.assertFalse(os.path.islink(link))

    def test_unknown_option_is_usage_error(self):
        r = self.run_s("--frobnicate")
        self.assertEqual(r.returncode, 1)


class TestSetupSmb(SetupFixture):
    """SMB storage mode: credentials, mount units, automount."""

    def test_smb_without_credentials_fails(self):
        self.configure(cred=False)
        r = self.run_s()
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("credentials missing", r.stdout)

    def test_bad_host_or_share_refused(self):
        for extra in ("PARTITOR_SMB_SHARE=my share\n", "PARTITOR_SMB_HOST=h;x\n"):
            self.configure(extra=extra)
            with self.subTest(extra=extra):
                r = self.run_s()
                self.assertEqual(r.returncode, 1, r.stdout)

    def test_credentials_mode_checked_and_never_printed(self):
        self.configure(mode=0o644)
        r = self.run_s()
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("want 600", r.stdout)
        self.assertNotIn("secret-not-shown", r.stdout + r.stderr)

    def test_configured_writes_units_and_enables_automount(self):
        self.configure(extra="PARTITOR_SMB_SHARE=scores\n")
        r = self.run_s()
        self.assertEqual(r.returncode, 0, r.stdout)
        with open(os.path.join(self.units, "mnt-partitor.mount"), encoding="utf-8") as fh:
            m = fh.read()
        self.assertIn("What=//192.0.2.10/scores", m)
        self.assertIn("Where=/mnt/partitor", m)
        self.assertIn("credentials=/etc/partitor/smb.cred,uid=" + ME, m)
        self.assertNotIn("@", m.split("[Unit]")[1])                       # no placeholder left
        with open(os.path.join(self.units, "mnt-partitor.automount"), encoding="utf-8") as fh:
            self.assertIn("Where=/mnt/partitor", fh.read())
        self.assertIn("systemctl daemon-reload", self.calls())
        self.assertIn("systemctl enable --now mnt-partitor.automount", self.calls())
        r2 = self.run_s()
        self.assertIn("ok   unit mnt-partitor.mount", r2.stdout)
        self.assertNotIn("secret-not-shown", r.stdout + r2.stdout)

    def test_unit_name_follows_the_library_path(self):
        self.configure(extra="PARTITOR_LIBRARY=/srv/my-scores\n")
        r = self.run_s()
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertTrue(os.path.isfile(os.path.join(self.units, "srv-my\\x2dscores.mount")))
        self.assertIn("enable --now srv-my\\x2dscores.automount", self.calls())

    def test_old_dropin_is_removed(self):
        self.configure()
        d = os.path.join(self.units, "mnt-partitor.mount.d")
        os.makedirs(d)
        write(os.path.join(d, "10-nas.conf"), "[Mount]\nWhat=//old/partitor\n", 0o644)
        self.assertEqual(self.run_s().returncode, 0)
        self.assertFalse(os.path.exists(d))

    def test_unreachable_library_warns(self):
        self.configure()
        w = os.path.join(self.tmp, "wrapper")
        write(w, "#!/bin/sh\necho 'ok   user: partitor'\nexit 0\n")
        r = self.run_s(extra={"PARTITOR_SKIP_SELFTEST": "0", "PARTITOR_WRAPPER": w})
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("WARN library not reachable", r.stdout)

    def test_reachable_library_checked_in_sandbox(self):
        self.configure()
        for d in ("inbox", "library"):
            os.makedirs(os.path.join(self.libdir, d))
        w = os.path.join(self.tmp, "wrapper")
        for rc, want in ((0, 0), (1, 1)):
            write(w, f"#!/bin/sh\necho \"wrapper $*\" >> \"$STUB_LOG\"\nexit {rc}\n")
            r = self.run_s(extra={"PARTITOR_SKIP_SELFTEST": "0", "PARTITOR_WRAPPER": w})
            with self.subTest(rc=rc):
                self.assertEqual(r.returncode, want, r.stdout)
                self.assertIn("wrapper --sandbox-check --library", self.calls())

    def test_smb_mode_does_not_create_local_library(self):
        self.configure()
        self.run_s()
        self.assertFalse(os.path.exists(self.libdir))
        self.assertFalse(os.path.exists(self.locallib))

    def test_check_mode_writes_nothing(self):
        self.configure()
        self.run_s()                       # user, folders, venv, units
        shutil.rmtree(self.units)
        before = self.calls().count("daemon-reload")
        r = self.run_s("--check")
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertFalse(os.path.exists(os.path.join(self.units, "mnt-partitor.mount")))
        self.assertEqual(self.calls().count("daemon-reload"), before)
        self.run_s()
        r = self.run_s("--check", extra={"STUB_ENABLED_RC": "0"})
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_dry_run_lists_units(self):
        self.configure()
        r = self.run_s("--dry-run")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("storage mode: smb", r.stdout)
        self.assertFalse(os.path.exists(self.units))


if __name__ == "__main__":
    unittest.main()
