# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""The CADWiz result verifier: judges whether a CAD result is correct.

Host-neutral per CLAUDE.md's layering rule - no FreeCAD import anywhere in
this package. Host adapters (src/integrations/mcp_tools/verification.py for
the live text/voice path) measure real geometry into plain values and hand
them to the functions here.
"""

from __future__ import annotations

from .checks import (
    DERIVED,
    HARD,
    check_clearance,
    check_collision,
    check_dimensions,
    check_mating_gap,
    check_measurement_succeeded,
    check_minimum_wall_thickness,
    check_recompute,
    check_required_features,
    check_shape_validity,
    check_solid_count,
    check_target_match,
    check_volume_removed,
    check_volume_reconstruction,
)
from .verifier import build_verdict

#: This package's own contract version, independent of a provenance record's
#: schema version. Bumps when a check's meaning changes (a tolerance, a
#: required assertion added or dropped) - the thing a provenance record's
#: "verifier version" field exists to distinguish from "the object's stamp
#: format changed" (see integrations.mcp_tools.provenance.PROVENANCE_SCHEMA_VERSION).
VERIFIER_VERSION = "1.0.0"

__all__ = [
    "DERIVED",
    "HARD",
    "check_clearance",
    "check_collision",
    "check_dimensions",
    "check_mating_gap",
    "check_measurement_succeeded",
    "check_minimum_wall_thickness",
    "check_recompute",
    "check_required_features",
    "check_shape_validity",
    "check_solid_count",
    "check_target_match",
    "check_volume_removed",
    "check_volume_reconstruction",
    "build_verdict",
    "VERIFIER_VERSION",
]
