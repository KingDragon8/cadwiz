# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""M2b: thin tools for the one genuine gap the founder's Group 1 priority
order surfaced -- everything else in that group (linear/polar pattern,
shell/thickness, revolve, mirror) already has a vendored tool and needed only
qualification, not new code (see `docs/reports/2026-09-08-roadmap-status.md`,
"M2b in progress").

**`create_hole` does not actually support counterbore/countersink**, despite
`docs/reports/2026-09-07-capability-inventory.md`'s claim that it "already
supports through/counterbore/countersink/threaded in one tool." Read
directly: `vendor/robust-mcp/src/freecad_mcp/tools/partdesign.py`'s
`create_hole` only ever sets `hole.Profile`, `.Depth`, `.DepthType`,
`.Threaded`, `.ThreadType`/`.ThreadSize`, `.Diameter` -- it never touches
`HoleCutType`, `HoleCutDiameter`, `HoleCutDepth`, or
`HoleCutCountersinkAngle`, which is what real FreeCAD 1.1.3's
`PartDesign::Hole` actually uses to select a counterbore or countersink
(confirmed 2026-09-08 by direct property inspection: `HoleCutType`'s enum is
`['None', 'Counterbore', 'Countersink', 'Counterdrill']`). The inventory's
claim was wrong, not fixed here (`vendor/` is never edited in place) --
this tool fills the actual gap.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable


def register_m2b_tools(mcp: Any, get_bridge: Callable[[], Awaitable[Any]]) -> None:
    """Register the M2b hole-cut-type tool onto `mcp`."""

    @mcp.tool()
    async def create_hole_advanced(
        sketch_name: str,
        diameter: float,
        depth: float,
        cut_type: str = "None",
        cut_diameter: float = 0.0,
        cut_depth: float = 0.0,
        countersink_angle: float = 90.0,
        hole_type: str = "Dimension",
        name: str | None = None,
        doc_name: str | None = None,
    ) -> dict[str, Any]:
        """Create a PartDesign hole with a real counterbore or countersink.

        `create_hole` (one of the 152 vendored tools) makes a plain
        cylindrical hole only -- see this module's docstring for the
        confirmed gap. This tool sets the properties that actually control
        the cut shape.

        Args:
            sketch_name: Name of the sketch with hole center point(s).
            diameter: Through-hole diameter, in millimetres.
            depth: Hole depth, in millimetres (ignored if hole_type is
                "ThroughAll").
            cut_type: "None" (plain hole), "Counterbore", "Countersink", or
                "Counterdrill".
            cut_diameter: Counterbore/counterdrill diameter (ignored for
                "None"/"Countersink"), in millimetres.
            cut_depth: Counterbore/counterdrill recess depth (ignored for
                "None"/"Countersink"), in millimetres.
            countersink_angle: Countersink included angle, in degrees
                (ignored unless cut_type is "Countersink").
            hole_type: Hole depth type: "Dimension", "ThroughAll", or
                "UpToFirst" -- same vocabulary as create_hole.
            name: Hole feature name. Auto-generated if None.
            doc_name: Document containing the sketch. Active document if None.

        Returns:
            name, label, type_id, hole_cut_type of the created feature.
        """
        if cut_type not in ("None", "Counterbore", "Countersink", "Counterdrill"):
            raise ValueError(
                f"cut_type must be one of None/Counterbore/Countersink/Counterdrill, got {cut_type!r}"
            )
        bridge = await get_bridge()
        code = f"""
doc = FreeCAD.ActiveDocument if {doc_name!r} is None else FreeCAD.getDocument({doc_name!r})
if doc is None:
    raise ValueError("No document found")

sketch = doc.getObject({sketch_name!r})
if sketch is None:
    raise ValueError(f"Sketch not found: {sketch_name!r}")

body = None
for obj in doc.Objects:
    if obj.TypeId == "PartDesign::Body" and hasattr(obj, "Group") and sketch in obj.Group:
        body = obj
        break
if body is None:
    raise ValueError("Sketch must be inside a PartDesign Body for Hole operation")

hole = body.newObject("PartDesign::Hole", {name!r} or "Hole")
hole.Profile = sketch
hole.Diameter = {diameter}
hole.Depth = {depth}
hole_type = {hole_type!r}
if hole_type == "ThroughAll":
    hole.DepthType = 1
elif hole_type == "UpToFirst":
    hole.DepthType = 2
else:
    hole.DepthType = 0
hole.HoleCutType = {cut_type!r}
if {cut_type!r} in ("Counterbore", "Counterdrill"):
    hole.HoleCutDiameter = {cut_diameter}
    hole.HoleCutDepth = {cut_depth}
elif {cut_type!r} == "Countersink":
    hole.HoleCutDiameter = {cut_diameter}
    hole.HoleCutCountersinkAngle = {countersink_angle}
doc.recompute()

if hole.Shape is None or hole.Shape.isNull():
    raise ValueError(f"{{hole.Name}} produced a null shape after recompute")

_result_ = {{
    "name": hole.Name,
    "label": hole.Label,
    "type_id": hole.TypeId,
    "hole_cut_type": hole.HoleCutType,
}}
"""
        result = await bridge.execute_python(code)
        if result.success:
            return result.result
        raise ValueError(result.error_traceback or "create_hole_advanced failed")

    @mcp.tool()
    async def create_tube(
        outer_radius: float = 5.0,
        inner_radius: float = 2.0,
        height: float = 10.0,
        name: str | None = None,
        doc_name: str | None = None,
    ) -> dict[str, Any]:
        """Create a Part Tube (pipe) primitive -- outer cylinder minus inner.

        `Part_Tube` had no tool among the 152 vendored ones (coverage map,
        2026-09-07: "no create_tube; a plain pipe/tube is a common
        printable primitive"). FreeCAD's own `Part_Tube` GUI command is
        implemented as a genuinely parametric `Part::FeaturePython`
        (`BasicShapes.Shapes.addTube` -- confirmed 2026-09-08 by
        reading `Mod/Part/BasicShapes/Shapes.py` directly, not guessed):
        its own `execute()` re-derives the shape from `OuterRadius`/
        `InnerRadius`/`Height` on every recompute, exactly like a native
        PartDesign feature, not a one-time frozen shape -- this tool calls
        that same first-party FreeCAD constructor rather than reimplementing
        it.

        Args:
            outer_radius: Outer radius, in millimetres. Defaults to 5.0.
            inner_radius: Inner (bore) radius, in millimetres. Must be less
                than outer_radius. Defaults to 2.0.
            height: Tube height, in millimetres. Defaults to 10.0.
            name: Object name. Auto-generated if None.
            doc_name: Document to create the tube in. Active document if None.

        Returns:
            name, label, type_id, volume_mm3 of the created tube.
        """
        if inner_radius >= outer_radius:
            raise ValueError(f"inner_radius ({inner_radius}) must be less than outer_radius ({outer_radius})")
        bridge = await get_bridge()
        code = f"""
import BasicShapes.Shapes as Shapes

doc = FreeCAD.ActiveDocument if {doc_name!r} is None else FreeCAD.getDocument({doc_name!r})
if doc is None:
    raise ValueError("No document found")

tube = Shapes.addTube(doc, {name!r} or "Tube")
tube.OuterRadius = {outer_radius}
tube.InnerRadius = {inner_radius}
tube.Height = {height}
doc.recompute()

if tube.Shape is None or tube.Shape.isNull():
    raise ValueError(f"{{tube.Name}} produced a null shape after recompute")

_result_ = {{
    "name": tube.Name,
    "label": tube.Label,
    "type_id": tube.TypeId,
    "volume_mm3": tube.Shape.Volume,
}}
"""
        result = await bridge.execute_python(code)
        if result.success:
            return result.result
        raise ValueError(result.error_traceback or "create_tube failed")

    @mcp.tool()
    async def constrain_symmetric(
        sketch_name: str,
        geometry1: int,
        point1: int,
        geometry2: int,
        point2: int,
        symmetry_line_geometry: int,
        doc_name: str | None = None,
    ) -> dict[str, Any]:
        """Constrain two sketch points symmetric about a third (line) geometry.

        `add_sketch_constraint` (one of the 152 vendored tools) accepts
        `constraint_type="Symmetric"` in its documented options, but its own
        generated code references a bare name `geometry2` that was never
        assigned in that scope (the local variables are `g1, p1, g2, p2` --
        confirmed 2026-09-08: calling it raises `NameError: name 'geometry2'
        is not defined` from inside the tool's own generated code, every
        time). This tool implements the real three-geometry
        `Sketcher.Constraint('Symmetric', geoId1, posId1, geoId2, posId2,
        refGeoId)` call directly.

        Args:
            sketch_name: Name of the sketch.
            geometry1: Index of the first point's geometry.
            point1: Point position on geometry1 (1=start, 2=end, 3=center).
            geometry2: Index of the second point's geometry.
            point2: Point position on geometry2.
            symmetry_line_geometry: Index of the line geometry1/geometry2
                are made symmetric about.
            doc_name: Document containing the sketch. Active document if None.

        Returns:
            constraint_index, constraint_count.
        """
        bridge = await get_bridge()
        code = f"""
import Sketcher

doc = FreeCAD.ActiveDocument if {doc_name!r} is None else FreeCAD.getDocument({doc_name!r})
if doc is None:
    raise ValueError("No document found")

sketch = doc.getObject({sketch_name!r})
if sketch is None:
    raise ValueError(f"Sketch not found: {sketch_name!r}")

doc.openTransaction("Add Symmetric Constraint")
try:
    constraint = Sketcher.Constraint(
        "Symmetric", {geometry1}, {point1}, {geometry2}, {point2}, {symmetry_line_geometry}
    )
    idx = sketch.addConstraint(constraint)
    doc.recompute()
    doc.commitTransaction()
except Exception:
    doc.abortTransaction()
    raise

_result_ = {{
    "constraint_index": idx,
    "constraint_count": sketch.ConstraintCount,
}}
"""
        result = await bridge.execute_python(code)
        if result.success:
            return result.result
        raise ValueError(result.error_traceback or "constrain_symmetric failed")

    @mcp.tool()
    async def fillet_sketch_geometry(
        sketch_name: str,
        geometry: int,
        point: int,
        radius: float,
        doc_name: str | None = None,
    ) -> dict[str, Any]:
        """Round a corner between two connected sketch lines with an arc.

        Distinct from `fillet_edges` (one of the 152 vendored tools), which
        fillets a solid's 3D edges after a feature exists -- this fillets
        the 2D sketch geometry itself, before extrusion, using real
        FreeCAD's `Sketcher::SketchObject.fillet(geoId, posId, radius)`
        (confirmed 2026-09-08 by direct probing: the two lines meeting at
        `posId` must already be coincident at that vertex; the call replaces
        the shared corner with a tangent arc and does not need a second
        geometry index -- FreeCAD infers the other line from which one
        shares that vertex).

        Args:
            sketch_name: Name of the sketch.
            geometry: Index of one of the two lines meeting at the corner.
            point: Which end of `geometry` is the corner (1=start, 2=end).
            radius: Fillet radius, in millimetres.
            doc_name: Document containing the sketch. Active document if None.

        Returns:
            geometry_count_before, geometry_count_after (a fillet adds one
            arc geometry element), arc_index, arc_radius_mm,
            radius_constraint_index (the constraint that makes the radius
            editable afterward -- see below).
        """
        bridge = await get_bridge()
        code = f"""
import Sketcher

doc = FreeCAD.ActiveDocument if {doc_name!r} is None else FreeCAD.getDocument({doc_name!r})
if doc is None:
    raise ValueError("No document found")

sketch = doc.getObject({sketch_name!r})
if sketch is None:
    raise ValueError(f"Sketch not found: {sketch_name!r}")

before = sketch.GeometryCount
doc.openTransaction("Fillet Sketch Geometry")
try:
    sketch.fillet({geometry}, {point}, {radius})
    after = sketch.GeometryCount
    arc_index = after - 1
    # sketch.fillet() does not add a Radius constraint on its own
    # (confirmed 2026-09-08: the arc's own .Radius stays fixed at its
    # creation value and cannot be edited afterward without one -- there
    # is no setRadius() method, and mutating .Radius directly on the
    # geometry object does not stick). Adding it here is what makes the
    # result an editable parameter rather than a frozen initial value.
    radius_constraint_index = sketch.addConstraint(
        Sketcher.Constraint("Radius", arc_index, {radius})
    )
    doc.recompute()
    doc.commitTransaction()
except Exception:
    doc.abortTransaction()
    raise

arc = sketch.Geometry[arc_index]

_result_ = {{
    "geometry_count_before": before,
    "geometry_count_after": after,
    "arc_index": arc_index,
    "arc_radius_mm": arc.Radius,
    "radius_constraint_index": radius_constraint_index,
}}
"""
        result = await bridge.execute_python(code)
        if result.success:
            return result.result
        raise ValueError(result.error_traceback or "fillet_sketch_geometry failed")
