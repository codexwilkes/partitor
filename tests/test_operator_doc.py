# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""The operator guide: sources in docs/operator/*.md, built by tools/build-operator-doc.py.

The generator needs markdown-it-py and PyYAML (developer packages). The tests that run
it use the first python that has them (this one, or the system python3) and skip when
none has. The menu-key and no-image tests need nothing extra."""
from __future__ import annotations

import ast
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL = os.path.join(ROOT, "tools", "build-operator-doc.py")
SRC = os.path.join(ROOT, "docs", "operator")


def _find_python():
    for py in (sys.executable, "/usr/bin/python3", shutil.which("python3")):
        if py and os.path.exists(py):
            r = subprocess.run([py, "-I", "-c", "import markdown_it, yaml"], capture_output=True)
            if r.returncode == 0:
                return py
    return None


PY = _find_python()


def run_tool(root, *args):
    return subprocess.run([PY, "-I", TOOL, "--root", root, *args], capture_output=True, text=True)


def slurp(path, mode="r"):
    with open(path, mode, **({} if "b" in mode else {"encoding": "utf-8"})) as f:
        return f.read()


def read(*p):
    with open(os.path.join(ROOT, *p), encoding="utf-8") as f:
        return f.read()


@unittest.skipUnless(PY, "markdown-it-py and PyYAML not installed (developer packages)")
class TestGenerator(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.root = os.path.join(self._td.name, "repo")
        os.makedirs(os.path.join(self.root, "docs"))
        shutil.copy(os.path.join(ROOT, "VERSION"), self.root)
        shutil.copytree(SRC, os.path.join(self.root, "docs", "operator"))

    def out(self):
        return os.path.join(self.root, "docs", "operator-flow.html")

    def edit(self, name, old, new):
        p = os.path.join(self.root, "docs", "operator", name)
        with open(p, encoding="utf-8") as f:
            t = f.read()
        self.assertIn(old, t)
        with open(p, "w", encoding="utf-8") as f:
            f.write(t.replace(old, new, 1))

    def test_committed_file_is_current(self):
        r = run_tool(ROOT, "--check")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_output_is_deterministic_and_self_contained(self):
        self.assertEqual(run_tool(self.root).returncode, 0)
        a = slurp(self.out(), "rb")
        self.assertEqual(run_tool(self.root).returncode, 0)
        self.assertEqual(a, slurp(self.out(), "rb"))
        self.assertEqual(a, slurp(os.path.join(ROOT, "docs", "operator-flow.html"), "rb"))
        text = a.decode("utf-8")
        self.assertTrue(text.startswith("<!-- GENERATED from docs/operator/*.md by tools/build-operator-doc.py. Do not edit. -->"))
        for bad in ("http://", "https://", "<script", "<link", " src=", "<img"):
            self.assertNotIn(bad, text)
        for sid in ("before", "drop", "analyse", "edit", "review", "build", "help"):
            self.assertEqual(text.count(f'<section id="{sid}">'), 1, sid)

    def test_check_passes_then_fails(self):
        run_tool(self.root)
        self.assertEqual(run_tool(self.root, "--check").returncode, 0)
        with open(self.out(), "a", encoding="utf-8") as f:
            f.write("<!-- hand edit -->\n")
        r = run_tool(self.root, "--check")
        self.assertEqual(r.returncode, 1)
        self.assertIn("not current", r.stderr)
        os.remove(self.out())
        self.assertEqual(run_tool(self.root, "--check").returncode, 1)

    def test_version_comes_from_version_file(self):
        with open(os.path.join(self.root, "VERSION"), "w") as f:
            f.write("9.8.7\n")
        self.assertEqual(run_tool(self.root).returncode, 0)
        text = slurp(self.out())
        self.assertEqual(text.count("partitor 9.8.7"), 2)
        self.assertNotRegex(text.replace("partitor 9.8.7", ""), r"partitor \d+\.\d+\.\d+")
        for name in ("guide.md", "problems.md"):
            self.assertNotRegex(read("docs", "operator", name), r"partitor \d+\.\d+\.\d+")

    def test_contract_violations(self):
        cases = [
            ("image", "guide.md", "A score PDF:", "![x](a.png) A score PDF:", "guide.md:", "image"),
            ("external link", "guide.md", "A score PDF:", "[x](https://example.com) A score PDF:", "guide.md:", "external"),
            ("external url", "guide.md", "A score PDF:", "see https://example.com A score PDF:", "guide.md:", "external"),
            ("raw tag", "guide.md", "A score PDF:", "<img src=a> A score PDF:", "guide.md:", "not allowed"),
            ("script", "guide.md", "A score PDF:", "<script>x</script> A score PDF:", "guide.md:", "raw HTML"),
            ("bad block", "guide.md", '<p class="note"><b>One', '<p class="tip"><b>One', "guide.md:", "raw HTML block"),
            ("bad pill", "guide.md", '<span class="pill wait">', '<span class="pill red">', "guide.md:", "not allowed"),
            ("h4", "guide.md", "### Part names", "#### Part names", "guide.md:", "heading level"),
            ("no id", "guide.md", " {#drop", " {#dropx", "guide.md:", "section ids"),
            ("no attrs", "guide.md", ' {#build eyebrow="Stage 5 · takes minutes"}', "", "guide.md:", "must end with"),
            ("order", "guide.md", "{#drop", "{#zzz", "guide.md:", "section ids"),
            ("stage key", "guide.md", "long: false}", "long: maybe}", "guide.md:1:", "each stage"),
            ("no front matter", "problems.md", "---\n", "", "problems.md:1:", "front matter"),
            ("two paragraphs", "problems.md", "run `partitor` again.", "run `partitor` again.\n\nA second paragraph.", "problems.md:", "one paragraph"),
            ("problem list", "problems.md", "Normal: those bars", "- Normal: those bars", "problems.md:", "one paragraph"),
        ]
        for label, name, old, new, where, msg in cases:
            with self.subTest(label):
                shutil.rmtree(os.path.join(self.root, "docs", "operator"))
                shutil.copytree(SRC, os.path.join(self.root, "docs", "operator"))
                self.edit(name, old, new)
                r = run_tool(self.root)
                self.assertEqual(r.returncode, 1, r.stdout)
                self.assertIn(where, r.stderr)
                self.assertIn(msg, r.stderr)
                if "1:" not in where:                      # a body error names a real line
                    self.assertRegex(r.stderr, re.escape(where.rstrip(":")) + r":[1-9]\d*:")
                self.assertFalse(os.path.exists(self.out()))

    def test_problems_become_the_faq_rows(self):
        run_tool(self.root)
        text = slurp(self.out())
        n = len(re.findall(r"^## ", read("docs", "operator", "problems.md"), re.M))
        help_html = text.split('<section id="help">')[1]
        self.assertEqual(help_html.count("<tr><td>"), n)


class TestSourcesRules(unittest.TestCase):
    def sources(self):
        return [os.path.join(SRC, n) for n in sorted(os.listdir(SRC))]

    def test_no_images_in_operator_sources(self):
        files = self.sources()
        self.assertGreaterEqual(len(files), 4)
        for p in files:
            with self.subTest(file=os.path.basename(p)):
                with open(p, encoding="utf-8") as f:
                    t = f.read()
                self.assertNotRegex(t, r"<img\b|!\[[^\]]*\]\(|<picture\b|<svg\b|url\(|@import")
                self.assertNotRegex(t, r"(?i)\.(png|jpe?g|gif|webp|svg)\b")

    def test_menu_keys_in_guide_equal_menu_keys_in_code(self):
        tree = ast.parse(read("lib", "partitor", "cli_main.py"))
        fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "item_menu")
        code = {}
        for n in ast.walk(fn):
            if (isinstance(n, ast.Compare) and isinstance(n.left, ast.Name) and n.left.id == "k"
                    and isinstance(n.ops[0], (ast.Eq, ast.In))):
                c = n.comparators[0]
                for e in (c.elts if isinstance(c, ast.Tuple) else [c]):
                    if isinstance(e, ast.Constant) and isinstance(e.value, str):
                        code[e.value] = n.lineno
        self.assertGreaterEqual(len(code), 15, "item_menu keys not found: the test reads `k == 'x'` and `k in (...)`")
        guide = read("docs", "operator", "guide.md").splitlines()
        start = next(i for i, ln in enumerate(guide) if ln.startswith("### The item menu"))
        end = next(i for i in range(start + 1, len(guide)) if guide[i].startswith("## "))
        doc = {}
        for i in range(start, end):
            ln = guide[i]
            if ln.startswith("| <kbd>"):
                for k in re.findall(r"<kbd>(\w)</kbd>", ln.split("|")[1]):
                    doc[k] = i + 1
        for k in sorted(set(code) - set(doc)):
            self.fail(f"menu key '{k}' is in lib/partitor/cli_main.py:{code[k]} (item_menu) "
                      "but not in the item-menu tables of docs/operator/guide.md")
        for k in sorted(set(doc) - set(code)):
            self.fail(f"menu key '{k}' is in docs/operator/guide.md:{doc[k]} "
                      "but not in item_menu of lib/partitor/cli_main.py")
