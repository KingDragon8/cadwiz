# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Observer lifecycle contracts; no FreeCAD observer is implemented here."""

from dataclasses import dataclass
from enum import Enum
from typing import Protocol


class ModelChangeKind(str, Enum):
    """Transport-neutral categories that can make a snapshot stale."""

    DOCUMENT = "document"
    SELECTION = "selection"
    RECOMPUTE = "recompute"
    ACTIVE_BODY = "active_body"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ModelChangeEvent:
    """Minimal invalidation event emitted by a future observer adapter."""

    kind: ModelChangeKind
    document_id: str | None = None


class ChangeListener(Protocol):
    """Callable interface receiving normalized model invalidation events."""

    def __call__(self, event: ModelChangeEvent) -> None:
        """Handle an event that may require a new snapshot."""
        ...


class ObserverAdapter(Protocol):
    """Lifecycle boundary for native document and selection observers."""

    def start(self, listener: ChangeListener) -> None:
        """Start forwarding normalized changes to ``listener``."""
        ...

    def stop(self) -> None:
        """Remove native registrations and stop forwarding events."""
        ...
