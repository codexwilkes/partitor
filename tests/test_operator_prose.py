# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""Prose rules of docs/operator/ (see the rules at the end of docs/operator/README.md)."""
from __future__ import annotations

import re
import unittest
from pathlib import Path

DOCS = Path(__file__).resolve().parent.parent / "docs" / "operator"
FILES = ["guide.md", "advanced.md", "problems.md"]
BANNED = [r"\bmeasures?\b", r"\bstave\b", r"\bsounding pitch\b", r"\btranspos\w*", r"\bsound(s|ed) an octave\b"]
MAX_PARAGRAPH_WORDS = 120
GUIDE_MAX_WORDS = 1700


def body(name: str) -> str:
    text = (DOCS / name).read_text(encoding="utf-8")
    return text.split("\n---\n", 1)[1] if text.startswith("---\n") else text


def paragraphs(text: str):
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    text = re.sub(r'<div class="screen">.*?</div>', "", text, flags=re.S)
    for block in re.split(r"\n\s*\n", text):
        block = block.strip()
        if not block or block.startswith(("|", "#")):
            continue
        yield from (b.strip() for b in re.split(r"\n(?=- |\d+\. )", block))


class OperatorProse(unittest.TestCase):
    def test_one_word_for_one_thing(self):
        for name in FILES:
            for pat in BANNED:
                with self.subTest(file=name, pattern=pat):
                    self.assertIsNone(re.search(pat, body(name), re.I), f"{name}: {pat}")

    def test_paragraphs_are_short(self):
        for name in FILES:
            for para in paragraphs(body(name)):
                with self.subTest(file=name, start=para[:40]):
                    self.assertLessEqual(len(para.split()), MAX_PARAGRAPH_WORDS)

    def test_guide_stays_short(self):
        self.assertLessEqual(len(body("guide.md").split()), GUIDE_MAX_WORDS)

    def test_advanced_headings_have_ids(self):
        heads = [l for l in body("advanced.md").splitlines() if l.startswith("## ")]
        ids = [re.search(r'\{#([a-z][a-z0-9-]*) eyebrow="[^"]*"\}$', h) for h in heads]
        self.assertTrue(all(ids), heads)
        got = [m.group(1) for m in ids]
        self.assertEqual(len(got), len(set(got)))

    def test_every_guide_link_to_advanced_exists(self):
        self.assertTrue((DOCS / "advanced.md").is_file())
        self.assertIn("(advanced.md)", body("guide.md"))
        self.assertIn("(guide.md)", (DOCS / "advanced.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
