# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Layer 3 advanced verbs: thin, first-party tools for what the FreeCAD
coverage map (`docs/reports/2026-09-07-freecad-coverage.md`) found genuinely
missing from the 152 vendored tools, for a 3D-printer-owner persona.

Registered onto the same `FastMCP` instance as the 152 vendored tools and the
three M6 native tools, via `ToolInvoker._server()` -- no second invocation
route, matching `register_native_tools`'s own pattern in `native_tools.py`.
Each tool is a small, first-party Python snippet run through the bridge's
`execute_python`, exactly as `export_3mf_native`/`check_wall_thickness` are:
this is CADWiz's own code, not model-written, so it is not in scope for
`macro_guard`'s review gate (see that module's docstring on what it does and
does not stand in front of).

Never edits `vendor/`. Where a vendored tool already covers part of an
operation (e.g. `add_sketch_circle` for a helix's profile), these tools build
on it rather than duplicating it.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable


def register_layer3_tools(mcp: Any, get_bridge: Callable[[], Awaitable[Any]]) -> None:
    """Register CADWiz's Layer 3 advanced-verb tools onto `mcp`."""

    @mcp.tool()
    async def create_partdesign_helix(
        body_name: str,
        sketch_name: str,
        pitch: float,
        height: float,
        mode: str = "additive",
        reversed_: bool = False,
        left_handed: bool = False,
        name: str | None = None,
        doc_name: str | None = None,
    ) -> dict[str, Any]:
        """Sweep a sketch profile along a helix to make a thread or a spring.

        Real FreeCAD 1.1.3 requires the helix's `ReferenceAxis` to be set
        explicitly to the profile sketch's own normal axis (`N_Axis`) --
        left at its `None` default, `AdditiveHelix`/`SubtractiveHelix` raise
        `gp_Dir() - input vector has zero norm` at recompute. Measured
        2026-09-07 against real FreeCAD, not assumed from documentation.

        Args:
            body_name: The PartDesign body the profile sketch belongs to.
            sketch_name: A sketch already in the body, carrying the profile
                to sweep (e.g. a circle from `add_sketch_circle`, offset from
                the sketch's own origin -- the offset distance becomes the
                coil radius; a profile centered on the origin degenerates to
                a straight extrusion, not a helix).
            pitch: Axial distance per turn, in millimetres.
            height: Total axial height of the helix, in millimetres.
            mode: "additive" (add material, the common case: a screw thread,
                a spring) or "subtractive" (cut a helical channel, e.g. a
                thread cut into a hole).
            reversed_: Sweep in the opposite direction along the axis.
            left_handed: Left-handed thread/coil instead of right-handed.
            name: Feature name. Auto-generated if None.
            doc_name: Document containing the body. Active document if None.

        Returns:
            name, label, type_id, volume_mm3 of the created feature.
        """
        if mode not in ("additive", "subtractive"):
            raise ValueError(f"mode must be 'additive' or 'subtractive', got {mode!r}")
        feature_type = "PartDesign::AdditiveHelix" if mode == "additive" else "PartDesign::SubtractiveHelix"
        bridge = await get_bridge()
        code = f"""
doc = FreeCAD.ActiveDocument if {doc_name!r} is None else FreeCAD.getDocument({doc_name!r})
if doc is None:
    raise ValueError("No document found")

body = doc.getObject({body_name!r})
if body is None:
    raise ValueError(f"Body not found: {body_name!r}")

sketch = doc.getObject({sketch_name!r})
if sketch is None:
    raise ValueError(f"Sketch not found: {sketch_name!r}")

helix = body.newObject({feature_type!r}, {name!r} or "Helix")
helix.Profile = (sketch, [""])
helix.ReferenceAxis = (sketch, ["N_Axis"])
helix.Pitch = {pitch}
helix.Height = {height}
helix.Reversed = {bool(reversed_)}
helix.LeftHanded = {bool(left_handed)}
doc.recompute()

if helix.Shape is None or helix.Shape.isNull():
    raise ValueError(f"{{helix.Name}} produced a null shape after recompute")

_result_ = {{
    "name": helix.Name,
    "label": helix.Label,
    "type_id": helix.TypeId,
    "volume_mm3": helix.Shape.Volume,
}}
"""
        result = await bridge.execute_python(code)
        if result.success:
            return result.result
        raise ValueError(result.error_traceback or f"create_partdesign_helix ({mode}) failed")

    @mcp.tool()
    async def convert_sketch_geometry_to_bspline(
        sketch_name: str,
        geometry_index: int,
        doc_name: str | None = None,
    ) -> dict[str, Any]:
        """Convert one sketch element (a line, arc, or conic) to a B-spline.

        The entry point for freeform editing: nothing among the 152 vendored
        tools or `add_sketch_bspline` above lets an existing element become
        editable as a NURBS curve. `Sketcher::SketchObject.convertToNURBS`
        preserves the curve's exact shape (a converted line keeps its
        original length; a converted arc keeps its original arc length) --
        this only changes the representation, not the geometry.

        Args:
            sketch_name: Name of the sketch carrying the geometry.
            geometry_index: Index of the element to convert (as returned by
                the `add_sketch_*` tool that created it, or from
                `get_sketch_info`).
            doc_name: Document containing the sketch. Active document if None.

        Returns:
            geometry_index, degree, is_bspline (always True on success).
        """
        bridge = await get_bridge()
        code = f"""
doc = FreeCAD.ActiveDocument if {doc_name!r} is None else FreeCAD.getDocument({doc_name!r})
if doc is None:
    raise ValueError("No document found")

sketch = doc.getObject({sketch_name!r})
if sketch is None:
    raise ValueError(f"Sketch not found: {sketch_name!r}")

sketch.convertToNURBS({geometry_index})
doc.recompute()
geo = sketch.Geometry[{geometry_index}]

_result_ = {{
    "geometry_index": {geometry_index},
    "degree": geo.Degree,
    "is_bspline": True,
}}
"""
        result = await bridge.execute_python(code)
        if result.success:
            return result.result
        raise ValueError(result.error_traceback or "convert_sketch_geometry_to_bspline failed")

    @mcp.tool()
    async def increase_sketch_bspline_degree(
        sketch_name: str,
        geometry_index: int,
        count: int = 1,
        doc_name: str | None = None,
    ) -> dict[str, Any]:
        """Raise a sketch B-spline's degree, preserving its exact shape.

        Degree elevation is shape-preserving by construction (a documented
        property of NURBS, confirmed 2026-09-07 against real FreeCAD: the
        curve's length is unchanged before and after). Only valid on an
        element that is already a B-spline --
        `convert_sketch_geometry_to_bspline` first if it is not.

        Args:
            sketch_name: Name of the sketch carrying the B-spline.
            geometry_index: Index of the B-spline element.
            count: How many degrees to add. Defaults to 1.
            doc_name: Document containing the sketch. Active document if None.

        Returns:
            geometry_index, degree_before, degree_after.
        """
        bridge = await get_bridge()
        code = f"""
doc = FreeCAD.ActiveDocument if {doc_name!r} is None else FreeCAD.getDocument({doc_name!r})
if doc is None:
    raise ValueError("No document found")

sketch = doc.getObject({sketch_name!r})
if sketch is None:
    raise ValueError(f"Sketch not found: {sketch_name!r}")

before = sketch.Geometry[{geometry_index}].Degree
sketch.increaseBSplineDegree({geometry_index}, {int(count)})
doc.recompute()
after = sketch.Geometry[{geometry_index}].Degree

_result_ = {{
    "geometry_index": {geometry_index},
    "degree_before": before,
    "degree_after": after,
}}
"""
        result = await bridge.execute_python(code)
        if result.success:
            return result.result
        raise ValueError(result.error_traceback or "increase_sketch_bspline_degree failed")

    @mcp.tool()
    async def create_subshape_binder(
        target_body_name: str,
        source_object_name: str,
        name: str | None = None,
        doc_name: str | None = None,
    ) -> dict[str, Any]:
        """Reference another body's (or any object's) shape into this body.

        The multi-body gap the coverage map named: `create_partdesign_body`
        makes an additional body, but nothing referenced one body's geometry
        into another's feature tree. A `PartDesign::SubShapeBinder` is a
        live, associative reference -- it updates when the source object
        changes and recomputes -- not a one-time copy, which is what makes
        cross-body construction (a second body built from the first one's
        result, without merging their trees) possible at all.

        Args:
            target_body_name: The PartDesign body the binder is added to.
            source_object_name: The object (another body's tip feature, a
                Part::Feature, anything with a Shape) to bind.
            name: Feature name. Auto-generated if None.
            doc_name: Document containing both objects. Active document if None.

        Returns:
            name, label, type_id, volume_mm3 of the created binder.
        """
        bridge = await get_bridge()
        code = f"""
doc = FreeCAD.ActiveDocument if {doc_name!r} is None else FreeCAD.getDocument({doc_name!r})
if doc is None:
    raise ValueError("No document found")

target_body = doc.getObject({target_body_name!r})
if target_body is None:
    raise ValueError(f"Body not found: {target_body_name!r}")

source = doc.getObject({source_object_name!r})
if source is None:
    raise ValueError(f"Source object not found: {source_object_name!r}")

binder = target_body.newObject("PartDesign::SubShapeBinder", {name!r} or "Binder")
binder.Support = [(source, "")]
doc.recompute()

if binder.Shape is None or binder.Shape.isNull():
    raise ValueError(f"{{binder.Name}} produced a null shape after recompute")

_result_ = {{
    "name": binder.Name,
    "label": binder.Label,
    "type_id": binder.TypeId,
    "volume_mm3": binder.Shape.Volume,
}}
"""
        result = await bridge.execute_python(code)
        if result.success:
            return result.result
        raise ValueError(result.error_traceback or "create_subshape_binder failed")

    @mcp.tool()
    async def create_draft_line(
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        z1: float = 0.0,
        z2: float = 0.0,
        name: str | None = None,
        doc_name: str | None = None,
    ) -> dict[str, Any]:
        """Free-standing Draft::Wire line, not scoped to a sketch.

        `create_line` (objects.py, one of the 152 vendored tools) makes a
        `Part::Feature` from a raw edge -- a dumb shape, not a parametric
        Draft object, and not what `Draft_Line` in the coverage map names.
        `add_sketch_line` needs an existing sketch. This is the free-standing
        case the coverage map found missing entirely.

        Returns:
            name, label, type_id, length_mm.
        """
        bridge = await get_bridge()
        code = f"""
import Draft

doc = FreeCAD.ActiveDocument if {doc_name!r} is None else FreeCAD.getDocument({doc_name!r})
if doc is None:
    raise ValueError("No document found")

obj = Draft.make_line(FreeCAD.Vector({x1}, {y1}, {z1}), FreeCAD.Vector({x2}, {y2}, {z2}))
if {name!r} is not None:
    obj.Label = {name!r}
doc.recompute()

if obj.Shape is None or obj.Shape.isNull():
    raise ValueError(f"{{obj.Name}} produced a null shape after recompute")

_result_ = {{
    "name": obj.Name,
    "label": obj.Label,
    "type_id": obj.TypeId,
    "length_mm": obj.Shape.Length,
}}
"""
        result = await bridge.execute_python(code)
        if result.success:
            return result.result
        raise ValueError(result.error_traceback or "create_draft_line failed")

    @mcp.tool()
    async def create_draft_circle(
        radius: float,
        x: float = 0.0,
        y: float = 0.0,
        z: float = 0.0,
        name: str | None = None,
        doc_name: str | None = None,
    ) -> dict[str, Any]:
        """Free-standing Draft::Circle, not scoped to a sketch.

        `add_sketch_circle` needs an existing sketch; nothing placed a
        free-standing 2D circle before this. Positioned by its center, on
        the XY plane (Draft's default working plane).

        Returns:
            name, label, type_id, area_mm2.
        """
        bridge = await get_bridge()
        code = f"""
import Draft

doc = FreeCAD.ActiveDocument if {doc_name!r} is None else FreeCAD.getDocument({doc_name!r})
if doc is None:
    raise ValueError("No document found")

placement = FreeCAD.Placement(FreeCAD.Vector({x}, {y}, {z}), FreeCAD.Rotation())
obj = Draft.make_circle({radius}, placement=placement, face=True)
if {name!r} is not None:
    obj.Label = {name!r}
doc.recompute()

if obj.Shape is None or obj.Shape.isNull():
    raise ValueError(f"{{obj.Name}} produced a null shape after recompute")

_result_ = {{
    "name": obj.Name,
    "label": obj.Label,
    "type_id": obj.TypeId,
    "area_mm2": obj.Shape.Area,
}}
"""
        result = await bridge.execute_python(code)
        if result.success:
            return result.result
        raise ValueError(result.error_traceback or "create_draft_circle failed")

    @mcp.tool()
    async def create_draft_rectangle(
        length: float,
        width: float,
        x: float = 0.0,
        y: float = 0.0,
        z: float = 0.0,
        name: str | None = None,
        doc_name: str | None = None,
    ) -> dict[str, Any]:
        """Free-standing Draft::Rectangle, not scoped to a sketch.

        Positioned by its lower-left corner, on the XY plane, matching
        `Draft.make_rectangle`'s own convention.

        Returns:
            name, label, type_id, area_mm2.
        """
        bridge = await get_bridge()
        code = f"""
import Draft

doc = FreeCAD.ActiveDocument if {doc_name!r} is None else FreeCAD.getDocument({doc_name!r})
if doc is None:
    raise ValueError("No document found")

placement = FreeCAD.Placement(FreeCAD.Vector({x}, {y}, {z}), FreeCAD.Rotation())
obj = Draft.make_rectangle({length}, {width}, placement=placement, face=True)
if {name!r} is not None:
    obj.Label = {name!r}
doc.recompute()

if obj.Shape is None or obj.Shape.isNull():
    raise ValueError(f"{{obj.Name}} produced a null shape after recompute")

_result_ = {{
    "name": obj.Name,
    "label": obj.Label,
    "type_id": obj.TypeId,
    "area_mm2": obj.Shape.Area,
}}
"""
        result = await bridge.execute_python(code)
        if result.success:
            return result.result
        raise ValueError(result.error_traceback or "create_draft_rectangle failed")

    @mcp.tool()
    async def check_mesh_manifold(
        object_name: str,
        doc_name: str | None = None,
    ) -> dict[str, Any]:
        """Report whether a Mesh object is solid and manifold. Read-only.

        The Mesh workbench's `Mesh_Evaluation` ("Evaluate and Repair") had no
        tool at all before this report -- the entire Mesh workbench was
        almost unbuilt (coverage map, 2026-09-07). This is the diagnostic
        half; `repair_mesh` below is the fix.

        Args:
            object_name: Name of the Mesh::Feature object to check.
            doc_name: Document containing the object. Active document if None.

        Returns:
            is_solid: whether the mesh forms a closed volume.
            has_self_intersections: whether any facets intersect.
            has_non_manifolds: whether any edge is shared by other than
                exactly two facets.
            facet_count, point_count.
        """
        bridge = await get_bridge()
        code = f"""
doc = FreeCAD.ActiveDocument if {doc_name!r} is None else FreeCAD.getDocument({doc_name!r})
if doc is None:
    raise ValueError("No document found")

obj = doc.getObject({object_name!r})
if obj is None:
    raise ValueError(f"Object not found: {object_name!r}")
if not hasattr(obj, "Mesh"):
    raise ValueError(f"{object_name!r} is not a Mesh object")

mesh = obj.Mesh
_result_ = {{
    "is_solid": mesh.isSolid(),
    "has_self_intersections": mesh.hasSelfIntersections(),
    "has_non_manifolds": mesh.hasNonManifolds(),
    "facet_count": mesh.CountFacets,
    "point_count": mesh.CountPoints,
}}
"""
        result = await bridge.execute_python(code)
        if result.success:
            return result.result
        raise ValueError(result.error_traceback or "check_mesh_manifold failed")

    @mcp.tool()
    async def repair_mesh(
        object_name: str,
        max_hole_edges: int = 100,
        doc_name: str | None = None,
    ) -> dict[str, Any]:
        """Fix holes, flipped normals, and duplicate geometry in a Mesh object.

        Applies, in order: `fillupHoles` (closes holes up to `max_hole_edges`
        edges), `harmonizeNormals` (makes facet winding consistent),
        `removeDuplicatedFacets`, `removeDuplicatedPoints`. Mutates the mesh
        in place -- this is CADWiz's own first-party implementation using
        FreeCAD's `Mesh` module directly (the same pattern
        `export_3mf_native` uses), not a wrapper around a vendored tool,
        since none of the 152 vendored tools touch a Mesh object at all.

        Args:
            object_name: Name of the Mesh::Feature object to repair.
            max_hole_edges: Largest hole (by edge count) `fillupHoles` will
                close. Defaults to 100.
            doc_name: Document containing the object. Active document if None.

        Returns:
            facet_count_before, facet_count_after, was_solid_before,
            is_solid_after.
        """
        bridge = await get_bridge()
        code = f"""
doc = FreeCAD.ActiveDocument if {doc_name!r} is None else FreeCAD.getDocument({doc_name!r})
if doc is None:
    raise ValueError("No document found")

obj = doc.getObject({object_name!r})
if obj is None:
    raise ValueError(f"Object not found: {object_name!r}")
if not hasattr(obj, "Mesh"):
    raise ValueError(f"{object_name!r} is not a Mesh object")

mesh = obj.Mesh.copy()
was_solid_before = mesh.isSolid()
facet_count_before = mesh.CountFacets

mesh.fillupHoles({int(max_hole_edges)}, 2)
mesh.harmonizeNormals()
mesh.removeDuplicatedFacets()
mesh.removeDuplicatedPoints()

obj.Mesh = mesh
doc.recompute()

_result_ = {{
    "facet_count_before": facet_count_before,
    "facet_count_after": mesh.CountFacets,
    "was_solid_before": was_solid_before,
    "is_solid_after": mesh.isSolid(),
}}
"""
        result = await bridge.execute_python(code)
        if result.success:
            return result.result
        raise ValueError(result.error_traceback or "repair_mesh failed")

    @mcp.tool()
    async def scale_mesh(
        object_name: str,
        factor_x: float,
        factor_y: float = 0.0,
        factor_z: float = 0.0,
        doc_name: str | None = None,
    ) -> dict[str, Any]:
        """Scale a Mesh object -- the downloaded-STL-came-in-wrong-units case.

        `scale_object` (one of the 152 vendored tools) targets `Part::Feature`
        objects; a `Mesh::Feature` has no `.scale()` method at all (confirmed
        2026-09-08 by direct API inspection) and needs `Mesh.transform()`
        with a scaling matrix instead -- genuinely different mechanics, not
        a name the vendored tool happened to miss.

        Args:
            object_name: Name of the Mesh::Feature object to scale.
            factor_x: Scale factor along X.
            factor_y: Scale factor along Y. Same as factor_x if 0 (uniform
                scaling, the common case).
            factor_z: Scale factor along Z. Same as factor_x if 0.
            doc_name: Document containing the object. Active document if None.

        Returns:
            factor_x, factor_y, factor_z actually applied, bounding_box_before,
            bounding_box_after (each [xlen, ylen, zlen] in mm).
        """
        fy = factor_y or factor_x
        fz = factor_z or factor_x
        bridge = await get_bridge()
        code = f"""
doc = FreeCAD.ActiveDocument if {doc_name!r} is None else FreeCAD.getDocument({doc_name!r})
if doc is None:
    raise ValueError("No document found")

obj = doc.getObject({object_name!r})
if obj is None:
    raise ValueError(f"Object not found: {object_name!r}")
if not hasattr(obj, "Mesh"):
    raise ValueError(f"{object_name!r} is not a Mesh object")

bbox_before = obj.Mesh.BoundBox
before = [bbox_before.XLength, bbox_before.YLength, bbox_before.ZLength]

mesh = obj.Mesh.copy()
matrix = FreeCAD.Matrix()
matrix.scale({factor_x}, {fy}, {fz})
mesh.transform(matrix)
obj.Mesh = mesh
doc.recompute()

bbox_after = obj.Mesh.BoundBox
_result_ = {{
    "factor_x": {factor_x}, "factor_y": {fy}, "factor_z": {fz},
    "bounding_box_before": before,
    "bounding_box_after": [bbox_after.XLength, bbox_after.YLength, bbox_after.ZLength],
}}
"""
        result = await bridge.execute_python(code)
        if result.success:
            return result.result
        raise ValueError(result.error_traceback or "scale_mesh failed")

    @mcp.tool()
    async def convert_mesh_to_solid(
        object_name: str,
        tolerance: float = 0.05,
        result_name: str | None = None,
        doc_name: str | None = None,
    ) -> dict[str, Any]:
        """Turn a (repaired, manifold) Mesh back into an editable Part solid.

        The inverse of `Mesh_FromPartShape`/M6's own solid-to-mesh direction:
        this closes the loop the coverage map named -- "so a repaired mesh
        can be edited" -- by producing a real `Part::Feature` solid whose
        Shape a `create_subshape_binder` (Layer 3) can then reference into a
        PartDesign body for further pad/pocket/fillet work. Confirmed
        2026-09-08: `Part.Shape.makeShapeFromMesh` + `Part.makeSolid` +
        `removeSplitter()` (drops redundant coplanar-facet seams) produces a
        valid solid whose volume matches the source mesh; a mesh that is not
        actually manifold (`check_mesh_manifold`'s own `is_solid=False`)
        will fail here, which is the correct outcome -- repair it first.

        Args:
            object_name: Name of the Mesh::Feature object to convert.
            tolerance: Sewing tolerance for reconstructing faces from
                triangles, in millimetres. Defaults to 0.05.
            result_name: Name for the resulting solid. Auto-generated if None.
            doc_name: Document containing the object. Active document if None.

        Returns:
            name, label, type_id, volume_mm3, is_valid of the created solid.
        """
        bridge = await get_bridge()
        code = f"""
import Part

doc = FreeCAD.ActiveDocument if {doc_name!r} is None else FreeCAD.getDocument({doc_name!r})
if doc is None:
    raise ValueError("No document found")

obj = doc.getObject({object_name!r})
if obj is None:
    raise ValueError(f"Object not found: {object_name!r}")
if not hasattr(obj, "Mesh"):
    raise ValueError(f"{object_name!r} is not a Mesh object")

shape = Part.Shape()
shape.makeShapeFromMesh(obj.Mesh.Topology, {tolerance})
solid = Part.makeSolid(shape)
solid = solid.removeSplitter()
if not solid.isValid() or solid.isNull():
    raise ValueError(
        f"the reconstructed solid is not valid -- {{object_name!r}} may not be "
        "manifold; check check_mesh_manifold/repair_mesh first"
    )

result = doc.addObject("Part::Feature", {result_name!r} or f"{{obj.Name}}_Solid")
result.Shape = solid
doc.recompute()

_result_ = {{
    "name": result.Name,
    "label": result.Label,
    "type_id": result.TypeId,
    "volume_mm3": result.Shape.Volume,
    "is_valid": result.Shape.isValid(),
}}
"""
        result = await bridge.execute_python(code)
        if result.success:
            return result.result
        raise ValueError(result.error_traceback or "convert_mesh_to_solid failed")
