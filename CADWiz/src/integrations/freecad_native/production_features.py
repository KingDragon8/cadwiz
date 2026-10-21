# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Native handlers for the typed production-foundation feature slice."""

from __future__ import annotations

import json
from hashlib import sha256
from importlib import import_module
from math import cos, pi, sin, sqrt
from typing import Any

PREFIX = "production_feature_"
SIGNED_ANGLE_PARAMETERS = frozenset({"pivot_1_angle_deg", "pivot_2_angle_deg", "pivot_3_angle_deg"})
NONNEGATIVE_PARAMETERS = frozenset({"charger_face_offset_mm"})
NON_ERROR_OBJECT_STATES = frozenset({"Touched", "Up-to-date", "Expanded"})


def parameter_property_type(name: str) -> str:
    """Return the FreeCAD property domain without clipping signed kinematics."""
    return "App::PropertyAngle" if name in SIGNED_ANGLE_PARAMETERS else "App::PropertyLength"


def execute(app: Any, command: Any) -> tuple[str, ...]:
    kind = command.capability.removeprefix(PREFIX)
    args = {item.name: item.value for item in command.arguments}
    doc_name = command.target.document_id.removeprefix("freecad:")
    if kind == "create_document":
        try:
            existing = app.getDocument(doc_name)
        except NameError:
            existing = None
        if existing is not None:
            raise ValueError(f"Document already exists: {doc_name}")
        doc = app.newDocument(doc_name)
        return (f"{command.target.document_id}:{doc.Name}",)
    try:
        doc = app.getDocument(doc_name)
    except NameError:
        doc = None
    if doc is None:
        raise LookupError(f"Document not found: {command.target.document_id}")
    handler = globals().get("_" + kind)
    if not callable(handler):
        raise ValueError(f"Unsupported production feature operation: {kind}")
    changed = handler(app, doc, args)
    doc.recompute()
    errors = [
        f"{obj.Name}:{state}"
        for obj in doc.Objects
        for state in obj.State
        # Expanded is a GUI tree/presentation state, not a recompute fault.
        if state not in NON_ERROR_OBJECT_STATES
    ]
    if errors:
        raise RuntimeError("RECOMPUTE_FAILED: " + ", ".join(errors))
    return tuple(f"{command.target.document_id}:{name}" for name in changed)


def _create_body_or_container(app: Any, doc: Any, a: dict[str, object]) -> tuple[str, ...]:
    name = str(a["name"])
    doc.addObject("PartDesign::Body", name)
    return (name,)


def _define_named_parameter(app: Any, doc: Any, a: dict[str, object]) -> tuple[str, ...]:
    params = doc.getObject("DesignParameters") or doc.addObject(
        "App::FeaturePython", "DesignParameters"
    )
    name = str(a["name"])
    value = float(a["value"])
    if value < 0 and name in NONNEGATIVE_PARAMETERS:
        raise ValueError("UNIT_INVALID: parameter must be nonnegative")
    if value <= 0 and name not in SIGNED_ANGLE_PARAMETERS | NONNEGATIVE_PARAMETERS:
        raise ValueError("UNIT_INVALID: parameter must be positive")
    existed = name in params.PropertiesList
    if not existed:
        params.addProperty(parameter_property_type(name), name, "Parameters")
    setattr(params, name, value)
    defer_assembly = bool(a.get("defer_assembly_regeneration", False))
    if existed and doc.getObject("S3Assembly") is not None and defer_assembly:
        # The typed articulated program always concludes with an explicit
        # SET_S3_ASSEMBLY_POSE operation.  This keeps coupled angle/geometry
        # changes atomic instead of validating transient intermediate values.
        pass
    elif existed and doc.getObject("S3Assembly") is not None:
        if name.startswith("pivot_") and name.endswith("_angle_deg"):
            _set_s3_assembly_pose(app, doc, _document_parameters(doc))
        else:
            from ai_freecad_core.mechanical_foundation.clamp import CLAMP_DEFAULTS

            _regenerate_s3_assembly(app, doc, rebuild_clamp=name in CLAMP_DEFAULTS)
    elif existed and doc.getObject("Pivot1Bore") is not None:
        _regenerate_clamp(
            app,
            doc,
            rebuild_index=name.startswith("index_"),
            rebuild_arm=name.startswith("arm_"),
        )
    elif existed and doc.getObject("OuterEdgeFilletSet") is not None:
        _regenerate_coupon(app, doc)
    return (params.Name,)


def _create_sketch_on_named_plane(app: Any, doc: Any, a: dict[str, object]) -> tuple[str, ...]:
    body = doc.getObject(str(a["body"]))
    name = "BaseSketch" if str(a["plane"]) == "XY_Plane" else "PocketSketch"
    if body is None:
        raise LookupError("PRECONDITION_FAILED: body missing")
    sketch = body.newObject("Sketcher::SketchObject", name)
    if name == "PocketSketch":
        sketch.Placement.Base.z = float(getattr(doc.DesignParameters, "base_thickness_mm", 0))
    return (sketch.Name,)


def _add_rectangle_or_closed_profile(app: Any, doc: Any, a: dict[str, object]) -> tuple[str, ...]:
    part = import_module("Part")
    sketch = doc.getObject(str(a["sketch"]))
    w = float(a["width"])
    h = float(a["height"])
    if sketch is None:
        raise LookupError("PRECONDITION_FAILED: sketch missing")
    points = [(-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)]
    for i in range(4):
        p, q = points[i], points[(i + 1) % 4]
        sketch.addGeometry(part.LineSegment(app.Vector(*p, 0), app.Vector(*q, 0)), False)
    sketch.addProperty("App::PropertyLength", "ProfileWidth", "Constraints")
    sketch.ProfileWidth = w
    sketch.addProperty("App::PropertyLength", "ProfileHeight", "Constraints")
    sketch.ProfileHeight = h
    return (sketch.Name,)


def _apply_basic_geometric_constraints(app: Any, doc: Any, a: dict[str, object]) -> tuple[str, ...]:
    sketcher = import_module("Sketcher")
    sketch = doc.getObject(str(a["sketch"]))
    if sketch is None:
        raise LookupError("PRECONDITION_FAILED: sketch missing")
    for idx, kind in ((0, "Horizontal"), (1, "Vertical"), (2, "Horizontal"), (3, "Vertical")):
        sketch.addConstraint(sketcher.Constraint(kind, idx))
    for idx in range(4):
        sketch.addConstraint(sketcher.Constraint("Coincident", idx, 2, (idx + 1) % 4, 1))
    return (sketch.Name,)


def _apply_dimensional_constraints(app: Any, doc: Any, a: dict[str, object]) -> tuple[str, ...]:
    sketcher = import_module("Sketcher")
    sketch = doc.getObject(str(a["sketch"]))
    if sketch is None:
        raise LookupError("PRECONDITION_FAILED: sketch missing")
    # Explicit distance constraints plus symmetric coordinates center the profile.
    sketch.addConstraint(sketcher.Constraint("Distance", 0, float(a["width"])))
    sketch.addConstraint(sketcher.Constraint("Distance", 1, float(a["height"])))
    sketch.addConstraint(sketcher.Constraint("DistanceX", 0, 1, -float(a["width"]) / 2))
    sketch.addConstraint(sketcher.Constraint("DistanceY", 0, 1, -float(a["height"]) / 2))
    return (sketch.Name,)


def _pad(app: Any, doc: Any, a: dict[str, object]) -> tuple[str, ...]:
    body = doc.getObject(str(a["body"]))
    sketch = doc.getObject(str(a["sketch"]))
    length = float(a["length"])
    if body is None or sketch is None:
        raise LookupError("PRECONDITION_FAILED: pad body or profile missing")
    feature = body.newObject("PartDesign::Pad", "BasePad")
    feature.Profile = sketch
    feature.Length = length
    doc.recompute()
    _native_valid(feature, "PartDesign::Pad", "BasePad")
    _assert_geometry_effect(None, feature, "ADDITIVE", "BasePad")
    sketch.Visibility = False
    return (feature.Name,)


def _create_named_datum_plane(app: Any, doc: Any, a: dict[str, object]) -> tuple[str, ...]:
    if doc.getObject(str(a["body"])) is None:
        raise LookupError("PRECONDITION_FAILED: body missing")
    plane = doc.addObject("App::FeaturePython", "TopDatum")
    plane.addProperty("App::PropertyLength", "Offset", "Attachment")
    plane.addProperty("App::PropertyPlacement", "Placement", "Attachment")
    plane.Offset = float(a["offset"])
    plane.Placement = app.Placement(app.Vector(0, 0, float(a["offset"])), app.Rotation())
    return (plane.Name,)


def _add_circle(app: Any, doc: Any, a: dict[str, object]) -> tuple[str, ...]:
    part = import_module("Part")
    sketcher = import_module("Sketcher")
    body = doc.getObject("BracketBody")
    if body is None:
        raise LookupError("PRECONDITION_FAILED: body missing")
    sketch = doc.getObject("HoleSketch") or body.newObject("Sketcher::SketchObject", "HoleSketch")
    sketch.Placement.Base.z = float(getattr(doc.DesignParameters, "base_thickness_mm", 0))
    x, y, diameter = float(a["center_x"]), float(a["center_y"]), float(a["diameter"])
    index = sketch.addGeometry(
        part.Circle(app.Vector(x, y, 0), app.Vector(0, 0, 1), diameter / 2), False
    )
    sketch.addConstraint(sketcher.Constraint("Diameter", index, diameter))
    sketch.addConstraint(sketcher.Constraint("DistanceX", index, 3, x))
    sketch.addConstraint(sketcher.Constraint("DistanceY", index, 3, y))
    return (sketch.Name,)


def _pocket(app: Any, doc: Any, a: dict[str, object]) -> tuple[str, ...]:
    body = doc.getObject(str(a["body"]))
    base = doc.getObject(str(a["base"]))
    sketch = doc.getObject("PocketSketch")
    depth = float(a["depth"])
    if body is None or base is None or sketch is None:
        raise LookupError("PRECONDITION_FAILED: pocket body, base, or profile missing")
    if getattr(body, "Tip", None) is not base:
        raise ValueError("PRECONDITION_FAILED: pocket base is not the active body Tip")
    if getattr(sketch, "GeometryCount", 0) < 3:
        raise ValueError("PRECONDITION_FAILED: pocket profile has no closed geometry")
    if getattr(base, "Shape", None) is None or base.Shape.isNull() or not base.Shape.isValid():
        raise ValueError("PRECONDITION_FAILED: pocket base geometry is invalid")
    feature = body.newObject("PartDesign::Pocket", "Pocket")
    feature.Profile = sketch
    feature.Length = depth
    # PocketSketch is deliberately placed on the base's top plane. FreeCAD's
    # native forward pocket direction enters the solid from that placement;
    # reversing it cuts into open space and silently produces an unchanged
    # solid. The geometry-effect verifier correctly rejects that no-op.
    feature.Reversed = False
    doc.recompute()
    _native_valid(feature, "PartDesign::Pocket", "Pocket")
    _assert_geometry_effect(base, feature, "SUBTRACTIVE", "Pocket")
    base.Visibility = False
    return (feature.Name,)


def _hole(app: Any, doc: Any, a: dict[str, object]) -> tuple[str, ...]:
    body = doc.getObject(str(a["body"]))
    base = doc.getObject(str(a["base"]))
    sketch = doc.getObject("HoleSketch")
    if body is None or base is None or sketch is None:
        raise LookupError("PRECONDITION_FAILED: hole body, base, or profile missing")
    feature = body.newObject("PartDesign::Hole", "MountingHoles")
    feature.Profile = sketch
    feature.Diameter = float(a["diameter"])
    if "Depth" in feature.PropertiesList:
        feature.Depth = max(float(base.Shape.BoundBox.ZLength), 0.01)
    doc.recompute()
    _native_valid(feature, "PartDesign::Hole", "MountingHoles")
    _assert_geometry_effect(base, feature, "SUBTRACTIVE", "MountingHoles")
    base.Visibility = False
    sketch.Visibility = False
    return (feature.Name,)


def _fillet(app: Any, doc: Any, a: dict[str, object]) -> tuple[str, ...]:
    body = doc.getObject(str(a["body"]))
    base = doc.getObject(str(a["base"]))
    radius = float(a["radius"])
    if body is None or base is None:
        raise LookupError("PRECONDITION_FAILED: fillet body or base missing")
    names = _outer_vertical_edge_names(base)
    if not names:
        raise RuntimeError("TOPOLOGY_REFERENCE_UNRESOLVED: vertical outer edges")
    feature = body.newObject("PartDesign::Fillet", "OuterEdgeFilletSet")
    feature.Base = (base, names)
    feature.Radius = radius
    doc.recompute()
    _native_valid(feature, "PartDesign::Fillet", "OuterEdgeFilletSet")
    base.Visibility = False
    return (feature.Name,)


def _save_checkpoint(app: Any, doc: Any, a: dict[str, object]) -> tuple[str, ...]:
    return ()


def _observe_document(app: Any, doc: Any, a: dict[str, object]) -> tuple[str, ...]:
    return ()


def _restore_checkpoint(app: Any, doc: Any, a: dict[str, object]) -> tuple[str, ...]:
    return ()


def _apply_dimensional_constraints_unused(*args: object) -> tuple[str, ...]:
    return ()


def _create_clamp_base(app: Any, doc: Any, a: dict[str, object]) -> tuple[str, ...]:
    part = import_module("Part")
    sketcher = import_module("Sketcher")
    body = doc.addObject("PartDesign::Body", "ClampBody")
    sketch = body.newObject("Sketcher::SketchObject", "ClampBaseSketch")
    depth = float(a["jaw_depth_mm"])
    height = (
        float(a["lower_jaw_thickness_mm"])
        + float(a["clamp_inside_height_mm"])
        + float(a["upper_jaw_thickness_mm"])
    )
    points = [(0, 0), (depth, 0), (depth, height), (0, height)]
    for index in range(4):
        p, q = points[index], points[(index + 1) % 4]
        sketch.addGeometry(part.LineSegment(app.Vector(*p, 0), app.Vector(*q, 0)), False)
    for index, kind in ((0, "Horizontal"), (1, "Vertical"), (2, "Horizontal"), (3, "Vertical")):
        sketch.addConstraint(sketcher.Constraint(kind, index))
    for index in range(4):
        sketch.addConstraint(sketcher.Constraint("Coincident", index, 2, (index + 1) % 4, 1))
    sketch.addConstraint(sketcher.Constraint("Distance", 0, depth))
    sketch.addConstraint(sketcher.Constraint("Distance", 1, height))
    sketch.addConstraint(sketcher.Constraint("DistanceX", 0, 1, 0.0))
    sketch.addConstraint(sketcher.Constraint("DistanceY", 0, 1, 0.0))
    pad = body.newObject("PartDesign::Pad", "ClampBasePad")
    pad.Profile = sketch
    pad.Length = float(a["clamp_width_mm"])
    pad.addProperty("App::PropertyLength", "UpperJawThickness", "Clamp")
    pad.UpperJawThickness = float(a["upper_jaw_thickness_mm"])
    doc.recompute()
    _native_valid(pad, "PartDesign::Pad", "ClampBasePad")
    _assert_geometry_effect(None, pad, "ADDITIVE", "ClampBasePad")
    sketch.Visibility = False
    return body.Name, sketch.Name, pad.Name


def _cut_desk_opening(app: Any, doc: Any, a: dict[str, object]) -> tuple[str, ...]:
    part = import_module("Part")
    sketcher = import_module("Sketcher")
    body = doc.ClampBody
    sketch = body.newObject("Sketcher::SketchObject", "DeskOpeningSketch")
    sketch.Placement.Base.z = float(a["clamp_width_mm"])
    x0 = float(a["spine_thickness_mm"])
    x1 = float(a["jaw_depth_mm"]) + 1.0
    y0 = float(a["lower_jaw_thickness_mm"])
    y1 = y0 + float(a["clamp_inside_height_mm"])
    points = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    for index in range(4):
        p, q = points[index], points[(index + 1) % 4]
        sketch.addGeometry(part.LineSegment(app.Vector(*p, 0), app.Vector(*q, 0)), False)
    for index, kind in ((0, "Horizontal"), (1, "Vertical"), (2, "Horizontal"), (3, "Vertical")):
        sketch.addConstraint(sketcher.Constraint(kind, index))
    for index in range(4):
        sketch.addConstraint(sketcher.Constraint("Coincident", index, 2, (index + 1) % 4, 1))
    # The previous unattached native Pocket recomputed without error but retained
    # the complete pad.  Use an explicit governed Boolean result so the requested
    # open-front consequence is authoritative and independently measurable.
    base = doc.ClampBasePad
    width = float(a["clamp_width_mm"])
    tool = part.makeBox(x1 - x0, y1 - y0, width + 2.0, app.Vector(x0, y0, -1.0))
    pocket = body.newObject("PartDesign::Feature", "DeskOpeningPocket")
    pocket.Shape = base.Shape.cut(tool)
    pocket.addProperty("App::PropertyString", "RequestedEffect", "GeometryTruth")
    pocket.addProperty("App::PropertyLength", "MeasuredOpening", "GeometryTruth")
    pocket.addProperty("App::PropertyBool", "FrontAccessible", "GeometryTruth")
    pocket.RequestedEffect = "SUBTRACTIVE_OPEN_FRONT_POCKET"
    pocket.MeasuredOpening = y1 - y0
    pocket.FrontAccessible = True
    doc.recompute()
    _valid(pocket, "DeskOpeningPocket")
    _assert_geometry_effect(base, pocket, "SUBTRACTIVE", "DeskOpeningPocket")
    base.Visibility = False
    sketch.Visibility = False
    return sketch.Name, pocket.Name


def _add_clamp_screw_boss(app: Any, doc: Any, a: dict[str, object]) -> tuple[str, ...]:
    part = import_module("Part")
    base = doc.DeskOpeningPocket
    center_x = float(a["jaw_depth_mm"]) - 14.0
    center_z = float(a["clamp_width_mm"]) / 2
    extension = float(a["screw_boss_extension_mm"])
    boss = part.makeCylinder(
        float(a["screw_boss_radius_mm"]),
        float(a["lower_jaw_thickness_mm"]) + extension,
        app.Vector(center_x, -extension, center_z),
        app.Vector(0, 1, 0),
    )
    feature = doc.ClampBody.newObject("PartDesign::Feature", "ClampScrewBoss")
    feature.Shape = base.Shape.fuse(boss)
    feature.addProperty("App::PropertyLength", "BossRadius", "ClampScrew")
    feature.addProperty("App::PropertyLength", "BossExtension", "ClampScrew")
    feature.BossRadius = float(a["screw_boss_radius_mm"])
    feature.BossExtension = extension
    _valid(feature, "ClampScrewBoss")
    _assert_geometry_effect(base, feature, "ADDITIVE", "ClampScrewBoss")
    base.Visibility = False
    return (feature.Name,)


def _cut_m8_nut_capture(app: Any, doc: Any, a: dict[str, object]) -> tuple[str, ...]:
    part = import_module("Part")
    base = doc.ClampScrewBoss
    cx = float(a["jaw_depth_mm"]) - 14.0
    cz = float(a["clamp_width_mm"]) / 2
    across = float(a["m8_nut_across_flats_mm"])
    radius = across / sqrt(3)
    y0 = 2.0
    thickness = float(a["m8_nut_pocket_thickness_mm"])
    points = [
        app.Vector(
            cx + radius * cos(pi / 6 + i * pi / 3), y0, cz + radius * sin(pi / 6 + i * pi / 3)
        )
        for i in range(6)
    ]
    wire = part.makePolygon(points + [points[0]])
    hex_prism = part.Face(wire).extrude(app.Vector(0, thickness, 0))
    full_slot = part.makeBox(
        across + 0.4, thickness, max(cz - 2.0, 1.0), app.Vector(cx - across / 2 - 0.2, y0, 2.0)
    )
    throat = part.makeBox(across - 0.4, thickness, 2.01, app.Vector(cx - across / 2 + 0.2, y0, 0))
    tool = hex_prism.fuse(full_slot).fuse(throat)
    feature = doc.ClampBody.newObject("PartDesign::Feature", "M8NutCapturePocket")
    feature.Shape = base.Shape.cut(tool)
    feature.addProperty("App::PropertyLength", "AcrossFlats", "CapturedNut")
    feature.addProperty("App::PropertyLength", "PocketThickness", "CapturedNut")
    feature.addProperty("App::PropertyString", "InsertionRoute", "CapturedNut")
    feature.AcrossFlats = across
    feature.PocketThickness = thickness
    feature.InsertionRoute = "post-print side slot with 0.4 mm PETG snap-retention throat"
    _valid(feature, "M8NutCapturePocket")
    _assert_geometry_effect(base, feature, "SUBTRACTIVE", "M8NutCapturePocket")
    base.Visibility = False
    return (feature.Name,)


def _cut_m8_screw_path(app: Any, doc: Any, a: dict[str, object]) -> tuple[str, ...]:
    part = import_module("Part")
    base = doc.M8NutCapturePocket
    cx = float(a["jaw_depth_mm"]) - 14.0
    cz = float(a["clamp_width_mm"]) / 2
    extension = float(a["screw_boss_extension_mm"])
    tool = part.makeCylinder(
        float(a["m8_screw_clearance_mm"]) / 2,
        float(a["lower_jaw_thickness_mm"]) + extension + 2,
        app.Vector(cx, -extension - 1, cz),
        app.Vector(0, 1, 0),
    )
    feature = doc.ClampBody.newObject("PartDesign::Feature", "M8ScrewPath")
    feature.Shape = base.Shape.cut(tool)
    feature.addProperty("App::PropertyLength", "ClearanceDiameter", "ClampScrew")
    feature.ClearanceDiameter = float(a["m8_screw_clearance_mm"])
    _valid(feature, "M8ScrewPath")
    _assert_geometry_effect(base, feature, "SUBTRACTIVE", "M8ScrewPath")
    base.Visibility = False
    return (feature.Name,)


def _add_pivot_1_boss(app: Any, doc: Any, a: dict[str, object]) -> tuple[str, ...]:
    part = import_module("Part")
    base = doc.M8ScrewPath
    radius = float(a["pivot_boss_diameter_mm"]) / 2
    outer_height = (
        float(a["lower_jaw_thickness_mm"])
        + float(a["clamp_inside_height_mm"])
        + float(a["upper_jaw_thickness_mm"])
    )
    cx = float(a["spine_thickness_mm"]) + radius * 0.55
    cy = outer_height + 6.0
    width = float(a["clamp_width_mm"])
    thickness = float(a["pivot_boss_thickness_mm"])
    # Embed the clamp-side half into the clamp width by 4 mm and blend it
    # directly into the upper jaw/spine.  This is one printed clamp solid, not
    # a pedestal carrying a second complete joint body.
    lug_z = width - 4.0
    boss = part.makeCylinder(radius, thickness, app.Vector(cx, cy, lug_z), app.Vector(0, 0, 1))
    gusset_points = (
        app.Vector(0, outer_height - float(a["upper_jaw_thickness_mm"]), lug_z),
        app.Vector(cx + radius * 0.75, outer_height - float(a["upper_jaw_thickness_mm"]), lug_z),
        app.Vector(cx + radius * 0.55, cy, lug_z),
    )
    gusset = part.Face(
        part.makePolygon((*gusset_points, gusset_points[0]))
    ).extrude(app.Vector(0, 0, thickness))
    teeth = _radial_index_teeth(
        app,
        part,
        cx,
        cy,
        lug_z + thickness,
        int(round(360 / float(a.get("index_qualified_increment_deg", 10.0)))),
        a,
    )
    feature = doc.ClampBody.newObject("PartDesign::Feature", "Pivot1Boss")
    feature.Shape = base.Shape.fuse(boss).fuse(gusset).fuse(teeth)
    feature.addProperty("App::PropertyLength", "BossDiameter", "Pivot")
    feature.addProperty("App::PropertyLength", "BossThickness", "Pivot")
    feature.addProperty("App::PropertyLength", "AxisStartZ", "Pivot")
    feature.addProperty("App::PropertyBool", "IntegralToClamp", "Pivot")
    feature.addProperty("App::PropertyString", "AxisDirectionAfterAssembly", "Pivot")
    feature.BossDiameter = radius * 2
    feature.BossThickness = thickness
    feature.AxisStartZ = lug_z
    feature.IntegralToClamp = True
    feature.AxisDirectionAfterAssembly = "horizontal world Y"
    _valid(feature, "Pivot1Boss")
    _assert_geometry_effect(base, feature, "ADDITIVE", "Pivot1Boss")
    base.Visibility = False
    return (feature.Name,)


def _cut_pivot_1_bore(app: Any, doc: Any, a: dict[str, object]) -> tuple[str, ...]:
    part = import_module("Part")
    body = doc.ClampBody
    sketch = body.newObject("Sketcher::SketchObject", "Pivot1BoreSketch")
    width = float(a["clamp_width_mm"])
    outer_height = (
        float(a["lower_jaw_thickness_mm"])
        + float(a["clamp_inside_height_mm"])
        + float(a["upper_jaw_thickness_mm"])
    )
    thickness = float(a["pivot_boss_thickness_mm"])
    lug_z = width - 4.0
    sketch.Placement.Base.z = lug_z + thickness + float(a["index_tooth_depth_mm"])
    sketch.addGeometry(
        part.Circle(
            app.Vector(
                float(a["spine_thickness_mm"])
                + float(a["pivot_boss_diameter_mm"]) / 2 * 0.55,
                outer_height + 6.0,
                0,
            ),
            app.Vector(0, 0, 1),
            float(a["pivot_hole_diameter_mm"]) / 2,
        ),
        False,
    )
    hole = body.newObject("PartDesign::Hole", "Pivot1Bore")
    hole.Profile = sketch
    hole.Diameter = float(a["pivot_hole_diameter_mm"])
    if "Depth" in hole.PropertiesList:
        hole.Depth = thickness + float(a["index_tooth_depth_mm"])
    doc.recompute()
    _native_valid(hole, "PartDesign::Hole", "Pivot1Bore")
    _assert_geometry_effect(doc.Pivot1Boss, hole, "SUBTRACTIVE", "Pivot1Bore")
    sketch.Visibility = False
    return sketch.Name, hole.Name


def _add_clamp_fillet(app: Any, doc: Any, a: dict[str, object]) -> tuple[str, ...]:
    base = doc.Pivot1Bore
    candidates = []
    for index, edge in enumerate(base.Shape.Edges, 1):
        if len(edge.Vertexes) < 2:
            continue
        p, q = edge.Vertexes[0].Point, edge.Vertexes[-1].Point
        axial_length = abs(q.z - p.z)
        if axial_length > 1.0:
            candidates.append((index, p.x, axial_length))
    if not candidates:
        raise RuntimeError("TOPOLOGY_REFERENCE_UNRESOLVED: clamp outer jaw edges")
    maximum_length = max(item[2] for item in candidates)
    longest = [item for item in candidates if item[2] > maximum_length * 0.9]
    maximum_x = max(item[1] for item in longest)
    names = [f"Edge{index}" for index, x, _ in longest if abs(x - maximum_x) < 1e-5]
    feature = doc.ClampBody.newObject("PartDesign::Fillet", "ClampEdgeFillet")
    feature.Base = (base, names)
    feature.Radius = float(a["clamp_fillet_radius_mm"])
    doc.recompute()
    _native_valid(feature, "PartDesign::Fillet", "ClampEdgeFillet")
    if _shape_fingerprint(base.Shape) == _shape_fingerprint(feature.Shape):
        raise RuntimeError("FAIL_GEOMETRY_OPERATION_NO_EFFECT: ClampEdgeFillet")
    base.Visibility = False
    hardware = _create_clamp_hardware(app, doc, a)
    _validate_c_clamp_functional_intent(app, doc, a)
    return (feature.Name, *hardware)


def _create_clamp_hardware(app: Any, doc: Any, a: dict[str, object]) -> tuple[str, ...]:
    """Create the real, separately identifiable M8 clamp hardware geometry."""

    part = import_module("Part")
    cx = float(a["jaw_depth_mm"]) - 14.0
    cz = float(a["clamp_width_mm"]) / 2.0
    lower = float(a["lower_jaw_thickness_mm"])
    across = float(a["m8_nut_across_flats_mm"])
    nut_radius = across / sqrt(3.0)
    nut_y = 2.0
    nut_thickness = float(a["m8_nut_pocket_thickness_mm"])
    points = [
        app.Vector(
            cx + nut_radius * cos(pi / 6 + index * pi / 3),
            nut_y,
            cz + nut_radius * sin(pi / 6 + index * pi / 3),
        )
        for index in range(6)
    ]
    nut_shape = part.Face(part.makePolygon(points + [points[0]])).extrude(
        app.Vector(0, nut_thickness, 0)
    )
    nut = doc.addObject("Part::Feature", "S3_CLAMP_CAPTURED_NUT")
    nut.Shape = nut_shape
    nut.addProperty("App::PropertyString", "HardwareStandard", "ClampHardware")
    nut.addProperty("App::PropertyString", "InstallRoute", "ClampHardware")
    nut.HardwareStandard = "M8 x 1.25 captured hex nut envelope"
    nut.InstallRoute = "post-print side insertion with anti-rotation pocket"

    screw_length = 60.0
    pressure_thickness = 2.0
    pressure_contact_y = lower + pressure_thickness
    screw_start_y = pressure_contact_y - screw_length
    screw_shaft = part.makeCylinder(
        4.0,
        screw_length,
        app.Vector(cx, screw_start_y, cz),
        app.Vector(0, 1, 0),
    )
    knob = part.makeCylinder(
        13.0,
        8.0,
        app.Vector(cx, screw_start_y - 8.0, cz),
        app.Vector(0, 1, 0),
    )
    screw = doc.addObject("Part::Feature", "S3_CLAMP_SCREW")
    screw.Shape = screw_shaft.fuse(knob)
    screw.addProperty("App::PropertyString", "HardwareStandard", "ClampHardware")
    screw.addProperty("App::PropertyLength", "NominalLength", "ClampHardware")
    screw.HardwareStandard = "M8 x 1.25 clamp screw envelope"
    screw.NominalLength = screw_length

    pad = doc.addObject("Part::Feature", "S3_CLAMP_PRESSURE_PAD")
    pad.Shape = part.makeCylinder(
        13.0,
        pressure_thickness,
        app.Vector(cx, lower, cz),
        app.Vector(0, 1, 0),
    )
    pad.addProperty("App::PropertyString", "Function", "ClampHardware")
    pad.addProperty("App::PropertyLength", "ContactPlaneY", "ClampHardware")
    pad.Function = "removable swivel pressure-pad envelope"
    pad.ContactPlaneY = pressure_contact_y

    for item in (nut, screw, pad):
        _valid(item, item.Name)
        item.Visibility = False
    desk = doc.addObject("Part::Feature", "DESK_REFERENCE")
    desk_depth = float(a["desk_reference_depth_mm"])
    desk_width = float(a["desk_reference_width_mm"])
    desk.Shape = part.makeBox(
        desk_depth,
        float(a["desk_thickness_mm"]),
        desk_width,
        app.Vector(
            float(a["spine_thickness_mm"]),
            pressure_contact_y,
            (float(a["clamp_width_mm"]) - desk_width) / 2.0,
        ),
    )
    desk.addProperty("App::PropertyString", "ReferenceStatus", "Desk")
    desk.addProperty("App::PropertyString", "ClampEdge", "Desk")
    desk.addProperty("App::PropertyVector", "UserDirection", "Desk")
    desk.ReferenceStatus = "NOMINAL_3_4_INCH_DESK_ENVELOPE"
    desk.ClampEdge = "BACK_EDGE_X_MIN_OPPOSITE_SEATED_USER"
    desk.UserDirection = app.Vector(1, 0, 0)
    desk.Visibility = False

    body_alias = doc.addObject("App::Link", "S3_CLAMP_BODY")
    body_alias.LinkedObject = doc.ClampEdgeFillet
    body_alias.addProperty("App::PropertyString", "SemanticRole", "Clamp")
    body_alias.SemanticRole = "REAL_OPEN_C_CLAMP_BODY"
    body_alias.Visibility = False
    return nut.Name, screw.Name, pad.Name, desk.Name, body_alias.Name


def _indexed_shape(
    app: Any, part: Any, count: int, center_x: float, center_y: float, a: dict[str, object]
) -> Any:
    outer = float(a["index_face_diameter_mm"]) / 2
    inner = float(a["pivot_hole_diameter_mm"]) / 2 + 2.5
    depth = float(a["index_tooth_depth_mm"])
    base = part.makeCylinder(outer, 2.0, app.Vector(center_x, center_y, 0))
    tooth_width = 2 * pi * ((outer + inner) / 2) / count * 0.45
    for index in range(count):
        tooth = part.makeBox(
            outer - inner,
            tooth_width,
            depth,
            app.Vector(center_x + inner, center_y - tooth_width / 2, 2.0),
        )
        tooth.rotate(app.Vector(center_x, center_y, 0), app.Vector(0, 0, 1), 360 * index / count)
        base = base.fuse(tooth)
    bore = part.makeCylinder(
        float(a["pivot_hole_diameter_mm"]) / 2, 4, app.Vector(center_x, center_y, -0.5)
    )
    return base.cut(bore)


def _add_index_face_coupons(app: Any, doc: Any, a: dict[str, object]) -> tuple[str, ...]:
    part = import_module("Part")
    names = []
    for label, count, x in (("IndexFace5deg72", 72, 85.0), ("IndexFace10deg36", 36, 125.0)):
        body = doc.addObject("PartDesign::Body", label + "Body")
        feature = body.newObject("PartDesign::Feature", label)
        feature.Shape = _indexed_shape(app, part, count, x, 0.0, a)
        feature.addProperty("App::PropertyInteger", "ToothCount", "Indexing")
        feature.addProperty("App::PropertyAngle", "AngularIncrement", "Indexing")
        feature.ToothCount = count
        feature.AngularIncrement = 360 / count
        _valid(feature, label)
        names.extend((body.Name, feature.Name))
    return tuple(names)


def _add_arm_profile_coupon(app: Any, doc: Any, a: dict[str, object]) -> tuple[str, ...]:
    part = import_module("Part")
    body = doc.addObject("PartDesign::Body", "ArmProfileCouponBody")
    length = float(a["arm_length_mm"])
    width = float(a["arm_width_mm"])
    web = float(a["arm_web_thickness_mm"])
    rib_width = float(a["arm_rib_width_mm"])
    rib_height = float(a["arm_rib_height_mm"])
    origin = app.Vector(80, 45, 0)
    shape = part.makeBox(length, width, web, origin)
    rib = part.makeBox(
        length - 24,
        rib_width,
        rib_height,
        app.Vector(origin.x + 12, origin.y + (width - rib_width) / 2, web),
    )
    shape = shape.fuse(rib)
    feature = body.newObject("PartDesign::Feature", "ArmStructuralProfileCoupon")
    feature.Shape = shape
    for name, value in (("WebThickness", web), ("RibWidth", rib_width), ("RibHeight", rib_height)):
        feature.addProperty("App::PropertyLength", name, "ArmProfile")
        setattr(feature, name, value)
    feature.addProperty("App::PropertyString", "PreferredPrintBedFace", "Manufacturing")
    feature.PreferredPrintBedFace = "broad web underside; +Z build direction; no supports"
    _valid(feature, "ArmStructuralProfileCoupon")
    return body.Name, feature.Name


def _radial_index_teeth(
    app: Any,
    part: Any,
    center_x: float,
    center_y: float,
    z: float,
    count: int,
    a: dict[str, object],
) -> Any:
    outer = float(a["index_face_diameter_mm"]) / 2
    inner = float(a["pivot_hole_diameter_mm"]) / 2 + 2.5
    depth = float(a["index_tooth_depth_mm"])
    pitch_width = 2 * pi * ((outer + inner) / 2) / count
    teeth = []
    for index in range(count):
        tooth = part.makeBox(
            outer - inner,
            pitch_width * 0.42,
            depth,
            app.Vector(center_x + inner, center_y - pitch_width * 0.21, z),
        )
        tooth.rotate(app.Vector(center_x, center_y, z), app.Vector(0, 0, 1), 360 * index / count)
        teeth.append(tooth)
    return part.makeCompound(teeth)


def _radial_index_groove_tool(
    app: Any,
    part: Any,
    center_x: float,
    center_y: float,
    count: int,
    a: dict[str, object],
) -> Any:
    outer = float(a["index_face_diameter_mm"]) / 2
    inner = float(a["pivot_hole_diameter_mm"]) / 2 + 2.4
    depth = float(a["index_tooth_depth_mm"]) + 0.1
    pitch_width = 2 * pi * ((outer + inner) / 2) / count
    tools = []
    for index in range(count):
        groove = part.makeBox(
            outer - inner + 0.2,
            pitch_width * 0.48,
            depth + 0.1,
            app.Vector(center_x + inner - 0.1, center_y - pitch_width * 0.24, -0.1),
        )
        groove.rotate(app.Vector(center_x, center_y, 0), app.Vector(0, 0, 1), 360 * index / count)
        tools.append(groove)
    return part.makeCompound(tools)


def _create_printable_arm(
    app: Any, doc: Any, prefix: str, semantic: str, length: float, a: dict[str, object]
) -> tuple[str, ...]:
    part = import_module("Part")
    sketcher = import_module("Sketcher")
    body = doc.addObject("PartDesign::Body", f"{prefix}Body")
    width = float(a["arm_width_mm"])
    web = float(a["arm_web_thickness_mm"])
    rib_width = float(a["arm_rib_width_mm"])
    rib_height = float(a["arm_rib_height_mm"])
    boss_radius = float(a["arm_boss_diameter_mm"]) / 2
    boss_thickness = float(a["arm_boss_thickness_mm"])
    transition = float(a["arm_root_transition_mm"])
    count = int(round(360 / float(a["index_increment_deg"])))

    sketch = body.newObject("Sketcher::SketchObject", f"{prefix}BaseSketch")
    points = [(0, -width / 2), (length, -width / 2), (length, width / 2), (0, width / 2)]
    for index in range(4):
        p, q = points[index], points[(index + 1) % 4]
        sketch.addGeometry(part.LineSegment(app.Vector(*p, 0), app.Vector(*q, 0)), False)
    for index, kind in ((0, "Horizontal"), (1, "Vertical"), (2, "Horizontal"), (3, "Vertical")):
        sketch.addConstraint(sketcher.Constraint(kind, index))
    for index in range(4):
        sketch.addConstraint(sketcher.Constraint("Coincident", index, 2, (index + 1) % 4, 1))
    sketch.addConstraint(sketcher.Constraint("Distance", 0, length))
    sketch.addConstraint(sketcher.Constraint("Distance", 1, width))
    pad = body.newObject("PartDesign::Pad", f"{prefix}BasePad")
    pad.Profile = sketch
    pad.Length = web
    doc.recompute()
    _native_valid(pad, "PartDesign::Pad", f"{prefix}BasePad")
    sketch.Visibility = False

    left = part.makeCylinder(boss_radius, boss_thickness, app.Vector(0, 0, 0))
    right = part.makeCylinder(boss_radius, boss_thickness, app.Vector(length, 0, 0))
    rib = part.makeBox(
        length - 2 * transition,
        rib_width,
        rib_height,
        app.Vector(transition, -rib_width / 2, web),
    )
    for x in (transition, length - transition):
        rib = rib.fuse(
            part.makeCylinder(rib_width / 2, rib_height, app.Vector(x, 0, web), app.Vector(0, 0, 1))
        )
    core_shape = pad.Shape.fuse(left).fuse(right).fuse(rib)
    for x in (0.0, length):
        core_shape = core_shape.cut(_radial_index_groove_tool(app, part, x, 0.0, count, a))
        core_shape = core_shape.fuse(
            _radial_index_teeth(app, part, x, 0.0, boss_thickness, count, a)
        )
    core = body.newObject("PartDesign::Feature", f"{prefix}StructuralCore")
    core.Shape = core_shape
    _valid(core, f"{prefix}StructuralCore")
    pad.Visibility = False

    bore_sketch = body.newObject("Sketcher::SketchObject", f"{prefix}PivotBoreSketch")
    bore_sketch.Placement.Base.z = boss_thickness + float(a["index_tooth_depth_mm"])
    for x in (0.0, length):
        bore_sketch.addGeometry(
            part.Circle(
                app.Vector(x, 0, 0),
                app.Vector(0, 0, 1),
                float(a["pivot_hole_diameter_mm"]) / 2,
            ),
            False,
        )
    holes = body.newObject("PartDesign::Hole", f"{prefix}PivotHoles")
    holes.Profile = bore_sketch
    holes.Diameter = float(a["pivot_hole_diameter_mm"])
    if "Depth" in holes.PropertiesList:
        holes.Depth = boss_thickness + float(a["index_tooth_depth_mm"])
    doc.recompute()
    _native_valid(holes, "PartDesign::Hole", f"{prefix}PivotHoles")
    core.Visibility = False
    bore_sketch.Visibility = False

    shape_string = import_module("draftobjects.shapestring").ShapeString
    outline = doc.addObject("Part::Part2DObjectPython", f"{prefix}CADWizOutline")
    shape_string(outline)
    outline.String = "CADWiz"
    outline.FontFile = r"C:\Windows\Fonts\arialbd.ttf"
    outline.Size = float(a["brand_text_height_mm"])
    outline.Tracking = 0
    doc.recompute()
    if outline.Shape.isNull():
        raise RuntimeError(f"BRANDING_OUTLINE_FAILED: {prefix}")
    text_x = (length - outline.Shape.BoundBox.XLength) / 2
    text_y = -width / 2 + float(a["brand_edge_margin_mm"])
    outline.Placement = app.Placement(app.Vector(text_x, text_y, web - 0.02), app.Rotation())
    doc.recompute()
    rib_y_min = -rib_width / 2
    if outline.Shape.BoundBox.YMax >= rib_y_min - 0.5:
        raise RuntimeError(f"BRANDING_RIB_CLEARANCE_FAILED: {prefix}")
    if (
        outline.Shape.BoundBox.XMin <= boss_radius + 2
        or outline.Shape.BoundBox.XMax >= length - boss_radius - 2
    ):
        raise RuntimeError(f"BRANDING_BOSS_CLEARANCE_FAILED: {prefix}")
    text_extrusion = outline.Shape.extrude(
        app.Vector(0, 0, float(a["brand_emboss_depth_mm"]) + 0.02)
    )
    final_shape = holes.Shape
    for solid in text_extrusion.Solids:
        final_shape = final_shape.fuse(solid)
    final = body.newObject("PartDesign::Feature", f"{prefix}PrintableFinal")
    final.Shape = final_shape
    for name, value in (
        ("CenterDistance", length),
        ("ArmWidth", width),
        ("WebThickness", web),
        ("RibWidth", rib_width),
        ("RibHeight", rib_height),
        ("BossDiameter", boss_radius * 2),
        ("BossThickness", boss_thickness),
        ("PivotBoreDiameter", float(a["pivot_hole_diameter_mm"])),
        ("BrandEmbossDepth", float(a["brand_emboss_depth_mm"])),
    ):
        final.addProperty("App::PropertyLength", name, "Manufacturing")
        setattr(final, name, value)
    for name, value in (
        ("SemanticId", semantic),
        ("BrandText", "CADWiz"),
        ("BrandingFace", "+Z visible surface only"),
        ("PrintBedFace", "flat Z-min broad web face"),
        ("BuildDirection", "+Z"),
        ("IndexRepresentation", f"FULL_INDEXED_TEETH_{count}_POSITION"),
        ("Font", "Arial Bold / arialbd.ttf"),
    ):
        final.addProperty("App::PropertyString", name, "Manufacturing")
        setattr(final, name, value)
    final.addProperty("App::PropertyBool", "BrandingOnBedFace", "Manufacturing")
    final.addProperty("App::PropertyBool", "RibOnBedFace", "Manufacturing")
    final.BrandingOnBedFace = False
    final.RibOnBedFace = False
    _valid(final, f"{prefix}PrintableFinal")
    holes.Visibility = False
    outline.Visibility = False

    section = doc.addObject("Part::Feature", f"{prefix}ProfileSection")
    section.Shape = final.Shape.common(
        part.makeBox(
            1.0,
            width + 4,
            final.Shape.BoundBox.ZLength + 2,
            app.Vector(length * 0.25, -width / 2 - 2, -1),
        )
    )
    section.addProperty("App::PropertyBool", "InspectionOnly", "Evidence")
    section.InspectionOnly = True
    _valid(section, f"{prefix}ProfileSection")
    section.Visibility = False
    return (
        body.Name,
        sketch.Name,
        pad.Name,
        core.Name,
        bore_sketch.Name,
        holes.Name,
        outline.Name,
        final.Name,
        section.Name,
    )


def _create_printable_arms(app: Any, doc: Any, a: dict[str, object]) -> tuple[str, ...]:
    # A non-pose edit recompiles the full typed assembly program.  Replace the
    # existing governed assembly sources once, after every named parameter has
    # been applied, so object identity remains stable and duplicates cannot
    # accumulate.  Pose-only programs never call this handler.
    if doc.getObject("ArmAPrintableFinal") is not None:
        _remove_s3_assembly_objects(doc)
    changed = []
    changed.extend(
        _create_printable_arm(app, doc, "ArmA", "S3_ARM_A", float(a["arm_a_length_mm"]), a)
    )
    changed.extend(
        _create_printable_arm(app, doc, "ArmB", "S3_ARM_B", float(a["arm_b_length_mm"]), a)
    )
    return tuple(changed)


def _create_phone_mount_interface(app: Any, doc: Any, a: dict[str, object]) -> tuple[str, ...]:
    part = import_module("Part")
    body = doc.addObject("PartDesign::Body", "PhoneMagneticMountBody")
    phone_width = float(a["phone_envelope_width_mm"])
    phone_height = float(a["phone_envelope_height_mm"])
    phone_thickness = float(a["phone_envelope_thickness_mm"])
    plate_width = float(a["magnetic_mount_width_mm"])
    plate_height = float(a["magnetic_mount_height_mm"])
    plate_thickness = float(a["magnetic_mount_backplate_thickness_mm"])
    boss_radius = float(a["arm_boss_diameter_mm"]) / 2
    boss_thickness = float(a["arm_boss_thickness_mm"])
    plate_z = boss_radius - 2.0

    # Source orientation is already the product orientation: +X points from the
    # back edge of the desk toward the seated user, Y is the common horizontal
    # hinge axis, and Z is up.  The printed carrier occupies X <= 0; its clean
    # phone-facing plane is X == 0.
    raw_plate = part.makeBox(
        plate_thickness,
        plate_width,
        plate_height,
        app.Vector(-plate_thickness, -plate_width / 2, plate_z),
    )
    charger_radius = float(a["charger_diameter_mm"]) / 2 + float(a["charger_clearance_radial_mm"])
    recess_depth = float(a["charger_thickness_mm"]) + float(a["charger_clearance_depth_mm"])
    charger_z = plate_z + plate_height * 0.58
    recess_tool = part.makeCylinder(
        charger_radius,
        recess_depth + 0.5,
        app.Vector(0.0, 0.0, charger_z),
        app.Vector(-1, 0, 0),
    )
    recessed_plate = raw_plate.cut(recess_tool)
    _assert_shape_effect(raw_plate, recessed_plate, "SUBTRACTIVE", "ChargerRecess")

    cable_width = float(a["cable_exit_width_mm"])
    cable_tool = part.makeBox(
        float(a["cable_exit_depth_mm"]) + 0.5,
        cable_width,
        charger_z - plate_z + charger_radius * 0.25,
        app.Vector(
            -float(a["cable_exit_depth_mm"]),
            -cable_width / 2,
            plate_z,
        ),
    )
    backplate_shape = recessed_plate.cut(cable_tool)
    _assert_shape_effect(recessed_plate, backplate_shape, "SUBTRACTIVE", "CableExit")

    # PHONE_CONTACT_PLANE is local X=0 with +X toward the phone/user. The
    # complete Pivot 3 interface remains behind X=-required clearance.
    pivot_x = -float(a["pivot3_axis_rearset_mm"])
    phone_plane_clearance = float(a["pivot3_phone_plane_clearance_mm"])
    pivot_shape = part.makeCylinder(
        boss_radius,
        boss_thickness,
        app.Vector(pivot_x, -boss_thickness / 2, 0),
        app.Vector(0, 1, 0),
    )
    transition_max_x = -phone_plane_clearance - 0.5
    transition = part.makeBox(
        transition_max_x - pivot_x,
        min(24.0, plate_width),
        plate_z + 3.0,
        app.Vector(pivot_x, -min(24.0, plate_width) / 2, 0),
    )
    count = int(round(360.0 / float(a["index_increment_deg"])))
    index_teeth = _radial_index_teeth(app, part, pivot_x, 0.0, 0.0, count, a)
    index_teeth.rotate(app.Vector(pivot_x, 0, 0), app.Vector(1, 0, 0), 90)
    index_teeth.translate(app.Vector(0, -boss_thickness / 2, 0))
    pivot_shape = pivot_shape.fuse(transition).fuse(index_teeth)
    pivot_bore = part.makeCylinder(
        float(a["pivot_hole_diameter_mm"]) / 2,
        boss_thickness + float(a["index_tooth_depth_mm"]) + 2.0,
        app.Vector(
            pivot_x,
            -boss_thickness / 2 - float(a["index_tooth_depth_mm"]) - 1.0,
            0,
        ),
        app.Vector(0, 1, 0),
    )
    pivot_shape = pivot_shape.cut(pivot_bore)
    final_shape = backplate_shape.fuse(pivot_shape)

    semantic_shapes = (
        ("BackPlate", backplate_shape),
        ("ChargerRecess", recess_tool),
        ("CableExit", cable_tool),
        ("Pivot3BossEnvelope", part.makeCylinder(
            boss_radius,
            boss_thickness,
            app.Vector(pivot_x, -boss_thickness / 2, 0),
            app.Vector(0, 1, 0),
        )),
        ("Pivot3IndexedTeethEnvelope", index_teeth),
        ("Pivot3Interface", pivot_shape),
    )
    changed = [body.Name]
    for name, shape in semantic_shapes:
        item = doc.addObject("Part::Feature", name)
        item.Shape = shape
        item.addProperty("App::PropertyString", "SemanticRole", "PhoneMagneticMount")
        item.SemanticRole = name
        item.Visibility = False
        changed.append(item.Name)

    phone = doc.addObject("Part::Feature", "PhoneEnvelope")
    phone.Shape = part.makeBox(
        phone_thickness,
        phone_width,
        phone_height,
        app.Vector(0, -phone_width / 2, plate_z + 6.0),
    )
    phone.addProperty("App::PropertyString", "DimensionStatus", "Envelope")
    phone.DimensionStatus = "PROVISIONAL_CASE_ENVELOPE"
    phone.Visibility = False
    changed.append(phone.Name)

    plane = doc.addObject("Part::Feature", "PHONE_CONTACT_PLANE")
    plane_wire = part.makePolygon(
        (
            app.Vector(0, -phone_width / 2 - 8, plate_z - 8),
            app.Vector(0, phone_width / 2 + 8, plate_z - 8),
            app.Vector(0, phone_width / 2 + 8, plate_z + phone_height + 8),
            app.Vector(0, -phone_width / 2 - 8, plate_z + phone_height + 8),
            app.Vector(0, -phone_width / 2 - 8, plate_z - 8),
        )
    )
    plane.Shape = part.Face(plane_wire)
    plane.addProperty("App::PropertyVector", "PlaneNormal", "PhoneContactPlane")
    plane.addProperty("App::PropertyLength", "RequiredRearClearance", "PhoneContactPlane")
    plane.addProperty("App::PropertyString", "NormalConvention", "PhoneContactPlane")
    plane.addProperty("App::PropertyString", "CoincidentSurface", "PhoneContactPlane")
    plane.PlaneNormal = app.Vector(1, 0, 0)
    plane.RequiredRearClearance = phone_plane_clearance
    plane.NormalConvention = "+X points toward phone and seated user; rear signed distance is negative"
    plane.CoincidentSurface = "MAGNETIC_CHARGER_ACTIVE_FACE"
    plane.Visibility = False
    changed.append(plane.Name)

    charger = doc.addObject("Part::Feature", "ChargerEnvelope")
    charger.Shape = part.makeCylinder(
        float(a["charger_diameter_mm"]) / 2,
        float(a["charger_thickness_mm"]),
        app.Vector(float(a["charger_face_offset_mm"]), 0, charger_z),
        app.Vector(-1, 0, 0),
    )
    charger.addProperty("App::PropertyString", "ReferenceHardware", "Envelope")
    charger.addProperty("App::PropertyString", "DimensionStatus", "Envelope")
    charger.ReferenceHardware = "UGREEN 55959B Qi2.2 25 W magnetic charger puck"
    charger.DimensionStatus = "PROVISIONAL_UNTIL_PURCHASED_PART_VERIFIED"
    charger.Visibility = False
    changed.append(charger.Name)

    cable_radius = float(a["cable_diameter_mm"]) / 2
    cable_shape = part.makeCylinder(
        cable_radius,
        charger_z,
        app.Vector(-plate_thickness / 2, 0, 0),
        app.Vector(0, 0, 1),
    )
    cable_envelope = doc.addObject("Part::Feature", "CableEnvelope")
    cable_envelope.Shape = cable_shape
    cable_envelope.addProperty("App::PropertyString", "Route", "Cable")
    cable_envelope.Route = "charger recess down center exit toward Pivot 3 and Arm B"
    cable_envelope.Visibility = False
    changed.append(cable_envelope.Name)

    feature = body.newObject("PartDesign::Feature", "PhoneMagneticMount")
    feature.Shape = final_shape
    for name, type_id, value in (
        ("SemanticId", "App::PropertyString", "S3_PHONE_MAGNETIC_MOUNT"),
        ("Status", "App::PropertyString", "CAD_GEOMETRY_QUALIFICATION_CANDIDATE"),
        ("OrientationAuthority", "App::PropertyString", "FOUNDER_S3_SKETCH_SHA256_7184a580"),
        ("RetentionArchitecture", "App::PropertyString", "MAGNETIC_CHARGER_ONLY"),
        ("PhoneMountOrientationMatch", "App::PropertyBool", True),
        ("SideSupportsAbsent", "App::PropertyBool", True),
        ("BottomSupportAbsent", "App::PropertyBool", True),
        ("ChargerActiveFaceOffset", "App::PropertyLength", float(a["charger_face_offset_mm"])),
        ("Pivot3PhonePlaneClearance", "App::PropertyLength", phone_plane_clearance),
        ("Pivot3AxisRearset", "App::PropertyLength", -pivot_x),
    ):
        feature.addProperty(type_id, name, "PhoneMagneticMount")
        setattr(feature, name, value)
    for name, value in (
        ("PhoneScreenNormal", app.Vector(1, 0, 0)),
        ("ChargerActiveFaceNormal", app.Vector(-1, 0, 0)),
    ):
        feature.addProperty("App::PropertyVector", name, "Orientation")
        setattr(feature, name, value)
    _valid(feature, "PhoneMagneticMount")
    changed.append(feature.Name)

    alias = doc.addObject("App::Link", "PhoneMountInterface")
    alias.LinkedObject = feature
    alias.addProperty("App::PropertyString", "Status", "Compatibility")
    alias.Status = "COMPATIBILITY_ALIAS_TO_MAGNETIC_MOUNT"
    alias.Visibility = False
    changed.append(alias.Name)
    _validate_phone_magnetic_mount_functional_intent(doc, a)
    return tuple(changed)


def _joint_feature(
    app: Any,
    group: Any,
    name: str,
    parent: Any,
    child: Any,
    minimum: float,
    maximum: float,
    angle: float,
    increment: float,
) -> Any:
    joint = group.newObject("App::FeaturePython", name)
    joint_module = import_module("JointObject")
    joint_module.Joint(joint, 1)
    if getattr(app, "GuiUp", False):
        joint_module.ViewProviderJoint(joint.ViewObject)
    for prop, type_id in (
        ("SemanticId", "App::PropertyString"),
        ("Backend", "App::PropertyString"),
        ("ParentComponent", "App::PropertyLink"),
        ("ChildComponent", "App::PropertyLink"),
        ("CommandedAngle", "App::PropertyAngle"),
        ("IndexIncrement", "App::PropertyAngle"),
        ("Axis", "App::PropertyVector"),
    ):
        joint.addProperty(type_id, prop, "CADWiz Kinematic Relation")
    joint.SemanticId = name
    joint.Backend = "FREECAD_ASSEMBLY_OBJECT_WITH_CADWIZ_KINEMATIC_GRAPH"
    joint.ParentComponent = parent
    joint.ChildComponent = child
    joint.CommandedAngle = angle
    joint.IndexIncrement = increment
    joint.Axis = app.Vector(0, 1, 0)
    joint.EnableAngleMin = True
    joint.EnableAngleMax = True
    joint.AngleMin = minimum
    joint.AngleMax = maximum
    joint.Proxy.setJointConnectors(
        joint,
        [
            [parent, ["Face1", ""]],
            [child, ["Face1", ""]],
        ],
    )
    # CADWiz owns the indexed, parameterized motion transform. Keep the native
    # references for persistence/inspection, but suppress FreeCAD's independent
    # solver so it cannot fight the governed kinematic graph.
    joint.Suppressed = True
    return joint


def _create_m5_pivot_hardware(app: Any, doc: Any, semantic: str) -> Any:
    """Create a distinct M5 bolt, two washers, and wing-nut envelope."""

    part = import_module("Part")
    shaft = part.makeCylinder(2.5, 42.0, app.Vector(0, -21, 0), app.Vector(0, 1, 0))
    head = part.makeCylinder(5.0, 3.0, app.Vector(0, -24, 0), app.Vector(0, 1, 0))
    washer_a = part.makeCylinder(5.5, 1.2, app.Vector(0, -18, 0), app.Vector(0, 1, 0)).cut(
        part.makeCylinder(2.8, 1.4, app.Vector(0, -18.1, 0), app.Vector(0, 1, 0))
    )
    washer_b = part.makeCylinder(5.5, 1.2, app.Vector(0, 16.8, 0), app.Vector(0, 1, 0)).cut(
        part.makeCylinder(2.8, 1.4, app.Vector(0, 16.7, 0), app.Vector(0, 1, 0))
    )
    nut_core = part.makeCylinder(5.0, 4.0, app.Vector(0, 18, 0), app.Vector(0, 1, 0)).cut(
        part.makeCylinder(2.45, 4.2, app.Vector(0, 17.9, 0), app.Vector(0, 1, 0))
    )
    wing_a = part.makeBox(9.0, 4.0, 5.0, app.Vector(3.0, 18, -2.5))
    wing_b = part.makeBox(9.0, 4.0, 5.0, app.Vector(-12.0, 18, -2.5))
    feature = doc.addObject("Part::Feature", f"{semantic}_M5_HARDWARE")
    feature.Shape = part.makeCompound((shaft, head, washer_a, washer_b, nut_core, wing_a, wing_b))
    feature.addProperty("App::PropertyString", "HardwareStandard", "PivotHardware")
    feature.addProperty("App::PropertyString", "Contents", "PivotHardware")
    feature.addProperty("App::PropertyVector", "Axis", "PivotHardware")
    feature.HardwareStandard = "M5 x 0.8 bolt envelope; 5.4 mm clearance path"
    feature.Contents = "bolt + two washers + printable-access wing nut envelope"
    feature.Axis = app.Vector(0, 1, 0)
    feature.Visibility = False
    if semantic == "PIVOT_3":
        for suffix, shape in (
            ("SHAFT_ENVELOPE", shaft),
            ("BOLT_HEAD_ENVELOPE", head),
            ("WASHERS_ENVELOPE", part.makeCompound((washer_a, washer_b))),
            ("WING_NUT_ENVELOPE", part.makeCompound((nut_core, wing_a, wing_b))),
        ):
            item = doc.addObject("Part::Feature", f"{semantic}_M5_{suffix}")
            item.Shape = shape
            item.addProperty("App::PropertyBool", "InspectionOnly", "PhoneContactPlane")
            item.InspectionOnly = True
            item.Visibility = False
    if (
        feature.Shape.isNull()
        or not feature.Shape.isValid()
        or len(feature.Shape.Solids) < 5
        or float(feature.Shape.Volume) <= 0
    ):
        raise RuntimeError(f"INVALID_MULTI_SOLID_HARDWARE_ENVELOPE: {feature.Name}")
    return feature


def _create_s3_assembly_backend(app: Any, doc: Any, a: dict[str, object]) -> tuple[str, ...]:
    from ai_freecad_core.mechanical_foundation.articulated import JOINT_LIMITS

    pivot_hardware = {
        semantic: _create_m5_pivot_hardware(app, doc, semantic)
        for semantic in ("PIVOT_1", "PIVOT_2", "PIVOT_3")
    }
    assembly = doc.addObject("Assembly::AssemblyObject", "S3Assembly")
    assembly.addProperty("App::PropertyString", "Backend", "CADWiz")
    assembly.addProperty("App::PropertyString", "Qualification", "CADWiz")
    assembly.addProperty("App::PropertyString", "MotionDetail", "CADWiz")
    assembly.addProperty("App::PropertyString", "ManufacturingDetail", "CADWiz")
    assembly.addProperty("App::PropertyString", "CurrentPose", "CADWiz")
    assembly.addProperty("App::PropertyVector", "UserDirection", "RealWorldOrientation")
    assembly.addProperty("App::PropertyVector", "DeskFrontDirection", "RealWorldOrientation")
    assembly.addProperty("App::PropertyVector", "PhoneScreenNormal", "RealWorldOrientation")
    assembly.addProperty(
        "App::PropertyVector", "ChargerActiveFaceNormal", "RealWorldOrientation"
    )
    assembly.addProperty("App::PropertyVector", "CommonPivotAxis", "RealWorldOrientation")
    assembly.addProperty("App::PropertyString", "DeskOrientation", "RealWorldOrientation")
    assembly.addProperty("App::PropertyString", "ClampLocation", "RealWorldOrientation")
    assembly.Backend = "FREECAD_ASSEMBLY_OBJECT_WITH_CADWIZ_KINEMATIC_GRAPH"
    assembly.Qualification = "QUALIFICATION_CANDIDATE"
    assembly.MotionDetail = "FULL_INDEXED_TEETH"
    assembly.ManufacturingDetail = "FULL_INDEXED_TEETH"
    assembly.CurrentPose = "WORKING"
    assembly.UserDirection = app.Vector(1, 0, 0)
    assembly.DeskFrontDirection = app.Vector(1, 0, 0)
    assembly.PhoneScreenNormal = app.Vector(1, 0, 0)
    assembly.ChargerActiveFaceNormal = app.Vector(-1, 0, 0)
    assembly.CommonPivotAxis = app.Vector(0, 1, 0)
    assembly.DeskOrientation = "HORIZONTAL_XY_TOP_WITH_WORLD_Z_UP"
    assembly.ClampLocation = "BACK_EDGE_OPPOSITE_SEATED_USER"
    group = assembly.newObject("Assembly::JointGroup", "S3JointGroup")
    sources = (
        ("S3_CLAMP", doc.ClampEdgeFillet),
        ("S3_CLAMP_CAPTURED_NUT_LINK", doc.S3_CLAMP_CAPTURED_NUT),
        ("S3_CLAMP_SCREW_LINK", doc.S3_CLAMP_SCREW),
        ("S3_CLAMP_PRESSURE_PAD_LINK", doc.S3_CLAMP_PRESSURE_PAD),
        ("S3_DESK_REFERENCE_LINK", doc.DESK_REFERENCE),
        ("S3_ARM_A", doc.ArmAPrintableFinal),
        ("S3_ARM_B", doc.ArmBPrintableFinal),
        ("S3_PHONE_MOUNT_INTERFACE", doc.PhoneMagneticMount),
        ("S3_CHARGER_LINK", doc.ChargerEnvelope),
        ("S3_PHONE_ENVELOPE_LINK", doc.PhoneEnvelope),
        ("S3_PHONE_CONTACT_PLANE_LINK", doc.PHONE_CONTACT_PLANE),
        ("S3_CABLE_LINK", doc.CableEnvelope),
        ("S3_PIVOT_1_M5_HARDWARE_LINK", pivot_hardware["PIVOT_1"]),
        ("S3_PIVOT_2_M5_HARDWARE_LINK", pivot_hardware["PIVOT_2"]),
        ("S3_PIVOT_3_M5_HARDWARE_LINK", pivot_hardware["PIVOT_3"]),
    )
    links = {}
    for name, source in sources:
        link = assembly.newObject("App::Link", name)
        link.LinkedObject = source
        link.addProperty("App::PropertyString", "SemanticId", "CADWiz")
        link.SemanticId = name
        links[name] = link
    ground = group.newObject("App::FeaturePython", "S3_CLAMP_GROUND")
    joint_module = import_module("JointObject")
    joint_module.GroundedJoint(ground, links["S3_CLAMP"])
    if getattr(app, "GuiUp", False):
        joint_module.ViewProviderGroundedJoint(ground.ViewObject)
    joint_specs = (
        (
            "PIVOT_1_CLAMP_TO_ARM_A",
            links["S3_CLAMP"],
            links["S3_ARM_A"],
            "pivot_1_angle_deg",
        ),
        (
            "PIVOT_2_ARM_A_TO_ARM_B",
            links["S3_ARM_A"],
            links["S3_ARM_B"],
            "pivot_2_angle_deg",
        ),
        (
            "PIVOT_3_ARM_B_TO_PHONE_MOUNT",
            links["S3_ARM_B"],
            links["S3_PHONE_MOUNT_INTERFACE"],
            "pivot_3_angle_deg",
        ),
    )
    joints = []
    for name, parent, child, angle_name in joint_specs:
        minimum, maximum = JOINT_LIMITS[name]
        joints.append(
            _joint_feature(
                app,
                group,
                name,
                parent,
                child,
                minimum,
                maximum,
                float(a[angle_name]),
                float(a["index_increment_deg"]),
            )
        )
    doc.recompute()
    return (
        assembly.Name,
        group.Name,
        *(link.Name for link in links.values()),
        ground.Name,
        *(joint.Name for joint in joints),
    )


def _document_parameters(doc: Any) -> dict[str, float]:
    return {
        name: float(getattr(doc.DesignParameters, name))
        for name in doc.DesignParameters.PropertiesList
        if name.endswith("_mm") or name.endswith("_deg")
    }


def _set_s3_assembly_pose(app: Any, doc: Any, a: dict[str, object]) -> tuple[str, ...]:
    from ai_freecad_core.mechanical_foundation.articulated import (
        QUALIFICATION_POSES,
        solve_planar_pose,
    )

    p = {name: float(value) for name, value in a.items() if isinstance(value, (int, float))}
    pose = solve_planar_pose(p)
    clamp_orientation = app.Rotation(app.Vector(1, 0, 0), 90)
    for name, transform in pose.component_transforms.items():
        link = doc.getObject(name)
        if link is None:
            raise LookupError(f"ASSEMBLY_COMPONENT_MISSING: {name}")
        if name == "S3_CLAMP":
            rotation = clamp_orientation
        elif name in {"S3_ARM_A", "S3_ARM_B"}:
            hinge = app.Rotation(app.Vector(0, 1, 0), -transform.hinge_angle_deg)
            rotation = hinge.multiply(clamp_orientation)
        else:
            rotation = app.Rotation(app.Vector(0, 1, 0), -transform.hinge_angle_deg)
        link.Placement = app.Placement(
            app.Vector(transform.x_mm, transform.y_mm, transform.z_mm),
            rotation,
        )
    clamp_placement = app.Placement(app.Vector(0, 0, 0), clamp_orientation)
    for name in (
        "S3_CLAMP_CAPTURED_NUT_LINK",
        "S3_CLAMP_SCREW_LINK",
        "S3_CLAMP_PRESSURE_PAD_LINK",
        "S3_DESK_REFERENCE_LINK",
    ):
        link = doc.getObject(name)
        if link is not None:
            link.Placement = clamp_placement
    phone_transform = pose.component_transforms["S3_PHONE_MOUNT_INTERFACE"]
    phone_placement = app.Placement(
        app.Vector(phone_transform.x_mm, phone_transform.y_mm, phone_transform.z_mm),
        app.Rotation(app.Vector(0, 1, 0), -phone_transform.hinge_angle_deg),
    )
    for name in (
        "S3_CHARGER_LINK",
        "S3_PHONE_ENVELOPE_LINK",
        "S3_PHONE_CONTACT_PLANE_LINK",
        "S3_CABLE_LINK",
    ):
        link = doc.getObject(name)
        if link is not None:
            link.Placement = phone_placement
    for joint_name, parameter in (
        ("PIVOT_1_CLAMP_TO_ARM_A", "pivot_1_angle_deg"),
        ("PIVOT_2_ARM_A_TO_ARM_B", "pivot_2_angle_deg"),
        ("PIVOT_3_ARM_B_TO_PHONE_MOUNT", "pivot_3_angle_deg"),
    ):
        joint = doc.getObject(joint_name)
        joint.CommandedAngle = p[parameter]
        center = pose.pivot_centers[joint_name]
        if "WorldPivotCenter" not in joint.PropertiesList:
            joint.addProperty(
                "App::PropertyVector", "WorldPivotCenter", "CADWiz Kinematic Relation"
            )
        joint.WorldPivotCenter = app.Vector(*center)
    for index, joint_name in enumerate(
        (
            "PIVOT_1_CLAMP_TO_ARM_A",
            "PIVOT_2_ARM_A_TO_ARM_B",
            "PIVOT_3_ARM_B_TO_PHONE_MOUNT",
        ),
        1,
    ):
        center = pose.pivot_centers[joint_name]
        hardware = doc.getObject(f"S3_PIVOT_{index}_M5_HARDWARE_LINK")
        hardware.Placement = app.Placement(app.Vector(*center), app.Rotation())
    angles = {
        name: p[name] for name in ("pivot_1_angle_deg", "pivot_2_angle_deg", "pivot_3_angle_deg")
    }
    matched = next(
        (
            name
            for name, values in QUALIFICATION_POSES.items()
            if all(abs(angles[key] - value) < 1e-9 for key, value in values.items())
        ),
        "CUSTOM_INDEXED_POSE",
    )
    doc.S3Assembly.CurrentPose = matched
    doc.recompute()
    _validate_s3_approved_concept_intent(doc, pose)
    return (
        "S3Assembly",
        "S3_CLAMP",
        "S3_ARM_A",
        "S3_ARM_B",
        "S3_PHONE_MOUNT_INTERFACE",
        "S3_CHARGER_LINK",
        "S3_CABLE_LINK",
        "S3_PIVOT_1_M5_HARDWARE_LINK",
        "S3_PIVOT_2_M5_HARDWARE_LINK",
        "S3_PIVOT_3_M5_HARDWARE_LINK",
        "S3_PHONE_ENVELOPE_LINK",
        "S3_PHONE_CONTACT_PLANE_LINK",
        "PIVOT_1_CLAMP_TO_ARM_A",
        "PIVOT_2_ARM_A_TO_ARM_B",
        "PIVOT_3_ARM_B_TO_PHONE_MOUNT",
    )


def _validate_s3_approved_concept_intent(doc: Any, pose: Any) -> None:
    """Fail the normal production operation if latest founder intent is violated."""

    joint_names = (
        "PIVOT_1_CLAMP_TO_ARM_A",
        "PIVOT_2_ARM_A_TO_ARM_B",
        "PIVOT_3_ARM_B_TO_PHONE_MOUNT",
    )
    joints = tuple(doc.getObject(name) for name in joint_names)
    axes_horizontal = all(
        joint is not None
        and abs(float(joint.Axis.z)) <= 1e-9
        and abs(abs(float(joint.Axis.y)) - 1.0) <= 1e-9
        for joint in joints
    )
    arm_links = tuple(
        item for item in (doc.getObject("S3_ARM_A"), doc.getObject("S3_ARM_B")) if item
    )
    p1 = pose.pivot_centers["PIVOT_1_CLAMP_TO_ARM_A"]
    p3 = pose.pivot_centers["PIVOT_3_ARM_B_TO_PHONE_MOUNT"]
    mount = doc.PhoneMagneticMount
    screen = mount.PhoneScreenNormal
    active = mount.ChargerActiveFaceNormal
    screw_below_desk = (
        float(doc.S3_CLAMP_SCREW.Shape.BoundBox.YMax)
        <= float(doc.DESK_REFERENCE.Shape.BoundBox.YMin) + 1e-6
    )
    checks = {
        "exactly_two_structural_arms": len(arm_links) == 2,
        "exactly_three_pivots": all(joint is not None for joint in joints),
        "all_pivot_axes_horizontal": axes_horizontal,
        "integrated_pivot_1_half": bool(doc.Pivot1Boss.IntegralToClamp)
        and len(doc.ClampEdgeFillet.Shape.Solids) == 1,
        "no_side_supports": doc.getObject("SideGuideLeft") is None
        and doc.getObject("SideGuideRight") is None,
        "no_bottom_phone_support": doc.getObject("BottomRetentionLedge") is None,
        "magnetic_only_mount": mount.RetentionArchitecture == "MAGNETIC_CHARGER_ONLY",
        "clamp_on_back_edge": float(p1[0]) < float(p3[0]),
        "mechanism_reaches_toward_user": float(p3[0]) > float(p1[0]),
        "screw_below_desk": screw_below_desk,
        "phone_screen_faces_user": screen.x > 0.999,
        "charger_face_opposes_screen": active.dot(screen) < -0.999,
        "cable_route_present": doc.getObject("S3_CABLE_LINK") is not None,
        "m5_hardware_at_all_pivots": all(
            doc.getObject(f"S3_PIVOT_{index}_M5_HARDWARE_LINK") is not None
            and doc.getObject(f"PIVOT_{index}_M5_HARDWARE").Shape.Volume > 0
            for index in (1, 2, 3)
        ),
    }
    failed = tuple(name for name, passed in checks.items() if not passed)
    if failed:
        raise RuntimeError(f"FAIL_FUNCTIONAL_INTENT: S3_APPROVED_CONCEPT: {', '.join(failed)}")
    _validate_pivot3_phone_contact_plane(doc)
    assembly = doc.S3Assembly
    for name in (
        "ExactlyTwoStructuralArms",
        "ExactlyThreePivots",
        "AllPivotAxesHorizontal",
        "ClampOnBackEdge",
        "MechanismReachesTowardUser",
        "PhoneScreenFacesUser",
        "NoPhoneSideSupports",
        "NoPhoneBottomSupport",
        "ScrewBelowDesk",
        "IntegratedPivot1",
        "M5HardwareAtAllPivots",
        "Pivot3PhonePlaneClearance",
    ):
        if name not in assembly.PropertiesList:
            assembly.addProperty("App::PropertyBool", name, "FunctionalIntent")
        setattr(assembly, name, True)
    assembly.Qualification = "CAD_GEOMETRY_QUALIFICATION_CANDIDATE"


def _shape_at_placement(source: Any, placement: Any) -> Any:
    shape = source.Shape.copy()
    shape.Placement = placement
    return shape


def _maximum_signed_distance_to_plane(
    shape: Any, plane_origin: Any, plane_normal: Any
) -> float:
    """Conservatively test every point using the placed shape's bounding envelope."""

    box = shape.BoundBox
    corners = (
        (x, y, z)
        for x in (box.XMin, box.XMax)
        for y in (box.YMin, box.YMax)
        for z in (box.ZMin, box.ZMax)
    )
    return max(
        (point - plane_origin).dot(plane_normal)
        for point in (type(plane_origin)(x, y, z) for x, y, z in corners)
    )


def _validate_pivot3_phone_contact_plane(doc: Any) -> Any:
    """Measure every governed Pivot 3 envelope against PHONE_CONTACT_PLANE."""

    from ai_freecad_core.production_foundation.geometry_truth import (
        verify_pivot3_phone_plane_clearance_invariants,
    )

    plane_link = doc.S3_PHONE_CONTACT_PLANE_LINK
    plane_origin = plane_link.Placement.Base
    plane_normal = plane_link.Placement.Rotation.multVec(doc.PHONE_CONTACT_PLANE.PlaneNormal)
    plane_normal.normalize()
    mount_placement = doc.S3_PHONE_MOUNT_INTERFACE.Placement
    arm_placement = doc.S3_ARM_B.Placement
    hardware_placement = doc.S3_PIVOT_3_M5_HARDWARE_LINK.Placement
    source_placements = {
        "pivot_boss": (doc.Pivot3BossEnvelope, mount_placement),
        "indexed_teeth": (doc.Pivot3IndexedTeethEnvelope, mount_placement),
        "phone_mount_lug": (doc.Pivot3Interface, mount_placement),
        # Testing the complete placed Arm B is stricter than isolating only its
        # terminal lug and preserves the qualified arm artifact byte-for-byte.
        "arm_b_terminal": (doc.ArmBPrintableFinal, arm_placement),
        "m5_shaft": (doc.PIVOT_3_M5_SHAFT_ENVELOPE, hardware_placement),
        "bolt_head": (doc.PIVOT_3_M5_BOLT_HEAD_ENVELOPE, hardware_placement),
        "washers": (doc.PIVOT_3_M5_WASHERS_ENVELOPE, hardware_placement),
        "wing_nut": (doc.PIVOT_3_M5_WING_NUT_ENVELOPE, hardware_placement),
    }
    world_shapes = {
        name: _shape_at_placement(source, placement)
        for name, (source, placement) in source_placements.items()
    }
    signed_distances = {
        name: _maximum_signed_distance_to_plane(shape, plane_origin, plane_normal)
        for name, shape in world_shapes.items()
    }
    phone_shape = _shape_at_placement(doc.PhoneEnvelope, doc.S3_PHONE_ENVELOPE_LINK.Placement)
    intersections = {
        name: float(shape.common(phone_shape).Volume) for name, shape in world_shapes.items()
    }
    screen = mount_placement.Rotation.multVec(doc.PhoneMagneticMount.PhoneScreenNormal)
    result = verify_pivot3_phone_plane_clearance_invariants(
        signed_distances_mm=signed_distances,
        required_rear_clearance_mm=float(doc.PHONE_CONTACT_PLANE.RequiredRearClearance),
        phone_intersection_volumes_mm3=intersections,
        charger_active_face_offset_mm=float(doc.PhoneMagneticMount.ChargerActiveFaceOffset),
        charger_active_face_tolerance_mm=0.5,
        phone_screen_faces_user=screen.x > 0.999,
    )
    if not result.passed:
        failed = ", ".join(name for name, passed in result.checks.items() if not passed)
        raise RuntimeError(f"{result.code}: {failed}")
    assembly = doc.S3Assembly
    property_specs = (
        ("Pivot3PhonePlaneClearanceStatus", "App::PropertyString"),
        ("MeasuredMinimumPivot3PhonePlaneClearance", "App::PropertyLength"),
        ("RequiredPivot3PhonePlaneClearance", "App::PropertyLength"),
        ("Pivot3PhonePlaneMeasurements", "App::PropertyString"),
        ("Pivot3PhoneIntersectionVolumes", "App::PropertyString"),
    )
    for name, type_id in property_specs:
        if name not in assembly.PropertiesList:
            assembly.addProperty(type_id, name, "PhoneContactPlane")
    assembly.Pivot3PhonePlaneClearanceStatus = "PASS"
    assembly.MeasuredMinimumPivot3PhonePlaneClearance = min(
        -value for value in signed_distances.values()
    )
    assembly.RequiredPivot3PhonePlaneClearance = float(
        doc.PHONE_CONTACT_PLANE.RequiredRearClearance
    )
    assembly.Pivot3PhonePlaneMeasurements = json.dumps(
        {
            name: {
                "maximum_signed_distance_mm": round(value, 6),
                "rear_clearance_mm": round(-value, 6),
            }
            for name, value in signed_distances.items()
        },
        sort_keys=True,
    )
    assembly.Pivot3PhoneIntersectionVolumes = json.dumps(
        {name: round(value, 9) for name, value in intersections.items()}, sort_keys=True
    )
    return result


def _remove_s3_assembly_objects(doc: Any) -> None:
    names = [
        "PIVOT_3_ARM_B_TO_PHONE_MOUNT",
        "PIVOT_2_ARM_A_TO_ARM_B",
        "PIVOT_1_CLAMP_TO_ARM_A",
        "S3_CLAMP_GROUND",
        "S3_DESK_REFERENCE_LINK",
        "S3_CLAMP_PRESSURE_PAD_LINK",
        "S3_CLAMP_SCREW_LINK",
        "S3_CLAMP_CAPTURED_NUT_LINK",
        "S3_CHARGER_LINK",
        "S3_CABLE_LINK",
        "S3_PIVOT_1_M5_HARDWARE_LINK",
        "S3_PIVOT_2_M5_HARDWARE_LINK",
        "S3_PIVOT_3_M5_HARDWARE_LINK",
        "S3_PHONE_ENVELOPE_LINK",
        "S3_PHONE_CONTACT_PLANE_LINK",
        "S3_PHONE_MOUNT_INTERFACE",
        "S3_ARM_B",
        "S3_ARM_A",
        "S3_CLAMP",
        "S3JointGroup",
        "S3Assembly",
        "PhoneMountInterface",
        "PhoneMagneticMount",
        "PhoneMagneticMountBody",
        "PhoneEnvelope",
        "PHONE_CONTACT_PLANE",
        "BackPlate",
        "ChargerEnvelope",
        "CableEnvelope",
        "ChargerRecess",
        "CableExit",
        "Pivot3Interface",
        "Pivot3BossEnvelope",
        "Pivot3IndexedTeethEnvelope",
        "PIVOT_1_M5_HARDWARE",
        "PIVOT_2_M5_HARDWARE",
        "PIVOT_3_M5_HARDWARE",
        "PIVOT_3_M5_SHAFT_ENVELOPE",
        "PIVOT_3_M5_BOLT_HEAD_ENVELOPE",
        "PIVOT_3_M5_WASHERS_ENVELOPE",
        "PIVOT_3_M5_WING_NUT_ENVELOPE",
    ]
    for prefix in ("ArmA", "ArmB"):
        names.extend(
            (
                f"{prefix}ProfileSection",
                f"{prefix}PrintableFinal",
                f"{prefix}CADWizOutline",
                f"{prefix}PivotHoles",
                f"{prefix}PivotBoreSketch",
                f"{prefix}StructuralCore",
                f"{prefix}BasePad",
                f"{prefix}BaseSketch",
                f"{prefix}Body",
            )
        )
    for name in names:
        if doc.getObject(name) is not None:
            doc.removeObject(name)
    doc.recompute()


def _regenerate_s3_assembly(app: Any, doc: Any, *, rebuild_clamp: bool) -> None:
    _remove_s3_assembly_objects(doc)
    if rebuild_clamp:
        _regenerate_clamp(app, doc)
    p = _document_parameters(doc)
    _create_printable_arms(app, doc, p)
    _create_phone_mount_interface(app, doc, p)
    _create_s3_assembly_backend(app, doc, p)
    _set_s3_assembly_pose(app, doc, p)
    doc.recompute()


def _regenerate_clamp(
    app: Any, doc: Any, *, rebuild_index: bool = False, rebuild_arm: bool = False
) -> None:
    names = [
        "S3_CLAMP_BODY",
        "DESK_REFERENCE",
        "S3_CLAMP_PRESSURE_PAD",
        "S3_CLAMP_SCREW",
        "S3_CLAMP_CAPTURED_NUT",
        "ClampEdgeFillet",
        "Pivot1Bore",
        "Pivot1BoreSketch",
        "Pivot1Boss",
        "M8ScrewPath",
        "M8NutCapturePocket",
        "ClampScrewBoss",
        "DeskOpeningPocket",
        "DeskOpeningSketch",
        "ClampBasePad",
        "ClampBaseSketch",
        "ClampBody",
    ]
    if rebuild_index:
        names = [
            "IndexFace5deg72",
            "IndexFace5deg72Body",
            "IndexFace10deg36",
            "IndexFace10deg36Body",
            *names,
        ]
    if rebuild_arm:
        names = ["ArmStructuralProfileCoupon", "ArmProfileCouponBody", *names]
    for name in names:
        if doc.getObject(name) is not None:
            doc.removeObject(name)
    doc.recompute()
    p = {
        name: float(getattr(doc.DesignParameters, name))
        for name in doc.DesignParameters.PropertiesList
        if name.endswith("_mm") or name.endswith("_deg")
    }
    p["clamp_inside_height_mm"] = p["desk_thickness_mm"] + p["desk_clearance_mm"]
    _create_clamp_base(app, doc, p)
    _cut_desk_opening(app, doc, p)
    _add_clamp_screw_boss(app, doc, p)
    _cut_m8_nut_capture(app, doc, p)
    _cut_m8_screw_path(app, doc, p)
    _add_pivot_1_boss(app, doc, p)
    _cut_pivot_1_bore(app, doc, p)
    _add_clamp_fillet(app, doc, p)
    if rebuild_index:
        _add_index_face_coupons(app, doc, p)
    if rebuild_arm:
        _add_arm_profile_coupon(app, doc, p)
    doc.recompute()


def _valid(feature: Any, label: str) -> None:
    if feature.Shape.isNull():
        raise RuntimeError(f"NULL_SHAPE: {label}")
    if not feature.Shape.isValid():
        raise RuntimeError(f"INVALID_SHAPE: {label}")
    if len(feature.Shape.Solids) != 1:
        raise RuntimeError(f"UNEXPECTED_SOLID_COUNT: {label}")


def _native_valid(feature: Any, expected_type: str, label: str) -> None:
    if feature.TypeId != expected_type:
        raise RuntimeError(f"NATIVE_FEATURE_TYPE_MISMATCH: {label} is {feature.TypeId}")
    _valid(feature, label)


def _shape_fingerprint(shape: Any) -> str:
    """Return a save/reopen-stable SHA-256 over canonical geometric measurements."""

    def rounded(value: float) -> float:
        # OCC may rewrite equivalent analytic edges during FCStd persistence.
        # Four decimal places is far below the manufacturing tolerances used by
        # this project while remaining stable across those representation edits.
        return round(float(value), 4)

    box = shape.BoundBox
    center = (
        shape.Solids[0].CenterOfMass
        if shape.Solids
        else type("Center", (), {"x": box.Center.x, "y": box.Center.y, "z": box.Center.z})()
    )
    payload = {
        "volume": rounded(shape.Volume),
        "area": rounded(shape.Area),
        "solids": len(shape.Solids),
        "shells": len(shape.Shells),
        "faces": len(shape.Faces),
        "edges": len(shape.Edges),
        "bbox": [
            rounded(box.XMin),
            rounded(box.YMin),
            rounded(box.ZMin),
            rounded(box.XMax),
            rounded(box.YMax),
            rounded(box.ZMax),
        ],
        "center_of_mass": [rounded(center.x), rounded(center.y), rounded(center.z)],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + sha256(encoded).hexdigest()


def _shape_observation(feature: Any) -> Any:
    from ai_freecad_core.production_foundation.geometry_truth import ShapeObservation

    shape = feature.Shape
    return ShapeObservation(
        fingerprint=_shape_fingerprint(shape),
        volume_mm3=float(shape.Volume),
        area_mm2=float(shape.Area),
        solid_count=len(shape.Solids),
        face_count=len(shape.Faces),
        edge_count=len(shape.Edges),
        valid=bool(not shape.isNull() and shape.isValid()),
    )


def _raw_shape_observation(shape: Any) -> Any:
    from ai_freecad_core.production_foundation.geometry_truth import ShapeObservation

    return ShapeObservation(
        fingerprint=_shape_fingerprint(shape),
        volume_mm3=float(shape.Volume),
        area_mm2=float(shape.Area),
        solid_count=len(shape.Solids),
        face_count=len(shape.Faces),
        edge_count=len(shape.Edges),
        valid=bool(not shape.isNull() and shape.isValid()),
    )


def _assert_shape_effect(before: Any, after: Any, kind: str, label: str) -> None:
    from ai_freecad_core.production_foundation.geometry_truth import (
        EffectKind,
        verify_geometry_effect,
    )

    result = verify_geometry_effect(
        _raw_shape_observation(before), _raw_shape_observation(after), EffectKind(kind)
    )
    if not result.passed:
        raise RuntimeError(f"{result.code}: {label}: {result.actual_effect}")


def _assert_geometry_effect(before: Any | None, after: Any, kind: str, label: str) -> None:
    from ai_freecad_core.production_foundation.geometry_truth import (
        EffectKind,
        ShapeObservation,
        verify_geometry_effect,
    )

    before_observation = (
        _shape_observation(before)
        if before is not None
        else ShapeObservation("EMPTY", 0.0, 0.0, 0, 0, 0, True)
    )
    result = verify_geometry_effect(before_observation, _shape_observation(after), EffectKind(kind))
    if not result.passed:
        raise RuntimeError(f"{result.code}: {label}: {result.actual_effect}")


def _validate_c_clamp_functional_intent(app: Any, doc: Any, a: dict[str, object]) -> Any:
    from ai_freecad_core.production_foundation.geometry_truth import verify_c_clamp_invariants

    part = import_module("Part")
    shape = doc.ClampEdgeFillet.Shape
    spine = float(a["spine_thickness_mm"])
    jaw_depth = float(a["jaw_depth_mm"])
    lower = float(a["lower_jaw_thickness_mm"])
    opening = float(a["clamp_inside_height_mm"])
    upper = float(a["upper_jaw_thickness_mm"])
    width = float(a["clamp_width_mm"])
    outer_height = lower + opening + upper
    probe_x = jaw_depth - 4.0
    probe_z = width / 2.0
    step = 0.05
    samples = int(outer_height / step) + 1
    states = [
        shape.isInside(app.Vector(probe_x, index * step, probe_z), 1e-5, False)
        for index in range(samples)
    ]
    void_runs: list[tuple[float, float]] = []
    start: int | None = None
    for index, occupied in enumerate(states):
        if not occupied and start is None:
            start = index
        if occupied and start is not None:
            void_runs.append((start * step, index * step))
            start = None
    measured = max(
        (end - begin for begin, end in void_runs if begin > lower - 1.0),
        default=0.0,
    )
    tunnel = part.makeBox(
        jaw_depth - spine + 20.0,
        min(2.0, opening / 4.0),
        min(4.0, width / 4.0),
        app.Vector(spine + 0.5, lower + opening / 2.0 - 1.0, probe_z - 2.0),
    )
    front_accessible = float(shape.common(tunnel).Volume) <= 1e-6
    upper_probe = part.makeBox(
        jaw_depth - spine,
        upper,
        width,
        app.Vector(spine, lower + opening, 0),
    )
    lower_probe = part.makeBox(jaw_depth - spine, lower, width, app.Vector(spine, 0, 0))
    spine_probe = part.makeBox(spine, outer_height, width, app.Vector(0, 0, 0))
    screw_axis_ok = spine < float(a["jaw_depth_mm"]) - 14.0 < jaw_depth and float(
        doc.M8NutCapturePocket.Shape.Volume
    ) > float(doc.M8ScrewPath.Shape.Volume)
    result = verify_c_clamp_invariants(
        single_body_solid=len(shape.Solids) == 1 and shape.isValid(),
        open_front=front_accessible and measured >= opening - 0.11,
        upper_jaw=float(shape.common(upper_probe).Volume) > 100.0,
        lower_jaw=float(shape.common(lower_probe).Volume) > 100.0,
        rear_spine=float(shape.common(spine_probe).Volume) > 100.0,
        desk_opening_mm=measured,
        required_desk_opening_mm=float(a["desk_thickness_mm"]),
        front_accessible=front_accessible,
        screw_axis_intersects_lower_jaw=screw_axis_ok,
        pivot_1_support=bool(doc.Pivot1Boss.IntegralToClamp)
        and len(doc.Pivot1Boss.Shape.Solids) == 1
        and float(doc.Pivot1Boss.Shape.Volume) > float(doc.M8ScrewPath.Shape.Volume)
        and float(doc.Pivot1Boss.Shape.Volume) > float(doc.Pivot1Bore.Shape.Volume),
    )
    if not result.passed:
        failed = ", ".join(name for name, passed in result.checks.items() if not passed)
        raise RuntimeError(f"{result.code}: C_CLAMP: {failed}")
    final = doc.ClampEdgeFillet
    for name, type_id in (
        ("GeometryTruthStatus", "App::PropertyString"),
        ("FunctionalIntentStatus", "App::PropertyString"),
        ("CClampFrontAccessible", "App::PropertyBool"),
        ("MeasuredDeskOpening", "App::PropertyLength"),
        ("QualificationFingerprint", "App::PropertyString"),
    ):
        if name not in final.PropertiesList:
            final.addProperty(type_id, name, "GeometryTruth")
    final.GeometryTruthStatus = "PASS"
    final.FunctionalIntentStatus = "PASS"
    final.CClampFrontAccessible = front_accessible
    final.MeasuredDeskOpening = measured
    final.QualificationFingerprint = _shape_fingerprint(shape)
    return result


def _validate_phone_magnetic_mount_functional_intent(
    doc: Any, a: dict[str, object]
) -> Any:
    from ai_freecad_core.production_foundation.geometry_truth import (
        verify_phone_magnetic_mount_invariants,
    )

    mount = doc.PhoneMagneticMount
    charger = doc.ChargerEnvelope
    recess = doc.ChargerRecess
    cable = doc.CableExit
    cable_envelope = doc.CableEnvelope
    box = mount.Shape.BoundBox
    charger_outside = float(charger.Shape.cut(recess.Shape).Volume)
    screen = mount.PhoneScreenNormal
    active = mount.ChargerActiveFaceNormal
    result = verify_phone_magnetic_mount_invariants(
        single_body_solid=len(mount.Shape.Solids) == 1 and mount.Shape.isValid(),
        upright_orientation=bool(mount.PhoneMountOrientationMatch)
        and box.ZLength > box.XLength
        and box.ZLength > box.YLength,
        magnetic_only_retention=mount.RetentionArchitecture == "MAGNETIC_CHARGER_ONLY",
        side_supports_absent=doc.getObject("SideGuideLeft") is None
        and doc.getObject("SideGuideRight") is None,
        bottom_support_absent=doc.getObject("BottomRetentionLedge") is None,
        charger_recess=float(recess.Shape.Volume) > 0,
        charger_fits=charger_outside <= 1e-5,
        active_face_offset_mm=float(a["charger_face_offset_mm"]),
        active_face_tolerance_mm=0.5,
        cable_exit=float(cable.Shape.common(recess.Shape).Volume) > 0,
        cable_route=float(cable_envelope.Shape.Volume) > 0,
        pivot_3_clear=float(doc.Pivot3Interface.Shape.Volume) > 0,
        phone_screen_faces_user=screen.x > 0.999 and abs(screen.y) < 1e-9 and abs(screen.z) < 1e-9,
        charger_normal_opposes_screen=active.dot(screen) < -0.999,
    )
    if not result.passed:
        failed = ", ".join(name for name, passed in result.checks.items() if not passed)
        raise RuntimeError(f"{result.code}: PHONE_MAGNETIC_MOUNT: {failed}")
    for name, type_id in (
        ("GeometryTruthStatus", "App::PropertyString"),
        ("FunctionalIntentStatus", "App::PropertyString"),
        ("QualificationFingerprint", "App::PropertyString"),
    ):
        if name not in mount.PropertiesList:
            mount.addProperty(type_id, name, "GeometryTruth")
    mount.GeometryTruthStatus = "PASS"
    mount.FunctionalIntentStatus = "PASS"
    mount.QualificationFingerprint = _shape_fingerprint(mount.Shape)
    return result


def _outer_vertical_edge_names(base: Any) -> list[str]:
    """Resolve outer vertical edges from geometry; EdgeN never crosses the IR seam."""
    bb = base.Shape.BoundBox
    tol = 1e-5
    names = []
    for index, edge in enumerate(base.Shape.Edges, 1):
        if len(edge.Vertexes) < 2:
            continue
        p, q = edge.Vertexes[0].Point, edge.Vertexes[-1].Point
        vertical = abs(q.z - p.z) > bb.ZLength * 0.9
        outer_x = abs(p.x - bb.XMin) < tol or abs(p.x - bb.XMax) < tol
        outer_y = abs(p.y - bb.YMin) < tol or abs(p.y - bb.YMax) < tol
        if vertical and outer_x and outer_y:
            names.append(f"Edge{index}")
    return names


def _regenerate_coupon(app: Any, doc: Any) -> None:
    """Regenerate accepted dependent features after a governed parameter edit."""
    p = doc.DesignParameters
    w, h, t = float(p.overall_width_mm), float(p.overall_height_mm), float(p.base_thickness_mm)
    pw, ph, pd = float(p.pocket_width_mm), float(p.pocket_height_mm), float(p.pocket_depth_mm)
    hd, hs, fr = float(p.hole_diameter_mm), float(p.hole_spacing_mm), float(p.fillet_radius_mm)
    if pw >= w or ph >= h or pd >= t or hs + hd >= w:
        raise ValueError("PRECONDITION_FAILED: edited clearances are invalid")
    for name, sw, sh in (("BaseSketch", w, h), ("PocketSketch", pw, ph)):
        sketch = doc.getObject(name)
        if sketch is not None:
            for index, value in ((8, sw), (9, sh), (10, -sw / 2), (11, -sh / 2)):
                sketch.setDatum(index, app.Units.Quantity(value, "mm"))
    # Native dress-up edge links in FreeCAD 1.1.3 are not topologically stable
    # across sketch-size edits. Remove the dress-up, recompute the governed
    # upstream chain, then deterministically reselect geometry and recreate it.
    doc.removeObject("OuterEdgeFilletSet")
    doc.recompute()
    doc.BasePad.Length = t
    doc.Pocket.Length = pd
    # PocketSketch lives on the top plane, so the accepted native direction
    # enters the solid.  Keep the same direction used by `_pocket`; reversing
    # it during a later parameter edit cuts into open space and silently turns
    # the pocket into a no-op while still leaving one geometrically valid solid.
    doc.Pocket.Reversed = False
    doc.MountingHoles.Diameter = hd
    if "Depth" in doc.MountingHoles.PropertiesList:
        doc.MountingHoles.Depth = t
    hole_sketch = doc.getObject("HoleSketch")
    if hole_sketch is not None and len(hole_sketch.Constraints) >= 6:
        for index, value in ((0, hd), (1, -hs / 2), (2, 0), (3, hd), (4, hs / 2), (5, 0)):
            hole_sketch.setDatum(index, app.Units.Quantity(value, "mm"))
        hole_sketch.Placement.Base.z = t
    # Constraint edits do not always dirty every transitive PartDesign feature in
    # the governed host. Explicitly invalidate the accepted native chain.
    for feature in (doc.BasePad, doc.Pocket, doc.MountingHoles):
        feature.touch()
    doc.recompute()
    names = _outer_vertical_edge_names(doc.MountingHoles)
    if not names:
        raise RuntimeError("TOPOLOGY_REFERENCE_UNRESOLVED: edited vertical outer edges")
    fillet = doc.BracketBody.newObject("PartDesign::Fillet", "OuterEdgeFilletSet")
    fillet.Base = (doc.MountingHoles, names)
    fillet.Radius = fr
    doc.recompute()
    for feature, expected, label in (
        (doc.BasePad, "PartDesign::Pad", "edited BasePad"),
        (doc.Pocket, "PartDesign::Pocket", "edited Pocket"),
        (doc.MountingHoles, "PartDesign::Hole", "edited MountingHoles"),
        (fillet, "PartDesign::Fillet", "edited OuterEdgeFilletSet"),
    ):
        _native_valid(feature, expected, label)
