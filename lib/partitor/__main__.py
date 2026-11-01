# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""python -m partitor: the same entry point as lib/partitor-engine (PYTHONPATH must hold lib/)."""
import sys

from partitor.cli_main import main

if __name__ == "__main__":
    sys.exit(main())
