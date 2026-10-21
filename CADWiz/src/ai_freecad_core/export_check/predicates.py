# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Part 21's four HARD export predicates, as assertions the verifier already reads.

    * export succeeds;
    * mesh is manifold / watertight;
    * mesh bounding box matches the FreeCAD solid within tolerance;
    * body count in export matches contract.

They are emitted as `AssertionResult` on the existing HARD layer rather than as
a new result type, so `result_verifier.build_verdict` decides an export the same
way it decides everything else: a failed HARD assertion is fatal and nothing
overrides it. Adding a parallel "export report" would have been a second
verifier, which the CRITICAL RULE exists to prevent.

Part 21's DERIVED predicates - minimum wall thickness, feature size, overhangs,
build volume - are deliberately not here. They need a printer profile and an
FDM model that does not exist yet, and an enum value with nothing behind it
invites a PASS that means nothing.
"""

from __future__ import annotations

from pathlib import Path

from ai_freecad_core.production_foundation.contracts import AssertionResult
from ai_freecad_core.result_verifier.checks import HARD

from .formats import ExportFormatError, read_export
from .mesh import BoundingBox

#: How far the exported mesh may differ from the solid, per axis.
#:
#: A mesh is a faceted approximation of a curved solid, so it is *expected* to
#: sit slightly inside a cylinder's true bounding box - the chord of each facet
#: falls short of the arc. 0.5 mm passes a normally tessellated part and still
#: catches the failures that matter: a unit slip (1000x), a wrong object
#: exported, or a mesher that dropped a feature.
DEFAULT_BOUNDING_BOX_TOLERANCE_MM = 0.5


def verify_export(
    path: Path,
    *,
    expected_bounds: BoundingBox | None = None,
    expected_body_count: int | None = None,
    tolerance_mm: float = DEFAULT_BOUNDING_BOX_TOLERANCE_MM,
    requirement_ids: tuple[str, ...] = (),
) -> tuple[AssertionResult, ...]:
    """Check a written export file against Part 21's HARD predicates.

    `expected_bounds` and `expected_body_count` come from the solid CADWiz
    built. When either is None its predicate is not emitted at all, rather than
    emitted as a pass: a check that had nothing to compare against did not
    happen, and a report that showed it passing would be claiming a comparison
    nobody made.
    """
    results: list[AssertionResult] = []

    if not path.exists():
        return (
            AssertionResult(
                "export_succeeds",
                HARD,
                False,
                "a written file",
                "no file",
                f"{path.name} was not written",
                requirement_ids,
            ),
        )
    size = path.stat().st_size
    if size == 0:
        return (
            AssertionResult(
                "export_succeeds",
                HARD,
                False,
                "a non-empty file",
                "0 bytes",
                f"{path.name} was written but is empty",
                requirement_ids,
            ),
        )

    try:
        mesh = read_export(path)
    except ExportFormatError as error:
        # Unreadable is a failure of "export succeeds", not a separate outcome:
        # a file a slicer cannot open has not been exported in any sense the
        # user cares about.
        return (
            AssertionResult(
                "export_succeeds",
                HARD,
                False,
                "a readable mesh file",
                "unreadable",
                str(error),
                requirement_ids,
            ),
        )

    topology = mesh.topology()
    results.append(
        AssertionResult(
            "export_succeeds",
            HARD,
            topology.triangle_count > 0,
            "a readable mesh with at least one triangle",
            f"{topology.triangle_count} triangles, {size} bytes",
            f"{path.name} read back cleanly"
            if topology.triangle_count
            else f"{path.name} is a valid file containing no geometry",
            requirement_ids,
        )
    )

    results.append(
        AssertionResult(
            "export_is_watertight",
            HARD,
            topology.watertight,
            "closed, manifold, consistently wound",
            (
                f"open_edges={topology.open_edges}, "
                f"non_manifold_edges={topology.non_manifold_edges}, "
                f"inconsistent_edges={topology.inconsistent_edges}, "
                f"degenerate_facets={topology.degenerate_facets}"
            ),
            "" if topology.watertight else _watertight_detail(topology),
            requirement_ids,
        )
    )

    if expected_bounds is not None:
        actual = mesh.bounding_box()
        if actual is None:
            results.append(
                AssertionResult(
                    "export_bounding_box_matches",
                    HARD,
                    False,
                    expected_bounds.size,
                    "no geometry",
                    "the export has no vertices to measure",
                    requirement_ids,
                )
            )
        else:
            matches = actual.matches(expected_bounds, tolerance_mm)
            results.append(
                AssertionResult(
                    "export_bounding_box_matches",
                    HARD,
                    matches,
                    tuple(round(value, 4) for value in expected_bounds.size),
                    tuple(round(value, 4) for value in actual.size),
                    ""
                    if matches
                    else (
                        f"largest axis difference "
                        f"{actual.largest_difference(expected_bounds):.4f} mm "
                        f"exceeds the {tolerance_mm} mm tolerance"
                    ),
                    requirement_ids,
                )
            )

    if expected_body_count is not None:
        matches = topology.component_count == expected_body_count
        results.append(
            AssertionResult(
                "export_body_count_matches",
                HARD,
                matches,
                expected_body_count,
                topology.component_count,
                ""
                if matches
                else (
                    f"the export contains {topology.component_count} separate bodies, "
                    f"and the contract calls for {expected_body_count}"
                ),
                requirement_ids,
            )
        )

    return tuple(results)


def _watertight_detail(topology: object) -> str:
    """Say which way it is broken, since the four failures need different fixes."""
    reasons = []
    if getattr(topology, "triangle_count", 0) == 0:
        reasons.append("it contains no triangles")
    if getattr(topology, "open_edges", 0):
        reasons.append(f"{topology.open_edges} edges are open (holes)")  # type: ignore[attr-defined]
    if getattr(topology, "non_manifold_edges", 0):
        reasons.append(
            f"{topology.non_manifold_edges} edges join three or more faces"  # type: ignore[attr-defined]
        )
    if getattr(topology, "inconsistent_edges", 0):
        reasons.append(
            f"{topology.inconsistent_edges} edges have faces pointing opposite ways"  # type: ignore[attr-defined]
        )
    if getattr(topology, "degenerate_facets", 0):
        reasons.append(
            f"{topology.degenerate_facets} triangles enclose no area"  # type: ignore[attr-defined]
        )
    return "the mesh is not watertight: " + "; ".join(reasons)
