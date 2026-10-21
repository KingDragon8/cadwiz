# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Fast-path planning for local semantic edits to imported polygon meshes."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class SemanticMeshRoute(StrEnum):
    LOOSE_PART_REPLACEMENT = "loose_part_replacement"
    MANIFOLD_BOOLEAN_REPLACEMENT = "manifold_boolean_replacement"
    OCCLUDING_REPLACEMENT = "occluding_replacement"
    LOCAL_VOXEL_RECONSTRUCTION = "local_voxel_reconstruction"


class SemanticMeshTool(StrEnum):
    PYMESHLAB = "pymeshlab"
    BLENDER = "blender"
    FREECAD = "freecad"
    MESHLAB_DESKTOP = "meshlab_desktop"


@dataclass(frozen=True, slots=True)
class SemanticMeshToolStage:
    tool: SemanticMeshTool
    purpose: str
    required: bool = True
    read_only: bool = False


@dataclass(frozen=True, slots=True)
class SemanticMeshEditFacts:
    connected_components: int
    manifold: bool
    source_faces: int
    replacement_may_occlude_original: bool
    physical_removal_required: bool


@dataclass(frozen=True, slots=True)
class SemanticMeshEditPlan:
    route: SemanticMeshRoute
    time_budget_seconds: int
    require_before_after_render: bool = True
    require_native_reopen: bool = True
    preserve_source: bool = True
    explanation: str = ""
    tool_stages: tuple[SemanticMeshToolStage, ...] = ()


def _validated_toolchain(edit_purpose: str) -> tuple[SemanticMeshToolStage, ...]:
    """Use each specialist for its measured strength; never invoke tools theatrically."""
    return (
        SemanticMeshToolStage(
            SemanticMeshTool.PYMESHLAB,
            "Inspect components, manifold state, defects, face count, and bounds.",
            read_only=True,
        ),
        SemanticMeshToolStage(SemanticMeshTool.BLENDER, edit_purpose),
        SemanticMeshToolStage(
            SemanticMeshTool.PYMESHLAB,
            "Reopen the candidate, repair only allowlisted defects, and compare topology.",
        ),
        SemanticMeshToolStage(
            SemanticMeshTool.FREECAD,
            "Import as a new object and independently validate visibility and downstream use.",
            read_only=True,
        ),
        SemanticMeshToolStage(
            SemanticMeshTool.MESHLAB_DESKTOP,
            "Optional human visual inspection; never required for unattended execution.",
            required=False,
            read_only=True,
        ),
    )


def plan_semantic_mesh_edit(facts: SemanticMeshEditFacts) -> SemanticMeshEditPlan:
    """Choose a bounded route before any destructive geometry operation."""
    if facts.connected_components > 1:
        return SemanticMeshEditPlan(
            SemanticMeshRoute.LOOSE_PART_REPLACEMENT,
            45,
            explanation="Separate and replace the independently connected target component.",
            tool_stages=_validated_toolchain(
                "Separate the loose target and create the replacement in an isolated scene."
            ),
        )
    if facts.manifold and facts.source_faces <= 500_000:
        return SemanticMeshEditPlan(
            SemanticMeshRoute.MANIFOLD_BOOLEAN_REPLACEMENT,
            90,
            explanation="The source is suitable for one controlled Boolean replacement.",
            tool_stages=_validated_toolchain(
                "Perform one bounded Boolean replacement with the approved geometry."
            ),
        )
    if facts.replacement_may_occlude_original and not facts.physical_removal_required:
        return SemanticMeshEditPlan(
            SemanticMeshRoute.OCCLUDING_REPLACEMENT,
            60,
            explanation=(
                "Preserve the fused source and place a closed replacement shell over the "
                "target; do not attempt exact Booleans on the unsuitable source."
            ),
            tool_stages=_validated_toolchain(
                "Create and position a closed semantic replacement without altering the source."
            ),
        )
    return SemanticMeshEditPlan(
        SemanticMeshRoute.LOCAL_VOXEL_RECONSTRUCTION,
        120,
        explanation=(
            "Isolate only the affected region, reconstruct it with a local voxel/SDF "
            "operation, and stitch it back; avoid whole-model remeshing."
        ),
        tool_stages=_validated_toolchain(
            "Perform bounded local voxel reconstruction and replace only the affected region."
        ),
    )
