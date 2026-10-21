# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""The deterministic fact layer (Phase 1.4). CADWiz, not AI.

It REPORTS every measured fact to the master, it NEVER redesigns, it NEVER
overrules subjective aesthetics -- and it REFUSES to certify COMPLETE while any
objective requirement in the Design Contract fails.

The numbers come from FreeCAD (see `integrations.ai_master.freecad_facts`);
this module only holds them, compares them with the contract and says what
passed. Pure Python, so every rule is testable without FreeCAD.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .design_contract import DesignContract, Requirement
from .editability import EditabilityAssessment, EditabilityEvidence, EditabilityLevel, assess
from .units import both


@dataclass(slots=True)
class PrinterProfile:
    name: str = "generic 220 mm printer"
    bed_x_mm: float = 220.0
    bed_y_mm: float = 220.0
    bed_z_mm: float = 250.0
    min_wall_mm: float = 0.8
    max_overhang_deg: float = 45.0


@dataclass(slots=True)
class PrintCheck:
    fits_bed: bool
    thin_walls: bool
    steep_overhangs: bool
    notes: list[str] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return self.fits_bed and not self.thin_walls and not self.steep_overhangs


@dataclass(slots=True)
class FactReport:
    """Everything CADWiz measured about one object/version. Optional fields are
    None when the measurement was not possible -- never guessed."""

    object_name: str
    bbox_mm: tuple[float, float, float] | None = None
    volume_mm3: float | None = None
    area_mm2: float | None = None
    solid_count: int = 0
    valid_solid: bool = False
    mesh_only: bool = False
    holes: list[dict[str, float]] = field(default_factory=list)   # {"diameter_mm": .., "depth_mm": ..}
    min_wall_mm: float | None = None
    min_wall_is_estimate: bool = True
    hollow: bool | None = None
    clearances_mm: list[dict[str, Any]] = field(default_factory=list)
    collisions: list[tuple[str, str]] = field(default_factory=list)
    feature_tree: dict[str, int] = field(default_factory=dict)   # bodies, sketches, features, named_parameters
    parameter_names: list[str] = field(default_factory=list)
    file_integrity_ok: bool = True
    living_design_verified: bool = False
    printer: PrintCheck | None = None
    editability: EditabilityAssessment | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if self.editability is not None:
            data["editability"] = {"level": self.editability.level.name, "evidence": list(self.editability.evidence),
                                   "meets_mechanical_target": self.editability.meets_mechanical_target}
        return data

    def plain_summary(self) -> str:
        """The measurements that matter, in plain words, both unit systems."""
        parts = [f"{self.object_name}:"]
        if self.bbox_mm:
            x, y, z = self.bbox_mm
            parts.append(f"about {both(x)} by {both(y)} by {both(z)}")
        if self.volume_mm3 is not None:
            parts.append(f"volume {self.volume_mm3 / 1000:.1f} cm3")
        parts.append("valid solid" if self.valid_solid else ("mesh only" if self.mesh_only else "NOT a valid solid"))
        if self.hollow is True:
            parts.append("hollow" + (f", wall about {both(self.min_wall_mm)}" + (" (estimate)" if self.min_wall_is_estimate else "") if self.min_wall_mm else ""))
        elif self.hollow is False:
            parts.append("solid throughout")
        if self.holes:
            parts.append(f"{len(self.holes)} hole(s): " + ", ".join(both(h['diameter_mm']) for h in self.holes[:6]))
        if self.collisions:
            parts.append(f"{len(self.collisions)} part(s) collide")
        if self.editability is not None:
            parts.append("editability " + self.editability.display())
        if self.printer is not None:
            parts.append("print: " + ("ready" if self.printer.ready else "; ".join(self.printer.notes) or "not ready"))
        return " ".join(parts[:1]) + " " + "; ".join(parts[1:]) + "."


def assess_editability(facts: FactReport, contract: DesignContract | None) -> EditabilityAssessment:
    names_match = bool(contract) and bool(facts.parameter_names) and any(
        p in facts.parameter_names for p in (contract.parameters if contract else {})
    )
    evidence = EditabilityEvidence(
        mesh_only=facts.mesh_only, valid_solid=facts.valid_solid,
        native_feature_tree=bool(facts.feature_tree.get("bodies") or facts.feature_tree.get("sketches") or facts.feature_tree.get("features")),
        named_parameters=int(facts.feature_tree.get("named_parameters", len(facts.parameter_names))),
        recognisable_parameter_names=names_match, living_design_verified=facts.living_design_verified,
    )
    return assess(evidence, build_path=contract.build_path if contract else "mechanical")


def check_print(facts: FactReport, profile: PrinterProfile) -> PrintCheck:
    notes: list[str] = []
    fits = True
    if facts.bbox_mm:
        x, y, z = facts.bbox_mm
        dims = sorted((x, y), reverse=True)
        bed = sorted((profile.bed_x_mm, profile.bed_y_mm), reverse=True)
        fits = dims[0] <= bed[0] and dims[1] <= bed[1] and z <= profile.bed_z_mm
        if not fits:
            notes.append(f"does not fit the {profile.name} bed ({both(x)} x {both(y)} x {both(z)})")
    else:
        fits = False
        notes.append("size unknown; cannot check the bed")
    thin = facts.min_wall_mm is not None and facts.min_wall_mm < profile.min_wall_mm
    if thin:
        notes.append(f"wall {both(facts.min_wall_mm or 0)} is under the printer's {both(profile.min_wall_mm)} minimum")
    steep = any("overhang" in n.lower() for n in facts.notes)
    if steep:
        notes.append("steep overhangs found")
    return PrintCheck(fits_bed=fits, thin_walls=thin, steep_overhangs=steep, notes=notes)


def measure_metric(facts: FactReport, metric: str) -> float | bool | None:
    """The measured value a requirement's metric names, or None when CADWiz could
    not measure it (reported as such, never guessed)."""
    bbox = facts.bbox_mm
    if metric in ("width_mm", "depth_mm", "height_mm"):
        if not bbox:
            return None
        return {"width_mm": bbox[0], "depth_mm": bbox[1], "height_mm": bbox[2]}[metric]
    if metric in ("base_diameter_mm", "diameter_mm"):
        return max(bbox[0], bbox[1]) if bbox else None
    if metric == "wall_mm" or metric == "min_wall_mm":
        return facts.min_wall_mm
    if metric == "hollow":
        return facts.hollow
    if metric == "volume_mm3":
        return facts.volume_mm3
    if metric == "valid_solid":
        return facts.valid_solid
    if metric == "solid_count":
        return facts.solid_count
    if metric == "hole_count":
        return len(facts.holes)
    if metric == "hole_diameter_mm":
        return facts.holes[0]["diameter_mm"] if facts.holes else None
    if metric == "fits_bed":
        return facts.printer.fits_bed if facts.printer else None
    if metric == "editability_level":
        return int(facts.editability.level) if facts.editability else None
    if metric == "clearance_mm":
        values = [c.get("mm") for c in facts.clearances_mm if c.get("mm") is not None]
        return min(values) if values else None
    if metric == "no_collisions":
        return not facts.collisions
    return None


@dataclass(frozen=True, slots=True)
class RequirementResult:
    name: str
    metric: str
    target: float | bool
    tolerance: float
    measured: float | bool | None
    passed: bool
    note: str

    def plain(self) -> str:
        if self.measured is None:
            return f"{self.name}: could not be measured ({self.note})"
        if isinstance(self.target, bool):
            return f"{self.name}: {'yes' if self.measured else 'no'} (wanted {'yes' if self.target else 'no'}) -- {'PASS' if self.passed else 'FAIL'}"
        if self.metric.endswith("_mm"):
            return f"{self.name}: measured {both(float(self.measured))}, wanted {both(float(self.target))} ± {self.tolerance:g} mm -- {'PASS' if self.passed else 'FAIL'}"
        return f"{self.name}: measured {self.measured}, wanted {self.target} ± {self.tolerance:g} -- {'PASS' if self.passed else 'FAIL'}"


def check_requirement(requirement: Requirement, facts: FactReport) -> RequirementResult:
    measured = measure_metric(facts, requirement.metric)
    if measured is None:
        return RequirementResult(requirement.name, requirement.metric, requirement.target, requirement.tolerance, None, False, "not measurable from this build")
    if isinstance(requirement.target, bool):
        passed = bool(measured) is requirement.target
    elif requirement.metric == "editability_level" or requirement.metric.endswith("_count") or requirement.metric == "min_wall_mm" and requirement.tolerance == 0:
        passed = float(measured) >= float(requirement.target) - requirement.tolerance
    else:
        passed = abs(float(measured) - float(requirement.target)) <= requirement.tolerance + 1e-9
    return RequirementResult(requirement.name, requirement.metric, requirement.target, requirement.tolerance, measured, passed, requirement.note)


@dataclass(frozen=True, slots=True)
class ContractCheck:
    results: tuple[RequirementResult, ...]
    subjective: tuple[str, ...]      # named for the master; never judged here

    @property
    def all_objective_pass(self) -> bool:
        return all(r.passed for r in self.results)

    def failures(self) -> list[RequirementResult]:
        return [r for r in self.results if not r.passed]

    def plain_lines(self) -> list[str]:
        lines = [r.plain() for r in self.results]
        lines.extend(f"{name}: for the master to judge (not measured)" for name in self.subjective)
        return lines


def check_contract(contract: DesignContract, facts: FactReport) -> ContractCheck:
    results = tuple(check_requirement(r, facts) for r in contract.objective_requirements())
    subjective = tuple(r.name for r in contract.requirements if r.kind != "objective")
    return ContractCheck(results=results, subjective=subjective)


@dataclass(frozen=True, slots=True)
class Certification:
    status: str                     # "COMPLETE" or "NOT COMPLETE"
    reasons: tuple[str, ...]

    @property
    def complete(self) -> bool:
        return self.status == "COMPLETE"


def certify(contract: DesignContract, facts: FactReport) -> Certification:
    """COMPLETE only when every objective requirement passes and the build is a
    valid solid with intact files. Subjective requirements are the master's call
    and never block or grant completion here."""
    check = check_contract(contract, facts)
    reasons: list[str] = [r.plain() for r in check.failures()]
    if not facts.file_integrity_ok:
        reasons.append("the saved file failed its integrity check")
    if contract.build_path == "mechanical" and facts.editability is not None and not facts.editability.meets_mechanical_target:
        reasons.append(f"editability is {facts.editability.level.name}; the mechanical path needs E3 or better")
    if not check.results and not facts.valid_solid:
        reasons.append("no objective requirement and no valid solid: nothing to certify")
    if reasons:
        return Certification("NOT COMPLETE", tuple(reasons))
    return Certification("COMPLETE", tuple(r.plain() for r in check.results))


def finish_report(facts: FactReport, contract: DesignContract | None, profile: PrinterProfile | None = None) -> FactReport:
    """Fill the derived fields (editability, print check) from the raw measurements."""
    facts.editability = assess_editability(facts, contract)
    if profile is not None:
        facts.printer = check_print(facts, profile)
    return facts


__all__ = [
    "Certification", "ContractCheck", "EditabilityLevel", "FactReport", "PrintCheck", "PrinterProfile",
    "RequirementResult", "assess_editability", "certify", "check_contract", "check_print", "check_requirement",
    "finish_report", "measure_metric",
]
