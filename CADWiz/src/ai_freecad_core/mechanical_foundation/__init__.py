# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Governed application-specific mechanical foundation for the S3 concept."""

from .articulated import (
    ASSEMBLY_BACKEND,
    ASSEMBLY_DEFAULTS,
    JOINT_LIMITS,
    QUALIFICATION_POSES,
    AssemblyPose,
    AssemblyValidation,
    PlanarTransform,
    compile_articulated_program,
    solve_planar_pose,
    validate_assembly_parameters,
)
from .clamp import (
    CLAMP_DEFAULTS,
    ClampValidation,
    compile_clamp_program,
    validate_clamp_parameters,
)
from .hardware import (
    HardwareDefinition,
    PurchaseOption,
    calculate_pivot_stack,
    choose_standard_length,
)
from .indexing import IndexCandidate, qualify_index_candidate

__all__ = [
    "CLAMP_DEFAULTS",
    "ASSEMBLY_BACKEND",
    "ASSEMBLY_DEFAULTS",
    "JOINT_LIMITS",
    "QUALIFICATION_POSES",
    "AssemblyPose",
    "AssemblyValidation",
    "ClampValidation",
    "HardwareDefinition",
    "IndexCandidate",
    "PurchaseOption",
    "PlanarTransform",
    "calculate_pivot_stack",
    "choose_standard_length",
    "compile_clamp_program",
    "compile_articulated_program",
    "qualify_index_candidate",
    "validate_clamp_parameters",
    "solve_planar_pose",
    "validate_assembly_parameters",
]
