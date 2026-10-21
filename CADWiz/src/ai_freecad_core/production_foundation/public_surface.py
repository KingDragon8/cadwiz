# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Plain-language projection of governed intent-gate outcomes.

This is the single bridge between the production request boundary and a user
conversation.  It deliberately does not execute geometry: PASS continues to
the normal production tool path, while every non-PASS result stops before a
tool or model can turn uncertainty into an unsupported success claim.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .contracts import IntentGateOutcome
from .intent_gate import evaluate_intent
from .request_boundary import FeatureRequestRouter, ProductionRoute


@dataclass(frozen=True, slots=True)
class PublicIntentDecision:
    request_id: str
    outcome: IntentGateOutcome
    may_execute: bool
    user_message: str
    technical_reason: str
    production_route: ProductionRoute


def evaluate_public_request(
    request_id: str,
    text: str,
    *,
    project_state: Mapping[str, float] | None = None,
    available_capabilities: set[str] | None = None,
) -> PublicIntentDecision:
    """Return the governed outcome in concise public language.

    BOX requests are PASS-through because their established compiler remains
    authoritative. Typed feature requests use the exact same router and intent
    gate as protected production execution.
    """

    router = FeatureRequestRouter(available_capabilities)
    spec, route = router.route(request_id, text, project_state)
    if route is ProductionRoute.BOX_PRIMITIVE:
        return PublicIntentDecision(
            request_id, IntentGateOutcome.PASS, True, "", "box", route
        )

    gate = evaluate_intent(spec, router.available)
    reason = "; ".join(gate.reasons)
    if gate.outcome is IntentGateOutcome.PASS:
        return PublicIntentDecision(request_id, gate.outcome, True, "", reason, route)

    if gate.outcome is IntentGateOutcome.ASK_USER:
        question = next(
            (
                unknown.question
                for unknown in gate.spec.unresolved_unknowns
                if not unknown.resolved and unknown.question.strip()
            ),
            "What information should I use before making that change?",
        )
        message = question
    elif gate.outcome is IntentGateOutcome.CAPABILITY_BLOCKED:
        missing = sorted(set(gate.spec.required_capabilities) - router.available)
        readable = ", ".join(item.replace("_", " ") for item in missing)
        message = (
            f"CADWiz cannot currently execute {readable}. No model change was made."
            if readable
            else "CADWiz cannot currently execute that operation. No model change was made."
        )
    else:
        message = "That request is not valid for this model. No model change was made."

    return PublicIntentDecision(request_id, gate.outcome, False, message, reason, route)
