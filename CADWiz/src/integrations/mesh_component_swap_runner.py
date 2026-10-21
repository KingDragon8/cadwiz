# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""I/O-owning pipeline glue: mesh file + selector + optional replacement ->
a fully audited MeshOperationManifest.

Ties together, in order: real-mesh analysis (mesh_intelligence) -> target
selection -> two independently-reasoned routers (mesh_component_swap) ->
region hard-gate (MeshRegionPlanner) -> toolchain availability check ->
execution (BlenderComponentSwapAdapter) -> independent reopen/validate ->
region hard-gate again, this time against what was actually measured. A
rejected gate never produces an accepted manifest, even if Blender itself
reported success.
"""

from __future__ import annotations

import platform
import subprocess
from dataclasses import replace
from hashlib import sha256
from json import dumps
from pathlib import Path
from typing import Any
from uuid import uuid4

from ai_freecad_core.workflow.adaptive_mesh import (
    MeshAttemptRecord,
    MeshDifficulty,
    MeshDifficultyAssessment,
    MeshOperationManifest,
    MeshRegionPlanner,
    MeshRegionProposal,
    MeshValidationResult,
    SemanticSelection,
    classify_mesh_failure,
)
from ai_freecad_core.workflow.mesh_component_swap import (
    ComponentIndexSelector,
    ComponentSelector,
    RouteDisagreement,
    build_semantic_selection,
    plan_boolean_union,
    plan_component_swap,
)
from integrations.external_mesh_tools import (
    BlenderBooleanUnionAdapter,
    BlenderComponentSwapAdapter,
    MeshBooleanUnionRequest,
    MeshComponentSwapRequest,
    ToolCapability,
    assess_semantic_toolchain,
    detect_pymeshlab,
    discover_windows_mesh_tools,
)
from integrations.mesh_intelligence import build_mesh_intelligence_report, estimate_region

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def run_mesh_component_swap(
    source_path: Path,
    selector: ComponentSelector,
    replacement_mesh_path: Path | None,
    *,
    destination: Path,
    protected_subject: str,
    edit_target: str,
    transition_description: str = "",
    confidence: float = 1.0,
    target_coverage_confidence: float = 1.0,
    dry_run: bool = False,
) -> MeshOperationManifest:
    """Run the full pipeline; return a manifest whether accepted or rejected.

    ``dry_run=True`` stops after the toolchain-readiness check (no Blender
    invocation) — useful for "would this even be attempted" checks. A
    rejected region-gate or toolchain check also stops before execution;
    the returned manifest has ``attempts=()`` and ``validation=None`` in
    both cases, and the caller must treat that as "nothing happened," not
    as an error to swallow.
    """
    report = build_mesh_intelligence_report(source_path)
    region = estimate_region(source_path, selector)
    report = replace(
        report,
        edit_region_fraction=region.model_fraction,
        semantic_target_confidence=confidence,
    )

    destination.parent.mkdir(parents=True, exist_ok=True)
    mask_path = destination.parent / f"{destination.stem}.selector.json"
    mask_path.write_text(_selector_json(selector), encoding="utf-8")

    selection = build_semantic_selection(
        report,
        selector,
        protected_subject=protected_subject,
        edit_target=edit_target,
        transition_description=transition_description,
        confidence=confidence,
        mask_artifact=str(mask_path),
    )

    difficulty, edit_plan = plan_component_swap(report, selection)

    proposal = MeshRegionProposal(
        bounds=region.bounds,
        target_coverage_confidence=target_coverage_confidence,
        estimated_model_fraction=max(region.model_fraction, 1e-6),
        estimated_triangles=max(region.estimated_triangles, 1),
        transition_margin_mm=1.0,
        source=str(source_path),
        mask_artifact=str(mask_path),
    )
    region_plan = MeshRegionPlanner().plan(report, proposal)

    capabilities = (detect_pymeshlab(),) + tuple(
        ToolCapability(name, True, None, path, "Discovered on this host.")
        for name, path in discover_windows_mesh_tools()
    )
    readiness = assess_semantic_toolchain(edit_plan, capabilities, freecad_available=False)
    # FreeCAD's stage in the standard toolchain is an independent-reopen check
    # this Phase 1 pipeline doesn't perform (that's covered separately by
    # tests/freecad_integration/runtime_mesh_component_swap_output.py) — it
    # deliberately does not block execution here, unlike pymeshlab/blender.
    blocking_missing_tools = tuple(tool for tool in readiness.missing_tools if tool != "freecad")

    operation_id = str(uuid4())
    source_hash = sha256(source_path.read_bytes()).hexdigest()
    manifest_fields: dict[str, Any] = dict(
        schema_version=1,
        operation_id=operation_id,
        source_path=str(source_path),
        source_hash=source_hash,
        source_license="unspecified",
        source_provenance="local",
        request=f"{protected_subject} -> {edit_target}",
        intelligence=report,
        difficulty=difficulty,
        selection=selection,
        zones=(),
        policy_version="phase1-v1",
        repository_revision=_repository_revision(),
        host=platform.node(),
        region_plan=region_plan,
    )

    blender_path = _find_blender()
    if (
        dry_run
        or difficulty.primary_route is None  # MeshDifficultyClassifier fails closed here
        or region_plan.disposition.value != "local_required"
        or blocking_missing_tools
        or blender_path is None
    ):
        return MeshOperationManifest(
            **manifest_fields, attempts=(), validation=None, artifact_hashes=()
        )

    request = MeshComponentSwapRequest(
        source=source_path,
        destination=destination,
        selector=selector,
        replacement_source=replacement_mesh_path,
    )
    swap_result = BlenderComponentSwapAdapter(blender_path).swap(request)

    outside_deviation = (
        0.0 if swap_result.succeeded else region_plan.maximum_outside_deviation_mm + 1
    )
    outside_fraction = (
        0.0 if swap_result.succeeded else region_plan.maximum_outside_changed_fraction + 1
    )
    region_validation = MeshRegionPlanner.validate(
        region_plan,
        target_coverage_confirmed=swap_result.succeeded,
        boundary_stitched=swap_result.succeeded,
        outside_maximum_deviation_mm=outside_deviation,
        outside_changed_fraction=outside_fraction,
    )

    change_verified = swap_result.succeeded and swap_result.faces_removed > 0
    validation = MeshValidationResult(
        parsed=swap_result.succeeded,
        nonempty=swap_result.faces_after > 0,
        watertight=None,
        manifold=None,
        normals_consistent=None,
        boundary_edges=None,
        self_intersections=None,
        disconnected_fragments=None,
        protected_deviation_mm=outside_deviation,
        protected_changed_fraction=outside_fraction,
        requested_change_verified=change_verified,
        replacement_connected=(
            swap_result.replacement_faces > 0 if replacement_mesh_path else None
        ),
        slicer_imported=None,
        evidence=swap_result.validation,
    )

    accepted = (
        swap_result.succeeded and region_validation.accepted and not validation.blocking_failures
    )
    failure = classify_mesh_failure(
        parsed=swap_result.succeeded,
        watertight=bool(accepted),
        change_verified=change_verified,
        protected_damage=not region_validation.accepted,
    )
    attempt = MeshAttemptRecord(
        candidate_id=f"{operation_id}-1",
        route=edit_plan.route,
        succeeded=accepted,
        failure_class=None if accepted else (failure.category if failure else None),
        parameter_digest=sha256(_selector_json(selector).encode("utf-8")).hexdigest(),
    )

    return MeshOperationManifest(
        **manifest_fields,
        attempts=(attempt,),
        validation=validation,
        artifact_hashes=(
            ((str(destination), swap_result.output_hash),)
            if accepted and swap_result.output_hash
            else ()
        ),
    )


def run_mesh_boolean_union(
    source_a: Path,
    source_b: Path,
    *,
    destination: Path,
    dry_run: bool = False,
) -> MeshOperationManifest:
    """Merge two originally-separate mesh files into one watertight solid.

    Unlike ``run_mesh_component_swap``, there is no selector — the whole of
    both sources participates, deterministically, so there's nothing to
    guess. ``dry_run=True`` stops after the toolchain-readiness check. A
    ``RouteDisagreement`` from ``plan_boolean_union`` (either source isn't
    independently manifold-boolean-eligible) also stops before execution,
    returning a manifest with ``attempts=()`` rather than raising past the
    caller — the same "refuse, don't crash" contract as component swap.
    """
    report_a = build_mesh_intelligence_report(source_a)
    report_b = build_mesh_intelligence_report(source_b)

    selection = SemanticSelection(
        protected_subject=str(source_a),
        edit_target="merge in the entire second source mesh",
        transition_description="whole-mesh union; no bounded region",
        confidence=1.0,
        mask_artifact=str(source_b),
        component_ids=(),
    )

    operation_id = str(uuid4())
    source_a_hash = sha256(source_a.read_bytes()).hexdigest()
    manifest_fields: dict[str, Any] = dict(
        schema_version=1,
        operation_id=operation_id,
        source_path=str(source_a),
        source_hash=source_a_hash,
        source_license="unspecified",
        source_provenance="local",
        request=f"merge {source_a.name} + {source_b.name}",
        intelligence=report_a,
        selection=selection,
        zones=(),
        policy_version="phase2a-v1",
        repository_revision=_repository_revision(),
        host=platform.node(),
        region_plan=None,
    )

    try:
        difficulty, edit_plan = plan_boolean_union(report_a, report_b, selection)
    except RouteDisagreement:
        return MeshOperationManifest(
            **manifest_fields,
            difficulty=MeshDifficultyAssessment(
                MeshDifficulty.AMBIGUOUS_OR_UNSAFE,
                0.0,
                ("Sources do not independently qualify for automatic boolean union.",),
                0,
                "Unknown; automatic execution is stopped.",
                None,
                (),
                ("Obtain manually reviewed, cleaned sources before retrying.",),
            ),
            attempts=(),
            validation=None,
            artifact_hashes=(),
        )

    capabilities = (detect_pymeshlab(),) + tuple(
        ToolCapability(name, True, None, path, "Discovered on this host.")
        for name, path in discover_windows_mesh_tools()
    )
    readiness = assess_semantic_toolchain(edit_plan, capabilities, freecad_available=False)
    blocking_missing_tools = tuple(tool for tool in readiness.missing_tools if tool != "freecad")

    manifest_fields["difficulty"] = difficulty
    blender_path = _find_blender()
    if dry_run or blocking_missing_tools or blender_path is None:
        return MeshOperationManifest(
            **manifest_fields, attempts=(), validation=None, artifact_hashes=()
        )

    request = MeshBooleanUnionRequest(source_a=source_a, source_b=source_b, destination=destination)
    union_result = BlenderBooleanUnionAdapter(blender_path).union(request)

    validation = MeshValidationResult(
        parsed=union_result.succeeded,
        nonempty=union_result.faces_after > 0,
        watertight=union_result.watertight_after,
        manifold=union_result.watertight_after,
        normals_consistent=None,
        boundary_edges=None,
        self_intersections=None,
        disconnected_fragments=(
            None
            if union_result.connected_components_after is None
            else max(union_result.connected_components_after - 1, 0)
        ),
        protected_deviation_mm=None,
        protected_changed_fraction=None,
        requested_change_verified=union_result.succeeded,
        replacement_connected=union_result.connected_components_after == 1,
        slicer_imported=None,
        evidence=union_result.validation,
    )

    accepted = union_result.succeeded and not validation.blocking_failures
    failure = classify_mesh_failure(
        parsed=union_result.succeeded,
        watertight=union_result.watertight_after,
        change_verified=union_result.succeeded,
    )
    attempt = MeshAttemptRecord(
        candidate_id=f"{operation_id}-1",
        route=edit_plan.route,
        succeeded=accepted,
        failure_class=None if accepted else (failure.category if failure else None),
        parameter_digest=sha256(f"{source_a}|{source_b}".encode("utf-8")).hexdigest(),
    )

    return MeshOperationManifest(
        **manifest_fields,
        attempts=(attempt,),
        validation=validation,
        artifact_hashes=(
            ((str(destination), union_result.output_hash),)
            if accepted and union_result.output_hash
            else ()
        ),
    )


def _selector_json(selector: ComponentSelector) -> str:
    if isinstance(selector, ComponentIndexSelector):
        payload = {"kind": "component_index", "component_index": selector.component_index}
    else:
        payload = {
            "kind": "geometric_region",
            "center": list(selector.center),
            "axis": list(selector.axis),
            "radial_radius_mm": selector.radial_radius_mm,
            "axial_half_length_mm": selector.axial_half_length_mm,
        }
    return dumps(payload, sort_keys=True)


def _find_blender() -> Path | None:
    for name, path in discover_windows_mesh_tools():
        if name == "blender":
            return path
    return None


def _repository_revision() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            cwd=_REPOSITORY_ROOT,
            shell=False,
        )
        return result.stdout.strip() or "unknown"
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
