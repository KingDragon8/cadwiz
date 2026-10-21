# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Pure, host-neutral checks that judge a CAD result correct or not.

Each function takes already-measured primitive values (floats, ints, dicts of
those) - never a FreeCAD shape - and returns an
:class:`~ai_freecad_core.production_foundation.contracts.AssertionResult`.
Host adapters (native FreeCAD, the MCP bridge) are responsible for turning
real geometry into those primitives; this module never imports FreeCAD, so it
is exercised directly in unit tests per docs/VERIFIER-SPEC.md's reachability
and test requirements.
"""

from __future__ import annotations

from typing import Mapping, Sequence

from ai_freecad_core.production_foundation.contracts import AssertionResult

HARD = "HARD"
DERIVED = "DERIVED"


def check_measurement_succeeded(error: str | None) -> AssertionResult:
    """The measurement probe itself must have run cleanly.

    A crash, hang/timeout, or malformed response is a HARD failure with the
    error text as evidence - never a silently-absent verdict. This is the
    gate that makes every other check in this module trustworthy: none of
    them run on data that failed to arrive honestly.
    """
    passed = error is None
    return AssertionResult(
        "measurement_succeeded",
        HARD,
        passed,
        expected=None,
        observed=error,
        detail="" if passed else error or "measurement failed with no detail",
    )


def check_recompute(bad_objects: Sequence[str]) -> AssertionResult:
    """Recompute/error-state check: no object left Invalid, Error, or null."""
    bad = tuple(bad_objects)
    passed = not bad
    return AssertionResult(
        "recompute",
        HARD,
        passed,
        expected=(),
        observed=bad,
        detail="" if passed else f"objects left in a bad state: {', '.join(bad)}",
    )


def check_shape_validity(shapes: Mapping[str, Mapping[str, object]]) -> AssertionResult:
    """Every measured shape must be non-null and OpenCascade-valid."""
    invalid = tuple(name for name, data in shapes.items() if not data.get("valid", False))
    passed = bool(shapes) and not invalid
    return AssertionResult(
        "shape_validity",
        HARD,
        passed,
        expected=(),
        observed=invalid,
        detail=(
            "no measured shapes"
            if not shapes
            else "" if passed else f"invalid or null shape(s): {', '.join(invalid)}"
        ),
    )


def check_solid_count(
    shapes: Mapping[str, Mapping[str, object]], *, minimum: int = 1
) -> AssertionResult:
    """Every measured shape must contain at least `minimum` solid(s)."""
    short = {
        name: int(data.get("solids", 0))
        for name, data in shapes.items()
        if int(data.get("solids", 0)) < minimum
    }
    passed = bool(shapes) and not short
    return AssertionResult(
        "solid_count",
        HARD,
        passed,
        expected=minimum,
        observed=short,
        detail=(
            "no measured shapes"
            if not shapes
            else "" if passed else f"below minimum {minimum} solid(s): {short}"
        ),
    )


def check_dimensions(
    measured_mm: Mapping[str, float],
    expected_mm: Mapping[str, float],
    *,
    tolerance_mm: float,
) -> AssertionResult:
    """Every expected named dimension must be present and within tolerance."""
    mismatches: dict[str, str] = {}
    for name, target in expected_mm.items():
        if name not in measured_mm:
            mismatches[name] = "missing"
            continue
        actual = measured_mm[name]
        delta = abs(actual - target)
        if delta > tolerance_mm:
            mismatches[name] = f"expected {target:g}mm, measured {actual:g}mm (off by {delta:g}mm)"
    passed = not mismatches
    return AssertionResult(
        "dimensions",
        HARD,
        passed,
        expected=dict(expected_mm),
        observed=dict(measured_mm),
        detail="" if passed else "; ".join(f"{name}: {reason}" for name, reason in mismatches.items()),
    )


def check_volume_removed(
    before_mm3: float, after_mm3: float, *, minimum_removed_mm3: float
) -> AssertionResult:
    """A hole, pocket, or bore must measurably remove material -- proves a
    boolean Cut actually ran, not just that a correctly shaped and placed
    cutter exists somewhere in the document. ORDER-2026-09-27-06 founder
    ruling 4: two independent frontier models both created cutter solids
    positioned as holes without ever subtracting them, so a viewer saw
    protruding cylinders rather than an object with real holes through it.

    `before_mm3` is the target's own volume before the cut (or an
    equivalent uncut baseline shape); `after_mm3` is the same object's
    volume once the operation claims to be finished. No shape name is
    referenced -- this applies to any cut/pocket/bore alike.
    """
    removed = before_mm3 - after_mm3
    passed = removed >= minimum_removed_mm3
    return AssertionResult(
        "volume_removed",
        HARD,
        passed,
        expected=minimum_removed_mm3,
        observed=removed,
        detail=(
            ""
            if passed
            else (
                f"only {removed:.3f} mm3 removed, expected at least "
                f"{minimum_removed_mm3:.3f} mm3 -- the cutter may not have "
                "actually been subtracted from the target"
            )
        ),
    )


def check_minimum_wall_thickness(
    measured_min_wall_mm: float, *, minimum_mm: float
) -> AssertionResult:
    """ORDER-2026-09-29-02 Stage 1: a printable piece must have real
    material everywhere, not just a valid-but-paper-thin shell. No shape
    name referenced -- applies to any solid a caller measured the
    thinnest wall of."""
    passed = measured_min_wall_mm >= minimum_mm
    return AssertionResult(
        "minimum_wall_thickness",
        HARD,
        passed,
        expected=minimum_mm,
        observed=measured_min_wall_mm,
        detail=(
            ""
            if passed
            else f"thinnest measured wall {measured_min_wall_mm:g}mm is below the required {minimum_mm:g}mm minimum"
        ),
    )


def check_mating_gap(
    min_gap_mm: float,
    max_gap_mm: float,
    avg_gap_mm: float,
    *,
    target_clearance_mm: float,
    tolerance_mm: float,
) -> AssertionResult:
    """ORDER-2026-09-29-02 Stage 1: the two mating faces of a split part
    must sit apart by roughly the intended print clearance everywhere
    along the seam, not just on average -- a gap that is locally zero
    binds the print even if the mean gap looks right. `min_gap_mm` <= 0
    means the pieces touch or overlap somewhere on the seam."""
    low = target_clearance_mm - tolerance_mm
    high = target_clearance_mm + tolerance_mm
    passed = min_gap_mm > 0 and min_gap_mm + 1e-9 >= low and max_gap_mm <= high + 1e-9
    detail = ""
    if not passed:
        if min_gap_mm <= 0:
            detail = f"minimum gap {min_gap_mm:g}mm -- the mating faces touch or overlap somewhere on the seam"
        else:
            detail = (
                f"gap min={min_gap_mm:g}mm max={max_gap_mm:g}mm avg={avg_gap_mm:g}mm, "
                f"outside the {target_clearance_mm:g}mm +/-{tolerance_mm:g}mm target clearance"
            )
    return AssertionResult(
        "mating_gap",
        HARD,
        passed,
        expected={"target_clearance_mm": target_clearance_mm, "tolerance_mm": tolerance_mm},
        observed={"min_mm": min_gap_mm, "max_mm": max_gap_mm, "avg_mm": avg_gap_mm},
        detail=detail,
    )


def check_volume_reconstruction(
    piece_a_mm3: float,
    piece_b_mm3: float,
    gap_volume_mm3: float,
    whole_mm3: float,
    *,
    tolerance_fraction: float = 0.05,
) -> AssertionResult:
    """ORDER-2026-09-29-02 Stage 1: piece A + piece B + the material the
    print-clearance gap removed should reconstruct the original whole
    body's volume -- a real check that the split was a clean partition
    of the same body, not two independently-built approximations that
    happen to look similar. No shape name referenced."""
    reconstructed = piece_a_mm3 + piece_b_mm3 + gap_volume_mm3
    if whole_mm3 <= 0:
        return AssertionResult(
            "volume_reconstruction", HARD, False,
            expected=whole_mm3, observed=reconstructed,
            detail=f"whole-body volume {whole_mm3:g}mm3 is not a real positive measurement",
        )
    relative_error = abs(reconstructed - whole_mm3) / whole_mm3
    passed = relative_error <= tolerance_fraction
    return AssertionResult(
        "volume_reconstruction",
        HARD,
        passed,
        expected=whole_mm3,
        observed=reconstructed,
        detail=(
            ""
            if passed
            else (
                f"pieces + gap reconstruct to {reconstructed:g}mm3, {relative_error:.1%} off "
                f"the whole body's {whole_mm3:g}mm3 (tolerance {tolerance_fraction:.1%})"
            )
        ),
    )


def check_clearance(clearance_mm: float, minimum_mm: float) -> AssertionResult:
    """Measured clearance must not fall below the required minimum."""
    passed = clearance_mm + 1e-6 >= minimum_mm
    return AssertionResult(
        "clearance",
        DERIVED,
        passed,
        expected=minimum_mm,
        observed=clearance_mm,
        detail="" if passed else f"clearance {clearance_mm:g}mm below required {minimum_mm:g}mm",
    )


def check_collision(
    overlap_volume_mm3: float, *, threshold_mm3: float = 1e-6,
    tiers: Mapping[str, str] | None = None,
) -> AssertionResult:
    """Measured pairwise overlap volume must be at or below the threshold.

    `tiers` (VERIFY-FAST, 2026-09-09) names which check answered each pair
    -- `bbox_no_overlap`, `mesh_no_overlap`, `exact`, or
    `inconclusive_budget_exceeded` -- from `verification.py`'s own tiered
    `_measure_probe`. Reported in `detail` always, pass or fail: a tier
    summary is evidence about HOW this result was reached, not just what
    it was, and an inconclusive pair contributing nothing to
    `overlap_volume_mm3` must never look identical to a pair that was
    genuinely, exactly checked and found clear.
    """
    passed = overlap_volume_mm3 <= threshold_mm3
    detail_parts = []
    if not passed:
        detail_parts.append(f"overlap volume {overlap_volume_mm3:g}mm3 exceeds {threshold_mm3:g}mm3")
    if tiers:
        counts: dict[str, int] = {}
        for tier in tiers.values():
            counts[tier] = counts.get(tier, 0) + 1
        tier_summary = ", ".join(f"{count} via {tier}" for tier, count in sorted(counts.items()))
        detail_parts.append(f"{len(tiers)} pair(s) checked: {tier_summary}")
        inconclusive = counts.get("inconclusive_budget_exceeded", 0)
        if inconclusive:
            detail_parts.append(
                f"{inconclusive} pair(s) exceeded the exact-check time budget and could not be "
                "confirmed either way -- not counted as a collision, but not confirmed clear"
            )
    return AssertionResult(
        "collision",
        HARD,
        passed,
        expected=threshold_mm3,
        observed=overlap_volume_mm3,
        detail="; ".join(detail_parts),
    )


def check_required_features(
    present: Sequence[str], required: Sequence[str]
) -> AssertionResult:
    """Every feature named in `required` must appear in `present`."""
    present_set = set(present)
    missing = tuple(name for name in required if name not in present_set)
    passed = not missing
    return AssertionResult(
        "required_features",
        HARD,
        passed,
        expected=tuple(required),
        observed=tuple(present),
        detail="" if passed else f"missing required feature(s): {', '.join(missing)}",
    )


def check_target_match(
    produced: Mapping[str, object],
    expected: Mapping[str, object],
    *,
    tolerance_mm: float,
) -> AssertionResult:
    """Does a produced result match an expected target spec, within tolerance?

    `expected` may carry `dimensions_mm` (Mapping[str, float]),
    `required_features` (Sequence[str]), and `max_overlap_mm3` (float,
    default 0.0 meaning no collision). `produced` carries the matching
    measured values under the same keys. This is the check a nightly trial
    uses to grade an attempt against a FreeCAD example-catalog target.
    """
    sub_results: list[AssertionResult] = []

    expected_dims = dict(expected.get("dimensions_mm") or {})
    if expected_dims:
        sub_results.append(
            check_dimensions(
                dict(produced.get("dimensions_mm") or {}),
                expected_dims,
                tolerance_mm=tolerance_mm,
            )
        )

    required_features = tuple(expected.get("required_features") or ())
    if required_features:
        sub_results.append(
            check_required_features(
                tuple(produced.get("features") or ()), required_features
            )
        )

    max_overlap = float(expected.get("max_overlap_mm3", 0.0))
    overlap = float(produced.get("overlap_mm3", 0.0))
    sub_results.append(check_collision(overlap, threshold_mm3=max(max_overlap, 1e-6)))

    passed = all(result.passed for result in sub_results)
    failed_detail = "; ".join(
        f"{result.assertion_id}: {result.detail}" for result in sub_results if not result.passed
    )
    return AssertionResult(
        "target_match",
        HARD,
        passed,
        expected=dict(expected),
        observed={
            "sub_checks": {result.assertion_id: result.passed for result in sub_results},
            **{key: value for key, value in produced.items()},
        },
        detail="" if passed else failed_detail,
    )
