# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""FILLET-PRO: professional fillet/chamfer behaviour, the layer above
capability 6 (already 8/8).

Founder pet peeve, verbatim: old-school CAD makes the user pick edges by
hand, fails cryptically when a radius doesn't fit, and breaks the fillet
the moment anything upstream changes. This module is CADWiz handling all of
that instead of the user.

**Edge selection by geometric query, never by name.** `select_edges` and
`create_smart_fillet` accept queries like `all_convex`, `top_face_perimeter`,
`longer_than(5)` -- resolved fresh against the CURRENT shape every time, so
there is no stored edge NAME to go stale when an upstream edit renumbers
FreeCAD's own internal topology (the well-known "topological naming
problem"). The query itself is stored (as a JSON string property on the
resulting fillet feature) and re-evaluated on every recompute via a real
`Part::FeaturePython` proxy (`QueryFilletFeature`, below) -- not a one-time
resolution frozen at creation time.

**Convexity, calibrated against real FreeCAD 1.1.3, not assumed.** For an
edge shared by exactly two faces, `Face.normalAt()` already returns a
correctly outward-pointing normal for a valid solid's face -- no manual
Orientation-based flip is needed (an earlier attempt applied one and got
inconsistent results). The sign of `cross(n1, n2).dot(tangent)`, where
`tangent` is taken from the edge as it appears in face1's own edge list
(with face1's own Orientation-based flip applied to the TANGENT, not the
normals), is `+1` for every edge of a plain box and exactly `-1` for the
one genuinely concave inner-corner edge of an L-shaped extrusion -- both
confirmed directly, 2026-09-08.
"""

from __future__ import annotations

import json
import math
import re
from typing import Any, Awaitable, Callable


# ---- geometric classification ---------------------------------------------


def _adjacent_faces(edge: Any, shape: Any) -> list[Any]:
    return [f for f in shape.Faces if any(e.isSame(edge) for e in f.Edges)]


def classify_convexity(edge: Any, shape: Any) -> str:
    """"convex", "concave", "tangent" (faces meet smoothly, no real corner),
    or "nonmanifold" (not shared by exactly two faces -- an open/boundary
    edge, excluded from every query below).
    """
    faces = _adjacent_faces(edge, shape)
    if len(faces) != 2:
        return "nonmanifold"
    f1, f2 = faces
    e_in_f1 = next((e for e in f1.Edges if e.isSame(edge)), None)
    if e_in_f1 is None:
        return "nonmanifold"
    mid_param = (e_in_f1.FirstParameter + e_in_f1.LastParameter) / 2
    pt = e_in_f1.valueAt(mid_param)
    tangent = e_in_f1.tangentAt(mid_param)
    if e_in_f1.Orientation == "Reversed":
        tangent = -tangent
    n1 = f1.normalAt(*f1.Surface.parameter(pt))
    n2 = f2.normalAt(*f2.Surface.parameter(pt))
    cross = n1.cross(n2)
    if cross.Length < 1e-9:
        return "tangent"
    sign = cross.dot(tangent)
    return "convex" if sign > 0 else "concave"


def classify_direction(edge: Any) -> str:
    """"vertical", "horizontal", or "other" -- straight edges only, by
    tangent alignment with the global Z axis. A curved edge is always
    "other": it has no single direction to classify.
    """
    curve_type = edge.Curve.TypeId if hasattr(edge, "Curve") else ""
    if "Line" not in curve_type:
        return "other"
    tangent = edge.tangentAt((edge.FirstParameter + edge.LastParameter) / 2)
    tangent.normalize()
    if abs(abs(tangent.z) - 1.0) < 1e-6:
        return "vertical"
    if abs(tangent.z) < 1e-6:
        return "horizontal"
    return "other"


# ---- query language ---------------------------------------------------


_CLAUSE_RE = re.compile(r"^(\w+)(?:\(([^)]*)\))?$")


def _parse_clause(clause: str) -> tuple[str, tuple[str, ...]]:
    match = _CLAUSE_RE.match(clause.strip())
    if not match:
        raise ValueError(f"unrecognized edge-query clause: {clause!r}")
    name, args = match.group(1), match.group(2)
    arg_tuple = tuple(a.strip() for a in args.split(",")) if args else ()
    return name, arg_tuple


def resolve_query(shape: Any, query: str | list[str]) -> list[str]:
    """Every edge name matching `query` against the shape's CURRENT geometry.

    `query` is one clause or a list of clauses, ANDed together (a query
    narrows the selection, it does not union separate ones -- "vertical"
    plus "longer_than(5)" means both, matching how a human would read the
    combination). Supported clauses: `all_outer`, `all_convex`,
    `all_concave`, `top_face_perimeter`, `edges_between(FaceA,FaceB)`,
    `longer_than(mm)`, `vertical`, `horizontal`.

    `all_outer` is deliberately simplified for this first version: it means
    every edge on the shape's own outer shell. For the common case this
    module is built for (a single-shell printable part, no internal
    cavities), that is every edge -- refining it to exclude edges bordering
    an internal void is real future work, not claimed here.
    """
    clauses = [query] if isinstance(query, str) else list(query)
    edges = list(shape.Edges)

    for clause in clauses:
        name, args = _parse_clause(clause)
        if name == "all_outer":
            continue  # simplified, see docstring
        elif name == "all_convex":
            edges = [e for e in edges if classify_convexity(e, shape) == "convex"]
        elif name == "all_concave":
            edges = [e for e in edges if classify_convexity(e, shape) == "concave"]
        elif name == "top_face_perimeter":
            top_face = max(shape.Faces, key=lambda f: f.CenterOfMass.z)
            edges = [e for e in edges if any(e.isSame(fe) for fe in top_face.Edges)]
        elif name == "edges_between":
            if len(args) != 2:
                raise ValueError("edges_between needs exactly two face names, e.g. edges_between(Face1,Face2)")
            face_a = _face_by_name(shape, args[0])
            face_b = _face_by_name(shape, args[1])
            edges = [
                e for e in edges
                if any(e.isSame(fe) for fe in face_a.Edges) and any(e.isSame(fe) for fe in face_b.Edges)
            ]
        elif name == "longer_than":
            if len(args) != 1:
                raise ValueError("longer_than needs exactly one value, e.g. longer_than(5)")
            threshold = float(args[0])
            edges = [e for e in edges if e.Length > threshold]
        elif name == "vertical":
            edges = [e for e in edges if classify_direction(e) == "vertical"]
        elif name == "horizontal":
            edges = [e for e in edges if classify_direction(e) == "horizontal"]
        elif name == "flat_adjacent_only":
            # Internal-only clause, not documented for end users: excludes
            # any edge bordering a non-planar face. Used automatically by
            # create_smart_fillet_impl when chaining a second group onto a
            # shape a prior group already filleted -- a fillet's own new
            # blend faces are curved, and their transitional edges (where a
            # blend face meets the original flat ones) are geometrically
            # concave in the same sense a real design corner is, so a
            # naive re-query for "the remaining concave edges" after a
            # convex group has already run would otherwise match the
            # fillet's own new geometry instead of the original corner.
            # Confirmed 2026-09-08: an L-shape's genuine single concave
            # edge was joined by three spurious ~2mm transitional edges
            # from the convex group's own fillet once applied first.
            edges = [
                e for e in edges
                if all(
                    f.Surface.TypeId == "Part::GeomPlane"
                    for f in _adjacent_faces(e, shape)
                )
            ]
        else:
            raise ValueError(f"unknown edge-query clause: {name!r}")

    return [_edge_name(shape, e) for e in edges]


#: PROVE-026 (docs/milestones/M-PROVE-SPEC.md): `fillet_edges`/`chamfer_edges`
#: take an explicit edge NAME ("Edge5"), not a symbolic query clause -- there
#: is no `all_convex`-style predicate to store for "the specific edge the
#: caller picked by hand". A geometric fingerprint is the query-language
#: equivalent for that case: identify the edge by where it IS, re-resolved
#: fresh against the current shape every recompute, the same way
#: `resolve_query` re-resolves a symbolic clause -- never by a frozen name or
#: FreeCAD's own Extended Element Name link (confirmed broken by a mere
#: upstream Pad Length change, PROVE-026's own measured evidence).
def edge_fingerprint(edge: Any) -> dict[str, Any]:
    """A geometric identity for one edge that survives a dimension change
    elsewhere in the shape.

    A straight edge is identified by a point on its own infinite line and
    that line's direction -- both independent of the edge's own length, so a
    Pad extruded taller along Z leaves a vertical edge's line exactly where
    it was, even though the edge's own two endpoints moved. A curved edge
    (arc/circle) is identified by its curve's own center instead, for the
    same reason: the center does not move when an unrelated dimension
    elsewhere changes, even though the edge's own endpoints might.
    """
    curve_type = edge.Curve.TypeId if hasattr(edge, "Curve") else ""
    mid_param = (edge.FirstParameter + edge.LastParameter) / 2
    point = edge.valueAt(mid_param)
    tangent = edge.tangentAt(mid_param)
    tangent.normalize()
    fingerprint: dict[str, Any] = {
        "curve_type": curve_type,
        "point": [point.x, point.y, point.z],
        "tangent": [tangent.x, tangent.y, tangent.z],
    }
    center = getattr(edge.Curve, "Center", None)
    if center is not None:
        fingerprint["center"] = [center.x, center.y, center.z]
    return fingerprint


def resolve_fingerprints(shape: Any, fingerprints: list[dict[str, Any]]) -> list[str]:
    """The fingerprint analogue of `resolve_query`: re-finds each stored
    fingerprint's own edge against the CURRENT shape, never reusing a name
    or index frozen at creation time. Raises if a fingerprint matches
    nothing -- silently dropping a requested edge would be a worse failure
    than an explicit one.
    """
    import FreeCAD  # noqa: PLC0415 - only importable inside FreeCAD's own process

    edges = list(shape.Edges)
    used: set[int] = set()
    resolved: list[str] = []
    for fingerprint in fingerprints:
        point = FreeCAD.Vector(*fingerprint["point"])
        tangent = FreeCAD.Vector(*fingerprint["tangent"])
        curve_type = fingerprint.get("curve_type", "")
        center = FreeCAD.Vector(*fingerprint["center"]) if "center" in fingerprint else None

        best_index: int | None = None
        best_score: float | None = None
        for index, candidate in enumerate(edges):
            if index in used:
                continue
            candidate_type = candidate.Curve.TypeId if hasattr(candidate, "Curve") else ""
            if curve_type and candidate_type != curve_type:
                continue
            if center is not None:
                candidate_center = getattr(candidate.Curve, "Center", None)
                if candidate_center is None:
                    continue
                score = candidate_center.sub(center).Length
            else:
                mid_param = (candidate.FirstParameter + candidate.LastParameter) / 2
                candidate_tangent = candidate.tangentAt(mid_param)
                candidate_tangent.normalize()
                if abs(candidate_tangent.dot(tangent)) < 1.0 - 1e-6:
                    continue  # not the same line direction -- not a candidate at all
                diff = candidate.valueAt(mid_param).sub(point)
                perpendicular = diff.sub(candidate_tangent.multiply(diff.dot(candidate_tangent)))
                score = perpendicular.Length
            if best_score is None or score < best_score:
                best_score, best_index = score, index

        if best_index is None:
            raise ValueError(f"fingerprint {fingerprint!r} matched no edge on the current shape")
        used.add(best_index)
        resolved.append(f"Edge{best_index + 1}")
    return resolved


def _find_partdesign_body(doc: Any, obj: Any) -> Any:
    """The same "is this object inside a PartDesign Body" check the vendored
    `fillet_edges`/`chamfer_edges` use, reproduced here (not imported --
    `vendor/` is never depended on the other direction) so PROVE-026's fix
    can make the identical routing decision."""
    for parent in doc.Objects:
        if parent.TypeId == "PartDesign::Body" and hasattr(parent, "Group") and obj in parent.Group:
            return parent
    return None


def create_dressup_impl(
    doc: Any, obj: Any, edge_names: list[str] | None, value: float, name: str | None, operation: str,
) -> dict[str, Any]:
    """PROVE-026's fix for `fillet_edges`/`chamfer_edges` on a PartDesign
    Body target: a `Part::FeaturePython` proxy (`QueryFilletFeature`, in
    fingerprint mode) that re-resolves its own edges by geometric fingerprint
    every recompute, instead of `PartDesign::Fillet`/`PartDesign::Chamfer`'s
    own frozen Extended Element Name link -- confirmed to break permanently
    after a mere upstream Pad Length change, identically for both features
    (docs/milestones/M-PROVE-SPEC.md PROVE-026, 2026-09-10).
    """
    base_shape = obj.Shape
    edges = (
        [base_shape.Edges[int(n[4:]) - 1] for n in edge_names]
        if edge_names else list(base_shape.Edges)
    )
    fingerprints = [edge_fingerprint(e) for e in edges]
    feature_name = name or ("Fillet" if operation == "fillet" else "Chamfer")
    feature = doc.addObject("Part::FeaturePython", feature_name)
    QueryFilletFeature(
        feature, obj, json.dumps(fingerprints), value,
        operation=operation, selection_mode="fingerprints",
    )
    doc.recompute()
    return {"name": feature.Name, "label": feature.Label, "type_id": feature.TypeId}


def _face_by_name(shape: Any, name: str) -> Any:
    match = re.match(r"^Face(\d+)$", name.strip())
    if not match:
        raise ValueError(f"expected a face name like 'Face3', got {name!r}")
    index = int(match.group(1)) - 1
    if not (0 <= index < len(shape.Faces)):
        raise ValueError(f"{name} out of range (shape has {len(shape.Faces)} faces)")
    return shape.Faces[index]


def _edge_name(shape: Any, edge: Any) -> str:
    for i, e in enumerate(shape.Edges):
        if e.isSame(edge):
            return f"Edge{i + 1}"
    raise ValueError("edge not found in shape's own Edges list")


# ---- feasibility --------------------------------------------------------


def max_feasible_radius(edge: Any, shape: Any) -> float:
    """The largest fillet radius this edge can plausibly take without a
    symmetric fillet on the opposite side of its narrowest adjacent face
    colliding with it.

    Computed as half the shortest distance from this edge to any OTHER edge
    in either of its two adjacent faces -- the same distance a symmetric
    fillet pair (this edge, and whatever mirrors it across that face) would
    have to split. Deliberately conservative: for a slot of width W, this
    gives W/2 for each long edge, exactly the ceiling past which two
    opposing fillets start to overlap -- confirmed against the "narrow
    slot" fixture, docs/milestones/M-PROVE-SPEC.md PROVE-017.
    """
    faces = _adjacent_faces(edge, shape)
    candidate_distances: list[float] = [edge.Length / 2.0]
    for face in faces:
        for other in face.Edges:
            if other.isSame(edge):
                continue
            try:
                distance = edge.distToShape(other)[0]
            except Exception:  # noqa: BLE001 - a degenerate distance query is just skipped
                continue
            if distance > 1e-9:
                candidate_distances.append(distance / 2.0)
    return min(candidate_distances) if candidate_distances else 0.0


# ---- grouping -------------------------------------------------------------


def group_edges(shape: Any, edge_names: list[str]) -> list[dict[str, Any]]:
    """Split `edge_names` into groups by convexity: convex vs concave (and
    "tangent", for edges whose adjacent faces meet smoothly with no real
    corner -- excluded from fillet attempts entirely, since there is
    nothing to round).

    **Simplified from the full spec on purpose.** The spec's own step 4
    also asks for connected-vs-isolated sub-splitting within a convexity
    group. That would need each resulting feature's re-evaluated query
    (see `create_smart_fillet_impl`, which stores a QUERY, not frozen edge
    names, specifically so it survives upstream edits) to express
    "connected to the others in this specific sub-group" -- a graph
    property, not a fixed geometric predicate the query language above can
    express and re-derive after a shape has changed. Convexity alone IS
    such a predicate (`all_convex`/`all_concave` re-resolve correctly every
    time), so it is what this version group is on. Isolated components
    within one convexity group share one fillet feature and one radius;
    if a real fixture needs them to differ, that is this simplification's
    known limit, stated here rather than silently.
    """
    by_name = {name: shape.Edges[int(name[4:]) - 1] for name in edge_names}
    convexity = {name: classify_convexity(edge, shape) for name, edge in by_name.items()}

    groups: dict[str, list[str]] = {}
    for name in edge_names:
        groups.setdefault(convexity[name], []).append(name)

    return [
        {"convexity": kind, "edge_names": names}
        for kind, names in groups.items()
        if kind in ("convex", "concave")
    ]


# ---- the query-re-evaluating feature ---------------------------------


class QueryFilletFeature:
    """A `Part::FeaturePython` proxy whose `execute()` re-resolves its own
    stored edge query against the CURRENT upstream shape on every
    recompute -- an upstream edit changes which edges the query matches,
    but the query itself, not a frozen list of edge names, is what survives.

    Mirrors `Part.BasicShapes.Shapes.TubeFeature`'s own pattern (confirmed
    2026-09-08 while building `create_tube`, M2b Group 3): a real property
    set plus a Python-side `execute()` that recomputes `fp.Shape` from
    those properties, not a wrapper around a second parametric feature.
    """

    def __init__(
        self, obj: Any, base: Any, query: str, radius: float,
        *, operation: str = "fillet", selection_mode: str = "clauses",
    ) -> None:
        obj.Proxy = self
        obj.addProperty("App::PropertyLink", "Base", "FilletPro", "The upstream feature this fillet reads from")
        obj.Base = base
        obj.addProperty("App::PropertyString", "Query", "FilletPro", "The edge-selection query, re-evaluated every recompute")
        obj.Query = query
        obj.addProperty("App::PropertyFloat", "Radius", "FilletPro", "Fillet radius (or chamfer size) in millimetres")
        obj.Radius = radius
        obj.addProperty(
            "App::PropertyString", "Operation", "FilletPro",
            "'fillet' (makeFillet) or 'chamfer' (makeChamfer) -- PROVE-026's fix reuses this "
            "proxy for chamfer_edges too, since both share the identical re-resolution problem",
        )
        obj.Operation = operation
        obj.addProperty(
            "App::PropertyString", "SelectionMode", "FilletPro",
            "'clauses' (Query is a JSON list of resolve_query strings) or 'fingerprints' "
            "(Query is a JSON list of edge_fingerprint dicts, resolved by resolve_fingerprints) "
            "-- PROVE-026's fix for fillet_edges/chamfer_edges' own explicit edge-name selection",
        )
        obj.SelectionMode = selection_mode
        obj.addProperty(
            "App::PropertyStringList", "LastResolvedEdges", "FilletPro",
            "The edge names the query matched on the most recent recompute, for diagnostics",
        )

    def execute(self, fp: Any) -> None:
        import json as _json  # noqa: PLC0415

        base_shape = fp.Base.Shape
        query = _json.loads(fp.Query)
        selection_mode = getattr(fp, "SelectionMode", "clauses")
        if selection_mode == "fingerprints":
            edge_names = resolve_fingerprints(base_shape, query)
        else:
            edge_names = resolve_query(base_shape, query)
        fp.LastResolvedEdges = edge_names
        if not edge_names:
            raise ValueError(f"query {query!r} matched no edges on the current shape")
        edges = [base_shape.Edges[int(name[4:]) - 1] for name in edge_names]
        operation = getattr(fp, "Operation", "fillet")
        if operation == "chamfer":
            fp.Shape = base_shape.makeChamfer(fp.Radius, edges)
        else:
            fp.Shape = base_shape.makeFillet(fp.Radius, edges)


# ---- the orchestration pipeline (runs inside FreeCAD's own process) ------


#: A group's own radius must land within this of its request to count as
#: "settled at the request", not "settled below it" -- 0.1mm per the spec.
_BISECTION_TOLERANCE_MM = 0.1
_MAX_BISECTION_ATTEMPTS = 6


def _try_fillet(base_shape: Any, edges: list[Any], radius: float) -> Any:
    """One kernel attempt. Returns the resulting Shape, or None on failure
    (a genuine OCC exception, or a shape that came back invalid -- treated
    the same as a kernel failure, since an invalid result is not a usable
    one)."""
    try:
        result = base_shape.makeFillet(radius, edges)
    except Exception:  # noqa: BLE001 - a kernel failure is the expected case being handled
        return None
    if result is None or result.isNull() or not result.isValid():
        return None
    return result


def _bisect_radius(base_shape: Any, edges: list[Any], requested: float, ceiling: float) -> dict[str, Any]:
    """Try `requested` first; on failure, bisect between 0 and
    `min(requested, ceiling)` for the largest working radius, within
    `_BISECTION_TOLERANCE_MM`, at most `_MAX_BISECTION_ATTEMPTS` attempts.
    Every attempt is logged, per the spec's own "log every attempt".
    """
    attempts: list[dict[str, Any]] = []
    cap = min(requested, ceiling) if ceiling > 0 else requested

    shape = _try_fillet(base_shape, edges, requested)
    attempts.append({"radius": requested, "ok": shape is not None})
    if shape is not None and requested <= ceiling + 1e-9:
        return {"radius": requested, "shape": shape, "attempts": attempts, "settled_below_request": False}

    low, high = 0.0, cap
    best_radius = 0.0
    best_shape = None
    for _ in range(_MAX_BISECTION_ATTEMPTS):
        if high - low < _BISECTION_TOLERANCE_MM:
            break
        mid = (low + high) / 2.0
        shape = _try_fillet(base_shape, edges, mid)
        attempts.append({"radius": mid, "ok": shape is not None})
        if shape is not None:
            best_radius, best_shape = mid, shape
            low = mid
        else:
            high = mid

    return {
        "radius": best_radius,
        "shape": best_shape,
        "attempts": attempts,
        "settled_below_request": True,
    }


def _analytic_volume_delta(edge_length: float, radius: float, convexity: str) -> float:
    """The material a fillet removes (convex) or adds (concave) for one
    edge, treating it as a 90-degree corner: `L * (R^2 - pi*R^2/4)` -- the
    same formula PROVE-015 confirmed exactly for a 2D sketch fillet's own
    area, extended along the edge length. An approximation for non-90-degree
    edges, disclosed as such -- the 25% tolerance in `verify_fillet_result`
    exists because of exactly this.
    """
    per_length = radius**2 * (1.0 - math.pi / 4.0)
    magnitude = edge_length * per_length
    return -magnitude if convexity == "convex" else magnitude


def create_smart_fillet_impl(
    doc: Any, base: Any, query: list[str], radius: float, name_prefix: str,
) -> dict[str, Any]:
    """The full pipeline: resolve -> group -> feasibility -> bisect ->
    create -> verify -> report. Runs entirely inside FreeCAD's process.
    """
    base_shape = base.Shape
    edge_names = resolve_query(base_shape, query)
    if not edge_names:
        raise ValueError(f"query {query!r} matched no edges on {base.Name}")

    # Grouping happens once, against the untouched base, purely to learn
    # which convexities are present -- NOT to freeze which edges belong to
    # each group. Every group's own edges are re-resolved fresh against
    # `current_base.Shape` below, the same query re-evaluation the stored
    # QueryFilletFeature itself will do on every future recompute; reusing
    # edge objects from `base_shape` after `current_base` has moved on to a
    # different feature's shape would be a stale-reference bug, not a
    # smaller version of the same one this whole module exists to avoid.
    initial_groups = group_edges(base_shape, edge_names)
    convexities_present = [g["convexity"] for g in initial_groups]

    group_reports: list[dict[str, Any]] = []
    features: list[Any] = []
    current_base = base

    for i, convexity in enumerate(convexities_present):
        group_query = list(query) + [f"all_{convexity}"]
        if i > 0:
            # See resolve_query's own "flat_adjacent_only" docstring: a
            # prior group's own fillet introduces new curved-face edges
            # that a naive convexity-only re-query would otherwise match
            # instead of the original design corners.
            group_query = group_query + ["flat_adjacent_only"]
        resolved_names = resolve_query(current_base.Shape, group_query)
        if not resolved_names:
            group_reports.append({
                "convexity": convexity, "edge_names": [], "requested_radius": radius,
                "used_radius": 0.0, "settled_below_request": True, "attempts": [],
                "applied": False, "note": "no matching edges found on re-resolution",
            })
            continue
        edges = [current_base.Shape.Edges[int(n[4:]) - 1] for n in resolved_names]
        ceiling = min(max_feasible_radius(e, current_base.Shape) for e in edges)
        outcome = _bisect_radius(current_base.Shape, edges, radius, ceiling)
        if outcome["shape"] is None:
            group_reports.append({
                "convexity": convexity,
                "edge_names": resolved_names,
                "requested_radius": radius,
                "used_radius": 0.0,
                "settled_below_request": True,
                "attempts": outcome["attempts"],
                "applied": False,
            })
            continue

        feature_name = f"{name_prefix}_{convexity}_{i}"
        feature = doc.addObject("Part::FeaturePython", feature_name)
        QueryFilletFeature(feature, current_base, json.dumps(group_query), outcome["radius"])
        doc.recompute()

        total_edge_length = sum(e.Length for e in edges)
        expected_delta = _analytic_volume_delta(total_edge_length, outcome["radius"], convexity)
        faces_before = len(current_base.Shape.Faces)
        actual_delta = feature.Shape.Volume - current_base.Shape.Volume
        actual_faces = len(feature.Shape.Faces)

        verified = (
            feature.Shape.isValid()
            and not feature.Shape.isNull()
            and actual_faces > faces_before
            and (
                expected_delta == 0
                or abs(actual_delta - expected_delta) <= 0.25 * abs(expected_delta) + 1e-6
            )
        )

        group_reports.append({
            "convexity": convexity,
            "edge_names": resolved_names,
            "requested_radius": radius,
            "used_radius": outcome["radius"],
            "settled_below_request": outcome["settled_below_request"],
            "attempts": outcome["attempts"],
            "applied": True,
            "feature_name": feature.Name,
            "verified": verified,
            "volume_delta": actual_delta,
            "expected_volume_delta": expected_delta,
            "face_count_before": faces_before,
            "face_count_after": actual_faces,
        })
        features.append(feature)
        current_base = feature

    return {
        "final_object": current_base.Name if features else base.Name,
        "groups": group_reports,
        "plain_language_report": build_plain_language_report(group_reports),
    }


def build_plain_language_report(group_reports: list[dict[str, Any]]) -> str:
    """Part 22's own vocabulary: what was asked, what was used, why, and
    the offer of alternatives -- never hidden in a log. Empty string if
    every group landed exactly at the request (nothing to explain)."""
    lines = []
    for group in group_reports:
        if not group["applied"]:
            lines.append(
                f"Could not fillet the {group['convexity']} edges "
                f"({len(group['edge_names'])} edge(s)) at {group['requested_radius']}mm -- "
                f"no working radius was found. Try a smaller radius, or change the "
                f"upstream geometry to give this corner more room."
            )
        elif group["settled_below_request"]:
            lines.append(
                f"You asked for a {group['requested_radius']}mm fillet on "
                f"{len(group['edge_names'])} {group['convexity']} edge(s), but the "
                f"geometry only had room for {group['used_radius']:.2f}mm there, so "
                f"that's what CADWiz used. Nothing else about your model changed. "
                f"To get the full {group['requested_radius']}mm, either widen the "
                f"nearby geometry, or ask for a chamfer instead -- a chamfer can fit "
                f"where a fillet of that size can't."
            )
    return "\n\n".join(lines)


# ---- fillets-last: the M-REACH planner rule ------------------------------


def _is_query_fillet(obj: Any) -> bool:
    return obj.TypeId == "Part::FeaturePython" and hasattr(obj, "Query") and hasattr(obj, "Base")


def _walk_fillet_chain(tip: Any) -> tuple[Any, list[tuple[str, float, str, str]]]:
    """From `tip`, walk `.Base` links back through every QueryFilletFeature,
    returning the true non-fillet base object and the (query_json, radius,
    operation, selection_mode) tuples in base-to-tip order -- what
    `rebuild_fillets_on` needs to recreate the same chain on a different
    base. `operation`/`selection_mode` are carried through explicitly
    (PROVE-026's fix) so a chamfer or fingerprint-selected feature in the
    chain rebuilds as itself, not silently reinterpreted as a clause-based
    fillet.
    """
    chain: list[tuple[str, float, str, str]] = []
    current = tip
    while _is_query_fillet(current):
        chain.append((
            current.Query, current.Radius,
            getattr(current, "Operation", "fillet"),
            getattr(current, "SelectionMode", "clauses"),
        ))
        current = current.Base
    chain.reverse()
    return current, chain


def rebuild_fillets_on(
    doc: Any, new_base: Any, chain: list[tuple[str, float, str, str]], name_prefix: str,
) -> Any:
    """Recreate a fillet chain (query, radius pairs, base-to-tip order) on
    top of `new_base` instead of whatever it was originally built on.

    This IS the planner rule from the spec: "fillet and chamfer features
    are placed at the end of the feature tree... suppresses fillets, adds
    the [new feature], re-applies fillets, then recomputes" -- implemented
    as rebuild rather than true in-place FreeCAD tree reordering (which a
    chain of independent Part::FeaturePython objects does not support
    without much more tree-surgery machinery than this module builds).
    Each fillet's own query is re-run fresh against the new chain's actual
    current shape at the point it is recreated, exactly as
    QueryFilletFeature.execute() does on every ordinary recompute -- this
    is not a special case, it is the same mechanism used once per
    surviving fillet.
    """
    current = new_base
    for i, (query_json, original_radius, operation, selection_mode) in enumerate(chain):
        feature = doc.addObject("Part::FeaturePython", f"{name_prefix}_rebuilt_{i}")
        QueryFilletFeature(
            feature, current, query_json, original_radius,
            operation=operation, selection_mode=selection_mode,
        )
        doc.recompute()
        current = feature
    return current


# ---- registration ---------------------------------------------------------


def register_fillet_pro_tools(mcp: Any, get_bridge: Callable[[], Awaitable[Any]]) -> None:
    """`select_edges` (read-only) and `create_smart_fillet` (the full
    query -> feasibility -> group -> bisect -> verify -> report pipeline).
    """

    @mcp.tool()
    async def select_edges(
        object_name: str,
        query: list[str],
        doc_name: str | None = None,
    ) -> dict[str, Any]:
        """Preview which edges a geometric query matches, without filleting.

        Read-only. See `create_smart_fillet` for what actually applies a
        fillet to the result -- this exists so a caller (or CADWiz's own
        conversational loop) can show the user what would be selected
        before committing to it.

        Args:
            object_name: Name of the object whose Shape to query.
            query: One or more clauses, ANDed together. Supported:
                "all_outer", "all_convex", "all_concave",
                "top_face_perimeter", "edges_between(FaceA,FaceB)",
                "longer_than(mm)", "vertical", "horizontal".
            doc_name: Document containing the object. Active document if None.

        Returns:
            edge_names, edge_count, convexity (a dict of edge_name ->
            "convex"/"concave"/"tangent"/"nonmanifold").
        """
        bridge = await get_bridge()
        query_json = json.dumps(query)
        code = f"""
import json
from integrations.mcp_tools.fillet_pro import resolve_query, classify_convexity

doc = FreeCAD.ActiveDocument if {doc_name!r} is None else FreeCAD.getDocument({doc_name!r})
if doc is None:
    raise ValueError("No document found")

obj = doc.getObject({object_name!r})
if obj is None:
    raise ValueError(f"Object not found: {object_name!r}")

shape = obj.Shape
query = json.loads({query_json!r})
edge_names = resolve_query(shape, query)
convexity = {{
    name: classify_convexity(shape.Edges[int(name[4:]) - 1], shape)
    for name in edge_names
}}

_result_ = {{
    "edge_names": edge_names,
    "edge_count": len(edge_names),
    "convexity": convexity,
}}
"""
        result = await bridge.execute_python(code)
        if result.success:
            return result.result
        raise ValueError(result.error_traceback or "select_edges failed")

    @mcp.tool()
    async def create_smart_fillet(
        object_name: str,
        query: list[str],
        radius: float,
        name: str | None = None,
        doc_name: str | None = None,
    ) -> dict[str, Any]:
        """Fillet edges selected by geometric query, with feasibility
        checking, automatic radius bisection, and a plain-language report
        if the request could not be fully honoured.

        This is the layer above `fillet_edges` (capability 6, already
        8/8): no edge names to pick by hand, a radius that does not fit
        somewhere does not fail the whole operation, and the selection
        survives upstream edits because it is stored as a query, re-run
        every recompute, not a frozen list of edge names.

        Args:
            object_name: Name of the object to fillet.
            query: One or more clauses, ANDed together -- see
                `select_edges` for the full list.
            radius: The requested fillet radius, in millimetres. Convex
                and concave edges among the matched set are grouped and
                filleted separately (concave edges physically add
                material when rounded; convex edges remove it), each
                bisected down from this radius independently if the full
                request does not fit.
            name: Prefix for the resulting feature name(s). Auto-generated
                if None.
            doc_name: Document containing the object. Active document if None.

        Returns:
            final_object: the name of the last feature in the resulting
                chain (fillet this, or a downstream tool, next).
            groups: one entry per convexity group -- requested_radius,
                used_radius, settled_below_request, attempts (every radius
                tried and whether it worked), verified, volume_delta,
                expected_volume_delta, face counts.
            plain_language_report: the Part 22-style explanation if any
                group settled below the request or could not be applied
                at all; empty string if everything was honoured exactly.
        """
        bridge = await get_bridge()
        query_json = json.dumps(query)
        code = f"""
import json
from integrations.mcp_tools.fillet_pro import create_smart_fillet_impl

doc = FreeCAD.ActiveDocument if {doc_name!r} is None else FreeCAD.getDocument({doc_name!r})
if doc is None:
    raise ValueError("No document found")

obj = doc.getObject({object_name!r})
if obj is None:
    raise ValueError(f"Object not found: {object_name!r}")

_result_ = create_smart_fillet_impl(doc, obj, json.loads({query_json!r}), {radius}, {name!r} or "SmartFillet")
"""
        result = await bridge.execute_python(code)
        if result.success:
            return result.result
        raise ValueError(result.error_traceback or "create_smart_fillet failed")

    @mcp.tool()
    async def insert_hole_before_fillets(
        fillet_tip_name: str,
        hole_sketch_name: str,
        diameter: float,
        depth: float,
        hole_type: str = "ThroughAll",
        cut_type: str = "None",
        cut_diameter: float = 0.0,
        cut_depth: float = 0.0,
        name: str | None = None,
        doc_name: str | None = None,
    ) -> dict[str, Any]:
        """The "fillets last" planner rule, for the concrete case of adding
        a hole after fillets already exist.

        Founder rule, verbatim: "If a user asks 'now add a hole,' CADWiz
        suppresses fillets, adds the hole, re-applies fillets, then
        recomputes." This walks back from `fillet_tip_name` through every
        `create_smart_fillet`-created feature to the true pre-fillet base,
        drills the hole THERE (`create_hole_advanced`, capability 22,
        already 8/8), then recreates each fillet's own stored query on top
        of the new hole -- implemented as a rebuild, since a chain of
        independent `Part::FeaturePython` fillet features has no in-place
        FreeCAD tree-reordering operation this module builds.

        Args:
            fillet_tip_name: Name of the current end of a fillet chain
                (whatever `create_smart_fillet` last returned as
                `final_object`).
            hole_sketch_name: Name of a sketch, attached to a face of the
                PRE-fillet base, carrying the hole's center point(s) --
                see `create_hole_advanced` for the same requirement.
            diameter, depth, hole_type, cut_type, cut_diameter, cut_depth:
                passed straight through to `create_hole_advanced`.
            name: Prefix for the rebuilt fillet feature names. Auto-
                generated if None.
            doc_name: Document containing the object. Active document if None.

        Returns:
            hole_name: the new hole feature's own name.
            final_object: the name of the new chain's own tip (a rebuilt
                fillet, or the hole itself if there was no fillet chain).
            fillet_count_rebuilt: how many fillet features were recreated.
        """
        bridge = await get_bridge()
        hole_code = f"""
doc = FreeCAD.ActiveDocument if {doc_name!r} is None else FreeCAD.getDocument({doc_name!r})
if doc is None:
    raise ValueError("No document found")

sketch = doc.getObject({hole_sketch_name!r})
if sketch is None:
    raise ValueError(f"Sketch not found: {hole_sketch_name!r}")

body = None
for obj in doc.Objects:
    if obj.TypeId == "PartDesign::Body" and hasattr(obj, "Group") and sketch in obj.Group:
        body = obj
        break
if body is None:
    raise ValueError("Sketch must be inside a PartDesign Body for Hole operation")

hole = body.newObject("PartDesign::Hole", {name!r} or "PreFilletHole")
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
    hole.HoleCutCountersinkAngle = 90.0
doc.recompute()

if hole.Shape is None or hole.Shape.isNull():
    raise ValueError(f"{{hole.Name}} produced a null shape after recompute")

from integrations.mcp_tools.fillet_pro import _walk_fillet_chain, rebuild_fillets_on

tip = doc.getObject({fillet_tip_name!r})
_pre_fillet_base, chain = _walk_fillet_chain(tip)
final = rebuild_fillets_on(doc, hole, chain, {name!r} or "PreFilletHole")

_result_ = {{
    "hole_name": hole.Name,
    "final_object": final.Name,
    "fillet_count_rebuilt": len(chain),
}}
"""
        result = await bridge.execute_python(hole_code)
        if result.success:
            return result.result
        raise ValueError(result.error_traceback or "insert_hole_before_fillets failed")

    # ---- PROVE-026 fix: fillet_edges/chamfer_edges, retrofitted --------
    #
    # The vendored versions of both tools (vendor/robust-mcp, never edited in
    # place) link a `PartDesign::Fillet`/`PartDesign::Chamfer`'s own `Base`
    # to a frozen list of edge objects, which FreeCAD resolves through its
    # own Extended Element Name mechanism. Measured to break permanently --
    # `Invalid edge link`, `Shape.Volume` frozen stale -- the moment the
    # source Pad's own `Length` changes, for BOTH tools identically
    # (docs/milestones/M-PROVE-SPEC.md PROVE-026, 2026-09-10). `mcp.
    # remove_tool` + a fresh `@mcp.tool()` registration under the SAME name
    # is required, not just registering a same-named function afterward --
    # `ToolManager.add_tool` silently keeps the FIRST registration on a name
    # collision (confirmed by reading its own source), so without the
    # explicit removal the vendored, broken version would keep winning.
    #
    # On a plain (non-Body) object these fall through to the exact same
    # `Part::Fillet`/`Part::Chamfer` path the vendored tools already use --
    # that path indexes edges directly, was never affected by this defect
    # (capability 6's own original Part::Box fixture proved it 8/8), and is
    # reproduced here rather than imported, since `vendor/` is never
    # depended on the other direction.

    mcp.remove_tool("fillet_edges")

    @mcp.tool()
    async def fillet_edges(
        object_name: str,
        radius: float,
        edges: list[str] | None = None,
        name: str | None = None,
        doc_name: str | None = None,
    ) -> dict[str, Any]:
        """Add fillet (rounded edges) to an object.

        PROVE-026 fix: on a PartDesign Body target, this uses a geometric
        edge fingerprint (see `edge_fingerprint`/`resolve_fingerprints`),
        re-resolved fresh every recompute, instead of `PartDesign::Fillet`'s
        own frozen Extended Element Name link -- confirmed to survive an
        upstream Pad Length change where the original broke permanently.
        Behaviour on a plain (non-Body) object is unchanged.

        Args:
            object_name: Name of the object to fillet.
            radius: Fillet radius.
            edges: List of edge names to fillet (e.g., ["Edge1", "Edge2"]).
                   Fillets all edges if None.
            name: Fillet feature name. Auto-generated if None.
            doc_name: Document containing the object. Uses active document if None.

        Returns:
            Dictionary with created fillet information:
                - name: Fillet name
                - label: Fillet label
                - type_id: Object type
        """
        bridge = await get_bridge()
        edges_param = edges if edges else None
        code = f"""
from integrations.mcp_tools.fillet_pro import create_dressup_impl, _find_partdesign_body

doc = FreeCAD.ActiveDocument if {doc_name!r} is None else FreeCAD.getDocument({doc_name!r})
if doc is None:
    raise ValueError("No document found")
obj = doc.getObject({object_name!r})
if obj is None:
    raise ValueError(f"Object not found: {object_name!r}")

body = _find_partdesign_body(doc, obj)
selected_edges = {edges_param!r}

doc.openTransaction("Fillet Edges")
try:
    if body:
        _result_ = create_dressup_impl(doc, obj, selected_edges, {radius}, {name!r}, "fillet")
    else:
        fillet_name = {name!r} or "Fillet"
        fillet = doc.addObject("Part::Fillet", fillet_name)
        fillet.Base = obj
        if selected_edges:
            edge_list = [(int(e.replace("Edge", "")), {radius}, {radius}) for e in selected_edges]
        else:
            edge_list = [(i + 1, {radius}, {radius}) for i in range(len(obj.Shape.Edges))]
        fillet.Edges = edge_list
        doc.recompute()
        _result_ = {{
            "name": fillet.Name,
            "label": fillet.Label,
            "type_id": fillet.TypeId,
        }}
    doc.commitTransaction()
except Exception:
    doc.abortTransaction()
    raise
"""
        result = await bridge.execute_python(code)
        if result.success:
            return result.result
        raise ValueError(result.error_traceback or "Fillet failed")

    mcp.remove_tool("chamfer_edges")

    @mcp.tool()
    async def chamfer_edges(
        object_name: str,
        size: float,
        edges: list[str] | None = None,
        name: str | None = None,
        doc_name: str | None = None,
    ) -> dict[str, Any]:
        """Add chamfer (beveled edges) to an object.

        PROVE-026 fix: on a PartDesign Body target, this uses a geometric
        edge fingerprint (see `edge_fingerprint`/`resolve_fingerprints`),
        re-resolved fresh every recompute, instead of `PartDesign::Chamfer`'s
        own frozen Extended Element Name link -- confirmed to survive an
        upstream Pad Length change where the original broke permanently.
        Behaviour on a plain (non-Body) object is unchanged.

        Args:
            object_name: Name of the object to chamfer.
            size: Chamfer size.
            edges: List of edge names to chamfer (e.g., ["Edge1", "Edge2"]).
                   Chamfers all edges if None.
            name: Chamfer feature name. Auto-generated if None.
            doc_name: Document containing the object. Uses active document if None.

        Returns:
            Dictionary with created chamfer information:
                - name: Chamfer name
                - label: Chamfer label
                - type_id: Object type
        """
        bridge = await get_bridge()
        edges_param = edges if edges else None
        code = f"""
from integrations.mcp_tools.fillet_pro import create_dressup_impl, _find_partdesign_body

doc = FreeCAD.ActiveDocument if {doc_name!r} is None else FreeCAD.getDocument({doc_name!r})
if doc is None:
    raise ValueError("No document found")
obj = doc.getObject({object_name!r})
if obj is None:
    raise ValueError(f"Object not found: {object_name!r}")

body = _find_partdesign_body(doc, obj)
selected_edges = {edges_param!r}

doc.openTransaction("Chamfer Edges")
try:
    if body:
        _result_ = create_dressup_impl(doc, obj, selected_edges, {size}, {name!r}, "chamfer")
    else:
        chamfer_name = {name!r} or "Chamfer"
        chamfer = doc.addObject("Part::Chamfer", chamfer_name)
        chamfer.Base = obj
        if selected_edges:
            edge_list = [(int(e.replace("Edge", "")), {size}, {size}) for e in selected_edges]
        else:
            edge_list = [(i + 1, {size}, {size}) for i in range(len(obj.Shape.Edges))]
        chamfer.Edges = edge_list
        doc.recompute()
        _result_ = {{
            "name": chamfer.Name,
            "label": chamfer.Label,
            "type_id": chamfer.TypeId,
        }}
    doc.commitTransaction()
except Exception:
    doc.abortTransaction()
    raise
"""
        result = await bridge.execute_python(code)
        if result.success:
            return result.result
        raise ValueError(result.error_traceback or "Chamfer failed")
