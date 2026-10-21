# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Host-neutral contracts for a future native FreeCAD integration adapter."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Protocol, TypeVar

from ai_freecad_core.contracts import DocumentIdentity, RecomputeStatus, SelectionState
from ai_freecad_core.model_state import ModelChangeEvent

T = TypeVar("T")


class NativeErrorCode(str, Enum):
    """Stable error categories translated from native host exceptions."""

    NO_ACTIVE_DOCUMENT = "no_active_document"
    DOCUMENT_CHANGED = "document_changed"
    OBJECT_NOT_FOUND = "object_not_found"
    PROPERTY_UNAVAILABLE = "property_unavailable"
    GUI_THREAD_REQUIRED = "gui_thread_required"
    UNSUPPORTED_CAPABILITY = "unsupported_capability"
    NATIVE_FAILURE = "native_failure"


@dataclass(frozen=True, slots=True)
class NativeAdapterError:
    """Structured, user-safe representation of a native adapter failure."""

    code: NativeErrorCode
    message: str
    native_type: str | None = None
    document_id: str | None = None
    object_id: str | None = None


@dataclass(frozen=True, slots=True)
class PropertyValue:
    """Serializable property extracted from a native object."""

    name: str
    type_name: str
    value: str | int | float | bool | None
    unit: str | None = None
    read_only: bool = False


@dataclass(frozen=True, slots=True)
class NativeObjectState:
    """Minimal stable identity and type information for a document object."""

    object_id: str
    name: str
    label: str
    type_id: str


@dataclass(frozen=True, slots=True)
class DependencyState:
    """Directed dependency between two stable object identities."""

    source_object_id: str
    target_object_id: str
    relation: str


@dataclass(frozen=True, slots=True)
class AdapterCapability:
    """One probed native capability with an optional limitation."""

    name: str
    available: bool
    detail: str = ""


@dataclass(frozen=True, slots=True)
class CompatibilityReport:
    """Runtime versions and probed capabilities reported by the adapter."""

    host_name: str
    host_version: str
    python_version: str
    qt_version: str | None = None
    occ_version: str | None = None
    pyside_version: str | None = None
    architecture: str | None = None
    gui_mode: bool = False
    capabilities: tuple[AdapterCapability, ...] = ()


class NativeEventSubscription(Protocol):
    """Idempotent lifecycle handle for native observer registration."""

    def cancel(self) -> None: ...


class GuiThreadDispatcher(Protocol):
    """Only boundary allowed to schedule GUI-sensitive native adapter work."""

    def dispatch(self, operation: Callable[[], T]) -> T: ...

    def is_gui_thread(self) -> bool: ...


class NativeFreeCADReadAdapter(Protocol):
    """Read-only contract a production FreeCAD adapter must implement."""

    def active_document(self) -> DocumentIdentity | None: ...

    def enumerate_objects(self, document: DocumentIdentity) -> tuple[NativeObjectState, ...]: ...

    def extract_properties(
        self, document: DocumentIdentity, object_id: str
    ) -> tuple[PropertyValue, ...]: ...

    def selection(self, document: DocumentIdentity | None) -> SelectionState: ...

    def recompute_status(self, document: DocumentIdentity | None) -> RecomputeStatus: ...

    def dependencies(self, document: DocumentIdentity) -> tuple[DependencyState, ...]: ...

    def subscribe(
        self, listener: Callable[[ModelChangeEvent], None]
    ) -> NativeEventSubscription: ...

    def compatibility(self) -> CompatibilityReport: ...

    def translate_error(self, error: BaseException) -> NativeAdapterError: ...
