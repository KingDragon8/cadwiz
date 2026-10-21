# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Native FreeCAD integration boundary; importing this package does not import FreeCAD."""

from .adapter import FreeCADReadAdapter
from .commands import FreeCADStructuredCommandAdapter
from .diagnosis import capture_diagnostic_snapshot
from .dispatch import FreeCADGuiThreadDispatcher, GuiThreadViolation
from .execution import FreeCADDocumentCopySource, FreeCADTransactionAdapter
from .snapshot import capture_snapshot
from .state import FreeCADActiveDocumentPort, FreeCADModelStateBridge, FreeCADSelectionPort
from .validation import (
    FreeCADGeometryValidator,
    FreeCADMotionEnvelopeValidator,
    FreeCADPresentationSnapshotReader,
    FreeCADRecomputeValidator,
)

__all__ = (
    "FreeCADGuiThreadDispatcher",
    "FreeCADGeometryValidator",
    "FreeCADDocumentCopySource",
    "FreeCADActiveDocumentPort",
    "FreeCADReadAdapter",
    "FreeCADModelStateBridge",
    "FreeCADMotionEnvelopeValidator",
    "FreeCADPresentationSnapshotReader",
    "FreeCADSelectionPort",
    "FreeCADRecomputeValidator",
    "FreeCADStructuredCommandAdapter",
    "FreeCADTransactionAdapter",
    "GuiThreadViolation",
    "capture_snapshot",
)
