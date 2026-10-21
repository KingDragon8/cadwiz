# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""PROVE-SWEEP batch 6 defect fix: `create_datum_plane`/`create_datum_line`/
`create_datum_point` (`vendor/robust-mcp/src/freecad_mcp/tools/
partdesign.py`) all resolve their own body's origin sub-objects by a FIXED
NAME STRING (`body.Origin.getObject("XY_Plane")`, `"X_Axis"`, `"Point"`).

That works only for the FIRST `PartDesign::Body` created in a document.
Confirmed directly 2026-09-11: a second body's own origin features are
auto-renamed by FreeCAD with a numeric suffix (`X_Axis001`, `XY_Plane001`,
`Origin003`, ...) -- `getObject("XY_Plane")` on that body's own `Origin`
returns `None`, and (worse than a loud failure) `AttachmentSupport =
[(None, "")]` does not raise: `PositionBySupport` silently no-ops, leaving
the resulting datum's own `Placement` at pure identity and SILENTLY
IGNORING the requested offset/position entirely. A second, separate defect
found the same session: `create_datum_point`'s own literal string `"Point"`
never matches ANY body's origin point object, even the first one -- its
real auto-generated name is `Origin001`/`Origin002`/... (never the bare
word `"Point"`), so this one is broken for EVERY body, not just the second.
A third, separate defect: `create_datum_line`'s own `MapMode = "ObjectXY"`
is not implemented for `PartDesign::Line` in real FreeCAD 1.1.3 at all
(raises `Attachment mode ObjectXY is not implemented` and leaves the
object permanently invalid) -- measured `MapMode = "Tangent"` gives the
correct result instead (the line's own tangent matches the requested axis
exactly, confirmed independently for X/Y/Z).

**The fix.** `_origin_feature(body, name)` resolves an origin sub-object by
its FIXED POSITION in `body.Origin.OriginFeatures` (confirmed stable
2026-09-11 across two bodies in the same document: `[X_Axis, Y_Axis,
Z_Axis, XY_Plane, XZ_Plane, YZ_Plane, <origin point>]`, always in that
order, regardless of what numeric suffix FreeCAD gives each body's own
copy) rather than by the name string FreeCAD happened to assign the FIRST
body's own features.

`vendor/` is never edited in place: this overrides all three tools under
their existing names, the same technique PROVE-026's fix (`fillet_pro.py`)
uses for `fillet_edges`/`chamfer_edges` -- `mcp.remove_tool` first, since
FastMCP's own `ToolManager.add_tool` silently keeps the FIRST registration
on a name collision.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

#: Fixed position of each origin feature within `body.Origin.OriginFeatures`
#: -- confirmed stable 2026-09-11 across multiple bodies in one document,
#: regardless of the numeric suffix FreeCAD gives each body's own copy.
_ORIGIN_FEATURE_INDEX = {
    "X_Axis": 0,
    "Y_Axis": 1,
    "Z_Axis": 2,
    "XY_Plane": 3,
    "XZ_Plane": 4,
    "YZ_Plane": 5,
    "Point": 6,
}


def _origin_feature(body: Any, name: str) -> Any:
    index = _ORIGIN_FEATURE_INDEX[name]
    return body.Origin.OriginFeatures[index]


def register_datum_pro_tools(mcp: Any, get_bridge: Callable[[], Awaitable[Any]]) -> None:
    mcp.remove_tool("create_datum_plane")
    mcp.remove_tool("create_datum_line")
    mcp.remove_tool("create_datum_point")

    @mcp.tool()
    async def create_datum_plane(
        body_name: str,
        offset: float = 0.0,
        base_plane: str = "XY_Plane",
        name: str | None = None,
        doc_name: str | None = None,
    ) -> dict[str, Any]:
        """Create a datum plane in a PartDesign body.

        Datum planes are reference planes used for sketching or measurements.

        Fixed 2026-09-11 (PROVE-SWEEP): resolves the body's own base plane by
        its fixed position in `body.Origin.OriginFeatures`, not by the
        vendored tool's own fixed name string (`"XY_Plane"`), which only
        matches the FIRST body created in a document -- any other body's own
        plane is auto-renamed (`"XY_Plane001"`, ...) and the vendored
        lookup silently returns a datum plane frozen at identity, ignoring
        the requested offset entirely.

        Args:
            body_name: Name of the PartDesign body.
            offset: Offset distance from base plane. Defaults to 0.
            base_plane: Base plane to offset from. Options:
                - "XY_Plane" - Horizontal plane
                - "XZ_Plane" - Front vertical plane
                - "YZ_Plane" - Side vertical plane
            name: Datum plane name. Auto-generated if None.
            doc_name: Document containing the body. Uses active document if None.

        Returns:
            Dictionary with created datum information:
                - name: Datum name
                - label: Datum label
                - type_id: Object type
        """
        bridge = await get_bridge()
        code = f"""
from integrations.mcp_tools.datum_pro import _origin_feature

doc = FreeCAD.ActiveDocument if {doc_name!r} is None else FreeCAD.getDocument({doc_name!r})
if doc is None:
    raise ValueError("No document found")

body = doc.getObject({body_name!r})
if body is None:
    raise ValueError(f"Body not found: {body_name!r}")

doc.openTransaction("Create Datum Plane")
try:
    datum_name = {name!r} or "DatumPlane"
    datum = body.newObject("PartDesign::Plane", datum_name)

    plane_obj = _origin_feature(body, {base_plane!r})
    datum.AttachmentSupport = [(plane_obj, "")]
    datum.MapMode = "FlatFace"
    datum.MapPathParameter = 0
    datum.MapReversed = False
    datum.AttachmentOffset = FreeCAD.Placement(
        FreeCAD.Vector(0, 0, {offset}),
        FreeCAD.Rotation(0, 0, 0, 1)
    )

    doc.recompute()
    doc.commitTransaction()

    _result_ = {{
        "name": datum.Name,
        "label": datum.Label,
        "type_id": datum.TypeId,
    }}
except Exception:
    doc.abortTransaction()
    raise
"""
        result = await bridge.execute_python(code)
        if result.success:
            return result.result
        raise ValueError(result.error_traceback or "Create datum plane failed")

    @mcp.tool()
    async def create_datum_line(
        body_name: str,
        base_axis: str = "X_Axis",
        name: str | None = None,
        doc_name: str | None = None,
    ) -> dict[str, Any]:
        """Create a datum line (axis) in a PartDesign body.

        Datum lines are reference axes used for patterns or measurements.

        Fixed 2026-09-11 (PROVE-SWEEP): resolves the body's own base axis
        positionally (see `create_datum_plane`'s own note -- the identical
        multi-body naming problem applies here) and uses `MapMode =
        "Tangent"`, not the vendored tool's own `"ObjectXY"`, which FreeCAD
        1.1.3 does not implement for this feature type and which left every
        resulting datum line permanently invalid.

        Args:
            body_name: Name of the PartDesign body.
            base_axis: Base axis. Options: "X_Axis", "Y_Axis", "Z_Axis".
            name: Datum line name. Auto-generated if None.
            doc_name: Document containing the body. Uses active document if None.

        Returns:
            Dictionary with created datum information:
                - name: Datum name
                - label: Datum label
                - type_id: Object type
        """
        bridge = await get_bridge()
        code = f"""
from integrations.mcp_tools.datum_pro import _origin_feature

doc = FreeCAD.ActiveDocument if {doc_name!r} is None else FreeCAD.getDocument({doc_name!r})
if doc is None:
    raise ValueError("No document found")

body = doc.getObject({body_name!r})
if body is None:
    raise ValueError(f"Body not found: {body_name!r}")

doc.openTransaction("Create Datum Line")
try:
    datum_name = {name!r} or "DatumLine"
    datum = body.newObject("PartDesign::Line", datum_name)

    axis_obj = _origin_feature(body, {base_axis!r})
    datum.AttachmentSupport = [(axis_obj, "")]
    datum.MapMode = "Tangent"

    doc.recompute()
    doc.commitTransaction()

    _result_ = {{
        "name": datum.Name,
        "label": datum.Label,
        "type_id": datum.TypeId,
    }}
except Exception:
    doc.abortTransaction()
    raise
"""
        result = await bridge.execute_python(code)
        if result.success:
            return result.result
        raise ValueError(result.error_traceback or "Create datum line failed")

    @mcp.tool()
    async def create_datum_point(
        body_name: str,
        position: list[float] | None = None,
        name: str | None = None,
        doc_name: str | None = None,
    ) -> dict[str, Any]:
        """Create a datum point in a PartDesign body.

        Datum points are reference points used for measurements or construction.

        Fixed 2026-09-11 (PROVE-SWEEP): resolves the body's own origin point
        positionally (see `create_datum_plane`'s own note), not by the
        vendored tool's own literal string `"Point"` -- FreeCAD never names a
        body's own origin point object `"Point"` (its real auto-generated
        name is `Origin001`/`Origin002`/...), so the vendored lookup returns
        `None` for EVERY body, not just a second one, and the resulting
        datum point silently stays at the world origin regardless of the
        requested `position`.

        Args:
            body_name: Name of the PartDesign body.
            position: Point position [x, y, z]. Uses origin if None.
            name: Datum point name. Auto-generated if None.
            doc_name: Document containing the body. Uses active document if None.

        Returns:
            Dictionary with created datum information:
                - name: Datum name
                - label: Datum label
                - type_id: Object type
        """
        bridge = await get_bridge()
        pos = position if position else [0, 0, 0]
        code = f"""
from integrations.mcp_tools.datum_pro import _origin_feature

doc = FreeCAD.ActiveDocument if {doc_name!r} is None else FreeCAD.getDocument({doc_name!r})
if doc is None:
    raise ValueError("No document found")

body = doc.getObject({body_name!r})
if body is None:
    raise ValueError(f"Body not found: {body_name!r}")

doc.openTransaction("Create Datum Point")
try:
    datum_name = {name!r} or "DatumPoint"
    datum = body.newObject("PartDesign::Point", datum_name)

    origin_point = _origin_feature(body, "Point")
    datum.AttachmentSupport = [(origin_point, "")]
    datum.MapMode = "ObjectOrigin"
    datum.AttachmentOffset = FreeCAD.Placement(
        FreeCAD.Vector({pos[0]}, {pos[1]}, {pos[2]}),
        FreeCAD.Rotation(0, 0, 0, 1)
    )

    doc.recompute()
    doc.commitTransaction()

    _result_ = {{
        "name": datum.Name,
        "label": datum.Label,
        "type_id": datum.TypeId,
    }}
except Exception:
    doc.abortTransaction()
    raise
"""
        result = await bridge.execute_python(code)
        if result.success:
            return result.result
        raise ValueError(result.error_traceback or "Create datum point failed")
