# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Immutable contracts for the five competitive-improvement capabilities."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


@dataclass(frozen=True, slots=True)
class GeometryFingerprint:
    object_id: str
    volume_mm3: float
    bounds_mm: tuple[float, float, float]
    topology: tuple[int, int, int, int]
    digest: str


@dataclass(frozen=True, slots=True)
class PresentedObject:
    object_id: str
    label: str
    role: str
    visible: bool
    shape_nonempty: bool
    fingerprint: GeometryFingerprint | None = None


@dataclass(frozen=True, slots=True)
class PresentationSnapshot:
    document_id: str
    objects: tuple[PresentedObject, ...]
    camera_fitted: bool
    ai_panel_open: bool
    screenshot_path: str | None = None


@dataclass(frozen=True, slots=True)
class VerificationIssue:
    code: str
    message: str
    object_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PresentationVerification:
    passed: bool
    visible_shape_count: int
    issues: tuple[VerificationIssue, ...]


@dataclass(frozen=True, slots=True)
class MaterialChangeEvidence:
    changed: bool
    changed_object_ids: tuple[str, ...]
    unchanged_object_ids: tuple[str, ...]
    issues: tuple[VerificationIssue, ...]


class MetricDirection(StrEnum):
    HIGHER = "higher"
    LOWER = "lower"


@dataclass(frozen=True, slots=True)
class BenchmarkMetric:
    name: str
    value: float
    direction: MetricDirection


@dataclass(frozen=True, slots=True)
class BenchmarkTaskResult:
    task_id: str
    hard_gates_passed: bool
    metrics: tuple[BenchmarkMetric, ...]
    evidence_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class BenchmarkRun:
    identifier: str
    candidate_ref: str
    results: tuple[BenchmarkTaskResult, ...]
    elapsed_seconds: float


class ExperimentDecision(StrEnum):
    KEEP = "keep"
    DISCARD = "discard"


@dataclass(frozen=True, slots=True)
class ExperimentEvaluation:
    decision: ExperimentDecision
    reasons: tuple[str, ...]
    improved_metrics: tuple[str, ...]
    regressed_metrics: tuple[str, ...]


class ExperimentLedger(Protocol):
    def append(
        self, baseline: BenchmarkRun, candidate: BenchmarkRun, result: ExperimentEvaluation
    ) -> None: ...


class RecipeValueSource(StrEnum):
    CONVERSATION = "conversation"
    PARAMETRIC_RECIPE = "parametric_recipe"
    FREECAD = "freecad"


@dataclass(frozen=True, slots=True)
class RecipeBinding:
    requirement_id: str
    object_name: str
    property_name: str
    expression: str | None = None


@dataclass(frozen=True, slots=True)
class RecipeParameter:
    requirement_id: str
    value: float | str
    unit: str | None
    source: RecipeValueSource


@dataclass(frozen=True, slots=True)
class DesignRecipe:
    project_id: str
    revision: int
    bindings: tuple[RecipeBinding, ...]
    parameters: tuple[RecipeParameter, ...]


@dataclass(frozen=True, slots=True)
class RecipeUpdate:
    recipe: DesignRecipe
    object_name: str
    property_name: str
    value: float | str
    unit: str | None


class ReuseAction(StrEnum):
    REUSE = "reuse"
    MODIFY = "modify"
    CREATE = "create"


@dataclass(frozen=True, slots=True)
class ReuseCandidate:
    identifier: str
    title: str
    relevance: float
    editable: bool
    modification_allowed: bool
    evidence_citations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReusePlan:
    action: ReuseAction
    candidate_id: str | None
    rationale: tuple[str, ...]
    citations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ManufacturingScore:
    requirement_coverage: float
    mass_g: float
    print_time_minutes: float
    support_volume_mm3: float
    minimum_wall_mm: float
    minimum_clearance_mm: float
    part_count: int
    hard_gates_passed: bool = True


@dataclass(frozen=True, slots=True)
class AlternativeCandidate:
    identifier: str
    score: ManufacturingScore
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AlternativeScorecard:
    ranked: tuple[AlternativeCandidate, ...]
    rejected_ids: tuple[str, ...]
    winner_id: str | None
    rationale: tuple[str, ...]
