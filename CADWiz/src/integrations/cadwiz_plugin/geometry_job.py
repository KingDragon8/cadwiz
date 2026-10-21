# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""The pairwise parts check (loose and overlapping parts), run by FreeCAD's
windowless program for the Problems list (ORDER-2026-10-19-03).

    freecadcmd geometry_job.py <folder>/manifest.json

The manifest lists each visible solid of the founder's model as a BREP file the
window wrote out. The answer goes to answer.json beside it. Its OpenCASCADE
calls can take minutes on a swept or lofted shape; here that costs only this
process, which the window stops after `problems_watch.GEOMETRY_TIME_LIMIT_S`.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[2]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

#: Here a slow overlap costs nothing but this process: let them all run.
OVERLAP_BUDGET_S = 60.0


def main(manifest_path: str) -> None:
    import Part  # noqa: PLC0415 - FreeCAD's own module

    from integrations.cadwiz_plugin.problems_watch import pair_problems  # noqa: PLC0415

    manifest = Path(manifest_path)
    parts = []
    for row in json.loads(manifest.read_text(encoding="utf-8")):
        shape = Part.read(row["brep"])
        solid = shape.Solids[0] if shape.Solids else shape
        parts.append((row["name"], row["label"], solid))
    found = pair_problems(parts, overlap_budget_s=OVERLAP_BUDGET_S)
    answer = manifest.with_name("answer.json")
    partial = answer.with_suffix(".part")
    partial.write_text(json.dumps([p.to_dict() for p in found]), encoding="utf-8")
    partial.replace(answer)


main([a for a in sys.argv if a.endswith("manifest.json")][-1])
