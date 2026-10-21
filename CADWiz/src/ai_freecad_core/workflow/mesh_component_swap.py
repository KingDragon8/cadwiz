# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Pure decision logic for generalized mesh component-swap edits.

Ties the existing ``MeshDifficultyClassifier`` and ``plan_semantic_mesh_edit``
routers together for the component-swap edit shape (remove a selected
target, optionally attach a provided replacement mesh). Zero I/O and zero
external-tool imports, matching the rest of ``ai_freecad_core`` — real mesh
files are only ever touched by ``integrations.mesh_intelligence`` and
``integrations.external_mesh_tools``.
"""

from __future__ import annotations

from dataclasses import dataclass

from .adaptive_mesh import (
    MeshDifficultyAssessment,
    MeshDifficultyClassifier,
    MeshIntelligenceReport,
    SemanticSelection,
)
from .semantic_mesh_edit import (
    SemanticMeshEditFacts,
    SemanticMeshEditPlan,
    SemanticMeshRoute,
    plan_semantic_mesh_edit,
)


@dataclass(frozen=True, slots=True)
class ComponentIndexSelector:
    """Target an independently separable connected component by index."""

    component_index: int

    def __post_init__(self) -> None:
        if self.component_index < 0:
            raise ValueError("component index cannot be negative")


@dataclass(frozen=True, slots=True)
class GeometricRegionSelector:
    """Target faces inside a bounded cylindrical region, for fused meshes.

    A direct generalization of the ``BRANCH_CENTER``/``BRANCH_AXIS``/radius
    constants that were hardcoded in the original one-off proof script —
    same math, now parameters instead of literals.
    """

    center: tuple[float, float, float]
    axis: tuple[float, float, float]
    radial_radius_mm: float
    axial_half_length_mm: float

    def __post_init__(self) -> None:
        if self.radial_radius_mm <= 0 or self.axial_half_length_mm <= 0:
            raise ValueError("region radius and half-length must be positive")


ComponentSelector = ComponentIndexSelector | GeometricRegionSelector


class RouteDisagreement(ValueError):
    """Two independently-reasoned routers disagreed; refuse rather than resolve it silently."""


def build_semantic_selection(
    report: MeshIntelligenceReport,
    selector: ComponentSelector,
    *,
    protected_subject: str,
    edit_target: str,
    transition_description: str,
    confidence: float,
    mask_artifact: str | None = None,
) -> SemanticSelection:
    """Translate a structured selector into the classifier's ``SemanticSelection``.

    Reproducibility comes from the selector, not from language understanding:
    a component index populates ``component_ids``; a geometric region must be
    backed by a ``mask_artifact`` reference (the caller writes the selector's
    exact numbers to a file) so the same selector reproduces the same face
    set on every run.
    """
    del report  # not needed for the translation itself; kept for signature symmetry
    if isinstance(selector, ComponentIndexSelector):
        return SemanticSelection(
            protected_subject=protected_subject,
            edit_target=edit_target,
            transition_description=transition_description,
            confidence=confidence,
            mask_artifact=mask_artifact,
            component_ids=(selector.component_index,),
        )
    if mask_artifact is None:
        raise ValueError("a geometric region selector requires a mask_artifact reference")
    return SemanticSelection(
        protected_subject=protected_subject,
        edit_target=edit_target,
        transition_description=transition_description,
        confidence=confidence,
        mask_artifact=mask_artifact,
        component_ids=(),
    )


def _separable_parts_for_swap(
    report: MeshIntelligenceReport, selection: SemanticSelection
) -> int:
    """How many separable parts the *edit target* spans, which is the planner's question.

    ``plan_semantic_mesh_edit`` tests ``connected_components > 1`` to decide
    whether the target can simply be lifted out as a loose part. That is a
    question about the target, not about the model — and the two are different
    the moment a model has unrelated extra pieces elsewhere, which real
    exported and scanned models almost always do.

    Passing the whole model's component count here was a real defect, found
    2026-07-29 by ``scripts/survey_unseen_meshes.py``: seven of ten unseen
    meshes were hard-blocked by ``RouteDisagreement`` and none routed, because
    the planner read "this model has 67 pieces" as "the target is a loose
    part" while the classifier — which asks the right question, ``report
    .component_separable and selection.component_ids`` — kept reasoning from
    topology. The two only agreed on ``dog_wizard.stl``, which happens to have
    exactly one component.

    So: a target named by component id on a separable model really is a loose
    part, and the model's own count applies. A target picked out by a
    geometric region is fused into the body by definition, however many
    unrelated pieces sit elsewhere, so it spans one part.

    A report claiming ``component_separable`` on a single-component model is
    self-contradictory; this deliberately lets that flow through to a
    ``RouteDisagreement`` rather than papering over it, because refusing
    contradictory inputs is exactly what that mechanism is for.
    """
    if report.component_separable and selection.component_ids:
        return report.connected_components
    return 1


def _facts_from_report(
    report: MeshIntelligenceReport, *, separable_parts: int
) -> SemanticMeshEditFacts:
    """Translate the fuller intelligence report into the router's narrow fact set.

    ``separable_parts`` is supplied by the caller rather than read off the
    report, because what it means depends on the edit: for a component swap it
    describes the target (see ``_separable_parts_for_swap``), while for a union
    every part of both sources participates, so the model's own count is the
    honest answer.

    Component swap always physically removes the target before placing any
    replacement — Phase 1 never leaves the source untouched and places an
    occluding replacement over it — so those two facts are fixed for this
    edit shape rather than derived from the report.
    """
    # "Manifold" here means "safe to hand to a Boolean", and Phase 2a's spike
    # established what that actually requires: Blender's EXACT solver was
    # reliable *for genuinely watertight inputs*. A mesh with no non-manifold
    # edges or vertices but hundreds of open boundaries is not that.
    #
    # Counting only non-manifold elements was the second half of the routing
    # defect found 2026-07-29: the classifier gates on ``report.watertight``
    # while this gated on the non-manifold counts, so every open-but-clean mesh
    # split the two routers apart. Real exported models are routinely
    # open-but-clean, so this was not an edge case.
    counted_clean: bool | None = None
    if report.non_manifold_edges is not None or report.non_manifold_vertices is not None:
        counted_clean = (report.non_manifold_edges or 0) == 0 and (
            report.non_manifold_vertices or 0
        ) == 0
    if counted_clean is None:
        manifold = bool(report.watertight)
    elif report.watertight is None:
        manifold = counted_clean
    else:
        manifold = counted_clean and report.watertight
    return SemanticMeshEditFacts(
        connected_components=separable_parts,
        manifold=manifold,
        source_faces=report.triangles,
        replacement_may_occlude_original=False,
        physical_removal_required=True,
    )


def plan_component_swap(
    report: MeshIntelligenceReport,
    selection: SemanticSelection,
) -> tuple[MeshDifficultyAssessment, SemanticMeshEditPlan]:
    """Cross-validate two independent routers before any mutation is planned.

    Disagreement between the difficulty classifier's primary route and the
    semantic edit planner's route is a hard block in Phase 1, not something
    silently resolved — it means two independently-reasoned views of the
    same mesh disagree about how it's safe to proceed.
    """
    assessment = MeshDifficultyClassifier().classify(report, selection)
    edit_plan = plan_semantic_mesh_edit(
        _facts_from_report(report, separable_parts=_separable_parts_for_swap(report, selection))
    )
    if assessment.primary_route is not None and assessment.primary_route != edit_plan.route:
        raise RouteDisagreement(
            f"difficulty classifier chose {assessment.primary_route.value!r} but the "
            f"semantic edit planner chose {edit_plan.route.value!r} for the same mesh"
        )
    return assessment, edit_plan


def plan_boolean_union(
    report_a: MeshIntelligenceReport,
    report_b: MeshIntelligenceReport,
    selection: SemanticSelection,
) -> tuple[MeshDifficultyAssessment, SemanticMeshEditPlan]:
    """Cross-validate three independent views before any merge is planned.

    Union has no target-selection ambiguity the way component swap does —
    the whole of both sources participates, deterministically — so there is
    no "which part" question to classify. What must still be checked is
    whether BOTH sources independently qualify for the one route this
    package has actually proven safe (``MANIFOLD_BOOLEAN_REPLACEMENT``,
    verified via the Blender EXACT-solver spike). Three independent reads —
    the difficulty classifier on source_a with ``selection``, and
    ``plan_semantic_mesh_edit`` on each source's own facts — must all agree;
    any disagreement is a hard block, matching ``plan_component_swap``'s
    refuse-rather-than-resolve stance.
    """
    # Unlike a swap, a union consumes the whole of both sources, so a source in
    # several pieces really is disqualifying and the model's own count is the
    # fact the planner needs. This is deliberately not the swap mapping.
    assessment = MeshDifficultyClassifier().classify(report_a, selection)
    plan_a = plan_semantic_mesh_edit(
        _facts_from_report(report_a, separable_parts=report_a.connected_components)
    )
    plan_b = plan_semantic_mesh_edit(
        _facts_from_report(report_b, separable_parts=report_b.connected_components)
    )
    routes = {assessment.primary_route, plan_a.route, plan_b.route}
    if routes != {SemanticMeshRoute.MANIFOLD_BOOLEAN_REPLACEMENT}:
        raise RouteDisagreement(
            "boolean union requires all independent views to agree on "
            f"MANIFOLD_BOOLEAN_REPLACEMENT; got classifier={assessment.primary_route}, "
            f"source_a={plan_a.route.value!r}, source_b={plan_b.route.value!r}"
        )
    return assessment, plan_a
