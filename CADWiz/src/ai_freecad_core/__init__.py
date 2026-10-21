# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Shared, vendor-independent services and contracts for CADWiz."""

from .contracts import (
    ActiveBodyState,
    DocumentIdentity,
    ModelSnapshot,
    RecomputeState,
    RecomputeStatus,
    SelectedObject,
    SelectionState,
)
from .model_state import LiveModelStateService

# ORDER-2026-10-06-02: from the moment any CADWiz code is imported, an automated run
# cannot reach a paid AI service (see ai/spend_guard.py).
from .ai.spend_guard import install_egress_guard as _install_egress_guard

_install_egress_guard()

__all__ = [
    "ActiveBodyState",
    "DocumentIdentity",
    "LiveModelStateService",
    "ModelSnapshot",
    "RecomputeState",
    "RecomputeStatus",
    "SelectedObject",
    "SelectionState",
]
