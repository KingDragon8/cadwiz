# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Host-neutral Visual Communications Screen contracts and draft lifecycle."""

from .contracts import (
    NormalizedPath,
    NormalizedPoint,
    NormalizedRegion,
    VisualActionResult,
    VisualCapability,
    VisualCommunication,
    VisualMark,
    VisualMarkAuthor,
    VisualMarkKind,
    VisualMarkSet,
    VisualMarkState,
    VisualSourceAnchor,
)
from .dialogue import (
    ConceptCorrection,
    ConceptReview,
    ConceptReviewState,
    VisualDraft,
    VisualUnderstanding,
)

__all__ = [
    "NormalizedPath",
    "NormalizedPoint",
    "NormalizedRegion",
    "ConceptCorrection",
    "ConceptReview",
    "ConceptReviewState",
    "VisualActionResult",
    "VisualCapability",
    "VisualCommunication",
    "VisualDraft",
    "VisualMark",
    "VisualMarkAuthor",
    "VisualMarkKind",
    "VisualMarkSet",
    "VisualMarkState",
    "VisualSourceAnchor",
    "VisualUnderstanding",
]
