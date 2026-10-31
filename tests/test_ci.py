# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""Tests for the CI files: the workflow parses, runs only scripts that exist,
keeps minimal permissions, and uses pinned action versions. Needs PyYAML
(skipped without it).

The last class guards the test count: discovery must find at least MIN_TESTS tests.

Run: python3 -m unittest -v tests/test_ci.py
"""
import os
import re
import unittest

try:
    import yaml
except ImportError:                      # pragma: no cover
    yaml = None

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
WF = os.path.join(ROOT, ".github", "workflows", "ci.yml")

# Discovered tests (skipped ones count) at the last step. Raise it with every step that adds
# tests; never lower it (CONTRIBUTING.md: the number of tests must not fall).
MIN_TESTS = 464


def text(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


@unittest.skipUnless(yaml, "PyYAML not installed")
class TestWorkflow(unittest.TestCase):
    def setUp(self):
        self.wf = yaml.safe_load(text(".github", "workflows", "ci.yml"))
        # YAML 1.1 reads the key "on" as True
        self.on = self.wf.get("on", self.wf.get(True))

    def test_triggers(self):
        self.assertIn("pull_request", self.on)
        self.assertIn("push", self.on)

    def test_read_only_permissions(self):
        self.assertEqual(self.wf["permissions"], {"contents": "read"})

    def test_actions_have_version_tags(self):
        for job in self.wf["jobs"].values():
            for step in job["steps"]:
                if "uses" in step:
                    with self.subTest(uses=step["uses"]):
                        self.assertRegex(step["uses"], r"^[\w./-]+@(v\d+|[0-9a-f]{40})$")

    def test_scripts_run_by_ci_exist(self):
        blob = text(".github", "workflows", "ci.yml")
        for path in re.findall(r"\b((?:bin|tools|tests)/[\w./-]+)", blob):
            with self.subTest(path=path):
                self.assertTrue(os.path.isfile(os.path.join(ROOT, path)), path)

    def test_shellcheck_covers_every_shell_script(self):
        shell = [f"bin/{n}" for n in os.listdir(os.path.join(ROOT, "bin"))] + \
                [f"tools/{n}" for n in os.listdir(os.path.join(ROOT, "tools")) if n.endswith(".sh")]
        blob = text(".github", "workflows", "ci.yml")
        for s in shell:
            with self.subTest(script=s):
                self.assertIn(s, blob)

    def test_ubuntu_matrix_has_312(self):
        self.assertIn("3.12", self.wf["jobs"]["test-ubuntu"]["strategy"]["matrix"]["python"])

    def test_macos_does_not_block(self):
        self.assertTrue(self.wf["jobs"]["test-macos"]["continue-on-error"])

    def test_macos_runner_is_pinned_not_latest(self):
        # GitHub retires runner images (macos-14 on 2026-11-02): a pinned image is a decision
        self.assertRegex(self.wf["jobs"]["test-macos"]["runs-on"], r"^macos-\d+$")

    def test_gate_runs_the_module_check(self):
        steps = " ".join(str(st.get("run", "")) for st in self.wf["jobs"]["gate"]["steps"])
        self.assertIn("tools/check-modules.py --static", steps)
        self.assertIn("check-modules.py --static", text("tools", "check-repo.sh"))

    def test_wheels_only(self):
        self.assertGreaterEqual(text(".github", "workflows", "ci.yml").count("--only-binary=:all:"), 2)

    def test_tag_pattern_matches_release_tags(self):
        pat = self.on["push"]["tags"][0]
        self.assertEqual(pat, "[0-9]*")        # glob: 0.4.0 and 0.4.0-rc.1, no "v" prefix

    def test_dependabot_and_templates_exist(self):
        for p in ((".github", "dependabot.yml"), (".github", "PULL_REQUEST_TEMPLATE.md"),
                  (".github", "ISSUE_TEMPLATE", "bug.md")):
            self.assertTrue(os.path.isfile(os.path.join(ROOT, *p)), p)


class TestTestCount(unittest.TestCase):
    def test_discovered_test_count_does_not_fall(self):
        suite = unittest.defaultTestLoader.discover(HERE, pattern="test*.py", top_level_dir=HERE)

        def leaves(s):
            for t in s:
                if isinstance(t, unittest.TestSuite):
                    yield from leaves(t)
                else:
                    yield t

        tests = list(leaves(suite))
        failed = [t.id() for t in tests if type(t).__name__ == "_FailedTest"]
        self.assertEqual(failed, [], "a test file does not import")
        self.assertGreaterEqual(len(tests), MIN_TESTS, "tests were removed or are not found")


if __name__ == "__main__":
    unittest.main()
