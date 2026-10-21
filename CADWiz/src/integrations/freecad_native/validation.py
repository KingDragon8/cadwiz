# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Read-only FreeCAD validators that emit immutable canonical evidence."""

from __future__ import annotations

from collections.abc import Callable
from importlib import import_module
from typing import Any

from ai_freecad_core.improvement import (
    GeometryFingerprint,
    PresentationSnapshot,
    PresentedObject,
)
from ai_freecad_core.validation.contracts import (
    EvidenceBinding,
    FindingSeverity,
    StageValidationReport,
    ValidationEvidence,
    ValidationFinding,
    ValidationOutcome,
    ValidationStage,
)

from .dispatch import FreeCADGuiThreadDispatcher


class _FreeCADValidator:
    def __init__(
        self,
        document_id: str,
        dispatcher: FreeCADGuiThreadDispatcher | None = None,
        app_provider: Callable[[], Any] | None = None,
    ) -> None:
        self._document_id = document_id
        self._dispatcher = dispatcher or FreeCADGuiThreadDispatcher()
        self._app_provider = app_provider or (lambda: import_module("FreeCAD"))

    def _document(self) -> Any:
        document = self._app_provider().getDocument(self._document_id.removeprefix("freecad:"))
        if document is None:
            raise LookupError(f"Document not found: {self._document_id}")
        return document


class FreeCADRecomputeValidator(_FreeCADValidator):
    """Observe recompute state without triggering recompute or mutation."""

    stage = ValidationStage.RECOMPUTE

    def validate(self, binding: EvidenceBinding) -> StageValidationReport:
        return self._dispatcher.dispatch(lambda: self._validate(binding))

    def _validate(self, binding: EvidenceBinding) -> StageValidationReport:
        evidence: list[ValidationEvidence] = []
        findings: list[ValidationFinding] = []
        for item in sorted(self._document().Objects, key=lambda value: value.Name):
            states = tuple(str(value) for value in item.State)
            object_id = f"{self._document_id}:{item.Name}"
            evidence_id = f"recompute:{item.Name}"
            evidence.append(
                ValidationEvidence(
                    evidence_id,
                    "FreeCAD.DocumentObject.State",
                    ",".join(states),
                    source_object_ids=(object_id,),
                )
            )
            errors = tuple(value for value in states if value not in {"Touched", "Up-to-date"})
            if errors:
                findings.append(
                    ValidationFinding(
                        "native_recompute_error",
                        f"{item.Name}: {', '.join(errors)}",
                        FindingSeverity.ERROR,
                        (evidence_id,),
                        object_ids=(object_id,),
                    )
                )
            elif "Touched" in states:
                findings.append(
                    ValidationFinding(
                        "recompute_required",
                        f"{item.Name} requires recompute",
                        FindingSeverity.WARNING,
                        (evidence_id,),
                        object_ids=(object_id,),
                    )
                )
        outcome = (
            ValidationOutcome.FAILED
            if any(item.severity is FindingSeverity.ERROR for item in findings)
            else ValidationOutcome.INCONCLUSIVE
            if findings
            else ValidationOutcome.PASSED
        )
        return StageValidationReport(self.stage, outcome, binding, tuple(findings), tuple(evidence))


class FreeCADGeometryValidator(_FreeCADValidator):
    """Check native shape validity and record topology and dimensional evidence."""

    stage = ValidationStage.GEOMETRY

    def validate(self, binding: EvidenceBinding) -> StageValidationReport:
        return self._dispatcher.dispatch(lambda: self._validate(binding))

    def _validate(self, binding: EvidenceBinding) -> StageValidationReport:
        evidence: list[ValidationEvidence] = []
        findings: list[ValidationFinding] = []
        shaped = 0
        for item in sorted(self._document().Objects, key=lambda value: value.Name):
            if not hasattr(item, "Shape"):
                continue
            shape = item.Shape
            shaped += 1
            object_id = f"{self._document_id}:{item.Name}"
            valid = not shape.isNull() and bool(shape.isValid())
            validity_id = f"shape-valid:{item.Name}"
            evidence.append(
                ValidationEvidence(
                    validity_id,
                    "OpenCascade.Shape.isValid",
                    str(valid).lower(),
                    source_object_ids=(object_id,),
                )
            )
            topology = (
                f"solids={len(shape.Solids)},faces={len(shape.Faces)},"
                f"edges={len(shape.Edges)},vertices={len(shape.Vertexes)}"
            )
            evidence.append(
                ValidationEvidence(
                    f"topology:{item.Name}",
                    "OpenCascade topology counts",
                    topology,
                    source_object_ids=(object_id,),
                )
            )
            box = shape.BoundBox
            evidence.extend(
                ValidationEvidence(
                    f"bounds-{axis}:{item.Name}",
                    "OpenCascade.BoundBox",
                    str(float(getattr(box, f"{axis}Length"))),
                    "mm",
                    (object_id,),
                )
                for axis in ("X", "Y", "Z")
            )
            if not valid:
                findings.append(
                    ValidationFinding(
                        "invalid_native_shape",
                        f"{item.Name} has a null or invalid shape",
                        FindingSeverity.ERROR,
                        (validity_id,),
                        object_ids=(object_id,),
                    )
                )
        if findings:
            outcome = ValidationOutcome.FAILED
        elif shaped:
            outcome = ValidationOutcome.PASSED
        else:
            outcome = ValidationOutcome.INCONCLUSIVE
        limitations = () if shaped else ("No shape-bearing objects were available",)
        return StageValidationReport(
            self.stage, outcome, binding, tuple(findings), tuple(evidence), limitations
        )


class FreeCADPresentationSnapshotReader(_FreeCADValidator):
    """Read stable shape and visibility evidence from a GUI document."""

    _temporary_tokens = ("tool", "construction", "reference", "temporary", "cutaway")

    def read(
        self,
        *,
        camera_fitted: bool,
        ai_panel_open: bool,
        screenshot_path: str | None,
    ) -> PresentationSnapshot:
        return self._dispatcher.dispatch(
            lambda: self._read(camera_fitted, ai_panel_open, screenshot_path)
        )

    def _read(
        self, camera_fitted: bool, ai_panel_open: bool, screenshot_path: str | None
    ) -> PresentationSnapshot:
        import hashlib

        objects = []
        for item in sorted(self._document().Objects, key=lambda value: value.Name):
            if not hasattr(item, "Shape"):
                continue
            shape = item.Shape
            nonempty = not shape.isNull()
            label = str(item.Label)
            folded = f"{item.Name} {label}".casefold()
            role = (
                "temporary"
                if any(token in folded for token in self._temporary_tokens)
                else "result"
            )
            visible = bool(getattr(getattr(item, "ViewObject", None), "Visibility", False))
            fingerprint = None
            object_id = f"{self._document_id}:{item.Name}"
            if nonempty:
                box = shape.BoundBox
                topology = (
                    len(shape.Solids),
                    len(shape.Faces),
                    len(shape.Edges),
                    len(shape.Vertexes),
                )
                bounds = (float(box.XLength), float(box.YLength), float(box.ZLength))
                raw = "|".join(
                    (
                        f"{float(shape.Volume):.9f}",
                        *(f"{value:.9f}" for value in bounds),
                        *(str(value) for value in topology),
                    )
                )
                fingerprint = GeometryFingerprint(
                    object_id,
                    float(shape.Volume),
                    bounds,
                    topology,
                    hashlib.sha256(raw.encode("ascii")).hexdigest(),
                )
            objects.append(
                PresentedObject(
                    object_id,
                    label,
                    role,
                    visible,
                    nonempty,
                    fingerprint,
                )
            )
        return PresentationSnapshot(
            self._document_id,
            tuple(objects),
            camera_fitted,
            ai_panel_open,
            screenshot_path,
        )


class FreeCADMotionEnvelopeValidator(_FreeCADValidator):
    """Sample translated shape copies without mutating the live FreeCAD document."""

    stage = ValidationStage.ENGINEERING

    def __init__(
        self,
        document_id: str,
        moving_object_name: str,
        obstacle_object_names: tuple[str, ...],
        axial_travel_mm: float,
        minimum_clearance_mm: float,
        sample_count: int = 19,
        dispatcher: FreeCADGuiThreadDispatcher | None = None,
        app_provider: Callable[[], Any] | None = None,
    ) -> None:
        super().__init__(document_id, dispatcher, app_provider)
        if axial_travel_mm <= 0 or minimum_clearance_mm < 0:
            raise ValueError("motion travel must be positive and clearance non-negative")
        if not obstacle_object_names or not 2 <= sample_count <= 1001:
            raise ValueError("motion validation requires obstacles and 2..1001 samples")
        self._moving_name = moving_object_name
        self._obstacle_names = obstacle_object_names
        self._travel = axial_travel_mm
        self._minimum_clearance = minimum_clearance_mm
        self._sample_count = sample_count

    def validate(self, binding: EvidenceBinding) -> StageValidationReport:
        return self._dispatcher.dispatch(lambda: self._validate(binding))

    def _validate(self, binding: EvidenceBinding) -> StageValidationReport:
        document = self._document()
        moving = document.getObject(self._moving_name)
        obstacles = tuple(document.getObject(name) for name in self._obstacle_names)
        if (
            moving is None
            or not hasattr(moving, "Shape")
            or any(item is None for item in obstacles)
        ):
            raise LookupError("motion object or obstacle was not found")
        app = self._app_provider()
        evidence: list[ValidationEvidence] = []
        findings: list[ValidationFinding] = []
        for index in range(self._sample_count):
            position = self._travel * index / (self._sample_count - 1)
            candidate = moving.Shape.copy()
            candidate.translate(app.Vector(0.0, 0.0, position))
            collision = sum(candidate.common(item.Shape).Volume for item in obstacles)
            clearance = min(candidate.distToShape(item.Shape)[0] for item in obstacles)
            collision_id = f"motion-collision:{index}"
            clearance_id = f"motion-clearance:{index}"
            evidence.extend(
                (
                    ValidationEvidence(
                        collision_id,
                        "OpenCascade.Shape.common.Volume",
                        str(float(collision)),
                        "mm3",
                    ),
                    ValidationEvidence(
                        clearance_id,
                        "OpenCascade.Shape.distToShape",
                        str(float(clearance)),
                        "mm",
                    ),
                )
            )
            if collision > 1e-6:
                findings.append(
                    ValidationFinding(
                        "motion_collision",
                        f"Collision at axial position {position:g} mm",
                        FindingSeverity.ERROR,
                        (collision_id,),
                    )
                )
            if clearance + 1e-6 < self._minimum_clearance:
                findings.append(
                    ValidationFinding(
                        "motion_clearance",
                        f"Clearance below {self._minimum_clearance:g} mm at {position:g} mm",
                        FindingSeverity.ERROR,
                        (clearance_id,),
                    )
                )
        outcome = ValidationOutcome.FAILED if findings else ValidationOutcome.PASSED
        return StageValidationReport(
            self.stage,
            outcome,
            binding,
            tuple(findings),
            tuple(evidence),
        )
