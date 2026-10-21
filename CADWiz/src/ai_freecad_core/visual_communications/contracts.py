# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Immutable host-neutral visual-dialogue contracts.

No type in this module imports or executes a presentation host or CAD product.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Mapping


def _required(value: str, name: str) -> str:
    if not value.strip():
        raise ValueError(f"{name} must be nonblank")
    return value


def _unit(value: float, name: str) -> float:
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be between 0 and 1")
    return value


class VisualCapability(str, Enum):
    SHOW = "show"
    GUIDE = "guide"
    INTERACT = "interact"


class VisualMarkKind(str, Enum):
    POINT = "point"
    RECTANGLE = "rectangle"
    CIRCLE = "circle"
    HIGHLIGHT = "highlight"
    LASSO = "lasso"
    ARROW = "arrow"
    MEASUREMENT = "measurement"
    NOTE = "note"


class VisualMarkAuthor(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"


class VisualMarkState(str, Enum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    RESOLVED = "resolved"
    ARCHIVED = "archived"


@dataclass(frozen=True, slots=True)
class NormalizedPoint:
    x: float
    y: float

    def __post_init__(self) -> None:
        _unit(self.x, "point x")
        _unit(self.y, "point y")


@dataclass(frozen=True, slots=True)
class NormalizedRegion:
    x: float
    y: float
    width: float
    height: float

    def __post_init__(self) -> None:
        for value, name in (
            (self.x, "region x"),
            (self.y, "region y"),
            (self.width, "region width"),
            (self.height, "region height"),
        ):
            _unit(value, name)
        if self.width <= 0 or self.height <= 0:
            raise ValueError("region dimensions must be positive")
        if self.x + self.width > 1 or self.y + self.height > 1:
            raise ValueError("region must fit within its source")


@dataclass(frozen=True, slots=True)
class NormalizedPath:
    points: tuple[NormalizedPoint, ...]
    closed: bool = False

    def __post_init__(self) -> None:
        if len(self.points) < 2:
            raise ValueError("path requires at least two points")
        if self.closed and len(self.points) < 3:
            raise ValueError("closed path requires at least three points")


@dataclass(frozen=True, slots=True)
class VisualSourceAnchor:
    asset_id: str
    source_hash: str | None = None
    media_type: str = "image"
    page_or_view: str = "default"
    orientation_degrees: int = 0
    source_width: int | None = None
    source_height: int | None = None
    zoom: float = 1.0
    pan_x: float = 0.0
    pan_y: float = 0.0

    def __post_init__(self) -> None:
        _required(self.asset_id, "asset id")
        _required(self.page_or_view, "page or view")
        if self.orientation_degrees not in {0, 90, 180, 270}:
            raise ValueError("orientation must be 0, 90, 180, or 270")
        if (self.source_width is not None and self.source_width <= 0) or (
            self.source_height is not None and self.source_height <= 0
        ):
            raise ValueError("source dimensions must be positive")
        if self.zoom <= 0:
            raise ValueError("zoom must be positive")

    @property
    def identity(self) -> tuple[str, str]:
        return self.asset_id, self.page_or_view


@dataclass(frozen=True, slots=True)
class VisualMark:
    id: str
    kind: VisualMarkKind
    source: VisualSourceAnchor
    author: VisualMarkAuthor = VisualMarkAuthor.USER
    state: VisualMarkState = VisualMarkState.DRAFT
    display_number: int | None = None
    point: NormalizedPoint | None = None
    region: NormalizedRegion | None = None
    path: NormalizedPath | None = None
    end_point: NormalizedPoint | None = None
    accessible_label: str = ""
    note: str = ""

    def __post_init__(self) -> None:
        _required(self.id, "mark id")
        if self.display_number is not None and self.display_number <= 0:
            raise ValueError("display number must be positive")
        populated = sum(value is not None for value in (self.point, self.region, self.path))
        if populated != 1:
            raise ValueError("mark requires exactly one authoritative geometry")
        if self.kind is VisualMarkKind.ARROW and self.end_point is None:
            raise ValueError("arrow requires an end point")


@dataclass(frozen=True, slots=True)
class VisualMarkSet:
    id: str
    source: VisualSourceAnchor
    marks: tuple[VisualMark, ...]
    text: str = ""
    speech_turn_id: str | None = None
    submitted: bool = False

    def __post_init__(self) -> None:
        _required(self.id, "mark-set id")
        ids = tuple(mark.id for mark in self.marks)
        if len(ids) != len(set(ids)):
            raise ValueError("mark ids must be unique")
        if any(mark.source.identity != self.source.identity for mark in self.marks):
            raise ValueError("mark set cannot contain cross-source marks")


@dataclass(frozen=True, slots=True)
class VisualActionResult:
    communication_id: str
    action_id: str
    option_id: str | None = None
    value: object | None = None
    selected_region: NormalizedRegion | None = None
    mark_ids: tuple[str, ...] = ()
    source: VisualSourceAnchor | None = None

    def __post_init__(self) -> None:
        _required(self.communication_id, "communication id")
        _required(self.action_id, "action id")
        if len(self.mark_ids) != len(set(self.mark_ids)):
            raise ValueError("result mark references must be unique")
        if self.mark_ids and self.source is None:
            raise ValueError("mark references require a source anchor")


@dataclass(frozen=True, slots=True)
class VisualCommunication:
    id: str
    capability: VisualCapability
    title: str
    text: str = ""
    product_payload: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _required(self.id, "communication id")
        _required(self.title, "communication title")
        object.__setattr__(self, "product_payload", MappingProxyType(dict(self.product_payload)))
