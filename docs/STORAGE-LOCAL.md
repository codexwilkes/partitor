<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
<!-- Copyright (C) 2026 Nathan Wilkes and partitor contributors -->
# Local library

The library is a folder on the machine that runs partitor. This is the default.

## Layout

```
/var/lib/partitor/library/
  inbox/        copy score PDFs here
  library/      one folder per piece (made by partitor)
```

The default path is `/var/lib/partitor/library`. Another path: set
`PARTITOR_LIBRARY` in the config file before you run the installer (see below).
The path must be absolute, outside `/home` (the sandbox cannot see `/home`),
and made of letters, digits and `. _ / -`.

## Set up

`partitor-install` makes the folders: `<library>`, `inbox/` and `library/`, mode
`2770`, owner and group `partitor`. Members of the group `partitor` can read and
write them. Add yourself, then log in again:

```bash
sudo usermod -aG partitor "$USER"
```

Then copy PDFs without root:

```bash
cp score.pdf /var/lib/partitor/library/inbox/
sudo partitor
```

## Another path

Guided: `sudo bin/partitor-init --library /data/scores`. By hand:

```bash
printf 'PARTITOR_LIBRARY=/data/scores\n' > partitor.conf
sudo bin/partitor-install --config partitor.conf
```

The installer copies the file to `/etc/default/partitor`. If you move an existing
library, stop first, then `sudo mv` the folder and keep owner, group and mode
(`sudo cp -a` or `rsync -aH`), then run the installer again.

## Notes

- A disk path on a mounted Windows drive (WSL2 `/mnt/c/...`) is not supported:
  the file modes and the sandbox user do not work there. Not tested.
- A mounted external disk works when the mount gives `partitor` write access and
  the folder modes above. Make sure the disk is mounted before you run partitor.
- Back up the library folder. It is the only copy of your state. The host holds
  code and settings only.
