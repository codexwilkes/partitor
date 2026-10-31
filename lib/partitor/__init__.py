# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Nathan Wilkes and partitor contributors
"""partitor engine package.

Today this package holds only `VERSION`. The engine code still lives in the
script `lib/partitor-engine`; it moves here in small steps (docs/DESIGN.md
§12). This file must stay free of imports: every start of the engine reads it.
"""

VERSION = "0.5.0-dev.2"
