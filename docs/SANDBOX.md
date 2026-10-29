<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
<!-- Copyright (C) 2026 Nathan Wilkes and partitor contributors -->
# Sandbox

partitor parses PDFs from the internet, and MuPDF has had security bugs. So the
engine never runs as root and never runs unconfined. The wrapper `bin/partitor`
(run as root, usually through `sudo partitor`) checks the paths, then starts the
engine with `systemd-run` as the system user `partitor`.

The wrapper never reads a PDF. It needs systemd (`systemd-run`).

## What the sandbox sets

| Property | Effect |
|---|---|
| `--uid=partitor --gid=partitor` | The engine is not root. It refuses to run as root. |
| `ProtectSystem=strict` | The whole file system is read-only. |
| `ReadWritePaths=` | Only `/var/lib/partitor`, and (library commands) the library folder. |
| `ProtectHome=yes` | `/home`, `/root` and `/run/user` are not visible. |
| `PrivateTmp=yes`, `PrivateDevices=yes` | Own `/tmp`; no device nodes. |
| `PrivateNetwork=yes`, `RestrictAddressFamilies=AF_UNIX` | No network. |
| `NoNewPrivileges=yes`, `CapabilityBoundingSet=` | No privilege gain; no capabilities. |
| `RestrictNamespaces`, `LockPersonality`, `RestrictRealtime`, `SystemCallArchitectures=native` | Fewer kernel features. |
| `ProtectKernelTunables`, `ProtectKernelModules`, `ProtectControlGroups` | Read-only kernel interfaces. |
| `UMask=0027` | New files are not world-readable. |
| `MemoryMax`, `CPUWeight`, `IOWeight`, `Nice=10`, `RuntimeMaxSec` | Limits (below). Other services keep priority. |

## Limits you can change

Set them in `/etc/default/partitor` (`KEY=value` lines):

| Key | Default | Meaning |
|---|---|---|
| `PARTITOR_MEMORY_MAX` | `auto` | Hard memory cap of one run, all workers together. `auto` = 70 % of the machine's memory, at least 1G. Or a size such as `8G`. Set it lower when other services need memory. |
| `PARTITOR_JOBS` | `auto` | Worker processes of a build. `auto` = CPUs - 1, at most 6, and as many as the memory cap holds (about 1.5 GB each, 2 GB for the main process). |
| `PARTITOR_CPU_WEIGHT` | 20 | cgroup CPU weight (100 = normal). |
| `PARTITOR_IO_WEIGHT` | 20 | cgroup IO weight (100 = normal). |
| `PARTITOR_RUNTIME_MAX` | 3600 | Seconds before a run is stopped. |

The workers run in the same unit, so the limits cover all of them together.

## Check it

```bash
sudo partitor --sandbox-check            # every line must say ok
sudo partitor --sandbox-check --library  # the same, plus the library folder
```

The installer runs the first check at the end. The check runs the engine inside
the sandbox and prints one line per item: the user is not root, no network
socket can open, the system is read-only, `/root` is hidden, the work folder is
writable. With `--library` it also tests that `inbox/` and `library/` are
writable. Memory, CPU and IO limits are not tested by this command.

## What the sandbox does not do

It limits the damage of a parser bug. It is not a guarantee. Keep the system
updated and do not feed partitor PDFs from sources you do not trust. See
`../SECURITY.md`.
