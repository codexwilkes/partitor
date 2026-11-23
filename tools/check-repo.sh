#!/usr/bin/env bash
# shellcheck shell=bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
#
# Repo gate (CI and before a release). Fails when the tracked files hold:
#   - a score or scan: *.pdf, *.jpg, *.jpeg, *.tif, *.tiff (copyright; no samples ship)
#   - a private network address (RFC 1918) or a *.invalid host
#   - a file without an SPDX line (bin/, lib/, tests/, tools/, platforms/; lib/ includes lib/partitor/;
#     the binary fixtures in tests/data/ and the icon files (*.png, *.ico) in platforms/ are the exceptions)
#   - a broken module structure (tools/check-modules.py --static)
#   - a stale docs/operator-flow.html (tools/build-operator-doc.py --check) or a version in it that is not VERSION
#   - a version that differs from VERSION: the package, the tag example in README.md and docs/INSTALL.md, the newest CHANGELOG release
#   - a version in the user docs (README, INSTALL, OPERATING, guide, ...) that is not VERSION
#   - a stale docs/COMMANDS.md or docs/cli.json (tools/build-cli-doc.py --check)
#   - a stale or wrong docs/ARCHITECTURE.md (tools/check-architecture.py)
# A private token list is checked by the maintainer, not here (it is itself personal).
# Usage: tools/check-repo.sh   (run from anywhere inside the repo)
set -euo pipefail
cd "$(git rev-parse --show-toplevel 2>/dev/null || dirname "$(dirname "$(realpath -- "${BASH_SOURCE[0]}")")")"
fail=0
bad() { echo "check-repo: FAIL $1"; fail=1; }
files() { if git rev-parse --git-dir >/dev/null 2>&1; then git ls-files; else find . -type f -not -path './.git/*' | sed 's|^\./||'; fi; }
while IFS= read -r f; do
  case "${f,,}" in *.pdf|*.jpg|*.jpeg|*.tif|*.tiff) bad "image or score file tracked: $f" ;; esac
done < <(files)
while IFS= read -r f; do
  case "$f" in LICENSE|share/fonts/*|tools/check-repo.sh) continue ;; esac
  if grep -InE '(^|[^0-9.])(10\.[0-9]+\.[0-9]+\.[0-9]+|192\.168\.[0-9]+\.[0-9]+|172\.(1[6-9]|2[0-9]|3[01])\.[0-9]+\.[0-9]+)([^0-9]|$)|\.invalid\b' "$f" >/dev/null 2>&1; then
    bad "private address or .invalid host in $f"
  fi
done < <(files)
while IFS= read -r f; do
  case "$f" in
    tests/data/*) continue ;;                 # binary fixtures cannot hold a licence line
    platforms/*.png|platforms/*.ico) continue ;;   # binary assets (the icon) cannot hold a licence line
    bin/*|lib/*|tests/*|tools/*|platforms/*)
      head -n 6 "$f" | grep -q 'SPDX-License-Identifier: AGPL-3.0-or-later' || bad "no SPDX line: $f" ;;
  esac
done < <(files)
if ! python3 tools/check-modules.py --static; then
  bad "module structure (tools/check-modules.py --static)"
fi
# The operator guide: generated from docs/operator/*.md. The version test needs no extra package.
ver="$(tr -d '[:space:]' < VERSION)"
if [ "$(grep -c "partitor ${ver}" docs/operator-flow.html)" != 2 ] \
   || grep -v "partitor ${ver}" docs/operator-flow.html | grep -Eq 'partitor [0-9]+\.[0-9]+\.[0-9]+'; then
  bad "docs/operator-flow.html does not carry VERSION ${ver} (run tools/build-operator-doc.py)"
fi
# One version: VERSION, the package, the tag example of README and INSTALL, the newest CHANGELOG release.
pkgver="$(sed -n 's/^VERSION = "\(.*\)"$/\1/p' lib/partitor/__init__.py)"
[ "$pkgver" = "$ver" ] || bad "lib/partitor/__init__.py has VERSION ${pkgver:-none}, the file VERSION has ${ver}"
for doc in README.md docs/INSTALL.md; do
  tagver="$(sed -n 's/.*git checkout --detach \([^ ]*\).*/\1/p' "$doc" | head -n 1)"
  [ "$tagver" = "$ver" ] || bad "${doc} names tag ${tagver:-none} in its checkout example, VERSION is ${ver}"
done
logver="$(sed -n 's/^## \([0-9][0-9.]*[0-9a-z.-]*\) — .*/\1/p' CHANGELOG.md | head -n 1)"
[ "$logver" = "$ver" ] || bad "the newest CHANGELOG release is ${logver:-none}, VERSION is ${ver}"
# No other version in the user docs: "partitor X.Y.Z" or "release X.Y.Z" must be VERSION (history files are exempt).
for doc in README.md docs/INSTALL.md docs/OPERATING.md docs/KNOWN-LIMITS.md docs/STORAGE-LOCAL.md docs/STORAGE-SMB.md docs/SANDBOX.md \
           docs/operator/guide.md docs/operator/advanced.md docs/operator/problems.md platforms/windows/README.md; do
  [ -f "$doc" ] || continue
  while IFS= read -r v; do
    [ "$v" = "$ver" ] || bad "${doc} names version ${v}, VERSION is ${ver}"
  done < <(grep -oE '(partitor|release) [0-9]+\.[0-9]+\.[0-9]+' "$doc" | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | sort -u)
done
# The command reference and the machine source of the CLI are generated from the code.
python3 tools/build-cli-doc.py --check || bad "docs/COMMANDS.md or docs/cli.json is old (run tools/build-cli-doc.py)"
# The architecture page: the module block is generated; diagrams use the drawable subset; paths exist.
python3 tools/check-architecture.py || bad "docs/ARCHITECTURE.md is stale or wrong (tools/check-architecture.py)"
# A python with the two developer packages: the first python3 on PATH, else the system one
# (CI test jobs put setup-python first on PATH; the apt packages belong to /usr/bin/python3).
docpy=""
for cand in python3 /usr/bin/python3; do
  if "$cand" -c "import markdown_it, yaml" 2>/dev/null; then docpy="$cand"; break; fi
done
if [ -n "$docpy" ]; then
  "$docpy" tools/build-operator-doc.py --check || bad "docs/operator-flow.html is not current (tools/build-operator-doc.py)"
elif [ -n "${CI:-}" ]; then
  bad "markdown-it-py or PyYAML missing in CI (apt install python3-markdown-it python3-yaml)"
else
  echo "check-repo: skip operator guide check (python3-markdown-it or python3-yaml missing)"
fi
(( fail )) && exit 1
echo "check-repo: ok"
