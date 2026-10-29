<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
<!-- Copyright (C) 2026 Nathan Wilkes and partitor contributors -->
# Library on an SMB share (NAS)

partitor can keep the library on a network share. The host mounts the share on
first use with systemd (an automount) and unmounts it when idle. The boot never
depends on the NAS.

Mode: set `PARTITOR_SMB_HOST`. Without it, the library is local
(`STORAGE-LOCAL.md`).

## 1. On the NAS

Steps and labels differ by vendor. The example is Synology DSM 7.2; **check each
label on your DSM**.

1. Make a long random password (32 characters or more) and keep it in your
   password manager:
   `tr -dc 'A-Za-z0-9' </dev/urandom | head -c 32; echo`
2. Shared folder: create `partitor` (any name; see `PARTITOR_SMB_SHARE`). Recycle
   bin on. No other user or group gets access.
3. User: create `partitor` with that password, not in the administrators group.
   Shared folder permission: read/write on this share, no access on every other
   share. Application permission: SMB only (no DSM, File Station, FTP, WebDAV,
   rsync).
4. SMB settings (Control Panel > File Services > SMB > Advanced): maximum SMB
   protocol SMB3. Transport encryption: the mode where the client chooses. The
   mount uses `seal` (encrypted); with encryption "disabled" on the server, the
   mount fails with error -95.
5. Firewall, if it is on: allow SMB (port 445) from the partitor host only.
   Never expose SMB to the internet.
6. In the share, make the folders `inbox` and `library`.

## 2. On the host

The guided way: `sudo bin/partitor-init`, answer 2 (SMB), then host, share, user
and password. It writes the config file and the credentials and runs the
installer. The manual way follows.

Config file (for example `partitor.conf`):

```
PARTITOR_LIBRARY=/mnt/partitor
PARTITOR_SMB_HOST=nas.example.net
PARTITOR_SMB_SHARE=partitor
```

`PARTITOR_LIBRARY` is the mount point. The host name or IPv4 address uses
letters, digits, `.` and `-` only.

Credentials (root only; the password is not echoed and is not in shell history;
`printf` is a shell builtin, so it does not show in `ps`):

```bash
sudo install -d -m 0750 /etc/partitor
sudo install -m 0600 /dev/null /etc/partitor/smb.cred
read -rp 'NAS user: ' u; read -rsp 'NAS password: ' p; echo
printf 'username=%s\npassword=%s\n' "$u" "$p" | sudo tee /etc/partitor/smb.cred >/dev/null
unset u p
sudo stat -c '%a %U:%G' /etc/partitor/smb.cred      # 600 root:root
```

Install:

```bash
sudo apt install cifs-utils
sudo bin/partitor-install --config partitor.conf
```

The installer writes the mount and automount units from `share/systemd/*.in`
(the unit name comes from the mount point: `/mnt/partitor` gives
`mnt-partitor.mount`), enables the automount, and checks the library as the
sandbox user. Run it again after you change the host, the share or the
credentials.

## 3. Check

```bash
ls /mnt/partitor                      # inbox  library (mounts on access)
findmnt /mnt/partitor                 # type cifs, options include vers=3.1.1 and seal
systemctl status mnt-partitor.automount --no-pager
sudo partitor --sandbox-check --library
```

If the mount fails: `journalctl -u mnt-partitor.mount -n 30 --no-pager`.

| Mount error | Likely cause |
|---|---|
| `Permission denied` (-13) | Wrong user or password in `smb.cred`; the NAS user has no SMB permission. |
| `Operation not supported` (-95) | Transport encryption is disabled on the NAS, or SMB3 is off. |
| `Host is down` (-112), timeout | Wrong `PARTITOR_SMB_HOST`, NAS off, or a firewall rule. |

After a change to `smb.cred` or the host: run the installer again and
`sudo systemctl restart mnt-partitor.automount` (use your unit name).

## Notes

- The mount owner is the sandbox user `partitor` (`uid`, `gid`, file mode 0660,
  directory mode 0770). Files appear on the NAS as that user.
- A NAS that is off gives a warning from the installer, and the hint
  "library folder not reachable" from `partitor`. Commands that need no library
  (`detect`, `build`, `pieces` in the work folder) still work.
- Not tested: the automount inside the sandbox across the idle unmount (about
  10 minutes) during a long menu session. Report problems.
