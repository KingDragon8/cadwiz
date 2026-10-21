# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""PROVE-SWEEP batch 11 defect fixes: three independent, real defects in
`vendor/robust-mcp/src/freecad_mcp/tools/partdesign.py`'s sketch-editing
tools, all confirmed directly against real FreeCAD 1.1.3.

**Defect one.** `add_sketch_constraint`'s own shared branch for
`"Horizontal"`/`"Vertical"`/`"Block"` crashes whenever a caller passes an
explicit point index -- which is `constrain_fix`'s entire reason to exist.

Confirmed directly 2026-09-11 against real FreeCAD 1.1.3:
`Sketcher.Constraint("Block", geo, point)` -- the vendored branch's own
3-argument call whenever `point1 >= 0` -- raises `TypeError: Invalid
parameters: ('Block', 0, 1) ... Constraint constructor accepts: -- empty
parameter list -- Constraint type and index`. The SAME 3-argument form
fails identically for `"Horizontal"` and `"Vertical"` too -- none of the
three types has a single-point constructor form in real FreeCAD; only a
geometry-only form (`(type, geo)`, the whole element) or, for Horizontal/
Vertical specifically, a TWO-point form (`(type, geo1, pos1, geo2, pos2)`,
making the line BETWEEN two points horizontal/vertical) exist. `constrain_
horizontal`/`constrain_vertical` (already PROVEN) never hit this: neither
takes a point argument at all, so their own calls always land on the safe
geometry-only branch.

**The fix.** `add_sketch_constraint`'s own "Block" case now always uses
the geometry-only form (`Sketcher.Constraint("Block", g1)`) -- confirmed
this is the ONLY form Block actually supports; a caller-supplied point
index is accepted (for API compatibility) but has no effect, since no
FreeCAD constraint can lock a single sketch POINT this way (a real
"fix this point in place" needs an absolute-coordinate constraint pair --
DistanceX + DistanceY -- a materially different mechanism, out of scope
for this fix). "Horizontal"/"Vertical" now use the two-point form when a
second point is genuinely supplied (`geometry2 >= 0` and `point2 >= 0`),
and fall back to the geometry-only form otherwise -- both confirmed
working against real FreeCAD.

`constrain_fix` (`Sketcher.Constraint("Block", geometry_index)` only, by
construction) is fixed the same way, as its own direct override rather
than delegating to the vendored `add_sketch_constraint`'s own internal
Python closure -- `vendor/robust-mcp`'s dedicated `constrain_*` tools each
call that closure directly by local Python reference, not through the MCP
registry, so overriding the registered `add_sketch_constraint` tool alone
would not reach `constrain_fix`'s own call.

**Defect two.** `toggle_construction` always reports `is_construction:
False`, regardless of the geometry's real, just-toggled state. It checks
`geo.Construction` on the `Part.Geom*` object returned by `sketch.
Geometry[index]` -- confirmed directly that this attribute never exists on
that object in FreeCAD 1.1.3 (`hasattr(geo, "Construction")` is `False`
before AND after toggling), so its own `if hasattr(...) else False`
fallback always takes the `False` branch. `Sketch.getConstruction(index)`
is the correct, direct query -- confirmed to return `True` right after
`toggleConstruction(index)`.

**Defect three.** `add_external_geometry` raises `AttributeError:
'Sketcher.SketchObject' object has no attribute 'ExternalGeometryCount'`
on every successful call -- confirmed the property does not exist;
`sketch.ExternalGeometry` (a list) is the real one, and `len(sketch.
ExternalGeometry)` is the correct count. The underlying `addExternal`
call itself was never broken.

**Defect four.** `get_sketch_info` has the identical `ExternalGeometryCount`
defect as `add_external_geometry` (raises the same `AttributeError` on
every call), plus a second, independent one: it reports `"dof": sketch.
solve()`, but `Sketch.solve()` returns a SOLVER STATUS code (`0` on
success), not the sketch's own degrees of freedom -- confirmed directly: a
genuinely under-constrained line (4 real DOF, `FullyConstrained ==
False`) still gets `solve() == 0`, so `get_sketch_info` would report
`dof: 0` for a sketch that is nowhere close to fully constrained.
`Sketch.DoF` is the correct, direct property (confirmed `4` for the same
fixture).

`vendor/` is never edited in place: all five tools are re-registered
under their existing names, the same technique PROVE-026's fix
(`fillet_pro.py`) uses -- `mcp.remove_tool` first, since FastMCP's own
`ToolManager.add_tool` silently keeps the FIRST registration on a name
collision.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable


def register_sketch_constraint_pro_tools(mcp: Any, get_bridge: Callable[[], Awaitable[Any]]) -> None:
    mcp.remove_tool("add_sketch_constraint")
    mcp.remove_tool("constrain_fix")
    mcp.remove_tool("toggle_construction")
    mcp.remove_tool("add_external_geometry")
    mcp.remove_tool("get_sketch_info")

    @mcp.tool()
    async def add_sketch_constraint(
        sketch_name: str,
        constraint_type: str,
        geometry1: int,
        point1: int = -1,
        geometry2: int = -2,
        point2: int = -1,
        value: float | None = None,
        doc_name: str | None = None,
    ) -> dict[str, Any]:
        """Add a constraint to a sketch.

        This is a general-purpose constraint tool. For common constraints,
        use the specific constraint tools (constrain_horizontal, etc.).

        Fixed 2026-09-11 (PROVE-SWEEP): "Block" now always uses the
        geometry-only form -- FreeCAD has no single-point Block constraint,
        confirmed directly (the vendored tool's own 3-argument attempt
        raised TypeError on every call). "Horizontal"/"Vertical" use the
        real two-point form when a genuine second point is supplied, and
        the geometry-only form otherwise, instead of the vendored tool's
        own always-3-argument attempt whenever a point was given.

        Args:
            sketch_name: Name of the sketch.
            constraint_type: Type of constraint. Options:
                - Geometric: "Coincident", "Horizontal", "Vertical", "Parallel",
                  "Perpendicular", "Tangent", "Equal", "Symmetric", "Block"
                - Dimensional: "Distance", "DistanceX", "DistanceY", "Radius",
                  "Diameter", "Angle"
            geometry1: Index of first geometry element.
            point1: Point index on first geometry (1=start, 2=end, 3=center).
                    Use -1 for edge itself. Ignored for "Block" (no single-
                    point form exists in FreeCAD); used for "Horizontal"/
                    "Vertical" only together with geometry2/point2 (the
                    real two-point form) -- a lone point1 with no second
                    point falls back to the geometry-only form.
            geometry2: Index of second geometry element. Use -2 for external.
            point2: Point index on second geometry.
            value: Value for dimensional constraints (distance, angle, etc.).
            doc_name: Document containing the sketch. Uses active document if None.

        Returns:
            Dictionary with constraint info:
                - constraint_index: Index of the added constraint
                - constraint_count: Total constraint count
        """
        bridge = await get_bridge()
        code = f"""
import Sketcher

doc = FreeCAD.ActiveDocument if {doc_name!r} is None else FreeCAD.getDocument({doc_name!r})
sketch = doc.getObject({sketch_name!r})
if sketch is None:
    raise ValueError(f"Sketch not found: {sketch_name!r}")

doc.openTransaction("Add Sketch Constraint")
try:
    ctype = {constraint_type!r}
    g1, p1, g2, p2 = {geometry1}, {point1}, {geometry2}, {point2}
    value = {value!r}

    if ctype == "Block":
        constraint = Sketcher.Constraint(ctype, g1)
    elif ctype in ["Horizontal", "Vertical"]:
        if p1 >= 0 and g2 >= 0 and p2 >= 0:
            constraint = Sketcher.Constraint(ctype, g1, p1, g2, p2)
        else:
            constraint = Sketcher.Constraint(ctype, g1)
    elif ctype in ["Coincident", "Perpendicular", "Parallel", "Tangent", "Equal"]:
        if p1 >= 0 and p2 >= 0:
            constraint = Sketcher.Constraint(ctype, g1, p1, g2, p2)
        else:
            constraint = Sketcher.Constraint(ctype, g1, g2)
    elif ctype == "Symmetric":
        if g2 < 0:
            raise ValueError("Symmetric constraint requires geometry2 as the symmetry line index")
        constraint = Sketcher.Constraint(ctype, g1, p1, g2, p2, geometry2)
    elif ctype in ["Distance", "DistanceX", "DistanceY"]:
        if value is None:
            raise ValueError(f"{{ctype}} constraint requires a value")
        if g2 >= 0:
            constraint = Sketcher.Constraint(ctype, g1, p1, g2, p2, value)
        elif p1 >= 0:
            constraint = Sketcher.Constraint(ctype, g1, p1, value)
        else:
            constraint = Sketcher.Constraint(ctype, g1, value)
    elif ctype in ["Radius", "Diameter"]:
        if value is None:
            raise ValueError(f"{{ctype}} constraint requires a value")
        constraint = Sketcher.Constraint(ctype, g1, value)
    elif ctype == "Angle":
        if value is None:
            raise ValueError("Angle constraint requires a value")
        if g2 >= 0:
            constraint = Sketcher.Constraint(ctype, g1, g2, value)
        else:
            constraint = Sketcher.Constraint(ctype, g1, value)
    else:
        raise ValueError(f"Unknown constraint type: {{ctype}}")

    idx = sketch.addConstraint(constraint)
    doc.recompute()
    doc.commitTransaction()

    _result_ = {{
        "constraint_index": idx,
        "constraint_count": sketch.ConstraintCount,
    }}
except Exception:
    doc.abortTransaction()
    raise
"""
        result = await bridge.execute_python(code)
        if result.success:
            return result.result
        raise ValueError(result.error_traceback or "Add constraint failed")

    @mcp.tool()
    async def constrain_fix(
        sketch_name: str,
        geometry_index: int,
        point_index: int = -1,
        doc_name: str | None = None,
    ) -> dict[str, Any]:
        """Fix (lock) a geometry element in place.

        Fixed 2026-09-11 (PROVE-SWEEP): FreeCAD's own "Block" constraint
        has no single-point form -- the vendored tool's own attempt to pass
        `point_index` through to it raised `TypeError` on every call with a
        point index other than the default. This always locks the WHOLE
        element; `point_index` is accepted for API compatibility but has no
        effect (fixing a single point in place needs a different
        mechanism -- an absolute DistanceX/DistanceY constraint pair --
        which this tool does not build).

        Args:
            sketch_name: Name of the sketch.
            geometry_index: Index of the geometry element to fix.
            point_index: Accepted for compatibility; has no effect (see above).
            doc_name: Document containing the sketch. Uses active document if None.

        Returns:
            Dictionary with constraint info:
                - constraint_index: Index of the added constraint
        """
        bridge = await get_bridge()
        code = f"""
import Sketcher

doc = FreeCAD.ActiveDocument if {doc_name!r} is None else FreeCAD.getDocument({doc_name!r})
sketch = doc.getObject({sketch_name!r})
if sketch is None:
    raise ValueError(f"Sketch not found: {sketch_name!r}")

doc.openTransaction("Constrain Fix")
try:
    idx = sketch.addConstraint(Sketcher.Constraint("Block", {geometry_index}))
    doc.recompute()
    doc.commitTransaction()

    _result_ = {{
        "constraint_index": idx,
        "constraint_count": sketch.ConstraintCount,
    }}
except Exception:
    doc.abortTransaction()
    raise
"""
        result = await bridge.execute_python(code)
        if result.success:
            return result.result
        raise ValueError(result.error_traceback or "Constrain fix failed")

    @mcp.tool()
    async def toggle_construction(
        sketch_name: str,
        geometry_index: int,
        doc_name: str | None = None,
    ) -> dict[str, Any]:
        """Toggle construction mode for a sketch geometry.

        Construction geometry is used for reference but not included
        in the final sketch profile.

        Fixed 2026-09-11 (PROVE-SWEEP): reads the new state back via
        `Sketch.getConstruction(index)`, not the vendored tool's own
        `geo.Construction` attribute check, which never exists on a
        `Part.Geom*` object in FreeCAD 1.1.3 and always reported `False`.

        Args:
            sketch_name: Name of the sketch.
            geometry_index: Index of the geometry to toggle.
            doc_name: Document containing the sketch. Uses active document if None.

        Returns:
            Dictionary with result:
                - success: Whether the operation succeeded
                - is_construction: New construction state
        """
        bridge = await get_bridge()
        code = f"""
doc = FreeCAD.ActiveDocument if {doc_name!r} is None else FreeCAD.getDocument({doc_name!r})
sketch = doc.getObject({sketch_name!r})
if sketch is None:
    raise ValueError(f"Sketch not found: {sketch_name!r}")

doc.openTransaction("Toggle Construction")
try:
    sketch.toggleConstruction({geometry_index})
    doc.recompute()
    doc.commitTransaction()

    is_construction = sketch.getConstruction({geometry_index})

    _result_ = {{
        "success": True,
        "is_construction": is_construction,
    }}
except Exception:
    doc.abortTransaction()
    raise
"""
        result = await bridge.execute_python(code)
        if result.success:
            return result.result
        raise ValueError(result.error_traceback or "Toggle construction failed")

    @mcp.tool()
    async def add_external_geometry(
        sketch_name: str,
        object_name: str,
        element: str,
        doc_name: str | None = None,
    ) -> dict[str, Any]:
        """Add external geometry reference to a sketch.

        External geometry allows referencing edges/faces from other
        objects for construction and constraints. For a sketch inside a
        PartDesign Body, the referenced object must be part of the same
        Body (or its own datum features) -- confirmed directly: FreeCAD
        itself refuses an unrelated document object with "<name> is not
        allowed as external geometry of this sketch", a real, sensible
        topological-locality restriction, not a defect this tool needs to
        route around.

        Fixed 2026-09-11 (PROVE-SWEEP): reports the count via `len(Sketch.
        ExternalGeometry)`, not the vendored tool's own `sketch.
        ExternalGeometryCount`, which does not exist as a property on
        `Sketcher::SketchObject` in FreeCAD 1.1.3 and raised `AttributeError`
        on every otherwise-successful call.

        Args:
            sketch_name: Name of the sketch.
            object_name: Name of the object to reference.
            element: Element to reference (e.g., "Edge1", "Face1").
            doc_name: Document containing the sketch. Uses active document if None.

        Returns:
            Dictionary with result:
                - success: Whether the operation succeeded
                - external_geometry_count: Number of external geometry elements
        """
        bridge = await get_bridge()
        code = f"""
doc = FreeCAD.ActiveDocument if {doc_name!r} is None else FreeCAD.getDocument({doc_name!r})
sketch = doc.getObject({sketch_name!r})
if sketch is None:
    raise ValueError(f"Sketch not found: {sketch_name!r}")

ref_obj = doc.getObject({object_name!r})
if ref_obj is None:
    raise ValueError(f"Object not found: {object_name!r}")

doc.openTransaction("Add External Geometry")
try:
    sketch.addExternal({object_name!r}, {element!r})
    doc.recompute()
    doc.commitTransaction()

    _result_ = {{
        "success": True,
        "external_geometry_count": len(sketch.ExternalGeometry),
    }}
except Exception:
    doc.abortTransaction()
    raise
"""
        result = await bridge.execute_python(code)
        if result.success:
            return result.result
        raise ValueError(result.error_traceback or "Add external geometry failed")

    @mcp.tool()
    async def get_sketch_info(
        sketch_name: str,
        doc_name: str | None = None,
    ) -> dict[str, Any]:
        """Get detailed information about a sketch.

        Fixed 2026-09-11 (PROVE-SWEEP): `external_geometry_count` via
        `len(Sketch.ExternalGeometry)`, not the vendored tool's own
        `sketch.ExternalGeometryCount` (does not exist, raised
        AttributeError on every call); `dof` via `Sketch.DoF` directly, not
        `Sketch.solve()` (a solver STATUS code, not the sketch's own
        degrees of freedom -- confirmed `solve() == 0` even for a
        genuinely under-constrained sketch).

        Args:
            sketch_name: Name of the sketch.
            doc_name: Document containing the sketch. Uses active document if None.

        Returns:
            Dictionary with sketch information:
                - name: Sketch name
                - geometry_count: Number of geometry elements
                - constraint_count: Number of constraints
                - external_geometry_count: Number of external geometry references
                - fully_constrained: Whether sketch is fully constrained
                - dof: Degrees of freedom remaining
        """
        bridge = await get_bridge()
        code = f"""
doc = FreeCAD.ActiveDocument if {doc_name!r} is None else FreeCAD.getDocument({doc_name!r})
sketch = doc.getObject({sketch_name!r})
if sketch is None:
    raise ValueError(f"Sketch not found: {sketch_name!r}")

_result_ = {{
    "name": sketch.Name,
    "label": sketch.Label,
    "geometry_count": sketch.GeometryCount,
    "constraint_count": sketch.ConstraintCount,
    "external_geometry_count": len(sketch.ExternalGeometry),
    "fully_constrained": sketch.FullyConstrained if hasattr(sketch, "FullyConstrained") else None,
    "dof": sketch.DoF if hasattr(sketch, "DoF") else None,
}}
"""
        result = await bridge.execute_python(code)
        if result.success:
            return result.result
        raise ValueError(result.error_traceback or "Get sketch info failed")
