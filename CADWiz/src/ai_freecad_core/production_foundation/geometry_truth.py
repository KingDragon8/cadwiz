# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Deterministic geometry, identity, functional-intent, and visual acceptance gates.

The types in this module deliberately do not import FreeCAD.  Native adapters turn
host shapes into :class:`ShapeObservation` records, while unit tests and other CAD
backends can exercise the same acceptance rules without a GUI or OCC runtime.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping


class EffectKind(str, Enum):
    ADDITIVE = "ADDITIVE"
    SUBTRACTIVE = "SUBTRACTIVE"
    TRANSFORM = "TRANSFORM"


FAIL_GEOMETRY_OPERATION_NO_EFFECT = "FAIL_GEOMETRY_OPERATION_NO_EFFECT"
FAIL_EFFECT_MISMATCH = "FAIL_EFFECT_MISMATCH"
FAIL_FUNCTIONAL_INTENT = "FAIL_FUNCTIONAL_INTENT"
FAIL_PARENT_GEOMETRY_IDENTITY = "FAIL_PARENT_GEOMETRY_IDENTITY"
FAIL_PHONE_CONTACT_PLANE_INTERFERENCE = "FAIL_PHONE_CONTACT_PLANE_INTERFERENCE"


@dataclass(frozen=True, slots=True)
class ShapeObservation:
    fingerprint: str
    volume_mm3: float
    area_mm2: float
    solid_count: int
    face_count: int
    edge_count: int
    valid: bool = True


@dataclass(frozen=True, slots=True)
class GeometryEffectResult:
    passed: bool
    code: str
    requested_effect: EffectKind
    actual_effect: str
    volume_delta_mm3: float
    fingerprint_changed: bool
    topology_changed: bool


def verify_geometry_effect(
    before: ShapeObservation,
    after: ShapeObservation,
    requested_effect: EffectKind,
    *,
    volume_tolerance_mm3: float = 1e-6,
) -> GeometryEffectResult:
    """Prove the material consequence of a meaningful feature operation."""

    delta = after.volume_mm3 - before.volume_mm3
    fingerprint_changed = before.fingerprint != after.fingerprint
    topology_changed = (before.face_count, before.edge_count) != (
        after.face_count,
        after.edge_count,
    )
    if not after.valid or after.solid_count < 1:
        return GeometryEffectResult(
            False,
            FAIL_EFFECT_MISMATCH,
            requested_effect,
            "invalid or empty result",
            delta,
            fingerprint_changed,
            topology_changed,
        )
    if abs(delta) <= volume_tolerance_mm3:
        return GeometryEffectResult(
            False,
            FAIL_GEOMETRY_OPERATION_NO_EFFECT,
            requested_effect,
            "no meaningful material change",
            delta,
            fingerprint_changed,
            topology_changed,
        )
    expected_sign = 1 if requested_effect is EffectKind.ADDITIVE else -1
    if requested_effect is not EffectKind.TRANSFORM and delta * expected_sign <= 0:
        return GeometryEffectResult(
            False,
            FAIL_EFFECT_MISMATCH,
            requested_effect,
            "material changed in the opposite direction",
            delta,
            fingerprint_changed,
            topology_changed,
        )
    return GeometryEffectResult(
        True,
        "PASS",
        requested_effect,
        "material added" if delta > 0 else "material removed",
        delta,
        fingerprint_changed,
        topology_changed,
    )


@dataclass(frozen=True, slots=True)
class InvariantResult:
    passed: bool
    code: str
    object_class: str
    checks: Mapping[str, bool]
    measurements: Mapping[str, float | str | bool] = field(default_factory=dict)


def _invariants(
    object_class: str,
    checks: Mapping[str, bool],
    measurements: Mapping[str, float | str | bool],
) -> InvariantResult:
    passed = bool(checks) and all(checks.values())
    return InvariantResult(
        passed,
        "PASS" if passed else FAIL_FUNCTIONAL_INTENT,
        object_class,
        dict(checks),
        dict(measurements),
    )


def verify_c_clamp_invariants(
    *,
    single_body_solid: bool,
    open_front: bool,
    upper_jaw: bool,
    lower_jaw: bool,
    rear_spine: bool,
    desk_opening_mm: float,
    required_desk_opening_mm: float,
    front_accessible: bool,
    screw_axis_intersects_lower_jaw: bool,
    pivot_1_support: bool,
) -> InvariantResult:
    return _invariants(
        "C_CLAMP",
        {
            "single_body_solid": single_body_solid,
            "open_front": open_front,
            "upper_jaw": upper_jaw,
            "lower_jaw": lower_jaw,
            "rear_spine": rear_spine,
            "desk_opening_measured": desk_opening_mm >= required_desk_opening_mm,
            "front_accessible": front_accessible,
            "screw_axis_intersects_lower_jaw": screw_axis_intersects_lower_jaw,
            "pivot_1_support": pivot_1_support,
        },
        {
            "desk_opening_mm": desk_opening_mm,
            "required_desk_opening_mm": required_desk_opening_mm,
            "C_CLAMP_FRONT_ACCESSIBLE": front_accessible,
        },
    )


def verify_hollow_shell_invariants(
    *, exterior: bool, interior_void: bool, wall_mm: float
) -> InvariantResult:
    return _invariants(
        "HOLLOW_SHELL",
        {"exterior": exterior, "interior_void": interior_void, "wall_measured": wall_mm > 0},
        {"wall_mm": wall_mm},
    )


def verify_arm_invariants(
    *, pivot_interfaces: int, planar_bed_face: bool, reinforcing_rib: bool
) -> InvariantResult:
    return _invariants(
        "ARM",
        {
            "two_pivot_interfaces": pivot_interfaces == 2,
            "planar_bed_face": planar_bed_face,
            "reinforcing_rib": reinforcing_rib,
        },
        {"pivot_interfaces": pivot_interfaces},
    )


def verify_phone_cradle_invariants(
    *,
    phone_fits: bool,
    upright_orientation: bool,
    insertion_path: bool,
    bottom_retention: bool,
    side_retention: bool,
    charger_recess: bool,
    charger_fits: bool,
    active_face_offset_mm: float,
    active_face_tolerance_mm: float,
    cable_exit: bool,
    pivot_3_clear: bool,
) -> InvariantResult:
    return _invariants(
        "PHONE_CRADLE",
        {
            "phone_envelope_fits": phone_fits,
            "PHONE_CRADLE_ORIENTATION_MATCH": upright_orientation,
            "insertion_path": insertion_path,
            "bottom_retention": bottom_retention,
            "side_retention": side_retention,
            "charger_recess": charger_recess,
            "charger_envelope_fits": charger_fits,
            "active_face_flush": abs(active_face_offset_mm) <= active_face_tolerance_mm,
            "cable_exit": cable_exit,
            "pivot_3_clear": pivot_3_clear,
        },
        {
            "active_face_offset_mm": active_face_offset_mm,
            "active_face_tolerance_mm": active_face_tolerance_mm,
        },
    )


def verify_phone_magnetic_mount_invariants(
    *,
    single_body_solid: bool,
    upright_orientation: bool,
    magnetic_only_retention: bool,
    side_supports_absent: bool,
    bottom_support_absent: bool,
    charger_recess: bool,
    charger_fits: bool,
    active_face_offset_mm: float,
    active_face_tolerance_mm: float,
    cable_exit: bool,
    cable_route: bool,
    pivot_3_clear: bool,
    phone_screen_faces_user: bool,
    charger_normal_opposes_screen: bool,
) -> InvariantResult:
    """Verify the founder-approved clean magnetic carrier architecture."""

    return _invariants(
        "PHONE_MAGNETIC_MOUNT",
        {
            "single_body_solid": single_body_solid,
            "upright_orientation": upright_orientation,
            "magnetic_only_retention": magnetic_only_retention,
            "side_supports_absent": side_supports_absent,
            "bottom_support_absent": bottom_support_absent,
            "charger_recess": charger_recess,
            "charger_envelope_fits": charger_fits,
            "active_face_flush": abs(active_face_offset_mm) <= active_face_tolerance_mm,
            "cable_exit": cable_exit,
            "cable_route": cable_route,
            "pivot_3_clear": pivot_3_clear,
            "phone_screen_faces_user": phone_screen_faces_user,
            "charger_normal_opposes_screen": charger_normal_opposes_screen,
        },
        {
            "active_face_offset_mm": active_face_offset_mm,
            "active_face_tolerance_mm": active_face_tolerance_mm,
        },
    )


def verify_pivot3_phone_plane_clearance_invariants(
    *,
    signed_distances_mm: Mapping[str, float],
    required_rear_clearance_mm: float,
    phone_intersection_volumes_mm3: Mapping[str, float],
    charger_active_face_offset_mm: float,
    charger_active_face_tolerance_mm: float,
    phone_screen_faces_user: bool,
    volume_tolerance_mm3: float = 1e-6,
) -> InvariantResult:
    """Fail closed when any Pivot 3 envelope approaches the phone contact plane.

    The plane normal points toward the phone/user. Therefore every governed
    envelope must have a maximum signed distance no greater than the negative
    required clearance. Inputs are measured by the native adapter from actual
    placed shape envelopes; this policy layer remains host independent.
    """

    limit = -float(required_rear_clearance_mm)
    rear_checks = {
        f"{name}_behind_phone_contact_plane": float(distance) <= limit + 1e-6
        for name, distance in signed_distances_mm.items()
    }
    intersection_checks = {
        f"{name}_clear_of_phone": float(volume) <= volume_tolerance_mm3
        for name, volume in phone_intersection_volumes_mm3.items()
    }
    checks = {
        **rear_checks,
        **intersection_checks,
        "charger_active_face_flush": abs(float(charger_active_face_offset_mm))
        <= float(charger_active_face_tolerance_mm),
        "phone_screen_faces_user": bool(phone_screen_faces_user),
    }
    passed = bool(checks) and all(checks.values())
    minimum_clearance = min(
        (-float(distance) for distance in signed_distances_mm.values()),
        default=float("-inf"),
    )
    return InvariantResult(
        passed=passed,
        code="PASS" if passed else FAIL_PHONE_CONTACT_PLANE_INTERFERENCE,
        object_class="PIVOT3_PHONE_CONTACT_PLANE",
        checks=checks,
        measurements={
            "required_rear_clearance_mm": float(required_rear_clearance_mm),
            "measured_minimum_clearance_mm": minimum_clearance,
            "charger_active_face_offset_mm": float(charger_active_face_offset_mm),
            **{f"{name}_signed_distance_mm": float(value) for name, value in signed_distances_mm.items()},
            **{
                f"{name}_phone_intersection_mm3": float(value)
                for name, value in phone_intersection_volumes_mm3.items()
            },
        },
    )


@dataclass(frozen=True, slots=True)
class QualifiedArtifactPassport:
    schema: str
    artifact_path: str
    object_name: str
    shape_fingerprint: str
    volume_mm3: float
    solid_count: int
    critical_invariants: Mapping[str, bool]
    dimensions_mm: Mapping[str, float]
    governed_derivation: str | None = None


@dataclass(frozen=True, slots=True)
class ArtifactIdentityResult:
    passed: bool
    code: str
    expected_fingerprint: str
    actual_fingerprint: str


def verify_artifact_identity(
    passport: QualifiedArtifactPassport,
    assembly_fingerprint: str,
    *,
    governed_derivation: str | None = None,
) -> ArtifactIdentityResult:
    matched = passport.shape_fingerprint == assembly_fingerprint
    derived = bool(governed_derivation and governed_derivation == passport.governed_derivation)
    passed = matched or derived
    return ArtifactIdentityResult(
        passed,
        "PASS" if passed else FAIL_PARENT_GEOMETRY_IDENTITY,
        passport.shape_fingerprint,
        assembly_fingerprint,
    )


@dataclass(frozen=True, slots=True)
class EngineeringVisualResult:
    passed: bool
    code: str
    answers: Mapping[str, bool]


def verify_engineering_visual_intent(answers: Mapping[str, bool]) -> EngineeringVisualResult:
    required = (
        "clamp_identifiable",
        "desk_attachment_visible",
        "arm_a_from_clamp_visible",
        "phone_orientation_matches_sketch",
        "charger_visible",
        "coherent_product",
    )
    normalized = {name: bool(answers.get(name, False)) for name in required}
    passed = all(normalized.values())
    return EngineeringVisualResult(
        passed,
        "PASS" if passed else FAIL_FUNCTIONAL_INTENT,
        normalized,
    )
