# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""The model seam. Provider-specific code lives in `integrations/llm/`, never here."""

from .seam import (
    ModelPort,
    ModelReply,
    ModelRequest,
    ModelUnavailable,
    ToolInvocation,
    ToolRequest,
    ask_model,
    current_model_provider,
    set_model_provider,
    set_wait_pump,
)

__all__ = (
    "ModelPort",
    "ModelReply",
    "ModelRequest",
    "ModelUnavailable",
    "ToolInvocation",
    "ToolRequest",
    "ask_model",
    "current_model_provider",
    "set_model_provider",
    "set_wait_pump",
)
