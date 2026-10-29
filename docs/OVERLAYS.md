<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
<!-- Copyright (C) 2026 Nathan Wilkes and partitor contributors -->
# Overlays

An overlay is a small wrapper that a site keeps outside this repository. It
holds what is specific to the site: the pinned version, the settings, the NAS
credentials step, local checks, and scripts that use the parts. The overlay
runs the same installer as everybody else, so a green install at the site means
a green install for users.

The pattern:

1. **Pin a tag.** The overlay names one release tag. The clone at `/opt/partitor`
   is checked out at that tag (detached). It is never edited at the site.
2. **Keep site settings outside the clone.** The settings file
   (`/etc/default/partitor`) and any logo or credentials live outside
   `/opt/partitor`. Track them in the overlay repository if they hold no secret.
   Never track the NAS credentials or a NAS address you want private.
3. **Wrap the installer.** The overlay script updates the clone, runs
   `bin/partitor-install`, then runs its own checks.
4. **Keep your own scripts out of the clone** and out of the library contract
   (`LIBRARY-LAYOUT.md`).

## Sample setup script

Inspiration, not supported. Adapt it.

```bash
#!/usr/bin/env bash
# site-setup: bring this host to the pinned partitor release
set -euo pipefail
HERE="$(dirname "$(realpath -- "$0")")"
PIN="$(tr -d '[:space:]' < "$HERE/partitor.pin")"        # e.g. 0.4.0
CLONE=/opt/partitor
[[ "$PIN" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-rc\.[0-9]+)?$ ]] || { echo "bad pin: $PIN" >&2; exit 1; }

[[ -d "$CLONE/.git" ]] || git clone https://github.com/codexwilkes/partitor "$CLONE"
if [[ -n "$(git -C "$CLONE" status --porcelain)" ]]; then
  echo "$CLONE has local changes; not switching" >&2; exit 1
fi
git -C "$CLONE" fetch --tags --quiet
git -C "$CLONE" checkout --detach --quiet "$PIN"

"$CLONE/bin/partitor-install"      # settings stay in /etc/default/partitor

# site checks
grep -q '^PARTITOR_MEMORY_MAX=' /etc/default/partitor \
  || echo "WARN: PARTITOR_MEMORY_MAX not set (auto = 70 % of RAM)"
partitor --version
```

Tags have no `v` prefix. Release candidates look like `0.4.0-rc.1`.

## Sample sync script

Publishing and sync are out of scope for partitor (`../README.md`, Scope). If you
write your own, use only the contract in `LIBRARY-LAYOUT.md`. Inspiration, not
supported:

```bash
#!/usr/bin/env bash
# copy the current part PDFs of every piece to a web folder
set -euo pipefail
LIB=/var/lib/partitor/library
DEST=/srv/parts
for item in "$LIB"/library/*/; do
  [[ -d "$item/parts" ]] || continue
  name="$(basename "$item")"
  rsync -a --delete --include='*--*.pdf' --exclude='*' "$item/parts/" "$DEST/$name/"
done
```

Run it after a build. Do not publish scores you have no right to share.
