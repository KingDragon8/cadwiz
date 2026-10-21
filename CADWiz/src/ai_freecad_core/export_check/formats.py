# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Read back what was exported, so the check measures the file and not the plan.

Part 21: "the exported mesh is checked, not assumed". That word does the work -
verifying the solid CADWiz still has in memory proves nothing about the bytes
the user will hand to a slicer. These readers open the actual file.

Two formats, both parsed here rather than through a library, because the
alternative is a new third-party dependency (Stop condition 4) to read two
formats that are between them a zip of XML and a fixed-size record loop.
"""

from __future__ import annotations

import re
import struct
import xml.etree.ElementTree as ElementTree
import zipfile
from pathlib import Path

from .mesh import TriangleMesh, Vertex

#: The 3MF core namespace. A file that does not declare it is not a 3MF whose
#: contents we can claim to understand.
_CORE_NAMESPACE = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"

#: Where the OPC container keeps the model. 3MF permits other part names via
#: _rels, but every writer in practice - FreeCAD's included, verified
#: 2026-09-06 - uses this one, and guessing is worse than saying so.
_MODEL_PART = "3D/3dmodel.model"


class ExportFormatError(ValueError):
    """The file is not the format it claims, or is not readable as one."""


def read_3mf(path: Path) -> TriangleMesh:
    """Parse the mesh out of a 3MF container."""
    if not zipfile.is_zipfile(path):
        raise ExportFormatError(f"{path.name} is not a zip container, so it is not a 3MF")
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            if _MODEL_PART not in names:
                raise ExportFormatError(
                    f"{path.name} has no {_MODEL_PART}; entries are {sorted(names)}"
                )
            payload = archive.read(_MODEL_PART)
    except zipfile.BadZipFile as error:
        raise ExportFormatError(f"{path.name} is a damaged zip: {error}") from error

    try:
        root = ElementTree.fromstring(payload)
    except ElementTree.ParseError as error:
        raise ExportFormatError(f"{path.name} has unreadable model XML: {error}") from error

    namespace = _namespace_of(root)
    vertices: list[Vertex] = []
    triangles: list[tuple[int, int, int]] = []
    for mesh_element in root.iter(f"{namespace}mesh"):
        # Each <object> carries its own vertex indices, so an offset keeps the
        # objects from sharing indices they never meant to share.
        offset = len(vertices)
        for vertex in mesh_element.iter(f"{namespace}vertex"):
            vertices.append(
                (
                    float(vertex.get("x", "0")),
                    float(vertex.get("y", "0")),
                    float(vertex.get("z", "0")),
                )
            )
        for triangle in mesh_element.iter(f"{namespace}triangle"):
            triangles.append(
                (
                    offset + int(triangle.get("v1", "0")),
                    offset + int(triangle.get("v2", "0")),
                    offset + int(triangle.get("v3", "0")),
                )
            )
    return TriangleMesh(vertices, triangles)


def unit_of_3mf(path: Path) -> str:
    """The declared unit, or "" when the file does not say.

    3MF defaults to millimetre when the attribute is absent, but "the file did
    not say" and "the file said millimetre" are different facts and a printer
    profile may care which.
    """
    with zipfile.ZipFile(path) as archive:
        root = ElementTree.fromstring(archive.read(_MODEL_PART))
    return root.get("unit", "")


def read_stl(path: Path) -> TriangleMesh:
    """Parse a binary or ASCII STL into loose facets."""
    data = path.read_bytes()
    if not data:
        raise ExportFormatError(f"{path.name} is empty")
    if _looks_ascii(data):
        return _read_ascii_stl(data, path)
    return _read_binary_stl(data, path)


def read_export(path: Path) -> TriangleMesh:
    """Read whichever of the two formats the suffix names."""
    suffix = path.suffix.casefold()
    if suffix == ".3mf":
        return read_3mf(path)
    if suffix == ".stl":
        return read_stl(path)
    raise ExportFormatError(f"no reader for {suffix or 'a file with no suffix'}")


def _namespace_of(root: ElementTree.Element) -> str:
    """The Clark-notation namespace prefix used by this document."""
    if root.tag.startswith("{"):
        return root.tag[: root.tag.index("}") + 1]
    return ""


def _looks_ascii(data: bytes) -> bool:
    """Whether this is an ASCII STL.

    The header alone is not enough: a binary STL may legally begin with the
    word "solid", and plenty do. The reliable tell is that a binary file's
    declared triangle count exactly matches its length.
    """
    if not data.startswith(b"solid"):
        return False
    if len(data) >= 84:
        (declared,) = struct.unpack("<I", data[80:84])
        if len(data) == 84 + declared * 50:
            return False
    return b"facet normal" in data[:2048] or b"vertex" in data[:2048]


def _read_binary_stl(data: bytes, path: Path) -> TriangleMesh:
    if len(data) < 84:
        raise ExportFormatError(f"{path.name} is too short to be a binary STL")
    (count,) = struct.unpack("<I", data[80:84])
    expected = 84 + count * 50
    if len(data) != expected:
        raise ExportFormatError(
            f"{path.name} declares {count} triangles, which needs {expected} bytes, "
            f"but the file is {len(data)}"
        )
    facets: list[tuple[Vertex, Vertex, Vertex]] = []
    for index in range(count):
        start = 84 + index * 50
        values = struct.unpack("<12f", data[start : start + 48])
        facets.append(
            (
                (values[3], values[4], values[5]),
                (values[6], values[7], values[8]),
                (values[9], values[10], values[11]),
            )
        )
    return TriangleMesh.from_facets(facets)


_VERTEX_LINE = re.compile(rb"vertex\s+(\S+)\s+(\S+)\s+(\S+)")


def _read_ascii_stl(data: bytes, path: Path) -> TriangleMesh:
    points: list[Vertex] = [
        (float(x), float(y), float(z)) for x, y, z in _VERTEX_LINE.findall(data)
    ]
    if len(points) % 3:
        raise ExportFormatError(
            f"{path.name} has {len(points)} vertices, which is not a whole number of triangles"
        )
    facets = [
        (points[index], points[index + 1], points[index + 2])
        for index in range(0, len(points), 3)
    ]
    return TriangleMesh.from_facets(facets)
