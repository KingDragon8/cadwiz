# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Mesh jobs that need pymeshlab, run in the system Python (ORDER-2026-10-18-02 B).

pymeshlab is installed in the founder's system Python, not in FreeCAD's, so the
plug-in runs these as a separate process (never on FreeCAD's window thread):

    python -m integrations.cadwiz_plugin.mesh_job <request.json> <result.json>

  repair   pymeshlab clean-up before printing: duplicates, unreferenced and null
           faces, non-manifold edges and vertices, holes up to a size, faces turned
           the same way; optionally drop tiny loose bits. Reports before and after.
  inspect  the same measures without changing anything.
  swap     the proven component-swap pipeline (mesh_component_swap_runner: the
           region gate, then Blender removes the held part and fills the hole);
           the replacement is made separately so it stays its own part.

Every job writes only the output path it was given (a new file), never the input.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def _measures(mesh_set: Any) -> dict[str, Any]:
    measures = dict(mesh_set.get_topological_measures())
    current = mesh_set.current_mesh()
    box = current.bounding_box()
    return {"faces": int(current.face_number()), "vertices": int(current.vertex_number()),
            "pieces": int(measures.get("connected_components_number", 0)), "holes": int(measures.get("number_holes", 0)),
            "boundary_edges": int(measures.get("boundary_edges", 0)),
            "non_manifold_edges": int(measures.get("non_two_manifold_edges", 0)),
            "watertight": bool(measures.get("boundary_edges", 1) == 0 and measures.get("is_mesh_two_manifold", False)),
            "size_mm": [float(box.dim_x()), float(box.dim_y()), float(box.dim_z())]}


def repair(request: dict[str, Any]) -> dict[str, Any]:
    import pymeshlab

    source, output = Path(request["source"]), Path(request["output"])
    if output.exists():
        raise ValueError("the output file already exists; a repair never overwrites a file")
    mesh_set = pymeshlab.MeshSet()
    mesh_set.load_new_mesh(str(source))
    before = _measures(mesh_set)
    mesh_set.meshing_remove_duplicate_vertices()
    mesh_set.meshing_remove_duplicate_faces()
    mesh_set.meshing_remove_null_faces()
    mesh_set.meshing_remove_unreferenced_vertices()
    mesh_set.meshing_repair_non_manifold_edges()
    mesh_set.meshing_repair_non_manifold_vertices()
    max_hole = int(request.get("max_hole_edges") or 100)
    try:
        mesh_set.meshing_close_holes(maxholesize=max_hole)
    except Exception as error:  # noqa: BLE001 - a hole too complex to close is reported, not fatal
        before.setdefault("notes", []).append(f"some holes could not be closed automatically ({type(error).__name__})")
    mesh_set.meshing_re_orient_faces_coherently()
    if request.get("drop_bits_under_faces"):
        mesh_set.meshing_remove_connected_component_by_face_number(mincomponentsize=int(request["drop_bits_under_faces"]))
    after = _measures(mesh_set)
    output.parent.mkdir(parents=True, exist_ok=True)
    mesh_set.save_current_mesh(str(output))
    return {"ok": True, "before": before, "after": after, "output": str(output)}


def inspect(request: dict[str, Any]) -> dict[str, Any]:
    import pymeshlab

    mesh_set = pymeshlab.MeshSet()
    mesh_set.load_new_mesh(str(request["source"]))
    return {"ok": True, "measures": _measures(mesh_set)}


def swap(request: dict[str, Any]) -> dict[str, Any]:
    from ai_freecad_core.workflow.mesh_component_swap import GeometricRegionSelector
    from integrations.mesh_component_swap_runner import run_mesh_component_swap

    region = request["region"]
    selector = GeometricRegionSelector(tuple(region["center"]), tuple(region["axis"]), float(region["radius_mm"]),
                                       float(region["half_length_mm"]))
    manifest = run_mesh_component_swap(Path(request["source"]), selector, None, destination=Path(request["output"]),
                                       protected_subject=str(request.get("keep") or "the model"),
                                       edit_target=str(request.get("remove") or "the held part"),
                                       transition_description="the region the user marked", confidence=1.0)
    attempts = list(manifest.attempts or ())
    succeeded = bool(attempts and attempts[0].succeeded and Path(request["output"]).is_file())
    plan = manifest.region_plan
    return {"ok": succeeded, "output": request["output"] if succeeded else "",
            "region_disposition": getattr(getattr(plan, "disposition", None), "value", ""),
            "route": str(getattr(manifest.difficulty, "primary_route", "")),
            "evidence": [str(e) for e in (manifest.validation.evidence if manifest.validation else ())],
            "why_not": "" if succeeded else _why_not(manifest)}


def _why_not(manifest: Any) -> str:
    plan = manifest.region_plan
    if plan is not None and plan.disposition.value != "local_required":
        return f"the marked region was not accepted for a local change ({plan.disposition.value}): mark just the held part, a little larger than it"
    if manifest.difficulty.primary_route is None:
        return "the mesh analysis could not choose a safe way to change it"
    if not manifest.attempts:
        return "Blender or pymeshlab was not found on this computer"
    return "Blender ran but the result did not pass its checks"


JOBS = {"repair": repair, "inspect": inspect, "swap": swap}


def main(argv: list[str]) -> int:
    request_path, result_path = Path(argv[0]), Path(argv[1])
    request = json.loads(request_path.read_text(encoding="utf-8"))
    try:
        result = JOBS[request["job"]](request)
    except Exception as error:  # noqa: BLE001 - every failure goes back as one line for Claude
        result = {"ok": False, "error": f"{type(error).__name__}: {error}"}
    result_path.write_text(json.dumps(result, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
