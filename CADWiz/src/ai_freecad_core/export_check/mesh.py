# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""A triangle mesh, and the topology questions print-readiness asks of it.

Domain-neutral: no FreeCAD, no file formats, no tools. It takes triangles and
answers whether they close a solid.

**Vertices are welded by position before any topology is computed.** STL stores
three fresh vertices per triangle and never says which coincide, so an unwelded
edge count says every edge is open and every mesh is broken. 3MF does index its
vertices, but welding both keeps one answer rather than two that disagree by
format. The weld tolerance is a quantisation grid, not a nearest-neighbour
search: exact enough for meshes a kernel just wrote, and it cannot be quadratic
on a large export.

The vocabulary here - open edges, non-manifold edges, component count,
watertight - is deliberately the same as `discovery.import_analysis.ImportFacts`
already uses for imported geometry. Two names for the same measurement is how a
dashboard ends up disagreeing with a report.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

#: Grid the weld quantises onto, in millimetres. A kernel writing a mesh emits
#: coincident vertices bit-identically or within float noise; 1e-6 mm is far
#: below any modelling tolerance and far above that noise.
WELD_TOLERANCE_MM = 1e-6

Vertex = tuple[float, float, float]
Triangle = tuple[int, int, int]


@dataclass(frozen=True, slots=True)
class BoundingBox:
    """Axis-aligned extent, in millimetres."""

    min_x: float
    min_y: float
    min_z: float
    max_x: float
    max_y: float
    max_z: float

    @property
    def size(self) -> tuple[float, float, float]:
        """Length, width, height."""
        return (
            self.max_x - self.min_x,
            self.max_y - self.min_y,
            self.max_z - self.min_z,
        )

    def matches(self, other: BoundingBox, tolerance_mm: float) -> bool:
        """Whether every extent agrees within tolerance."""
        return all(
            abs(a - b) <= tolerance_mm
            for a, b in zip(self.size, other.size, strict=True)
        )

    def largest_difference(self, other: BoundingBox) -> float:
        """The worst disagreement between two boxes, for a failure message."""
        return max(abs(a - b) for a, b in zip(self.size, other.size, strict=True))


@dataclass(frozen=True, slots=True)
class MeshTopology:
    """What the triangles add up to."""

    triangle_count: int
    vertex_count: int
    #: Edges used by exactly one triangle: a hole.
    open_edges: int
    #: Edges used by three or more: a surface that branches.
    non_manifold_edges: int
    #: Edges used by two triangles that traverse them the same way, which means
    #: one of the two faces points inward.
    inconsistent_edges: int
    #: Triangles with a repeated vertex, which enclose no area.
    degenerate_facets: int
    #: Connected pieces, by shared welded vertices. The export's body count.
    component_count: int

    @property
    def watertight(self) -> bool:
        """Closed, manifold, and consistently wound, with something in it.

        All four, not just "no open edges". A mesh whose faces disagree about
        which way is out passes a hole check and still slices into nonsense.
        """
        return (
            self.triangle_count > 0
            and self.open_edges == 0
            and self.non_manifold_edges == 0
            and self.inconsistent_edges == 0
            and self.degenerate_facets == 0
        )


class TriangleMesh:
    """Triangles, welded, with their topology computed once on demand."""

    def __init__(self, vertices: Sequence[Vertex], triangles: Iterable[Triangle]) -> None:
        self._raw_vertices = tuple(vertices)
        self._raw_triangles = tuple(triangles)
        for triangle in self._raw_triangles:
            if any(index < 0 or index >= len(self._raw_vertices) for index in triangle):
                raise ValueError("triangle references a vertex that does not exist")

    @classmethod
    def from_facets(cls, facets: Iterable[tuple[Vertex, Vertex, Vertex]]) -> TriangleMesh:
        """Build from loose triangles, the shape STL arrives in."""
        vertices: list[Vertex] = []
        triangles: list[Triangle] = []
        for facet in facets:
            base = len(vertices)
            vertices.extend(facet)
            triangles.append((base, base + 1, base + 2))
        return cls(vertices, triangles)

    @property
    def raw_vertex_count(self) -> int:
        """Vertices as stored, before welding."""
        return len(self._raw_vertices)

    def bounding_box(self) -> BoundingBox | None:
        """The extent, or None for an empty mesh."""
        if not self._raw_vertices:
            return None
        xs = [item[0] for item in self._raw_vertices]
        ys = [item[1] for item in self._raw_vertices]
        zs = [item[2] for item in self._raw_vertices]
        return BoundingBox(min(xs), min(ys), min(zs), max(xs), max(ys), max(zs))

    def _welded(self) -> tuple[list[Vertex], list[Triangle]]:
        """Merge coincident vertices onto a quantisation grid."""
        index_of: dict[tuple[int, int, int], int] = {}
        remap: list[int] = []
        vertices: list[Vertex] = []
        for vertex in self._raw_vertices:
            key = tuple(round(value / WELD_TOLERANCE_MM) for value in vertex)
            existing = index_of.get(key)  # type: ignore[arg-type]
            if existing is None:
                existing = len(vertices)
                index_of[key] = existing  # type: ignore[index]
                vertices.append(vertex)
            remap.append(existing)
        triangles = [
            (remap[a], remap[b], remap[c]) for a, b, c in self._raw_triangles
        ]
        return vertices, triangles

    def topology(self) -> MeshTopology:
        """Compute every topology answer in one pass over the welded mesh."""
        vertices, triangles = self._welded()

        degenerate = sum(1 for a, b, c in triangles if len({a, b, c}) < 3)

        # Directed edge counts. An undirected edge used twice is manifold; the
        # two uses must run in opposite directions or the faces disagree about
        # which side is outside.
        directed: dict[tuple[int, int], int] = {}
        for a, b, c in triangles:
            if len({a, b, c}) < 3:
                continue
            for edge in ((a, b), (b, c), (c, a)):
                directed[edge] = directed.get(edge, 0) + 1

        open_edges = 0
        non_manifold = 0
        inconsistent = 0
        seen: set[tuple[int, int]] = set()
        for (start, end), forward in directed.items():
            key = (start, end) if start < end else (end, start)
            if key in seen:
                continue
            seen.add(key)
            backward = directed.get((end, start), 0)
            total = forward + backward
            if total == 1:
                open_edges += 1
            elif total > 2:
                non_manifold += 1
            elif forward == 2 or backward == 2:
                # Used twice, but both uses traverse it the same way.
                inconsistent += 1

        return MeshTopology(
            triangle_count=len(triangles),
            vertex_count=len(vertices),
            open_edges=open_edges,
            non_manifold_edges=non_manifold,
            inconsistent_edges=inconsistent,
            degenerate_facets=degenerate,
            component_count=_component_count(len(vertices), triangles),
        )


def _component_count(vertex_count: int, triangles: Sequence[Triangle]) -> int:
    """Connected pieces, by union-find over shared vertices.

    Vertices belonging to no triangle are ignored rather than counted as
    components of their own: a stray point is not a body, and counting it as
    one would fail a body-count predicate on a mesh that is actually correct.
    """
    if not triangles:
        return 0
    parent = list(range(vertex_count))

    def find(item: int) -> int:
        while parent[item] != item:
            parent[item] = parent[parent[item]]
            item = parent[item]
        return item

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    used: set[int] = set()
    for a, b, c in triangles:
        union(a, b)
        union(b, c)
        used.update((a, b, c))
    return len({find(item) for item in used})
