# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Import every CADWiz module once.

    python scripts/ci/import_every_module.py            # plain Python (CI)
    "C:\\Program Files\\FreeCAD 1.1\\bin\\freecadcmd.exe" scripts/ci/import_every_module.py   # inside FreeCAD

A module may only fail to import because it needs FreeCAD itself (FreeCAD,
FreeCADGui, Part, PySide, ...) and FreeCAD is not there; that is reported as
"needs FreeCAD". Any other failure -- a missing CADWiz file, a typo, a removed
dependency -- fails the check. Run inside FreeCAD, nothing may be skipped.
"""
from __future__ import annotations

import importlib
import importlib.util
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "CADWiz" / "src"
VENDOR = ROOT / "CADWiz" / "vendor" / "robust-mcp" / "src"
FREECAD_ONLY = {"FreeCAD", "FreeCADGui", "Part", "PartDesign", "Sketcher", "Mesh", "MeshPart", "TechDraw", "Draft",
                "PySide", "PySide2", "PySide6", "pivy", "BasicShapes", "bpy", "bmesh", "mathutils", "pymeshlab"}
#: Programs CADWiz starts as their own process (FreeCAD without a window, Blender,
#: a separate Python). Importing them would run them, so they are compiled instead.
ENTRY_POINTS = {"integrations.ai_master.worker", "integrations.cadwiz_plugin.drawing_job",
                "integrations.cadwiz_plugin.geometry_job", "integrations.cadwiz_plugin.mesh_job",
                "integrations.mcp_tools.collision_worker", "integrations.mcp_tools.exec_worker",
                "integrations.mcp_tools.probe_runner"}


def modules() -> list[str]:
    found = []
    for path in sorted(SRC.rglob("*.py")):
        parts = list(path.relative_to(SRC).with_suffix("").parts)
        if parts[-1] == "__init__":
            parts = parts[:-1]
        found.append(".".join(parts))
    return found


def main() -> int:
    for path in (str(SRC), str(VENDOR)):
        if path not in sys.path:
            sys.path.insert(0, path)
    inside_freecad = "FreeCAD" in sys.modules or importlib.util.find_spec("FreeCAD") is not None
    ok, needs_freecad, failed = 0, [], []
    for name in modules():
        if name in ENTRY_POINTS:
            source = SRC.joinpath(*name.split(".")).with_suffix(".py")
            try:
                compile(source.read_text(encoding="utf-8"), str(source), "exec")
                ok += 1
            except SyntaxError:
                failed.append((name, traceback.format_exc(limit=1)))
            continue
        try:
            importlib.import_module(name)
            ok += 1
        except ModuleNotFoundError as error:
            if (error.name or "").split(".")[0] in FREECAD_ONLY and not inside_freecad:
                needs_freecad.append(name)
            elif (error.name or "").split(".")[0] in {"bpy", "bmesh", "mathutils", "pymeshlab"}:
                needs_freecad.append(name)        # Blender / PyMeshLab scripts run in their own programs
            else:
                failed.append((name, traceback.format_exc(limit=2)))
        except Exception:  # noqa: BLE001
            failed.append((name, traceback.format_exc(limit=2)))
    print(f"imported {ok}; needs FreeCAD or an optional tool: {len(needs_freecad)}; FAILED: {len(failed)}")
    for name in needs_freecad:
        print(f"  needs FreeCAD/tool: {name}")
    for name, why in failed:
        print(f"  FAILED: {name}\n{why}")
    return 1 if failed else 0


if __name__ in ("__main__", "import_every_module"):
    code = main()
    if __name__ == "__main__":
        sys.exit(code)
