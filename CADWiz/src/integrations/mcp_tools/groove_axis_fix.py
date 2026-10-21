# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""TOOL FACTORY defect fix for `groove_sketch`, found live 2026-09-27 while
proving this tool's founder path (`tests/freecad_integration/
runtime_groove_sketch_voice_path.py`).

The vendored implementation (`vendor/robust-mcp/src/freecad_mcp/tools/
partdesign.py`, `groove_sketch`) resolves a `"Base_X"`/`"Base_Y"`/`"Base_Z"`
axis with `body.Origin.getObject(f"{axis_ref}_Axis")` -- a lookup by the
origin feature's internal `Name`. FreeCAD document object `Name`s are unique
per-*document*, not per-body: confirmed live, a document's first
`PartDesign::Body` gets origin features named `X_Axis`/`Y_Axis`/`Z_Axis`, but
every subsequent body's origin features are disambiguated to `X_Axis001`,
`X_Axis002`, and so on, even though each lives in its own body's `Origin`
group. `getObject("X_Axis")` on a second-or-later body's `Origin` therefore
returns `None`, and the vendored code passes that `None` straight into
`groove.ReferenceAxis = (None, [""])`, raising `TypeError: type of first
element in tuple must be 'DocumentObject', not NoneType` -- a real founder-
path failure for `groove_sketch` on any document with more than one body,
which is an entirely ordinary case, not an edge case.

Each origin feature also carries a `Role` property (`"X_Axis"`, `"Y_Axis"`,
`"Z_Axis"`, ...) that FreeCAD keeps stable across renaming -- confirmed live
against a second body's Origin. Matching on `Role` instead of `Name` is the
fix.

`vendor/` is never edited in place: this overrides `groove_sketch` under its
existing name, the same technique `document_undo_fix.py` uses for
`create_document`/`open_document` and `fillet_pro.py` uses for
`fillet_edges`/`chamfer_edges` -- `mcp.remove_tool` first, since FastMCP's
own `ToolManager.add_tool` silently keeps the FIRST registration on a name
collision.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable


def register_groove_axis_fix(mcp: Any, get_bridge: Callable[[], Awaitable[Any]]) -> None:
    mcp.remove_tool("groove_sketch")

    @mcp.tool()
    async def groove_sketch(
        sketch_name: str,
        angle: float = 360.0,
        axis: str = "Base_X",
        symmetric: bool = False,
        reversed: bool = False,
        name: str | None = None,
        doc_name: str | None = None,
    ) -> dict[str, Any]:
        """Create a Groove (subtractive revolution) from a sketch.

        Revolves a sketch profile and subtracts it from existing material.

        Fixed 2026-09-27: resolves a `"Base_*"` axis by the origin feature's
        `Role` property instead of its `Name` -- the vendored lookup by
        `Name` (`"X_Axis"`) breaks on every body after the first one in a
        document, because FreeCAD disambiguates origin feature `Name`s
        document-wide (`"X_Axis001"`, ...) even though `Role` stays stable.

        Args:
            sketch_name: Name of the sketch to revolve.
            angle: Groove angle in degrees. Defaults to 360.
            axis: Axis to revolve around. Options:
                - "Base_X" - X axis
                - "Base_Y" - Y axis
                - "Base_Z" - Z axis
                - "Sketch_V" - Sketch vertical axis
                - "Sketch_H" - Sketch horizontal axis
            symmetric: Whether to revolve symmetrically. Defaults to False.
            reversed: Whether to reverse direction. Defaults to False.
            name: Groove feature name. Auto-generated if None.
            doc_name: Document containing the sketch. Uses active document if None.

        Returns:
            Dictionary with created groove information:
                - name: Groove name
                - label: Groove label
                - type_id: Object type
        """
        bridge = await get_bridge()

        code = f"""
doc = FreeCAD.ActiveDocument if {doc_name!r} is None else FreeCAD.getDocument({doc_name!r})
sketch = doc.getObject({sketch_name!r})
if sketch is None:
    raise ValueError(f"Sketch not found: {sketch_name!r}")

# Find the body containing this sketch
body = None
for obj in doc.Objects:
    if obj.TypeId == "PartDesign::Body":
        if hasattr(obj, "Group") and sketch in obj.Group:
            body = obj
            break

if body is None:
    raise ValueError("Sketch must be inside a PartDesign Body for Groove operation")


def _origin_feature_by_role(origin, role):
    for feature in origin.OriginFeatures:
        if getattr(feature, "Role", None) == role:
            return feature
    return None


# Wrap in transaction for undo support
doc.openTransaction("Groove Sketch")
try:
    groove_name = {name!r} or "Groove"
    groove = body.newObject("PartDesign::Groove", groove_name)
    groove.Profile = sketch
    groove.Angle = {angle}
    groove.Symmetric = {symmetric}
    groove.Reversed = {reversed}

    # Set axis reference
    axis_name = {axis!r}
    if axis_name.startswith("Base_"):
        axis_ref = axis_name.replace("Base_", "")
        axis_feature = _origin_feature_by_role(body.Origin, f"{{axis_ref}}_Axis")
        if axis_feature is None:
            raise ValueError(f"Could not find {{axis_ref}}_Axis on body {{body.Name}}'s Origin")
        groove.ReferenceAxis = (axis_feature, [""])
    elif axis_name.startswith("Sketch_"):
        if axis_name == "Sketch_V":
            groove.ReferenceAxis = (sketch, ["V_Axis"])
        else:
            groove.ReferenceAxis = (sketch, ["H_Axis"])

    doc.recompute()
    doc.commitTransaction()
except Exception:
    doc.abortTransaction()
    raise

_result_ = {{
    "name": groove.Name,
    "label": groove.Label,
    "type_id": groove.TypeId,
}}
"""
        result = await bridge.execute_python(code)
        if result.success:
            return result.result
        raise ValueError(result.error_traceback or "Groove failed")
