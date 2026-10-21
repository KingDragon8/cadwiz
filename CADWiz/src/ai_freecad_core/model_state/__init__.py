# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Live model-state service and its adapter interfaces."""

from .active_document import ActiveDocumentAdapter, ActiveDocumentCapture
from .observers import ModelChangeEvent, ModelChangeKind, ObserverAdapter
from .selection import SelectionAdapter
from .service import (
    ImmediateRefreshScheduler,
    LiveModelStateService,
    ModelStateError,
    ModelStateErrorCode,
    RefreshScheduler,
    SnapshotListener,
    Subscription,
)

__all__ = [
    "ActiveDocumentAdapter",
    "ActiveDocumentCapture",
    "LiveModelStateService",
    "ImmediateRefreshScheduler",
    "ModelStateError",
    "ModelStateErrorCode",
    "ModelChangeEvent",
    "ModelChangeKind",
    "ObserverAdapter",
    "RefreshScheduler",
    "SelectionAdapter",
    "SnapshotListener",
    "Subscription",
]
