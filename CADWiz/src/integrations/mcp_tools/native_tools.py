# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Export-and-verify: the step Part 21 requires and the tool layer was missing.

**Correction, 2026-09-06.** The Phase 0 reconciliation recorded (§D.9.2) that
"there is no 3MF export tool among the 152", and Phase 1 was ordered to build
one. That claim was wrong. `export_3mf` has been in `vendor/robust-mcp`'s
`tools/export.py` all along, registered alongside `export_stl`, `export_obj`,
`export_step` and `export_iges`. The error came from the inventory grep used
during the audit - `def [a-z_]*` stops at the digit in `3mf`, so the tool
appeared in that listing as a bare `export_`, and the truncation was read as a
separate tool rather than as a broken pattern.

So there is nothing to build and nothing to duplicate. What Part 21 actually
still lacked is its other half, and it is the half that carries the weight:

    "export must be a verified step, not an afterthought -
     the exported mesh is checked, not assumed."

Every vendored export tool writes a file and reports success on the strength of
having written it. None reads the bytes back. A mesh with holes in it, or one
whose bounding box disagrees with the solid because a unit slipped, returns
success and nothing looks - the same shape of defect the M0 audit found for
renders, and the same fix: make the check part of the operation rather than a
tool someone may remember to call.

This module is that check, applied at `ToolInvoker` so it cannot be bypassed,
in the same place and for the same reason as render-after-op.

**STEP and IGES are skipped, not passed.** They are B-rep formats and the mesh
reader cannot open them, so there is nothing this can honestly assert about
them. A skip is recorded as a skip; claiming a pass for a file nobody read
would be the exact false PASS Part 8 is about.

**M6, 2026-09-07: `register_native_tools` adds three CADWiz-owned tools** --
`export_3mf_native`, `check_wall_thickness`, `check_bed_fit` -- registered
onto the same `FastMCP` instance `ToolInvoker._server()` registers the 152
vendored tools onto, so they run through the identical `call_tool` path
(no second invocation route). `export_3mf_native` does not call the vendored
`export_3mf`; it is a separate, first-party implementation using FreeCAD's
own `Mesh`/`MeshPart` modules directly, held to the same Part 21 predicates
above via `MESH_EXPORT_TOOLS`. The other two are genuinely new capability:
neither existed anywhere before this (the capability inventory,
`docs/reports/2026-09-07-capability-inventory.md`, recorded both as
SPEC-ONLY -- named in the roadmap, zero implementation).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping

from ai_freecad_core.export_check import BoundingBox, verify_export
from ai_freecad_core.production_foundation.contracts import AssertionResult

#: Export tools whose output this can actually read, and the argument naming
#: the file each writes. Verified against vendor/robust-mcp on 2026-09-06.
#: `export_3mf_native` (below) is CADWiz's own tool, not vendored, held to
#: the identical check -- M6, 2026-09-07.
MESH_EXPORT_TOOLS: Mapping[str, str] = {
    "export_stl": "file_path",
    "export_3mf": "file_path",
    "export_3mf_native": "file_path",
}

#: Export tools that write something the mesh reader cannot open. Listed so a
#: reader can see they were considered, and so `is_verifiable_export` does not
#: have to guess from the name.
UNVERIFIABLE_EXPORT_TOOLS: frozenset[str] = frozenset(
    {"export_step", "export_iges", "export_obj"}
)


@dataclass(frozen=True, slots=True)
class ExportVerification:
    """What was checked about a written export file."""

    tool: str
    path: str
    assertions: tuple[AssertionResult, ...] = ()
    skipped_reason: str = ""

    @property
    def ok(self) -> bool:
        """A skipped check is not a failure, and is not a pass either.

        Callers must read `checked` before treating `ok` as evidence. The two
        are separate for the same reason a headless render records
        `render_skipped` instead of quietly passing.
        """
        return all(item.passed for item in self.assertions)

    @property
    def checked(self) -> bool:
        """Whether anything was actually measured."""
        return not self.skipped_reason and bool(self.assertions)

    def failure_summary(self) -> str:
        """Why the export is not usable, in the order the checks ran."""
        return "; ".join(
            f"{item.assertion_id} — {item.detail or item.observed}"
            for item in self.assertions
            if not item.passed
        )


def is_verifiable_export(tool_name: str) -> bool:
    """Whether this tool writes a mesh file the checker can read back."""
    return tool_name in MESH_EXPORT_TOOLS


#: Probes the document for what the export *should* contain.
#:
#: The object selection mirrors `_build_object_selection_code` in
#: `vendor/robust-mcp/src/freecad_mcp/tools/export.py`, read on 2026-09-06:
#: named objects if given, else visible shapes under a GUI, else every shape.
#: It has to match exactly - a probe that picks a different set than the export
#: did would compare the file against the wrong solid and fail a correct export.
_EXPECTATION_SCRIPT = """
import json
import FreeCAD

request = json.loads({payload!r})
names = request["object_names"]

wanted_doc = request["doc_name"]
doc = FreeCAD.ActiveDocument if wanted_doc is None else FreeCAD.getDocument(wanted_doc)
if doc is None:
    raise ValueError("No document found")

if names is not None:
    objects = [doc.getObject(n) for n in names]
elif FreeCAD.GuiUp:
    objects = [
        obj for obj in doc.Objects
        if hasattr(obj, 'Shape') and obj.ViewObject and obj.ViewObject.Visibility
    ]
else:
    objects = [obj for obj in doc.Objects if hasattr(obj, 'Shape')]
objects = [obj for obj in objects if obj is not None and hasattr(obj, 'Shape')]

bounds = None
solids = 0
for item in objects:
    shape = item.Shape
    if shape.isNull():
        continue
    solids += len(shape.Solids)
    box = shape.BoundBox
    values = [box.XMin, box.YMin, box.ZMin, box.XMax, box.YMax, box.ZMax]
    if bounds is None:
        bounds = values
    else:
        bounds = [min(bounds[i], values[i]) for i in range(3)] + [
            max(bounds[3 + i], values[3 + i]) for i in range(3)
        ]

_result_ = {{"bounds": bounds, "solid_count": solids, "object_count": len(objects)}}
"""


async def verify_export_tool_call(
    bridge: Any, tool_name: str, arguments: Mapping[str, Any]
) -> ExportVerification:
    """Read back what an export tool just wrote and hold it to Part 21.

    Never raises. A probe that fails is recorded as a skip with its reason, not
    as a failed export: being unable to measure the solid is a fact about this
    session, not a fault in the file.
    """
    path_argument = MESH_EXPORT_TOOLS.get(tool_name)
    if path_argument is None:
        return ExportVerification(
            tool_name, "", skipped_reason=f"{tool_name} writes a format the checker cannot read"
        )
    target = str(arguments.get(path_argument, "") or "")
    if not target:
        return ExportVerification(tool_name, "", skipped_reason="no file path was given")

    expected_bounds: BoundingBox | None = None
    expected_bodies: int | None = None
    try:
        payload = json.dumps(
            {
                "object_names": arguments.get("object_names"),
                "doc_name": arguments.get("doc_name"),
            }
        )
        probe = await bridge.execute_python(_EXPECTATION_SCRIPT.format(payload=payload))
        if getattr(probe, "success", False) and isinstance(probe.result, dict):
            raw = probe.result.get("bounds")
            if raw and len(raw) == 6:
                expected_bounds = BoundingBox(*(float(value) for value in raw))
            count = probe.result.get("solid_count")
            expected_bodies = int(count) if count else None
    except Exception as error:  # noqa: BLE001 - an unmeasurable solid is not a bad file
        return ExportVerification(
            tool_name, target, skipped_reason=f"could not measure the source solid: {error}"
        )

    assertions = verify_export(
        Path(target),
        expected_bounds=expected_bounds,
        expected_body_count=expected_bodies,
    )
    return ExportVerification(tool_name, target, assertions)


def register_native_tools(mcp: Any, get_bridge: Callable[[], Awaitable[Any]]) -> None:
    """Register CADWiz's own print-readiness tools onto `mcp`.

    Called from `ToolInvoker._server()` right after the vendored 152 -- same
    `FastMCP` instance, same `@mcp.tool()` decorator, same `call_tool` path.
    """

    @mcp.tool()
    async def export_3mf_native(
        file_path: str,
        object_names: list[str] | None = None,
        doc_name: str | None = None,
        mesh_tolerance: float = 0.1,
    ) -> dict[str, Any]:
        """Export objects to 3MF using FreeCAD's own Mesh module, CADWiz-owned.

        A separate implementation from the vendored `export_3mf` (not a
        wrapper around it), so CADWiz controls this code directly rather
        than depending on `vendor/robust-mcp` for a capability the product
        markets as its own (print readiness, M6). Held to the identical
        Part 21 predicates via `MESH_EXPORT_TOOLS` above -- passing this
        check is what "native" has to mean here, not a different bar.

        Args:
            file_path: Path for the output .3mf file.
            object_names: Objects to export. Every shaped object if None.
            doc_name: Document to export from. Active document if None.
            mesh_tolerance: Linear deflection for tessellation. Lower is finer.
        """
        bridge = await get_bridge()
        code = f"""
import Mesh
import MeshPart

doc = FreeCAD.ActiveDocument if {doc_name!r} is None else FreeCAD.getDocument({doc_name!r})
if doc is None:
    raise ValueError("No document found")

names = {object_names!r}
if names:
    objects = [doc.getObject(n) for n in names]
    missing = [n for n, o in zip(names, objects) if o is None]
    if missing:
        raise ValueError(f"objects not found: {{missing}}")
else:
    objects = [
        o for o in doc.Objects
        if getattr(o, "Shape", None) is not None and not o.Shape.isNull()
    ]
if not objects:
    raise ValueError("nothing to export")

meshes = []
for obj in objects:
    shape = getattr(obj, "Shape", None)
    if shape is None or shape.isNull():
        continue
    meshes.append(
        MeshPart.meshFromShape(
            Shape=shape, LinearDeflection={mesh_tolerance}, AngularDeflection=0.5
        )
    )
if not meshes:
    raise ValueError("no exportable shapes among the selected objects")

final_mesh = meshes[0]
for extra in meshes[1:]:
    final_mesh.addMesh(extra)
final_mesh.write({file_path!r})

_result_ = {{
    "success": True,
    "path": {file_path!r},
    "object_count": len(meshes),
    "facet_count": final_mesh.CountFacets,
}}
"""
        result = await bridge.execute_python(code)
        if result.success:
            return result.result
        raise ValueError(result.error_traceback or "3MF export failed")

    @mcp.tool()
    async def check_wall_thickness(
        object_name: str,
        minimum_mm: float,
        doc_name: str | None = None,
    ) -> dict[str, Any]:
        """Flag walls thinner than a stated minimum, M6's print-readiness check.

        **Measures opposing planar faces only.** For every pair of planar
        faces whose normals point at each other (anti-parallel) and whose
        bounding boxes overlap, the perpendicular distance between the two
        planes is a wall thickness measurement; the minimum found across all
        such pairs is reported. This catches the common case directly --
        a flat wall milled or pocketed too thin -- and is stated as a
        boundary, not hidden: a curved or organic wall (a filleted shell, a
        swept tube) is not measured by this check and is not claimed to be.

        Args:
            object_name: Name of the solid to check.
            minimum_mm: The stated minimum wall thickness, in millimetres.
            doc_name: Document containing the object. Active document if None.

        Returns:
            success: whether the minimum found (if any) meets `minimum_mm`.
            minimum_thickness_mm: the smallest opposing-planar-face gap found,
                or None if no measurable opposing pair exists.
            pairs_checked: how many opposing planar-face pairs were measured.
        """
        bridge = await get_bridge()
        code = f"""
doc = FreeCAD.ActiveDocument if {doc_name!r} is None else FreeCAD.getDocument({doc_name!r})
if doc is None:
    raise ValueError("No document found")
obj = doc.getObject({object_name!r})
if obj is None:
    raise ValueError(f"object not found: {object_name!r}")
shape = getattr(obj, "Shape", None)
if shape is None or shape.isNull():
    raise ValueError(f"{object_name!r} has no shape")

planar = []
for face in shape.Faces:
    try:
        if face.Surface.isPlanar():
            planar.append(face)
    except Exception:
        pass

minimum_thickness = None
pairs_checked = 0

def _dominant_axis(vector):
    components = (abs(vector.x), abs(vector.y), abs(vector.z))
    return components.index(max(components))

def _axis_range(bbox, axis):
    if axis == 0:
        return bbox.XMin, bbox.XMax
    if axis == 1:
        return bbox.YMin, bbox.YMax
    return bbox.ZMin, bbox.ZMax

for i, face_a in enumerate(planar):
    normal_a = face_a.normalAt(0, 0)
    center_a = face_a.CenterOfMass
    box_a = face_a.BoundBox
    # Two opposing faces are, by definition, separated *along* their shared
    # normal's dominant axis -- their extent never overlaps there. Overlap
    # only needs checking in the other two axes; checking all three (as an
    # earlier version of this probe did) always found the pair "not
    # overlapping" on the separation axis and silently measured nothing.
    # Measured on a 40x30x20 Part::Box, 2026-09-07: the bug reported 0 pairs
    # checked on a plain solid box; this fix reports 3, minimum 20mm.
    skip_axis = _dominant_axis(normal_a)
    check_axes = tuple(axis for axis in range(3) if axis != skip_axis)
    for face_b in planar[i + 1:]:
        normal_b = face_b.normalAt(0, 0)
        if normal_a.dot(normal_b) > -0.999:
            continue
        box_b = face_b.BoundBox
        overlap = True
        for axis in check_axes:
            a_min, a_max = _axis_range(box_a, axis)
            b_min, b_max = _axis_range(box_b, axis)
            if a_max < b_min or b_max < a_min:
                overlap = False
                break
        if not overlap:
            continue
        distance = abs((face_b.CenterOfMass - center_a).dot(normal_a))
        if distance < 1e-6:
            continue
        pairs_checked += 1
        if minimum_thickness is None or distance < minimum_thickness:
            minimum_thickness = distance

_result_ = {{
    "minimum_thickness_mm": minimum_thickness,
    "pairs_checked": pairs_checked,
}}
"""
        probe = await bridge.execute_python(code)
        if not probe.success:
            raise ValueError(probe.error_traceback or "wall-thickness probe failed")
        minimum = probe.result["minimum_thickness_mm"]
        return {
            "success": minimum is not None and minimum >= minimum_mm,
            "minimum_thickness_mm": minimum,
            "stated_minimum_mm": minimum_mm,
            "pairs_checked": probe.result["pairs_checked"],
        }

    @mcp.tool()
    async def check_bed_fit(
        object_name: str,
        bed_x_mm: float,
        bed_y_mm: float,
        bed_z_mm: float,
        doc_name: str | None = None,
    ) -> dict[str, Any]:
        """Whether an object's bounding box fits a stated printer bed volume.

        **As-oriented only.** Checks the object's current bounding box
        against the stated bed in its current placement; it does not search
        rotations that might make an object fit that does not fit as
        oriented. Stated here rather than silently assumed away.

        Args:
            object_name: Name of the solid to check.
            bed_x_mm: Bed width, in millimetres.
            bed_y_mm: Bed depth, in millimetres.
            bed_z_mm: Maximum print height, in millimetres.
            doc_name: Document containing the object. Active document if None.
        """
        bridge = await get_bridge()
        code = f"""
doc = FreeCAD.ActiveDocument if {doc_name!r} is None else FreeCAD.getDocument({doc_name!r})
if doc is None:
    raise ValueError("No document found")
obj = doc.getObject({object_name!r})
if obj is None:
    raise ValueError(f"object not found: {object_name!r}")
shape = getattr(obj, "Shape", None)
if shape is None or shape.isNull():
    raise ValueError(f"{object_name!r} has no shape")
box = shape.BoundBox
_result_ = {{"x_mm": box.XLength, "y_mm": box.YLength, "z_mm": box.ZLength}}
"""
        probe = await bridge.execute_python(code)
        if not probe.success:
            raise ValueError(probe.error_traceback or "bed-fit probe failed")
        measured = probe.result
        overflow = {
            axis: max(0.0, measured[f"{axis}_mm"] - bed)
            for axis, bed in (("x", bed_x_mm), ("y", bed_y_mm), ("z", bed_z_mm))
        }
        fits = all(value <= 0.0 for value in overflow.values())
        return {
            "success": fits,
            "object_mm": measured,
            "bed_mm": {"x": bed_x_mm, "y": bed_y_mm, "z": bed_z_mm},
            "overflow_mm": overflow,
        }
