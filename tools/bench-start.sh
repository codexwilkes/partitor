#!/usr/bin/env bash
# shellcheck shell=bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
#
# Start-up cost of the engine: wall time of `venv/bin/python lib/partitor-engine --version`.
# Usage: tools/bench-start.sh [N]    N runs (default 5)
# Output: one line per run, then the median. Nothing else.
#   run 1: 0.481 s
#   ...
#   median: 0.483 s
# Use it before and after a step that moves code into lib/partitor (cold-start budget
# of the modular split: not more than 10 % above the 0.4.2 median). Run it in the same
# environment each time. The first run may be slower (cold file cache); the median
# hides it. Exit codes: 0 ok; 1 no venv; 2 usage error.
set -euo pipefail
export LC_ALL=C                       # EPOCHREALTIME and awk need a decimal point

n="${1:-5}"
[[ "$n" =~ ^[1-9][0-9]*$ ]] || { echo "usage: bench-start.sh [N]   (N: a positive integer)" >&2; exit 2; }
root="$(dirname "$(dirname "$(realpath -- "${BASH_SOURCE[0]}")")")"
py="$root/venv/bin/python"
engine="$root/lib/partitor-engine"
[[ -x "$py" ]] || { echo "bench-start: no venv python: $py" >&2; exit 1; }

times=()
for ((i = 1; i <= n; i++)); do
  t0="$EPOCHREALTIME"
  "$py" "$engine" --version >/dev/null
  t1="$EPOCHREALTIME"
  t="$(awk -v a="$t0" -v b="$t1" 'BEGIN { printf "%.3f", b - a }')"
  times+=("$t")
  echo "run $i: $t s"
done
median="$(printf '%s\n' "${times[@]}" | sort -n | awk '{ v[NR] = $1 }
  END { if (NR % 2) printf "%.3f", v[(NR + 1) / 2]; else printf "%.3f", (v[NR / 2] + v[NR / 2 + 1]) / 2 }')"
echo "median: $median s"
