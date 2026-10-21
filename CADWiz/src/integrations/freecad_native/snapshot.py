# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Serialized canonical snapshot capture composed from the native read adapter."""

from datetime import UTC, datetime
from threading import RLock

from ai_freecad_core.contracts import ModelSnapshot

from .adapter import FreeCADReadAdapter

_CAPTURE_LOCK = RLock()


def capture_snapshot(adapter: FreeCADReadAdapter, revision: int = 1) -> ModelSnapshot:
    """Capture one coherent active-document snapshot without retaining native objects."""
    with _CAPTURE_LOCK:
        document = adapter.active_document()
        selection = adapter.selection(document)
        recompute = adapter.recompute_status(document)
        if adapter.active_document() != document:
            raise RuntimeError("Active document changed during snapshot capture")
        return ModelSnapshot(revision, datetime.now(UTC), document, selection, recompute=recompute)
