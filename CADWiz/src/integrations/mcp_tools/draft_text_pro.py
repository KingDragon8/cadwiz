# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""DRAFT-TEXT-PRO: fixes `draft_text_on_surface`'s silent no-op defect.

**The defect, found 2026-09-12 (PROVE-SWEEP final chunk, capability 58).**
`draft_text_on_surface` (`vendor/robust-mcp/src/freecad_mcp/tools/draft.py`)
builds `text_face` from the ShapeString's own `Shape.Wires` -- already in
world coordinates, since a `DocumentObject`'s `.Shape` reflects its own
current `Placement` -- extrudes that face into `text_solid` (a bare
`Part.Shape`, still in the same already-correct world coordinates), and
then runs one extra line before the boolean operation:

    text_solid.Placement = shape_string.Placement

Assigning `.Placement` on a bare `Part.Shape` (not a `DocumentObject`)
transforms whatever coordinates the shape already holds by that placement
-- it does not "confirm" or "re-apply" the placement the geometry was
already built from, it adds a SECOND copy of it on top. Confirmed directly
2026-09-12: for a box at the origin with a top face at z=10, extruding a
label positioned at z=10.1 down to z=8.6 (correctly overlapping the box)
and then re-applying that same placement moves the solid to z=18.7-20.2 --
completely clear of the box. The boolean cut/fuse that follows then has
zero overlap with the target every time, for every face position, and the
tool returns a renamed copy of the UNCHANGED target shape with no error at
all: `draft_text_on_surface` reports success and produces a result object,
but no engraving or embossing ever happens.

**The fix.** Drop the redundant re-placement -- `text_solid` needs no
`Placement` of its own; its geometry is already in the correct world
position. Everything else is the vendored tool's own logic, byte-for-byte
(`vendor/` is never edited in place): re-registered under the same name via
`mcp.remove_tool` + a fresh `@mcp.tool()`, PROVE-026's own technique.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable


def register_draft_text_pro_tools(mcp: Any, get_bridge: Callable[[], Awaitable[Any]]) -> None:
    mcp.remove_tool("draft_text_on_surface")

    @mcp.tool()
    async def draft_text_on_surface(
        text: str,
        target_face: str,
        target_object: str,
        depth: float = 2.0,
        font_path: str | None = None,
        size: float = 10.0,
        position: list[float] | None = None,
        operation: str = "engrave",
        name: str | None = None,
        doc_name: str | None = None,
    ) -> dict[str, Any]:
        """Create embossed or engraved text on a surface.

        DRAFT-TEXT-PRO fix (2026-09-12): the vendored tool re-applied the
        ShapeString's own Placement to the already-placed extruded solid,
        moving it completely clear of the target face every time -- the
        boolean operation always had zero overlap, so the tool silently
        did nothing to the target's geometry while reporting success. This
        drops that redundant re-placement; the extruded solid's own
        geometry is already in world coordinates.

        Args:
            text: The text string to create.
            target_face: Face name to place text on (e.g., "Face1", "Face6").
            target_object: Name of the object containing the face.
            depth: Depth of emboss/engrave in mm. Defaults to 2.0.
            font_path: Path to font file. Uses system default if None.
            size: Font size in mm. Defaults to 10.0.
            position: Text position offset [x, y] on the face. Defaults to [0, 0].
            operation: "emboss" (raised) or "engrave" (cut into). Defaults to "engrave".
            name: Name for the result object. Auto-generated if None.
            doc_name: Target document. Uses active document if None.

        Returns:
            Dictionary with result information:
                - name: Result object name
                - label: Result label
                - type_id: Object type
                - operation: Operation performed (emboss/engrave)
                - text: Text that was created
                - depth: Depth used
        """
        bridge = await get_bridge()
        pos = position if position is not None else [0.0, 0.0]
        if len(pos) != 2:
            raise ValueError(f"position must have exactly 2 elements, got {len(pos)}")

        code = f"""
import Draft
import Part
import os

doc = FreeCAD.ActiveDocument if {doc_name!r} is None else FreeCAD.getDocument({doc_name!r})
if doc is None:
    raise ValueError("No document found")

target = doc.getObject({target_object!r})
if target is None:
    raise ValueError(f"Target object not found: {target_object!r}")

if not hasattr(target, 'Shape') or target.Shape is None:
    raise ValueError(f"Target object has no shape: {target_object!r}")

face_name = {target_face!r}
try:
    face = getattr(target.Shape, face_name)
except Exception:
    raise ValueError(f"Face not found: {{face_name}} on {target_object!r}")

doc.openTransaction("Text on Surface")
try:
    text = {text!r}
    size = {size!r}
    depth = {depth!r}
    operation = {operation!r}.lower()
    pos_offset = {pos!r}
    result_name = {name!r} or f"Text_{{target.Name}}"

    if operation not in ("emboss", "engrave"):
        raise ValueError(f"Invalid operation: {{operation}}. Use 'emboss' or 'engrave'.")

    font_path = {font_path!r}
    if font_path is None:
        default_fonts = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/TTF/DejaVuSans.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
            "/Library/Fonts/Arial.ttf",
            "C:/Windows/Fonts/arial.ttf",
        ]
        for fp in default_fonts:
            if os.path.exists(fp):
                font_path = fp
                break
        if font_path is None:
            raise ValueError("No font file specified and no default font found.")

    if not os.path.exists(font_path):
        raise ValueError(f"Font file not found: {{font_path}}")

    face_center = face.CenterOfMass
    face_normal = face.normalAt(0, 0)

    shape_string = Draft.make_shapestring(text, font_path, size)
    if shape_string is None:
        raise ValueError("Failed to create ShapeString")

    doc.recompute()

    if abs(face_normal.z) > 0.9:
        rotation = FreeCAD.Rotation(FreeCAD.Vector(0, 0, 1), 0)
        if face_normal.z < 0:
            rotation = FreeCAD.Rotation(FreeCAD.Vector(1, 0, 0), 180)
    elif abs(face_normal.x) > 0.9:
        rotation = FreeCAD.Rotation(FreeCAD.Vector(0, 1, 0), 90 if face_normal.x > 0 else -90)
    else:
        rotation = FreeCAD.Rotation(FreeCAD.Vector(1, 0, 0), 90 if face_normal.y < 0 else -90)

    offset = FreeCAD.Vector(pos_offset[0], pos_offset[1], 0)
    text_pos = face_center + offset

    if operation == "engrave":
        text_pos = text_pos + face_normal * 0.1
    else:
        text_pos = text_pos - face_normal * depth

    shape_string.Placement = FreeCAD.Placement(text_pos, rotation)
    doc.recompute()

    wires = shape_string.Shape.Wires
    if not wires:
        raise ValueError("ShapeString has no wires")

    closed_wires = [w for w in wires if w.isClosed()]
    if not closed_wires:
        raise ValueError("Could not create faces from text - no closed wires")

    try:
        text_face = Part.makeFace(closed_wires, "Part::FaceMakerBullseye")
    except Exception as e:
        raise ValueError(f"Could not create faces from text: {{e}}")

    if not text_face.Faces:
        raise ValueError("Could not create faces from text")

    extrude_dir = face_normal * depth
    if operation == "engrave":
        extrude_dir = face_normal * (-depth)

    # DRAFT-TEXT-PRO fix: text_face's own Wires are already in world
    # coordinates (they came from the ShapeString's own placed Shape), and
    # so is the solid extruded from them -- no further Placement belongs
    # here. The vendored tool's own extra `text_solid.Placement =
    # shape_string.Placement` line moved the solid a second time, clear of
    # every target face, and is deliberately not reproduced.
    text_solid = text_face.extrude(extrude_dir)

    if operation == "engrave":
        result_shape = target.Shape.cut(text_solid)
    else:
        result_shape = target.Shape.fuse(text_solid)

    result_obj = doc.addObject("Part::Feature", result_name)
    result_obj.Shape = result_shape

    if FreeCAD.GuiUp:
        shape_string.ViewObject.Visibility = False
        target.ViewObject.Visibility = False

    doc.recompute()
    doc.commitTransaction()

    _result_ = {{
        "name": result_obj.Name,
        "label": result_obj.Label,
        "type_id": result_obj.TypeId,
        "operation": operation,
        "text": text,
        "depth": depth,
    }}
except Exception:
    doc.abortTransaction()
    raise
"""
        result = await bridge.execute_python(code)
        if result.success and result.result:
            return result.result
        raise ValueError(result.error_traceback or "Failed to create text on surface")
