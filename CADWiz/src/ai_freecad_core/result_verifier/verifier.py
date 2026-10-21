# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Aggregate individual checks into one structured pass/fail verdict."""

from __future__ import annotations

from ai_freecad_core.production_foundation.contracts import AssertionResult, VerificationResult
from ai_freecad_core.production_foundation.verification import RepairBudget, VerificationCoordinator

_coordinator = VerificationCoordinator()


def build_verdict(
    assertions: tuple[AssertionResult, ...],
    *,
    budget: RepairBudget | None = None,
    repair_signature: str | None = None,
) -> VerificationResult:
    """PASS only if every HARD assertion passes; DERIVED failures are recorded but non-blocking."""
    return _coordinator.compare(assertions, budget=budget, repair_signature=repair_signature)
