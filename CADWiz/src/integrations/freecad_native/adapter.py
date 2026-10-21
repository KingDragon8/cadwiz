# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Thin native FreeCAD read adapter; native objects never leave this module."""

from __future__ import annotations

import platform
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from importlib import import_module
from typing import Any

from ai_freecad_core.contracts import (
    DocumentIdentity,
    RecomputeState,
    RecomputeStatus,
    SelectedObject,
    SelectionState,
)
from ai_freecad_core.model_state import ModelChangeEvent
from ai_freecad_core.native import (
    AdapterCapability,
    CompatibilityReport,
    DependencyState,
    NativeAdapterError,
    NativeErrorCode,
    NativeObjectState,
    PropertyValue,
)


def _app() -> Any:
    return import_module("FreeCAD")


def _gui() -> Any | None:
    try:
        return import_module("FreeCADGui")
    except ImportError:
        return None


def _document_id(document: Any) -> str:
    return f"freecad:{document.Name}"


def _identity(document: Any) -> DocumentIdentity:
    return DocumentIdentity(
        _document_id(document), document.Name, document.Label, document.FileName or None
    )


@dataclass
class _Subscription:
    app: Any
    observer: Any
    gui: Any | None = None
    selection_observer: Any | None = None
    cancelled: bool = False

    def cancel(self) -> None:
        if not self.cancelled:
            self.app.removeDocumentObserver(self.observer)
            if self.gui is not None and self.selection_observer is not None:
                self.gui.Selection.removeObserver(self.selection_observer)
            self.cancelled = True


class _DocumentObserver:
    def __init__(self, listener: Callable[[ModelChangeEvent], None]) -> None:
        self._listener = listener

    def slotChangedObject(self, document_object: Any, _property: str) -> None:
        from ai_freecad_core.model_state import ModelChangeKind

        self._listener(
            ModelChangeEvent(ModelChangeKind.DOCUMENT, f"freecad:{document_object.Document.Name}")
        )

    def slotCreatedObject(self, document_object: Any) -> None:
        self.slotChangedObject(document_object, "")

    def slotDeletedObject(self, document_object: Any) -> None:
        self.slotChangedObject(document_object, "")


class _SelectionObserver:
    def __init__(self, listener: Callable[[ModelChangeEvent], None]) -> None:
        self._listener = listener

    def addSelection(self, document_name: str, *_args: Any) -> None:
        from ai_freecad_core.model_state import ModelChangeKind

        self._listener(ModelChangeEvent(ModelChangeKind.SELECTION, f"freecad:{document_name}"))

    def removeSelection(self, document_name: str, *_args: Any) -> None:
        self.addSelection(document_name)

    def clearSelection(self, document_name: str) -> None:
        self.addSelection(document_name)


class FreeCADReadAdapter:
    """Translate native read state into immutable canonical contracts."""

    def active_document(self) -> DocumentIdentity | None:
        app = _app()
        gui = _gui()
        document = None
        if gui is not None and getattr(app, "GuiUp", False):
            active_gui = gui.activeDocument()
            document = active_gui.Document if active_gui is not None else None
        document = document or app.ActiveDocument
        return _identity(document) if document is not None else None

    def _document(self, identity: DocumentIdentity) -> Any:
        document = _app().getDocument(identity.name)
        if document is None or _document_id(document) != identity.document_id:
            raise LookupError(f"Document is no longer active: {identity.document_id}")
        return document

    def enumerate_objects(self, document: DocumentIdentity) -> tuple[NativeObjectState, ...]:
        native = self._document(document)
        return tuple(
            NativeObjectState(
                f"{document.document_id}:{item.Name}", item.Name, item.Label, item.TypeId
            )
            for item in sorted(native.Objects, key=lambda value: value.Name)
        )

    def extract_properties(
        self, document: DocumentIdentity, object_id: str
    ) -> tuple[PropertyValue, ...]:
        native = self._document(document)
        name = object_id.rsplit(":", 1)[-1]
        item = native.getObject(name)
        if item is None:
            raise LookupError(f"Object not found: {object_id}")
        values: list[PropertyValue] = []
        for property_name in sorted(item.PropertiesList):
            raw = item.getPropertyByName(property_name)
            unit = str(getattr(raw, "Unit", "")) or None
            value = getattr(raw, "Value", raw)
            if not isinstance(value, (str, int, float, bool, type(None))):
                value = str(value)
            statuses = item.getPropertyStatus(property_name)
            values.append(
                PropertyValue(
                    property_name,
                    item.getTypeIdOfProperty(property_name),
                    value,
                    unit,
                    "ReadOnly" in statuses,
                )
            )
        return tuple(values)

    def selection(self, document: DocumentIdentity | None) -> SelectionState:
        gui = _gui()
        if gui is None or not getattr(_app(), "GuiUp", False):
            return SelectionState(document.document_id if document else None)
        selected = []
        for item in gui.Selection.getSelectionEx():
            native = item.Object
            selected.append(
                SelectedObject(
                    f"freecad:{native.Document.Name}:{native.Name}",
                    native.Name,
                    native.Label,
                    tuple(item.SubElementNames),
                )
            )
        return SelectionState(document.document_id if document else None, tuple(selected))

    def recompute_status(self, document: DocumentIdentity | None) -> RecomputeStatus:
        if document is None:
            return RecomputeStatus()
        native = self._document(document)
        errors = tuple(
            f"{item.Name}: {state}"
            for item in sorted(native.Objects, key=lambda value: value.Name)
            for state in item.State
            if state not in {"Touched", "Up-to-date"}
        )
        touched = any("Touched" in item.State for item in native.Objects)
        state = (
            RecomputeState.FAILED
            if errors
            else RecomputeState.REQUIRED
            if touched
            else RecomputeState.CLEAN
        )
        return RecomputeStatus(state, errors)

    def dependencies(self, document: DocumentIdentity) -> tuple[DependencyState, ...]:
        native = self._document(document)
        edges = {(item.Name, target.Name) for item in native.Objects for target in item.OutList}
        return tuple(
            DependencyState(
                f"{document.document_id}:{source}",
                f"{document.document_id}:{target}",
                "out_list",
            )
            for source, target in sorted(edges)
        )

    def subscribe(self, listener: Callable[[ModelChangeEvent], None]) -> _Subscription:
        app = _app()
        observer = _DocumentObserver(listener)
        app.addDocumentObserver(observer)
        gui = _gui()
        selection_observer = None
        if gui is not None and getattr(app, "GuiUp", False):
            selection_observer = _SelectionObserver(listener)
            gui.Selection.addObserver(selection_observer)
        return _Subscription(app, observer, gui, selection_observer)

    def compatibility(self) -> CompatibilityReport:
        app = _app()
        version = app.Version()
        qt_version = None
        pyside_version = None
        occ_version = None
        part_available = False
        with suppress(ImportError):
            qt_version = str(import_module("PySide.QtCore").qVersion())
            pyside_version = str(getattr(import_module("PySide"), "__version__", "")) or None
        with suppress(ImportError):
            part = import_module("Part")
            part_available = True
            occ_version = str(getattr(part, "OCC_VERSION", "")) or None
        capabilities = tuple(
            AdapterCapability(name, available)
            for name, available in sorted(
                {
                    "document_observer": hasattr(app, "addDocumentObserver"),
                    "gui": _gui() is not None and bool(getattr(app, "GuiUp", False)),
                    "property_status": hasattr(app.DocumentObject, "getPropertyStatus"),
                    "part": part_available,
                    "dependencies": hasattr(app.DocumentObject, "OutList"),
                    "save_copy": hasattr(app.Document, "saveCopy"),
                    "transactions": all(
                        hasattr(app.Document, name)
                        for name in ("openTransaction", "commitTransaction", "abortTransaction")
                    ),
                }.items()
            )
        )
        return CompatibilityReport(
            "FreeCAD",
            ".".join(version[:3]),
            platform.python_version(),
            qt_version=qt_version,
            occ_version=occ_version,
            pyside_version=pyside_version,
            architecture=platform.machine(),
            gui_mode=bool(getattr(app, "GuiUp", False)),
            capabilities=capabilities,
        )

    def translate_error(self, error: BaseException) -> NativeAdapterError:
        code = (
            NativeErrorCode.OBJECT_NOT_FOUND
            if isinstance(error, LookupError)
            else NativeErrorCode.NATIVE_FAILURE
        )
        return NativeAdapterError(code, str(error), type(error).__name__)
