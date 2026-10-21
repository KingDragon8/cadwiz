# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Deterministic draft-mark lifecycle and request-understanding helpers."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Any
from uuid import uuid4

from .contracts import (
    NormalizedPoint,
    NormalizedRegion,
    VisualMark,
    VisualMarkKind,
    VisualMarkSet,
    VisualSourceAnchor,
)


@dataclass(frozen=True, slots=True)
class VisualUnderstanding:
    target: str = ""
    change: str = ""
    amount_or_direction: str = ""
    constraint_or_reason: str = ""
    approved: bool = False

    def corrected(self, **changes: Any) -> "VisualUnderstanding":
        allowed = set(self.__dataclass_fields__)
        if set(changes) - allowed:
            raise ValueError("unknown understanding field")
        return replace(self, **changes)


class ConceptReviewState(str, Enum):
    DRAFT = "draft"
    IN_REVIEW = "in_review"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    SKIPPED_DETERMINISTIC = "skipped_deterministic"


@dataclass(frozen=True, slots=True)
class ConceptCorrection:
    id: str
    verbatim: str
    understanding: VisualUnderstanding
    mark_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.id.strip() or not self.verbatim.strip():
            raise ValueError("concept correction id and verbatim text must be nonblank")
        if len(self.mark_ids) != len(set(self.mark_ids)):
            raise ValueError("concept correction mark ids must be unique")


@dataclass(frozen=True, slots=True)
class ConceptReview:
    """Governed concept-first record; it cannot execute or mutate CAD."""

    id: str
    source: VisualSourceAnchor
    state: ConceptReviewState = ConceptReviewState.DRAFT
    corrections: tuple[ConceptCorrection, ...] = ()
    decision_reason: str = ""

    @staticmethod
    def is_required(
        *,
        topology_uncertain: bool = False,
        orientation_critical: bool = False,
        sketch_supplied: bool = False,
        multiple_arrangements: bool = False,
        deterministic: bool = False,
    ) -> bool:
        return not deterministic and any(
            (topology_uncertain, orientation_critical, sketch_supplied, multiple_arrangements)
        )

    @property
    def cad_build_authorized(self) -> bool:
        return self.state in {
            ConceptReviewState.CONFIRMED,
            ConceptReviewState.SKIPPED_DETERMINISTIC,
        }

    def begin(self) -> "ConceptReview":
        if self.state is not ConceptReviewState.DRAFT:
            raise ValueError("only a draft concept review can begin")
        return replace(self, state=ConceptReviewState.IN_REVIEW)

    def record(self, correction: ConceptCorrection) -> "ConceptReview":
        if self.state is not ConceptReviewState.IN_REVIEW:
            raise ValueError("corrections require an in-review concept")
        if any(item.id == correction.id for item in self.corrections):
            raise ValueError("concept correction ids must be unique")
        return replace(self, corrections=(*self.corrections, correction))

    def confirm(self, reason: str = "user confirmed concept") -> "ConceptReview":
        if self.state is not ConceptReviewState.IN_REVIEW:
            raise ValueError("only an in-review concept can be confirmed")
        return replace(self, state=ConceptReviewState.CONFIRMED, decision_reason=reason)

    def reject(self, reason: str) -> "ConceptReview":
        if self.state is not ConceptReviewState.IN_REVIEW or not reason.strip():
            raise ValueError("an in-review concept and reason are required")
        return replace(self, state=ConceptReviewState.REJECTED, decision_reason=reason)

    def skip_deterministic(self, reason: str) -> "ConceptReview":
        if self.state is not ConceptReviewState.DRAFT or not reason.strip():
            raise ValueError("a draft concept and deterministic reason are required")
        return replace(
            self,
            state=ConceptReviewState.SKIPPED_DETERMINISTIC,
            decision_reason=reason,
        )


class VisualDraft:
    """One source-scoped draft with exact undo snapshots and stable numbering."""

    def __init__(self, source: VisualSourceAnchor) -> None:
        self.source = source
        self._marks: list[VisualMark] = []
        self._undo: list[tuple[VisualMark, ...]] = []
        self._redo: list[tuple[VisualMark, ...]] = []
        self._next_number = 1

    @property
    def marks(self) -> tuple[VisualMark, ...]:
        return tuple(self._marks)

    def _checkpoint(self) -> None:
        self._undo.append(self.marks)
        self._redo.clear()

    def add_point(self, point: NormalizedPoint, note: str = "") -> VisualMark:
        self._checkpoint()
        mark = VisualMark(
            id=f"mark-{uuid4().hex}",
            kind=VisualMarkKind.POINT,
            source=self.source,
            display_number=self._next_number,
            point=point,
            accessible_label=f"User marker {self._next_number}",
            note=note,
        )
        self._next_number += 1
        self._marks.append(mark)
        return mark

    def add_region(self, region: NormalizedRegion) -> VisualMark:
        return self.add_shaped_region(VisualMarkKind.RECTANGLE, region)

    def add_shaped_region(
        self, kind: VisualMarkKind, region: NormalizedRegion
    ) -> VisualMark:
        if kind not in {
            VisualMarkKind.RECTANGLE,
            VisualMarkKind.CIRCLE,
            VisualMarkKind.HIGHLIGHT,
        }:
            raise ValueError("region mark requires rectangle, circle, or highlight")
        self._checkpoint()
        mark = VisualMark(
            id=f"mark-{uuid4().hex}",
            kind=kind,
            source=self.source,
            region=region,
            accessible_label="User marked area",
        )
        self._marks.append(mark)
        return mark

    def add_arrow(
        self, start: NormalizedPoint, end: NormalizedPoint, *, measurement: bool = False
    ) -> VisualMark:
        self._checkpoint()
        mark = VisualMark(
            id=f"mark-{uuid4().hex}",
            kind=(VisualMarkKind.MEASUREMENT if measurement else VisualMarkKind.ARROW),
            source=self.source,
            point=start,
            end_point=end,
            accessible_label="User measurement" if measurement else "User arrow",
        )
        self._marks.append(mark)
        return mark

    def add_note(self, point: NormalizedPoint, note: str = "") -> VisualMark:
        self._checkpoint()
        mark = VisualMark(
            id=f"mark-{uuid4().hex}",
            kind=VisualMarkKind.NOTE,
            source=self.source,
            display_number=self._next_number,
            point=point,
            accessible_label=f"User note {self._next_number}",
            note=note,
        )
        self._next_number += 1
        self._marks.append(mark)
        return mark

    def delete(self, mark_id: str) -> None:
        if not any(mark.id == mark_id for mark in self._marks):
            raise KeyError(mark_id)
        self._checkpoint()
        self._marks = [mark for mark in self._marks if mark.id != mark_id]

    def clear(self) -> None:
        if not self._marks:
            return
        self._checkpoint()
        self._marks.clear()

    def undo(self) -> bool:
        if not self._undo:
            return False
        self._redo.append(self.marks)
        self._marks = list(self._undo.pop())
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        self._undo.append(self.marks)
        self._marks = list(self._redo.pop())
        return True

    def bind(self, text: str = "", speech_turn_id: str | None = None) -> VisualMarkSet:
        return VisualMarkSet(
            id=f"mark-set-{uuid4().hex}",
            source=self.source,
            marks=self.marks,
            text=text,
            speech_turn_id=speech_turn_id,
        )
