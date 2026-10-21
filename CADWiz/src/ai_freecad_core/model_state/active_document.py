# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Port for reading active-document state from a future CAD adapter."""

from dataclasses import dataclass, field
from typing import Protocol

from ai_freecad_core.contracts import (
    ActiveBodyState,
    DocumentIdentity,
    RecomputeStatus,
)


@dataclass(frozen=True, slots=True)
class ActiveDocumentCapture:
    """Related active-document values captured consistently by one adapter call."""

    document: DocumentIdentity | None = None
    active_body: ActiveBodyState | None = None
    recompute: RecomputeStatus = field(default_factory=RecomputeStatus)


class ActiveDocumentAdapter(Protocol):
    """Interface that isolates native active-document APIs from core services."""

    def capture(self) -> ActiveDocumentCapture:
        """Return the current document, body, and recompute state atomically."""
        ...
