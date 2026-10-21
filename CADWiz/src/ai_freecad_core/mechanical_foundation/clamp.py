# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Typed clamp parameters, validation, and feature-program compilation."""

from __future__ import annotations

from dataclasses import dataclass

from ai_freecad_core.production_foundation.contracts import (
    EngineeringIntentSpecLite,
    FeatureOperationIR,
    FeatureProgramIR,
)
from ai_freecad_core.production_foundation.contracts import (
    FeatureOperationType as T,
)

CLAMP_DEFAULTS: dict[str, float] = {
    "desk_thickness_mm": 19.05,
    "desk_clearance_mm": 2.0,
    "clamp_width_mm": 60.0,
    "jaw_depth_mm": 55.0,
    "upper_jaw_thickness_mm": 12.0,
    "lower_jaw_thickness_mm": 14.0,
    "spine_thickness_mm": 14.0,
    "screw_boss_radius_mm": 10.0,
    "screw_boss_extension_mm": 6.0,
    "m8_screw_clearance_mm": 8.6,
    "m8_nut_across_flats_mm": 13.4,
    "m8_nut_pocket_thickness_mm": 6.8,
    "pivot_bolt_nominal_mm": 5.0,
    "pivot_hole_diameter_mm": 5.4,
    "pivot_boss_diameter_mm": 32.0,
    "pivot_boss_thickness_mm": 12.0,
    "clamp_fillet_radius_mm": 2.0,
    "index_face_diameter_mm": 30.0,
    "index_tooth_depth_mm": 1.2,
    "index_target_increment_deg": 5.0,
    "index_qualified_increment_deg": 10.0,
    "arm_length_mm": 150.0,
    "arm_width_mm": 28.0,
    "arm_web_thickness_mm": 4.0,
    "arm_rib_width_mm": 8.0,
    "arm_rib_height_mm": 7.0,
    "desk_reference_depth_mm": 700.0,
    "desk_reference_width_mm": 600.0,
}


@dataclass(frozen=True, slots=True)
class ClampValidation:
    valid: bool
    reasons: tuple[str, ...]
    inside_height_mm: float


def validate_clamp_parameters(parameters: dict[str, float]) -> ClampValidation:
    p = {**CLAMP_DEFAULTS, **parameters}
    reasons = []
    if any(value <= 0 for value in p.values()):
        reasons.append("all clamp dimensions must be positive")
    inside = p["desk_thickness_mm"] + p["desk_clearance_mm"]
    if p["clamp_width_mm"] < 60:
        reasons.append("clamp width must remain at least 60 mm")
    if p["spine_thickness_mm"] < 3 * 0.4:
        reasons.append("spine is below the derived three-line FDM wall minimum")
    if p["m8_nut_across_flats_mm"] + 2.4 > p["screw_boss_radius_mm"] * 2:
        reasons.append("nut pocket leaves insufficient boss wall")
    if p["pivot_hole_diameter_mm"] >= p["pivot_boss_diameter_mm"] - 8:
        reasons.append("pivot bore leaves insufficient radial boss material")
    if p["index_face_diameter_mm"] >= p["pivot_boss_diameter_mm"]:
        reasons.append("indexed face must fit inside pivot boss")
    return ClampValidation(not reasons, tuple(reasons), inside)


def compile_clamp_program(
    spec: EngineeringIntentSpecLite, document_id: str = "freecad:S3PrintedClamp"
) -> FeatureProgramIR:
    p = {**CLAMP_DEFAULTS}
    p.update(
        {
            name: float(value)
            for name, value in spec.mandatory_requirements.items()
            if name in CLAMP_DEFAULTS and isinstance(value, (int, float))
        }
    )
    validation = validate_clamp_parameters(p)
    if not validation.valid:
        raise ValueError("; ".join(validation.reasons))
    p["clamp_inside_height_mm"] = validation.inside_height_mm
    operations: list[FeatureOperationIR] = []

    def add(target: str, kind: T, params: dict[str, object], checkpoint: str) -> None:
        operations.append(
            FeatureOperationIR(
                f"clamp-op-{len(operations) + 1:02d}",
                target,
                kind,
                params,
                {name: "mm" for name, value in params.items() if isinstance(value, float)},
                (),
                ("observed native state matches expected clamp stage",),
                checkpoint,
                ("observation", "validator", "viewport"),
            )
        )

    for name, value in p.items():
        add(
            f"Clamp.Parameters.{name}",
            T.DEFINE_NAMED_PARAMETER,
            {"name": name, "value": value},
            "document",
        )
    add("Clamp.ClampBody", T.CREATE_CLAMP_BASE, dict(p), "parameters")
    add("Clamp.DeskOpeningPocket", T.CUT_DESK_OPENING, dict(p), "clamp-base")
    add("Clamp.ClampScrewBoss", T.ADD_CLAMP_SCREW_BOSS, dict(p), "desk-opening")
    add("Clamp.M8NutCapturePocket", T.CUT_M8_NUT_CAPTURE, dict(p), "screw-boss")
    add("Clamp.M8ScrewPath", T.CUT_M8_SCREW_PATH, dict(p), "nut-capture")
    add("Clamp.Pivot1Boss", T.ADD_PIVOT_1_BOSS, dict(p), "screw-path")
    add("Clamp.Pivot1Bore", T.CUT_PIVOT_1_BORE, dict(p), "pivot-boss")
    add("Clamp.ClampEdgeFillet", T.ADD_CLAMP_FILLET, dict(p), "pivot-bore")
    add("Coupons.IndexFaces", T.ADD_INDEX_FACE_COUPONS, dict(p), "clamp")
    add("Coupons.ArmStructuralProfile", T.ADD_ARM_PROFILE_COUPON, dict(p), "index-coupons")
    add("Document.Observation", T.OBSERVE_DOCUMENT, {"active_subject": "Pivot1Bore"}, "complete")
    return FeatureProgramIR("cadwiz-clamp-ir@1", spec.intent_id, document_id, tuple(operations))
