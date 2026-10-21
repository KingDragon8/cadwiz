# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""PRINT-PREP: assembly -> expert plate layout (M6 Print Readiness, T1, 2026-09-08).

SPLIT -> ORIENT -> ARRANGE -> ADVISE -> EXPORT, in three tools:
`split_printable_parts`, `plan_print_layout`, `export_print_plates`.

**What "printable" means, decided once, not guessed per object.** A
`PartDesign::Body`'s own `.Tip` property is FreeCAD's own answer to "the one
solid this Body was built to produce" -- every feature in a Body's chain
exists to shape that Tip. SPLIT operates on Body objects only: purchased
hardware (`*_HARDWARE`, `*_LINK` objects referencing screws/bolts/washers),
clearance/reference envelopes (`*Envelope`, `*_REFERENCE`,
`PHONE_CONTACT_PLANE`), and assembly-level links/joints are excluded by
construction -- they were never inside a Body's own Tip chain, not filtered
out by a name-pattern guess. Confirmed 2026-09-08 against the qualification
target (`CADW-S3-PIVOT3-PHONE-PLANE-20260830T234002Z`): exactly 4 of its 117
objects are `PartDesign::Body`, each with a clean single-solid Tip -- the
clamp, both arms, and the phone mount, matching the real physical BOM.

**Overhang and support volume are stated estimates, not slicer output.**
`evaluate_orientations` tessellates each candidate orientation
(`MeshPart.meshFromShape`) and classifies facets by their own normal versus
the print axis (steeper than 45 degrees from horizontal, excluding facets
already resting on the bed, is the standard FDM overhang threshold). Support
volume approximates each overhang facet's own material as a column from the
facet down to the bed, scaled by `_SUPPORT_INFILL_FRACTION` (a stated 15%
sparse-support-density assumption, not a measured constant) -- disclosed
here so nobody downstream mistakes it for a real slicer's own number.
"""

from __future__ import annotations

import json
import math
from typing import Any, Awaitable, Callable, Sequence

Polygon = Sequence[tuple[float, float]]

#: Generic corner keep-out size, in mm -- NOT a measured dimension of any
#: specific printer. A stand-in for "this printer profile has bed clips or a
#: BLTouch mount near the corners" when a caller does not supply the real
#: printer's own `machine_disallowed_areas`. T1 bug fix, 2026-09-13: ARRANGE
#: previously had no keep-out concept at all and packed starting at raw bed
#: origin (0, 0) -- Cura's own build-volume check correctly refused to slice
#: ("Unable to slice") the moment a real printer profile marked that corner
#: disallowed. Labelled here so nobody mistakes this placeholder for a real
#: printer's own measured geometry (CLAUDE.md: never fabricate a number that
#: looks measured).
DEFAULT_DISALLOWED_CORNER_MM = 20.0

#: Default keep-in-from-every-edge margin, matching the founder's own stated
#: default.
DEFAULT_EDGE_MARGIN_MM = 10.0


def default_disallowed_areas(bed_x: float, bed_y: float) -> tuple[Polygon, ...]:
    """Four generic corner keep-out squares -- see `DEFAULT_DISALLOWED_CORNER_MM`.

    Used only when a caller does not supply `disallowed_areas` explicitly;
    real qualification against a real printer should pass that printer's own
    `machine_disallowed_areas` (Cura's own definition format, bed-corner-
    origin here rather than Cura's bed-center-origin -- converted at the one
    place that talks to Cura, not carried through this module's own math).
    """
    c = min(DEFAULT_DISALLOWED_CORNER_MM, bed_x / 2.0, bed_y / 2.0)
    return (
        ((0.0, 0.0), (c, 0.0), (c, c), (0.0, c)),
        ((bed_x - c, 0.0), (bed_x, 0.0), (bed_x, c), (bed_x - c, c)),
        ((0.0, bed_y - c), (c, bed_y - c), (c, bed_y), (0.0, bed_y)),
        ((bed_x - c, bed_y - c), (bed_x, bed_y - c), (bed_x, bed_y), (bed_x - c, bed_y)),
    )


def _polygon_bbox(polygon: Polygon) -> tuple[float, float, float, float]:
    xs = [p[0] for p in polygon]
    ys = [p[1] for p in polygon]
    return min(xs), min(ys), max(xs), max(ys)


def usable_rect(
    bed_x: float, bed_y: float, edge_margin: float, disallowed_areas: Sequence[Polygon],
) -> tuple[float, float, float, float]:
    """The rectangle ARRANGE may actually pack into: the bed inset by
    `edge_margin` on every side, inset FURTHER on any side a disallowed
    area's own bounding box touches (within 1e-6mm) -- a bed-clip strip at
    the back edge pushes the usable rectangle's own top down to clear it,
    a corner keep-out pushes in on both the side and the top/bottom it
    touches. Deliberately conservative and deliberately not a general
    polygon-avoiding packer: a disallowed area that does NOT touch any bed
    edge (an island in the middle of the bed) is not handled by this inset
    -- real printer keep-outs are overwhelmingly edge/corner features (bed
    clips, mounts, connectors), and `plan_print_layout_impl`'s own final
    `footprint_intersects_disallowed` pass still catches the general case
    by refusing to return a plan that collides, rather than silently
    shipping one.
    """
    left = bottom = right_inset = top_inset = edge_margin
    for polygon in disallowed_areas:
        pxmin, pymin, pxmax, pymax = _polygon_bbox(polygon)
        spans_full_width = pxmin <= 1e-6 and pxmax >= bed_x - 1e-6
        spans_full_depth = pymin <= 1e-6 and pymax >= bed_y - 1e-6
        # A polygon spanning the full width (an Ender-3-style bed-clip
        # strip running edge to edge) touches x=0 AND x=bed_x at once --
        # that is a Y-axis constraint only (nothing to its "left" or
        # "right" to shift into, it blocks the whole width at that Y
        # range); treating it as also insetting X would be wrong.
        # Symmetric for a polygon spanning the full depth.
        if spans_full_width and not spans_full_depth:
            if pymin <= 1e-6:
                bottom = max(bottom, pymax)
            if pymax >= bed_y - 1e-6:
                top_inset = max(top_inset, bed_y - pymin)
            continue
        if spans_full_depth and not spans_full_width:
            if pxmin <= 1e-6:
                left = max(left, pxmax)
            if pxmax >= bed_x - 1e-6:
                right_inset = max(right_inset, bed_x - pxmin)
            continue
        # A genuine corner/localized feature (does not span either full
        # axis): apply the ordinary per-edge touch logic to every edge it
        # touches.
        if pxmin <= 1e-6:
            left = max(left, pxmax)
        if pxmax >= bed_x - 1e-6:
            right_inset = max(right_inset, bed_x - pxmin)
        if pymin <= 1e-6:
            bottom = max(bottom, pymax)
        if pymax >= bed_y - 1e-6:
            top_inset = max(top_inset, bed_y - pymin)
    return left, bottom, bed_x - right_inset, bed_y - top_inset


def _aabb_overlaps(
    ax0: float, ay0: float, ax1: float, ay1: float,
    bx0: float, by0: float, bx1: float, by1: float,
) -> bool:
    return ax0 < bx1 and ax1 > bx0 and ay0 < by1 and ay1 > by0


def footprint_intersects_disallowed(
    plate_x: float, plate_y: float, width: float, depth: float,
    disallowed_areas: Sequence[Polygon],
) -> bool:
    """Whether a part's own footprint rectangle (its bounding box, at its
    final plate position) overlaps ANY disallowed area's own bounding box.
    Conservative (bbox vs bbox, not exact polygon vs polygon) -- a real
    collision is never missed; a non-rectangular disallowed area could in
    principle produce a false positive against a part that actually clears
    it, which is the safe direction to be wrong in."""
    px0, py0, px1, py1 = plate_x, plate_y, plate_x + width, plate_y + depth
    for polygon in disallowed_areas:
        dx0, dy0, dx1, dy1 = _polygon_bbox(polygon)
        if _aabb_overlaps(px0, py0, px1, py1, dx0, dy0, dx1, dy1):
            return True
    return False

# ---- SPLIT ------------------------------------------------------------------


def find_printable_bodies(doc: Any) -> list[dict[str, Any]]:
    """Every `PartDesign::Body` in `doc`, with its own Tip and a decision."""
    decisions: list[dict[str, Any]] = []
    for obj in doc.Objects:
        if obj.TypeId != "PartDesign::Body":
            continue
        tip = obj.Tip
        if tip is None:
            decisions.append({
                "body_name": obj.Name, "tip_name": "", "decision": "exclude",
                "reason": "Body has no Tip (empty feature chain) -- nothing to print",
            })
            continue
        shape = getattr(tip, "Shape", None)
        if shape is None or shape.isNull() or not shape.isValid():
            decisions.append({
                "body_name": obj.Name, "tip_name": tip.Name, "decision": "exclude",
                "reason": f"Tip {tip.Name!r} has no valid solid Shape",
            })
            continue
        if len(shape.Solids) != 1:
            decisions.append({
                "body_name": obj.Name, "tip_name": tip.Name, "decision": "exclude",
                "reason": f"Tip {tip.Name!r} has {len(shape.Solids)} solids, not exactly 1 -- "
                          "SPLIT produces one printable part per solid, not per Body, when a "
                          "Body's own Tip is itself multi-solid",
            })
            continue
        decisions.append({
            "body_name": obj.Name, "tip_name": tip.Name, "decision": "include",
            "reason": f"Body {obj.Name!r}'s own Tip {tip.Name!r} is a single valid solid "
                      f"(volume {shape.Volume:.2f} mm3) -- the one shape this Body exists to produce",
        })
    return decisions


def _excluded_summary(doc: Any) -> dict[str, int]:
    """A coarse tally of what SPLIT did not touch and why, for the report --
    not a per-object decision (only Bodies get those), just a count so a
    reader can see nothing was silently dropped."""
    hardware = envelope = link = joint = other_shaped = 0
    for obj in doc.Objects:
        if obj.TypeId == "PartDesign::Body":
            continue
        name_upper = obj.Name.upper()
        if obj.TypeId == "App::Link":
            link += 1
        elif obj.TypeId.startswith("Assembly::"):
            joint += 1
        elif "HARDWARE" in name_upper or "_SCREW" in name_upper or "_NUT" in name_upper or "_WASHER" in name_upper:
            hardware += 1
        elif "ENVELOPE" in name_upper or "REFERENCE" in name_upper or "CONTACT_PLANE" in name_upper:
            envelope += 1
        elif getattr(obj, "Shape", None) is not None and not obj.Shape.isNull():
            other_shaped += 1
    return {
        "hardware_or_fastener": hardware, "envelope_or_reference": envelope,
        "assembly_link": link, "assembly_joint_or_group": joint,
        "other_shaped_not_a_body_tip": other_shaped,
    }


def split_printable_parts_impl(doc: Any, name_prefix: str) -> dict[str, Any]:
    """Create one frozen `Part::Feature` per printable Body's own Tip.

    A frozen copy, not a live link: ORIENT and ARRANGE need to rotate and
    translate each part independently for plate layout, and doing that to
    the Body's own Tip would move the parametric model itself. `SourceBody`
    and `SourceTip` (plain string properties) keep the traceable name back
    to the model this came from -- "preserving names" the way a frozen BREP
    export always must, not a live parametric link (no such link would
    survive a real slicer import anyway).

    A Body's Tip feature holds its geometry in the Body's own *local*
    frame -- confirmed 2026-09-10: `tip.Shape.Placement` is identity and
    `tip.Shape.BoundBox` sits at the local origin even when the Body itself
    is placed elsewhere in the assembly, because a Body's child features
    are always authored relative to the Body, not the document. Copying
    `tip.Shape` alone therefore drops the Body's own position in the
    assembly -- every part SPLIT produced landed stacked at the world
    origin regardless of where its source Body actually sat, which is
    wrong for the slicer and also defeats ARRANGE/verification's tier-1
    bounding-box check (every pair's boxes trivially overlapped at the
    origin, forcing the expensive tiers on every pair). `body.
    getGlobalPlacement()` is FreeCAD's own accessor for a Body's full world
    transform -- Body's own Placement plus whatever container chain (an
    App::Link, a nested App::Part) it sits inside -- so the copied shape is
    placed with that, not just `body.Placement`, which would miss a
    container's own transform.
    """
    decisions = find_printable_bodies(doc)
    parts: list[dict[str, Any]] = []
    for entry in decisions:
        if entry["decision"] != "include":
            continue
        tip = doc.getObject(entry["tip_name"])
        body = doc.getObject(entry["body_name"])
        part_name = f"{name_prefix}_{entry['body_name']}"
        part = doc.addObject("Part::Feature", part_name)
        shape = tip.Shape.copy()
        shape.Placement = body.getGlobalPlacement().multiply(shape.Placement)
        part.Shape = shape
        part.addProperty("App::PropertyString", "SourceBody", "PrintPrep", "")
        part.SourceBody = entry["body_name"]
        part.addProperty("App::PropertyString", "SourceTip", "PrintPrep", "")
        part.SourceTip = entry["tip_name"]
        doc.recompute()
        parts.append({
            "part_name": part.Name, "source_body": entry["body_name"],
            "source_tip": entry["tip_name"], "volume_mm3": part.Shape.Volume,
        })
    return {
        "parts": parts,
        "decisions": decisions,
        "excluded_summary": _excluded_summary(doc),
    }


# ---- ORIENT -------------------------------------------------------------

#: Facet normals steeper than this from horizontal need support underneath
#: (measured from the +Z print axis; a facet whose normal points more than
#: 45 degrees away from straight down is considered self-supporting -- the
#: standard FDM 45-degree rule of thumb).
_OVERHANG_ANGLE_DEG = 45.0
#: Sparse-support-density assumption for the support-volume estimate -- a
#: stated planning number, not a measured constant. Typical slicer defaults
#: run 10-20%; 15% is the middle of that range.
_SUPPORT_INFILL_FRACTION = 0.15
#: A facet within this many mm of the shape's own lowest Z is "resting on
#: the bed", not an overhang needing support underneath it.
_BED_CONTACT_TOLERANCE_MM = 0.05


def _candidate_rotations(shape: Any) -> list[dict[str, Any]]:
    """One candidate per distinct planar-face outward normal (largest faces
    first), plus the shape's own as-modeled orientation (identity) -- the
    founder's own starting heuristic, "largest flat face down", as the
    first candidate tried, evaluated against the rest rather than assumed
    to win."""
    import FreeCAD  # noqa: PLC0415

    seen_normals: list[Any] = []
    candidates: list[dict[str, Any]] = [{
        "label": "as-modeled (identity)", "normal": FreeCAD.Vector(0, 0, -1),
        "rotation": FreeCAD.Rotation(), "source_area": 0.0,
    }]
    try:
        shape_center = shape.CenterOfMass
    except AttributeError:
        # `Part.Compound` (SPLIT's own frozen copies wrap their one real
        # solid in a Compound, confirmed 2026-09-09) has no CenterOfMass
        # of its own on this FreeCAD build -- only Solid/Face/Shell do.
        # The Compound is documented, by SPLIT's own contract, to wrap
        # exactly one solid, so that solid's own center is the right
        # answer, not an approximation; BoundBox.Center is kept only as a
        # last-resort fallback for a shape with no Solids at all.
        solids = shape.Solids
        shape_center = solids[0].CenterOfMass if solids else shape.BoundBox.Center
    planar_faces = []
    for index, face in enumerate(shape.Faces):
        surface = face.Surface
        if type(surface).__name__ != "Plane":
            continue
        normal = face.normalAt(0, 0)
        if face.Orientation == "Reversed":
            normal = normal * -1
        # `Orientation`-based flipping alone is not reliable -- confirmed
        # 2026-09-09 on a plain `Part.makeBox(30, 20, 10)`: the largest
        # face (600 mm2, Forward orientation, no flip applied) came back
        # with normal (0, 0, 1) even though its own center sits at the
        # shape's z_min, i.e. pointing INTO the solid, not away from it.
        # Rotating that face "down" by aligning its (wrong-way) normal to
        # -Z put it at the top of the rotated bounding box instead of the
        # bottom, which then fed a completely inverted contact_area into
        # ORIENT's own tie-break (the smallest, least-stable face won).
        # A face's own center offset from the shape's overall centroid is
        # a second, independent check: for a convex-ish solid a true
        # outward normal always points away from that centroid, the same
        # sanity check FILLET-PRO's own convexity classifier
        # (classify_convexity, PROVE-017) relies on elsewhere in this
        # program.
        if normal.dot(face.CenterOfMass - shape_center) < 0:
            normal = -normal
        planar_faces.append((index, face, normal))
    planar_faces.sort(key=lambda item: item[1].Area, reverse=True)
    for index, face, normal in planar_faces[:8]:
        if any(normal.dot(other) > 0.999 for other in seen_normals):
            continue
        seen_normals.append(normal)
        target = FreeCAD.Vector(0, 0, -1)
        axis = normal.cross(target)
        if axis.Length < 1e-9:
            rotation = FreeCAD.Rotation() if normal.dot(target) > 0 else FreeCAD.Rotation(
                FreeCAD.Vector(1, 0, 0), 180
            )
        else:
            angle = math.degrees(math.acos(max(-1.0, min(1.0, normal.dot(target)))))
            rotation = FreeCAD.Rotation(axis, angle)
        candidates.append({
            "label": f"Face{index + 1} down (area {face.Area:.1f} mm2)",
            "normal": normal, "rotation": rotation, "source_area": face.Area,
        })
    return candidates


def _score_orientation(shape: Any, rotation: Any) -> dict[str, Any]:
    """Tessellate `shape` rotated by `rotation` and measure overhang area,
    estimated support volume, and bed-contact area -- real geometry, not a
    guess from the candidate face's own area."""
    import FreeCAD  # noqa: PLC0415
    import MeshPart  # noqa: PLC0415

    rotated = shape.copy()
    rotated.Placement = FreeCAD.Placement(FreeCAD.Vector(0, 0, 0), rotation)
    bbox = rotated.BoundBox
    z_min = bbox.ZMin
    # Coarse on purpose: this tessellation only feeds an overhang/support
    # AREA estimate, evaluated once per candidate orientation (several per
    # part) -- the fine mesh a slicer or the final STL export needs is a
    # different job (`_mesh_for`'s own default 0.1mm, used only there).
    # Measured 2026-09-08: 0.5mm deflection on the qualification target's
    # own arms/mount made this loop the dominant cost of the whole plan.
    mesh = MeshPart.meshFromShape(Shape=rotated, LinearDeflection=1.5, AngularDeflection=0.8)
    overhang_area = 0.0
    support_volume = 0.0
    contact_area = 0.0
    down = FreeCAD.Vector(0, 0, -1)
    cos_threshold = math.cos(math.radians(_OVERHANG_ANGLE_DEG))
    for facet in mesh.Facets:
        normal = FreeCAD.Vector(*facet.Normal)
        points = facet.Points
        facet_z_min = min(p[2] for p in points)
        facet_z_max = max(p[2] for p in points)
        area = facet.Area
        # A facet counts as bed contact only when its OWN highest point is
        # also near z_min, not merely its lowest -- confirmed 2026-09-09: a
        # coarse tessellation (LinearDeflection=1.5) splits each vertical
        # side face into two triangles sharing the bottom edge's corners,
        # so `min(p[2] ...) <= z_min + tolerance` alone flagged BOTH
        # triangles of every side wall as "in contact", one vertex away
        # from the bed being enough to count the triangle's WHOLE area --
        # even though it climbs the full height of the part. That made a
        # box's smallest end-face (standing it on end, the least stable
        # choice) report MORE contact area than its largest face lying
        # flat, inverting ORIENT's own stability tie-break. Requiring the
        # facet's own highest point to be flat too keeps only the genuinely
        # horizontal, bed-level triangles.
        if facet_z_min <= z_min + _BED_CONTACT_TOLERANCE_MM and facet_z_max <= z_min + _BED_CONTACT_TOLERANCE_MM:
            contact_area += area
            continue
        downward = normal.dot(down)
        if downward >= cos_threshold:
            avg_z = sum(p[2] for p in points) / 3.0
            overhang_area += area
            support_volume += area * max(0.0, avg_z - z_min) * _SUPPORT_INFILL_FRACTION
    return {
        "overhang_area_mm2": overhang_area,
        "support_volume_mm3": support_volume,
        "contact_area_mm2": contact_area,
        "footprint_x_mm": bbox.XLength,
        "footprint_y_mm": bbox.YLength,
        "height_mm": bbox.ZLength,
        "total_surface_area_mm2": rotated.Area,
    }


def evaluate_orientations(shape: Any) -> dict[str, Any]:
    """Try every candidate orientation, pick the one with the least
    estimated support volume (ties broken by larger bed contact -- better
    first-layer adhesion), and log every candidate tried, not just the
    winner."""
    candidates = _candidate_rotations(shape)
    evaluated = []
    for candidate in candidates:
        measured = _score_orientation(shape, candidate["rotation"])
        evaluated.append({"label": candidate["label"], **measured, "_rotation": candidate["rotation"]})
    evaluated.sort(key=lambda item: (item["support_volume_mm3"], -item["contact_area_mm2"]))
    winner = evaluated[0]
    runners_up = [
        {key: value for key, value in item.items() if key != "_rotation"}
        for item in evaluated[1:]
    ]
    return {
        "chosen": {key: value for key, value in winner.items() if key != "_rotation"},
        "chosen_rotation": winner["_rotation"],
        "runners_up": runners_up,
    }


# ---- ARRANGE + ADVISE -----------------------------------------------------


def _pack_plates(
    footprints: list[dict[str, Any]], bed_x: float, bed_y: float, spacing: float,
    *, usable: tuple[float, float, float, float] | None = None,
) -> list[list[dict[str, Any]]]:
    """Greedy shelf packing, largest footprint first: fill a row left to
    right until the next part would not fit, start a new row, start a new
    plate when a row will not fit under the current one either. Not
    optimal bin-packing (an NP-hard problem this planner does not need to
    solve exactly) -- a defensible, deterministic, expert-plausible layout,
    in print order.

    `usable` is the `(x0, y0, x1, y1)` rectangle to pack into (see
    `usable_rect`) -- everything is packed shelf-style within it as if it
    were the whole bed, then EACH PLATE's own used extent is centered
    within that rectangle (T1 bug fix, 2026-09-13: ARRANGE previously
    always started at raw bed origin (0, 0), which a real printer profile
    can mark disallowed). Defaults to the full bed with no margin, for
    callers that have not adopted a printer profile yet.
    """
    x0, y0, x1, y1 = usable if usable is not None else (0.0, 0.0, bed_x, bed_y)
    usable_width, usable_depth = x1 - x0, y1 - y0
    ordered = sorted(footprints, key=lambda item: item["footprint_x_mm"] * item["footprint_y_mm"], reverse=True)
    plates: list[list[dict[str, Any]]] = []
    plate: list[dict[str, Any]] = []
    cursor_x = cursor_y = 0.0
    row_height = 0.0
    for item in ordered:
        width, depth = item["footprint_x_mm"], item["footprint_y_mm"]
        if width > usable_width or depth > usable_depth:
            # Does not fit this bed's own usable area at all, in this
            # orientation -- placed alone on its own plate rather than
            # silently dropped. Left at the usable rect's own corner, not
            # centered: an oversized part is already a defect the caller
            # must see, not one worth polishing the placement of.
            if plate:
                plates.append(_center_plate(plate, x0, y0, usable_width, usable_depth))
            plates.append([{**item, "plate_x_mm": x0, "plate_y_mm": y0, "oversized": True}])
            plate = []
            cursor_x = cursor_y = row_height = 0.0
            continue
        if cursor_x + width > usable_width:
            cursor_x = 0.0
            cursor_y += row_height + spacing
            row_height = 0.0
        if cursor_y + depth > usable_depth:
            plates.append(_center_plate(plate, x0, y0, usable_width, usable_depth))
            plate = []
            cursor_x = cursor_y = row_height = 0.0
        plate.append({**item, "plate_x_mm": cursor_x, "plate_y_mm": cursor_y, "oversized": False})
        cursor_x += width + spacing
        row_height = max(row_height, depth)
    if plate:
        plates.append(_center_plate(plate, x0, y0, usable_width, usable_depth))
    return plates


def _center_plate(
    plate: list[dict[str, Any]], x0: float, y0: float, usable_width: float, usable_depth: float,
) -> list[dict[str, Any]]:
    """Shift one plate's own packed items (still in shelf-relative
    coordinates, origin at the shelf's own corner) so the plate's own used
    extent sits centered within the usable rectangle, then into world/bed
    coordinates via `x0`/`y0`. A plate using less than the full usable
    area is centered rather than left pinned to one corner -- what "arrange
    must center the plate on the bed" means when there is more than one
    part on the plate, not just a single part centered alone."""
    used_x1 = max(item["plate_x_mm"] + item["footprint_x_mm"] for item in plate)
    used_y1 = max(item["plate_y_mm"] + item["footprint_y_mm"] for item in plate)
    center_dx = (usable_width - used_x1) / 2.0
    center_dy = (usable_depth - used_y1) / 2.0
    return [
        {**item, "plate_x_mm": x0 + center_dx + item["plate_x_mm"], "plate_y_mm": y0 + center_dy + item["plate_y_mm"]}
        for item in plate
    ]


def advise_part(measured: dict[str, Any]) -> dict[str, Any]:
    """Brim/raft, supports, wall/infill -- each derived from a number this
    module actually measured for this part's own chosen orientation, not a
    fixed rule of thumb applied blind."""
    height = measured["height_mm"]
    contact_area = measured["contact_area_mm2"]
    footprint_area = measured["footprint_x_mm"] * measured["footprint_y_mm"]
    overhang_area = measured["overhang_area_mm2"]
    total_area = max(measured["total_surface_area_mm2"], 1e-9)
    volume = measured["volume_mm3"]

    adhesion = "raft" if footprint_area > 0 and contact_area < 0.05 * footprint_area else (
        "brim" if contact_area > 0 and height / math.sqrt(contact_area) > 4.0 else "none"
    )
    supports = overhang_area > 0.02 * total_area

    # Average wall proxy: volume / surface area approximates a shell's own
    # thickness for a roughly-uniform-wall part -- thinner suggests more
    # perimeters for strength, per common FDM guidance (not a fabricated
    # number: it is literally this part's own volume-to-area ratio).
    avg_thickness_proxy = volume / total_area if total_area > 0 else 0.0
    if avg_thickness_proxy < 3.0:
        walls, infill = 4, 30
    else:
        walls, infill = 3, 20

    why_parts = [f"chosen face: {measured['label']}"]
    if supports:
        why_parts.append(f"{overhang_area:.0f} mm2 overhangs beyond {_OVERHANG_ANGLE_DEG:.0f} degrees")
    if adhesion != "none":
        why_parts.append(f"bed contact {contact_area:.0f} mm2 vs {height:.0f} mm height")

    return {
        "adhesion": adhesion,
        "supports": supports,
        "wall_count": walls,
        "infill_percent": infill,
        "why": "; ".join(why_parts),
    }


def plan_print_layout_impl(
    doc: Any, part_names: list[str], bed_x: float, bed_y: float, bed_z: float, spacing: float,
    edge_margin: float = DEFAULT_EDGE_MARGIN_MM, disallowed_areas: Sequence[Polygon] | None = None,
) -> dict[str, Any]:
    """ORIENT each part, ARRANGE onto one or more plates, ADVISE each part
    -- all three, since a plate assignment cannot be chosen before every
    part's own footprint (which depends on its own chosen orientation) is
    known.

    T1 bug fix, 2026-09-13: ARRANGE previously packed starting at raw bed
    origin (0, 0) with no margin or keep-out concept at all. `edge_margin`
    (default 10mm) and `disallowed_areas` (default: four generic corner
    keep-outs, `default_disallowed_areas` -- pass a real printer's own
    `machine_disallowed_areas` for an accurate plan) now define the
    rectangle `_pack_plates` packs into and centers within (`usable_rect`);
    a final pass (`footprint_intersects_disallowed`) refuses to return a
    plan where any part's own footprint still overlaps a disallowed area,
    rather than silently shipping one.
    """
    import FreeCAD  # noqa: PLC0415

    areas = tuple(disallowed_areas) if disallowed_areas is not None else default_disallowed_areas(bed_x, bed_y)
    usable = usable_rect(bed_x, bed_y, edge_margin, areas)
    usable_x0, usable_y0, usable_x1, usable_y1 = usable
    if usable_x1 <= usable_x0 or usable_y1 <= usable_y0:
        raise ValueError(
            f"edge_margin={edge_margin}mm plus this bed's own disallowed areas leave no usable printable "
            f"area on a {bed_x}x{bed_y}mm bed"
        )

    per_part: dict[str, Any] = {}
    footprints: list[dict[str, Any]] = []
    for name in part_names:
        obj = doc.getObject(name)
        if obj is None:
            raise ValueError(f"part not found: {name!r}")
        evaluation = evaluate_orientations(obj.Shape)
        chosen = evaluation["chosen"]
        chosen["volume_mm3"] = obj.Shape.Volume
        chosen["part_name"] = name
        oversized = (
            chosen["footprint_x_mm"] > usable_x1 - usable_x0
            or chosen["footprint_y_mm"] > usable_y1 - usable_y0
        )
        if chosen["height_mm"] > bed_z:
            oversized = True
        advice = advise_part(chosen)
        per_part[name] = {
            "chosen_orientation": {k: v for k, v in chosen.items() if k not in ("part_name",)},
            "runners_up": evaluation["runners_up"],
            "advice": advice,
            "rotation": evaluation["chosen_rotation"],
            "height_exceeds_bed_z": chosen["height_mm"] > bed_z,
        }
        footprints.append(chosen)

    plates = _pack_plates(footprints, bed_x, bed_y, spacing, usable=usable)

    for plate in plates:
        for item in plate:
            if item.get("oversized"):
                continue
            if footprint_intersects_disallowed(
                item["plate_x_mm"], item["plate_y_mm"],
                item["footprint_x_mm"], item["footprint_y_mm"], areas,
            ):
                raise ValueError(
                    f"{item['part_name']}'s own footprint at ({item['plate_x_mm']:.1f}, "
                    f"{item['plate_y_mm']:.1f}) still intersects a disallowed area after ARRANGE -- "
                    "usable_rect's own edge-touching inset does not cover a keep-out that does not "
                    "touch any bed edge; refusing to return a plan that would not actually slice"
                )

    plates_out: list[dict[str, Any]] = []
    for plate_index, plate in enumerate(plates):
        plate_names = []
        for item in plate:
            name = item["part_name"]
            obj = doc.getObject(name)
            info = per_part[name]
            obj.Placement = FreeCAD.Placement(FreeCAD.Vector(0, 0, 0), info["rotation"])
            bbox = obj.Shape.BoundBox
            obj.Placement.Base = FreeCAD.Vector(
                item["plate_x_mm"] - bbox.XMin, item["plate_y_mm"] - bbox.YMin, -bbox.ZMin,
            )
            if "PrintPlate" not in obj.PropertiesList:
                # `Part::Feature` (SPLIT's own frozen-copy type) has no
                # `hasProperty()` method -- confirmed 2026-09-09,
                # AttributeError; `PropertiesList` membership is the
                # generic, always-available check.
                obj.addProperty("App::PropertyInteger", "PrintPlate", "PrintPrep", "")
            obj.PrintPlate = plate_index
            plate_names.append(name)
        doc.recompute()
        plate_area_used = sum(f["footprint_x_mm"] * f["footprint_y_mm"] for f in plate)
        plates_out.append({
            "plate_index": plate_index,
            "part_names": plate_names,
            "bed_usage_percent": 100.0 * plate_area_used / (bed_x * bed_y) if bed_x * bed_y else 0.0,
            "any_oversized": any(f.get("oversized") for f in plate),
        })

    return {
        "bed": {
            "x_mm": bed_x, "y_mm": bed_y, "z_mm": bed_z, "spacing_mm": spacing,
            "edge_margin_mm": edge_margin,
            "usable_rect_mm": {"x0": usable_x0, "y0": usable_y0, "x1": usable_x1, "y1": usable_y1},
            "disallowed_areas": [[list(pt) for pt in polygon] for polygon in areas],
        },
        "parts": {
            name: {
                "orientation": info["chosen_orientation"],
                "runners_up": info["runners_up"],
                "advice": info["advice"],
                "plate": next(p["plate_index"] for p in plates_out if name in p["part_names"]),
                "height_exceeds_bed_z": info["height_exceeds_bed_z"],
            }
            for name, info in per_part.items()
        },
        "plates": plates_out,
    }


# ---- EXPORT -----------------------------------------------------------


def _mesh_for(obj: Any, mesh_tolerance: float = 0.1) -> Any:
    import MeshPart  # noqa: PLC0415

    return MeshPart.meshFromShape(Shape=obj.Shape, LinearDeflection=mesh_tolerance, AngularDeflection=0.5)


def export_print_plates_impl(
    doc: Any, part_names: list[str], output_dir: str, mesh_tolerance: float = 0.1,
) -> dict[str, Any]:
    """One STL per part, one 3MF per plate -- the same `MeshPart.
    meshFromShape` + `Mesh.write` mechanism `export_3mf_native` (M6,
    2026-09-07) already uses, not a second implementation of mesh writing.
    Each file is read back and verified: manifold (`isSolid()`, the same
    predicate `check_mesh_manifold`, capability 17, already qualified),
    positive volume, and Z ~= 0 (the part actually rests on the bed after
    ARRANGE's own Z placement, not floating or embedded)."""
    import os  # noqa: PLC0415

    import Mesh  # noqa: PLC0415

    os.makedirs(output_dir, exist_ok=True)
    parts_out: dict[str, Any] = {}
    plates: dict[int, list[str]] = {}
    for name in part_names:
        obj = doc.getObject(name)
        if obj is None:
            raise ValueError(f"part not found: {name!r}")
        plate_index = int(getattr(obj, "PrintPlate", 0))
        plates.setdefault(plate_index, []).append(name)

        stl_path = os.path.join(output_dir, f"{name}.stl")
        _mesh_for(obj, mesh_tolerance).write(stl_path)
        readback = Mesh.Mesh(stl_path)
        bbox = readback.BoundBox
        parts_out[name] = {
            "stl_path": stl_path,
            "is_solid": bool(readback.isSolid()),
            "facet_count": readback.CountFacets,
            "volume_mm3": readback.Volume,
            "positive_volume": readback.Volume > 0.0,
            "z_min_mm": bbox.ZMin,
            "rests_on_bed": abs(bbox.ZMin) <= 0.1,
            "manifold": bool(readback.isSolid()),
        }

    plates_out: dict[str, Any] = {}
    for plate_index, names in plates.items():
        plate_path = os.path.join(output_dir, f"plate_{plate_index}.3mf")
        combined = _mesh_for(doc.getObject(names[0]), mesh_tolerance)
        for extra_name in names[1:]:
            combined.addMesh(_mesh_for(doc.getObject(extra_name), mesh_tolerance))
        combined.write(plate_path)
        readback = Mesh.Mesh(plate_path)
        plates_out[str(plate_index)] = {
            "plate_path": plate_path,
            "part_names": names,
            "facet_count": readback.CountFacets,
            "file_size_bytes": os.path.getsize(plate_path),
        }

    return {"parts": parts_out, "plates": plates_out}


# ---- MCP tool registration -------------------------------------------------


def register_print_prep_tools(mcp: Any, get_bridge: Callable[[], Awaitable[Any]]) -> None:
    @mcp.tool()
    async def split_printable_parts(
        name_prefix: str = "Print",
        doc_name: str | None = None,
    ) -> dict[str, Any]:
        """SPLIT: one frozen printable solid per `PartDesign::Body`'s own Tip.

        Args:
            name_prefix: Prefix for each created part's own object name.
            doc_name: Document to split. Active document if None.

        Returns:
            parts: one entry per created part (part_name, source_body,
                source_tip, volume_mm3).
            decisions: one entry per Body found, include/exclude and why.
            excluded_summary: coarse counts of everything else in the
                document that was never a candidate (hardware, envelopes,
                links, joints).
        """
        bridge = await get_bridge()
        code = f"""
from integrations.mcp_tools.print_prep import split_printable_parts_impl

doc = FreeCAD.ActiveDocument if {doc_name!r} is None else FreeCAD.getDocument({doc_name!r})
if doc is None:
    raise ValueError("No document found")

_result_ = split_printable_parts_impl(doc, {name_prefix!r})
"""
        result = await bridge.execute_python(code)
        if result.success:
            return result.result
        raise ValueError(result.error_traceback or "split_printable_parts failed")

    @mcp.tool()
    async def plan_print_layout(
        part_names: list[str],
        bed_x_mm: float = 220.0,
        bed_y_mm: float = 220.0,
        bed_z_mm: float = 250.0,
        spacing_mm: float = 5.0,
        edge_margin_mm: float = DEFAULT_EDGE_MARGIN_MM,
        disallowed_areas: list[list[list[float]]] | None = None,
        doc_name: str | None = None,
    ) -> dict[str, Any]:
        """ORIENT + ARRANGE + ADVISE: pick each part's own best print
        orientation, pack them onto one or more plates, and recommend
        adhesion/supports/walls/infill per part.

        Args:
            part_names: Objects to plan (`split_printable_parts`'s own
                `parts[*].part_name`).
            bed_x_mm, bed_y_mm, bed_z_mm: Printable volume. Defaults to a
                220x220x250mm bed.
            spacing_mm: Minimum gap kept between parts on a plate.
            edge_margin_mm: Minimum gap kept between any part and the bed's
                own physical edge. Defaults to 10mm.
            disallowed_areas: Printer-specific keep-out polygons, bed-
                corner-origin (each a list of [x, y] mm points), the same
                shape Cura's own `machine_disallowed_areas` describes. Four
                generic corner keep-outs if None -- pass a real printer's
                own values for an accurate plan.
            doc_name: Document containing the parts. Active document if None.

        Returns:
            bed: the bed dimensions used, plus the resolved edge_margin_mm,
                usable_rect_mm, and disallowed_areas actually applied.
            parts: per part, chosen orientation (with measured overhang
                area, estimated support volume, footprint, height),
                runners-up tried, advice, and which plate it landed on.
            plates: one entry per plate, in print order, with its own
                part list and bed usage percentage.
        """
        bridge = await get_bridge()
        code = f"""
import json
from integrations.mcp_tools.print_prep import plan_print_layout_impl

doc = FreeCAD.ActiveDocument if {doc_name!r} is None else FreeCAD.getDocument({doc_name!r})
if doc is None:
    raise ValueError("No document found")

_areas_ = json.loads({json.dumps(disallowed_areas)!r})
_result_ = plan_print_layout_impl(
    doc, json.loads({json.dumps(part_names)!r}), {bed_x_mm}, {bed_y_mm}, {bed_z_mm}, {spacing_mm},
    {edge_margin_mm},
    [[tuple(pt) for pt in polygon] for polygon in _areas_] if _areas_ is not None else None,
)
"""
        result = await bridge.execute_python(code)
        if result.success:
            return result.result
        raise ValueError(result.error_traceback or "plan_print_layout failed")

    @mcp.tool()
    async def export_print_plates(
        part_names: list[str],
        output_dir: str,
        mesh_tolerance: float = 0.1,
        doc_name: str | None = None,
    ) -> dict[str, Any]:
        """EXPORT: one STL per part plus one 3MF per plate, each read back
        and verified (manifold, positive volume, resting at Z~=0).

        Args:
            part_names: Parts to export (already planned via
                `plan_print_layout`, so each carries a `PrintPlate` index).
            output_dir: Directory to write files into. Created if missing.
            mesh_tolerance: Linear deflection for tessellation. Lower is finer.
            doc_name: Document containing the parts. Active document if None.

        Returns:
            parts: per part, stl_path, is_solid, facet_count, volume_mm3,
                positive_volume, z_min_mm, rests_on_bed, manifold.
            plates: per plate index, plate_path, its own part list, and
                facet_count/file_size_bytes.
        """
        bridge = await get_bridge()
        code = f"""
import json
from integrations.mcp_tools.print_prep import export_print_plates_impl

doc = FreeCAD.ActiveDocument if {doc_name!r} is None else FreeCAD.getDocument({doc_name!r})
if doc is None:
    raise ValueError("No document found")

_result_ = export_print_plates_impl(
    doc, json.loads({json.dumps(part_names)!r}), {output_dir!r}, {mesh_tolerance}
)
"""
        result = await bridge.execute_python(code)
        if result.success:
            return result.result
        raise ValueError(result.error_traceback or "export_print_plates failed")
