# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Read-only native evidence capture for FixMeForthman."""

from __future__ import annotations

from importlib import import_module
from uuid import uuid4

from ai_freecad_core.diagnosis import DiagnosticObjectState, DiagnosticSnapshot


def capture_diagnostic_snapshot() -> DiagnosticSnapshot | None:
    """Capture native facts without recompute, transaction, save, or mutation."""
    app = import_module("FreeCAD")
    document = app.ActiveDocument
    if document is None:
        return None
    gui = import_module("FreeCADGui") if getattr(app, "GuiUp", False) else None
    selected = (
        {item.Object.Name for item in gui.Selection.getSelectionEx()} if gui is not None else set()
    )
    objects = []
    for order, item in enumerate(document.Objects):
        shape = getattr(item, "Shape", None)
        has_shape_property = hasattr(item, "Shape")
        shape_available = not has_shape_property or (shape is not None and not shape.isNull())
        shape_valid = None
        solid_count = None
        if shape is not None and not shape.isNull():
            try:
                shape_valid = bool(shape.isValid())
                solid_count = len(shape.Solids)
            except Exception:
                shape_valid = None
        states = tuple(str(value) for value in getattr(item, "State", ()))
        # FreeCAD mixes presentation flags such as ``Expanded`` into State.
        # Treating every non-Touched value as an error made any expanded,
        # perfectly healthy object look like the first failed feature.
        failure_words = (
            "error",
            "invalid",
            "failed",
            "exception",
            "missing",
            "broken",
            "over-constrained",
        )
        error_text = " ".join(
            value
            for value in states
            if any(word in value.casefold() for word in failure_words)
        )
        scenario = getattr(item, "FailureScenario", "")
        if scenario:
            error_text = f"{error_text} {scenario}".strip()
        if item.TypeId.startswith("Mesh::") and not error_text:
            error_text = "mesh issue: imported mesh has no parametric feature history"
        objects.append(
            DiagnosticObjectState(
                f"freecad:{document.Name}:{item.Name}",
                item.Name,
                item.Label,
                item.TypeId,
                order,
                tuple(f"freecad:{document.Name}:{value.Name}" for value in item.OutList),
                states,
                shape_available,
                shape_valid,
                solid_count,
                error_text,
            )
        )
    version = ".".join(str(value) for value in app.Version()[:3])
    return DiagnosticSnapshot(
        f"fixme-{uuid4().hex}",
        f"freecad:{document.Name}",
        document.Label,
        version,
        tuple(objects),
        tuple(f"freecad:{document.Name}:{name}" for name in sorted(selected)),
    )
