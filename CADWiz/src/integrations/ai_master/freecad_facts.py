# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Measure a FreeCAD document into a `FactReport` (Phase 1.4, the FreeCAD side).

Duck-typed over the document and its objects so it runs against a real
`FreeCAD.Document` inside FreeCAD and against stand-ins in a unit test. Every
number is read from the shape; anything that cannot be read is None (reported
as "could not measure"), never guessed. Estimates say so (`min_wall_is_estimate`).
"""
from __future__ import annotations

import math
from typing import Any, Iterable

from ai_freecad_core.ai_master.design_contract import DesignContract
from ai_freecad_core.ai_master.fact_layer import FactReport, PrinterProfile, finish_report
from integrations.ai_master.shape_box import tight_box

_PARAMETRIC_TYPES = ("PartDesign::Body", "Sketcher::SketchObject", "PartDesign::")
_MESH_TYPES = ("Mesh::",)


def _objects(document: Any, names: Iterable[str] | None) -> list[Any]:
    objects = list(getattr(document, "Objects", None) or [])
    if names:
        wanted = set(names)
        objects = [o for o in objects if getattr(o, "Name", "") in wanted or getattr(o, "Label", "") in wanted]
    return objects


def _shape_of(obj: Any) -> Any | None:
    shape = getattr(obj, "Shape", None)
    try:
        if shape is None or (callable(getattr(shape, "isNull", None)) and shape.isNull()):
            return None
    except Exception:  # noqa: BLE001
        return None
    return shape


def _holes(shape: Any) -> list[dict[str, float]]:
    """Cylindrical faces whose axis runs through material: each distinct radius
    counts as one hole. A rough, honest count -- a through-hole has one face."""
    holes: list[dict[str, float]] = []
    seen: set[float] = set()
    try:
        for face in getattr(shape, "Faces", []) or []:
            surface = getattr(face, "Surface", None)
            if surface is None or type(surface).__name__ != "Cylinder":
                continue
            radius = float(getattr(surface, "Radius", 0.0))
            if radius <= 0:
                continue
            # A cylinder face that is a hole curves inward: its area is less than
            # a full cylinder of its bounding height would need for an outer wall.
            box = face.BoundBox
            height = max(box.XLength, box.YLength, box.ZLength)
            key = round(radius, 2)
            if key in seen:
                continue
            seen.add(key)
            holes.append({"diameter_mm": round(2 * radius, 3), "depth_mm": round(float(height), 3)})
    except Exception:  # noqa: BLE001
        pass
    return holes


def _hollow_and_wall(shape: Any, bbox: tuple[float, float, float]) -> tuple[bool | None, float | None]:
    """Hollow if the solid fills much less than its outer envelope; wall as an
    ESTIMATE volume / (outer area / 2). Good for shells, labelled as estimate."""
    try:
        volume = float(shape.Volume)
        area = float(shape.Area)
    except Exception:  # noqa: BLE001
        return None, None
    if volume <= 0 or area <= 0 or min(bbox) <= 0:
        return None, None
    # A shell's volume is roughly its surface times its wall (two faces each),
    # so 2V/A estimates the wall. A solid cone or sphere gives a "wall" of a
    # good fraction of its size; a real shell gives a sliver of it.
    wall = 2.0 * volume / area
    if wall < 0.15 * min(bbox) or len(getattr(shape, "Shells", []) or []) > 1:
        return True, round(wall, 3)
    return False, None


def measure_document(document: Any, *, object_name: str = "", subject_names: Iterable[str] | None = None,
                     contract: DesignContract | None = None, printer: PrinterProfile | None = None,
                     living_design_verified: bool = False) -> FactReport:
    objects = _objects(document, subject_names)
    name = object_name or (getattr(objects[0], "Label", "") if objects else getattr(document, "Label", "document"))
    facts = FactReport(object_name=str(name))
    shapes = [s for s in (_shape_of(o) for o in objects) if s is not None]
    facts.mesh_only = bool(objects) and all(str(getattr(o, "TypeId", "")).startswith(_MESH_TYPES) for o in objects) and not shapes
    if shapes:
        xs: list[float] = []
        for shape in shapes:
            try:
                box = tight_box(shape)
                xs.append((box.XMin, box.YMin, box.ZMin, box.XMax, box.YMax, box.ZMax))
            except Exception:  # noqa: BLE001
                continue
        if xs:
            lo = [min(b[i] for b in xs) for i in range(3)]
            hi = [max(b[i + 3] for b in xs) for i in range(3)]
            facts.bbox_mm = (round(hi[0] - lo[0], 3), round(hi[1] - lo[1], 3), round(hi[2] - lo[2], 3))
        try:
            facts.volume_mm3 = round(sum(float(s.Volume) for s in shapes), 3)
            facts.area_mm2 = round(sum(float(s.Area) for s in shapes), 3)
            facts.solid_count = sum(len(getattr(s, "Solids", []) or []) for s in shapes)
            facts.valid_solid = facts.solid_count > 0 and all(bool(s.isValid()) for s in shapes if hasattr(s, "isValid"))
        except Exception as error:  # noqa: BLE001
            facts.notes.append(f"shape could not be fully read: {error}")
        for shape in shapes:
            facts.holes.extend(_holes(shape))
        if facts.bbox_mm and len(shapes) == 1:
            facts.hollow, facts.min_wall_mm = _hollow_and_wall(shapes[0], facts.bbox_mm)
    all_objects = list(getattr(document, "Objects", None) or [])
    types = [str(getattr(o, "TypeId", "")) for o in all_objects]
    facts.feature_tree = {
        "bodies": sum(t == "PartDesign::Body" for t in types),
        "sketches": sum(t.startswith("Sketcher::") for t in types),
        # A bare `PartDesign::Feature` is a fixed solid carried in PartDesign
        # (no sketch, no parameters): it is not a parametric feature.
        "features": sum(t.startswith("PartDesign::") and t not in ("PartDesign::Body", "PartDesign::Feature") for t in types),
        "named_parameters": 0,
    }
    names: list[str] = []
    for obj in all_objects:
        if str(getattr(obj, "TypeId", "")).startswith("Spreadsheet::"):
            try:
                if hasattr(obj, "getAliases"):            # test stand-ins
                    names.extend(str(a) for a in obj.getAliases() or [])
                else:                                      # FreeCAD 1.1: walk the used cells
                    for cell in obj.getUsedCells():
                        alias = obj.getAlias(cell)
                        if alias:
                            names.append(str(alias))
            except Exception:  # noqa: BLE001
                pass
        for prop in getattr(obj, "PropertiesList", []) or []:
            if str(prop).startswith("P_") or str(getattr(obj, "getGroupOfProperty", lambda p: "")(prop)) == "Design":
                names.append(str(prop)[2:] if str(prop).startswith("P_") else str(prop))
    facts.parameter_names = sorted(set(names))
    facts.feature_tree["named_parameters"] = len(facts.parameter_names)
    facts.living_design_verified = living_design_verified
    for obj in all_objects:
        try:
            state = set(str(s) for s in (getattr(obj, "State", None) or ()))
        except TypeError:
            state = set()
        if state & {"Invalid", "Error"}:
            facts.file_integrity_ok = False
            facts.notes.append(f"{getattr(obj, 'Label', '?')} has an error")
    return finish_report(facts, contract, printer)


def steep_overhang_note(shape: Any, max_deg: float = 45.0) -> str:
    """Planar downward-facing faces steeper than the printer allows (a note the
    print check reads). Only planar faces are judged; curved ones are skipped."""
    try:
        worst = 0.0
        for face in getattr(shape, "Faces", []) or []:
            if type(getattr(face, "Surface", None)).__name__ != "Plane":
                continue
            normal = face.normalAt(0, 0)
            if normal.z >= 0:
                continue
            angle = math.degrees(math.acos(max(-1.0, min(1.0, -normal.z))))
            worst = max(worst, angle)
        if worst > max_deg and worst < 89.9:
            return f"overhang of {worst:.0f} degrees found (over {max_deg:g})"
    except Exception:  # noqa: BLE001
        pass
    return ""
