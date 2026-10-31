#!/usr/bin/env bash
# shellcheck shell=bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
#
# Repo gate (CI and before a release). Fails when the tracked files hold:
#   - a score or scan: *.pdf, *.jpg, *.jpeg, *.tif, *.tiff (copyright; no samples ship)
#   - a private network address (RFC 1918) or a *.invalid host
#   - a file without an SPDX line (bin/, lib/, tests/, tools/; lib/ includes lib/partitor/;
#     the binary fixtures in tests/data/ are the one exception)
#   - a broken module structure (tools/check-modules.py --static)
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
    bin/*|lib/*|tests/*|tools/*)
      head -n 6 "$f" | grep -q 'SPDX-License-Identifier: AGPL-3.0-or-later' || bad "no SPDX line: $f" ;;
  esac
done < <(files)
if ! python3 tools/check-modules.py --static; then
  bad "module structure (tools/check-modules.py --static)"
fi
(( fail )) && exit 1
echo "check-repo: ok"
