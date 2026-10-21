# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Deterministic intent gate; capability gaps are never turned into questions."""

from __future__ import annotations
from dataclasses import replace
from .contracts import DerivedEngineeringValue, EngineeringIntentSpecLite, IntentGateOutcome, IntentGateResult, UnknownClass

def evaluate_intent(spec:EngineeringIntentSpecLite, available_capabilities:set[str]) -> IntentGateResult:
    reasons:list[str]=[]
    missing=sorted(set(spec.required_capabilities)-available_capabilities)
    if missing:
        outcome=IntentGateOutcome.CAPABILITY_BLOCKED; reasons.append("missing production capabilities: "+", ".join(missing))
    elif any(isinstance(v,(int,float)) and not isinstance(v,bool) and v<=0 for k,v in spec.mandatory_requirements.items() if any(word in k.casefold() for word in ("width","height","thickness","depth","diameter","spacing","radius"))):
        outcome=IntentGateOutcome.INVALID; reasons.append("mandatory engineering dimensions must be positive")
    else:
        critical=[u.identifier for u in spec.unresolved_unknowns if not u.resolved and u.classification is UnknownClass.A_INTENT_CRITICAL]
        if critical:
            outcome=IntentGateOutcome.ASK_USER; reasons.append("unresolved intent-critical facts: "+", ".join(critical))
        else:
            outcome=IntentGateOutcome.PASS
    derived=list(spec.derived_engineering_values)
    if spec.manufacturing_constraints.get("material")=="PETG" and not any(v.identifier=="petg_min_wall" for v in derived):
        nozzle=float(spec.manufacturing_constraints.get("nozzle_diameter_mm",0.4))
        derived.append(DerivedEngineeringValue("petg_min_wall",round(nozzle*4,3),"mm","4 * nozzle_diameter_mm",("four perimeter baseline",),"declared PETG manufacturing rule",0.85))
    assumptions=list(spec.assumptions)
    if "color" not in spec.mandatory_requirements:
        assumptions.append("Cosmetic color default: neutral gray; reversible")
    updated=replace(spec,derived_engineering_values=tuple(derived),assumptions=tuple(dict.fromkeys(assumptions)),current_gate_outcome=outcome)
    return IntentGateResult(outcome,updated,tuple(reasons),outcome is IntentGateOutcome.PASS)

