# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Marks anchored to the model, and the frame the founder shows Claude.

ORDER-2026-10-18-01 (the panel redesign the founder approved on 2026-10-18).
The archived Visual Communications Screen kept marks in picture coordinates, so
a circle drawn on the helmet's brim stayed where it was on the glass when the
view turned. Here every mark is held as points ON THE MODEL (millimetres in the
document's own coordinates, plus the face it was drawn on when there was one)
and is projected into whatever view is on screen now. The archived contracts
(`contracts.py`) are still the record: `to_visual_mark` turns an anchored mark
into a `VisualMark` for the picture a frame was frozen with.

Domain-neutral: no FreeCAD, no Qt. The camera is plain numbers read from the
host's 3D view; the projection follows Coin's own rule for fitting a camera
into a picture whose shape differs from the window's (the viewport mapping
FreeCAD uses, ADJUST_CAMERA), so the same marks land on the same spots in the
panel's picture, the frozen frame and FreeCAD's own view.
"""
from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field, replace
from typing import Any, Iterable, Sequence

from .contracts import (
    NormalizedPath,
    NormalizedPoint,
    NormalizedRegion,
    VisualMark,
    VisualMarkAuthor,
    VisualMarkKind,
    VisualMarkState,
    VisualSourceAnchor,
)

Vec = tuple[float, float, float]

MM_PER_INCH = 25.4


def inches_first(mm: float) -> str:
    """'1.57 in (40 mm)': the founder reads inches first with millimetres beside."""
    inches = mm / MM_PER_INCH
    return f"{_num(inches, 2)} in ({_num(mm, 1)} mm)"


def _num(value: float, places: int) -> str:
    text = f"{value:.{places}f}".rstrip("0").rstrip(".")
    return text if text not in ("", "-0") else "0"


def _sub(a: Vec, b: Vec) -> Vec:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _add(a: Vec, b: Vec) -> Vec:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _scale(a: Vec, s: float) -> Vec:
    return (a[0] * s, a[1] * s, a[2] * s)


def _dot(a: Vec, b: Vec) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _norm(a: Vec) -> Vec:
    length = math.sqrt(_dot(a, a))
    return _scale(a, 1.0 / length) if length > 0 else a


def distance(a: Vec, b: Vec) -> float:
    d = _sub(a, b)
    return math.sqrt(_dot(d, d))


def _rotate(q: tuple[float, float, float, float], v: Vec) -> Vec:
    """Rotate `v` by the unit quaternion q = (x, y, z, w) -- Coin's SbRotation order."""
    length = math.sqrt(sum(c * c for c in q)) or 1.0      # FreeCAD hands over float32 values: make it exactly unit
    x, y, z, w = (c / length for c in q)
    u = (x, y, z)
    uv = _dot(u, v)
    uu = _dot(u, u)
    cross = (y * v[2] - z * v[1], z * v[0] - x * v[2], x * v[1] - y * v[0])
    return (2 * uv * x + (w * w - uu) * v[0] + 2 * w * cross[0],
            2 * uv * y + (w * w - uu) * v[1] + 2 * w * cross[1],
            2 * uv * z + (w * w - uu) * v[2] + 2 * w * cross[2])


@dataclass(frozen=True, slots=True)
class Camera:
    """A 3D view's camera as plain numbers.

    `kind` is "orthographic" (FreeCAD's default) or "perspective". For an
    orthographic camera `height` is the height of the visible area in mm; for a
    perspective one `height_angle` is the vertical field of view in radians.
    The camera looks along its local -Z with +Y up, turned by `orientation`."""

    kind: str
    position: Vec
    orientation: tuple[float, float, float, float]
    height: float = 0.0
    height_angle: float = 0.0
    focal_distance: float = 1.0

    def __post_init__(self) -> None:
        if self.kind not in ("orthographic", "perspective"):
            raise ValueError("camera kind must be orthographic or perspective")
        if self.kind == "orthographic" and self.height <= 0:
            raise ValueError("an orthographic camera needs a positive height")
        if self.kind == "perspective" and not 0 < self.height_angle < math.pi:
            raise ValueError("a perspective camera needs a height angle between 0 and pi")

    # ---- axes -------------------------------------------------------------------
    @property
    def right(self) -> Vec:
        return _rotate(self.orientation, (1.0, 0.0, 0.0))

    @property
    def up(self) -> Vec:
        return _rotate(self.orientation, (0.0, 1.0, 0.0))

    @property
    def forward(self) -> Vec:
        return _rotate(self.orientation, (0.0, 0.0, -1.0))

    def _half_extent(self, aspect: float) -> tuple[float, float]:
        """Half width and half height of the visible area: in mm (orthographic) or
        as tangents (perspective). Coin's ADJUST_CAMERA: a picture wider than tall
        widens the view; a picture taller than wide keeps the camera's height on
        the WIDTH and grows the height, so a tall picture never crops the model."""
        if aspect <= 0:
            raise ValueError("aspect must be positive")
        half = self.height / 2.0 if self.kind == "orthographic" else math.tan(self.height_angle / 2.0)
        half_w, half_h = half * aspect, half
        if aspect < 1.0:
            half_w, half_h = half_w / aspect, half_h / aspect
        return half_w, half_h

    # ---- model point <-> picture point ------------------------------------------
    def project(self, point: Vec, aspect: float) -> tuple[float, float] | None:
        """Where a model point appears in a picture of shape `aspect` (width /
        height): (u, v) with (0, 0) the picture's top-left and (1, 1) its
        bottom-right. Outside 0..1 means off the picture. None when the point is
        behind a perspective camera."""
        d = _sub(point, self.position)
        x, y = _dot(d, self.right), _dot(d, self.up)
        half_w, half_h = self._half_extent(aspect)
        if self.kind == "perspective":
            z = _dot(d, self.forward)
            if z <= 1e-9:
                return None
            x, y = x / z, y / z
        return 0.5 + x / (2.0 * half_w), 0.5 - y / (2.0 * half_h)

    def ray(self, u: float, v: float, aspect: float) -> tuple[Vec, Vec]:
        """The line of sight through picture point (u, v): (origin, unit direction)."""
        half_w, half_h = self._half_extent(aspect)
        sx, sy = (u - 0.5) * 2.0 * half_w, (0.5 - v) * 2.0 * half_h
        if self.kind == "orthographic":
            origin = _add(self.position, _add(_scale(self.right, sx), _scale(self.up, sy)))
            return origin, self.forward
        direction = _norm(_add(self.forward, _add(_scale(self.right, sx), _scale(self.up, sy))))
        return self.position, direction

    def point_at_focus(self, u: float, v: float, aspect: float) -> Vec:
        """The model-space point under (u, v) at the camera's focal distance --
        where a mark goes when nothing of the model is under the pointer."""
        origin, direction = self.ray(u, v, aspect)
        if self.kind == "orthographic":
            return _add(origin, _scale(direction, self.focal_distance))
        along = self.focal_distance / max(_dot(direction, self.forward), 1e-9)
        return _add(origin, _scale(direction, along))

    def mm_per_picture_height(self, point: Vec, aspect: float) -> float:
        """How many mm the full picture height spans at `point`'s depth."""
        _w, half_h = self._half_extent(aspect)
        if self.kind == "orthographic":
            return 2.0 * half_h
        depth = max(_dot(_sub(point, self.position), self.forward), 1e-9)
        return 2.0 * half_h * depth

    # ---- record ---------------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "position": list(self.position), "orientation": list(self.orientation),
                "height": self.height, "height_angle": self.height_angle, "focal_distance": self.focal_distance}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Camera":
        return cls(str(data["kind"]), tuple(float(x) for x in data["position"]),  # type: ignore[arg-type]
                   tuple(float(x) for x in data["orientation"]),  # type: ignore[arg-type]
                   float(data.get("height") or 0.0), float(data.get("height_angle") or 0.0),
                   float(data.get("focal_distance") or 1.0))


@dataclass(frozen=True, slots=True)
class ModelAnchor:
    """A point of a mark, in the document's own coordinates (mm). `obj` and
    `element` name what it was placed on ("Pad", "Face6") when it was placed on
    the model; `on_model` is False for a point in the air (no surface under it)."""

    point: Vec
    obj: str = ""
    element: str = ""
    on_model: bool = False

    def where(self) -> str:
        if self.obj:
            return f"{self.obj}.{self.element}" if self.element else self.obj
        return ""

    def to_dict(self) -> dict[str, Any]:
        return {"point_mm": [round(c, 4) for c in self.point], "object": self.obj, "element": self.element,
                "on_model": self.on_model}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ModelAnchor":
        return cls(tuple(float(c) for c in data["point_mm"]), str(data.get("object") or ""),  # type: ignore[arg-type]
                   str(data.get("element") or ""), bool(data.get("on_model")))


#: The ten things on the marking toolbar map onto the archived mark kinds.
TOOL_KINDS: dict[str, VisualMarkKind] = {
    "point": VisualMarkKind.POINT,
    "circle": VisualMarkKind.CIRCLE,
    "box": VisualMarkKind.RECTANGLE,
    "highlight": VisualMarkKind.HIGHLIGHT,
    "lasso": VisualMarkKind.LASSO,
    "arrow": VisualMarkKind.ARROW,
    "measure": VisualMarkKind.MEASUREMENT,
    "note": VisualMarkKind.NOTE,
}
#: How many anchors each kind holds: (at least, at most).
_ANCHOR_COUNT: dict[VisualMarkKind, tuple[int, int]] = {
    VisualMarkKind.POINT: (1, 1),
    VisualMarkKind.NOTE: (1, 1),
    VisualMarkKind.CIRCLE: (2, 2),         # centre, a point on the rim
    VisualMarkKind.RECTANGLE: (2, 400),    # two opposite corners, or the outline of a face it goes around
    VisualMarkKind.HIGHLIGHT: (2, 400),    # two opposite corners, or the outline of the face it paints
    VisualMarkKind.ARROW: (2, 2),          # from, to
    VisualMarkKind.MEASUREMENT: (2, 2),
    VisualMarkKind.LASSO: (3, 400),
}
PLAIN_KIND = {VisualMarkKind.POINT: "point", VisualMarkKind.NOTE: "note", VisualMarkKind.CIRCLE: "circle",
              VisualMarkKind.RECTANGLE: "box", VisualMarkKind.HIGHLIGHT: "highlight", VisualMarkKind.ARROW: "arrow",
              VisualMarkKind.MEASUREMENT: "measurement", VisualMarkKind.LASSO: "lasso"}


@dataclass(frozen=True, slots=True)
class AnchoredMark:
    id: str
    kind: VisualMarkKind
    anchors: tuple[ModelAnchor, ...]
    author: VisualMarkAuthor = VisualMarkAuthor.USER
    number: int = 1
    text: str = ""

    def __post_init__(self) -> None:
        low, high = _ANCHOR_COUNT[self.kind]
        if not low <= len(self.anchors) <= high:
            raise ValueError(f"a {PLAIN_KIND[self.kind]} mark needs {low}..{high} points, got {len(self.anchors)}")
        if self.number <= 0:
            raise ValueError("mark numbers start at 1")

    @property
    def length_mm(self) -> float | None:
        """The measured distance of a measurement (or an arrow), in mm."""
        if self.kind in (VisualMarkKind.MEASUREMENT, VisualMarkKind.ARROW):
            return distance(self.anchors[0].point, self.anchors[1].point)
        if self.kind is VisualMarkKind.CIRCLE:
            return distance(self.anchors[0].point, self.anchors[1].point)  # the radius
        return None

    def label(self) -> str:
        """What the picture writes beside the mark."""
        if self.kind is VisualMarkKind.MEASUREMENT:
            return inches_first(self.length_mm or 0.0)
        if self.kind is VisualMarkKind.NOTE:
            return self.text
        return self.text or str(self.number)

    def describe(self) -> str:
        """One plain line for Claude: who drew what, on what, where."""
        who = "the founder's" if self.author is VisualMarkAuthor.USER else "your"
        line = f"Mark {self.number} ({who} {PLAIN_KIND[self.kind]})"
        placed = sorted({a.where() for a in self.anchors if a.where()})
        if placed:
            line += " on " + ", ".join(placed)
        first = self.anchors[0].point
        line += f" at ({_num(first[0], 2)}, {_num(first[1], 2)}, {_num(first[2], 2)}) mm"
        if self.kind is VisualMarkKind.MEASUREMENT:
            line += f": {inches_first(self.length_mm or 0.0)} between its two points"
        elif self.kind is VisualMarkKind.ARROW:
            end = self.anchors[1].point
            line += f", pointing to ({_num(end[0], 2)}, {_num(end[1], 2)}, {_num(end[2], 2)}) mm"
        elif self.kind is VisualMarkKind.CIRCLE:
            line += f", radius {inches_first(self.length_mm or 0.0)}"
        if self.text and self.kind is not VisualMarkKind.MEASUREMENT:
            line += f' -- "{self.text}"'
        if not any(a.on_model for a in self.anchors):
            line += " (placed in the air in front of the model, not on a surface)"
        return line

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"id": self.id, "number": self.number, "kind": PLAIN_KIND[self.kind],
                               "author": "founder" if self.author is VisualMarkAuthor.USER else "claude",
                               "anchors": [a.to_dict() for a in self.anchors], "text": self.text, "description": self.describe()}
        if self.kind is VisualMarkKind.MEASUREMENT:
            out["distance_mm"] = round(self.length_mm or 0.0, 3)
            out["distance"] = inches_first(self.length_mm or 0.0)
        return out

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AnchoredMark":
        kind = next(k for k, name in PLAIN_KIND.items() if name == data["kind"])
        author = VisualMarkAuthor.USER if data.get("author", "founder") == "founder" else VisualMarkAuthor.ASSISTANT
        return cls(str(data["id"]), kind, tuple(ModelAnchor.from_dict(a) for a in data["anchors"]), author,
                   int(data.get("number") or 1), str(data.get("text") or ""))


@dataclass(frozen=True, slots=True)
class PlacedMark:
    """An anchored mark as it falls on one picture right now: points in picture
    units (0..1, may run off the edge), and the circle's radius in picture-height
    units. `visible` is False when every point is off the picture or behind it."""

    mark: AnchoredMark
    points: tuple[tuple[float, float], ...]
    radius: float = 0.0
    visible: bool = True


def place(mark: AnchoredMark, camera: Camera, aspect: float) -> PlacedMark:
    projected = [camera.project(a.point, aspect) for a in mark.anchors]
    if any(p is None for p in projected):
        return PlacedMark(mark, (), visible=False)
    points = tuple(p for p in projected if p is not None)
    radius = 0.0
    if mark.kind is VisualMarkKind.CIRCLE:
        span = camera.mm_per_picture_height(mark.anchors[0].point, aspect)
        radius = (mark.length_mm or 0.0) / span if span > 0 else 0.0
        points = points[:1]
    visible = any(-0.05 <= u <= 1.05 and -0.05 <= v <= 1.05 for u, v in points)
    return PlacedMark(mark, points, radius, visible)


def _clamp(value: float) -> float:
    return min(1.0, max(0.0, value))


def to_visual_mark(placed: PlacedMark, source: VisualSourceAnchor, aspect: float) -> VisualMark | None:
    """The archived contract's record of this mark on the frozen picture
    (clamped to the picture), or None when it is not on the picture at all."""
    if not placed.visible or not placed.points:
        return None
    mark = placed.mark
    pts = [NormalizedPoint(_clamp(u), _clamp(v)) for u, v in placed.points]
    common = {"id": mark.id, "kind": mark.kind, "source": source, "author": mark.author, "state": VisualMarkState.SUBMITTED,
              "display_number": mark.number, "accessible_label": mark.describe(), "note": mark.text}
    if mark.kind in (VisualMarkKind.POINT, VisualMarkKind.NOTE):
        return VisualMark(point=pts[0], **common)
    if mark.kind in (VisualMarkKind.ARROW, VisualMarkKind.MEASUREMENT):
        return VisualMark(point=pts[0], end_point=pts[1], **common)
    if mark.kind is VisualMarkKind.HIGHLIGHT and len(pts) > 2:
        return VisualMark(path=NormalizedPath(tuple(pts), closed=True), **common)
    if mark.kind is VisualMarkKind.LASSO:
        return VisualMark(path=NormalizedPath(tuple(pts), closed=True), **common)
    if mark.kind is VisualMarkKind.CIRCLE:
        cu, cv = placed.points[0]
        rv = placed.radius
        ru = rv / aspect
        x0, y0, x1, y1 = _clamp(cu - ru), _clamp(cv - rv), _clamp(cu + ru), _clamp(cv + rv)
    else:
        us, vs = [p[0] for p in placed.points], [p[1] for p in placed.points]
        x0, y0, x1, y1 = _clamp(min(us)), _clamp(min(vs)), _clamp(max(us)), _clamp(max(vs))
    width, height = max(x1 - x0, 1e-4), max(y1 - y0, 1e-4)
    x0, y0 = min(x0, 1 - width), min(y0, 1 - height)
    return VisualMark(region=NormalizedRegion(x0, y0, width, height), **common)


@dataclass(slots=True)
class MarkBook:
    """The marks on the screen: the founder's and Claude's, numbered separately.
    Undo and Clear touch only marks, never the model."""

    marks: list[AnchoredMark] = field(default_factory=list)
    _ids: Any = field(default_factory=lambda: itertools.count(1))

    def add(self, kind: VisualMarkKind | str, anchors: Sequence[ModelAnchor], *, author: VisualMarkAuthor = VisualMarkAuthor.USER,
            text: str = "") -> AnchoredMark:
        if isinstance(kind, str):
            if kind not in TOOL_KINDS:
                raise ValueError(f"no mark kind called {kind!r}; the kinds are {', '.join(TOOL_KINDS)}")
            kind = TOOL_KINDS[kind]
        number = 1 + sum(1 for m in self.marks if m.author is author)
        prefix = "f" if author is VisualMarkAuthor.USER else "c"
        mark = AnchoredMark(f"{prefix}{next(self._ids)}", kind, tuple(anchors), author, number, text.strip())
        self.marks.append(mark)
        return mark

    def by(self, author: VisualMarkAuthor) -> list[AnchoredMark]:
        return [m for m in self.marks if m.author is author]

    def undo(self, author: VisualMarkAuthor = VisualMarkAuthor.USER) -> AnchoredMark | None:
        for index in range(len(self.marks) - 1, -1, -1):
            if self.marks[index].author is author:
                return self.marks.pop(index)
        return None

    def clear(self, author: VisualMarkAuthor | None = None) -> int:
        before = len(self.marks)
        self.marks = [m for m in self.marks if author is not None and m.author is not author]
        return before - len(self.marks)

    def renumber(self) -> None:
        counters: dict[VisualMarkAuthor, int] = {}
        renumbered = []
        for mark in self.marks:
            counters[mark.author] = counters.get(mark.author, 0) + 1
            renumbered.append(replace(mark, number=counters[mark.author]))
        self.marks = renumbered

    def to_list(self) -> list[dict[str, Any]]:
        return [m.to_dict() for m in self.marks]


def describe_marks(marks: Iterable[AnchoredMark]) -> list[str]:
    return [m.describe() for m in marks]
