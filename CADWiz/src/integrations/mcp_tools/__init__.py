# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""The product's connection to the vendored FreeCAD tool layer."""

from .bridge import build_in_process_bridge, gui_is_up, running_inside_freecad
from .invoker import (
    DocumentRequired,
    ProhibitedOperation,
    ToolExecutionFailed,
    ToolInvoker,
    ToolNotFound,
    ToolResult,
    is_mutating,
)
from .macro_guard import GUARDED_TOOLS, MACRO_REVIEW_FLAG, is_guarded
from .verification import RenderVerification, verify_after_mutation

__all__ = (
    "CommandOutcome",
    "DocumentRequired",
    "GUARDED_TOOLS",
    "MACRO_REVIEW_FLAG",
    "ProhibitedOperation",
    "RenderVerification",
    "ToolCommandService",
    "ToolExecutionFailed",
    "ToolInvoker",
    "ToolNotFound",
    "ToolResult",
    "build_in_process_bridge",
    "gui_is_up",
    "is_guarded",
    "is_mutating",
    "running_inside_freecad",
    "verify_after_mutation",
)


def __getattr__(name: str):
    # ToolCommandService (and the model routing it brings with it) loads only when
    # asked for: the Claude plug-in drives FreeCAD through this package without ever
    # needing it (ORDER-2026-10-21-01, the open-source tree).
    if name in ("CommandOutcome", "ToolCommandService"):
        from . import service

        return getattr(service, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
