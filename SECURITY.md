<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
<!-- Copyright (C) 2026 Nathan Wilkes and partitor contributors -->
# Security

## What partitor does with untrusted input

partitor opens PDF files. MuPDF, the library that parses them, has a history of
security bugs, and a score PDF often comes from the internet. So:

- The engine runs as the system user `partitor`, never as root, in a systemd
  sandbox: no network, a read-only system, no `/home`, limited writes, memory
  and time limits (`docs/SANDBOX.md`).
- The root wrapper never opens a PDF.
- The sandbox limits the damage of a parser bug. It is not a guarantee. Keep the
  system and the Python packages updated, and do not process PDFs from sources
  you do not trust.
- The engine does not make network connections. The only network use is the
  installer (apt, PyPI) and, in SMB mode, the host's mount of the share.
- Without systemd (for example by hand on macOS) there is no sandbox.

SMB credentials are in `/etc/partitor/smb.cred` (0600, root). They are never in
the repository and never printed.

## Report a vulnerability

Use GitHub private vulnerability reporting on this repository (Security tab,
"Report a vulnerability"), or write to partitor@codexwilkes.com. Please do not
open a public issue for a vulnerability.

Include the version (`partitor --version`), the system, and steps to reproduce.
Do not send a PDF you have no right to share; describe it, or make a minimal one.

This is a hobby project. Reports are handled on a best-effort basis; there is no
fixed response time and no bounty. The maintainer will not log in to your
systems. Fixes go to the newest release only.

## Supported versions

The newest release.
