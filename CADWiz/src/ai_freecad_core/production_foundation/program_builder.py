# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""General IR program builder -- M-REACH (M3), 2026-09-07.

`compile_coupon_program` (ir.py) builds exactly one hardcoded part. This is
the same idea generalized: a small, ordered set of methods, each appending
one `FeatureOperationIR` with a deterministic name, a real unit map, and the
same evidence/checkpoint shape `_op` already established. A caller (a script
building one of the TEST-ISO-001 parts, or a future compiler standing in
front of this one) describes a part as a sequence of calls and gets a
`FeatureProgramIR` back -- the "concrete versioned JSON feature-program IR"
the roadmap names, extended to more than one part.

Kept deliberately close to the vendored tool it will become, one operation
type per vendored tool call `ToolInvokerFeatureExecutor`
(`src/integrations/mcp_tools/ir_executor.py`) actually makes -- not a richer
"design intent" abstraction over them. `EngineeringIntentSpecLite` is that
richer layer already, referenced by `intent_id`; this builder does not
duplicate it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .contracts import (
    FEATURE_IR_SCHEMA_VERSION,
    FeatureOperationIR,
    FeatureOperationType as T,
    FeatureProgramIR,
)
from .ir import feature_name

_NUMERIC = (int, float)


def _units_for(parameters: dict[str, object]) -> dict[str, str]:
    """Every numeric, non-bool parameter is a millimetre value here.

    True of every operation this builder currently emits (lengths, radii,
    diameters, coordinates). A future operation whose numeric parameter is
    not a length (a count, an angle in degrees) must not go through this
    helper unmodified -- it would mislabel the unit, which is exactly the
    silent-wrong-unit failure `normalize_length` exists elsewhere to catch.
    """
    return {
        key: "mm"
        for key, value in parameters.items()
        if isinstance(value, _NUMERIC) and not isinstance(value, bool)
    }


@dataclass(slots=True)
class IRProgramBuilder:
    """Accumulates operations; `build()` freezes them into a `FeatureProgramIR`.

    Every `add_*` method returns the deterministic feature name it just
    created (`feature_name(target)`), so the next call can reference it by
    name without the caller inventing or guessing what the executor will
    call the resulting FreeCAD object.
    """

    document_id: str
    intent_id: str
    schema_version: str = FEATURE_IR_SCHEMA_VERSION
    _operations: list[FeatureOperationIR] = field(default_factory=list)
    _names: set[str] = field(default_factory=set)

    def _add(
        self,
        target: str,
        kind: T,
        parameters: dict[str, object],
        *,
        pre: tuple[str, ...] = (),
        post: tuple[str, ...] = (),
        checkpoint: str = "start",
        unit_overrides: dict[str, str] | None = None,
    ) -> str:
        """`unit_overrides` corrects `_units_for`'s "every number is mm" default
        for a parameter that is not a length -- an angle in degrees, a count,
        a turn number. Applied after, not instead of, so a call site only
        overrides the one or two parameters that need it.
        """
        name = feature_name(target)
        if name in self._names:
            raise ValueError(f"duplicate feature name: {name} (target {target!r})")
        self._names.add(name)
        units = _units_for(parameters)
        if unit_overrides:
            units.update(unit_overrides)
        operation = FeatureOperationIR(
            f"op-{len(self._operations) + 1:02d}",
            target,
            kind,
            parameters,
            units,
            pre,
            post,
            checkpoint,
            ("observation", "validator"),
        )
        self._operations.append(operation)
        return name

    # ---- document / body -------------------------------------------------

    def create_document(self, target: str, *, name: str) -> str:
        return self._add(target, T.CREATE_DOCUMENT, {"name": name}, post=("document exists",))

    def create_body(self, target: str, *, checkpoint: str = "document") -> str:
        return self._add(
            target, T.CREATE_BODY_OR_CONTAINER, {}, checkpoint=checkpoint, post=("body exists",)
        )

    # ---- primitives (capability 1) ---------------------------------------

    def create_box(
        self, target: str, *, length: float, width: float, height: float,
        checkpoint: str = "document",
    ) -> str:
        return self._add(
            target, T.CREATE_PRIMITIVE_BOX,
            {"length": length, "width": width, "height": height},
            checkpoint=checkpoint, post=("one valid solid",),
        )

    def create_cylinder(
        self, target: str, *, diameter: float, height: float, checkpoint: str = "document",
    ) -> str:
        return self._add(
            target, T.CREATE_PRIMITIVE_CYLINDER, {"diameter": diameter, "height": height},
            checkpoint=checkpoint, post=("one valid solid",),
        )

    def create_sphere(self, target: str, *, diameter: float, checkpoint: str = "document") -> str:
        return self._add(
            target, T.CREATE_PRIMITIVE_SPHERE, {"diameter": diameter},
            checkpoint=checkpoint, post=("one valid solid",),
        )

    def create_cone(
        self, target: str, *, diameter1: float, diameter2: float, height: float,
        checkpoint: str = "document",
    ) -> str:
        return self._add(
            target, T.CREATE_PRIMITIVE_CONE,
            {"diameter1": diameter1, "diameter2": diameter2, "height": height},
            checkpoint=checkpoint, post=("one valid solid",),
        )

    def set_placement(
        self, target: str, *, object_name: str, x: float = 0.0, y: float = 0.0, z: float = 0.0,
        checkpoint: str,
    ) -> str:
        return self._add(
            target, T.SET_PLACEMENT, {"object_name": object_name, "x": x, "y": y, "z": z},
            checkpoint=checkpoint,
        )

    # ---- sketching --------------------------------------------------------

    def create_sketch(
        self, target: str, *, body: str, plane: str, checkpoint: str,
    ) -> str:
        return self._add(
            target, T.CREATE_SKETCH_ON_NAMED_PLANE, {"body": body, "plane": plane},
            checkpoint=checkpoint,
        )

    def add_rectangle(
        self, target: str, *, sketch: str, x: float, y: float,
        width: float, height: float, checkpoint: str,
    ) -> str:
        return self._add(
            target, T.ADD_RECTANGLE_OR_CLOSED_PROFILE,
            {"sketch": sketch, "x": x, "y": y, "width": width, "height": height},
            checkpoint=checkpoint,
        )

    def add_circle(
        self, target: str, *, sketch: str, x: float, y: float, diameter: float,
        checkpoint: str,
    ) -> str:
        return self._add(
            target, T.ADD_CIRCLE, {"sketch": sketch, "x": x, "y": y, "diameter": diameter},
            checkpoint=checkpoint,
        )

    def add_polyline(
        self, target: str, *, sketch: str, points: tuple[tuple[float, float], ...],
        checkpoint: str,
    ) -> str:
        """A closed profile built from straight segments -- the L-shapes and
        stepped outlines a rectangle or a circle cannot express, without
        needing a dedicated polygon tool for every distinct shape a part
        happens to need.
        """
        if len(points) < 3:
            raise ValueError("a closed polyline profile needs at least 3 points")
        flat: list[float] = [coordinate for point in points for coordinate in point]
        return self._add(
            target, T.ADD_LINE_SEGMENT, {"sketch": sketch, "points": flat},
            checkpoint=checkpoint,
        )

    def add_slot(
        self, target: str, *, sketch: str, x1: float, y1: float,
        x2: float, y2: float, width: float, checkpoint: str,
    ) -> str:
        return self._add(
            target, T.ADD_SLOT_PROFILE,
            {"sketch": sketch, "x1": x1, "y1": y1, "x2": x2, "y2": y2, "width": width},
            checkpoint=checkpoint,
        )

    def add_point(self, target: str, *, sketch: str, x: float, y: float, checkpoint: str) -> str:
        """A hole center marker -- `hole()`'s sketch must contain one of these
        per hole, not a circle (a circle is a profile to pad or pocket; a
        hole feature reads point locations instead).
        """
        return self._add(
            target, T.ADD_POINT, {"sketch": sketch, "x": x, "y": y}, checkpoint=checkpoint,
        )

    # ---- features (capabilities 4-6) --------------------------------------

    def pad(self, target: str, *, sketch: str, length: float, checkpoint: str) -> str:
        return self._add(
            target, T.PAD, {"sketch": sketch, "length": length},
            checkpoint=checkpoint, post=("one valid solid",),
        )

    def pocket(self, target: str, *, sketch: str, length: float, checkpoint: str) -> str:
        return self._add(
            target, T.POCKET, {"sketch": sketch, "length": length},
            checkpoint=checkpoint, post=("one valid solid",),
        )

    def hole(
        self, target: str, *, sketch: str, diameter: float, depth: float | None,
        checkpoint: str,
    ) -> str:
        parameters: dict[str, object] = {"sketch": sketch, "diameter": diameter}
        if depth is None:
            parameters["through_all"] = True
        else:
            parameters["depth"] = depth
        return self._add(target, T.HOLE, parameters, checkpoint=checkpoint, post=("one valid solid",))

    def fillet(
        self, target: str, *, base: str, radius: float, edges: tuple[str, ...],
        checkpoint: str,
    ) -> str:
        return self._add(
            target, T.FILLET, {"base": base, "radius": radius, "edges": list(edges)},
            checkpoint=checkpoint, post=("one valid solid",),
        )

    def chamfer(
        self, target: str, *, base: str, size: float, edges: tuple[str, ...],
        checkpoint: str,
    ) -> str:
        return self._add(
            target, T.CHAMFER, {"base": base, "size": size, "edges": list(edges)},
            checkpoint=checkpoint, post=("one valid solid",),
        )

    # ---- booleans -----------------------------------------------------------

    def boolean_union(self, target: str, *, base: str, tool: str, checkpoint: str) -> str:
        return self._add(
            target, T.BOOLEAN_UNION, {"base": base, "tool": tool},
            checkpoint=checkpoint, post=("one valid solid",),
        )

    def boolean_cut(self, target: str, *, base: str, tool: str, checkpoint: str) -> str:
        return self._add(
            target, T.BOOLEAN_CUT, {"base": base, "tool": tool},
            checkpoint=checkpoint, post=("one valid solid",),
        )

    # ---- parameters (capability 7) -----------------------------------------

    def spreadsheet(self, target: str, *, checkpoint: str) -> str:
        return self._add(target, T.DEFINE_SPREADSHEET_PARAMETER, {}, checkpoint=checkpoint)

    def bind_parameter(
        self, target: str, *, spreadsheet: str, cell: str, alias: str,
        bound_object: str, bound_property: str, formula: str, checkpoint: str,
    ) -> str:
        return self._add(
            target, T.BIND_SPREADSHEET_PARAMETER,
            {
                "spreadsheet": spreadsheet, "cell": cell, "alias": alias,
                "bound_object": bound_object, "bound_property": bound_property,
                "formula": formula,
            },
            checkpoint=checkpoint,
        )

    # ---- Layer 3: helix, B-spline/freeform, multi-body, Draft 2D, draft angle

    def create_helix(
        self, target: str, *, body: str, sketch: str, pitch: float, height: float,
        mode: str = "additive", checkpoint: str,
    ) -> str:
        kind = T.CREATE_HELIX_ADDITIVE if mode == "additive" else T.CREATE_HELIX_SUBTRACTIVE
        return self._add(
            target, kind, {"body": body, "sketch": sketch, "pitch": pitch, "height": height},
            checkpoint=checkpoint, post=("one valid solid",),
        )

    def convert_to_bspline(self, target: str, *, sketch: str, geometry_index: int, checkpoint: str) -> str:
        """Not shape-changing (see `runtime_layer3_qualification.py`'s
        `qualify_bspline`), so this has no "one valid solid" postcondition --
        what it must preserve is the sketch's existing shape, not produce one.
        """
        return self._add(
            target, T.CONVERT_TO_BSPLINE, {"sketch": sketch, "geometry_index": geometry_index},
            checkpoint=checkpoint,
        )

    def increase_bspline_degree(
        self, target: str, *, sketch: str, geometry_index: int, count: int = 1, checkpoint: str,
    ) -> str:
        return self._add(
            target, T.INCREASE_BSPLINE_DEGREE,
            {"sketch": sketch, "geometry_index": geometry_index, "count": count},
            checkpoint=checkpoint,
        )

    def create_subshape_binder(
        self, target: str, *, target_body: str, source_object: str, checkpoint: str,
    ) -> str:
        return self._add(
            target, T.CREATE_SUBSHAPE_BINDER,
            {"target_body": target_body, "source_object": source_object},
            checkpoint=checkpoint, post=("one valid solid",),
        )

    def add_draft_line(
        self, target: str, *, x1: float, y1: float, x2: float, y2: float,
        z1: float = 0.0, z2: float = 0.0, checkpoint: str,
    ) -> str:
        return self._add(
            target, T.ADD_DRAFT_LINE, {"x1": x1, "y1": y1, "x2": x2, "y2": y2, "z1": z1, "z2": z2},
            checkpoint=checkpoint,
        )

    def add_draft_circle(
        self, target: str, *, radius: float, x: float = 0.0, y: float = 0.0, z: float = 0.0,
        checkpoint: str,
    ) -> str:
        return self._add(
            target, T.ADD_DRAFT_CIRCLE, {"radius": radius, "x": x, "y": y, "z": z},
            checkpoint=checkpoint,
        )

    def add_draft_rectangle(
        self, target: str, *, length: float, width: float,
        x: float = 0.0, y: float = 0.0, z: float = 0.0, checkpoint: str,
    ) -> str:
        return self._add(
            target, T.ADD_DRAFT_RECTANGLE,
            {"length": length, "width": width, "x": x, "y": y, "z": z},
            checkpoint=checkpoint,
        )

    def apply_draft_angle(
        self, target: str, *, base: str, angle: float, faces: tuple[str, ...],
        plane: str = "XY", checkpoint: str,
    ) -> str:
        """`angle` is degrees, not millimetres -- overridden explicitly since
        `_units_for` would otherwise mislabel it "mm" like every other
        numeric parameter this builder emits. Measured 2026-09-07
        (`qualify_draft_angle`): `faces` must be given explicitly -- the
        vendored `draft_feature` tool's own `faces=None` does not draft "all
        suitable faces" despite its docstring, it drafts none.
        """
        return self._add(
            target, T.APPLY_DRAFT_ANGLE,
            {"base": base, "angle": angle, "faces": list(faces), "plane": plane},
            checkpoint=checkpoint, post=("one valid solid",),
            unit_overrides={"angle": "deg"},
        )

    # ---- M2b Group 1: patterns, shell/thickness, revolve, mirror, holes -----

    def linear_pattern(
        self, target: str, *, feature: str, direction: str = "X", length: float,
        occurrences: int, checkpoint: str,
    ) -> str:
        return self._add(
            target, T.LINEAR_PATTERN,
            {"feature": feature, "direction": direction, "length": length, "occurrences": occurrences},
            checkpoint=checkpoint, post=("one valid solid",),
            unit_overrides={"occurrences": "count"},
        )

    def polar_pattern(
        self, target: str, *, feature: str, axis: str = "Z", angle: float = 360.0,
        occurrences: int, checkpoint: str,
    ) -> str:
        return self._add(
            target, T.POLAR_PATTERN,
            {"feature": feature, "axis": axis, "angle": angle, "occurrences": occurrences},
            checkpoint=checkpoint, post=("one valid solid",),
            unit_overrides={"angle": "deg", "occurrences": "count"},
        )

    def shell_thickness(
        self, target: str, *, base: str, thickness: float, faces_to_remove: tuple[str, ...],
        checkpoint: str,
    ) -> str:
        return self._add(
            target, T.SHELL_THICKNESS,
            {"base": base, "thickness": thickness, "faces_to_remove": list(faces_to_remove)},
            checkpoint=checkpoint, post=("one valid solid",),
        )

    def revolve(
        self, target: str, *, sketch: str, angle: float = 360.0, axis: str = "Base_X",
        checkpoint: str,
    ) -> str:
        return self._add(
            target, T.REVOLVE, {"sketch": sketch, "angle": angle, "axis": axis},
            checkpoint=checkpoint, post=("one valid solid",),
            unit_overrides={"angle": "deg"},
        )

    def mirror_feature(self, target: str, *, feature: str, plane: str = "XY", checkpoint: str) -> str:
        return self._add(
            target, T.MIRROR_FEATURE, {"feature": feature, "plane": plane},
            checkpoint=checkpoint, post=("one valid solid",),
        )

    def hole_advanced(
        self, target: str, *, sketch: str, diameter: float, depth: float,
        cut_type: str = "None", cut_diameter: float = 0.0, cut_depth: float = 0.0,
        countersink_angle: float = 90.0, hole_type: str = "Dimension", checkpoint: str,
    ) -> str:
        return self._add(
            target, T.HOLE_ADVANCED,
            {
                "sketch": sketch, "diameter": diameter, "depth": depth, "cut_type": cut_type,
                "cut_diameter": cut_diameter, "cut_depth": cut_depth,
                "countersink_angle": countersink_angle, "hole_type": hole_type,
            },
            checkpoint=checkpoint, post=("one valid solid",),
            unit_overrides={"countersink_angle": "deg"},
        )

    # ---- M2b Group 2: downloaded-STL rescue ---------------------------------

    def scale_mesh(
        self, target: str, *, mesh: str, factor_x: float, factor_y: float = 0.0,
        factor_z: float = 0.0, checkpoint: str,
    ) -> str:
        return self._add(
            target, T.SCALE_MESH,
            {"mesh": mesh, "factor_x": factor_x, "factor_y": factor_y, "factor_z": factor_z},
            checkpoint=checkpoint,
            unit_overrides={"factor_x": "ratio", "factor_y": "ratio", "factor_z": "ratio"},
        )

    def convert_mesh_to_solid(
        self, target: str, *, mesh: str, tolerance: float = 0.05, checkpoint: str,
    ) -> str:
        return self._add(
            target, T.CONVERT_MESH_TO_SOLID, {"mesh": mesh, "tolerance": tolerance},
            checkpoint=checkpoint, post=("one valid solid",),
        )

    # ---- M2b Group 3: Part_Tube, sketch symmetric, sketch fillet -----------

    def create_tube(
        self, target: str, *, outer_radius: float = 5.0, inner_radius: float = 2.0,
        height: float = 10.0, checkpoint: str,
    ) -> str:
        return self._add(
            target, T.CREATE_TUBE,
            {"outer_radius": outer_radius, "inner_radius": inner_radius, "height": height},
            checkpoint=checkpoint, post=("one valid solid",),
        )

    def constrain_sketch_symmetric(
        self, target: str, *, sketch: str, geometry1: int, point1: int, geometry2: int,
        point2: int, symmetry_line_geometry: int, checkpoint: str,
    ) -> str:
        return self._add(
            target, T.CONSTRAIN_SKETCH_SYMMETRIC,
            {
                "sketch": sketch, "geometry1": geometry1, "point1": point1,
                "geometry2": geometry2, "point2": point2,
                "symmetry_line_geometry": symmetry_line_geometry,
            },
            checkpoint=checkpoint,
        )

    def fillet_sketch_geometry(
        self, target: str, *, sketch: str, geometry: int, point: int, radius: float,
        checkpoint: str,
    ) -> str:
        return self._add(
            target, T.FILLET_SKETCH_GEOMETRY,
            {"sketch": sketch, "geometry": geometry, "point": point, "radius": radius},
            checkpoint=checkpoint,
        )

    # ---- FILLET-PRO ----------------------------------------------------------

    def create_smart_fillet(
        self, target: str, *, object_name: str, query: list[str], radius: float,
        checkpoint: str,
    ) -> str:
        return self._add(
            target, T.CREATE_SMART_FILLET,
            {"object_name": object_name, "query": query, "radius": radius},
            checkpoint=checkpoint, post=("one valid solid",),
        )

    def insert_hole_before_fillets(
        self, target: str, *, fillet_tip: str, hole_sketch: str, diameter: float,
        depth: float, hole_type: str = "ThroughAll", cut_type: str = "None",
        cut_diameter: float = 0.0, cut_depth: float = 0.0, checkpoint: str,
    ) -> str:
        return self._add(
            target, T.INSERT_HOLE_BEFORE_FILLETS,
            {
                "fillet_tip": fillet_tip, "hole_sketch": hole_sketch, "diameter": diameter,
                "depth": depth, "hole_type": hole_type, "cut_type": cut_type,
                "cut_diameter": cut_diameter, "cut_depth": cut_depth,
            },
            checkpoint=checkpoint, post=("one valid solid",),
        )

    # ---- PRINT-PREP ------------------------------------------------------------

    def split_printable_parts(
        self, target: str, *, name_prefix: str = "Print", checkpoint: str,
    ) -> str:
        """SPLIT: one frozen printable solid per `PartDesign::Body`'s own
        Tip in the active document. Unlike every other operation here, this
        one produces a variable number of independently-named objects, not
        one predictable feature name -- `target`'s own deterministic name
        is a logical label for this step, not an object the executor will
        actually find; the real names come back in the tool's own payload
        and the executor reports the first one as the active subject."""
        return self._add(
            target, T.SPLIT_PRINTABLE_PARTS, {"name_prefix": name_prefix},
            checkpoint=checkpoint,
        )

    def plan_print_layout(
        self, target: str, *, part_names: list[str], bed_x_mm: float = 220.0,
        bed_y_mm: float = 220.0, bed_z_mm: float = 250.0, spacing_mm: float = 5.0,
        edge_margin_mm: float = 10.0, disallowed_areas: list[list[tuple[float, float]]] | None = None,
        checkpoint: str,
    ) -> str:
        """`edge_margin_mm`/`disallowed_areas` (T1 bug fix, 2026-09-13): the
        printer-profile keep-out ARRANGE now respects -- see
        `print_prep.usable_rect`/`default_disallowed_areas`. `None` (the
        default here) lets the tool apply its own generic corner keep-outs;
        pass a real printer's own `machine_disallowed_areas` for an
        accurate plan."""
        return self._add(
            target, T.PLAN_PRINT_LAYOUT,
            {
                "part_names": part_names, "bed_x_mm": bed_x_mm, "bed_y_mm": bed_y_mm,
                "bed_z_mm": bed_z_mm, "spacing_mm": spacing_mm, "edge_margin_mm": edge_margin_mm,
                "disallowed_areas": (
                    [[list(pt) for pt in polygon] for polygon in disallowed_areas]
                    if disallowed_areas is not None else None
                ),
            },
            checkpoint=checkpoint,
        )

    def export_print_plates(
        self, target: str, *, part_names: list[str], output_dir: str, checkpoint: str,
    ) -> str:
        return self._add(
            target, T.EXPORT_PRINT_PLATES,
            {"part_names": part_names, "output_dir": output_dir},
            checkpoint=checkpoint,
        )

    # ---- M3 PLANNABLE SWEEP: datum features (capability 9) ------------------

    def create_datum_plane(
        self, target: str, *, body: str, offset: float, base_plane: str = "XY_Plane",
        checkpoint: str,
    ) -> str:
        return self._add(
            target, T.CREATE_DATUM_PLANE,
            {"body": body, "offset": offset, "base_plane": base_plane},
            checkpoint=checkpoint,
        )

    def create_datum_line(
        self, target: str, *, body: str, base_axis: str = "X_Axis", checkpoint: str,
    ) -> str:
        return self._add(
            target, T.CREATE_DATUM_LINE, {"body": body, "base_axis": base_axis},
            checkpoint=checkpoint,
        )

    def create_datum_point(
        self, target: str, *, body: str, position: tuple[float, float, float], checkpoint: str,
    ) -> str:
        return self._add(
            target, T.CREATE_DATUM_POINT, {"body": body, "position": list(position)},
            checkpoint=checkpoint,
        )

    # ---- M3 PLANNABLE SWEEP: sketch constraints extra ------------------------
    # (capabilities 3, 33, 36-38, 40, 42)

    def constrain_distance_x(
        self, target: str, *, sketch: str, geometry: int, point: int, distance: float,
        checkpoint: str,
    ) -> str:
        return self._add(
            target, T.CONSTRAIN_DISTANCE_X,
            {"sketch": sketch, "geometry": geometry, "point": point, "distance": distance},
            checkpoint=checkpoint,
        )

    def constrain_horizontal(
        self, target: str, *, sketch: str, geometry_index: int, checkpoint: str,
    ) -> str:
        return self._add(
            target, T.CONSTRAIN_HORIZONTAL,
            {"sketch": sketch, "geometry_index": geometry_index}, checkpoint=checkpoint,
        )

    def constrain_vertical(
        self, target: str, *, sketch: str, geometry_index: int, checkpoint: str,
    ) -> str:
        return self._add(
            target, T.CONSTRAIN_VERTICAL,
            {"sketch": sketch, "geometry_index": geometry_index}, checkpoint=checkpoint,
        )

    def constrain_radius(
        self, target: str, *, sketch: str, geometry_index: int, radius: float, checkpoint: str,
    ) -> str:
        return self._add(
            target, T.CONSTRAIN_RADIUS,
            {"sketch": sketch, "geometry_index": geometry_index, "radius": radius},
            checkpoint=checkpoint,
        )

    def constrain_distance(
        self, target: str, *, sketch: str, geometry1: int, point1: int, distance: float,
        checkpoint: str,
    ) -> str:
        return self._add(
            target, T.CONSTRAIN_DISTANCE,
            {"sketch": sketch, "geometry1": geometry1, "point1": point1, "distance": distance},
            checkpoint=checkpoint,
        )

    def constrain_distance_y(
        self, target: str, *, sketch: str, geometry: int, point: int, distance: float,
        checkpoint: str,
    ) -> str:
        return self._add(
            target, T.CONSTRAIN_DISTANCE_Y,
            {"sketch": sketch, "geometry": geometry, "point": point, "distance": distance},
            checkpoint=checkpoint,
        )

    def constrain_angle(
        self, target: str, *, sketch: str, geometry1: int, angle: float, checkpoint: str,
    ) -> str:
        return self._add(
            target, T.CONSTRAIN_ANGLE, {"sketch": sketch, "geometry1": geometry1, "angle": angle},
            checkpoint=checkpoint, unit_overrides={"angle": "deg"},
        )

    def add_arc(
        self, target: str, *, sketch: str, center_x: float, center_y: float, radius: float,
        start_angle: float, end_angle: float, checkpoint: str,
    ) -> str:
        return self._add(
            target, T.ADD_ARC,
            {"sketch": sketch, "center_x": center_x, "center_y": center_y, "radius": radius,
             "start_angle": start_angle, "end_angle": end_angle},
            checkpoint=checkpoint, unit_overrides={"start_angle": "deg", "end_angle": "deg"},
        )

    def constrain_coincident(
        self, target: str, *, sketch: str, geometry1: int, point1: int, geometry2: int,
        point2: int, checkpoint: str,
    ) -> str:
        return self._add(
            target, T.CONSTRAIN_COINCIDENT,
            {"sketch": sketch, "geometry1": geometry1, "point1": point1,
             "geometry2": geometry2, "point2": point2},
            checkpoint=checkpoint,
        )

    def add_polygon(
        self, target: str, *, sketch: str, center_x: float, center_y: float, radius: float,
        sides: int, checkpoint: str,
    ) -> str:
        return self._add(
            target, T.ADD_POLYGON,
            {"sketch": sketch, "center_x": center_x, "center_y": center_y, "radius": radius,
             "sides": sides},
            checkpoint=checkpoint, unit_overrides={"sides": "count"},
        )

    def add_ellipse(
        self, target: str, *, sketch: str, center_x: float, center_y: float,
        major_radius: float, minor_radius: float, checkpoint: str,
    ) -> str:
        return self._add(
            target, T.ADD_ELLIPSE,
            {"sketch": sketch, "center_x": center_x, "center_y": center_y,
             "major_radius": major_radius, "minor_radius": minor_radius},
            checkpoint=checkpoint,
        )

    def add_bspline(
        self, target: str, *, sketch: str, points: tuple[tuple[float, float], ...],
        closed: bool = False, checkpoint: str,
    ) -> str:
        """A freeform curve through control points -- an organic profile
        (an egg's asymmetric outline, a jagged crack line) that neither an
        ellipse nor straight polyline segments can express."""
        if len(points) < 2:
            raise ValueError("a bspline needs at least 2 control points")
        return self._add(
            target, T.ADD_BSPLINE,
            {"sketch": sketch, "points": [list(point) for point in points], "closed": closed},
            checkpoint=checkpoint,
        )

    def constrain_equal(
        self, target: str, *, sketch: str, geometry1: int, geometry2: int, checkpoint: str,
    ) -> str:
        return self._add(
            target, T.CONSTRAIN_EQUAL, {"sketch": sketch, "geometry1": geometry1, "geometry2": geometry2},
            checkpoint=checkpoint,
        )

    def add_sketch_constraint(
        self, target: str, *, sketch: str, constraint_type: str, geometry1: int,
        point1: int = -1, geometry2: int = -2, point2: int = -1, value: float | None = None,
        checkpoint: str,
    ) -> str:
        """The general-purpose fallback constraint tool, for constraint types
        with no dedicated wrapper op (e.g. "Block"). Prefer the dedicated
        constrain_* builder methods above when one exists for the type."""
        return self._add(
            target, T.ADD_SKETCH_CONSTRAINT,
            {"sketch": sketch, "constraint_type": constraint_type, "geometry1": geometry1,
             "point1": point1, "geometry2": geometry2, "point2": point2, "value": value},
            checkpoint=checkpoint,
        )

    def constrain_parallel(
        self, target: str, *, sketch: str, geometry1: int, geometry2: int, checkpoint: str,
    ) -> str:
        return self._add(
            target, T.CONSTRAIN_PARALLEL, {"sketch": sketch, "geometry1": geometry1, "geometry2": geometry2},
            checkpoint=checkpoint,
        )

    def constrain_perpendicular(
        self, target: str, *, sketch: str, geometry1: int, geometry2: int, checkpoint: str,
    ) -> str:
        return self._add(
            target, T.CONSTRAIN_PERPENDICULAR,
            {"sketch": sketch, "geometry1": geometry1, "geometry2": geometry2},
            checkpoint=checkpoint,
        )

    def constrain_tangent(
        self, target: str, *, sketch: str, geometry1: int, geometry2: int, checkpoint: str,
    ) -> str:
        return self._add(
            target, T.CONSTRAIN_TANGENT, {"sketch": sketch, "geometry1": geometry1, "geometry2": geometry2},
            checkpoint=checkpoint,
        )

    # ---- M3 PLANNABLE SWEEP: export/import/validation HARD-predicate --------
    # (capabilities 41, 50, 59, 60)

    def validate_object(self, target: str, *, object_name: str, checkpoint: str) -> str:
        return self._add(
            target, T.VALIDATE_OBJECT, {"object_name": object_name}, checkpoint=checkpoint,
        )

    def validate_document(self, target: str, *, checkpoint: str) -> str:
        return self._add(target, T.VALIDATE_DOCUMENT, {}, checkpoint=checkpoint)

    def export_step(
        self, target: str, *, object_names: tuple[str, ...], file_path: str, checkpoint: str,
    ) -> str:
        return self._add(
            target, T.EXPORT_STEP,
            {"object_names": list(object_names), "file_path": file_path}, checkpoint=checkpoint,
        )

    def export_stl(
        self, target: str, *, object_names: tuple[str, ...], file_path: str,
        mesh_tolerance: float = 0.1, checkpoint: str,
    ) -> str:
        return self._add(
            target, T.EXPORT_STL,
            {"object_names": list(object_names), "file_path": file_path,
             "mesh_tolerance": mesh_tolerance},
            checkpoint=checkpoint,
        )

    def export_3mf(
        self, target: str, *, object_names: tuple[str, ...], file_path: str,
        mesh_tolerance: float = 0.1, checkpoint: str,
    ) -> str:
        return self._add(
            target, T.EXPORT_3MF,
            {"object_names": list(object_names), "file_path": file_path,
             "mesh_tolerance": mesh_tolerance},
            checkpoint=checkpoint,
        )

    def export_3mf_native(
        self, target: str, *, object_names: tuple[str, ...], file_path: str,
        mesh_tolerance: float = 0.1, checkpoint: str,
    ) -> str:
        return self._add(
            target, T.EXPORT_3MF_NATIVE,
            {"object_names": list(object_names), "file_path": file_path,
             "mesh_tolerance": mesh_tolerance},
            checkpoint=checkpoint,
        )

    def export_obj(
        self, target: str, *, object_names: tuple[str, ...], file_path: str,
        mesh_tolerance: float = 0.1, checkpoint: str,
    ) -> str:
        return self._add(
            target, T.EXPORT_OBJ,
            {"object_names": list(object_names), "file_path": file_path,
             "mesh_tolerance": mesh_tolerance},
            checkpoint=checkpoint,
        )

    def export_iges(
        self, target: str, *, object_names: tuple[str, ...], file_path: str, checkpoint: str,
    ) -> str:
        return self._add(
            target, T.EXPORT_IGES,
            {"object_names": list(object_names), "file_path": file_path}, checkpoint=checkpoint,
        )

    def import_step(self, target: str, *, file_path: str, checkpoint: str) -> str:
        """Distinct from LIVE-RESULT's own `import_step` operation
        (`compute_live_result`'s `"import_step"` string key, unrelated to
        this enum) -- that one builds a fresh document-less shape from an
        external file with no in-document source; this one is the plain
        HARD-predicate round trip capability 50 qualifies (file written,
        re-read, object count/shape confirmed)."""
        return self._add(
            target, T.IMPORT_STEP_IR, {"file_path": file_path}, checkpoint=checkpoint,
            post=("one valid solid",),
        )

    def import_stl(self, target: str, *, file_path: str, checkpoint: str) -> str:
        return self._add(
            target, T.IMPORT_STL, {"file_path": file_path}, checkpoint=checkpoint,
            post=("one valid solid",),
        )

    def spreadsheet_export_csv(
        self, target: str, *, spreadsheet: str, file_path: str, checkpoint: str,
    ) -> str:
        return self._add(
            target, T.SPREADSHEET_EXPORT_CSV,
            {"spreadsheet": spreadsheet, "file_path": file_path}, checkpoint=checkpoint,
        )

    def spreadsheet_import_csv(
        self, target: str, *, spreadsheet: str, file_path: str, checkpoint: str,
    ) -> str:
        return self._add(
            target, T.SPREADSHEET_IMPORT_CSV,
            {"spreadsheet": spreadsheet, "file_path": file_path}, checkpoint=checkpoint,
        )

    def check_bed_fit(
        self, target: str, *, object_name: str, bed_x_mm: float = 220.0,
        bed_y_mm: float = 220.0, bed_z_mm: float = 250.0, checkpoint: str,
    ) -> str:
        return self._add(
            target, T.CHECK_BED_FIT,
            {"object_name": object_name, "bed_x_mm": bed_x_mm, "bed_y_mm": bed_y_mm,
             "bed_z_mm": bed_z_mm},
            checkpoint=checkpoint,
        )

    def check_mesh_manifold(self, target: str, *, object_name: str, checkpoint: str) -> str:
        return self._add(
            target, T.CHECK_MESH_MANIFOLD, {"object_name": object_name}, checkpoint=checkpoint,
        )

    def check_wall_thickness(
        self, target: str, *, object_name: str, minimum_mm: float, checkpoint: str,
    ) -> str:
        return self._add(
            target, T.CHECK_WALL_THICKNESS,
            {"object_name": object_name, "minimum_mm": minimum_mm}, checkpoint=checkpoint,
        )

    # ---- M3 PLANNABLE SWEEP: Part-workbench primitives extra (cap 43) -------

    def create_ellipse(
        self, target: str, *, major_radius: float, minor_radius: float, checkpoint: str = "document",
    ) -> str:
        return self._add(
            target, T.CREATE_ELLIPSE, {"major_radius": major_radius, "minor_radius": minor_radius},
            checkpoint=checkpoint,
        )

    def create_helix_primitive(
        self, target: str, *, pitch: float, height: float, radius: float, checkpoint: str = "document",
    ) -> str:
        return self._add(
            target, T.CREATE_HELIX_PRIMITIVE, {"pitch": pitch, "height": height, "radius": radius},
            checkpoint=checkpoint,
        )

    def create_line_primitive(
        self, target: str, *, point1: tuple[float, float, float],
        point2: tuple[float, float, float], checkpoint: str = "document",
    ) -> str:
        return self._add(
            target, T.CREATE_LINE_PRIMITIVE, {"point1": list(point1), "point2": list(point2)},
            checkpoint=checkpoint,
        )

    def create_plane_primitive(
        self, target: str, *, length: float, width: float, checkpoint: str = "document",
    ) -> str:
        return self._add(
            target, T.CREATE_PLANE_PRIMITIVE, {"length": length, "width": width},
            checkpoint=checkpoint,
        )

    def create_prism(
        self, target: str, *, polygon_sides: int, circumradius: float, height: float,
        checkpoint: str = "document",
    ) -> str:
        return self._add(
            target, T.CREATE_PRISM,
            {"polygon_sides": polygon_sides, "circumradius": circumradius, "height": height},
            checkpoint=checkpoint, post=("one valid solid",),
            unit_overrides={"polygon_sides": "count"},
        )

    def create_regular_polygon(
        self, target: str, *, polygon_sides: int, circumradius: float, checkpoint: str = "document",
    ) -> str:
        return self._add(
            target, T.CREATE_REGULAR_POLYGON,
            {"polygon_sides": polygon_sides, "circumradius": circumradius},
            checkpoint=checkpoint, unit_overrides={"polygon_sides": "count"},
        )

    def create_wedge(
        self, target: str, *, xmin: float, ymin: float, zmin: float, x2min: float, z2min: float,
        xmax: float, ymax: float, zmax: float, x2max: float, z2max: float,
        checkpoint: str = "document",
    ) -> str:
        return self._add(
            target, T.CREATE_WEDGE,
            {"xmin": xmin, "ymin": ymin, "zmin": zmin, "x2min": x2min, "z2min": z2min,
             "xmax": xmax, "ymax": ymax, "zmax": zmax, "x2max": x2max, "z2max": z2max},
            checkpoint=checkpoint, post=("one valid solid",),
        )

    def create_torus(
        self, target: str, *, radius1: float, radius2: float, checkpoint: str = "document",
    ) -> str:
        return self._add(
            target, T.CREATE_TORUS, {"radius1": radius1, "radius2": radius2},
            checkpoint=checkpoint, post=("one valid solid",),
        )

    # ---- M3 PLANNABLE SWEEP: object editing / shape-compound ----------------
    # (capabilities 45, 46, 47)

    def copy_object(
        self, target: str, *, object_name: str, offset: tuple[float, float, float] = (0.0, 0.0, 0.0),
        checkpoint: str,
    ) -> str:
        return self._add(
            target, T.COPY_OBJECT, {"object_name": object_name, "offset": list(offset)},
            checkpoint=checkpoint, post=("one valid solid",),
        )

    def delete_object(self, target: str, *, object_name: str, checkpoint: str) -> str:
        return self._add(target, T.DELETE_OBJECT, {"object_name": object_name}, checkpoint=checkpoint)

    def mirror_object(
        self, target: str, *, object_name: str, plane: str = "XY", checkpoint: str,
    ) -> str:
        return self._add(
            target, T.MIRROR_OBJECT, {"object_name": object_name, "plane": plane},
            checkpoint=checkpoint, post=("one valid solid",),
        )

    def offset_3d(self, target: str, *, object_name: str, offset: float, checkpoint: str) -> str:
        return self._add(
            target, T.OFFSET_3D, {"object_name": object_name, "offset": offset},
            checkpoint=checkpoint, post=("one valid solid",),
        )

    def scale_object(
        self, target: str, *, object_name: str, scale: float, checkpoint: str,
    ) -> str:
        return self._add(
            target, T.SCALE_OBJECT, {"object_name": object_name, "scale": scale},
            checkpoint=checkpoint, post=("one valid solid",), unit_overrides={"scale": "ratio"},
        )

    def shell_object(
        self, target: str, *, object_name: str, thickness: float,
        faces_to_remove: tuple[str, ...], checkpoint: str,
    ) -> str:
        return self._add(
            target, T.SHELL_OBJECT,
            {"object_name": object_name, "thickness": thickness,
             "faces_to_remove": list(faces_to_remove)},
            checkpoint=checkpoint, post=("one valid solid",),
        )

    def edit_object(
        self, target: str, *, object_name: str, properties: dict[str, object], checkpoint: str,
    ) -> str:
        return self._add(
            target, T.EDIT_OBJECT, {"object_name": object_name, "properties": properties},
            checkpoint=checkpoint,
        )

    def rotate_object(
        self, target: str, *, object_name: str, axis: tuple[float, float, float], angle: float,
        checkpoint: str,
    ) -> str:
        return self._add(
            target, T.ROTATE_OBJECT, {"object_name": object_name, "axis": list(axis), "angle": angle},
            checkpoint=checkpoint, unit_overrides={"angle": "deg"},
        )

    def common_all(
        self, target: str, *, object_names: tuple[str, ...], checkpoint: str,
    ) -> str:
        return self._add(
            target, T.COMMON_ALL, {"object_names": list(object_names)},
            checkpoint=checkpoint, post=("one valid solid",),
        )

    def fuse_all(
        self, target: str, *, object_names: tuple[str, ...], checkpoint: str,
    ) -> str:
        return self._add(
            target, T.FUSE_ALL, {"object_names": list(object_names)},
            checkpoint=checkpoint, post=("one valid solid",),
        )

    def part_loft(
        self, target: str, *, profile_names: tuple[str, ...], checkpoint: str,
        solid: bool = True, ruled: bool = False, closed: bool = False,
    ) -> str:
        return self._add(
            target, T.PART_LOFT,
            {"profile_names": list(profile_names), "solid": solid, "ruled": ruled, "closed": closed},
            checkpoint=checkpoint, post=("one valid solid",),
        )

    def part_sweep(
        self, target: str, *, profile_name: str, spine_name: str, checkpoint: str,
        solid: bool = True, frenet: bool = True,
    ) -> str:
        return self._add(
            target, T.PART_SWEEP,
            {"profile_name": profile_name, "spine_name": spine_name, "solid": solid, "frenet": frenet},
            checkpoint=checkpoint, post=("one valid solid",),
        )

    def loft(
        self, target: str, *, sketches: tuple[str, ...], ruled: bool = False,
        closed: bool = False, checkpoint: str,
    ) -> str:
        return self._add(
            target, T.LOFT,
            {"sketches": list(sketches), "ruled": ruled, "closed": closed},
            checkpoint=checkpoint, post=("one valid solid",),
        )

    def sweep(
        self, target: str, *, profile_sketch: str, spine_sketch: str, checkpoint: str,
        transition: str = "Transformed",
    ) -> str:
        return self._add(
            target, T.SWEEP,
            {"profile_sketch": profile_sketch, "spine_sketch": spine_sketch, "transition": transition},
            checkpoint=checkpoint, post=("one valid solid",),
        )

    def groove(
        self, target: str, *, sketch: str, angle: float = 360.0, axis: str = "Base_X",
        checkpoint: str,
    ) -> str:
        return self._add(
            target, T.GROOVE, {"sketch": sketch, "angle": angle, "axis": axis},
            checkpoint=checkpoint, post=("one valid solid",),
            unit_overrides={"angle": "deg"},
        )

    def explode_compound(self, target: str, *, object_name: str, checkpoint: str) -> str:
        return self._add(
            target, T.EXPLODE_COMPOUND, {"object_name": object_name}, checkpoint=checkpoint,
        )

    def make_compound(
        self, target: str, *, object_names: tuple[str, ...], checkpoint: str,
    ) -> str:
        return self._add(
            target, T.MAKE_COMPOUND, {"object_names": list(object_names)}, checkpoint=checkpoint,
        )

    def make_face(self, target: str, *, object_name: str, checkpoint: str) -> str:
        return self._add(target, T.MAKE_FACE, {"object_name": object_name}, checkpoint=checkpoint)

    def make_wire(
        self, target: str, *, points: tuple[tuple[float, float, float], ...], closed: bool,
        checkpoint: str,
    ) -> str:
        return self._add(
            target, T.MAKE_WIRE,
            {"points": [list(pt) for pt in points], "closed": closed}, checkpoint=checkpoint,
        )

    def extrude(
        self, target: str, *, object_name: str, direction: tuple[float, float, float],
        checkpoint: str,
    ) -> str:
        return self._add(
            target, T.EXTRUDE, {"object_name": object_name, "direction": list(direction)},
            checkpoint=checkpoint, post=("one valid solid",),
        )

    def section_shape(
        self, target: str, *, object_name: str, plane: str = "XY", offset: float = 0.0,
        checkpoint: str,
    ) -> str:
        return self._add(
            target, T.SECTION_SHAPE, {"object_name": object_name, "plane": plane, "offset": offset},
            checkpoint=checkpoint,
        )

    def slice_shape(
        self, target: str, *, object_name: str, plane_point: tuple[float, float, float],
        plane_normal: tuple[float, float, float], checkpoint: str,
    ) -> str:
        return self._add(
            target, T.SLICE_SHAPE,
            {"object_name": object_name, "plane_point": list(plane_point),
             "plane_normal": list(plane_normal)},
            checkpoint=checkpoint,
        )

    # ---- observation --------------------------------------------------------

    def observe(self, target: str, *, active_subject: str, checkpoint: str) -> str:
        return self._add(
            target, T.OBSERVE_DOCUMENT, {"active_subject": active_subject},
            checkpoint=checkpoint,
        )

    def build(self) -> FeatureProgramIR:
        if not self._operations:
            raise ValueError("a feature program needs at least one operation")
        return FeatureProgramIR(
            self.schema_version, self.intent_id, self.document_id, tuple(self._operations)
        )
