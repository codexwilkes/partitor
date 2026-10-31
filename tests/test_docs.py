# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""Tests that the documents match the code (a document that contradicts the
code is a defect). No packages needed.

Run: python3 -m unittest -v tests/test_docs.py
"""
import ast
import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
DOCS = os.path.join(ROOT, "docs")


def read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def doc_files():
    out = [os.path.join(ROOT, n) for n in
           ("README.md", "SECURITY.md", "CONTRIBUTING.md", "CHANGELOG.md", "NOTICE")]
    out += [os.path.join(DOCS, n) for n in sorted(os.listdir(DOCS))]
    return out


def tests_source():
    """The text of all test files except this one (a checker must not satisfy itself)."""
    names = sorted(n for n in os.listdir(os.path.join(ROOT, "tests"))
                   if n.endswith(".py") and n != "test_docs.py")
    return "\n".join(read("tests", n) for n in names)


ENGINE = read("lib", "partitor-engine")
WRAPPER = read("bin", "partitor")
INSTALLER = read("bin", "partitor-install")
DESIGN = read("docs", "DESIGN.md")


def literal_dict(name):
    """The dict assigned to NAME in the engine, with literal values only."""
    tree = ast.parse(ENGINE)
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return node.value
    raise AssertionError(f"{name} not found in the engine")


class TestDocFiles(unittest.TestCase):
    def test_all_documents_exist(self):
        for n in ("README.md", "SECURITY.md", "CONTRIBUTING.md", "CHANGELOG.md", "NOTICE",
                  "LICENSE"):
            self.assertTrue(os.path.isfile(os.path.join(ROOT, n)), n)
        for n in ("INSTALL.md", "STORAGE-LOCAL.md", "STORAGE-SMB.md", "OPERATING.md",
                  "SANDBOX.md", "DESIGN.md", "KNOWN-LIMITS.md", "LIBRARY-LAYOUT.md",
                  "OVERLAYS.md", "operator-flow.html"):
            self.assertTrue(os.path.isfile(os.path.join(DOCS, n)), n)

    def test_spdx_in_markdown(self):
        for p in doc_files():
            if p.endswith(".md"):
                with self.subTest(file=os.path.basename(p)):
                    self.assertIn("SPDX-License-Identifier: AGPL-3.0-or-later",
                                  open(p, encoding="utf-8").read(400))

    def test_referenced_documents_exist(self):
        names = set(os.listdir(DOCS)) | set(os.listdir(ROOT))
        for p in doc_files():
            text = open(p, encoding="utf-8").read()
            for ref in set(re.findall(r"\b([A-Z][A-Z0-9-]+\.md|operator-flow\.html)\b", text)):
                with self.subTest(file=os.path.basename(p), ref=ref):
                    self.assertIn(ref, names)

    @unittest.skipUnless(os.environ.get("PARTITOR_SCRUB_TOKENS"),
                         "PARTITOR_SCRUB_TOKENS not set (maintainer's private word list)")
    def test_no_site_references(self):
        """The maintainer keeps a private list of words (one regex per line) that
        must not appear in the public documents. The list is not in the repo."""
        with open(os.environ["PARTITOR_SCRUB_TOKENS"], encoding="utf-8") as f:
            pats = [re.compile(x.strip(), re.I) for x in f if x.strip()]
        for p in doc_files():
            text = open(p, encoding="utf-8").read().replace("codexwilkes", "")
            for pat in pats:
                # the vendor name is the worked example of the NAS guide
                if os.path.basename(p) == "STORAGE-SMB.md" and pat.search("Synology"):
                    continue
                with self.subTest(file=os.path.basename(p), pattern=pat.pattern):
                    self.assertIsNone(pat.search(text))

    def test_no_private_addresses(self):
        pat = re.compile(r"\b(10\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+|172\.(1[6-9]|2\d|3[01])\.\d+\.\d+)\b")
        for p in doc_files():
            with self.subTest(file=os.path.basename(p)):
                self.assertIsNone(pat.search(open(p, encoding="utf-8").read()))


class TestVersionInDocs(unittest.TestCase):
    def test_operator_flow_version(self):
        v = read("VERSION").strip()
        html = read("docs", "operator-flow.html")
        self.assertEqual(len(re.findall(r"partitor " + re.escape(v), html)), 2)
        self.assertNotRegex(html.replace("partitor " + v, ""), r"partitor \d+\.\d+")  # only VERSION

    def test_changelog_has_current_version(self):
        v = read("VERSION").strip()
        self.assertIn(f"## {v}", read("CHANGELOG.md"))


class TestTestsSource(unittest.TestCase):
    def test_helper_reads_every_test_file_but_this_one(self):
        src = tests_source()
        self.assertIn("class TestCommands", src)                 # tests/test_cli.py
        self.assertIn("class TestWrapper", src)                  # tests/test_partitor_setup.py
        self.assertNotIn("def test_helper_reads_every_test_file_but_this_one", src)


class TestCodeMap(unittest.TestCase):
    """The module table of docs/DESIGN.md §12 and of CONTRIBUTING.md follows tools/modules.txt."""

    def listed(self):
        rows = {}
        with open(os.path.join(ROOT, "tools", "modules.txt"), encoding="utf-8") as fh:
            for line in fh:
                f = line.split("#", 1)[0].split()
                if len(f) >= 3:
                    rows[f[1]] = int(f[0])
        return rows

    def table(self, text):
        return {m: int(lv) for lv, m in re.findall(r"^\|\s*(\d)\s*\|\s*`(\w+)`\s*\|", text, re.M)}

    def test_design_code_map_matches_modules_txt(self):
        part = DESIGN.split("## 12. ", 1)[1]
        self.assertEqual(self.table(part), self.listed())

    def test_contributing_module_table_matches_modules_txt(self):
        self.assertEqual(self.table(read("CONTRIBUTING.md")), self.listed())


class TestDesignSections(unittest.TestCase):
    def headings(self):
        return set(re.findall(r"^#+ (\d+(?:\.\d+)?)\.? ", DESIGN, re.M))

    def test_cited_sections_exist(self):
        cites = set()
        for src in (ENGINE, tests_source(), WRAPPER, INSTALLER):
            cites |= set(re.findall(r"DESIGN\.md\s+§(\d+(?:\.\d+)?)", src))
        self.assertTrue(cites)
        for c in cites:
            with self.subTest(section=c):
                self.assertIn(c, self.headings())

    def test_cited_items_exist(self):
        cites = set()
        for src in (ENGINE, tests_source()):
            cites |= set(re.findall(r"§(4\.[23]) item (\d+)", src))
        for sec, item in cites:
            start = DESIGN.index(f"### {sec} ")
            nxt = re.search(r"^#{2,3} ", DESIGN[start + 5:], re.M)
            body = DESIGN[start:start + 5 + nxt.start()] if nxt else DESIGN[start:]
            with self.subTest(section=sec, item=item):
                self.assertRegex(body, rf"(?m)^{item}\. \*\*")

    def test_set_keys_listed(self):
        node = literal_dict("SET_KEYS")
        keys = {k.value for k in node.keys}
        m = re.search(r"- `set` keys: (.*?)\n- `bars", DESIGN, re.S)
        self.assertTrue(m)
        listed = set(re.findall(r"[a-z_]+", re.sub(r"\([^)]*\)", "", m.group(1).split("Bad keys")[0])))
        listed -= {"and", "per", "part"}
        self.assertEqual(keys - listed, set(), "set keys missing in DESIGN 6.2")
        self.assertEqual(listed - keys, set(), "DESIGN 6.2 lists keys that do not exist")

    def test_layout_defaults_in_design(self):
        node = literal_dict("LAYOUT_DEFAULTS")
        d = {k.value: ast.literal_eval(v) for k, v in zip(node.keys, node.values)}
        self.assertEqual((d["min_staff_mm"], d["max_staff_mm"], d["small_mm"]), (5.0, 8.0, 6.5))
        self.assertEqual((d["gap"], d["gap_min"]), (10.0, 7.0))
        self.assertEqual((d["margin_side"], d["gutter"]), (15.0, 5.0))
        self.assertIn("`min_staff_mm`, `max_staff_mm` | `5`, `8`", DESIGN)
        self.assertIn("`small_mm` (6.5 mm)", DESIGN)
        self.assertIn("`gap` 10 sp (floor `gap_min` 7 sp", DESIGN)
        self.assertIn("`margin_top`, `margin_bottom`, `margin_side` (mm, default 15), floor 5 mm", DESIGN)
        self.assertIn("`gutter` mm (default 5)", DESIGN)


class TestSettingsDocs(unittest.TestCase):
    def wrapper_defaults(self):
        return dict(re.findall(r'^(PARTITOR_[A-Z_]+)="([^"]*)"$', WRAPPER, re.M))

    def test_sandbox_defaults(self):
        d = self.wrapper_defaults()
        sandbox = read("docs", "SANDBOX.md")
        for key in ("PARTITOR_MEMORY_MAX", "PARTITOR_JOBS", "PARTITOR_CPU_WEIGHT",
                    "PARTITOR_IO_WEIGHT", "PARTITOR_RUNTIME_MAX"):
            with self.subTest(key=key):
                m = re.search(rf"\| `{key}` \| `?([^|`]+?)`? \|", sandbox)
                self.assertTrue(m, key)
                self.assertEqual(m.group(1).strip(), d[key])

    def test_install_lists_every_setting(self):
        install = read("docs", "INSTALL.md")
        d = self.wrapper_defaults()
        for key in list(d) + ["PARTITOR_SMB_HOST", "PARTITOR_SMB_SHARE", "PARTITOR_LOGO"]:
            with self.subTest(key=key):
                self.assertTrue(key in install, key)

    def test_documented_keys_exist_in_code(self):
        code = ENGINE + WRAPPER + INSTALLER + tests_source()
        for p in doc_files():
            for key in set(re.findall(r"\bPARTITOR_[A-Z_]+\b", open(p, encoding="utf-8").read())):
                with self.subTest(file=os.path.basename(p), key=key):
                    self.assertTrue(key in code, key)

    def test_logo_wording(self):
        # logo unset: no logo, no warning (DESIGN 5.5, CHANGELOG)
        self.assertIn("Unset: no logo, no room kept, no warning", DESIGN)

    def test_storage_defaults(self):
        self.assertIn('LIBRARY="$(cfg PARTITOR_LIBRARY)"; LIBRARY="${LIBRARY:-/var/lib/partitor/library}"',
                      INSTALLER)
        for n in ("STORAGE-LOCAL.md", "INSTALL.md", "DESIGN.md"):
            self.assertIn("/var/lib/partitor/library", read("docs", n))
        self.assertIn("PARTITOR_SMB_SHARE=partitor", read("docs", "STORAGE-SMB.md"))


class TestCommandsInDocs(unittest.TestCase):
    def test_commands_exist(self):
        sub = {c for c in re.findall(r"[a-z]+", " ".join(re.findall(r'"([a-z]+)"', ENGINE)))}
        ops = read("docs", "OPERATING.md")
        table = ops.split("## Commands")[1].split("## The work folder")[0]
        for c in re.findall(r"`partitor (\w+)", table):
            with self.subTest(command=c):
                self.assertTrue(c in sub or c in ("pieces", "detect", "build"), c)

    def test_init_options_in_docs(self):
        init = read("bin", "partitor-init")
        install = read("docs", "INSTALL.md")
        for flag in re.findall(r"^#\s+(--[a-z-]+)", init.split("# Usage:")[1].split("# Exit codes")[0], re.M):
            with self.subTest(flag=flag):
                self.assertIn(flag, init)
                self.assertTrue(flag in install, flag)

    def test_installer_flags_in_docs(self):
        for flag in ("--check", "--dry-run", "--config"):
            self.assertIn(flag, INSTALLER)
            self.assertIn(flag, read("docs", "INSTALL.md"))


if __name__ == "__main__":
    unittest.main()
