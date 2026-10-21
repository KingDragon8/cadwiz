# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Deterministic orchestration of read-only validators."""

from typing import Protocol

from .contracts import (
    EvidenceBinding,
    StageValidationReport,
    ValidationOutcome,
    ValidationReport,
    ValidationStage,
)


class ReadOnlyValidator(Protocol):
    @property
    def stage(self) -> ValidationStage: ...

    def validate(self, binding: EvidenceBinding) -> StageValidationReport: ...


class ValidationPipeline:
    """Aggregate stages conservatively without overstating confidence."""

    def __init__(self, validators: tuple[ReadOnlyValidator, ...]) -> None:
        if not isinstance(validators, tuple):
            raise TypeError("validators must be a tuple")
        stages = tuple(item.stage for item in validators)
        if len(stages) != len(set(stages)):
            raise ValueError("validation stages must be unique")
        order = {stage: index for index, stage in enumerate(ValidationStage)}
        self._validators = tuple(sorted(validators, key=lambda item: order[item.stage]))

    def run(self, binding: EvidenceBinding) -> ValidationReport:
        reports = tuple(item.validate(binding) for item in self._validators)
        if any(item.binding != binding for item in reports):
            raise ValueError("validator report binding does not match pipeline binding")
        outcomes = {item.outcome for item in reports}
        if ValidationOutcome.FAILED in outcomes:
            outcome = ValidationOutcome.FAILED
        elif outcomes == {ValidationOutcome.PASSED} and reports:
            outcome = ValidationOutcome.PASSED
        else:
            outcome = ValidationOutcome.INCONCLUSIVE
        return ValidationReport(binding, outcome, reports)
