# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Deterministic CAD/manufacturing assessment for printed radial index faces."""

from __future__ import annotations

from dataclasses import dataclass
from math import pi


@dataclass(frozen=True, slots=True)
class IndexCandidate:
    increment_deg: float
    tooth_count: int
    face_outer_diameter_mm: float
    face_inner_diameter_mm: float
    tooth_depth_mm: float
    nozzle_diameter_mm: float
    pitch_width_mm: float
    tooth_width_mm: float
    valley_width_mm: float
    cad_status: str
    physical_print_status: str = "NOT_TESTED"


def qualify_index_candidate(
    increment_deg: float,
    outer_diameter_mm: float = 30.0,
    inner_diameter_mm: float = 11.0,
    tooth_depth_mm: float = 1.2,
    nozzle_diameter_mm: float = 0.4,
) -> IndexCandidate:
    if increment_deg <= 0 or abs(360 / increment_deg - round(360 / increment_deg)) > 1e-9:
        raise ValueError("angular increment must divide 360 degrees exactly")
    if inner_diameter_mm <= 5 or outer_diameter_mm <= inner_diameter_mm:
        raise ValueError("indexed face diameters are invalid")
    count = round(360 / increment_deg)
    mean_radius = (outer_diameter_mm + inner_diameter_mm) / 4
    pitch = 2 * pi * mean_radius / count
    tooth = pitch * 0.5
    valley = pitch - tooth
    status = (
        "CAD_GEOMETRY_QUALIFIED"
        if min(tooth, valley) >= 2 * nozzle_diameter_mm
        else "CAD_GEOMETRY_QUALIFIED_WITH_LIMITS"
    )
    return IndexCandidate(
        increment_deg,
        count,
        outer_diameter_mm,
        inner_diameter_mm,
        tooth_depth_mm,
        nozzle_diameter_mm,
        pitch,
        tooth,
        valley,
        status,
    )
