# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Deterministic ordinary-request routing for the typed feature slice."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from enum import Enum
from typing import Mapping, Protocol

from .contracts import (
    EngineeringIntentSpecLite,
    FeatureOperationType,
    FeatureProgramIR,
    IntentGateOutcome,
    Unknown,
    UnknownClass,
)
from .intent_gate import evaluate_intent
from .ir import compile_coupon_program


class ProductionRoute(str, Enum):
    BOX_PRIMITIVE = "BOX_PRIMITIVE"
    TYPED_FEATURE_IR = "TYPED_FEATURE_IR"
    NO_GEOMETRY = "NO_GEOMETRY"


@dataclass(frozen=True, slots=True)
class RouteDecision:
    request_id: str
    intent_id: str
    selected_production_route: ProductionRoute
    required_capabilities: tuple[str, ...]
    accepted_capabilities: tuple[str, ...]
    missing_capabilities: tuple[str, ...]
    gate_result: IntentGateOutcome
    execution_outcome: str


@dataclass(frozen=True, slots=True)
class OrdinaryFeatureRequestResult:
    raw_request: str
    decision: RouteDecision
    intent: EngineeringIntentSpecLite
    program: FeatureProgramIR | None
    execution: object | None
    user_message: str


class FeatureProgramBuilder(Protocol):
    def execute(self, program: FeatureProgramIR) -> object: ...


class FeatureRequestRouter:
    def __init__(self, available_capabilities: set[str] | None = None):
        self.available = available_capabilities or {item.value for item in FeatureOperationType}

    def route(
        self, request_id: str, text: str, project_state: Mapping[str, float] | None = None
    ) -> tuple[EngineeringIntentSpecLite, ProductionRoute]:
        lower = text.casefold()
        state = dict(project_state or {})
        is_assembly = (
            any(
                phrase in lower
                for phrase in (
                    "two arms",
                    "phone-holder assembly",
                    "phone holder assembly",
                    "cadwiz name",
                    "printer-bed side",
                    "printer bed side",
                    "center pivot",
                    "fold the phone holder",
                    "raise the phone mount",
                    "arm a",
                    "arm b",
                    "first arm",
                    "second arm",
                    "approved phone holder",
                    "magnetic charger",
                    "magnetic-only",
                    "back edge of the desk",
                    "horizontal hinge",
                )
            )
            or "arm_a_length_mm" in state
        )
        is_clamp = (
            is_assembly
            or "clamp" in lower
            or "three-quarter-inch desk" in lower
            or "clamp_width_mm" in state
        )
        defaults: dict[str, float] = {}
        if is_assembly:
            from ai_freecad_core.mechanical_foundation.articulated import ASSEMBLY_DEFAULTS
            from ai_freecad_core.mechanical_foundation.clamp import CLAMP_DEFAULTS

            defaults = {**CLAMP_DEFAULTS, **ASSEMBLY_DEFAULTS}
        elif is_clamp:
            from ai_freecad_core.mechanical_foundation.clamp import CLAMP_DEFAULTS

            defaults = dict(CLAMP_DEFAULTS)
        if "variable-section" in lower or "b-spline loft" in lower:
            required = tuple(sorted(self.available | {"variable_section_loft"}))
        elif not is_clamp and all(
            word not in lower for word in ("pocket", "hole", "fillet", "bracket", "clamp")
        ):
            # Existing ParametricPartRequest remains the authoritative BOX compiler input.
            spec = self._spec(request_id, text, state, tuple())
            return spec, ProductionRoute.BOX_PRIMITIVE
        else:
            required = tuple(sorted(self.available))
        params = {**defaults, **state, **self._numbers(lower)}
        if is_assembly:
            params.update(self._assembly_relative_updates(lower, params))
        unknowns = ()
        if is_clamp and "much wider" in lower:
            unknowns = (
                Unknown(
                    "clamp_width_mm",
                    UnknownClass.A_INTENT_CRITICAL,
                    "What finished clamp width should I use?",
                ),
            )
        elif "right width" in lower and "overall_width_mm" not in params:
            unknowns = (
                Unknown(
                    "overall_width_mm",
                    UnknownClass.A_INTENT_CRITICAL,
                    "What overall width should the bracket use?",
                ),
            )
        spec = self._spec(
            request_id,
            text,
            params,
            required,
            unknowns,
            artifact_name=(
                "S3 ARTICULATED ASSEMBLY"
                if is_assembly
                else "S3 PRINTED DESK CLAMP"
                if is_clamp
                else None
            ),
            assembly=is_assembly,
        )
        return spec, ProductionRoute.TYPED_FEATURE_IR

    def _spec(
        self,
        rid: str,
        text: str,
        params: Mapping[str, float],
        required: tuple[str, ...],
        unknowns: tuple[Unknown, ...] = (),
        artifact_name: str | None = None,
        assembly: bool = False,
    ) -> EngineeringIntentSpecLite:
        return EngineeringIntentSpecLite(
            "1",
            f"intent:{rid}",
            artifact_name or "PARAMETRIC MOUNTING BRACKET COUPON",
            text,
            required_components=(
                (
                    "S3_CLAMP",
                    "S3_ARM_A",
                    "S3_ARM_B",
                    "S3_PHONE_MOUNT_INTERFACE",
                    "S3_CHARGER_LINK",
                    "S3_CABLE_LINK",
                )
                if assembly
                else ()
            ),
            required_interfaces=(
                (
                    "PIVOT_1_CLAMP_TO_ARM_A",
                    "PIVOT_2_ARM_A_TO_ARM_B",
                    "PIVOT_3_ARM_B_TO_PHONE_MOUNT",
                )
                if assembly
                else ()
            ),
            mandatory_requirements=dict(params),
            manufacturing_constraints={
                "material": "PETG",
                "nozzle_diameter_mm": 0.4,
                **(
                    {
                        "print_bed_face": "flat bottom face",
                        "build_direction": "+Z",
                        "branding_face": "+Z only",
                        "branding_text": "CADWiz",
                    }
                    if assembly
                    else {}
                ),
            },
            founder_locked_facts=(
                {
                    "branding_text": "CADWiz",
                    "branding_on_bed_face": False,
                    "pivot_count": 3,
                    "structural_arm_count": 2,
                    "pivot_hardware": "M5 x 0.8",
                    "pivot_axis": "horizontal world Y",
                    "desk_orientation": "horizontal with clamp on back edge",
                    "user_direction": "+X from back edge across desk",
                    "phone_screen_direction": "+X toward seated user",
                    "phone_retention": "magnetic charger only",
                    "phone_side_rails": False,
                    "phone_bottom_ledge": False,
                    "pivot_1_fixed_half": "integral to clamp solid",
                }
                if assembly
                else {}
            ),
            unresolved_unknowns=unknowns,
            required_capabilities=required,
            provenance={"request_id": rid, "source": "ordinary_request"},
        )

    @staticmethod
    def _numbers(text: str) -> dict[str, float]:
        p = {}
        patterns = {
            "overall_width_mm": (
                r"(?:is|width to)\s+(\d+(?:\.\d+)?)\s*millimet(?:re|er)s?\s+wide"
                r"|(?:bracket width to|width)\s+(\d+(?:\.\d+)?)\s*millimet(?:re|er)s?"
                r"|(?:bracket)\s+(\d+(?:\.\d+)?)\s*millimet(?:re|er)s?\s+wide"
            ),
            "overall_height_mm": r"(\d+(?:\.\d+)?)\s*millimetres?\s+high",
            "base_thickness_mm": r"(\d+(?:\.\d+)?)\s*millimetres?\s+thick",
            "pocket_pair": r"pocket\s+(\d+(?:\.\d+)?)\s+by\s+(\d+(?:\.\d+)?)\s*millimetres?",
            "pocket_depth_mm": r"(?:and\s+)?(\d+(?:\.\d+)?)\s*millimetres?\s+deep",
            "hole_diameter_mm": r"two\s+(\d+(?:\.\d+)?)\s*millimetre\s+mounting holes",
            "hole_spacing_mm": (
                r"(?:holes?\s+)?spaced\s+(\d+(?:\.\d+)?)\s*millimetres?\s+apart"
                r"|hole spacing to\s+(\d+(?:\.\d+)?)\s*millimetres?"
            ),
            "fillet_radius_mm": (
                r"(?:add|radius to|fillet radius to)\s+(\d+(?:\.\d+)?)\s*"
                r"millimetre(?:s)?\s+(?:outside\s+)?fillets?"
                r"|outside fillet radius to\s+(\d+(?:\.\d+)?)\s*millimetres?"
            ),
            "desk_thickness_mm": (
                r"(?:fit|fits?)\s+(?:a\s+)?(\d+(?:\.\d+)?)\s*millimet(?:re|er)s?\s*(?:thick\s+)?desk"
                r"|desk opening to fit a\s+(\d+(?:\.\d+)?)\s*millimet(?:re|er)"
            ),
            "clamp_width_mm": (
                r"clamp\s+(\d+(?:\.\d+)?)\s*millimet(?:re|er)s?\s+wide"
                r"|clamp width to\s+(\d+(?:\.\d+)?)"
            ),
            "upper_jaw_thickness_mm": (
                r"upper jaw thickness to\s+(\d+(?:\.\d+)?)\s*millimet(?:re|er)s?"
            ),
            "screw_boss_extension_mm": (
                r"screw boss (?:extension|thickness) to\s+(\d+(?:\.\d+)?)\s*"
                r"millimet(?:re|er)s?"
            ),
            "arm_a_length_mm": (
                r"(?:arm a|first arm) length to\s+(\d+(?:\.\d+)?)\s*millimet(?:re|er)s?"
            ),
            "arm_b_length_mm": (
                r"(?:arm b|second arm) length to\s+(\d+(?:\.\d+)?)\s*millimet(?:re|er)s?"
            ),
            "arm_width_mm": r"(?:both )?arms?\s+(\d+(?:\.\d+)?)\s*millimet(?:re|er)s?\s+wide",
            "arm_rib_height_mm": (
                r"(?:rib height to|with)\s+(\d+(?:\.\d+)?)\s*millimet(?:re|er)"
                r"(?:s)?(?:\s+high)?\s+ribs?"
            ),
            "arm_web_thickness_mm": (
                r"(?:web thickness to|and)\s+(\d+(?:\.\d+)?)\s*millimet(?:re|er)"
                r"(?:s)?\s+(?:thick\s+)?web"
            ),
            "brand_emboss_depth_mm": (
                r"cadwiz emboss(?: depth)? to\s+(\d+(?:\.\d+)?)\s*millimet(?:re|er)s?"
            ),
            "pivot_1_angle_deg": r"pivot 1 (?:angle )?to\s+(-?\d+(?:\.\d+)?)\s*degrees?",
            "pivot_2_angle_deg": r"pivot 2 (?:angle )?to\s+(-?\d+(?:\.\d+)?)\s*degrees?",
            "pivot_3_angle_deg": r"pivot 3 (?:angle )?to\s+(-?\d+(?:\.\d+)?)\s*degrees?",
        }
        for key, pattern in patterns.items():
            match = re.search(pattern, text)
            if not match:
                continue
            values = [float(v) for v in match.groups() if v is not None]
            if key == "pocket_pair":
                p.update(pocket_width_mm=values[0], pocket_height_mm=values[1])
            else:
                p[key] = values[0]
        return p

    @staticmethod
    def _assembly_relative_updates(text: str, current: Mapping[str, float]) -> dict[str, float]:
        from ai_freecad_core.mechanical_foundation.articulated import QUALIFICATION_POSES

        updates: dict[str, float] = {}
        relative = re.search(
            r"(?:first arm|arm a)\s+(\d+(?:\.\d+)?)\s*millimet(?:re|er)s?\s+longer",
            text,
        )
        if relative:
            updates["arm_a_length_mm"] = float(current["arm_a_length_mm"]) + float(
                relative.group(1)
            )
        relative = re.search(
            r"(?:second arm|arm b)\s+(\d+(?:\.\d+)?)\s*millimet(?:re|er)s?\s+longer",
            text,
        )
        if relative:
            updates["arm_b_length_mm"] = float(current["arm_b_length_mm"]) + float(
                relative.group(1)
            )
        click = re.search(r"center pivot up one\s+(\d+(?:\.\d+)?)\s*-?degree click", text)
        if click:
            updates["pivot_2_angle_deg"] = float(current["pivot_2_angle_deg"]) + float(
                click.group(1)
            )
        if "fold the phone holder" in text or "position a" in text:
            updates.update(QUALIFICATION_POSES["FOLDED_STOWED"])
        elif "low extension" in text or "position b" in text:
            updates.update(QUALIFICATION_POSES["LOW_EXTENSION"])
        elif "normal working position" in text or "position c" in text:
            updates.update(QUALIFICATION_POSES["WORKING"])
        elif "raise the phone mount" in text or "position d" in text:
            updates.update(QUALIFICATION_POSES["HIGH_RAISED"])
        elif "pull the phone toward the user" in text or "position e" in text:
            updates.update(QUALIFICATION_POSES["TOWARD_USER"])
        return updates


def process_feature_text(
    router: FeatureRequestRouter,
    builder: FeatureProgramBuilder,
    request_id: str,
    text: str,
    project_state: Mapping[str, float] | None = None,
) -> OrdinaryFeatureRequestResult:
    spec, route = router.route(request_id, text, project_state)
    if route is ProductionRoute.BOX_PRIMITIVE:
        decision = RouteDecision(
            request_id,
            spec.intent_id,
            route,
            (),
            (),
            (),
            IntentGateOutcome.PASS,
            "DELEGATE_EXISTING_BOX",
        )
        return OrdinaryFeatureRequestResult(
            text, decision, spec, None, None, "Use the existing BOX request compiler."
        )
    gate = evaluate_intent(spec, router.available)
    missing = tuple(sorted(set(spec.required_capabilities) - router.available))
    if gate.outcome is not IntentGateOutcome.PASS:
        message = {
            IntentGateOutcome.ASK_USER: gate.reasons[0],
            IntentGateOutcome.CAPABILITY_BLOCKED: gate.reasons[0],
            IntentGateOutcome.INVALID: gate.reasons[0],
        }[gate.outcome]
        decision = RouteDecision(
            request_id,
            spec.intent_id,
            ProductionRoute.NO_GEOMETRY,
            spec.required_capabilities,
            tuple(sorted(set(spec.required_capabilities) & router.available)),
            missing,
            gate.outcome,
            "NO_GEOMETRY",
        )
        return OrdinaryFeatureRequestResult(text, decision, gate.spec, None, None, message)
    try:
        program = (
            _compile_articulated(gate.spec)
            if gate.spec.artifact_name == "S3 ARTICULATED ASSEMBLY"
            else _compile_clamp(gate.spec)
            if gate.spec.artifact_name == "S3 PRINTED DESK CLAMP"
            else compile_coupon_program(gate.spec)
        )
    except ValueError as error:
        invalid = replace(gate.spec, current_gate_outcome=IntentGateOutcome.INVALID)
        decision = RouteDecision(
            request_id,
            spec.intent_id,
            ProductionRoute.NO_GEOMETRY,
            spec.required_capabilities,
            spec.required_capabilities,
            (),
            IntentGateOutcome.INVALID,
            "NO_GEOMETRY",
        )
        return OrdinaryFeatureRequestResult(text, decision, invalid, None, None, str(error))
    execution = builder.execute(program)
    decision = RouteDecision(
        request_id,
        spec.intent_id,
        route,
        spec.required_capabilities,
        spec.required_capabilities,
        (),
        IntentGateOutcome.PASS,
        "EXECUTED",
    )
    return OrdinaryFeatureRequestResult(
        text, decision, gate.spec, program, execution, "Typed feature request completed."
    )


def _compile_clamp(spec: EngineeringIntentSpecLite) -> FeatureProgramIR:
    from ai_freecad_core.mechanical_foundation.clamp import compile_clamp_program

    return compile_clamp_program(spec)


def _compile_articulated(spec: EngineeringIntentSpecLite) -> FeatureProgramIR:
    from ai_freecad_core.mechanical_foundation.articulated import compile_articulated_program

    return compile_articulated_program(spec)
