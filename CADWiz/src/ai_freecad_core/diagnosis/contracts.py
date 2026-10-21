# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Immutable evidence contracts for read-only whole-document diagnosis."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class CauseClassification(str, Enum):
    RECOMPUTE = "recompute_failure"
    BROKEN_REFERENCE = "broken_reference"
    SKETCH_CONSTRAINT = "sketch_constraint_failure"
    NULL_SHAPE = "null_shape"
    INVALID_SHAPE = "invalid_shape"
    MULTIPLE_SOLIDS = "multiple_solids"
    BOOLEAN = "nonintersecting_boolean"
    POCKET = "pocket_failure"
    PARAMETER = "invalid_parameter"
    FILLET = "fillet_or_chamfer_failure"
    THICKNESS = "thickness_failure"
    LOFT = "loft_failure"
    SWEEP = "sweep_failure"
    DEPENDENCY = "invalid_dependency"
    EXPRESSION = "broken_expression"
    EXPORT = "export_failure"
    MESH = "mesh_issue"
    UNKNOWN = "unknown"


class DiagnosisConfidence(str, Enum):
    CONFIRMED = "confirmed"
    HIGHLY_LIKELY = "highly_likely"
    POSSIBLE = "possible"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class DiagnosticObjectState:
    object_id: str
    name: str
    label: str
    type_id: str
    order: int
    dependencies: tuple[str, ...] = ()
    states: tuple[str, ...] = ()
    shape_available: bool = True
    shape_valid: bool | None = None
    solid_count: int | None = None
    error_text: str = ""


@dataclass(frozen=True, slots=True)
class DiagnosticSnapshot:
    run_id: str
    document_id: str
    document_label: str
    freecad_version: str
    objects: tuple[DiagnosticObjectState, ...]
    selected_hint_ids: tuple[str, ...] = ()
    mutation_occurred: bool = False

    def __post_init__(self) -> None:
        if not self.run_id or not self.document_id:
            raise ValueError("diagnostic snapshot requires run and document identity")
        if self.mutation_occurred:
            raise ValueError("diagnostic snapshots must be read-only")


@dataclass(frozen=True, slots=True)
class DiagnosisEvidence:
    object_id: str
    source: str
    detail: str


@dataclass(frozen=True, slots=True)
class RepairStrategy:
    identifier: str
    title: str
    rationale: str
    risk: str
    approval_required: bool = True


@dataclass(frozen=True, slots=True)
class DiagnosisReport:
    run_id: str
    document_id: str
    root_cause: DiagnosticObjectState | None
    classification: CauseClassification | None
    confidence: DiagnosisConfidence
    dependency_path: tuple[str, ...]
    evidence: tuple[DiagnosisEvidence, ...]
    downstream_symptoms: tuple[str, ...]
    warnings: tuple[str, ...]
    repair_strategies: tuple[RepairStrategy, ...]
    mutation_occurred: bool
    original_model_safe: bool
    summary: str
