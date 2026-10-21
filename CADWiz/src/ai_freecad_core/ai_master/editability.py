# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""The editability standard, shown on every result (Phase 1.3).

    E0  mesh / static            -- triangles, nothing to edit
    E1  valid FreeCAD solid      -- a real B-rep solid, editable only by hand
    E2  parametric native tree   -- Body, Sketches, constraints, features
    E3  named design parameters  -- concepts the founder recognises (a Spreadsheet
                                    or named properties) drive the features
    E4  living design            -- saved, reopened, and one intended feature
                                    changed conversationally without damaging
                                    the others -- VERIFIED BY TEST, never claimed

Mechanical path target: E3 minimum, E4 verified by test. Organic path: E0/E1
allowed, with functional features (holes, mounts, mating faces) native where
needed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum


class EditabilityLevel(IntEnum):
    E0 = 0
    E1 = 1
    E2 = 2
    E3 = 3
    E4 = 4

    @property
    def label(self) -> str:
        return _LABELS[self]

    def display(self) -> str:
        return f"{self.name} — {self.label}"


_LABELS = {
    EditabilityLevel.E0: "mesh or static shape; nothing to edit",
    EditabilityLevel.E1: "valid solid; editable only by hand",
    EditabilityLevel.E2: "native feature tree (sketches, constraints, features)",
    EditabilityLevel.E3: "named design parameters you would recognise drive the features",
    EditabilityLevel.E4: "living design: reopened and changed one feature at a time, verified",
}


@dataclass(slots=True)
class EditabilityEvidence:
    """What the fact layer found. Each flag is a measured fact, not a claim."""

    mesh_only: bool = False
    valid_solid: bool = False
    native_feature_tree: bool = False       # PartDesign Body / Sketches / features present
    named_parameters: int = 0               # Spreadsheet aliases or named properties driving features
    recognisable_parameter_names: bool = False  # names match the Design Contract's parameters
    living_design_verified: bool = False    # the E4 test ran: save, reopen, change one parameter, others intact
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class EditabilityAssessment:
    level: EditabilityLevel
    evidence: tuple[str, ...]
    meets_mechanical_target: bool

    def display(self) -> str:
        return self.level.display()


def assess(evidence: EditabilityEvidence, *, build_path: str = "mechanical") -> EditabilityAssessment:
    lines: list[str] = []
    if evidence.mesh_only or not evidence.valid_solid:
        level = EditabilityLevel.E0
        lines.append("mesh or no valid solid" if evidence.mesh_only else "no valid solid found")
    else:
        level = EditabilityLevel.E1
        lines.append("valid solid")
        if evidence.native_feature_tree:
            level = EditabilityLevel.E2
            lines.append("native feature tree present")
            if evidence.named_parameters > 0 and evidence.recognisable_parameter_names:
                level = EditabilityLevel.E3
                lines.append(f"{evidence.named_parameters} named parameter(s) drive the features")
                if evidence.living_design_verified:
                    level = EditabilityLevel.E4
                    lines.append("living-design test passed: reopened, one parameter changed, others intact")
                else:
                    lines.append("living-design test not run or not passed")
            elif evidence.named_parameters > 0:
                lines.append(f"{evidence.named_parameters} parameter(s), but names do not match the contract")
            else:
                lines.append("no named parameters")
        else:
            lines.append("no native feature tree")
    lines.extend(evidence.notes)
    target = EditabilityLevel.E3 if build_path == "mechanical" else EditabilityLevel.E0
    return EditabilityAssessment(level=level, evidence=tuple(lines), meets_mechanical_target=level >= target)
