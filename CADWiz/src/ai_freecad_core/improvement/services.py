# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Deterministic services implementing the competitive-improvement loop."""

from __future__ import annotations

from dataclasses import dataclass, replace

from .contracts import (
    AlternativeCandidate,
    AlternativeScorecard,
    BenchmarkRun,
    DesignRecipe,
    ExperimentDecision,
    ExperimentEvaluation,
    ExperimentLedger,
    GeometryFingerprint,
    MaterialChangeEvidence,
    MetricDirection,
    PresentationSnapshot,
    PresentationVerification,
    RecipeParameter,
    RecipeUpdate,
    RecipeValueSource,
    ReuseAction,
    ReuseCandidate,
    ReusePlan,
    VerificationIssue,
)


class PresentationVerificationService:
    _temporary_roles = frozenset({"tool", "construction", "reference", "temporary"})

    def verify(
        self, snapshot: PresentationSnapshot, *, inspection_view_requested: bool = False
    ) -> PresentationVerification:
        visible = tuple(item for item in snapshot.objects if item.visible and item.shape_nonempty)
        issues = []
        if not visible:
            issues.append(VerificationIssue("blank_presentation", "No visible non-empty shape"))
        leaked = tuple(
            item.object_id
            for item in visible
            if item.role.strip().casefold() in self._temporary_roles
        )
        if leaked and not inspection_view_requested:
            issues.append(
                VerificationIssue(
                    "temporary_geometry_visible",
                    "Temporary or construction geometry is visible",
                    leaked,
                )
            )
        if not snapshot.camera_fitted:
            issues.append(VerificationIssue("camera_not_fitted", "Camera is not fitted"))
        if not snapshot.ai_panel_open:
            issues.append(VerificationIssue("ai_panel_closed", "AI panel is not open"))
        if not snapshot.screenshot_path:
            issues.append(VerificationIssue("missing_screenshot", "Screenshot evidence is absent"))
        return PresentationVerification(not issues, len(visible), tuple(issues))


class MaterialChangeService:
    def compare(
        self,
        before: tuple[GeometryFingerprint, ...],
        after: tuple[GeometryFingerprint, ...],
        required_object_ids: tuple[str, ...] = (),
    ) -> MaterialChangeEvidence:
        old = {item.object_id: item for item in before}
        new = {item.object_id: item for item in after}
        shared = sorted(set(old) & set(new))
        changed = tuple(identifier for identifier in shared if old[identifier] != new[identifier])
        unchanged = tuple(identifier for identifier in shared if identifier not in changed)
        issues = []
        if not changed and not (set(old) ^ set(new)):
            issues.append(
                VerificationIssue("no_material_change", "Geometry fingerprint is unchanged")
            )
        missing = tuple(sorted(set(required_object_ids) - set(changed)))
        if missing:
            issues.append(
                VerificationIssue(
                    "required_region_unchanged", "Required objects did not change", missing
                )
            )
        all_changed = tuple(sorted(set(changed) | (set(old) ^ set(new))))
        return MaterialChangeEvidence(not issues, all_changed, unchanged, tuple(issues))


class BenchmarkExperimentService:
    def __init__(self, ledger: ExperimentLedger | None = None) -> None:
        self._ledger = ledger

    def evaluate(self, baseline: BenchmarkRun, candidate: BenchmarkRun) -> ExperimentEvaluation:
        base_tasks = {item.task_id: item for item in baseline.results}
        candidate_tasks = {item.task_id: item for item in candidate.results}
        reasons, improved, regressed = [], [], []
        missing = tuple(sorted(set(base_tasks) - set(candidate_tasks)))
        if missing:
            reasons.append("candidate omitted protected tasks: " + ", ".join(missing))
        failed = tuple(
            sorted(item.task_id for item in candidate.results if not item.hard_gates_passed)
        )
        if failed:
            reasons.append("hard gates failed: " + ", ".join(failed))
        for task_id in sorted(set(base_tasks) & set(candidate_tasks)):
            prior = {item.name: item for item in base_tasks[task_id].metrics}
            current = {item.name: item for item in candidate_tasks[task_id].metrics}
            for name in sorted(set(prior) & set(current)):
                before, after = prior[name], current[name]
                delta = after.value - before.value
                better = delta > 0 if before.direction is MetricDirection.HIGHER else delta < 0
                worse = delta < 0 if before.direction is MetricDirection.HIGHER else delta > 0
                key = f"{task_id}:{name}"
                if better:
                    improved.append(key)
                elif worse:
                    regressed.append(key)
        if regressed:
            reasons.append("protected metrics regressed")
        if not improved:
            reasons.append("no measured improvement")
        decision = ExperimentDecision.KEEP if not reasons else ExperimentDecision.DISCARD
        result = ExperimentEvaluation(decision, tuple(reasons), tuple(improved), tuple(regressed))
        if self._ledger is not None:
            self._ledger.append(baseline, candidate, result)
        return result


class DesignRecipeService:
    def update(
        self,
        recipe: DesignRecipe,
        requirement_id: str,
        value: float | str,
        unit: str | None,
        source: RecipeValueSource,
    ) -> RecipeUpdate:
        binding = next(
            (item for item in recipe.bindings if item.requirement_id == requirement_id), None
        )
        if binding is None:
            raise KeyError(f"No recipe binding for {requirement_id}")
        parameters = {item.requirement_id: item for item in recipe.parameters}
        parameters[requirement_id] = RecipeParameter(requirement_id, value, unit, source)
        updated = replace(
            recipe,
            revision=recipe.revision + 1,
            parameters=tuple(parameters[key] for key in sorted(parameters)),
        )
        return RecipeUpdate(updated, binding.object_name, binding.property_name, value, unit)


class ReusePlanningService:
    def plan(self, candidates: tuple[ReuseCandidate, ...]) -> ReusePlan:
        eligible = tuple(
            item
            for item in candidates
            if item.editable and item.modification_allowed and item.evidence_citations
        )
        if not eligible:
            return ReusePlan(
                ReuseAction.CREATE,
                None,
                ("No editable, licensed, evidence-backed candidate was available",),
                (),
            )
        selected = max(eligible, key=lambda item: (item.relevance, item.identifier))
        action = ReuseAction.REUSE if selected.relevance >= 0.9 else ReuseAction.MODIFY
        return ReusePlan(
            action,
            selected.identifier,
            (f"Selected highest eligible relevance {selected.relevance:.3f}",),
            selected.evidence_citations,
        )


class AlternativeScorecardService:
    def rank(self, candidates: tuple[AlternativeCandidate, ...]) -> AlternativeScorecard:
        viable = tuple(item for item in candidates if item.score.hard_gates_passed)
        rejected = tuple(item.identifier for item in candidates if not item.score.hard_gates_passed)
        if not viable:
            return AlternativeScorecard((), rejected, None, ("No candidate passed hard gates",))
        maxima = {
            "mass": max(item.score.mass_g for item in viable) or 1,
            "time": max(item.score.print_time_minutes for item in viable) or 1,
            "supports": max(item.score.support_volume_mm3 for item in viable) or 1,
            "parts": max(item.score.part_count for item in viable) or 1,
        }

        def score(item: AlternativeCandidate) -> float:
            value = item.score
            return (
                value.requirement_coverage * 5
                + min(value.minimum_wall_mm / 1.6, 1.0)
                + min(value.minimum_clearance_mm / 0.3, 1.0)
                - value.mass_g / maxima["mass"]
                - value.print_time_minutes / maxima["time"]
                - value.support_volume_mm3 / maxima["supports"]
                - value.part_count / maxima["parts"]
            )

        ranked = tuple(sorted(viable, key=lambda item: (-score(item), item.identifier)))
        winner = ranked[0]
        rationale = (
            f"{winner.identifier} ranked highest after hard gates",
            "Coverage and minimum manufacturable dimensions outweighed normalized costs",
        )
        return AlternativeScorecard(ranked, rejected, winner.identifier, rationale)


@dataclass(frozen=True, slots=True)
class ImprovementServiceSuite:
    """One composed boundary for the five workbench improvement capabilities."""

    presentation: PresentationVerificationService
    material_change: MaterialChangeService
    experiments: BenchmarkExperimentService
    recipes: DesignRecipeService
    reuse: ReusePlanningService
    alternatives: AlternativeScorecardService
