# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Render-and-verify, run after every mutation before success is reported.

The M0 audit found the render primitive built and exposed but never enforced:
`get_screenshot` existed as a tool the model could *choose* to call, and no
mutating tool called it. So a boolean that produced a null shape, or an object
left in an error state, returned success and nothing looked.

Three checks, cheapest first, and all three must pass:

1. **Recompute** - ask FreeCAD to rebuild. A mutation that leaves the document
   needing a recompute has not finished happening.
2. **Error state** - any object reporting an error fails the mutation, even
   though the tool call itself returned cleanly. This is the check that catches
   a fillet that took no edges.
3. **Render** - capture the 3D view. If the view cannot be drawn, something is
   wrong that the object graph did not admit to.

Where there is no GUI the render is skipped rather than failed, and the
verification records that it was skipped. Reporting a headless session as a
render failure would be a lie, and reporting it as a clean render would be a
worse one.
"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from ai_freecad_core.production_foundation.contracts import AssertionResult, VerificationResult
from ai_freecad_core.result_verifier import (
    DERIVED,
    HARD,
    build_verdict,
    check_clearance,
    check_collision,
    check_measurement_succeeded,
    check_recompute,
    check_shape_validity,
    check_solid_count,
    check_target_match,
)

# Small, because it is evidence rather than something anyone looks at.
RENDER_WIDTH = 640
RENDER_HEIGHT = 480

#: ORDER-2026-09-27-06 PHASE 3(b) / audit F3: real FreeCAD type IDs for
#: construction/reference geometry that is never expected to contain a
#: solid, by design -- a sketch is a profile to pad/pocket/revolve later,
#: not a finished part. Narrow and explicit on purpose: this exempts
#: known reference types from the solid_count HARD assertion, not any
#: object that merely happens to have a low solid count right now.
_NEVER_SOLID_TYPE_IDS = frozenset({
    "Sketcher::SketchObject",
    "PartDesign::Point",
    "PartDesign::Line",
    "PartDesign::Plane",
    "PartDesign::ShapeBinder",
    "Part::Point",
    "Part::Plane",
    "Part::Line",
    "App::Line",
    "App::Plane",
    "App::Origin",
    "Draft::Wire",
})

#: The outer, best-effort ceiling on the whole measurement probe. Real
#: protection against a single hanging OCC call now comes from
#: `EXACT_CALL_BUDGET_SECONDS` below, enforced *inside* the probe itself -
#: this outer wrapper cannot actually preempt a synchronous, non-yielding
#: `exec()` running in the same process as the embedded bridge (confirmed
#: 2026-09-09, PROVE-023: a probe ran 97+ minutes past this "30 second"
#: figure without `asyncio.wait_for` ever firing, because the coroutine
#: never yielded control back to the event loop). Kept, at a value large
#: enough to cover several exact-tier pairs, for bridges that genuinely can
#: cancel a call out-of-process (socket/xmlrpc).
MEASUREMENT_TIMEOUT_SECONDS = 600.0

#: Per PAIR, per exact-tier call (`Shape.common()`, then `distToShape()`),
#: not per probe -- run in a genuinely killable OS SUBPROCESS, not a
#: worker thread (see `_bounded_exact_`'s own docstring: a thread's
#: "budget" never actually bound anything, because `Shape.common()`
#: holds the GIL for its own duration). ORDER-2026-10-05-03 FOUNDER-
#: FOUND BUG: lowered from 120.0. A full pairwise sweep (every object
#: against every other) can hit many pairs that all fall through to this
#: tier -- confirmed live, 2026-10-05: the founder's 6-block picture
#: build needed 21 pairs (7 objects), and this single call blocked the
#: GUI thread (no event pumping happens inside a bare `subprocess.run`
#: wait) for up to 120s per pair per op, compounding toward the same
#: class of multi-minute freeze PROVE-023 already measured once at 97+
#: minutes. 120s is now also capped in aggregate across the whole probe
#: by EXACT_TIER_AGGREGATE_BUDGET_SECONDS below -- the two bounds work
#: together, not instead of each other.
EXACT_CALL_BUDGET_SECONDS = 20.0

#: ORDER-2026-10-05-03: a SECOND, aggregate ceiling across every pair's
#: exact-tier attempts within one probe run, checked between pairs (the
#: one place this probe genuinely can yield -- not mid-subprocess-wait,
#: which cannot be interrupted without killing the subprocess outright).
#: Once exhausted, every remaining pair that reaches tier 3 is recorded
#: "inconclusive_budget_exceeded" without even attempting the exact call
#: -- the same honest outcome a single slow call already produces, just
#: applied to the whole probe instead of letting a long pair sequence
#: run unbounded. This is what actually gives MEASUREMENT_TIMEOUT_
#: SECONDS below a real effect for this tier; that outer wrapper alone
#: was already measured not to preempt a non-yielding call (PROVE-023).
EXACT_TIER_AGGREGATE_BUDGET_SECONDS = 45.0

#: Tier 2's own pass/fail line: a coarse mesh's own vertices can be off by
#: roughly its own deflection (print_prep.py uses 1.5-2.0mm elsewhere in
#: this program for the same kind of estimate); a minimum vertex-to-vertex
#: gap comfortably past that is treated as ruling out a true intersection
#: without paying for the exact call.
MESH_TIER_CLEARANCE_MARGIN_MM = 4.0

#: PROVE-025 (2026-09-10): a real S3 model's own long, thin, non-cuboid
#: parts (two 182mm pivot arms) produced axis-aligned bounding boxes that
#: overlap even when the true solids may not -- an AABB is a poor fit for
#: a shape whose extent along one axis dwarfs the other two. Ratio of the
#: longest AABB edge to the second-longest; a shape at or past this ratio
#: gets the oriented-bounding-box tier below before falling through to the
#: coarse-mesh tier. Founder ruling, 2026-09-12, item 3.
OBB_ASPECT_RATIO_THRESHOLD = 2.5


@dataclass(frozen=True, slots=True)
class RenderVerification:
    """The evidence that a mutation actually landed."""

    ok: bool
    tool: str = ""
    recomputed: bool = False
    rendered: bool = False
    render_skipped: bool = False
    errors: tuple[str, ...] = field(default_factory=tuple)
    reason: str = ""
    #: The captured view, base64 PNG, when there was one. Kept rather than
    #: discarded: the render already happened to prove the mutation landed, and
    #: throwing the picture away meant paying for a screenshot after every
    #: build and then telling the user about it in words.
    #:
    #: Empty when headless, when the render failed, or when nothing was
    #: captured -- never a placeholder image, because a grey rectangle shown as
    #: confirmation is worse than showing nothing.
    image_base64: str = ""
    image_format: str = "png"
    viewport_valid: bool = False
    viewport_record: dict[str, object] = field(default_factory=dict)
    #: The structured, per-check pass/fail result from the CADWiz result
    #: verifier (docs/VERIFIER-SPEC.md) - shape validity, solid count,
    #: collision, and (when an expected_spec was given) target-match. None
    #: only when measurement was never attempted at all (an earlier,
    #: cheaper check already returned above it). Once attempted, this is
    #: always a real VerificationResult, including on a probe crash, hang/
    #: timeout, or malformed response - never silently None again after
    #: that point. See check_measurement_succeeded.
    result_verdict: VerificationResult | None = None

    @property
    def cad_operation_complete(self) -> bool:
        return self.ok and self.recomputed and (
            self.render_skipped or (self.rendered and self.viewport_valid)
        )

    def summary(self) -> str:
        if not self.ok:
            return f"unverified: {self.reason}"
        if self.render_skipped:
            return "verified (no GUI, render skipped)"
        return "verified by render"


_ERROR_PROBE = """
_bad_ = []
try:
    _doc_ = FreeCAD.ActiveDocument
    if _doc_ is not None:
        _doc_.recompute()
        for _o_ in _doc_.Objects:
            _state_ = list(getattr(_o_, 'State', []) or [])
            if 'Invalid' in _state_ or 'Error' in _state_:
                _bad_.append(_o_.Name)
            _sh_ = getattr(_o_, 'Shape', None)
            # Some objects are shapeless until something is put in them, and
            # that is not a fault. A fresh PartDesign::Body reports
            # State=['Up-to-date'], Tip=None and a null Shape; an empty sketch
            # is null until it has geometry. Flagging those made
            # `create_partdesign_body` fail verification every time it was
            # called against a real kernel -- so no Body could be created
            # through the tool layer at all, and pads and pockets were
            # unreachable behind it. Measured on FreeCAD 1.1.3, 2026-09-06.
            #
            # The check keeps its teeth where it matters: a Body that has a Tip
            # and still comes back null, or a sketch that has geometry and
            # still comes back null, is broken and is still reported.
            # It is the Tip that decides, not what the Body contains. A Body
            # holding only sketches and datums has no solid yet and reports
            # Tip=None; that is FreeCAD working correctly, not a broken build.
            # Once a Tip exists and the shape is still null, the Body really is
            # broken and is still reported.
            _empty_body_ = hasattr(_o_, 'Tip') and getattr(_o_, 'Tip', None) is None
            _empty_sketch_ = int(getattr(_o_, 'GeometryCount', -1)) == 0
            _shapeless_by_design_ = (
                (_empty_body_ or _empty_sketch_) and 'Invalid' not in _state_
                and 'Error' not in _state_
            )
            _null_ = (
                _sh_ is not None and hasattr(_sh_, 'isNull') and _sh_.isNull()
            )
            if _null_:
                # Nothing further may be asked of a null shape: isValid() calls
                # into BRepCheck_Analyzer, which raises Standard_NullObject and
                # took down the whole probe with 'probe-failed'.
                if not _shapeless_by_design_:
                    _bad_.append(_o_.Name + ':null-shape')
            elif _sh_ is not None and hasattr(_sh_, 'isValid') and not _sh_.isValid():
                _bad_.append(_o_.Name + ':invalid-shape')
            elif (_sh_ is not None and str(getattr(_o_, 'TypeId', '')).startswith('Part::')
                  and 'Part2DObject' not in str(getattr(_o_, 'TypeId', ''))
                  and hasattr(_sh_, 'Solids') and not _sh_.Solids
                  and hasattr(_sh_, 'Faces') and _sh_.Faces
                  and not (
                      hasattr(_sh_, 'BoundBox')
                      and min(_sh_.BoundBox.XLength, _sh_.BoundBox.YLength, _sh_.BoundBox.ZLength) < 1e-6
                  )):
                # A pure wire (no Faces, only Edges) is not a defect --
                # `Draft.make_line` reports TypeId 'Part::FeaturePython', which
                # the 'Part2DObject' exemption above does not cover the way it
                # covers `Draft.make_circle`/`make_rectangle`
                # (Part2DObjectPython), even though a free-standing Draft line
                # is exactly as shapeless-by-design as a sketch line. Measured
                # 2026-09-07, Layer 3's Draft 2D primitives:
                # `create_draft_line` failed render-after-op every time
                # without this, for having correctly made a wire rather than a
                # solid -- the same class of false failure `_empty_body_`/
                # `_empty_sketch_` above were added to fix. The `and _sh_.Faces`
                # clause keeps this narrow: a Part:: object with faces but no
                # solid (genuinely broken) is still caught.
                #
                # A flat reference face -- zero thickness in at least one
                # bounding-box dimension -- is the same class of not-a-fault
                # again, one level flatter: a Face with no Solids because it
                # was never meant to enclose a volume, not because a solid
                # failed to close. Measured 2026-09-08 against
                # PHONE_CONTACT_PLANE (`CADW-S3-PIVOT3-PHONE-PLANE-
                # 20260830T234002Z`, a real production model): TypeId
                # Part::Feature, 1 Face, 0 Solids, BoundBox
                # (0.0, 96.0, 171.0), isValid()==True -- a genuine flat
                # governance-plane marker, not a broken solid, and PRINT-
                # PREP's own `split_printable_parts` failed render-after-op
                # on this exact object every time without this exemption. A
                # solid construction that failed to CLOSE still occupies
                # three real dimensions (it is unclosed, not flat); an
                # exactly-zero bounding-box dimension is the narrow,
                # geometric signal that this shape was never meant to be a
                # solid at all.
                _bad_.append(_o_.Name + ':no-solid')
except Exception as _e_:
    _bad_.append('probe-failed:' + str(_e_))
_result_ = _bad_
"""


def _measure_probe(
    active_subjects: tuple[str, ...], *, exact_budget_s: float = EXACT_CALL_BUDGET_SECONDS,
    exact_tier_aggregate_budget_s: float = EXACT_TIER_AGGREGATE_BUDGET_SECONDS,
    mesh_margin_mm: float = MESH_TIER_CLEARANCE_MARGIN_MM,
    obb_aspect_threshold: float = OBB_ASPECT_RATIO_THRESHOLD,
) -> str:
    """Dimension/solid-count/validity/collision probe, same measurements as
    FreeCADGeometryValidator and FreeCADMotionEnvelopeValidator
    (integrations/freecad_native/validation.py), adapted to the bridge's
    execute_python transport so they run on the live tool-calling path
    instead of only the orphaned native-runtime front door.

    VERIFY-FAST, 2026-09-09 (PROVE-023): the pairwise collision/clearance
    check used to go straight to exact OCC `Shape.common()`/`distToShape()`
    for every pair, and on a real 117-object production assembly one such
    call did not return within 97 minutes. PROVE-025 (2026-09-10) then
    measured that AABB overlap alone is the wrong broad phase for that
    model's own long, thin parts: two 182mm pivot arms have IDENTICAL
    bounding boxes regardless of whether the real solids intersect, so
    tier 1 could not resolve any pair and tier 2's own "any vertex fell in
    the shared box" test was too permissive to be conclusive on its own.
    Founder ruling, 2026-09-12, item 3: keep cheap-first, per pair, but
    make each tier actually conclusive before falling through:

    1. Bounding-box overlap (six float comparisons). Boxes that do not
       overlap cannot intersect - no OCC call needed at all, and the boxes'
       own gap is a safe LOWER BOUND on true clearance (the real shapes are
       at least this far apart).
    1.5. Oriented-bounding-box separating-axis test, only for a pair where
       EITHER shape's own AABB aspect ratio (longest edge / second-longest)
       is at or past `OBB_ASPECT_RATIO_THRESHOLD` - the long-thin-part case
       PROVE-025 measured, where an axis-aligned box is a poor fit. Each
       flagged shape's own coarse mesh points (below) are PCA-reduced to a
       tight box aligned to the shape's own principal axes; the classic
       15-axis SAT (each OBB's 3 local axes, plus the 9 pairwise cross
       products) either proves separation - a real geometric guarantee, an
       OBB fully contains its shape - or is inconclusive and falls through.
       Skipped entirely for a pair where neither shape is long/thin: OBB
       construction costs a PCA that a compact part's own AABB already
       answers just as well.
    2. A coarse tessellated-mesh containment-plus-margin check, only when
       (1)/(1.5) did not resolve the pair. Earlier versions only asked
       "does any vertex of either mesh fall inside the two boxes' own
       overlap region", which PROVE-025 found routinely inconclusive for
       real, moderately complex parts (fillets and holes put vertices
       inside that region even when the true minimum gap is comfortably
       clear). This tests each mesh's own vertices for real containment
       inside the OTHER shape's actual BREP (`Part.Shape.isInside`, exact
       per point, not a bounding-box approximation) and ALSO requires the
       two point clouds' own minimum surface-to-surface distance
       (`scipy.spatial.cKDTree`) to clear `mesh_margin_mm`. Both conditions
       are required: distance alone is UNSOUND for two shapes that
       genuinely overlap (measured directly: two 50mm cubes sharing a real
       25x50x50mm overlap still have coarse surface vertices 25mm apart,
       since discrete corner samples do not know when one shape's interior
       has been penetrated) - only a real containment test catches that.
       Passing both is treated as a verified non-collision in its own right
       - tier 3 does not run for that pair at all - and the measured
       surface gap is recorded as this pair's own `min_clearance_mm` rather
       than left unset the way the old boolean-only version did.
    3. The exact OCC call, only when (2) is inconclusive (the coarse
       minimum distance is at or under `mesh_margin_mm`), run in a
       genuinely killable OS SUBPROCESS (`collision_worker.py`) with its
       own budget, not a thread - measured 2026-09-09 that `Shape.common()`
       does not release Python's GIL for its own duration, so a worker
       THREAD's "budget" never actually bound anything: the main thread's
       own timeout check also needs the GIL to run, and could not get it
       either, reproducing the exact multi-hour hang this tier exists to
       prevent (checkpoint 1 ran past 90 minutes on the real S3 model with
       the thread-based version in place). A subprocess has its own GIL and
       can be killed by the parent regardless of what it is doing; a call
       that blows its budget is recorded "inconclusive_budget_exceeded",
       not silently treated as "no collision".

    `pair_tiers` names which tier answered each pair, so a caller
    (`_build_result_verdict`'s own `check_collision` call) can report the
    tier actually used as evidence, not just the numbers it produced.
    """
    subject_json = json.dumps(tuple(str(value) for value in active_subjects))
    worker_path = str(Path(__file__).resolve().parent / "collision_worker.py")
    # ORDER-2026-10-05-03 FOUNDER-FOUND BUG: collision_worker.py's own
    # docstring has always said "Invoked as: freecadcmd.exe collision_
    # worker.py ..." -- headless, no window. The code below instead used
    # `sys.executable`, which is whatever binary is CURRENTLY running --
    # the GUI `freecad.exe` for every real, interactive session -- so
    # every exact-tier pair launched a full second GUI FreeCAD, visible
    # for the few seconds it took to run and exit. Confirmed live,
    # 2026-10-05: this is what the founder saw as a window "flashing
    # open for about three seconds and vanishing, roughly once a
    # minute." Derived here, once, from the real interpreter's own
    # directory, so it is `freecadcmd.exe` regardless of whether this
    # session is itself the GUI or the headless build.
    worker_exe = str(Path(sys.executable).resolve().with_name("freecadcmd.exe"))
    return f'''
import subprocess as _subprocess_
import sys as _sys_
import tempfile as _tempfile_
import os as _os_
import time as _time_
_shapes_ = {{}}
_overlap_mm3_ = 0.0
_min_clearance_mm_ = None
_pair_tiers_ = {{}}
_EXACT_BUDGET_S_ = {exact_budget_s}
_EXACT_TIER_DEADLINE_ = _time_.monotonic() + {exact_tier_aggregate_budget_s}
_MESH_MARGIN_MM_ = {mesh_margin_mm}
_OBB_ASPECT_THRESHOLD_ = {obb_aspect_threshold}
_WORKER_PATH_ = {worker_path!r}
_WORKER_EXE_ = {worker_exe!r}

def _boxes_overlap_(a, b):
    return (
        a.XMin <= b.XMax and a.XMax >= b.XMin
        and a.YMin <= b.YMax and a.YMax >= b.YMin
        and a.ZMin <= b.ZMax and a.ZMax >= b.ZMin
    )

def _box_gap_(a, b):
    gx = max(a.XMin - b.XMax, b.XMin - a.XMax, 0.0)
    gy = max(a.YMin - b.YMax, b.YMin - a.YMax, 0.0)
    gz = max(a.ZMin - b.ZMax, b.ZMin - a.ZMax, 0.0)
    return (gx * gx + gy * gy + gz * gz) ** 0.5

def _aspect_ratio_(bbox):
    """Longest AABB edge / second-longest. A cube is 1.0; PROVE-025's own
    182mm pivot arms are the shape this exists to flag."""
    edges = sorted((bbox.XLength, bbox.YLength, bbox.ZLength), reverse=True)
    if edges[1] <= 1e-9:
        return float("inf")
    return edges[0] / edges[1]

def _coarse_mesh_points_(shape):
    try:
        import MeshPart as _MeshPart_
        _mesh_ = _MeshPart_.meshFromShape(Shape=shape, LinearDeflection=2.0, AngularDeflection=0.8)
        _pts_ = []
        for _facet_ in _mesh_.Facets:
            _pts_.extend(_facet_.Points)
        return _pts_
    except Exception:
        return None

def _obb_from_points_(points):
    """PCA-reduced oriented bounding box: (center, axes, half_extents), or
    None if there are too few points or numpy is unavailable. `axes` is a
    3x3 array whose ROWS are the shape's own principal unit axes.

    Built from the SAME coarse tessellation `_coarse_mesh_points_` uses
    (LinearDeflection 2.0mm) -- the true continuous surface can bulge
    slightly beyond the straight lines connecting discrete tessellated
    vertices, so a box fit exactly to those vertices could be marginally
    too tight. Padded by that same 2.0mm deflection on every side so
    "OBBs do not overlap" stays a safe, slightly conservative claim rather
    than one that trusts the tessellation's own approximation error to be
    exactly zero."""
    _TESSELLATION_PAD_MM_ = 2.0
    try:
        import numpy as _np_
        _pts_ = _np_.asarray(points, dtype=float)
        if _pts_.shape[0] < 4:
            return None
        _mean_ = _pts_.mean(axis=0)
        _centered_ = _pts_ - _mean_
        _cov_ = _np_.cov(_centered_, rowvar=False)
        _eigvals_, _eigvecs_ = _np_.linalg.eigh(_cov_)
        _axes_ = _eigvecs_.T  # rows are unit eigenvectors, already orthonormal
        _proj_ = _centered_ @ _axes_.T
        _mins_ = _proj_.min(axis=0)
        _maxs_ = _proj_.max(axis=0)
        _half_extents_ = (_maxs_ - _mins_) / 2.0 + _TESSELLATION_PAD_MM_
        _local_center_ = (_maxs_ + _mins_) / 2.0
        _center_ = _mean_ + _local_center_ @ _axes_
        return _center_, _axes_, _half_extents_
    except Exception:
        return None

def _obb_overlap_(obb_a, obb_b):
    """Classic 15-axis separating-axis test between two oriented boxes.
    Returns True if the OBBs overlap (or the test could not run and is
    therefore inconclusive -- fails closed, same convention as every other
    tier here); False only on a PROVEN separating axis, which is a real
    geometric guarantee since an OBB fully contains the shape it was built
    from."""
    try:
        import numpy as _np_
        _center_a_, _axes_a_, _half_a_ = obb_a
        _center_b_, _axes_b_, _half_b_ = obb_b
        _t_ = _center_b_ - _center_a_
        _candidate_axes_ = list(_axes_a_) + list(_axes_b_)
        for _i_ in range(3):
            for _j_ in range(3):
                _cross_ = _np_.cross(_axes_a_[_i_], _axes_b_[_j_])
                _norm_ = _np_.linalg.norm(_cross_)
                if _norm_ > 1e-9:
                    _candidate_axes_.append(_cross_ / _norm_)
        for _axis_ in _candidate_axes_:
            _t_proj_ = abs(_np_.dot(_t_, _axis_))
            _r_a_ = sum(_half_a_[_k_] * abs(_np_.dot(_axes_a_[_k_], _axis_)) for _k_ in range(3))
            _r_b_ = sum(_half_b_[_k_] * abs(_np_.dot(_axes_b_[_k_], _axis_)) for _k_ in range(3))
            if _t_proj_ > _r_a_ + _r_b_ + 1e-6:
                return False
        return True
    except Exception:
        return True

def _min_cloud_distance_(pts_a, pts_b):
    """Minimum point-to-point distance between two coarse point clouds, via
    a `scipy.spatial.cKDTree` nearest-neighbour query -- O((n+m) log n), not
    the O(n*m) brute force. Returns None if scipy is unavailable or either
    cloud is empty, which the caller treats as inconclusive.

    NOT sufficient on its own -- surface-to-surface distance alone is
    UNSOUND for two shapes that genuinely overlap: two 50mm cubes offset
    25mm on one axis truly share a 25x50x50mm volume, but their own nearest
    CORNER vertices can still measure a positive gap (confirmed directly,
    this exact case: coarse vertex-to-vertex distance measured 25mm apart
    while `Shape.common()` reported a real 62500mm3 overlap) -- discrete
    surface samples do not know when one shape's interior has been
    penetrated. `_any_point_inside_shape_` below is what actually catches
    that; this distance is only an EXTRA margin on top of it, the same
    tessellation-deflection safety margin the original tier 2 already used."""
    try:
        from scipy.spatial import cKDTree as _cKDTree_
        if not pts_a or not pts_b:
            return None
        _tree_ = _cKDTree_(pts_b)
        _dists_, _ = _tree_.query(pts_a, k=1)
        return float(min(_dists_))
    except Exception:
        return None

def _any_point_inside_shape_(points, shape, tolerance=1e-4):
    """Whether any coarse tessellation vertex of ONE shape lies inside the
    OTHER shape's real BREP, via `Part.Shape.isInside` -- an exact,
    per-point containment test against the actual solid, not an
    approximation against its bounding box. This is the soundness fix over
    both the old tier 2 (tested against the two AABBs' shared region, a
    looser superset of the real shape) and a surface-distance-only test
    (unsound for genuine overlap, see `_min_cloud_distance_`'s own note):
    a point actually inside the other real shape is unambiguous evidence
    of intersection, whatever the coarse mesh's own vertices happen to
    measure to each other."""
    for _point_ in points:
        try:
            if shape.isInside(FreeCAD.Vector(*_point_), tolerance, True):
                return True
        except Exception:
            return True  # inconclusive on error -> do not clear the pair
    return False

def _bounded_exact_(shape_a, shape_b, budget):
    """Runs `collision_worker.py` as a genuinely killable OS subprocess for
    each of the two exact calls (common, distance) between `shape_a` and
    `shape_b`, budgeted independently. `subprocess.run(..., timeout=...)`
    kills the child process on timeout regardless of whether it has
    released the GIL -- it is a separate process with its own -- unlike
    the worker-THREAD version this replaced, whose own "budget" never
    actually bound anything (measured 2026-09-09: `Shape.common()` holds
    the GIL for its own duration, so the calling thread's own timeout
    check could not run either).

    Returns (overlap_volume_or_None, overlap_ok, distance_or_None,
    distance_ok)."""
    _tmp_dir_ = _tempfile_.mkdtemp(prefix="cadwiz_collision_")
    _path_a_ = _os_.path.join(_tmp_dir_, "a.brep")
    _path_b_ = _os_.path.join(_tmp_dir_, "b.brep")
    try:
        with open(_path_a_, "w", encoding="utf-8") as _f_:
            _f_.write(shape_a.exportBrepToString())
        with open(_path_b_, "w", encoding="utf-8") as _f_:
            _f_.write(shape_b.exportBrepToString())

        def _run_op_(op):
            # ORDER-2026-10-05-03 FOUNDER-FOUND BUG, part 2: a bare
            # `subprocess.run(timeout=budget)` blocks this thread -- the
            # real FreeCAD GUI thread -- for up to the WHOLE budget with
            # no event pumping at all. Confirmed live with a heartbeat
            # proof: fixing only the executable (headless, no visible
            # window) and the aggregate ceiling above still left a
            # single pair's own wait as a real, measured ~57s gap with
            # the window not repainting. `Popen` + a short poll loop
            # lets this call pump Qt's event loop between polls instead
            # -- the subprocess itself is unaffected (still a real,
            # killable OS process on its own budget), only HOW this
            # thread waits for it changes.
            try:
                _proc_ = _subprocess_.Popen(
                    [_WORKER_EXE_, _WORKER_PATH_, op, _path_a_, _path_b_],
                    stdout=_subprocess_.PIPE, stderr=_subprocess_.PIPE, text=True,
                )
            except Exception:
                return None, False
            _deadline_ = _time_.monotonic() + budget
            try:
                _qt_widgets_ = None
                try:
                    import PySide.QtWidgets as _qt_widgets_
                except Exception:
                    _qt_widgets_ = None
                while _proc_.poll() is None:
                    if _time_.monotonic() > _deadline_:
                        _proc_.kill()
                        _proc_.wait()
                        return None, False
                    if _qt_widgets_ is not None:
                        try:
                            _qt_widgets_.QApplication.processEvents()
                        except Exception:
                            pass
                    _time_.sleep(0.05)
                _stdout_, _ = _proc_.communicate()
            except Exception:
                return None, False
            if _proc_.returncode != 0:
                return None, False
            try:
                # Only the first line: `freecadcmd.exe` prints its own
                # version banner to stdout on process shutdown, appended
                # directly after the worker's own output (confirmed
                # 2026-09-09) - the worker's own result is always exactly
                # one line, newline-terminated, written and flushed before
                # that banner has a chance to interleave.
                _out_lines_ = _stdout_.splitlines()
                if op == "both":
                    return (float(_out_lines_[0].strip()), float(_out_lines_[1].strip())), True
                return float(_out_lines_[0].strip()), True
            except (TypeError, ValueError, IndexError):
                return None, False

        # ORDER-2026-10-06-01: one helper process for both measurements --
        # starting a headless FreeCAD costs ~2.5 s each time, so two per pair
        # was most of the time a 21-pair check took.
        _pair_result_, _pair_ok_ = _run_op_("both")
        if _pair_ok_:
            return _pair_result_[0], True, _pair_result_[1], True
        return None, False, None, False
    finally:
        for _path_ in (_path_a_, _path_b_):
            try:
                _os_.remove(_path_)
            except OSError:
                pass
        try:
            _os_.rmdir(_tmp_dir_)
        except OSError:
            pass

try:
    _doc_ = FreeCAD.ActiveDocument
    if _doc_ is not None:
        _names_ = set({subject_json})
        _objs_ = [
            _o_ for _o_ in _doc_.Objects
            if getattr(_o_, "Shape", None) is not None and not _o_.Shape.isNull()
            and (not _names_ or _o_.Name in _names_)
        ]
        for _o_ in _objs_:
            _sh_ = _o_.Shape
            _box_ = _sh_.BoundBox
            _shapes_[_o_.Name] = {{
                "valid": bool(_sh_.isValid()),
                "solids": len(_sh_.Solids),
                "x_mm": float(_box_.XLength),
                "y_mm": float(_box_.YLength),
                "z_mm": float(_box_.ZLength),
                "volume_mm3": float(_sh_.Volume) if _sh_.Solids else 0.0,
                # ORDER-2026-09-27-06 PHASE 3(b): so a caller can tell a
                # sketch/reference object (never expected to have solids)
                # apart from a part that was supposed to produce one.
                "type_id": _o_.TypeId,
            }}
        _mesh_cache_ = {{}}
        _obb_cache_ = {{}}
        _pair_total_ = len(_objs_) * (len(_objs_) - 1) // 2
        _pair_done_ = 0
        for _i_ in range(len(_objs_)):
            for _j_ in range(_i_ + 1, len(_objs_)):
                _pair_done_ += 1
                print("CADWIZ_PROGRESS", _pair_done_, _pair_total_, flush=True)
                _a_ = _objs_[_i_]
                _b_ = _objs_[_j_]
                _pair_key_ = f"{{_a_.Name}}:{{_b_.Name}}"
                _bb_a_ = _a_.Shape.BoundBox
                _bb_b_ = _b_.Shape.BoundBox

                # ---- tier 1: bounding-box overlap -------------------------
                if not _boxes_overlap_(_bb_a_, _bb_b_):
                    _pair_tiers_[_pair_key_] = "bbox_no_overlap"
                    _gap_ = _box_gap_(_bb_a_, _bb_b_)
                    if _min_clearance_mm_ is None or _gap_ < _min_clearance_mm_:
                        _min_clearance_mm_ = _gap_
                    continue

                if _a_.Name not in _mesh_cache_:
                    _mesh_cache_[_a_.Name] = _coarse_mesh_points_(_a_.Shape)
                if _b_.Name not in _mesh_cache_:
                    _mesh_cache_[_b_.Name] = _coarse_mesh_points_(_b_.Shape)
                _pts_a_ = _mesh_cache_[_a_.Name]
                _pts_b_ = _mesh_cache_[_b_.Name]

                # ---- tier 1.5: oriented-bounding-box SAT, long/thin only ---
                if (
                    max(_aspect_ratio_(_bb_a_), _aspect_ratio_(_bb_b_)) >= _OBB_ASPECT_THRESHOLD_
                    and _pts_a_ is not None and _pts_b_ is not None
                ):
                    if _a_.Name not in _obb_cache_:
                        _obb_cache_[_a_.Name] = _obb_from_points_(_pts_a_)
                    if _b_.Name not in _obb_cache_:
                        _obb_cache_[_b_.Name] = _obb_from_points_(_pts_b_)
                    _obb_a_ = _obb_cache_[_a_.Name]
                    _obb_b_ = _obb_cache_[_b_.Name]
                    if _obb_a_ is not None and _obb_b_ is not None and not _obb_overlap_(_obb_a_, _obb_b_):
                        _pair_tiers_[_pair_key_] = "obb_no_overlap"
                        continue

                # ---- tier 2: coarse tessellated-mesh containment + margin -
                _mesh_conclusive_ = False
                if _pts_a_ is not None and _pts_b_ is not None:
                    _coarse_gap_ = _min_cloud_distance_(_pts_a_, _pts_b_)
                    _a_inside_b_ = _any_point_inside_shape_(_pts_a_, _b_.Shape)
                    _b_inside_a_ = False if _a_inside_b_ else _any_point_inside_shape_(_pts_b_, _a_.Shape)
                    if (
                        _coarse_gap_ is not None and _coarse_gap_ > _MESH_MARGIN_MM_
                        and not _a_inside_b_ and not _b_inside_a_
                    ):
                        _pair_tiers_[_pair_key_] = "mesh_no_overlap"
                        if _min_clearance_mm_ is None or _coarse_gap_ < _min_clearance_mm_:
                            _min_clearance_mm_ = _coarse_gap_
                        _mesh_conclusive_ = True
                if _mesh_conclusive_:
                    continue

                # ---- tier 3: exact OCC call, budgeted (subprocess) --------
                # ORDER-2026-10-05-03: the aggregate ceiling. A single
                # call's own timeout cannot be interrupted mid-wait, but
                # BETWEEN pairs this probe can check whether it has
                # already spent its whole exact-tier allowance -- once
                # it has, every remaining pair is honestly recorded
                # "inconclusive_budget_exceeded" without attempting
                # another possibly-120s-class call, instead of running
                # the full pairwise sweep unbounded.
                if _time_.monotonic() > _EXACT_TIER_DEADLINE_:
                    _pair_tiers_[_pair_key_] = "inconclusive_budget_exceeded"
                    continue
                _common_result_, _common_ok_, _distance_result_, _distance_ok_ = _bounded_exact_(
                    _a_.Shape, _b_.Shape, _EXACT_BUDGET_S_,
                )
                if _common_ok_:
                    _overlap_mm3_ += float(_common_result_)
                if _distance_ok_:
                    _distance_ = float(_distance_result_)
                    if _min_clearance_mm_ is None or _distance_ < _min_clearance_mm_:
                        _min_clearance_mm_ = _distance_
                _pair_tiers_[_pair_key_] = "exact" if (_common_ok_ and _distance_ok_) else "inconclusive_budget_exceeded"
except Exception as _e_:
    _shapes_ = {{"__error__": str(_e_)}}
_result_ = {{
    "shapes": _shapes_, "overlap_mm3": _overlap_mm3_, "min_clearance_mm": _min_clearance_mm_,
    "pair_tiers": _pair_tiers_,
}}
'''


def _isolated_probe_available(bridge: Any) -> bool:
    """True only inside the real FreeCAD GUI process, where the headless
    runner exists. Fake bridges (tests) and headless runs keep the in-process
    path unchanged."""
    import os

    from .isolated import headless_available

    if os.environ.get("CADWIZ_PROBE_INPROCESS") == "1":
        return False
    if getattr(bridge, "_fc_module", None) is None:
        return False
    return headless_available()


def _run_probe_isolated(bridge: Any, macro: str, timeout_s: float) -> dict[str, Any]:
    """Run the measurement probe in a headless worker process on a saved copy
    of the active document, keeping the window alive while waiting.

    Read-only by construction: nothing the worker does can touch the user's
    document. Cancel (`BuildCancelled` raised by `progress.pump()`) kills the
    worker and propagates. Returns what the probe returned, or
    `{"error": ...}` exactly as the in-process path would.
    """
    import shutil
    import tempfile

    from . import progress
    from .isolated import run_headless

    document = bridge._fc_module.ActiveDocument
    if document is None:
        return {"shapes": {}, "overlap_mm3": 0.0, "min_clearance_mm": None, "pair_tiers": {}}
    work_dir = tempfile.mkdtemp(prefix="cadwiz_probe_")
    try:
        copy_path = str(Path(work_dir) / "doc.FCStd")
        macro_path = Path(work_dir) / "probe_macro.py"
        result_path = Path(work_dir) / "result.json"
        progress.report("Saving a safe copy to measure")
        document.saveCopy(copy_path)
        macro_path.write_text(macro, encoding="utf-8")

        def on_line(line: str) -> None:
            parts = line.split()
            if len(parts) == 3 and parts[0] == "CADWIZ_PROGRESS":
                progress.status(f"Checking that parts don't overlap, {parts[1]} of {parts[2]}")

        outcome = run_headless(
            str(Path(__file__).resolve().parent / "probe_runner.py"),
            [copy_path, str(macro_path), str(result_path)],
            timeout_s=timeout_s,
            label="Measuring the model",
            on_line=on_line,
        )
        if outcome.timed_out:
            return {"error": f"measurement probe timed out after {timeout_s:g}s"}
        if outcome.returncode != 0 or not result_path.exists():
            detail = outcome.stderr.strip() or f"exit code {outcome.returncode}"
            return {"error": f"measurement probe reported failure: {detail}"}
        measured = json.loads(result_path.read_text(encoding="utf-8"))
        if isinstance(measured, dict):
            return measured
        return {"error": "measurement probe did not return structured evidence"}
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


async def measure_objects(
    bridge: Any, active_subjects: tuple[str, ...] = ()
) -> dict[str, Any]:
    """Measure real geometry (dims, solid count, validity, overlap) over the
    live bridge. Always returns a dict - never None, never raises. Any
    crash, hang/timeout, or malformed response is reported as
    `{"error": "<text>"}` so the caller can turn it into an explicit FAIL
    with the error captured as evidence, rather than a silently-missing
    verdict. A verifier that can go quiet under exactly the conditions
    worth catching is worse than one that is merely strict.
    """
    macro = _measure_probe(active_subjects)
    if _isolated_probe_available(bridge):
        from .build_safety import BuildCancelled

        try:
            isolated = _run_probe_isolated(bridge, macro, MEASUREMENT_TIMEOUT_SECONDS)
        except BuildCancelled:
            raise
        except Exception as error:  # noqa: BLE001
            return {"error": f"measurement probe raised: {error}"}
        shapes = isolated.get("shapes") if isinstance(isolated, dict) else None
        if not isinstance(shapes, dict):
            if isinstance(isolated, dict) and "error" in isolated:
                return isolated
            return {"error": "measurement probe did not return structured evidence"}
        if "__error__" in shapes:
            return {"error": f"measurement probe's own script raised: {shapes['__error__']}"}
        return isolated
    try:
        probe = await asyncio.wait_for(
            bridge.execute_python(macro),
            timeout=MEASUREMENT_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        return {"error": f"measurement probe timed out after {MEASUREMENT_TIMEOUT_SECONDS:g}s"}
    except Exception as error:  # noqa: BLE001
        return {"error": f"measurement probe raised: {error}"}
    if not getattr(probe, "success", False):
        detail = getattr(probe, "error", "") or getattr(probe, "stderr", "") or "no detail"
        return {"error": f"measurement probe reported failure: {detail}"}
    measured = getattr(probe, "result", None)
    if not isinstance(measured, dict) or not isinstance(measured.get("shapes"), dict):
        return {"error": "measurement probe did not return structured evidence"}
    shapes = measured["shapes"]
    if "__error__" in shapes:
        return {"error": f"measurement probe's own script raised: {shapes['__error__']}"}
    return measured


def grade_against_target(
    measured: Mapping[str, Any],
    expected_spec: Mapping[str, Any],
    *,
    tolerance_mm: float = 0.5,
    features: Sequence[str] = (),
) -> VerificationResult:
    """Does a measured result match an expected target spec (dimensions
    within tolerance, required features present, no collision)? Pure and
    host-neutral past this point - see ai_freecad_core.result_verifier.

    A measurement error fails closed here too, same as _build_result_verdict:
    grading zeros against a target as if they were real geometry would be a
    fabricated result, not a lenient one.
    """
    error = measured.get("error")
    if error is not None:
        return build_verdict((check_measurement_succeeded(str(error)),))

    shapes = measured.get("shapes") or {}
    primary_name = next(iter(sorted(shapes)), None)
    primary = shapes.get(primary_name, {}) if primary_name else {}
    produced = {
        "dimensions_mm": {
            "x_mm": primary.get("x_mm", 0.0),
            "y_mm": primary.get("y_mm", 0.0),
            "z_mm": primary.get("z_mm", 0.0),
        },
        "features": tuple(features),
        "overlap_mm3": float(measured.get("overlap_mm3", 0.0)),
    }
    assertion = check_target_match(produced, expected_spec, tolerance_mm=tolerance_mm)
    return build_verdict((assertion,))


def _build_result_verdict(
    measured: Mapping[str, Any],
    *,
    expected_spec: Mapping[str, Any] | None = None,
    tolerance_mm: float = 0.5,
) -> VerificationResult:
    """Always returns a real verdict - see measure_objects()'s docstring.

    A measurement error short-circuits to a single FAIL assertion carrying
    the error text as evidence: there is no real shape data to check
    anything else against, and reporting fabricated pass/fail on the
    other checks would be worse than reporting none of them.
    """
    error = measured.get("error")
    if error is not None:
        return build_verdict((check_measurement_succeeded(str(error)),))

    shapes = measured.get("shapes") or {}
    # ORDER-2026-09-27-06 PHASE 3(b) / audit F3: "some zero-solid checks
    # are inappropriate for intentional sketches." A Sketcher/reference
    # object legitimately has zero solids by design -- it was never
    # supposed to produce one, so it must not fail the same HARD
    # assertion a part that actually needed a solid would fail on.
    # Scoped narrowly to known, real FreeCAD construction/reference
    # types, not every object with a low solid count.
    solid_count_shapes = {
        name: data
        for name, data in shapes.items()
        if str(data.get("type_id", "")) not in _NEVER_SOLID_TYPE_IDS
    }
    if solid_count_shapes:
        solid_count_assertion = check_solid_count(solid_count_shapes)
    elif shapes:
        # Everything measured is a known construction/reference type (a
        # sketch, a datum) -- there is nothing here that was ever supposed
        # to have a solid, so the check does not apply. check_solid_count
        # itself would read an empty input as "no measured shapes" and
        # FAIL, which is right when nothing was measured at all but wrong
        # here: something real was measured, it just never needed a solid.
        solid_count_assertion = AssertionResult(
            "solid_count", HARD, True, expected=1, observed={},
            detail="not applicable -- every measured object is a sketch/reference type",
        )
    else:
        solid_count_assertion = check_solid_count(solid_count_shapes)
    assertions = [
        check_measurement_succeeded(None),
        check_shape_validity(shapes),
        solid_count_assertion,
        check_collision(float(measured.get("overlap_mm3", 0.0)), tiers=measured.get("pair_tiers")),
    ]
    if expected_spec is not None:
        primary_name = next(iter(sorted(shapes)), None)
        primary = shapes.get(primary_name, {}) if primary_name else {}
        produced = {
            "dimensions_mm": {
                "x_mm": primary.get("x_mm", 0.0),
                "y_mm": primary.get("y_mm", 0.0),
                "z_mm": primary.get("z_mm", 0.0),
            },
            "features": (),
            "overlap_mm3": float(measured.get("overlap_mm3", 0.0)),
        }
        assertions.append(check_target_match(produced, expected_spec, tolerance_mm=tolerance_mm))

        required_clearance = expected_spec.get("minimum_clearance_mm")
        if required_clearance is not None:
            measured_clearance = measured.get("min_clearance_mm")
            if measured_clearance is None:
                # A clearance requirement was stated but there were fewer
                # than two objects to measure a distance between. That is a
                # failure to confirm the requirement, not nothing to report -
                # the same no-skip principle as a probe crash, expressed
                # directly rather than via a sentinel value through
                # check_clearance.
                assertions.append(
                    AssertionResult(
                        "clearance",
                        DERIVED,
                        False,
                        expected=required_clearance,
                        observed=None,
                        detail="clearance was required but fewer than two objects "
                        "were measured to compute a distance between",
                    )
                )
            else:
                assertions.append(
                    check_clearance(float(measured_clearance), float(required_clearance))
                )
    return build_verdict(tuple(assertions))


async def verify_after_mutation(
    bridge: Any,
    tool: str,
    *,
    active_subjects: tuple[str, ...] = (),
    operation_id: str = "",
    expected_spec: Mapping[str, Any] | None = None,
) -> RenderVerification:
    """Recompute, look for broken objects, then draw it. All three must pass."""
    # 1 + 2. Recompute and inspect, in one round trip.
    try:
        probe = await bridge.execute_python(_ERROR_PROBE)
    except Exception as error:  # noqa: BLE001
        return RenderVerification(
            ok=False, tool=tool, reason=f"could not recompute: {error}"
        )

    if not getattr(probe, "success", False):
        detail = getattr(probe, "error", "") or getattr(probe, "stderr", "")
        return RenderVerification(
            ok=False, tool=tool, reason=f"recompute failed: {detail}"
        )

    broken = tuple(str(name) for name in (getattr(probe, "result", None) or ()))
    if broken:
        return RenderVerification(
            ok=False, tool=tool, recomputed=True, errors=broken,
            reason=f"objects left in a bad state: {', '.join(broken)}",
        )

    # 2.5. Result verifier (docs/VERIFIER-SPEC.md): measure real dimensions,
    #      solid count, validity, and collision over the same live bridge,
    #      and judge them. A measurement crash/hang/timeout does NOT fail
    #      the render check above (that stays about recompute+render only,
    #      unchanged) - but it does produce an explicit FAIL result_verdict
    #      with the error captured as evidence. It is never silently None
    #      once measurement is actually attempted; None here means only
    #      "never attempted" (an earlier check already returned above).
    measured = await measure_objects(bridge, active_subjects)
    result_verdict = _build_result_verdict(measured, expected_spec=expected_spec)

    # 3. Draw it. Without a GUI there is nothing to draw, and that is not a
    #    failure - but it is recorded, so nobody reads it as a clean render.
    try:
        gui = await bridge.is_gui_available()
    except Exception:  # noqa: BLE001
        gui = False
    if not gui:
        return RenderVerification(
            ok=True, tool=tool, recomputed=True, render_skipped=True,
            result_verdict=result_verdict,
        )

    subject_json = json.dumps(tuple(str(value) for value in active_subjects))
    operation_json = json.dumps(operation_id or tool)
    frame_probe = f'''\
import json as _json_
import os as _os_
from datetime import datetime as _datetime_, timezone as _timezone_
import FreeCAD as _FreeCAD_
import FreeCADGui as _Gui_
from integrations.freecad_native.demo_viewport import DynamicViewportDirector as _Director_
_names_ = set({subject_json})
_objects_ = [
    _object_ for _object_ in (_FreeCAD_.ActiveDocument.Objects if _FreeCAD_.ActiveDocument else [])
    if getattr(_object_, "Shape", None) is not None
    and not _object_.Shape.isNull()
    and (not _names_ or _object_.Name in _names_)
]
if not _objects_ and _FreeCAD_.ActiveDocument:
    _objects_ = [
        _object_ for _object_ in _FreeCAD_.ActiveDocument.Objects
        if getattr(_object_, "Shape", None) is not None and not _object_.Shape.isNull()
    ]
_record_ = {{
    "operation_id": {operation_json},
    "active_subject_ids": [_object_.Name for _object_ in _objects_],
    "timestamp": _datetime_.now(_timezone_.utc).isoformat(),
}}
try:
    if not _objects_:
        _record_.update({{"status": "PASS", "empty_document": True, "correction_attempts": 0}})
    else:
        _director_ = _Director_(_FreeCAD_, _Gui_)
        _quality_ = _director_.frame(
            _objects_, force=True, marker="CAD_OPERATION_VIEWPORT", reset_orientation=False
        )
        _bounds_ = _director_.object_bounds(_objects_)
        _record_.update({{
            "status": "PASS",
            "bounding_box_dimensions": list(_bounds_.size),
            "projected_center_x": 0.5 + _quality_.center_offset_x,
            "projected_center_y": 0.5 + _quality_.center_offset_y,
            "center_offset_percentage": 100.0 * _quality_.center_offset,
            "screen_occupancy_percentage": 100.0 * _quality_.fill,
            "clipping": _quality_.clipped,
            "camera_orientation": str(_Gui_.activeDocument().activeView().getCameraOrientation()),
            "correction_attempts": sum(
                1 for _marker_ in _director_.markers if _marker_.name == "VIEW_CENTER_CORRECTION"
            ),
        }})
except Exception as _error_:
    _record_.update({{"status": "FAIL", "reason": str(_error_)}})
_evidence_ = _os_.environ.get("CADWIZ_VIEWPORT_EVIDENCE", "")
if _evidence_:
    with open(_evidence_, "a", encoding="utf-8") as _stream_:
        _stream_.write(_json_.dumps(_record_, sort_keys=True) + "\\n")
_result_ = _record_
'''
    try:
        frame = await bridge.execute_python(frame_probe)
    except Exception as error:  # noqa: BLE001
        return RenderVerification(
            ok=False, tool=tool, recomputed=True,
            reason=f"viewport check raised: {error}",
            result_verdict=result_verdict,
        )
    viewport_record = getattr(frame, "result", None)
    if not getattr(frame, "success", False) or not isinstance(viewport_record, dict):
        return RenderVerification(
            ok=False, tool=tool, recomputed=True,
            reason="viewport check did not return structured evidence",
            result_verdict=result_verdict,
        )
    if viewport_record.get("status") != "PASS":
        return RenderVerification(
            ok=False, tool=tool, recomputed=True,
            reason=f"viewport quality failed: {viewport_record.get('reason', 'unknown')}",
            viewport_record=viewport_record,
            result_verdict=result_verdict,
        )

    try:
        # Founder-found bug, 2026-09-27 (ORDER-2026-09-27-04, PART B): this
        # call used to pass no view_angle, which the bridge defaults to
        # "Isometric" -- `view.viewIsometric()`, a fixed default distance
        # around the origin. That silently discarded the fit-to-bounding-box
        # framing `_director_.frame()` had just computed a few lines above,
        # so any object not near the origin at that default distance never
        # appeared in the captured image at all (confirmed live: every
        # GP-012 judge screenshot tonight was a plain background gradient,
        # nothing built). FitAll re-fits to whatever is actually in the
        # document right before the pixels are captured, so the same
        # object that just passed the viewport-quality check above is
        # guaranteed to be the object the picture actually shows.
        from .bridge import ensure_vendor_importable  # noqa: PLC0415

        ensure_vendor_importable()
        from freecad_mcp.bridge.base import ViewAngle  # noqa: PLC0415

        shot = await bridge.get_screenshot(
            width=RENDER_WIDTH, height=RENDER_HEIGHT, view_angle=ViewAngle.FIT_ALL
        )
    except Exception as error:  # noqa: BLE001
        return RenderVerification(
            ok=False, tool=tool, recomputed=True,
            reason=f"render raised: {error}",
            result_verdict=result_verdict,
        )

    if not getattr(shot, "success", False):
        return RenderVerification(
            ok=False, tool=tool, recomputed=True,
            reason=f"render failed: {getattr(shot, 'error', 'no detail')}",
            result_verdict=result_verdict,
        )

    return RenderVerification(
        ok=True,
        tool=tool,
        recomputed=True,
        rendered=True,
        result_verdict=result_verdict,
        viewport_valid=True,
        viewport_record=viewport_record,
        image_base64=str(getattr(shot, "data", "") or ""),
        image_format=str(getattr(shot, "format", "png") or "png"),
    )
