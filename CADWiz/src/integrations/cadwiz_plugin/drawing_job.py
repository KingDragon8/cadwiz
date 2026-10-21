# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Makes a technical drawing sheet, run by FreeCAD's windowless program
(ORDER-2026-10-19-06):

    freecadcmd drawing_job.py <folder>/request.json

The request names a saved copy of the founder's model, where the SVG goes, the
title block, whether to draw a section, and any dimensions Claude adds (points in
model millimetres). Each view is a copy of the visible parts turned to face the
viewer, then projected with FreeCAD's TechDraw (visible and hidden edges); a
hollow part gets SECTION A-A, cut through its middle and seen from the front, in
place of the right-side view. The sheet itself is laid out by
`ai_freecad_core.drawings.sheet`. Writes result.json beside the request.

Runs in its own process because projection is OpenCASCADE work with no time
limit of its own: FreeCAD's window must never wait on it (ORDER-2026-10-19-03).
"""
from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

SRC = Path(__file__).resolve().parents[2]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

#: (toward the viewer, up) for each view; right follows from them (see `frame`).
VIEWS = {"front": ((0.0, -1.0, 0.0), (0.0, 0.0, 1.0)),
         "top": ((0.0, 0.0, 1.0), (0.0, 1.0, 0.0)),
         "right": ((1.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
         "iso": ((1.0, -1.0, 1.0), (0.0, 0.0, 1.0))}
SKIP_TYPES = ("Sketcher::", "Spreadsheet::", "App::", "PartDesign::Plane", "PartDesign::Line", "PartDesign::Point",
              "PartDesign::CoordinateSystem")


def frame(toward: tuple[float, float, float], up: tuple[float, float, float]):
    """Rows (right, up, toward) of the turn that puts the viewer on +Z."""
    import FreeCAD as App

    t = App.Vector(*toward).normalize()
    u = App.Vector(*up)
    u = (u - t * u.dot(t)).normalize()              # up, made square to the line of sight
    r = u.cross(t).normalize()
    return r, u, t


def turned(shape, rows):
    import FreeCAD as App

    r, u, t = rows
    matrix = App.Matrix(r.x, r.y, r.z, 0, u.x, u.y, u.z, 0, t.x, t.y, t.z, 0, 0, 0, 0, 1)
    copy = shape.copy()
    copy.transformShape(matrix)
    return copy


def to_view(point, rows) -> tuple[float, float]:
    import FreeCAD as App

    r, u, _t = rows
    p = App.Vector(*point)
    return (p.dot(r), p.dot(u))


def polylines(shape, deflection: float) -> list[list[tuple[float, float]]]:
    lines = []
    if shape is None or shape.isNull():
        return lines
    for edge in shape.Edges:
        try:
            points = edge.discretize(Deflection=deflection)
        except Exception:  # noqa: BLE001 - a degenerate edge draws nothing
            continue
        if len(points) >= 2:
            lines.append([(round(p.x, 3), round(p.y, 3)) for p in points])
    return lines


def project(shape, rows, deflection: float):
    import FreeCAD as App
    import TechDraw

    parts = TechDraw.projectEx(turned(shape, rows), App.Vector(0, 0, 1))
    # [visible sharp, visible smooth, visible seam, visible outline, visible iso, hidden x5]
    visible = polylines(parts[0], deflection) + polylines(parts[3], deflection)
    hidden = polylines(parts[5], deflection) + polylines(parts[8], deflection)
    return visible, hidden


def is_hollow(shape) -> bool:
    """A shell (a can, a cup, a helmet): its volume is a sliver of its surface
    times its size -- the same rule the fact layer uses."""
    box = shape.BoundBox
    least = min(box.XLength, box.YLength, box.ZLength)
    if shape.Volume <= 0 or shape.Area <= 0 or least <= 0:
        return False
    return 2.0 * shape.Volume / shape.Area < 0.15 * least


def section(shape, rows, deflection: float):
    """SECTION A-A: the half of the model away from the front viewer, its cut faces hatched."""
    import FreeCAD as App
    import Part

    box = shape.BoundBox
    cy = box.Center.y
    keep = Part.makeBox(box.XLength + 2, box.YMax - cy + 1, box.ZLength + 2, App.Vector(box.XMin - 1, cy, box.ZMin - 1))
    half = shape.common(keep)
    visible, hidden = project(half, rows, deflection)
    hatch = []
    for face in half.Faces:
        try:
            normal = face.normalAt(*face.Surface.parameter(face.CenterOfMass))
        except Exception:  # noqa: BLE001
            continue
        if abs(abs(normal.y) - 1.0) > 1e-6 or abs(face.CenterOfMass.y - cy) > 1e-4:
            continue
        loops = []
        for wire in face.Wires:
            points = wire.discretize(Deflection=deflection)
            loops.append([to_view((p.x, p.y, p.z), rows) for p in points])
        hatch.append(loops)
    return visible, hidden, hatch


def model_shape(document):
    import Part

    solids = []
    for obj in document.Objects:
        type_id = str(getattr(obj, "TypeId", ""))
        if type_id.startswith(SKIP_TYPES) or not bool(getattr(obj, "Visibility", True)):
            continue
        users = [u for u in getattr(obj, "InList", []) if not str(getattr(u, "TypeId", "")).startswith(("App::Origin", "Spreadsheet::"))]
        if users:
            continue                                   # made into something else: the something else is drawn
        shape = getattr(obj, "Shape", None)
        if shape is None or shape.isNull():
            continue
        solids.extend(shape.Solids)
    return Part.makeCompound(solids) if solids else None


def main(request_path: str) -> None:
    request_file = Path(request_path)
    result_file = request_file.with_name("result.json")
    try:
        import FreeCAD as App

        from ai_freecad_core.drawings.sheet import Dimension, View, compose

        request = json.loads(request_file.read_text(encoding="utf-8"))
        document = App.openDocument(request["source"])
        shape = model_shape(document)
        if shape is None:
            result_file.write_text(json.dumps({"ok": False, "say": "There is no solid shape to draw yet."}), encoding="utf-8")
            return
        deflection = max(0.02, shape.BoundBox.DiagonalLength / 800.0)
        rows = {name: frame(*spec) for name, spec in VIEWS.items()}
        views = {}
        for name in ("front", "top", "iso"):
            visible, hidden = project(shape, rows[name], deflection)
            views[name] = View(name, visible, hidden if name != "iso" else [])
        wanted = str(request.get("section") or "auto")
        hollow = is_hollow(shape)
        if wanted == "on" or (wanted == "auto" and hollow):
            visible, hidden, hatch = section(shape, rows["front"], deflection)
            # a section shows what the cut reveals: no hidden lines behind it
            views["section"] = View("section", visible, [], hatch, label="SECTION A-A (CUT THROUGH THE MIDDLE)")
        else:
            visible, hidden = project(shape, rows["right"], deflection)
            views["right"] = View("right", visible, hidden, label="RIGHT")
        views["front"].label, views["top"].label = "FRONT", "TOP"
        dims = []
        for spec in request.get("dimensions") or []:
            view = str(spec.get("view") or "front")
            key = "front" if view == "section" else view
            if key not in rows:
                continue
            dims.append(Dimension(view, to_view(spec["start"], rows[key]), to_view(spec["end"], rows[key]),
                                  str(spec.get("label") or ""), float(spec.get("offset") or 8.0)))
        svg, scale = compose(views, title=str(request.get("title") or document.Label), version=int(request.get("version") or 0),
                             date=str(request.get("date") or ""), dimensions=dims, note=str(request.get("note") or ""))
        Path(request["out_svg"]).write_text(svg, encoding="utf-8")
        box = shape.BoundBox
        result_file.write_text(json.dumps({"ok": True, "svg": request["out_svg"], "scale": scale, "hollow": hollow,
                                           "section": "section" in views,
                                           "size_mm": [round(box.XLength, 2), round(box.YLength, 2), round(box.ZLength, 2)]}),
                               encoding="utf-8")
    except Exception as error:  # noqa: BLE001 - reported to the window, which says it plainly
        result_file.write_text(json.dumps({"ok": False, "say": "The drawing could not be made from this model.",
                                           "detail": f"{type(error).__name__}: {error}", "trace": traceback.format_exc()[-1500:]}),
                               encoding="utf-8")


main([a for a in sys.argv if a.endswith("request.json")][-1])
