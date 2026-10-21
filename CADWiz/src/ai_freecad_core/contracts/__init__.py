# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Public immutable contracts used across CADWiz components."""

from .snapshot import (
    ActiveBodyState,
    DocumentIdentity,
    ModelSnapshot,
    RecomputeState,
    RecomputeStatus,
    SelectedObject,
    SelectionState,
)

__all__ = [
    "ActiveBodyState",
    "DocumentIdentity",
    "ModelSnapshot",
    "RecomputeState",
    "RecomputeStatus",
    "SelectedObject",
    "SelectionState",
]
