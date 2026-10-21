# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""The Design Contract (ORDER-2026-10-11-03 Phase 1.1).

Per project, persisted, versioned. Created and updated by the MASTER; stored,
versioned and CHECKED by CADWiz. CADWiz never authors intent in it: every field
that says what the founder wants comes from the master's reply, and the only
thing CADWiz adds is the check result (`check_requirements`) and the version
number. The founder's words are kept verbatim.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .units import Quantity, UnitError, parse_quantity

BUILD_PATHS = ("mechanical", "organic")

#: Metrics the fact layer can measure and a requirement can name. Objective by
#: construction: each maps to a number or a yes/no the fact layer reports.
OBJECTIVE_METRICS: frozenset[str] = frozenset(
    {
        "width_mm", "depth_mm", "height_mm", "base_diameter_mm", "diameter_mm", "wall_mm", "hollow",
        "volume_mm3", "valid_solid", "solid_count", "hole_count", "hole_diameter_mm", "fits_bed",
        "min_wall_mm", "editability_level", "clearance_mm", "no_collisions",
    }
)


@dataclass(frozen=True, slots=True)
class Parameter:
    """A named design parameter the founder would recognise ('base_diameter')."""

    name: str
    quantity: Quantity
    label: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "label": self.label or self.name.replace("_", " "), **self.quantity.to_dict()}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Parameter":
        return cls(str(data["name"]), Quantity.from_dict(data), str(data.get("label", "")))


@dataclass(frozen=True, slots=True)
class Requirement:
    """One acceptance requirement with a tolerance. `kind` is 'objective' (the
    fact layer measures it) or 'subjective' (the master judges it; the fact layer
    never overrules aesthetics)."""

    name: str
    metric: str
    target: float | bool
    tolerance: float = 0.0
    unit: str = "mm"
    kind: str = "objective"
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Requirement":
        return cls(**{k: data[k] for k in ("name", "metric", "target", "tolerance", "unit", "kind", "note") if k in data})


@dataclass(slots=True)
class DesignContract:
    project: str
    object_name: str
    intent_founder_words: str                 # verbatim, never summarised away
    master_summary: str = ""                  # the master's own summary
    parameters: dict[str, Parameter] = field(default_factory=dict)
    features: list[str] = field(default_factory=list)          # semantic features ("hollow shell", "4 mounting holes")
    relationships: list[str] = field(default_factory=list)     # "clearance 0.20 mm between mating faces"
    requirements: list[Requirement] = field(default_factory=list)
    editability_commitments: list[str] = field(default_factory=list)  # parameter names that must stay named and editable
    build_path: str = "mechanical"
    assumptions: list[str] = field(default_factory=list)       # addendum 4: stated, not asked
    version: int = 1
    authored_by: str = "master"
    updated_utc: str = ""

    def __post_init__(self) -> None:
        if self.build_path not in BUILD_PATHS:
            raise ValueError(f"build_path must be one of {BUILD_PATHS}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "project": self.project, "object_name": self.object_name,
            "intent_founder_words": self.intent_founder_words, "master_summary": self.master_summary,
            "parameters": [p.to_dict() for p in self.parameters.values()],
            "features": list(self.features), "relationships": list(self.relationships),
            "requirements": [r.to_dict() for r in self.requirements],
            "editability_commitments": list(self.editability_commitments),
            "build_path": self.build_path, "assumptions": list(self.assumptions),
            "version": self.version, "authored_by": self.authored_by, "updated_utc": self.updated_utc,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DesignContract":
        params = {p["name"]: Parameter.from_dict(p) for p in data.get("parameters", [])}
        return cls(
            project=str(data["project"]), object_name=str(data["object_name"]),
            intent_founder_words=str(data.get("intent_founder_words", "")), master_summary=str(data.get("master_summary", "")),
            parameters=params, features=list(data.get("features", [])), relationships=list(data.get("relationships", [])),
            requirements=[Requirement.from_dict(r) for r in data.get("requirements", [])],
            editability_commitments=list(data.get("editability_commitments", [])),
            build_path=str(data.get("build_path", "mechanical")), assumptions=list(data.get("assumptions", [])),
            version=int(data.get("version", 1)), authored_by=str(data.get("authored_by", "master")),
            updated_utc=str(data.get("updated_utc", "")),
        )

    def objective_requirements(self) -> list[Requirement]:
        return [r for r in self.requirements if r.kind == "objective"]

    def parameter_line(self) -> str:
        """'base diameter 2 in (50.8 mm); height 6 in (152.4 mm)' -- for the VCS."""
        return "; ".join(f"{p.label or p.name.replace('_', ' ')} {p.quantity.display()}" for p in self.parameters.values())

    def assumptions_line(self) -> str:
        """Addendum 4: one line, stated instead of asked."""
        return "; ".join(a.strip().rstrip(".") for a in self.assumptions if a.strip())


class ContractStore:
    """CADWiz's half: store, version and reload. Never changes intent."""

    def __init__(self, folder: str | Path) -> None:
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)

    def _path(self, version: int) -> Path:
        return self.folder / f"contract.v{version}.json"

    def save(self, contract: DesignContract) -> Path:
        """Store as the next version. The master authored it; CADWiz stamps the
        version and time and keeps every earlier version."""
        latest = self.latest_version()
        contract.version = latest + 1
        contract.updated_utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        path = self._path(contract.version)
        path.write_text(json.dumps(contract.to_dict(), indent=2), encoding="utf-8")
        (self.folder / "contract.json").write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        return path

    def latest_version(self) -> int:
        versions = [int(p.stem.split(".v")[1]) for p in self.folder.glob("contract.v*.json")]
        return max(versions, default=0)

    def load(self, version: int | None = None) -> DesignContract | None:
        path = self._path(version) if version else self.folder / "contract.json"
        if not path.exists():
            return None
        return DesignContract.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def history(self) -> list[DesignContract]:
        return [c for v in range(1, self.latest_version() + 1) if (c := self.load(v)) is not None]


def update_contract(project: Any, object_name: str, args: dict[str, Any], founder_words: str) -> "DesignContract":
    """Merge new sizes, requirements and notes into the project's design contract and
    save it as a new version. Shared by the AI-master loop and the Claude plug-in's
    design_record tool (moved here from loop.py, ORDER-2026-10-21-01, so the plug-in
    does not need the loop)."""
    existing = project.contract()
    params: dict[str, Parameter] = dict(existing.parameters) if existing else {}
    for name, value in dict(args.get("parameters") or {}).items():
        try:
            quantity = parse_quantity(str(value)) if not isinstance(value, dict) else parse_quantity(f"{value.get('value')} {value.get('unit', 'mm')}")
        except UnitError:
            continue
        params[str(name)] = Parameter(str(name), quantity, str(name).replace("_", " "))
    requirements = [Requirement.from_dict(r) for r in (args.get("requirements") or []) if isinstance(r, dict) and {"name", "metric", "target"} <= set(r)] or (existing.requirements if existing else [])
    contract = DesignContract(
        project=project.name, object_name=object_name,
        intent_founder_words=founder_words if not existing else (existing.intent_founder_words + "\n" + founder_words),
        master_summary=str(args.get("master_summary") or (existing.master_summary if existing else "")),
        parameters=params,
        features=list(args.get("features") or (existing.features if existing else [])),
        relationships=list(args.get("relationships") or (existing.relationships if existing else [])),
        requirements=requirements,
        editability_commitments=list(args.get("editability_commitments") or (existing.editability_commitments if existing else [])),
        build_path=str(args.get("build_path") or (existing.build_path if existing else "mechanical")),
        assumptions=list(args.get("assumptions") or (existing.assumptions if existing else [])),
    )
    project.contracts.save(contract)
    return contract

