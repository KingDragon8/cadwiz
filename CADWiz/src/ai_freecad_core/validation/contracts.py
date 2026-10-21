# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Immutable contracts for independent, evidence-bound validation."""

from dataclasses import dataclass
from enum import Enum


class ValidationStage(str, Enum):
    EXECUTION = "execution"
    RECOMPUTE = "recompute"
    GEOMETRY = "geometry"
    ENGINEERING = "engineering"
    READINESS = "readiness"


class ValidationOutcome(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    INCONCLUSIVE = "inconclusive"
    SKIPPED = "skipped"


class FindingSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass(frozen=True, slots=True)
class EvidenceBinding:
    """Exact revisions and versions against which evidence was measured."""

    intent_revision_id: str
    model_revision: int
    command_id: str | None = None
    document_version_id: str | None = None

    def __post_init__(self) -> None:
        if not self.intent_revision_id.strip() or self.model_revision < 0:
            raise ValueError("evidence binding requires a valid intent and model revision")


@dataclass(frozen=True, slots=True)
class ValidationEvidence:
    identifier: str
    method: str
    observed_value: str
    unit: str | None = None
    source_object_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.identifier.strip() or not self.method.strip():
            raise ValueError("evidence identifier and method must not be empty")


@dataclass(frozen=True, slots=True)
class ValidationFinding:
    code: str
    message: str
    severity: FindingSeverity
    evidence_ids: tuple[str, ...] = ()
    requirement_ids: tuple[str, ...] = ()
    object_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class StageValidationReport:
    stage: ValidationStage
    outcome: ValidationOutcome
    binding: EvidenceBinding
    findings: tuple[ValidationFinding, ...] = ()
    evidence: tuple[ValidationEvidence, ...] = ()
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for value in (self.findings, self.evidence, self.limitations):
            if not isinstance(value, tuple):
                raise TypeError("validation report collections must be tuples")
        identifiers = tuple(item.identifier for item in self.evidence)
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("evidence identifiers must be unique")
        known = set(identifiers)
        if any(set(item.evidence_ids) - known for item in self.findings):
            raise ValueError("finding references unknown evidence")


@dataclass(frozen=True, slots=True)
class ValidationReport:
    binding: EvidenceBinding
    outcome: ValidationOutcome
    stages: tuple[StageValidationReport, ...]
