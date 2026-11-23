#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
#
# Gate for a change that touches only docs (docs/RELEASING.md, "Gates by kind of change").
# It refuses a change outside README.md, CHANGELOG.md, VERSION, docs/ and the version line of
# lib/partitor/__init__.py. It runs the tests that read docs and tools/check-repo.sh (about 1 minute).
# CI runs the full suite on every push; a docs-only tag waits for green CI on its commit.
#
# Usage: tools/doc-gate.sh        (run in the repo, with the change not yet committed or just committed: HEAD~1 is not used)
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PYTHON:-venv/bin/python}"

# Every test module that reads docs/ is here. tests/test_ci.py checks this list.
DOC_TESTS=(test_ci test_docs test_cli_doc test_operator_doc test_operator_prose test_architecture test_choices test_hooks)

changed=$({ git diff --name-only HEAD; git ls-files --others --exclude-standard; } | sort -u)
other=$(printf '%s\n' "$changed" | grep -vE '^(README\.md|CHANGELOG\.md|VERSION|docs/.*|lib/partitor/__init__\.py)$' || true)
if [ -n "$other" ]; then
    printf 'doc-gate: not a docs-only change, run the full gates. Files:\n%s\n' "$other" >&2
    exit 1
fi
if printf '%s\n' "$changed" | grep -qx 'lib/partitor/__init__.py'; then
    extra=$(git diff -U0 HEAD -- lib/partitor/__init__.py | grep -E '^[+-][^+-]' | grep -vE "^[+-]VERSION = " || true)
    if [ -n "$extra" ]; then
        printf 'doc-gate: lib/partitor/__init__.py changes more than the version line:\n%s\n' "$extra" >&2
        exit 1
    fi
fi

mods=()
for m in "${DOC_TESTS[@]}"; do mods+=("tests.$m"); done
"$PY" -m unittest "${mods[@]}" 2>&1 | tail -n 4
bash tools/check-repo.sh | tail -n 3
echo "doc-gate: ok"
