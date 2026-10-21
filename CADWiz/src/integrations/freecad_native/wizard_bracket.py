# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Native parametric construction for the Wizard flanged-tube benchmark.

The builder lives in the product integration rather than in a test helper so the
benchmark exercises the same protected StructuredCommand adapter as a user job.
"""

from __future__ import annotations

import json
from importlib import import_module
from typing import Any

PARAMETERS = (
    ("A1", "Base length", "B1", "80 mm", "base_length"),
    ("A2", "Base width", "B2", "50 mm", "base_width"),
    ("A3", "Base thickness", "B3", "6 mm", "base_thickness"),
    ("A4", "Tube outside diameter", "B4", "30 mm", "tube_od"),
    ("A5", "Tube inside diameter", "B5", "24 mm", "tube_id"),
    ("A6", "Tube height above base", "B6", "45 mm", "tube_height"),
    ("A7", "Mounting-hole diameter", "B7", "6 mm", "hole_diameter"),
    ("A8", "Mounting-hole X offset", "B8", "28 mm", "hole_offset_x"),
    ("A9", "Gusset thickness", "B9", "5 mm", "gusset_thickness"),
    ("A10", "Gusset height", "B10", "24 mm", "gusset_height"),
    ("A11", "Gusset reach", "B11", "16 mm", "gusset_reach"),
    ("A12", "Corner fillet radius", "B12", "4 mm", "fillet_radius"),
    ("A13", "Tube-top chamfer", "B13", "1.5 mm", "chamfer_size"),
)


def _part() -> Any:
    return import_module("Part")


def _app() -> Any:
    return import_module("FreeCAD")


def _length(obj: Any, name: str, group: str = "Dimensions") -> None:
    obj.addProperty("App::PropertyLength", name, group)


def _proxy_state(self: object) -> None:
    return None


def _restore_proxy(self: object, state: object) -> None:
    return None


class _BaseProxy:
    def __init__(self, obj: Any) -> None:
        obj.Proxy = self
        for name in ("Length", "Width", "Thickness", "FilletRadius"):
            _length(obj, name)
        obj.addProperty("App::PropertyInteger", "AppliedFilletCount", "Verification")
        obj.AppliedFilletCount = 4

    def execute(self, obj: Any) -> None:
        app, part = _app(), _part()
        length = float(obj.Length)
        width = float(obj.Width)
        thickness = float(obj.Thickness)
        radius = float(obj.FilletRadius)
        shape = part.makeBox(
            length,
            width,
            thickness,
            app.Vector(-length / 2.0, -width / 2.0, 0.0),
        )
        vertical = [
            edge
            for edge in shape.Edges
            if abs(edge.Vertexes[-1].Point.z - edge.Vertexes[0].Point.z) > thickness - 1e-6
        ]
        if len(vertical) != 4:
            raise RuntimeError(f"Expected four vertical base edges, found {len(vertical)}")
        obj.Shape = shape.makeFillet(radius, vertical)

    __getstate__ = _proxy_state
    __setstate__ = _restore_proxy


class _TubeProxy:
    def __init__(self, obj: Any) -> None:
        obj.Proxy = self
        for name in ("OutsideDiameter", "InsideDiameter", "Height", "BaseThickness", "ChamferSize"):
            _length(obj, name)
        obj.addProperty("App::PropertyAngle", "ChamferAngle", "Verification")
        obj.ChamferAngle = 45.0

    def execute(self, obj: Any) -> None:
        app, part = _app(), _part()
        outer = float(obj.OutsideDiameter) / 2.0
        inner = float(obj.InsideDiameter) / 2.0
        base_top = float(obj.BaseThickness)
        top = base_top + float(obj.Height)
        chamfer = float(obj.ChamferSize)
        if not 0 < inner < outer or not 0 < chamfer < outer - inner:
            raise ValueError("Tube diameters and chamfer do not define a valid hollow profile")
        points = (
            app.Vector(inner, 0.0, base_top - 0.5),
            app.Vector(outer, 0.0, base_top - 0.5),
            app.Vector(outer, 0.0, top - chamfer),
            app.Vector(outer - chamfer, 0.0, top),
            app.Vector(inner, 0.0, top),
        )
        wire = part.makePolygon((*points, points[0]))
        obj.Shape = part.Face(wire).revolve(
            app.Vector(0.0, 0.0, 0.0), app.Vector(0.0, 0.0, 1.0), 360.0
        )

    __getstate__ = _proxy_state
    __setstate__ = _restore_proxy


class _BaseTubeProxy:
    def __init__(self, obj: Any) -> None:
        obj.Proxy = self
        obj.addProperty("App::PropertyLink", "Base", "Construction")
        obj.addProperty("App::PropertyLink", "Tube", "Construction")

    def execute(self, obj: Any) -> None:
        obj.Shape = obj.Base.Shape.fuse(obj.Tube.Shape).removeSplitter()

    __getstate__ = _proxy_state
    __setstate__ = _restore_proxy


class _HoleCutProxy:
    def __init__(self, obj: Any) -> None:
        obj.Proxy = self
        obj.addProperty("App::PropertyLink", "Source", "Construction")
        for name in ("HoleDiameter", "HoleOffsetX", "BaseThickness"):
            _length(obj, name)
        obj.addProperty("App::PropertyInteger", "HoleCount", "Verification")
        obj.HoleCount = 2

    def execute(self, obj: Any) -> None:
        app, part = _app(), _part()
        radius = float(obj.HoleDiameter) / 2.0
        offset = float(obj.HoleOffsetX)
        height = float(obj.BaseThickness) + 2.0
        tool = part.makeCylinder(radius, height, app.Vector(-offset, 0.0, -1.0)).fuse(
            part.makeCylinder(radius, height, app.Vector(offset, 0.0, -1.0))
        )
        obj.Shape = obj.Source.Shape.cut(tool).removeSplitter()

    __getstate__ = _proxy_state
    __setstate__ = _restore_proxy


class _GussetProxy:
    def __init__(self, obj: Any) -> None:
        obj.Proxy = self
        for name in (
            "TubeOutsideDiameter",
            "BaseThickness",
            "Thickness",
            "Height",
            "Reach",
        ):
            _length(obj, name)

    def execute(self, obj: Any) -> None:
        app, part = _app(), _part()
        thickness = float(obj.Thickness)
        near = float(obj.TubeOutsideDiameter) / 2.0 - 1.0
        far = float(obj.TubeOutsideDiameter) / 2.0 + float(obj.Reach)
        base_top = float(obj.BaseThickness)
        top = base_top + float(obj.Height)
        points = (
            app.Vector(near, -thickness / 2.0, base_top - 0.5),
            app.Vector(far, -thickness / 2.0, base_top - 0.5),
            app.Vector(near, -thickness / 2.0, top),
        )
        face = part.Face(part.makePolygon((*points, points[0])))
        obj.Shape = face.extrude(app.Vector(0.0, thickness, 0.0))

    __getstate__ = _proxy_state
    __setstate__ = _restore_proxy


class _MirrorProxy:
    def __init__(self, obj: Any) -> None:
        obj.Proxy = self
        obj.addProperty("App::PropertyLink", "Original", "Construction")
        obj.addProperty("App::PropertyString", "MirrorPlane", "Construction")
        obj.MirrorPlane = "YZ (X=0)"

    def execute(self, obj: Any) -> None:
        app = _app()
        mirrored = obj.Original.Shape.copy()
        result = mirrored.mirror(app.Vector(0.0, 0.0, 0.0), app.Vector(1.0, 0.0, 0.0))
        obj.Shape = result if result is not None else mirrored

    __getstate__ = _proxy_state
    __setstate__ = _restore_proxy


class _FinalProxy:
    def __init__(self, obj: Any) -> None:
        obj.Proxy = self
        obj.addProperty("App::PropertyLink", "Source", "Construction")
        obj.addProperty("App::PropertyLink", "GussetSeed", "Construction")
        obj.addProperty("App::PropertyLink", "GussetMirror", "Construction")
        for name in ("HoleDiameter", "HoleOffsetX", "BaseThickness"):
            _length(obj, name)

    def execute(self, obj: Any) -> None:
        app, part = _app(), _part()
        shape = obj.Source.Shape.fuse(obj.GussetSeed.Shape)
        shape = shape.fuse(obj.GussetMirror.Shape)
        radius = float(obj.HoleDiameter) / 2.0
        offset = float(obj.HoleOffsetX)
        height = float(obj.BaseThickness) + 2.0
        tool = part.makeCylinder(radius, height, app.Vector(-offset, 0.0, -1.0)).fuse(
            part.makeCylinder(radius, height, app.Vector(offset, 0.0, -1.0))
        )
        obj.Shape = shape.cut(tool).removeSplitter()

    __getstate__ = _proxy_state
    __setstate__ = _restore_proxy


def _bind(obj: Any, property_name: str, alias: str) -> None:
    obj.setExpression(property_name, f"WizardParameters.{alias}")


def _argument(arguments: dict[str, object], name: str) -> float:
    value = arguments[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ValueError(f"{name} must be a positive number")
    return float(value)


def build_parametric_flanged_tube_bracket(
    document: Any, arguments: dict[str, object]
) -> tuple[str, ...]:
    """Create the editable benchmark feature tree in an existing document."""
    required = {
        "base_length",
        "base_width",
        "base_thickness",
        "tube_od",
        "tube_id",
        "tube_height",
        "hole_diameter",
        "hole_offset_x",
        "gusset_thickness",
        "gusset_height",
        "gusset_reach",
        "fillet_radius",
        "chamfer_size",
    }
    missing = sorted(required - arguments.keys())
    if missing:
        raise ValueError("Missing bracket parameters: " + ", ".join(missing))
    values = {name: _argument(arguments, name) for name in required}
    if document.getObject("WizardBracket") is not None:
        raise ValueError("Wizard benchmark bracket already exists in this document")

    sheet = document.addObject("Spreadsheet::Sheet", "WizardParameters")
    sheet.Label = "Wizard benchmark parameters"
    for label_cell, label, value_cell, default, alias in PARAMETERS:
        sheet.set(label_cell, label)
        number = values[alias]
        unit_value = f"{number:g} mm"
        sheet.set(value_cell, unit_value if default.endswith("mm") else str(number))
        sheet.setAlias(value_cell, alias)

    base = document.addObject("PartDesign::FeaturePython", "BaseFillet")
    base.Label = "Centered base with four vertical corner fillets"
    _BaseProxy(base)
    for prop, alias in (
        ("Length", "base_length"),
        ("Width", "base_width"),
        ("Thickness", "base_thickness"),
        ("FilletRadius", "fillet_radius"),
    ):
        _bind(base, prop, alias)

    tube = document.addObject("PartDesign::FeaturePython", "TubeForm")
    tube.Label = "Hollow vertical tube with external top chamfer"
    _TubeProxy(tube)
    for prop, alias in (
        ("OutsideDiameter", "tube_od"),
        ("InsideDiameter", "tube_id"),
        ("Height", "tube_height"),
        ("BaseThickness", "base_thickness"),
        ("ChamferSize", "chamfer_size"),
    ):
        _bind(tube, prop, alias)

    union = document.addObject("PartDesign::FeaturePython", "BaseTubeUnion")
    union.Label = "Base and tube union"
    _BaseTubeProxy(union)
    union.Base = base
    union.Tube = tube

    holes = document.addObject("PartDesign::FeaturePython", "MountingHoles")
    holes.Label = "Two through mounting holes"
    _HoleCutProxy(holes)
    holes.Source = union
    for prop, alias in (
        ("HoleDiameter", "hole_diameter"),
        ("HoleOffsetX", "hole_offset_x"),
        ("BaseThickness", "base_thickness"),
    ):
        _bind(holes, prop, alias)

    seed = document.addObject("PartDesign::FeaturePython", "GussetSeed")
    seed.Label = "Seed reinforcement gusset"
    _GussetProxy(seed)
    for prop, alias in (
        ("TubeOutsideDiameter", "tube_od"),
        ("BaseThickness", "base_thickness"),
        ("Thickness", "gusset_thickness"),
        ("Height", "gusset_height"),
        ("Reach", "gusset_reach"),
    ):
        _bind(seed, prop, alias)

    mirror = document.addObject("PartDesign::FeaturePython", "GussetMirror")
    mirror.Label = "Opposed mirrored gusset"
    _MirrorProxy(mirror)
    mirror.Original = seed

    final = document.addObject("PartDesign::FeaturePython", "WizardBracket")
    final.Label = "CADWiz Wizard flanged tube bracket"
    _FinalProxy(final)
    final.Source = holes
    final.GussetSeed = seed
    final.GussetMirror = mirror
    for prop, alias in (
        ("HoleDiameter", "hole_diameter"),
        ("HoleOffsetX", "hole_offset_x"),
        ("BaseThickness", "base_thickness"),
    ):
        _bind(final, prop, alias)
    for name, value in (
        ("BenchmarkId", arguments.get("benchmark_id", "")),
        ("AssistanceMode", arguments.get("assistance_mode", "")),
        ("OriginalRequest", arguments.get("user_request", "")),
        ("AssumptionsJson", arguments.get("assumptions_json", "[]")),
        (
            "ExecutionPath",
            "StructuredCommand -> SafeExecutionService -> FreeCADStructuredCommandAdapter",
        ),
        ("GoverningStandard", "docs/CADW-DEMO-STANDARD.md"),
    ):
        final.addProperty("App::PropertyString", name, "Benchmark Evidence")
        setattr(final, name, str(value))

    document.recompute()
    states = [state for item in document.Objects for state in item.State if state != "Up-to-date"]
    if states or final.Shape.isNull() or not final.Shape.isValid() or len(final.Shape.Solids) != 1:
        raise RuntimeError(
            "Wizard bracket failed recompute, validity, or single-solid verification: "
            + json.dumps(states)
        )
    for item in (sheet, base, tube, union, holes, seed, mirror):
        if getattr(item, "ViewObject", None) is not None:
            item.ViewObject.Visibility = False
    if getattr(final, "ViewObject", None) is not None:
        final.ViewObject.ShapeColor = (0.16, 0.48, 0.86)
    return tuple(f"freecad:{document.Name}:{item.Name}" for item in document.Objects)


def inspect_parametric_flanged_tube_bracket(document: Any) -> dict[str, Any]:
    """Measure the saved model from native geometry and editable properties."""
    app, part = _app(), _part()
    final = document.getObject("WizardBracket")
    base = document.getObject("BaseFillet")
    tube = document.getObject("TubeForm")
    holes = document.getObject("MountingHoles")
    seed = document.getObject("GussetSeed")
    mirror = document.getObject("GussetMirror")
    sheet = document.getObject("WizardParameters")
    required = (final, base, tube, holes, seed, mirror, sheet)
    if any(item is None for item in required):
        raise LookupError("The reopened document is missing Wizard benchmark features")

    bore_probe = part.makeCylinder(
        float(tube.InsideDiameter) / 2.0 - 0.05,
        float(tube.Height),
        app.Vector(0.0, 0.0, float(base.Thickness)),
    )
    hole_radius = float(holes.HoleDiameter) / 2.0 - 0.05
    hole_probe = part.makeCylinder(
        hole_radius,
        float(base.Thickness) + 2.0,
        app.Vector(-float(holes.HoleOffsetX), 0.0, -1.0),
    ).fuse(
        part.makeCylinder(
            hole_radius,
            float(base.Thickness) + 2.0,
            app.Vector(float(holes.HoleOffsetX), 0.0, -1.0),
        )
    )
    circular_radii = sorted(
        round(float(edge.Curve.Radius), 6)
        for edge in base.Shape.Edges
        if hasattr(getattr(edge, "Curve", None), "Radius")
    )
    cylindrical_fillet_radii = sorted(
        round(float(face.Surface.Radius), 6)
        for face in base.Shape.Faces
        if hasattr(getattr(face, "Surface", None), "Radius")
        and "Cylinder" in str(type(face.Surface))
    )
    conical_faces = [
        face
        for face in tube.Shape.Faces
        if "Cone" in type(getattr(face, "Surface", None)).__name__
        or "Cone" in str(type(getattr(face, "Surface", None)))
    ]
    expression_bindings = (
        (base, "Length"),
        (base, "FilletRadius"),
        (tube, "OutsideDiameter"),
        (tube, "ChamferSize"),
        (holes, "HoleOffsetX"),
        (seed, "Reach"),
    )
    expression_maps = [dict(getattr(obj, "ExpressionEngine", ())) for obj, _ in expression_bindings]
    expressions = [
        mapping.get(prop)
        for mapping, (_, prop) in zip(expression_maps, expression_bindings, strict=True)
    ]
    seed_box, mirror_box = seed.Shape.BoundBox, mirror.Shape.BoundBox
    assumption_data = json.loads(final.AssumptionsJson)
    expected_construction = {
        "BaseFillet",
        "TubeForm",
        "BaseTubeUnion",
        "MountingHoles",
        "GussetSeed",
        "GussetMirror",
        "WizardBracket",
    }
    stray_solid_count = sum(
        len(item.Shape.Solids)
        for item in document.Objects
        if item.Name not in expected_construction
        and hasattr(item, "Shape")
        and not item.Shape.isNull()
    )
    return {
        "final_valid": bool(final.Shape.isValid() and not final.Shape.isNull()),
        "final_solid_count": len(final.Shape.Solids),
        "stray_solid_count": stray_solid_count,
        "base_length": float(base.Shape.BoundBox.XLength),
        "base_width": float(base.Shape.BoundBox.YLength),
        "base_thickness": float(base.Shape.BoundBox.ZLength),
        "tube_od": float(tube.OutsideDiameter),
        "tube_id": float(tube.InsideDiameter),
        "tube_height": float(tube.Height),
        "tube_axis_x": (tube.Shape.BoundBox.XMin + tube.Shape.BoundBox.XMax) / 2.0,
        "tube_axis_y": (tube.Shape.BoundBox.YMin + tube.Shape.BoundBox.YMax) / 2.0,
        "tube_bore_clear": final.Shape.common(bore_probe).Volume < 1e-5,
        "hole_count": int(holes.HoleCount),
        "hole_diameter": float(holes.HoleDiameter),
        "hole_x": (-float(holes.HoleOffsetX), float(holes.HoleOffsetX)),
        "hole_y": (0.0, 0.0),
        "holes_through": final.Shape.common(hole_probe).Volume < 1e-5,
        "gusset_count": 2,
        "gussets_symmetric": (
            abs(seed.Shape.Volume - mirror.Shape.Volume) < 1e-5
            and abs(seed_box.XMin + mirror_box.XMax) < 1e-5
            and abs(seed_box.XMax + mirror_box.XMin) < 1e-5
        ),
        "gussets_connected": len(final.Shape.Solids) == 1,
        "fillet_count": sum(
            abs(value - float(base.FilletRadius)) < 1e-5 for value in cylindrical_fillet_radii
        ),
        "fillet_radius": float(base.FilletRadius),
        "chamfer_present": len(conical_faces) == 1,
        "chamfer_size": float(tube.ChamferSize),
        "chamfer_angle": float(tube.ChamferAngle),
        "parametric": all(expression is not None for expression in expressions),
        "mesh_only": getattr(final, "TypeId", "").startswith("Mesh"),
        "assumptions_recorded": (
            len(assumption_data) >= 20
            and final.BenchmarkId == "CADW-WIZARD-BENCH-001"
            and final.GoverningStandard == "docs/CADW-DEMO-STANDARD.md"
        ),
        "wizard_execution_path": (
            final.AssistanceMode == "do_it"
            and "FreeCADStructuredCommandAdapter" in final.ExecutionPath
        ),
        "geometry_evidence": {
            "base_circular_edge_radii": circular_radii,
            "base_cylindrical_face_radii": cylindrical_fillet_radii,
            "tube_conical_face_count": len(conical_faces),
            "bore_probe_intersection_volume": final.Shape.common(bore_probe).Volume,
            "hole_probe_intersection_volume": final.Shape.common(hole_probe).Volume,
            "final_volume": final.Shape.Volume,
            "gusset_seed_bounds": {
                "x": [seed_box.XMin, seed_box.XMax],
                "y": [seed_box.YMin, seed_box.YMax],
                "z": [seed_box.ZMin, seed_box.ZMax],
            },
            "gusset_mirror_bounds": {
                "x": [mirror_box.XMin, mirror_box.XMax],
                "y": [mirror_box.YMin, mirror_box.YMax],
                "z": [mirror_box.ZMin, mirror_box.ZMax],
            },
            "expression_bindings": [str(value) for value in expressions],
        },
    }
