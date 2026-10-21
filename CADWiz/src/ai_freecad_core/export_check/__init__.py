# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Reading an exported mesh back, and holding it to Part 21's HARD predicates."""

from .formats import ExportFormatError, read_3mf, read_export, read_stl, unit_of_3mf
from .mesh import (
    WELD_TOLERANCE_MM,
    BoundingBox,
    MeshTopology,
    TriangleMesh,
)
from .predicates import DEFAULT_BOUNDING_BOX_TOLERANCE_MM, verify_export

__all__ = [
    "DEFAULT_BOUNDING_BOX_TOLERANCE_MM",
    "WELD_TOLERANCE_MM",
    "BoundingBox",
    "ExportFormatError",
    "MeshTopology",
    "TriangleMesh",
    "read_3mf",
    "read_export",
    "read_stl",
    "unit_of_3mf",
    "verify_export",
]
