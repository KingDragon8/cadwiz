# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Governed S3 articulated-arm parameters, validation, kinematics, and typed IR."""

from __future__ import annotations

from dataclasses import dataclass, replace
from math import cos, radians, sin
from typing import Mapping

from ai_freecad_core.production_foundation.contracts import (
    EngineeringIntentSpecLite,
    FeatureOperationIR,
    FeatureProgramIR,
)
from ai_freecad_core.production_foundation.contracts import (
    FeatureOperationType as T,
)

from .clamp import CLAMP_DEFAULTS, compile_clamp_program

ASSEMBLY_BACKEND = "FREECAD_ASSEMBLY_OBJECT_WITH_CADWIZ_KINEMATIC_GRAPH"
USER_DIRECTION = (1.0, 0.0, 0.0)
DESK_FRONT_DIRECTION = (1.0, 0.0, 0.0)
PHONE_SCREEN_NORMAL = (1.0, 0.0, 0.0)
CHARGER_ACTIVE_FACE_NORMAL = (-1.0, 0.0, 0.0)
PIVOT_AXIS = (0.0, 1.0, 0.0)
ASSEMBLY_DEFAULTS: dict[str, float] = {
    "arm_a_length_mm": 150.0,
    "arm_b_length_mm": 150.0,
    "arm_width_mm": 28.0,
    "arm_web_thickness_mm": 4.0,
    "arm_rib_width_mm": 8.0,
    "arm_rib_height_mm": 7.0,
    "arm_boss_diameter_mm": 32.0,
    "arm_boss_thickness_mm": 12.0,
    "arm_root_transition_mm": 16.0,
    "pivot_hole_diameter_mm": 5.4,
    "index_face_diameter_mm": 30.0,
    "index_tooth_depth_mm": 1.2,
    "index_increment_deg": 10.0,
    "index_disengagement_mm": 0.2,
    "brand_text_height_mm": 5.0,
    "brand_emboss_depth_mm": 0.8,
    "brand_edge_margin_mm": 2.0,
    "phone_envelope_width_mm": 80.0,
    "phone_envelope_height_mm": 155.0,
    "phone_envelope_thickness_mm": 11.0,
    "phone_case_clearance_mm": 1.5,
    "magnetic_mount_width_mm": 86.0,
    "magnetic_mount_height_mm": 168.0,
    "magnetic_mount_backplate_thickness_mm": 12.0,
    "charger_diameter_mm": 59.9,
    "charger_thickness_mm": 10.4,
    "charger_clearance_radial_mm": 0.6,
    "charger_clearance_depth_mm": 0.6,
    "charger_face_offset_mm": 0.0,
    "cable_diameter_mm": 4.0,
    "cable_exit_width_mm": 8.0,
    "cable_exit_depth_mm": 12.0,
    "cable_route_offset_mm": 7.0,
    "pivot3_phone_plane_clearance_mm": 1.5,
    "pivot3_axis_rearset_mm": 18.0,
    "pivot_1_angle_deg": 40.0,
    "pivot_2_angle_deg": -20.0,
    "pivot_3_angle_deg": -20.0,
}

JOINT_LIMITS: dict[str, tuple[float, float]] = {
    "PIVOT_1_CLAMP_TO_ARM_A": (0.0, 90.0),
    "PIVOT_2_ARM_A_TO_ARM_B": (-170.0, 90.0),
    "PIVOT_3_ARM_B_TO_PHONE_MOUNT": (-90.0, 90.0),
}

QUALIFICATION_POSES: dict[str, dict[str, float]] = {
    "FOLDED_STOWED": {
        "pivot_1_angle_deg": 80.0,
        "pivot_2_angle_deg": -160.0,
        "pivot_3_angle_deg": 80.0,
    },
    "LOW_EXTENSION": {
        "pivot_1_angle_deg": 10.0,
        "pivot_2_angle_deg": 0.0,
        "pivot_3_angle_deg": -10.0,
    },
    "WORKING": {
        "pivot_1_angle_deg": 40.0,
        "pivot_2_angle_deg": -20.0,
        "pivot_3_angle_deg": -20.0,
    },
    "HIGH_RAISED": {
        "pivot_1_angle_deg": 70.0,
        "pivot_2_angle_deg": -20.0,
        "pivot_3_angle_deg": -50.0,
    },
    "TOWARD_USER": {
        "pivot_1_angle_deg": 20.0,
        "pivot_2_angle_deg": 0.0,
        "pivot_3_angle_deg": -20.0,
    },
}


@dataclass(frozen=True, slots=True)
class AssemblyValidation:
    valid: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PlanarTransform:
    x_mm: float
    y_mm: float
    z_mm: float
    hinge_angle_deg: float

    @property
    def yaw_deg(self) -> float:
        """Compatibility projection for older evidence readers.

        The governed angle is now rotation in the world X-Z plane about the
        horizontal Y hinge axis; it is not a top-down yaw.
        """

        return self.hinge_angle_deg


@dataclass(frozen=True, slots=True)
class AssemblyPose:
    pivot_centers: Mapping[str, tuple[float, float, float]]
    component_transforms: Mapping[str, PlanarTransform]


def validate_assembly_parameters(parameters: Mapping[str, float]) -> AssemblyValidation:
    p = {**CLAMP_DEFAULTS, **ASSEMBLY_DEFAULTS, **parameters}
    reasons: list[str] = []
    positive = (
        "arm_a_length_mm",
        "arm_b_length_mm",
        "arm_width_mm",
        "arm_web_thickness_mm",
        "arm_rib_width_mm",
        "arm_rib_height_mm",
        "arm_boss_diameter_mm",
        "arm_boss_thickness_mm",
        "pivot_hole_diameter_mm",
        "index_face_diameter_mm",
        "index_tooth_depth_mm",
        "brand_text_height_mm",
        "brand_emboss_depth_mm",
        "phone_envelope_width_mm",
        "phone_envelope_height_mm",
        "phone_envelope_thickness_mm",
        "magnetic_mount_width_mm",
        "magnetic_mount_height_mm",
        "magnetic_mount_backplate_thickness_mm",
        "charger_diameter_mm",
        "charger_thickness_mm",
        "cable_diameter_mm",
        "cable_exit_width_mm",
        "cable_exit_depth_mm",
        "pivot3_phone_plane_clearance_mm",
        "pivot3_axis_rearset_mm",
    )
    if any(float(p[name]) <= 0 for name in positive):
        reasons.append("all manufacturing dimensions must be positive")
    boss = float(p["arm_boss_diameter_mm"])
    minimum_length = boss + 50.0
    if min(float(p["arm_a_length_mm"]), float(p["arm_b_length_mm"])) < minimum_length:
        reasons.append(f"arm center distance must remain at least {minimum_length:g} mm")
    if float(p["arm_rib_width_mm"]) + 2 * float(p["brand_text_height_mm"]) + 2 > float(
        p["arm_width_mm"]
    ):
        reasons.append("arm width cannot preserve separate rib and branding lanes")
    if float(p["arm_web_thickness_mm"]) < 1.6:
        reasons.append("arm web is below the four-line 0.4 mm nozzle baseline")
    if float(p["pivot_hole_diameter_mm"]) >= boss - 8:
        reasons.append("pivot bore leaves insufficient radial boss material")
    if float(p["index_face_diameter_mm"]) >= boss:
        reasons.append("indexed face must fit inside the pivot boss")
    recess_depth = float(p["charger_thickness_mm"]) + float(p["charger_clearance_depth_mm"])
    if recess_depth >= float(p["magnetic_mount_backplate_thickness_mm"]):
        reasons.append("charger recess must retain a rear support wall")
    if float(p["cable_exit_width_mm"]) < float(p["cable_diameter_mm"]) + 1.0:
        reasons.append("cable exit must provide at least 1 mm diametral clearance")
    required_rearset = (
        float(p["arm_boss_diameter_mm"]) / 2.0
        + float(p["pivot3_phone_plane_clearance_mm"])
    )
    if float(p["pivot3_axis_rearset_mm"]) < required_rearset:
        reasons.append(
            "Pivot 3 axis rearset must keep its boss behind PHONE_CONTACT_PLANE"
        )
    increment = float(p["index_increment_deg"])
    if increment <= 0 or abs(360 / increment - round(360 / increment)) > 1e-9:
        reasons.append("indexed increment must divide 360 degrees exactly")
    for name, semantic in (
        ("pivot_1_angle_deg", "PIVOT_1_CLAMP_TO_ARM_A"),
        ("pivot_2_angle_deg", "PIVOT_2_ARM_A_TO_ARM_B"),
        ("pivot_3_angle_deg", "PIVOT_3_ARM_B_TO_PHONE_MOUNT"),
    ):
        value = float(p[name])
        minimum, maximum = JOINT_LIMITS[semantic]
        if not minimum <= value <= maximum:
            reasons.append(f"{semantic} angle must remain within {minimum:g}..{maximum:g} degrees")
        if abs(value / increment - round(value / increment)) > 1e-9:
            reasons.append(f"{semantic} angle must align to the {increment:g}-degree index")
    cumulative = sum(float(p[name]) for name in (
        "pivot_1_angle_deg",
        "pivot_2_angle_deg",
        "pivot_3_angle_deg",
    ))
    if abs(cumulative) > 1e-9:
        reasons.append("phone mount must remain upright with its screen normal toward the user")
    return AssemblyValidation(not reasons, tuple(reasons))


def solve_planar_pose(parameters: Mapping[str, float]) -> AssemblyPose:
    p = {**CLAMP_DEFAULTS, **ASSEMBLY_DEFAULTS, **parameters}
    validation = validate_assembly_parameters(p)
    if not validation.valid:
        raise ValueError("; ".join(validation.reasons))
    outer_height = (
        float(p["lower_jaw_thickness_mm"])
        + float(p["desk_thickness_mm"])
        + float(p["desk_clearance_mm"])
        + float(p["upper_jaw_thickness_mm"])
    )
    pivot_radius = float(p["pivot_boss_diameter_mm"]) / 2.0
    pivot_center_x = float(p["spine_thickness_mm"]) + pivot_radius * 0.55
    # Keep the integrated boss compact while clearing the nominal desktop by
    # 2 mm at every hinge angle (16 mm radius over the 35.05 mm desk top).
    pivot_center_z = outer_height + 6.0
    arm_a_y = -(
        float(p["clamp_width_mm"])
        - 4.0
        + float(p["pivot_boss_thickness_mm"])
        + float(p["index_tooth_depth_mm"])
    )
    mating_step = (
        float(p["arm_boss_thickness_mm"])
        + float(p["index_tooth_depth_mm"])
        + float(p["index_disengagement_mm"])
    )
    arm_b_y = arm_a_y + mating_step
    mount_y = (
        arm_b_y
        + float(p["arm_boss_thickness_mm"]) / 2.0
        + float(p["index_tooth_depth_mm"])
    )
    p1 = (pivot_center_x, pivot_center_z)
    a1 = float(p["pivot_1_angle_deg"])
    a12 = a1 + float(p["pivot_2_angle_deg"])
    a123 = a12 + float(p["pivot_3_angle_deg"])

    def end(start: tuple[float, float], length: float, angle: float) -> tuple[float, float]:
        theta = radians(angle)
        return start[0] + length * cos(theta), start[1] + length * sin(theta)

    p2 = end(p1, float(p["arm_a_length_mm"]), a1)
    p3 = end(p2, float(p["arm_b_length_mm"]), a12)
    contact_plane_x = p3[0] + float(p["pivot3_axis_rearset_mm"])
    return AssemblyPose(
        {
            "PIVOT_1_CLAMP_TO_ARM_A": (p1[0], arm_a_y, p1[1]),
            "PIVOT_2_ARM_A_TO_ARM_B": (p2[0], arm_b_y, p2[1]),
            "PIVOT_3_ARM_B_TO_PHONE_MOUNT": (p3[0], arm_b_y, p3[1]),
        },
        {
            "S3_CLAMP": PlanarTransform(0.0, 0.0, 0.0, 0.0),
            "S3_ARM_A": PlanarTransform(p1[0], arm_a_y, p1[1], a1),
            "S3_ARM_B": PlanarTransform(p2[0], arm_b_y, p2[1], a12),
            "S3_PHONE_MOUNT_INTERFACE": PlanarTransform(
                contact_plane_x, mount_y, p3[1], a123
            ),
        },
    )


def compile_articulated_program(
    spec: EngineeringIntentSpecLite, document_id: str = "freecad:S3ArticulatedAssembly"
) -> FeatureProgramIR:
    p = {**CLAMP_DEFAULTS, **ASSEMBLY_DEFAULTS}
    p.update(
        {
            name: float(value)
            for name, value in spec.mandatory_requirements.items()
            if name in p and isinstance(value, (int, float)) and not isinstance(value, bool)
        }
    )
    validation = validate_assembly_parameters(p)
    if not validation.valid:
        raise ValueError("; ".join(validation.reasons))
    lower_request = spec.user_goal.casefold()
    pose_only = any(
        phrase in lower_request
        for phrase in (
            "position a",
            "position b",
            "position c",
            "position d",
            "position e",
            "fold the phone holder",
            "raise the phone mount",
            "pull the phone toward the user",
            "pivot 1 angle",
            "pivot 2 angle",
            "pivot 3 angle",
            "center pivot",
        )
    )
    if pose_only:
        operations: list[FeatureOperationIR] = []
        for name in ("pivot_1_angle_deg", "pivot_2_angle_deg", "pivot_3_angle_deg"):
            operations.append(
                FeatureOperationIR(
                    f"assembly-pose-op-{len(operations) + 1:02d}",
                    f"Assembly.Parameters.{name}",
                    T.DEFINE_NAMED_PARAMETER,
                    {
                        "name": name,
                        "value": p[name],
                        "defer_assembly_regeneration": True,
                    },
                    {},
                    (),
                    ("coupled indexed pose parameters commit atomically",),
                    "existing-assembly",
                    ("observation", "validator", "viewport"),
                )
            )
        operations.append(
            FeatureOperationIR(
                f"assembly-pose-op-{len(operations) + 1:02d}",
                "Assembly.Pose",
                T.SET_S3_ASSEMBLY_POSE,
                dict(p),
                {name: "mm" for name in p if name.endswith("_mm")},
                (),
                ("existing assembly reaches the requested indexed pose",),
                "coupled-parameters",
                ("observation", "validator", "viewport"),
            )
        )
        operations.append(
            FeatureOperationIR(
                f"assembly-pose-op-{len(operations) + 1:02d}",
                "Assembly.Observation",
                T.OBSERVE_DOCUMENT,
                {"active_subject": "S3Assembly"},
                {},
                (),
                ("observed assembly pose matches the request",),
                "pose",
                ("observation", "validator", "viewport"),
            )
        )
        return FeatureProgramIR(
            "cadwiz-s3-approved-concept-pose-ir@1",
            spec.intent_id,
            document_id,
            tuple(operations),
        )
    clamp_spec = replace(
        spec,
        artifact_name="S3 PRINTED DESK CLAMP",
        mandatory_requirements={name: p[name] for name in CLAMP_DEFAULTS},
    )
    clamp = compile_clamp_program(clamp_spec, document_id)
    operations = [
        item
        for item in clamp.operations
        if item.operation_type
        not in {T.ADD_INDEX_FACE_COUPONS, T.ADD_ARM_PROFILE_COUPON, T.OBSERVE_DOCUMENT}
    ]

    def add(target: str, kind: T, values: Mapping[str, object], checkpoint: str) -> None:
        operations.append(
            FeatureOperationIR(
                f"assembly-op-{len(operations) + 1:02d}",
                target,
                kind,
                dict(values),
                {name: "mm" for name in values if name.endswith("_mm")},
                (),
                ("actual assembly geometry and semantic relation match the request",),
                checkpoint,
                ("observation", "validator", "viewport"),
            )
        )

    for name in ASSEMBLY_DEFAULTS:
        if name in CLAMP_DEFAULTS:
            continue
        add(
            f"Assembly.Parameters.{name}",
            T.DEFINE_NAMED_PARAMETER,
            {
                "name": name,
                "value": p[name],
                # Coupled arm/joint edits are one typed feature program.  Do
                # not validate transient, half-populated poses between the
                # parameter operations; SET_S3_ASSEMBLY_POSE is the commit.
                "defer_assembly_regeneration": True,
            },
            "clamp",
        )
    add("Assembly.PrintableArms", T.CREATE_PRINTABLE_ARMS, p, "assembly-parameters")
    add(
        "Assembly.PhoneMountInterface",
        T.CREATE_PHONE_MOUNT_INTERFACE,
        p,
        "printable-arms",
    )
    add("Assembly.Backend", T.CREATE_S3_ASSEMBLY_BACKEND, p, "phone-interface")
    add("Assembly.Pose", T.SET_S3_ASSEMBLY_POSE, p, "assembly-backend")
    add("Assembly.Observation", T.OBSERVE_DOCUMENT, {"active_subject": "S3Assembly"}, "pose")
    return FeatureProgramIR(
        "cadwiz-s3-approved-concept-ir@2", spec.intent_id, document_id, tuple(operations)
    )
