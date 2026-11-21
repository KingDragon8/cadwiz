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


def inspect(user_data: Path | None = None, *, include_paths: bool = False, runtime: dict | None = None) -> dict[str, Any]:
    roots = [user_data / "Mod"] if user_data else candidate_mod_dirs()
    installs = []
    issues = []
    loadable_backups = 0
    for mod in roots:
        if not mod.is_dir():
            continue
        try:
            folders = sorted(mod.iterdir())
        except OSError:
            issues.append("An add-on folder could not be inspected. Its contents remain unverified.")
            continue
        for folder in folders:
            name = folder.name.lower().replace("-", "")
            if not folder.is_dir() or not ("cadwiz" in name or name == "aifreecad"):
                continue
            # Backups are evidence, never active installations and never deleted.
            if any(word in folder.name.lower() for word in ("backup", "replaced", ".old")):
                if (folder / "InitGui.py").is_file() or (folder / "CADWiz/InitGui.py").is_file():
                    loadable_backups += 1
                continue
            found = [p.parent for pattern in ('InitGui.py', 'CADWiz/InitGui.py', '*/CADWiz/InitGui.py')
                     for p in folder.glob(pattern)]
            addon = found[0] if found else folder
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
            if len(found) > 1:
                problems.append('Multiple workbench roots exist inside this installation.')
            if addon != folder and addon.parent != folder:
                problems.append('Nested release directory found; use the workbench-only repair installer.')
            version = 'unknown'
            try:
                tree = ast.parse((addon / 'src/integrations/cadwiz_plugin/__init__.py').read_text(encoding='utf-8-sig'))
                for node in tree.body:
                    if isinstance(node, ast.Assign) and any(isinstance(n, ast.Name) and n.id == 'CADWIZ_VERSION' for n in node.targets):
                        version = ast.literal_eval(node.value)
            except (OSError, ValueError, SyntaxError):
                pass
            item = {"candidate": len(installs) + 1, "files_checked": True, 'version': version,
                    'method': 'repository-layout' if addon == folder / 'CADWiz' else 'manual' if addon == folder else 'nested-or-incomplete',
                    "problems": problems}
            if include_paths:
                item['directory'] = str(addon)
            installs.append(item)
    if loadable_backups:
        issues.append("Backup add-ons still contain startup code inside Mod and may also load. Preserve them; review a move outside Mod before repairing.")
    if not installs:
        issues.append("No CADWiz installation found in the checked add-on folders.")
    if len(installs) > 1:
        issues.append("Multiple candidate installations found; preserve them and identify the active one in FreeCAD.")
    if not user_data:
        issues.append("Active FreeCAD add-on directory is unverified. Obtain FreeCAD.getUserAppDataDir() from the running instance.")
    missing = []
    for name in ('mcp',):
        try:
            available = importlib.util.find_spec(name) is not None
        except (ImportError, ValueError):
            available = False
        if not available:
            missing.append(name)
    if missing:
        issues.append("Connector dependency is unavailable in this Python; check again using FreeCAD's Python.")
    # A caller cannot turn a filesystem scan into proof of GUI activation.
    result = {"schema_version": 1, "system": platform.system(), "architecture": platform.machine(),
            "python": platform.python_version(), "offline": True, "read_only": True,
            "directory_confidence": "confirmed" if user_data else "undetermined",
            "installations": installs, "loadable_backups": loadable_backups,
            "issues": issues, "missing_dependencies": missing,
            "startup_verified": False, "ai_connection_verified": False,
            "next_action": "In the existing FreeCAD window, verify CADWiz opens and the connection works. No files were changed."}
    manifests = list((user_data / 'CADWiz-backups').glob('*/rollback.json')) if user_data else []
    result['rollback_records'] = len(manifests)
    result['runtime'] = runtime or {'workbench_registered': 'NOT VERIFIED', 'panel_open': 'NOT VERIFIED',
                                   'freecad_version': 'NOT VERIFIED', 'assistant_connected': 'NOT VERIFIED'}
    if include_paths and user_data:
        result['checked_user_data'] = str(user_data)
    return result


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
    parser.add_argument('--local-paths', action='store_true', help='Include local paths; review before sharing.')
    args = parser.parse_args()
    print(json.dumps(inspect(args.user_data, include_paths=args.local_paths), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
