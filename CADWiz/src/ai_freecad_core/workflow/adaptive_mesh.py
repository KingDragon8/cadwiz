# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Contracts and deterministic planning for adaptive imported-mesh modification."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import IntEnum, StrEnum
from hashlib import sha256
from json import dumps
from typing import Any

from .semantic_mesh_edit import SemanticMeshRoute


class MeshDifficulty(IntEnum):
    DIRECT_COMPONENT = 1
    BOUNDED_LOCAL = 2
    COMPLEX_LOCAL_RECONSTRUCTION = 3
    GLOBAL_INTERVENTION = 4
    AMBIGUOUS_OR_UNSAFE = 5


class MeshFailureClass(StrEnum):
    IMPORT_PARSING = "import_or_parsing_failure"
    UNIT_AMBIGUITY = "unit_ambiguity"
    SEMANTIC_SELECTION = "semantic_selection_failure"
    COMPONENT_SEPARATION = "incorrect_component_separation"
    BOOLEAN = "boolean_failure"
    NON_MANIFOLD_INPUT = "non_manifold_input"
    RESOURCE_EXHAUSTION = "resource_exhaustion"
    TIMEOUT = "timeout"
    EXTERNAL_ENGINE = "external_engine_failure"
    HOLE_REPAIR = "hole_repair_failure"
    SURFACE_RECONSTRUCTION = "surface_reconstruction_failure"
    PROTECTED_DAMAGE = "excessive_protected_region_damage"
    DETAIL_LOSS = "detail_loss_failure"
    SELF_INTERSECTION = "self_intersection"
    NON_WATERTIGHT = "non_watertight_result"
    WEAK_ATTACHMENT = "weak_or_disconnected_replacement_attachment"
    DIMENSIONAL = "dimensional_error"
    EXPORT = "export_failure"
    SLICER_IMPORT = "slicer_import_failure"
    USER_CANCELLED = "user_cancelled"
    UNSUPPORTED_TOPOLOGY = "unsupported_topology"
    UNKNOWN = "unknown_failure"


class ZoneKind(StrEnum):
    PROTECTED = "protected"
    EDIT = "edit"
    TRANSITION = "transition"


class MeshRegionDisposition(StrEnum):
    LOCAL_REQUIRED = "local_required"
    GLOBAL_APPROVAL_REQUIRED = "global_approval_required"
    USER_MASK_REQUIRED = "user_mask_required"


@dataclass(frozen=True, slots=True)
class RegionBounds:
    center: tuple[float, float, float]
    half_extents: tuple[float, float, float]
    axis: tuple[float, float, float] | None = None

    def __post_init__(self) -> None:
        if any(value <= 0 for value in self.half_extents):
            raise ValueError("region half-extents must be positive")


@dataclass(frozen=True, slots=True)
class MeshRegionProposal:
    bounds: RegionBounds
    target_coverage_confidence: float
    estimated_model_fraction: float
    estimated_triangles: int
    transition_margin_mm: float
    source: str
    mask_artifact: str | None = None

    def __post_init__(self) -> None:
        if not 0 <= self.target_coverage_confidence <= 1:
            raise ValueError("target coverage confidence must be between zero and one")
        if not 0 < self.estimated_model_fraction <= 1:
            raise ValueError("estimated model fraction must be greater than zero and at most one")
        if self.estimated_triangles < 1 or self.transition_margin_mm <= 0:
            raise ValueError("region needs triangles and a positive transition margin")


@dataclass(frozen=True, slots=True)
class MeshRegionPlan:
    disposition: MeshRegionDisposition
    bounds: RegionBounds
    transition_margin_mm: float
    working_triangles: int
    triangle_reduction_fraction: float
    maximum_outside_deviation_mm: float
    maximum_outside_changed_fraction: float
    requires_mask_review: bool
    extraction_artifact: str | None
    boundary_artifact: str | None
    reasons: tuple[str, ...]
    stop_conditions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MeshRegionValidation:
    accepted: bool
    target_coverage_confirmed: bool
    boundary_stitched: bool
    outside_maximum_deviation_mm: float
    outside_changed_fraction: float
    failures: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MeshResources:
    cpu_count: int
    memory_available_bytes: int
    disk_available_bytes: int
    engines: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MeshIntelligenceReport:
    file_format: str
    file_size_bytes: int
    bounds: tuple[float, float, float]
    unit: str | None
    unit_confidence: float
    triangles: int
    vertices: int
    edges: int | None
    shells: int
    connected_components: int
    open_boundaries: int | None
    non_manifold_edges: int | None
    non_manifold_vertices: int | None
    degenerate_faces: int | None
    duplicate_faces: int | None
    self_intersection_estimate: int | None
    normals_consistent: bool | None
    watertight: bool | None
    component_separable: bool
    local_density_estimate: float | None
    thin_feature_estimate: float | None
    edit_region_fraction: float
    semantic_target_confidence: float
    resources: MeshResources
    risks: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for value, name in (
            (self.unit_confidence, "unit confidence"),
            (self.edit_region_fraction, "edit-region fraction"),
            (self.semantic_target_confidence, "semantic confidence"),
        ):
            if not 0 <= value <= 1:
                raise ValueError(f"{name} must be between zero and one")
        if self.triangles < 0 or self.vertices < 0 or self.connected_components < 0:
            raise ValueError("mesh counts cannot be negative")


@dataclass(frozen=True, slots=True)
class SemanticSelection:
    protected_subject: str
    edit_target: str
    transition_description: str
    confidence: float
    mask_artifact: str | None
    component_ids: tuple[int, ...] = ()

    @property
    def reproducible(self) -> bool:
        return bool(self.mask_artifact or self.component_ids)


@dataclass(frozen=True, slots=True)
class GeometryZone:
    kind: ZoneKind
    artifact: str
    maximum_surface_deviation_mm: float
    maximum_changed_fraction: float


@dataclass(frozen=True, slots=True)
class MeshDifficultyAssessment:
    level: MeshDifficulty
    confidence: float
    reasons: tuple[str, ...]
    expected_runtime_seconds: int
    expected_detail_loss: str
    primary_route: SemanticMeshRoute | None
    fallback_routes: tuple[SemanticMeshRoute, ...]
    stop_conditions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MeshWorkflowCandidate:
    candidate_id: str
    route: SemanticMeshRoute
    engine_chain: tuple[str, ...]
    rationale: tuple[str, ...]
    time_budget_seconds: int


@dataclass(frozen=True, slots=True)
class MeshAttemptRecord:
    candidate_id: str
    route: SemanticMeshRoute
    succeeded: bool
    failure_class: MeshFailureClass | None
    parameter_digest: str


@dataclass(frozen=True, slots=True)
class MeshFailure:
    category: MeshFailureClass
    explanation: str
    evidence: tuple[str, ...]
    likely_cause: str
    retry_sensible: bool
    recommended_route: SemanticMeshRoute | None
    user_input_would_help: bool


@dataclass(frozen=True, slots=True)
class MeshValidationResult:
    parsed: bool
    nonempty: bool
    watertight: bool | None
    manifold: bool | None
    normals_consistent: bool | None
    boundary_edges: int | None
    self_intersections: int | None
    disconnected_fragments: int | None
    protected_deviation_mm: float | None
    protected_changed_fraction: float | None
    requested_change_verified: bool
    replacement_connected: bool | None
    slicer_imported: bool | None
    evidence: tuple[str, ...]

    @property
    def blocking_failures(self) -> tuple[str, ...]:
        checks = {
            "parse": self.parsed,
            "nonempty": self.nonempty,
            "watertight": self.watertight,
            "manifold": self.manifold,
            "normals": self.normals_consistent,
            "requested_change": self.requested_change_verified,
            "replacement_connection": self.replacement_connected,
            "slicer_import": self.slicer_imported,
        }
        return tuple(name for name, passed in checks.items() if passed is False)


@dataclass(frozen=True, slots=True)
class MeshOperationManifest:
    schema_version: int
    operation_id: str
    source_path: str
    source_hash: str
    source_license: str
    source_provenance: str
    request: str
    intelligence: MeshIntelligenceReport
    difficulty: MeshDifficultyAssessment
    selection: SemanticSelection
    zones: tuple[GeometryZone, ...]
    attempts: tuple[MeshAttemptRecord, ...]
    validation: MeshValidationResult | None
    artifact_hashes: tuple[tuple[str, str], ...]
    policy_version: str
    repository_revision: str
    host: str
    region_plan: MeshRegionPlan | None = None

    def canonical_json(self) -> str:
        return dumps(asdict(self), sort_keys=True, separators=(",", ":"), default=str)

    @property
    def digest(self) -> str:
        return sha256(self.canonical_json().encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class WorkflowLearningRecord:
    topology_signature: str
    request_class: str
    route: SemanticMeshRoute
    succeeded: bool
    runtime_seconds: float
    failure_class: MeshFailureClass | None
    evidence_manifest: str


@dataclass(frozen=True, slots=True)
class WorkflowPolicy:
    version: str
    route_order: tuple[SemanticMeshRoute, ...]
    evidence_count: int


@dataclass(frozen=True, slots=True)
class PromotionDecision:
    promoted: bool
    previous_version: str
    candidate_version: str
    reasons: tuple[str, ...]


class MeshDifficultyClassifier:
    """Fail closed when geometry cannot support reproducible semantic selection."""

    def classify(
        self, report: MeshIntelligenceReport, selection: SemanticSelection
    ) -> MeshDifficultyAssessment:
        if selection.confidence < 0.55 or not selection.reproducible:
            return MeshDifficultyAssessment(
                MeshDifficulty.AMBIGUOUS_OR_UNSAFE,
                max(report.semantic_target_confidence, selection.confidence),
                ("The target is not reproducibly identified.",),
                0,
                "Unknown; automatic execution is stopped.",
                None,
                (),
                ("Obtain a rough user mask or select a component.",),
            )
        if report.component_separable and selection.component_ids:
            return MeshDifficultyAssessment(
                MeshDifficulty.DIRECT_COMPONENT,
                selection.confidence,
                ("The requested target is an independently addressable component.",),
                45,
                "None expected outside the selected component.",
                SemanticMeshRoute.LOOSE_PART_REPLACEMENT,
                (SemanticMeshRoute.MANIFOLD_BOOLEAN_REPLACEMENT,),
                ("Stop if protected geometry changes.",),
            )
        if report.watertight and report.triangles <= 500_000:
            return MeshDifficultyAssessment(
                MeshDifficulty.BOUNDED_LOCAL,
                selection.confidence,
                ("The target is connected but the mesh supports bounded local processing.",),
                90,
                "Limited to the transition zone.",
                SemanticMeshRoute.MANIFOLD_BOOLEAN_REPLACEMENT,
                (SemanticMeshRoute.LOCAL_VOXEL_RECONSTRUCTION,),
                ("Stop after one equivalent Boolean failure.",),
            )
        if report.edit_region_fraction <= 0.15:
            return MeshDifficultyAssessment(
                MeshDifficulty.COMPLEX_LOCAL_RECONSTRUCTION,
                selection.confidence,
                ("The fused target requires reviewed local reconstruction.",),
                180,
                "Possible local texture loss in the transition zone.",
                SemanticMeshRoute.LOCAL_VOXEL_RECONSTRUCTION,
                (),
                ("Stop if the mask is unreviewed.", "Stop on protected-zone deviation."),
            )
        return MeshDifficultyAssessment(
            MeshDifficulty.GLOBAL_INTERVENTION,
            selection.confidence,
            ("The affected region is too large for a local strategy.",),
            600,
            "Substantial surface detail may be lost.",
            SemanticMeshRoute.LOCAL_VOXEL_RECONSTRUCTION,
            (),
            ("Require explicit approval before global remeshing.",),
        )


class MeshRegionPlanner:
    """Make local processing the default while failing closed on incomplete regions."""

    def __init__(
        self,
        *,
        maximum_local_fraction: float = 0.25,
        minimum_target_coverage: float = 0.85,
        maximum_outside_deviation_mm: float = 0.05,
        maximum_outside_changed_fraction: float = 0.0001,
    ) -> None:
        self.maximum_local_fraction = maximum_local_fraction
        self.minimum_target_coverage = minimum_target_coverage
        self.maximum_outside_deviation_mm = maximum_outside_deviation_mm
        self.maximum_outside_changed_fraction = maximum_outside_changed_fraction

    def plan(
        self,
        report: MeshIntelligenceReport,
        proposal: MeshRegionProposal,
    ) -> MeshRegionPlan:
        reasons: tuple[str, ...]
        if proposal.target_coverage_confidence < self.minimum_target_coverage:
            disposition = MeshRegionDisposition.USER_MASK_REQUIRED
            reasons = ("The proposed region may not contain the entire semantic target.",)
        elif proposal.estimated_model_fraction > self.maximum_local_fraction:
            disposition = MeshRegionDisposition.GLOBAL_APPROVAL_REQUIRED
            reasons = ("The proposed region is too large for protected local processing.",)
        else:
            disposition = MeshRegionDisposition.LOCAL_REQUIRED
            reasons = (
                "The complete target fits inside a bounded region with a transition margin.",
                "All geometry outside the region remains protected.",
            )
        reduction = max(
            0.0,
            min(1.0, 1.0 - proposal.estimated_triangles / max(report.triangles, 1)),
        )
        return MeshRegionPlan(
            disposition,
            proposal.bounds,
            proposal.transition_margin_mm,
            proposal.estimated_triangles,
            reduction,
            self.maximum_outside_deviation_mm,
            self.maximum_outside_changed_fraction,
            disposition is MeshRegionDisposition.USER_MASK_REQUIRED,
            None,
            None,
            reasons,
            (
                "Stop if the target crosses the region boundary.",
                "Stop if the transition margin touches unrelated sensitive geometry.",
                "Reject if protected geometry exceeds either outside-change tolerance.",
            ),
        )

    @staticmethod
    def validate(
        plan: MeshRegionPlan,
        *,
        target_coverage_confirmed: bool,
        boundary_stitched: bool,
        outside_maximum_deviation_mm: float,
        outside_changed_fraction: float,
    ) -> MeshRegionValidation:
        failures = []
        if not target_coverage_confirmed:
            failures.append("target_not_fully_contained")
        if not boundary_stitched:
            failures.append("region_boundary_not_stitched")
        if outside_maximum_deviation_mm > plan.maximum_outside_deviation_mm:
            failures.append("outside_surface_deviation")
        if outside_changed_fraction > plan.maximum_outside_changed_fraction:
            failures.append("outside_changed_fraction")
        if plan.disposition is not MeshRegionDisposition.LOCAL_REQUIRED:
            failures.append("local_execution_not_authorized")
        return MeshRegionValidation(
            not failures,
            target_coverage_confirmed,
            boundary_stitched,
            outside_maximum_deviation_mm,
            outside_changed_fraction,
            tuple(failures),
        )


class MeshWorkflowPlanner:
    """Rank distinct candidates and suppress equivalent failed retries."""

    _ENGINES = {
        SemanticMeshRoute.LOOSE_PART_REPLACEMENT: ("pymeshlab", "blender", "pymeshlab"),
        SemanticMeshRoute.MANIFOLD_BOOLEAN_REPLACEMENT: (
            "pymeshlab",
            "blender_exact",
            "pymeshlab",
        ),
        SemanticMeshRoute.LOCAL_VOXEL_RECONSTRUCTION: (
            "pymeshlab",
            "blender_voxel",
            "pymeshlab",
        ),
        SemanticMeshRoute.OCCLUDING_REPLACEMENT: ("blender", "pymeshlab"),
    }

    def plan(
        self,
        assessment: MeshDifficultyAssessment,
        attempts: tuple[MeshAttemptRecord, ...] = (),
    ) -> tuple[MeshWorkflowCandidate, ...]:
        routes = (
            (assessment.primary_route, *assessment.fallback_routes)
            if assessment.primary_route is not None
            else ()
        )
        failed = {(item.route, item.parameter_digest) for item in attempts if not item.succeeded}
        candidates = []
        for index, route in enumerate(routes, start=1):
            digest = sha256(f"{route.value}:policy-1".encode()).hexdigest()
            if (route, digest) in failed:
                continue
            candidates.append(
                MeshWorkflowCandidate(
                    f"candidate-{index}-{route.value}",
                    route,
                    self._ENGINES[route],
                    (assessment.reasons[0], "Independent validation follows execution."),
                    max(assessment.expected_runtime_seconds, 1),
                )
            )
        return tuple(candidates)


class WorkflowPromotionManager:
    """Promote only evidence-backed policies; preserve an explicit rollback target."""

    def evaluate(
        self,
        current: WorkflowPolicy,
        candidate: WorkflowPolicy,
        records: tuple[WorkflowLearningRecord, ...],
        *,
        minimum_cases: int = 10,
    ) -> PromotionDecision:
        relevant = tuple(item for item in records if item.evidence_manifest)
        failures = tuple(item for item in relevant if not item.succeeded)
        reasons = []
        if len(relevant) < minimum_cases:
            reasons.append(f"requires at least {minimum_cases} evidenced cases")
        if failures:
            reasons.append("one or more hard-gated qualification cases failed")
        if candidate.version == current.version:
            reasons.append("candidate policy must have a new version")
        return PromotionDecision(
            not reasons,
            current.version,
            candidate.version,
            tuple(reasons),
        )


def classify_mesh_failure(
    *, timed_out: bool = False, parsed: bool = True, semantic_confidence: float = 1.0,
    protected_damage: bool = False, watertight: bool | None = True,
    change_verified: bool = True,
) -> MeshFailure | None:
    if timed_out:
        category = MeshFailureClass.TIMEOUT
    elif not parsed:
        category = MeshFailureClass.IMPORT_PARSING
    elif semantic_confidence < 0.55:
        category = MeshFailureClass.SEMANTIC_SELECTION
    elif protected_damage:
        category = MeshFailureClass.PROTECTED_DAMAGE
    elif watertight is False:
        category = MeshFailureClass.NON_WATERTIGHT
    elif not change_verified:
        category = MeshFailureClass.UNKNOWN
    else:
        return None
    routes = {
        MeshFailureClass.TIMEOUT: None,
        MeshFailureClass.IMPORT_PARSING: None,
        MeshFailureClass.SEMANTIC_SELECTION: None,
        MeshFailureClass.PROTECTED_DAMAGE: SemanticMeshRoute.LOCAL_VOXEL_RECONSTRUCTION,
        MeshFailureClass.NON_WATERTIGHT: SemanticMeshRoute.LOCAL_VOXEL_RECONSTRUCTION,
        MeshFailureClass.UNKNOWN: None,
    }
    return MeshFailure(
        category,
        category.value.replace("_", " ").capitalize(),
        (f"failure_class={category.value}",),
        "A required hard gate did not pass.",
        routes[category] is not None,
        routes[category],
        category is MeshFailureClass.SEMANTIC_SELECTION,
    )


def manifest_from_dict(value: dict[str, Any]) -> MeshOperationManifest:
    """Strictly reconstruct a persisted manifest and reject unknown schema versions."""
    if value.get("schema_version") != 1:
        raise ValueError("unsupported mesh operation manifest schema")
    intelligence = MeshIntelligenceReport(
        **{
            **value["intelligence"],
            "resources": MeshResources(**value["intelligence"]["resources"]),
            "risks": tuple(value["intelligence"].get("risks", ())),
        }
    )
    difficulty = MeshDifficultyAssessment(
        **{
            **value["difficulty"],
            "level": MeshDifficulty(value["difficulty"]["level"]),
            "primary_route": (
                SemanticMeshRoute(value["difficulty"]["primary_route"])
                if value["difficulty"]["primary_route"]
                else None
            ),
            "fallback_routes": tuple(
                SemanticMeshRoute(item) for item in value["difficulty"]["fallback_routes"]
            ),
            "reasons": tuple(value["difficulty"]["reasons"]),
            "stop_conditions": tuple(value["difficulty"]["stop_conditions"]),
        }
    )
    return MeshOperationManifest(
        schema_version=1,
        operation_id=value["operation_id"],
        source_path=value["source_path"],
        source_hash=value["source_hash"],
        source_license=value["source_license"],
        source_provenance=value["source_provenance"],
        request=value["request"],
        intelligence=intelligence,
        difficulty=difficulty,
        selection=SemanticSelection(
            **{
                **value["selection"],
                "component_ids": tuple(value["selection"].get("component_ids", ())),
            }
        ),
        zones=tuple(
            GeometryZone(**{**item, "kind": ZoneKind(item["kind"])}) for item in value["zones"]
        ),
        attempts=tuple(
            MeshAttemptRecord(
                **{
                    **item,
                    "route": SemanticMeshRoute(item["route"]),
                    "failure_class": (
                        MeshFailureClass(item["failure_class"])
                        if item["failure_class"]
                        else None
                    ),
                }
            )
            for item in value["attempts"]
        ),
        validation=(
            MeshValidationResult(
                **{**value["validation"], "evidence": tuple(value["validation"]["evidence"])}
            )
            if value["validation"]
            else None
        ),
        artifact_hashes=tuple(tuple(item) for item in value["artifact_hashes"]),
        policy_version=value["policy_version"],
        repository_revision=value["repository_revision"],
        host=value["host"],
        region_plan=(
            MeshRegionPlan(
                **{
                    **value["region_plan"],
                    "disposition": MeshRegionDisposition(
                        value["region_plan"]["disposition"]
                    ),
                    "bounds": RegionBounds(**value["region_plan"]["bounds"]),
                    "reasons": tuple(value["region_plan"]["reasons"]),
                    "stop_conditions": tuple(value["region_plan"]["stop_conditions"]),
                }
            )
            if value.get("region_plan")
            else None
        ),
    )
