# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Native parametric builders for the five replacement-part benchmarks."""

from __future__ import annotations

import json
from importlib import import_module
from typing import Any


def _app() -> Any:
    return import_module("FreeCAD")


def _part() -> Any:
    return import_module("Part")


def _state(self: object) -> None:
    return None


def _restore(self: object, state: object) -> None:
    return None


def _rounded_cylinder(radius: float, height: float, fillet: float) -> Any:
    app, part = _app(), _part()
    inner = radius - fillet
    offsets = (0.5, 1.0, 1.5, 2.0)
    rounded = tuple(inner + (fillet**2 - (fillet - offset) ** 2) ** 0.5 for offset in offsets)
    points = [app.Vector(0, 0, 0), app.Vector(inner, 0, 0)]
    points.extend(
        app.Vector(value, 0, offset) for value, offset in zip(rounded, offsets, strict=True)
    )
    points.append(app.Vector(radius, 0, height - fillet))
    points.extend(
        app.Vector(value, 0, height - offset)
        for value, offset in zip(reversed(rounded[:-1]), reversed(offsets[:-1]), strict=True)
    )
    points.extend((app.Vector(inner, 0, height), app.Vector(0, 0, height)))
    wire = part.makePolygon((*points, points[0]))
    return part.Face(wire).revolve(app.Vector(0, 0, 0), app.Vector(0, 0, 1), 360)


def _knob(d: dict[str, float]) -> Any:
    app, part = _app(), _part()
    body = _rounded_cylinder(d["outer_diameter"] / 2, d["height"], d["fillet_radius"])
    radius = d["socket_diameter"] / 2
    flat_x = -radius + d["socket_flat"]
    socket = part.makeCylinder(radius, d["insertion_depth"] + 0.5, app.Vector(0, 0, -0.5))
    keep = part.makeBox(
        2 * radius, 2 * radius, d["insertion_depth"] + 1, app.Vector(-radius, -radius, -0.5)
    )
    keep = keep.common(
        part.makeBox(
            flat_x + radius,
            2 * radius,
            d["insertion_depth"] + 1,
            app.Vector(-radius, -radius, -0.5),
        )
    )
    socket = socket.common(keep)
    groove = part.makeBox(
        d["outer_diameter"] / 2,
        d["indicator_width"],
        d["indicator_depth"] + 0.5,
        app.Vector(0, -d["indicator_width"] / 2, d["height"] - d["indicator_depth"]),
    )
    return body.cut(socket.fuse(groove)).removeSplitter()


def _angle_bracket(d: dict[str, float]) -> Any:
    app, part = _app(), _part()
    length, width, thick = d["horizontal_length"], d["width"], d["thickness"]
    horizontal = part.makeBox(length, width, thick)
    vertical_edges = [edge for edge in horizontal.Edges if edge.BoundBox.ZLength > thick - 0.1]
    horizontal = horizontal.makeFillet(d["fillet_radius"], vertical_edges)
    vertical = part.makeBox(thick, width, d["vertical_height"])
    shape = horizontal.fuse(vertical)
    hole_r = d["hole_diameter"] / 2
    offset = d["hole_offset"]
    tools = part.makeCylinder(hole_r, thick + 2, app.Vector(offset, width / 2, -1)).fuse(
        part.makeCylinder(hole_r, thick + 2, app.Vector(length - offset, width / 2, -1))
    )
    for z in (offset, d["vertical_height"] - offset):
        tool = part.makeCylinder(
            hole_r, thick + 2, app.Vector(-1, width / 2, z), app.Vector(1, 0, 0)
        )
        tools = tools.fuse(tool)
    for y in (width / 4, 3 * width / 4):
        points = (
            app.Vector(0, y - d["gusset_thickness"] / 2, thick),
            app.Vector(18, y - d["gusset_thickness"] / 2, thick),
            app.Vector(0, y - d["gusset_thickness"] / 2, 23),
        )
        gusset = part.Face(part.makePolygon((*points, points[0]))).extrude(
            app.Vector(0, d["gusset_thickness"], 0)
        )
        shape = shape.fuse(gusset)
    return shape.cut(tools).removeSplitter()


def _hose_adapter(d: dict[str, float]) -> Any:
    app, part = _app(), _part()
    large_r = d["large_od"] / 2
    small_outer = d["small_id"] / 2 + d["min_wall"]
    first = 15.0
    transition = d["transition_length"]
    last = d["length"] - first - transition
    outer = part.makeCylinder(large_r, first)
    outer = outer.fuse(part.makeCone(large_r, small_outer, transition, app.Vector(0, 0, first)))
    outer = outer.fuse(part.makeCylinder(small_outer, last, app.Vector(0, 0, first + transition)))
    outer = outer.fuse(part.makeCylinder(large_r + d["barb_rise"], 2.0, app.Vector(0, 0, 3.0)))
    large_inner = large_r - d["min_wall"]
    small_inner = d["small_id"] / 2
    passage = part.makeCylinder(large_inner, first + 0.1, app.Vector(0, 0, -0.05))
    passage = passage.fuse(
        part.makeCone(large_inner, small_inner, transition, app.Vector(0, 0, first))
    )
    passage = passage.fuse(
        part.makeCylinder(small_inner, last + 0.1, app.Vector(0, 0, first + transition))
    )
    return outer.cut(passage).removeSplitter()


def _clip(d: dict[str, float]) -> Any:
    app, part = _app(), _part()
    inner = d["clip_id"] / 2
    outer = inner + d["wall"]
    height = d["tab_thickness"]
    ring = part.makeCylinder(outer, height).cut(part.makeCylinder(inner, height))
    opening = part.makeBox(
        outer + 1, d["opening"], height + 2, app.Vector(0, -d["opening"] / 2, -1)
    )
    ring = ring.cut(opening)
    tab_x = -outer - d["tab_length"] + 0.5
    tab = part.makeBox(
        d["tab_length"], d["tab_width"], height, app.Vector(tab_x, -d["tab_width"] / 2, 0)
    )
    root_x = -outer - 2.0
    root = part.makeCylinder(
        d["root_fillet"],
        height,
        app.Vector(root_x, -d["tab_width"] / 2 + d["root_fillet"], 0),
    )
    root = root.fuse(
        part.makeCylinder(
            d["root_fillet"],
            height,
            app.Vector(root_x, d["tab_width"] / 2 - d["root_fillet"], 0),
        )
    )
    center_x = tab_x + d["tab_length"] / 2
    hole = part.makeCylinder(d["hole_diameter"] / 2, height + 2, app.Vector(center_x, 0, -1))
    return ring.fuse(tab).fuse(root).cut(hole).removeSplitter()


def _foot(d: dict[str, float]) -> Any:
    app, part = _app(), _part()
    foot = part.makeCylinder(d["foot_diameter"] / 2, d["foot_height"])
    boss = part.makeCylinder(d["boss_od"] / 2, d["boss_height"], app.Vector(0, 0, d["foot_height"]))
    top_edges = [
        edge
        for edge in boss.Edges
        if abs(edge.BoundBox.ZMax - (d["foot_height"] + d["boss_height"])) < 0.1
    ]
    boss = boss.makeFillet(d["fillet_radius"], top_edges)
    shape = foot.fuse(boss)
    bore = part.makeCylinder(
        d["tap_bore"] / 2,
        d["thread_depth"],
        app.Vector(0, 0, d["foot_height"] + d["boss_height"] - d["thread_depth"]),
    )
    recess = part.makeCylinder(
        d["recess_diameter"] / 2, d["recess_depth"] + 0.1, app.Vector(0, 0, -0.05)
    )
    return shape.cut(bore.fuse(recess)).removeSplitter()


BUILDERS = {
    "CADW-REPLACE-001": _knob,
    "CADW-REPLACE-002": _angle_bracket,
    "CADW-REPLACE-003": _hose_adapter,
    "CADW-REPLACE-004": _clip,
    "CADW-REPLACE-005": _foot,
}


class _ReplacementProxy:
    def __init__(self, obj: Any, identifier: str, names: tuple[str, ...]) -> None:
        obj.Proxy = self
        obj.addProperty("App::PropertyString", "BenchmarkId", "Benchmark")
        obj.BenchmarkId = identifier
        for name in names:
            obj.addProperty("App::PropertyLength", name, "Parameters")

    def execute(self, obj: Any) -> None:
        dimensions = {name: float(getattr(obj, name)) for name in obj.ParameterNames.split(",")}
        obj.Shape = BUILDERS[obj.BenchmarkId](dimensions)

    __getstate__ = _state
    __setstate__ = _restore


def build_parametric_replacement_part(
    document: Any, arguments: dict[str, object]
) -> tuple[str, ...]:
    identifier = str(arguments["benchmark_id"])
    if identifier not in BUILDERS:
        raise ValueError(f"Unknown replacement benchmark: {identifier}")
    spec_data = json.loads(str(arguments["spec_json"]))
    dimensions = {
        name: float(value) for name, value in json.loads(str(arguments["dimensions_json"])).items()
    }
    sheet = document.addObject("Spreadsheet::Sheet", "ReplacementParameters")
    feature = document.addObject("PartDesign::FeaturePython", "ReplacementPart")
    _ReplacementProxy(feature, identifier, tuple(dimensions))
    feature.addProperty("App::PropertyString", "ParameterNames", "Benchmark")
    feature.addProperty("App::PropertyString", "ManifestJson", "Benchmark")
    feature.addProperty("App::PropertyString", "OriginalRequest", "Benchmark")
    feature.addProperty("App::PropertyString", "ExecutionPath", "Benchmark")
    feature.addProperty("App::PropertyString", "ThreadRepresentation", "Benchmark")
    feature.ParameterNames = ",".join(dimensions)
    feature.ManifestJson = json.dumps(spec_data, sort_keys=True)
    feature.OriginalRequest = str(arguments["request"])
    feature.ExecutionPath = (
        "StructuredCommand -> SafeExecutionService -> FreeCADStructuredCommandAdapter"
    )
    feature.ThreadRepresentation = (
        "metadata plus 6.8 mm tap-drill bore"
        if identifier == "CADW-REPLACE-005"
        else "not applicable"
    )
    for index, (name, value) in enumerate(dimensions.items(), 1):
        cell = f"B{index}"
        sheet.set(f"A{index}", name)
        sheet.set(cell, f"{value:g} mm")
        sheet.setAlias(cell, name)
        feature.setExpression(name, f"ReplacementParameters.{name}")
    document.recompute()
    if feature.Shape.isNull() or not feature.Shape.isValid() or len(feature.Shape.Solids) != 1:
        raise RuntimeError(f"{identifier} failed native validity or one-solid acceptance")
    if getattr(sheet, "ViewObject", None) is not None:
        sheet.ViewObject.Visibility = False
    return tuple(f"freecad:{document.Name}:{item.Name}" for item in document.Objects)


def inspect_replacement_part(document: Any) -> dict[str, Any]:
    feature = document.getObject("ReplacementPart")
    sheet = document.getObject("ReplacementParameters")
    manifest = json.loads(feature.ManifestJson)
    dimensions = {name: float(getattr(feature, name)) for name in feature.ParameterNames.split(",")}
    expressions = dict(feature.ExpressionEngine)
    return {
        **dimensions,
        "valid": feature.Shape.isValid() and not feature.Shape.isNull(),
        "one_solid": len(feature.Shape.Solids) == 1,
        "features_present": _feature_probes(feature.BenchmarkId, feature.Shape, dimensions),
        "parametric": sheet is not None and all(name in expressions for name in dimensions),
        "provenance_complete": all(
            key in manifest
            for key in (
                "input_evidence",
                "external_catalog_evidence",
                "benchmark_assumptions",
                "derived_values",
                "reconciliation_decisions",
            )
        ),
        "assumptions_complete": bool(manifest["benchmark_assumptions"])
        and manifest["unresolved_ordinary_inputs"] == [],
        "protected_execution": "FreeCADStructuredCommandAdapter" in feature.ExecutionPath,
        "volume": feature.Shape.Volume,
        "solid_count": len(feature.Shape.Solids),
        "thread_representation": feature.ThreadRepresentation,
        "geometry_bounds": {
            "x": feature.Shape.BoundBox.XLength,
            "y": feature.Shape.BoundBox.YLength,
            "z": feature.Shape.BoundBox.ZLength,
        },
        "cylindrical_face_radii": sorted(
            round(float(face.Surface.Radius), 6)
            for face in feature.Shape.Faces
            if hasattr(getattr(face, "Surface", None), "Radius")
            and "Cylinder" in str(type(face.Surface))
        ),
    }


def _feature_probes(identifier: str, shape: Any, d: dict[str, float]) -> bool:
    app, part = _app(), _part()
    if identifier == "CADW-REPLACE-001":
        socket_probe = part.makeCylinder(
            min(d["socket_diameter"] / 2 - 0.2, d["socket_flat"] - d["socket_diameter"] / 2 - 0.2),
            d["insertion_depth"] - 0.1,
            app.Vector(0, 0, 0),
        )
        groove_probe = part.makeBox(
            d["outer_diameter"] / 2 - 1.0,
            d["indicator_width"] - 0.2,
            d["indicator_depth"] - 0.2,
            app.Vector(
                1.0,
                -(d["indicator_width"] - 0.2) / 2,
                d["height"] - d["indicator_depth"] + 0.1,
            ),
        )
        return (
            shape.common(socket_probe).Volume < 1e-5
            and shape.common(groove_probe).Volume < 1e-5
            and shape.BoundBox.ZLength <= d["height"] + 0.1
            and abs(shape.BoundBox.XLength - d["outer_diameter"]) < 0.1
        )
    if identifier == "CADW-REPLACE-002":
        hole_r = d["hole_diameter"] / 2 - 0.1
        holes = part.makeCylinder(
            hole_r,
            d["thickness"] + 2,
            app.Vector(d["hole_offset"], d["width"] / 2, -1),
        ).fuse(
            part.makeCylinder(
                hole_r,
                d["thickness"] + 2,
                app.Vector(d["horizontal_length"] - d["hole_offset"], d["width"] / 2, -1),
            )
        )
        for z in (d["hole_offset"], d["vertical_height"] - d["hole_offset"]):
            holes = holes.fuse(
                part.makeCylinder(
                    hole_r,
                    d["thickness"] + 2,
                    app.Vector(-1, d["width"] / 2, z),
                    app.Vector(1, 0, 0),
                )
            )
        fillets = [
            float(face.Surface.Radius)
            for face in shape.Faces
            if hasattr(getattr(face, "Surface", None), "Radius")
            and "Cylinder" in str(type(face.Surface))
            and abs(float(face.Surface.Radius) - d["fillet_radius"]) < 0.1
        ]
        return (
            shape.BoundBox.XLength >= d["horizontal_length"] - 0.1
            and shape.BoundBox.ZLength >= d["vertical_height"] - 0.1
            and shape.common(holes).Volume < 1e-5
            and len(fillets) >= 2
        )
    if identifier == "CADW-REPLACE-003":
        probe = part.makeCylinder(d["small_id"] / 2 - 0.1, d["length"])
        return shape.common(probe).Volume < 1e-5 and abs(shape.BoundBox.ZLength - d["length"]) < 0.1
    if identifier == "CADW-REPLACE-004":
        probe = part.makeCylinder(d["rod_diameter"] / 2 - 0.2, d["tab_thickness"])
        outer = d["clip_id"] / 2 + d["wall"]
        tab_x = -outer - d["tab_length"] + 0.5
        hole = part.makeCylinder(
            d["hole_diameter"] / 2 - 0.1,
            d["tab_thickness"] + 2,
            app.Vector(tab_x + d["tab_length"] / 2, 0, -1),
        )
        return (
            shape.common(probe).Volume < 1e-5
            and shape.common(hole).Volume < 1e-5
            and len(shape.Solids) == 1
        )
    bore_probe = part.makeCylinder(
        d["tap_bore"] / 2 - 0.1,
        d["thread_depth"] - 0.1,
        app.Vector(0, 0, d["foot_height"] + d["boss_height"] - d["thread_depth"]),
    )
    recess_probe = part.makeCylinder(
        d["recess_diameter"] / 2 - 0.1,
        d["recess_depth"] - 0.1,
        app.Vector(0, 0, 0),
    )
    return (
        shape.common(bore_probe).Volume < 1e-5
        and shape.common(recess_probe).Volume < 1e-5
        and abs(shape.BoundBox.ZLength - (d["foot_height"] + d["boss_height"])) < 0.1
    )
