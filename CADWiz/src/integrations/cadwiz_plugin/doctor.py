# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Offline, read-only installation checks; does not import FreeCAD or user code.

Run with Python even when the workbench cannot load. An explicit user-data
directory from the running FreeCAD is authoritative; guessed paths are candidates.
Reports contain no file contents, user paths, credentials, geometry or prompts.
"""
from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import platform
import sys
from pathlib import Path
from typing import Any


def inspect(user_data: Path | None = None) -> dict[str, Any]:
    roots = [user_data / "Mod"] if user_data else candidate_mod_dirs()
    installs = []
    for mod in roots:
        if not mod.is_dir():
            continue
        for folder in sorted(mod.iterdir()):
            name = folder.name.lower().replace("-", "")
            if not folder.is_dir() or not ("cadwiz" in name or name == "aifreecad"):
                continue
            # Backups are evidence, never active installations and never deleted.
            if any(word in folder.name.lower() for word in ("backup", "replaced", ".old")):
                continue
            addon = folder / "CADWiz" if (folder / "CADWiz").is_dir() else folder
            init = addon / "InitGui.py"
            problems = []
            if not init.is_file():
                problems.append("Startup file is missing.")
            else:
                try:
                    ast.parse(init.read_text(encoding="utf-8-sig"))
                except (OSError, UnicodeError, SyntaxError):
                    problems.append("Startup file cannot be read or parsed.")
            if not (addon / "src/integrations/cadwiz_plugin/addon.py").is_file():
                problems.append("Panel source is missing or this is a development link install.")
            installs.append({"candidate": len(installs) + 1, "files_checked": True,
                             "problems": problems})
    issues = []
    if not installs:
        issues.append("No CADWiz installation found in the checked add-on folders.")
    if len(installs) > 1:
        issues.append("Multiple candidate installations found; preserve them and identify the active one in FreeCAD.")
    if not user_data:
        issues.append("Active FreeCAD add-on directory is unverified. Obtain FreeCAD.getUserAppDataDir() from the running instance.")
    missing = [name for name in ("mcp",) if importlib.util.find_spec(name) is None]
    if missing:
        issues.append("Connector dependency is unavailable in this Python; check again using FreeCAD's Python.")
    # A caller cannot turn a filesystem scan into proof of GUI activation.
    return {"schema_version": 1, "system": platform.system(), "architecture": platform.machine(),
            "python": platform.python_version(), "offline": True, "read_only": True,
            "directory_confidence": "confirmed" if user_data else "undetermined",
            "installations": installs, "issues": issues, "missing_dependencies": missing,
            "startup_verified": False, "ai_connection_verified": False,
            "next_action": "In the existing FreeCAD window, verify CADWiz opens and the connection works. No files were changed."}


def candidate_mod_dirs() -> list[Path]:
    import os

    home = Path.home()
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", home / "AppData/Roaming")) / "FreeCAD"
    elif sys.platform == "darwin":
        base = home / "Library/Application Support/FreeCAD"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", home / ".local/share")) / "FreeCAD"
    candidates = [base / "Mod", *sorted(base.glob("v*/Mod"))]
    if sys.platform == "darwin":
        candidates.append(home / "Library/Preferences/FreeCAD/Mod")
    return list(dict.fromkeys(candidates))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-data", type=Path, help="FreeCAD.getUserAppDataDir() from your running FreeCAD")
    args = parser.parse_args()
    print(json.dumps(inspect(args.user_data), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
