# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""LIVE-RESULT: one generic `Part::FeaturePython` wrapper for the whole
frozen-result tool family, not nine separate FILLET-PRO-style rebuilds.

**The defect this replaces, found and recorded across PROVE-SWEEP batches
2, 4, 6, and 7.** `fuse_all`, `common_all`, `shell_object`, `mirror_object`,
`scale_object`, `offset_3d`, `revolve_shape`, `copy_object`, and
`import_step` (`vendor/robust-mcp`, never edited in place) all share the
identical pattern: `result = doc.addObject("Part::Feature", name);
result.Shape = <computed shape>`. A `Part::Feature` has no `execute()` of
its own -- it is a one-time BREP snapshot with no recompute recipe and no
live link back to whatever it was built from. Changing an upstream object
afterward (a source pad's own Length, for instance) leaves the frozen
result's own volume exactly where it started -- confirmed directly, every
time, across all nine tools before this fix.

**The fix, once, for the whole family.** `LiveResultFeature` is a
`Part::FeaturePython` proxy -- the same mechanism FILLET-PRO's own
`QueryFilletFeature` (`fillet_pro.py`) already proved out for a single
tool -- storing three properties: `Sources` (an `App::PropertyLinkList` to
the upstream object(s), which is what makes FreeCAD's own dependency graph
mark this feature for recompute whenever a source's Shape changes -- no
different a mechanism than any other live PartDesign feature), `Operation`
(which shape computation to run), and `Params` (a JSON-encoded dict of
whatever else that computation needs -- a mirror plane, a scale factor, a
file path). `execute()` re-derives `Shape` from all three, fresh, every
recompute -- never a frozen snapshot.

`import_step` is the one member with no in-document source object at all
(its own source is an external file): `Sources` is empty and `Params`
carries the file path instead; `execute()` re-reads that file from disk
with `Part.Shape().read(path)` (a bare shape, no extra document objects,
confirmed 2026-09-11) every time it runs -- "live" for an external file
means the shape updates if the file changes AND the feature is told to
recompute (`touch()` + `doc.recompute()`), the correct, honest meaning of
"live" for a reference to something outside the document's own dependency
graph.

`vendor/` is never edited in place: all nine tools are re-registered under
their existing names (`mcp.remove_tool` + a fresh `@mcp.tool()`, PROVE-026's
own technique, required because FastMCP's own `ToolManager.add_tool`
silently keeps the FIRST registration on a name collision).
"""

from __future__ import annotations

import json
from typing import Any, Awaitable, Callable


class LiveResultFeature:
    """A `Part::FeaturePython` proxy whose `execute()` re-derives its own
    Shape from a stored operation, its source object links, and its own
    parameters -- never a frozen snapshot."""

    def __init__(self, obj: Any, operation: str, sources: list[Any], params: dict[str, Any]) -> None:
        obj.Proxy = self
        obj.addProperty(
            "App::PropertyLinkList", "Sources", "LiveResult",
            "Upstream objects this result is derived from -- empty for a file-sourced operation",
        )
        obj.Sources = sources
        obj.addProperty(
            "App::PropertyString", "Operation", "LiveResult",
            "Which shape computation to re-run every recompute",
        )
        obj.Operation = operation
        obj.addProperty(
            "App::PropertyString", "Params", "LiveResult",
            "JSON-encoded operation parameters (plane/scale/offset/file path/...)",
        )
        obj.Params = json.dumps(params)

    def execute(self, fp: Any) -> None:
        import json as _json  # noqa: PLC0415

        operation = fp.Operation
        params = _json.loads(fp.Params)
        sources = list(fp.Sources)
        shape, placement = compute_live_result(operation, sources, params)
        fp.Shape = shape
        if placement is not None:
            fp.Placement = placement


def compute_live_result(operation: str, sources: list[Any], params: dict[str, Any]) -> tuple[Any, Any | None]:
    """The nine operations, each reproducing its own vendored tool's exact
    shape computation -- only the frozen-snapshot assignment is replaced,
    not the geometry itself. Returns (shape, placement_or_None); only
    `copy` sets a placement (matching the vendored tool's own behaviour of
    positioning the copy at the source's CURRENT placement plus a fixed
    offset -- confirmed 2026-09-11 to produce an identical bounding box
    whether the target is a Part::Feature or a Part::FeaturePython)."""
    import FreeCAD  # noqa: PLC0415

    if operation == "fuse":
        shape = sources[0].Shape
        for source in sources[1:]:
            shape = shape.fuse(source.Shape)
        return shape, None

    if operation == "common":
        shape = sources[0].Shape
        for source in sources[1:]:
            shape = shape.common(source.Shape)
        return shape, None

    if operation == "shell":
        obj = sources[0]
        faces_param = params.get("faces_to_remove")
        if faces_param:
            faces = [obj.Shape.Faces[int(name[4:]) - 1] for name in faces_param]
        else:
            # Re-picked fresh every recompute, not frozen at creation time --
            # an improvement on the vendored tool's own one-shot pick, and
            # the only sensible live behaviour when no face was named.
            faces = [max(obj.Shape.Faces, key=lambda f: f.Area)]
        return obj.Shape.makeThickness(faces, params["thickness"], 1e-3), None

    if operation == "mirror":
        obj = sources[0]
        normal = FreeCAD.Vector(*params["normal"])
        center = obj.Shape.BoundBox.Center  # re-measured every recompute, not frozen
        return obj.Shape.mirror(center, normal), None

    if operation == "scale":
        obj = sources[0]
        matrix = FreeCAD.Matrix()
        matrix.scale(FreeCAD.Vector(*params["scale"]))
        return obj.Shape.transformGeometry(matrix), None

    if operation == "offset":
        obj = sources[0]
        return obj.Shape.makeOffsetShape(params["offset"], 1e-3), None

    if operation == "revolve":
        obj = sources[0]
        axis_point = FreeCAD.Vector(*params["axis_point"])
        axis_direction = FreeCAD.Vector(*params["axis_direction"])
        return obj.Shape.revolve(axis_point, axis_direction, params["angle"]), None

    if operation == "copy":
        obj = sources[0]
        offset = FreeCAD.Vector(*params["offset"])
        placement = FreeCAD.Placement(obj.Placement.Base + offset, obj.Placement.Rotation)
        return obj.Shape.copy(), placement

    if operation == "import_step":
        import Part  # noqa: PLC0415

        shape = Part.Shape()
        shape.read(params["file_path"])
        return shape, None

    if operation == "loft":
        import Part  # noqa: PLC0415

        profiles = [source.Shape.Wires[0] for source in sources]
        loft = Part.makeLoft(profiles, params["solid"], params["ruled"], params["closed"])
        return loft, None

    if operation == "sweep":
        import Part  # noqa: PLC0415

        spine = Part.Wire(sources[1].Shape.Wires[0])
        profile = sources[0].Shape.Wires[0]
        sweep = spine.makePipeShell([profile], params["solid"], params["frenet"])
        return sweep, None

    raise ValueError(f"unknown LiveResultFeature operation: {operation!r}")


def create_live_result_impl(
    doc: Any, operation: str, sources: list[Any], params: dict[str, Any], name: str | None,
) -> dict[str, Any]:
    feature_name = name or operation.capitalize()
    feature = doc.addObject("Part::FeaturePython", feature_name)
    LiveResultFeature(feature, operation, sources, params)
    doc.recompute()
    return {"name": feature.Name, "label": feature.Label, "type_id": feature.TypeId}


# ---- registration -----------------------------------------------------

_MIRROR_PLANE_NORMAL = {"XY": [0.0, 0.0, 1.0], "XZ": [0.0, 1.0, 0.0], "YZ": [1.0, 0.0, 0.0]}


def register_live_result_tools(mcp: Any, get_bridge: Callable[[], Awaitable[Any]]) -> None:
    for _name in (
        "fuse_all", "common_all", "shell_object", "mirror_object", "scale_object",
        "offset_3d", "revolve_shape", "copy_object", "import_step",
        "part_loft", "part_sweep",
    ):
        mcp.remove_tool(_name)

    @mcp.tool()
    async def fuse_all(
        object_names: list[str],
        result_name: str | None = None,
        doc_name: str | None = None,
    ) -> dict[str, Any]:
        """Fuse (union) multiple shapes into a single solid.

        LIVE-RESULT fix (2026-09-11): the result is a live Part::FeaturePython
        that re-fuses its own sources every recompute -- changing any
        upstream object updates the fused volume, unlike the vendored
        tool's own frozen Part::Feature snapshot.

        Args:
            object_names: List of object names to fuse.
            result_name: Name for result object. Auto-generated if None.
            doc_name: Document containing the objects. Uses active document if None.

        Returns:
            Dictionary with created object information: name, label, type_id.
        """
        bridge = await get_bridge()
        code = f"""
from integrations.mcp_tools.live_result import create_live_result_impl

doc = FreeCAD.ActiveDocument if {doc_name!r} is None else FreeCAD.getDocument({doc_name!r})
if doc is None:
    raise ValueError("No document found")

sources = []
for obj_name in {object_names!r}:
    obj = doc.getObject(obj_name)
    if obj is None:
        raise ValueError(f"Object not found: {{obj_name}}")
    if not hasattr(obj, "Shape"):
        raise ValueError(f"Object has no shape: {{obj_name}}")
    sources.append(obj)

if len(sources) < 2:
    raise ValueError("Need at least 2 objects to fuse")

doc.openTransaction("Fuse All")
try:
    _result_ = create_live_result_impl(doc, "fuse", sources, {{}}, {result_name!r} or "Fusion")
    doc.commitTransaction()
except Exception:
    doc.abortTransaction()
    raise
"""
        result = await bridge.execute_python(code)
        if result.success:
            return result.result
        raise ValueError(result.error_traceback or "Fuse all failed")

    @mcp.tool()
    async def common_all(
        object_names: list[str],
        result_name: str | None = None,
        doc_name: str | None = None,
    ) -> dict[str, Any]:
        """Find the common (intersection) of multiple shapes.

        LIVE-RESULT fix (2026-09-11): see fuse_all's own note -- identical
        fix, the intersection instead of the union.

        Args:
            object_names: List of object names to intersect.
            result_name: Name for result object. Auto-generated if None.
            doc_name: Document containing the objects. Uses active document if None.

        Returns:
            Dictionary with created object information: name, label, type_id.
        """
        bridge = await get_bridge()
        code = f"""
from integrations.mcp_tools.live_result import create_live_result_impl

doc = FreeCAD.ActiveDocument if {doc_name!r} is None else FreeCAD.getDocument({doc_name!r})
if doc is None:
    raise ValueError("No document found")

sources = []
for obj_name in {object_names!r}:
    obj = doc.getObject(obj_name)
    if obj is None:
        raise ValueError(f"Object not found: {{obj_name}}")
    if not hasattr(obj, "Shape"):
        raise ValueError(f"Object has no shape: {{obj_name}}")
    sources.append(obj)

if len(sources) < 2:
    raise ValueError("Need at least 2 objects for common operation")

doc.openTransaction("Common All")
try:
    _result_ = create_live_result_impl(doc, "common", sources, {{}}, {result_name!r} or "Common")
    doc.commitTransaction()
except Exception:
    doc.abortTransaction()
    raise
"""
        result = await bridge.execute_python(code)
        if result.success:
            return result.result
        raise ValueError(result.error_traceback or "Common all failed")

    @mcp.tool()
    async def shell_object(
        object_name: str,
        thickness: float,
        faces_to_remove: list[str] | None = None,
        result_name: str | None = None,
        doc_name: str | None = None,
    ) -> dict[str, Any]:
        """Create a shell (hollow) version of a solid by removing faces.

        LIVE-RESULT fix (2026-09-11): the result is a live Part::FeaturePython
        that re-shells its own source every recompute; if no face was named,
        the largest face is re-picked fresh each time too, not frozen at
        creation.

        Args:
            object_name: Name of the solid object to shell.
            thickness: Wall thickness (positive = outward, negative = inward).
            faces_to_remove: List of face names to remove (e.g., ["Face1", "Face6"]).
                            If None, removes the largest face.
            result_name: Name for result object. Auto-generated if None.
            doc_name: Document containing the object. Uses active document if None.

        Returns:
            Dictionary with created object information: name, label, type_id.
        """
        bridge = await get_bridge()
        faces_param = faces_to_remove if faces_to_remove else None
        code = f"""
from integrations.mcp_tools.live_result import create_live_result_impl

doc = FreeCAD.ActiveDocument if {doc_name!r} is None else FreeCAD.getDocument({doc_name!r})
if doc is None:
    raise ValueError("No document found")

obj = doc.getObject({object_name!r})
if obj is None:
    raise ValueError(f"Object not found: {object_name!r}")
if not hasattr(obj, "Shape"):
    raise ValueError("Object has no shape")

doc.openTransaction("Shell Object")
try:
    params = {{"thickness": {thickness}, "faces_to_remove": {faces_param!r}}}
    _result_ = create_live_result_impl(doc, "shell", [obj], params, {result_name!r} or f"{{obj.Name}}_shell")
    doc.commitTransaction()
except Exception:
    doc.abortTransaction()
    raise
"""
        result = await bridge.execute_python(code)
        if result.success:
            return result.result
        raise ValueError(result.error_traceback or "Shell operation failed")

    @mcp.tool()
    async def mirror_object(
        object_name: str,
        plane: str = "XY",
        result_name: str | None = None,
        doc_name: str | None = None,
    ) -> dict[str, Any]:
        """Mirror an object across a plane.

        LIVE-RESULT fix (2026-09-11): the result is a live Part::FeaturePython
        that re-mirrors its own source every recompute, about that source's
        CURRENT bounding-box center -- not frozen at the center measured
        when the mirror was first created.

        Args:
            object_name: Name of the object to mirror.
            plane: Mirror plane. Options: "XY", "XZ", "YZ".
            result_name: Name for result object. Auto-generated if None.
            doc_name: Document containing the object. Uses active document if None.

        Returns:
            Dictionary with created object information: name, label, type_id.
        """
        if plane not in _MIRROR_PLANE_NORMAL:
            raise ValueError(f"Invalid plane: {plane}. Use: XY, XZ, YZ")
        bridge = await get_bridge()
        normal = _MIRROR_PLANE_NORMAL[plane]
        code = f"""
from integrations.mcp_tools.live_result import create_live_result_impl

doc = FreeCAD.ActiveDocument if {doc_name!r} is None else FreeCAD.getDocument({doc_name!r})
if doc is None:
    raise ValueError("No document found")

obj = doc.getObject({object_name!r})
if obj is None:
    raise ValueError(f"Object not found: {object_name!r}")
if not hasattr(obj, "Shape"):
    raise ValueError("Object has no shape to mirror")

doc.openTransaction("Mirror Object")
try:
    params = {{"normal": {normal!r}}}
    _result_ = create_live_result_impl(doc, "mirror", [obj], params, {result_name!r} or f"{{obj.Name}}_mirror")
    doc.commitTransaction()
except Exception:
    doc.abortTransaction()
    raise
"""
        result = await bridge.execute_python(code)
        if result.success:
            return result.result
        raise ValueError(result.error_traceback or "Mirror operation failed")

    @mcp.tool()
    async def scale_object(
        object_name: str,
        scale: float | list[float],
        result_name: str | None = None,
        doc_name: str | None = None,
    ) -> dict[str, Any]:
        """Scale an object uniformly or non-uniformly.

        LIVE-RESULT fix (2026-09-11): the result is a live Part::FeaturePython
        that re-scales its own source every recompute.

        Args:
            object_name: Name of the object to scale.
            scale: Scale factor. Can be:
                - A single float for uniform scaling
                - A list [sx, sy, sz] for non-uniform scaling
            result_name: Name for result object. Auto-generated if None.
            doc_name: Document containing the object. Uses active document if None.

        Returns:
            Dictionary with created object information: name, label, type_id.
        """
        bridge = await get_bridge()
        scale_vec = [scale, scale, scale] if isinstance(scale, int | float) else list(scale)
        code = f"""
from integrations.mcp_tools.live_result import create_live_result_impl

doc = FreeCAD.ActiveDocument if {doc_name!r} is None else FreeCAD.getDocument({doc_name!r})
if doc is None:
    raise ValueError("No document found")

obj = doc.getObject({object_name!r})
if obj is None:
    raise ValueError(f"Object not found: {object_name!r}")
if not hasattr(obj, "Shape"):
    raise ValueError("Object has no shape to scale")

doc.openTransaction("Scale Object")
try:
    params = {{"scale": {scale_vec!r}}}
    _result_ = create_live_result_impl(doc, "scale", [obj], params, {result_name!r} or f"{{obj.Name}}_scaled")
    doc.commitTransaction()
except Exception:
    doc.abortTransaction()
    raise
"""
        result = await bridge.execute_python(code)
        if result.success:
            return result.result
        raise ValueError(result.error_traceback or "Scale operation failed")

    @mcp.tool()
    async def offset_3d(
        object_name: str,
        offset: float,
        result_name: str | None = None,
        doc_name: str | None = None,
    ) -> dict[str, Any]:
        """Create a 3D offset of a shape.

        LIVE-RESULT fix (2026-09-11): the result is a live Part::FeaturePython
        that re-offsets its own source every recompute.

        Args:
            object_name: Name of the object to offset.
            offset: Offset distance (positive = outward, negative = inward).
            result_name: Name for result object. Auto-generated if None.
            doc_name: Document containing the object. Uses active document if None.

        Returns:
            Dictionary with created object information: name, label, type_id.
        """
        bridge = await get_bridge()
        code = f"""
from integrations.mcp_tools.live_result import create_live_result_impl

doc = FreeCAD.ActiveDocument if {doc_name!r} is None else FreeCAD.getDocument({doc_name!r})
if doc is None:
    raise ValueError("No document found")

obj = doc.getObject({object_name!r})
if obj is None:
    raise ValueError(f"Object not found: {object_name!r}")
if not hasattr(obj, "Shape"):
    raise ValueError("Object has no shape")

doc.openTransaction("3D Offset")
try:
    params = {{"offset": {offset}}}
    _result_ = create_live_result_impl(doc, "offset", [obj], params, {result_name!r} or f"{{obj.Name}}_offset")
    doc.commitTransaction()
except Exception:
    doc.abortTransaction()
    raise
"""
        result = await bridge.execute_python(code)
        if result.success:
            return result.result
        raise ValueError(result.error_traceback or "3D offset failed")

    @mcp.tool()
    async def revolve_shape(
        object_name: str,
        axis_point: list[float],
        axis_direction: list[float],
        angle: float = 360.0,
        result_name: str | None = None,
        doc_name: str | None = None,
    ) -> dict[str, Any]:
        """Revolve a wire or face around an axis.

        LIVE-RESULT fix (2026-09-11): the result is a live Part::FeaturePython
        that re-revolves its own source every recompute.

        Args:
            object_name: Name of the wire or face object to revolve.
            axis_point: A point on the rotation axis [x, y, z].
            axis_direction: Direction of the rotation axis [x, y, z].
            angle: Revolution angle in degrees. Defaults to 360.
            result_name: Name for result object. Auto-generated if None.
            doc_name: Document containing the object. Uses active document if None.

        Returns:
            Dictionary with created object information: name, label, type_id.
        """
        bridge = await get_bridge()
        code = f"""
from integrations.mcp_tools.live_result import create_live_result_impl

doc = FreeCAD.ActiveDocument if {doc_name!r} is None else FreeCAD.getDocument({doc_name!r})
if doc is None:
    raise ValueError("No document found")

obj = doc.getObject({object_name!r})
if obj is None:
    raise ValueError(f"Object not found: {object_name!r}")
if not hasattr(obj, "Shape"):
    raise ValueError("Object has no shape")

doc.openTransaction("Revolve Shape")
try:
    params = {{"axis_point": {axis_point!r}, "axis_direction": {axis_direction!r}, "angle": {angle}}}
    _result_ = create_live_result_impl(doc, "revolve", [obj], params, {result_name!r} or f"{{obj.Name}}_revolved")
    doc.commitTransaction()
except Exception:
    doc.abortTransaction()
    raise
"""
        result = await bridge.execute_python(code)
        if result.success:
            return result.result
        raise ValueError(result.error_traceback or "Revolve shape failed")

    @mcp.tool()
    async def copy_object(
        object_name: str,
        new_name: str | None = None,
        offset: list[float] | None = None,
        doc_name: str | None = None,
    ) -> dict[str, Any]:
        """Create a copy of an object.

        LIVE-RESULT fix (2026-09-11): the result is a live Part::FeaturePython
        that re-copies its own source every recompute, positioned at the
        source's CURRENT placement plus the requested offset -- moving the
        source now moves the copy too, preserving the same relative offset.

        Args:
            object_name: Name of the object to copy.
            new_name: Name for the copy. Auto-generated if None.
            offset: Position offset [x, y, z] for the copy. [0,0,0] if None.
            doc_name: Document containing the object. Uses active document if None.

        Returns:
            Dictionary with created object information: name, label, type_id.
        """
        bridge = await get_bridge()
        offset_vec = list(offset) if offset else [0.0, 0.0, 0.0]
        code = f"""
from integrations.mcp_tools.live_result import create_live_result_impl

doc = FreeCAD.ActiveDocument if {doc_name!r} is None else FreeCAD.getDocument({doc_name!r})
if doc is None:
    raise ValueError("No document found")

obj = doc.getObject({object_name!r})
if obj is None:
    raise ValueError(f"Object not found: {object_name!r}")
if not hasattr(obj, "Shape"):
    raise ValueError("Object has no shape to copy")

doc.openTransaction("Copy Object")
try:
    params = {{"offset": {offset_vec!r}}}
    _result_ = create_live_result_impl(doc, "copy", [obj], params, {new_name!r} or f"{{obj.Name}}_copy")
    doc.commitTransaction()
except Exception:
    doc.abortTransaction()
    raise
"""
        result = await bridge.execute_python(code)
        if result.success:
            return result.result
        raise ValueError(result.error_traceback or "Copy operation failed")

    @mcp.tool()
    async def import_step(
        file_path: str,
        doc_name: str | None = None,
    ) -> dict[str, Any]:
        """Import a STEP file into FreeCAD.

        LIVE-RESULT fix (2026-09-11): the result is a live Part::FeaturePython
        that re-reads the source STEP file from disk every recompute
        (`touch()` + `doc.recompute()`) -- "live" for an external file means
        the shape follows the file on disk, unlike the vendored tool's own
        one-time `Part.insert` snapshot.

        Args:
            file_path: Path to the .step file to import.
            doc_name: Document to import into. Creates new if None.

        Returns:
            Dictionary with import result:
                - success: Whether import was successful
                - document: Name of document containing imported object
                - objects: List containing the imported object's own name
        """
        bridge = await get_bridge()
        code = f"""
import os

from integrations.mcp_tools.live_result import create_live_result_impl

if not os.path.exists({file_path!r}):
    raise FileNotFoundError(f"File not found: {file_path!r}")

doc = FreeCAD.ActiveDocument if {doc_name!r} is None else FreeCAD.getDocument({doc_name!r})
if doc is None:
    doc = FreeCAD.newDocument("Imported")

doc.openTransaction("Import STEP")
try:
    params = {{"file_path": {file_path!r}}}
    created = create_live_result_impl(doc, "import_step", [], params, None)
    doc.commitTransaction()
    _result_ = {{
        "success": True,
        "document": doc.Name,
        "objects": [created["name"]],
    }}
except Exception:
    doc.abortTransaction()
    raise
"""
        result = await bridge.execute_python(code)
        if result.success:
            return result.result
        raise ValueError(result.error_traceback or "STEP import failed")

    @mcp.tool()
    async def part_loft(
        profile_names: list[str],
        solid: bool = True,
        ruled: bool = False,
        closed: bool = False,
        result_name: str | None = None,
        doc_name: str | None = None,
    ) -> dict[str, Any]:
        """Create a loft (transition shape) between multiple profiles.

        LIVE-RESULT fix (2026-09-12, bin (a) of the final PROVE-SWEEP chunk):
        the result is a live Part::FeaturePython that re-lofts its own
        profiles every recompute, extending the same generic wrapper
        fuse_all/common_all/etc. already use -- no new architecture, one
        more operation through it.

        Args:
            profile_names: List of wire/face object names to loft through (in order).
            solid: Whether to create a solid (True) or shell (False). Defaults to True.
            ruled: Whether to create ruled surfaces. Defaults to False.
            closed: Whether to close the loft (connect last to first). Defaults to False.
            result_name: Name for result object. Auto-generated if None.
            doc_name: Document containing the profiles. Uses active document if None.

        Returns:
            Dictionary with created object information: name, label, type_id.
        """
        bridge = await get_bridge()
        code = f"""
from integrations.mcp_tools.live_result import create_live_result_impl

doc = FreeCAD.ActiveDocument if {doc_name!r} is None else FreeCAD.getDocument({doc_name!r})
if doc is None:
    raise ValueError("No document found")

sources = []
for name in {profile_names!r}:
    obj = doc.getObject(name)
    if obj is None:
        raise ValueError(f"Object not found: {{name}}")
    if not hasattr(obj, "Shape") or not obj.Shape.Wires:
        raise ValueError(f"Object has no wires: {{name}}")
    sources.append(obj)

if len(sources) < 2:
    raise ValueError("Need at least 2 profiles for loft")

doc.openTransaction("Part Loft")
try:
    params = {{"solid": {solid}, "ruled": {ruled}, "closed": {closed}}}
    _result_ = create_live_result_impl(doc, "loft", sources, params, {result_name!r} or "Loft")
    doc.commitTransaction()
except Exception:
    doc.abortTransaction()
    raise
"""
        result = await bridge.execute_python(code)
        if result.success:
            return result.result
        raise ValueError(result.error_traceback or "Part loft failed")

    @mcp.tool()
    async def part_sweep(
        profile_name: str,
        spine_name: str,
        solid: bool = True,
        frenet: bool = True,
        result_name: str | None = None,
        doc_name: str | None = None,
    ) -> dict[str, Any]:
        """Sweep a profile along a spine path.

        LIVE-RESULT fix (2026-09-12, bin (a) of the final PROVE-SWEEP chunk):
        see part_loft's own note -- identical fix, the same generic wrapper,
        one more operation.

        Args:
            profile_name: Name of the profile wire/face object.
            spine_name: Name of the spine (path) wire object.
            solid: Whether to create a solid. Defaults to True.
            frenet: Whether to use Frenet mode for orientation. Defaults to True.
            result_name: Name for result object. Auto-generated if None.
            doc_name: Document containing the objects. Uses active document if None.

        Returns:
            Dictionary with created object information: name, label, type_id.
        """
        bridge = await get_bridge()
        code = f"""
from integrations.mcp_tools.live_result import create_live_result_impl

doc = FreeCAD.ActiveDocument if {doc_name!r} is None else FreeCAD.getDocument({doc_name!r})
if doc is None:
    raise ValueError("No document found")

profile_obj = doc.getObject({profile_name!r})
if profile_obj is None:
    raise ValueError(f"Profile object not found: {profile_name!r}")
spine_obj = doc.getObject({spine_name!r})
if spine_obj is None:
    raise ValueError(f"Spine object not found: {spine_name!r}")
if not hasattr(profile_obj, "Shape") or not profile_obj.Shape.Wires:
    raise ValueError("Profile has no wires")
if not hasattr(spine_obj, "Shape") or not spine_obj.Shape.Wires:
    raise ValueError("Spine has no wires")

doc.openTransaction("Part Sweep")
try:
    params = {{"solid": {solid}, "frenet": {frenet}}}
    _result_ = create_live_result_impl(
        doc, "sweep", [profile_obj, spine_obj], params, {result_name!r} or "Sweep",
    )
    doc.commitTransaction()
except Exception:
    doc.abortTransaction()
    raise
"""
        result = await bridge.execute_python(code)
        if result.success:
            return result.result
        raise ValueError(result.error_traceback or "Part sweep failed")
