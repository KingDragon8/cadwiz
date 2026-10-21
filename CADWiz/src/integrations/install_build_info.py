# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Reads the install SHA `tools/ship.py` writes, for display where the
founder already looks (M-CASH-REGISTER, docs/factory/M-CASH-REGISTER.md,
item 4: "CADWiz: the assistant's first line / about").

Kept a thin, isolated read -- no FreeCAD import, so it is trivially unit
testable and the panel's greeting code never has to know the file format.
"""
from __future__ import annotations

import json
from pathlib import Path

INSTALL_SHA_FILE = (
    Path.home() / "AppData" / "Roaming" / "FreeCAD" / "v1-1" / "Mod" / "AI-FreeCAD" / "INSTALL_SHA.json"
)


def build_info_line(sha_file: Path | None = None) -> str:
    """Returns a one-line "Build: <sha> (<date>)" string, or "" if the
    install has never been shipped (no file yet) or the file is
    unreadable -- absence is shown as absence, never a fabricated value."""
    path = sha_file if sha_file is not None else INSTALL_SHA_FILE
    if not path.is_file():
        return ""
    try:
        info = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return ""
    sha = info.get("sha")
    built_at = info.get("built_at_utc")
    if not sha:
        return ""
    return f"Build: {sha}" + (f" ({built_at})" if built_at else "")
