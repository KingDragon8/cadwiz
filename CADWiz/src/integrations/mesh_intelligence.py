# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Real-mesh analysis backing the mesh component-swap pipeline.

This is the one place a real mesh file gets turned into the
``MeshIntelligenceReport`` that ``ai_freecad_core``'s classifier/planner
already know how to reason over. Pymeshlab-backed, following the same
``detect_pymeshlab()``/``_inspect_with_pymeshlab`` patterns already used by
``external_mesh_tools.py``. ``ai_freecad_core`` itself never imports
pymeshlab or touches a file — that import boundary is deliberate.
"""

from __future__ import annotations

import ctypes
import os
import platform
import shutil
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any

from ai_freecad_core.workflow.adaptive_mesh import (
    MeshIntelligenceReport,
    MeshResources,
    RegionBounds,
)
from ai_freecad_core.workflow.mesh_component_swap import (
    ComponentIndexSelector,
    ComponentSelector,
    GeometricRegionSelector,
)
from integrations.external_mesh_tools import detect_pymeshlab


class MeshAnalysisError(RuntimeError):
    """A mesh could not be honestly analyzed; never silently guessed at."""


class EmptyRegionSelection(MeshAnalysisError):
    """The chosen region contains no surface at all.

    This is not a malfunction and it is not an ambiguous request — it is a
    measured fact about the model, and the most common cause is a perfectly
    reasonable one: the centre of a hollow or shell-like model (a bottle, a
    box, a case) is empty space. It carries the measured distance to the
    nearest surface so the caller can tell the user how far off the point was
    and what radius would actually reach material, instead of reporting a bare
    failure they cannot act on.
    """

    def __init__(
        self,
        center: tuple[float, float, float],
        nearest_point: tuple[float, float, float],
        nearest_distance_mm: float,
        reachable_radial_radius_mm: float | None,
    ) -> None:
        self.center = center
        self.nearest_point = nearest_point
        self.nearest_distance_mm = nearest_distance_mm
        self.reachable_radial_radius_mm = reachable_radial_radius_mm
        spot = ", ".join(f"{value:.2f}" for value in center)
        nearest = ", ".join(f"{value:.2f}" for value in nearest_point)
        if reachable_radial_radius_mm is not None:
            remedy = (
                f"Widen the region radius to at least "
                f"{reachable_radial_radius_mm:.2f} mm to reach it"
            )
        else:
            remedy = (
                "The region is also too short along its axis to reach any surface, "
                "so lengthen it as well as widening it"
            )
        super().__init__(
            f"There is nothing to edit at that spot. The point you chose "
            f"({spot}) is in empty space — this model is hollow or open there. "
            f"The nearest surface is {nearest_distance_mm:.2f} mm away at "
            f"({nearest}). {remedy}, or choose a point on the surface instead."
        )


@dataclass(frozen=True, slots=True)
class RegionEstimate:
    """Real, computed membership of a selector against an actual mesh file."""

    bounds: RegionBounds
    estimated_triangles: int
    model_fraction: float


def probe_resources(engines: tuple[str, ...]) -> MeshResources:
    """Report real, currently-available resources; never a fabricated estimate."""
    _total, _used, disk_free = shutil.disk_usage(Path.cwd().anchor)
    return MeshResources(
        cpu_count=os.cpu_count() or 1,
        memory_available_bytes=_available_memory_bytes(),
        disk_available_bytes=disk_free,
        engines=engines,
    )


def _available_memory_bytes() -> int:
    """Delegates to the one place hardware is read.

    This used to carry its own GlobalMemoryStatusEx call. Two copies of a
    Windows memory probe is how a panel and a router end up reporting different
    machines, so the structure definition and the call now live in
    `integrations.hardware` and this returns 0 when the value is unreadable --
    which is what the mesh estimator here has always expected.
    """
    from integrations.hardware import detect

    available = detect().available_memory_bytes
    return int(available) if available is not None else 0


def _mesh_bounds(mesh: Any) -> tuple[float, float, float]:
    matrix = mesh.vertex_matrix()
    spans = matrix.max(axis=0) - matrix.min(axis=0)
    return (float(spans[0]), float(spans[1]), float(spans[2]))


def build_mesh_intelligence_report(path: Path) -> MeshIntelligenceReport:
    """Analyze a real mesh file with pymeshlab.

    Fields the file alone cannot answer stay honestly unresolved rather than
    fabricated: ``edit_region_fraction``/``semantic_target_confidence`` are
    left at 0.0 here (this function never sees a selector) — a caller must
    fill in real values from :func:`estimate_region` before classification.
    ``degenerate_faces``/``duplicate_faces``/``self_intersection_estimate``/
    ``normals_consistent`` are left ``None``: not cheaply obtainable from a
    single read-only pass without mutating a scratch copy first, which is
    out of scope for a pure analysis step (Phase 1 limitation).
    """
    capability = detect_pymeshlab()
    if not capability.available:
        raise MeshAnalysisError(f"pymeshlab is not available: {capability.explanation}")
    if not path.is_file():
        raise MeshAnalysisError(f"mesh file not found: {path}")
    module = import_module("pymeshlab")
    mesh_set = module.MeshSet()
    mesh_set.load_new_mesh(str(path))
    mesh = mesh_set.current_mesh()
    measures = mesh_set.get_topological_measures()

    connected_components = int(measures["connected_components_number"])
    watertight = bool(measures["is_mesh_two_manifold"]) and int(measures["number_holes"]) == 0

    return MeshIntelligenceReport(
        file_format=path.suffix.lstrip(".").lower(),
        file_size_bytes=path.stat().st_size,
        bounds=_mesh_bounds(mesh),
        unit="mm",
        unit_confidence=1.0,
        triangles=int(measures["faces_number"]),
        vertices=int(measures["vertices_number"]),
        edges=int(measures["edges_number"]),
        shells=connected_components,
        connected_components=connected_components,
        open_boundaries=int(measures["boundary_edges"]),
        non_manifold_edges=int(measures["non_two_manifold_edges"]),
        non_manifold_vertices=int(measures["non_two_manifold_vertices"]),
        degenerate_faces=None,
        duplicate_faces=None,
        self_intersection_estimate=None,
        normals_consistent=None,
        watertight=watertight,
        component_separable=connected_components > 1,
        local_density_estimate=None,
        thin_feature_estimate=None,
        edit_region_fraction=0.0,
        semantic_target_confidence=0.0,
        resources=probe_resources(engines=("pymeshlab",)),
        risks=(),
    )


def estimate_region(path: Path, selector: ComponentSelector) -> RegionEstimate:
    """Compute real face membership for a selector against an actual mesh.

    Not a guess: loads the mesh and tests every face's centroid against the
    selector's actual geometry (or its real connected-component split), so
    the numbers are independently reproducible from the same selector and
    mesh — the same test a caller could rerun and get the same answer from.
    """
    capability = detect_pymeshlab()
    if not capability.available:
        raise MeshAnalysisError(f"pymeshlab is not available: {capability.explanation}")
    module = import_module("pymeshlab")
    mesh_set = module.MeshSet()
    mesh_set.load_new_mesh(str(path))
    mesh = mesh_set.current_mesh()
    total_faces = mesh.face_number()
    if total_faces == 0:
        raise MeshAnalysisError("mesh has no faces")

    if isinstance(selector, ComponentIndexSelector):
        mesh_set.generate_splitting_by_connected_components()
        target_index = selector.component_index + 1
        if target_index >= mesh_set.mesh_number():
            raise MeshAnalysisError(
                f"component index {selector.component_index} does not exist "
                f"({mesh_set.mesh_number() - 1} components found)"
            )
        component = mesh_set.mesh(target_index)
        estimated_triangles = component.face_number()
        bounds = _region_bounds(component.vertex_matrix())
    else:
        estimated_triangles, bounds = _capsule_region(mesh, selector)

    return RegionEstimate(
        bounds=bounds,
        estimated_triangles=estimated_triangles,
        model_fraction=min(1.0, estimated_triangles / total_faces),
    )


def _region_bounds(vertices: Any) -> RegionBounds:
    spans = vertices.max(axis=0) - vertices.min(axis=0)
    mean = vertices.mean(axis=0)
    center = (float(mean[0]), float(mean[1]), float(mean[2]))
    half_extents = tuple(max(float(spans[index]) / 2, 1e-6) for index in range(3))
    return RegionBounds(center=center, half_extents=half_extents)  # type: ignore[arg-type]


def _capsule_region(mesh: Any, selector: GeometricRegionSelector) -> tuple[int, RegionBounds]:
    import numpy as np

    vertices = mesh.vertex_matrix()
    faces = mesh.face_matrix()
    centroids = vertices[faces].mean(axis=1)
    center = np.array(selector.center, dtype="float64")
    axis = np.array(selector.axis, dtype="float64")
    axis = axis / np.linalg.norm(axis)
    offsets = centroids - center
    axial = offsets @ axis
    radial = np.linalg.norm(offsets - np.outer(axial, axis), axis=1)
    inside = (np.abs(axial) <= selector.axial_half_length_mm) & (
        radial <= selector.radial_radius_mm
    )
    estimated_triangles = int(inside.sum())
    if estimated_triangles == 0:
        # Measure how far off the request was rather than reporting a bare
        # failure: the caller can only help the user if it knows the distance
        # to real material and the radius that would have reached it.
        distances = np.linalg.norm(offsets, axis=1)
        nearest_index = int(distances.argmin())
        within_axial = np.abs(axial) <= selector.axial_half_length_mm
        reachable = float(radial[within_axial].min()) if bool(within_axial.any()) else None
        raise EmptyRegionSelection(
            center=(float(center[0]), float(center[1]), float(center[2])),
            nearest_point=(
                float(centroids[nearest_index][0]),
                float(centroids[nearest_index][1]),
                float(centroids[nearest_index][2]),
            ),
            nearest_distance_mm=float(distances[nearest_index]),
            reachable_radial_radius_mm=reachable,
        )
    matched_vertices = vertices[np.unique(faces[inside])]
    return estimated_triangles, _region_bounds(matched_vertices)
