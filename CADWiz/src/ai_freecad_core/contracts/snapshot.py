# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Immutable contracts for a consistent point-in-time model snapshot."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class RecomputeState(str, Enum):
    """Known document recompute outcomes without FreeCAD-specific constants."""

    CLEAN = "clean"
    REQUIRED = "required"
    FAILED = "failed"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class DocumentIdentity:
    """Stable identity and user-facing metadata for one model document."""

    document_id: str
    name: str
    label: str
    file_path: str | None = None

    def __post_init__(self) -> None:
        """Require the stable identifier and internal document name."""
        if not self.document_id:
            raise ValueError("document_id must not be empty")
        if not self.name:
            raise ValueError("name must not be empty")


@dataclass(frozen=True, slots=True)
class SelectedObject:
    """One selected object and its ordered native subelement names."""

    object_id: str
    name: str
    label: str
    subelements: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Require a stable object identifier and internal object name."""
        if not self.object_id:
            raise ValueError("object_id must not be empty")
        if not self.name:
            raise ValueError("name must not be empty")


@dataclass(frozen=True, slots=True)
class SelectionState:
    """Ordered selected objects associated with an optional document."""

    document_id: str | None = None
    objects: tuple[SelectedObject, ...] = ()


@dataclass(frozen=True, slots=True)
class ActiveBodyState:
    """Identity of the active Part Design body, when one is active."""

    object_id: str
    name: str
    label: str

    def __post_init__(self) -> None:
        """Require a stable object identifier and internal body name."""
        if not self.object_id:
            raise ValueError("object_id must not be empty")
        if not self.name:
            raise ValueError("name must not be empty")


@dataclass(frozen=True, slots=True)
class RecomputeStatus:
    """Document recompute state and diagnostic messages at capture time."""

    state: RecomputeState = RecomputeState.UNKNOWN
    errors: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ModelSnapshot:
    """Atomic, revisioned view shared by native UI and external adapters.

    The revision belongs to this service and is independent of FreeCAD's undo
    stack. A timezone-aware capture time makes snapshots unambiguous across
    processes and machines.
    """

    revision: int
    captured_at: datetime
    document: DocumentIdentity | None = None
    selection: SelectionState = field(default_factory=SelectionState)
    active_body: ActiveBodyState | None = None
    recompute: RecomputeStatus = field(default_factory=RecomputeStatus)

    def __post_init__(self) -> None:
        """Validate revision and timestamp invariants."""
        if self.revision < 0:
            raise ValueError("revision must be non-negative")
        if self.captured_at.tzinfo is None or self.captured_at.utcoffset() is None:
            raise ValueError("captured_at must be timezone-aware")
        if self.document is None and self.selection.document_id is not None:
            raise ValueError("selection cannot reference a document when none is active")
        if self.document is not None and self.selection.document_id not in (
            None,
            self.document.document_id,
        ):
            raise ValueError("selection document must match the active document")

    def is_stale_against(self, current_revision: int) -> bool:
        """Return whether a newer service revision is known to exist."""
        if current_revision < 0:
            raise ValueError("current_revision must be non-negative")
        return self.revision < current_revision
