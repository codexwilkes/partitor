<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
<!-- Copyright (C) 2026 Nathan Wilkes and partitor contributors -->
# Install

partitor runs on one Linux host. The installer sets up the host and checks the
result. It is safe to run again.

## Requirements

- Ubuntu 26.04 LTS with systemd (the tested platform). Ubuntu 24.04 should work:
  the pinned packages have wheels for its Python 3.12 and the tests pass there
  (`KNOWN-LIMITS.md`). macOS and hosts without
  systemd are not supported yet (`KNOWN-LIMITS.md`).
- Root access (`sudo`).
- Internet access during the install (apt and PyPI).
- Memory: not measured on small hosts. A detect or a build uses worker processes under a
  memory cap; the default cap is 70 % of the RAM (`SANDBOX.md`). Long scans of
  books need more memory than clean vector scores.
- Disk: the venv holds the Python packages (several hundred MB). The library
  size depends on your scores.

## Steps

1. Install the system packages. The installer only checks them and prints this
   command when one is missing:

   ```bash
   sudo apt install git python3-venv tesseract-ocr
   # SMB library: also cifs-utils
   ```

2. Get the code. The clone is the install: the venv lives inside it.

   ```bash
   sudo git clone https://github.com/codexwilkes/partitor /opt/partitor
   cd /opt/partitor
   sudo git checkout --detach 0.4.0        # a release tag, not main
   ```

3. Choose the storage (`STORAGE-LOCAL.md` or `STORAGE-SMB.md`).

4. Run the guided setup, or the installer directly.

   **Guided** (recommended): it asks where the library lives (local folder or
   SMB share), the path, for SMB the host, share, user and password (the
   password is not echoed; it goes to `/etc/partitor/smb.cred`, mode 0600), the
   memory cap and an optional logo. It shows a summary, writes
   `/etc/default/partitor` (settings it does not ask about are kept), and runs
   the installer.

   ```bash
   sudo bin/partitor-init
   sudo bin/partitor-init --yes                  # defaults, no questions
   sudo bin/partitor-init --yes --library /data/scores --memory 8G
   sudo bin/partitor-init --no-install --out partitor.conf   # write the file only
   ```

   Options: `--yes`, `--library PATH`, `--smb-host HOST`, `--smb-share NAME`,
   `--memory SIZE`, `--logo FILE`, `--no-install`, `--out FILE`. The password
   is only read from the terminal.

   **Direct**: the default is a local library in `/var/lib/partitor/library`; then
   no config file is needed. Otherwise write a config file with `KEY=value`
   lines, for example `partitor.conf`:

   ```bash
   sudo bin/partitor-install                      # default settings
   sudo bin/partitor-install --config partitor.conf
   ```

   Every line must say `ok`. A `FAIL` line says what to do. `WARN` means a
   non-fatal problem, for example a NAS that is off.

5. Check it:

   ```bash
   sudo partitor --version
   sudo partitor --sandbox-check --library
   ```

6. Use it: copy a PDF into the `inbox/` folder of the library and run
   `sudo partitor` (`OPERATING.md`, `operator-flow.html`).

## What the installer does

In order (details in the header of `bin/partitor-install`):

1. Checks the apt packages. It does not install them.
2. Creates the system user `partitor` (own group, no login shell).
3. Creates `/var/lib/partitor` and `/var/lib/partitor/work`.
4. Copies `--config FILE` to `/etc/default/partitor`.
5. Local library: creates `<library>`, `inbox/`, `library/` with mode `2770`.
6. Creates the venv in the clone, and installs `requirements.txt` into it again
   when the file changes.
7. Compiles the bytecode of the engine package `lib/partitor` as root (a file
   that has no `.pyc`, or is newer than it). Checks that the user `partitor` can
   read every file of the package; if not, it warns and prints the fix command.
8. Links `partitor`, `partitor-init` and `partitor-install` in
   `/usr/local/sbin` to the scripts in `bin/`.
9. Runs the sandbox self-test.
10. SMB library: checks `/etc/partitor/smb.cred`, writes the mount and automount
   units, enables the automount, and checks the library as the sandbox user.

`--check` reports without changing anything (exit 1 on a difference).
`--dry-run` lists what a run would change (exit 0).

## Settings file

`/etc/default/partitor` holds `KEY=value` lines. The wrapper reads it at every
run. Keys: `PARTITOR_LIBRARY`, `PARTITOR_SMB_HOST`, `PARTITOR_SMB_SHARE`
(storage; the installer reads these); `PARTITOR_MEMORY_MAX`, `PARTITOR_JOBS`,
`PARTITOR_CPU_WEIGHT`, `PARTITOR_IO_WEIGHT`, `PARTITOR_RUNTIME_MAX`
(`SANDBOX.md`); `PARTITOR_LIST_PAGE` (menu items per page, 5-200);
`PARTITOR_LOGO` (a PNG file for title and back pages; unset = no logo). Keep the file
outside `/home`, `/root` and `/tmp` (the sandbox hides them) and readable by the service
user; `partitor-install` warns when it is not.
An environment variable `PARTITOR_LIBRARY` beats the file.

## Upgrade

```bash
cd /opt/partitor
sudo git fetch --tags
sudo git checkout --detach <new tag>
sudo bin/partitor-install
```

The installer compiles the bytecode of the new `lib/partitor` (step 7), so run it
after every checkout.

Read `CHANGELOG.md` first, especially "Library layout" and BREAKING lines.
After an engine update, `sudo partitor analyse --all` analyses every item again;
it keeps your edits.

## Uninstall

The installer removes nothing. By hand:

```bash
sudo rm /usr/local/sbin/partitor
sudo rm -rf /opt/partitor
sudo rm -rf /etc/partitor /etc/default/partitor
# SMB: stop and remove the units (use your unit names)
sudo systemctl disable --now mnt-partitor.automount mnt-partitor.mount
sudo rm /etc/systemd/system/mnt-partitor.{mount,automount}
# State and library (this deletes your parts):
sudo rm -rf /var/lib/partitor
sudo userdel partitor
```

Back up the library first.
