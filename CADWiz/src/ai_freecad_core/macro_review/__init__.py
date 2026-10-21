# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Prohibited-operations review for model-generated Python.

Domain-neutral: it reviews text and returns a verdict. It does not know what
FreeCAD is, which tool asked, or how a refusal is reported. Those belong to the
integration that enforces it.
"""

from .contracts import Finding, MacroReview, ReviewOutcome
from .reviewer import (
    ALLOWED_IMPORTS,
    PROHIBITED_ATTRIBUTES,
    PROHIBITED_CALLS,
    review_source,
)

__all__ = [
    "ALLOWED_IMPORTS",
    "Finding",
    "MacroReview",
    "PROHIBITED_ATTRIBUTES",
    "PROHIBITED_CALLS",
    "ReviewOutcome",
    "review_source",
]
