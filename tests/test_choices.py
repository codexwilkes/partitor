# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""The rules for a choice (CONTRIBUTING.md, "Add a choice"): every enum key of
the layout defaults can be set, is described in the layout help and is named in
the design document."""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from support import pt, setUpModule, tearDownModule  # noqa: E402,F401

ROOT = Path(__file__).resolve().parent.parent
# enum keys that are not a user setting of the printed part


class TestChoices(unittest.TestCase):
    def enum_keys(self):
        return sorted(k for k, v in pt.LAYOUT_DEFAULTS.items() if isinstance(v, str))

    def test_enum_keys_exist(self):
        self.assertIn("cutline", self.enum_keys())
        self.assertIn("large", self.enum_keys())

    def test_every_enum_key_can_be_set(self):
        have = {v[0] for v in pt.SET_KEYS.values()}
        for k in self.enum_keys():
            with self.subTest(key=k):
                self.assertIn(k, have)

    def test_every_enum_key_has_help(self):
        for k in self.enum_keys():
            with self.subTest(key=k):
                self.assertIn(f"#   {k}:", pt.LAYOUT_HELP)

    def test_every_enum_key_is_in_design(self):
        text = (ROOT / "docs" / "DESIGN.md").read_text(encoding="utf-8")
        for k in self.enum_keys():
            with self.subTest(key=k):
                self.assertIn(k, text)

    def test_set_values_match_the_default(self):
        for name, (key, parser) in pt.SET_KEYS.items():
            if isinstance(parser, tuple) and isinstance(pt.LAYOUT_DEFAULTS.get(key), str):
                with self.subTest(key=key):
                    self.assertIn(pt.LAYOUT_DEFAULTS[key], parser)


if __name__ == "__main__":
    unittest.main()
