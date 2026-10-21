# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Port for reading selected objects from a future CAD adapter."""

from typing import Protocol

from ai_freecad_core.contracts import DocumentIdentity, SelectionState


class SelectionAdapter(Protocol):
    """Interface that normalizes native selection into immutable contracts."""

    def capture(self, document: DocumentIdentity | None) -> SelectionState:
        """Capture selection for the supplied active document context."""
        ...
