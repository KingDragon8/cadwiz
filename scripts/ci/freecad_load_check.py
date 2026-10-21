# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Load the CADWiz addon in FreeCAD without a window and check it is whole.

    freecadcmd scripts/ci/freecad_load_check.py

Runs inside FreeCAD's own Python (FreeCAD 1.1.3): imports every CADWiz module
with FreeCAD present (nothing may be skipped), then makes a box through CADWiz's
plug-in session -- the same code Claude's tools run -- and reads it back. Writes
`freecad-load-check.txt` beside this script's repo root and exits non-zero on any
failure. No network, no AI.
"""
from __future__ import annotations

import os
import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(os.environ.get("CADWIZ_REPO") or Path(__file__).resolve().parents[2])
OUT = ROOT / "freecad-load-check.txt"
lines: list[str] = []


def say(text: str) -> None:
    lines.append(text)
    print(text)


def run() -> int:
    sys.path[:0] = [str(ROOT / "CADWiz" / "src"), str(ROOT / "CADWiz" / "vendor" / "robust-mcp" / "src")]
    import FreeCAD

    say("FreeCAD " + ".".join(FreeCAD.Version()[:3]))
    sys.path.insert(0, str(ROOT / "scripts" / "ci"))
    import import_every_module

    code = import_every_module.main()
    say(f"import every module inside FreeCAD: {'PASS' if code == 0 else 'FAIL'}")
    from integrations.cadwiz_plugin.session import PluginSession

    work = Path(tempfile.mkdtemp(prefix="cadwiz-load-check-"))
    doc = FreeCAD.newDocument("LoadCheck")
    box = doc.addObject("Part::Box", "Box")
    box.Length, box.Width, box.Height = 40, 25, 12
    doc.recompute()
    doc.saveAs(str(work / "LoadCheck.FCStd"))
    session = PluginSession(app=FreeCAD, project_root=work / "projects", log_path=work / "tool-calls.jsonl")
    seen = session.call("inspect_document", {"document": "LoadCheck"})
    whole = seen.get("ok") and "Box" in str(seen)
    say(f"plug-in session reads a model in FreeCAD: {'PASS' if whole else 'FAIL'}")
    return 0 if code == 0 and whole else 1


try:
    result = run()
except Exception:  # noqa: BLE001
    say("FAIL:\n" + traceback.format_exc())
    result = 1
OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
os._exit(result)
