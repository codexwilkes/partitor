# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""Entry point of partitor on Windows: install the Windows hooks, then run the normal CLI.

From a source tree:  set PYTHONPATH=lib;platforms\\windows  then  py -3.12 -m partitor_windows
partitor.exe (build-windows.py) starts here too."""
import sys

from partitor import cli_main, hooks
from partitor_windows import pack


def main() -> int:
    hooks.install(pack)
    return cli_main.main()


if __name__ == "__main__":
    sys.exit(main())
