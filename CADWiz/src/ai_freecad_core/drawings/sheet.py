# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""A technical drawing sheet laid out from projected views (ORDER-2026-10-19-06).

Founder ruling 2026-10-19: a Drawings button -- "like a technical drawing. And
associated support with that button." This module is the sheet only: it never
touches FreeCAD. The views arrive already projected to 2D (u to the right, v up,
in model millimetres) by `integrations/cadwiz_plugin/drawing_job.py`; here they
are placed the American way (third-angle: the top view above the front view, the
right-side view to its right, a 3D view in the free corner), drawn at the largest
standard scale that fits a Letter page, dimensioned in inches with millimetres
beside them, and given a title block. The result is one SVG document.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from html import escape

from ai_freecad_core.visual_communications.anchored import inches_first

Point = tuple[float, float]

#: Letter, landscape, in millimetres -- his printer's paper.
SHEET_W, SHEET_H = 279.4, 215.9
MARGIN = 10.0
TITLE_H = 24.0
#: Room around a view for its dimensions, and between views.
DIM_ROOM = 16.0
GAP = 14.0
#: Standard scales, largest first (2.0 is 2:1, 0.5 is 1:2).
SCALES = (10.0, 5.0, 2.0, 1.0, 1 / 2, 1 / 3, 1 / 4, 1 / 5, 1 / 10, 1 / 20, 1 / 50, 1 / 100)
TEXT_MM = 3.0
ARROW_MM = 2.2


@dataclass
class View:
    """One projected view: polylines in model mm (u right, v up)."""

    name: str                                            # "front", "top", "right", "section", "iso"
    visible: list[list[Point]] = field(default_factory=list)
    hidden: list[list[Point]] = field(default_factory=list)
    hatch: list[list[list[Point]]] = field(default_factory=list)   # cut faces: each a list of closed loops
    label: str = ""

    def box(self) -> tuple[float, float, float, float]:
        points = [p for line in self.visible + self.hidden for p in line] + [p for face in self.hatch for loop in face for p in loop]
        if not points:
            return (0.0, 0.0, 0.0, 0.0)
        us, vs = [p[0] for p in points], [p[1] for p in points]
        return (min(us), max(us), min(vs), max(vs))

    def size(self) -> tuple[float, float]:
        u0, u1, v0, v1 = self.box()
        return (u1 - u0, v1 - v0)


@dataclass
class Dimension:
    """A dimension Claude adds: two points in one view's own model frame (mm)."""

    view: str
    start: Point
    end: Point
    label: str = ""                                      # default: the distance, inches first
    offset: float = 8.0                                  # sheet mm off the line: + below / right of it, - above / left


def scale_label(scale: float) -> str:
    if scale >= 1:
        return f"{scale:g}:1"
    return f"1:{1 / scale:g}"


def choose_scale(width_mm: float, depth_mm: float, height_mm: float) -> float:
    """The largest standard scale at which front, top and right views fit the sheet."""
    room_w = SHEET_W - 2 * MARGIN - 2 * DIM_ROOM - GAP
    room_h = SHEET_H - 2 * MARGIN - TITLE_H - 2 * DIM_ROOM - GAP
    need_w, need_h = width_mm + depth_mm, height_mm + depth_mm
    for scale in SCALES:
        if need_w * scale <= room_w and need_h * scale <= room_h:
            return scale
    return SCALES[-1]


def dimension_text(mm: float) -> str:
    return inches_first(abs(mm))


class _Canvas:
    def __init__(self) -> None:
        self.parts: list[str] = []

    def line(self, points: list[Point], css: str) -> None:
        if len(points) >= 2:
            self.parts.append(f'<polyline class="{css}" points="' + " ".join(f"{x:.2f},{y:.2f}" for x, y in points) + '"/>')

    def text(self, x: float, y: float, words: str, size: float = TEXT_MM, anchor: str = "middle", rotate: float = 0.0,
             bold: bool = False) -> None:
        turn = f' transform="rotate({rotate:.1f} {x:.2f} {y:.2f})"' if rotate else ""
        weight = ' font-weight="bold"' if bold else ""
        self.parts.append(f'<text x="{x:.2f}" y="{y:.2f}" font-size="{size:.2f}" text-anchor="{anchor}"{weight}{turn}>{escape(words)}</text>')

    def arrow(self, tip: Point, towards: Point) -> None:
        dx, dy = towards[0] - tip[0], towards[1] - tip[1]
        length = (dx * dx + dy * dy) ** 0.5 or 1.0
        ux, uy = dx / length, dy / length
        back = (tip[0] + ux * ARROW_MM, tip[1] + uy * ARROW_MM)
        side = (-uy * ARROW_MM * 0.35, ux * ARROW_MM * 0.35)
        self.parts.append(f'<polygon class="arrow" points="{tip[0]:.2f},{tip[1]:.2f} {back[0] + side[0]:.2f},{back[1] + side[1]:.2f} '
                          f'{back[0] - side[0]:.2f},{back[1] - side[1]:.2f}"/>')

    def dimension(self, a: Point, b: Point, offset: float, words: str) -> None:
        """A dimension between sheet points a and b, drawn `offset` mm to the right of the
        direction a->b on the page (sheet y runs down): left to right, positive is below;
        bottom to top, negative is to the left."""
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = (dx * dx + dy * dy) ** 0.5
        if length < 0.5:
            return
        nx, ny = -dy / length, dx / length
        a2, b2 = (a[0] + nx * offset, a[1] + ny * offset), (b[0] + nx * offset, b[1] + ny * offset)
        reach = 1.5 if offset >= 0 else -1.5
        self.line([a, (a2[0] + nx * reach, a2[1] + ny * reach)], "ext")
        self.line([b, (b2[0] + nx * reach, b2[1] + ny * reach)], "ext")
        self.line([a2, b2], "dim")
        self.arrow(a2, b2)
        self.arrow(b2, a2)
        angle = _degrees(dx, dy)
        if angle > 90:
            angle -= 180
        elif angle < -90:
            angle += 180
        # the usual drafting rule: words above a level dimension line, to the left of
        # an upright one (read from the right-hand side of the sheet)
        mid = ((a2[0] + b2[0]) / 2, (a2[1] + b2[1]) / 2)
        if abs(dx) >= abs(dy):
            self.text(mid[0], mid[1] - 1.0, words, rotate=angle)
        else:
            self.text(mid[0] - 1.0, mid[1], words, rotate=angle)


def _degrees(dx: float, dy: float) -> float:
    import math

    return math.degrees(math.atan2(dy, dx))


@dataclass
class Placed:
    """Where a view sits on the sheet: sheet x = left + (u - u0) * scale, sheet y = bottom - (v - v0) * scale."""

    view: View
    left: float
    bottom: float
    scale: float

    def at(self, p: Point) -> Point:
        u0, _u1, v0, _v1 = self.view.box()
        return (self.left + (p[0] - u0) * self.scale, self.bottom - (p[1] - v0) * self.scale)

    def corners(self) -> tuple[float, float, float, float]:
        w, h = self.view.size()
        return (self.left, self.bottom - h * self.scale, self.left + w * self.scale, self.bottom)


def compose(views: dict[str, View], *, title: str, version: int = 0, date: str = "", dimensions: list[Dimension] | None = None,
            note: str = "") -> tuple[str, float]:
    """The finished sheet as SVG, and the scale used.

    views needs "front" and "top"; "right" (or "section", which takes its place)
    and "iso" are drawn when given."""
    front, top = views["front"], views["top"]
    side = views.get("section") or views.get("right")
    width, height = front.size()
    depth = top.size()[1] if top.box() != (0.0, 0.0, 0.0, 0.0) else (side.size()[0] if side else 0.0)
    scale = choose_scale(width, depth, height)

    left = MARGIN + DIM_ROOM
    top_band = MARGIN + DIM_ROOM / 2
    top_bottom = top_band + depth * scale
    front_bottom = top_bottom + GAP + DIM_ROOM / 2 + height * scale
    placed = {"front": Placed(front, left, front_bottom, scale), "top": Placed(top, left, top_bottom, scale)}
    side_left = left + width * scale + GAP + DIM_ROOM / 2
    if side is not None:
        placed[side.name] = Placed(side, side_left, front_bottom, scale)

    canvas = _Canvas()
    for key, spot in placed.items():
        for line in spot.view.hidden:
            canvas.line([spot.at(p) for p in line], "hidden")
        for face in spot.view.hatch:
            path = " ".join("M " + " L ".join(f"{x:.2f},{y:.2f}" for x, y in (spot.at(p) for p in loop)) + " Z" for loop in face)
            canvas.parts.append(f'<path class="cut" d="{path}"/>')
        for line in spot.view.visible:
            canvas.line([spot.at(p) for p in line], "visible")
        x0, y0, x1, y1 = spot.corners()
        canvas.text((x0 + x1) / 2, y1 + DIM_ROOM - 1.0, spot.view.label or key.upper(), size=TEXT_MM * 0.9, bold=True)

    # overall sizes: the front view's width and height, the top view's depth
    fx0, fy0, fx1, fy1 = placed["front"].corners()
    canvas.dimension((fx0, fy1), (fx1, fy1), 8.0, dimension_text(width))        # below the front view
    canvas.dimension((fx0, fy1), (fx0, fy0), -8.0, dimension_text(height))      # left of the front view
    tx0, ty0, tx1, ty1 = placed["top"].corners()
    canvas.dimension((tx0, ty1), (tx0, ty0), -8.0, dimension_text(depth))       # left of the top view

    for dim in dimensions or []:
        spot = placed.get(dim.view)
        if spot is None:
            continue
        a, b = spot.at(dim.start), spot.at(dim.end)
        distance = ((dim.end[0] - dim.start[0]) ** 2 + (dim.end[1] - dim.start[1]) ** 2) ** 0.5
        canvas.dimension(a, b, dim.offset, dim.label or dimension_text(distance))

    iso = views.get("iso")
    if iso is not None and iso.box() != (0.0, 0.0, 0.0, 0.0):
        room = (side_left, MARGIN + 6.0, SHEET_W - MARGIN - 4.0, top_bottom)   # right of the top view, above the side view
        iw, ih = iso.size()
        if iw > 0 and ih > 0 and room[2] - room[0] > 20 and room[3] - room[1] > 20:
            iso_scale = min((room[2] - room[0]) / iw, (room[3] - room[1]) / ih) * 0.9
            spot = Placed(iso, (room[0] + room[2]) / 2 - iw * iso_scale / 2, (room[1] + room[3]) / 2 + ih * iso_scale / 2, iso_scale)
            for line in iso.visible:
                canvas.line([spot.at(p) for p in line], "visible")
            canvas.text((room[0] + room[2]) / 2, room[3] + 4.0, "3D VIEW (NOT TO SCALE)", size=TEXT_MM * 0.8, bold=True)

    _title_block(canvas, title, scale, version, date, note)
    return _document(canvas), scale


def _title_block(canvas: _Canvas, title: str, scale: float, version: int, date: str, note: str) -> None:
    x0, y0 = MARGIN, SHEET_H - MARGIN - TITLE_H
    x1, y1 = SHEET_W - MARGIN, SHEET_H - MARGIN
    canvas.line([(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)], "frame")
    split = x0 + (x1 - x0) * 0.5
    canvas.line([(split, y0), (split, y1)], "frame")
    canvas.text(x0 + 4, y0 + 10, title, size=6.0, anchor="start", bold=True)
    canvas.text(x0 + 4, y0 + 18, note or "Made by CADWiz from the model in FreeCAD", size=TEXT_MM, anchor="start")
    rows = [f"Scale {scale_label(scale)}    Units: in (mm)    Third-angle projection",
            f"Date {date or '-'}    Version {('v' + str(version)) if version else '-'}"]
    for i, row in enumerate(rows):
        canvas.text(split + 4, y0 + 9 + i * 8, row, size=TEXT_MM, anchor="start")


def _document(canvas: _Canvas) -> str:
    style = (".visible{fill:none;stroke:#000;stroke-width:0.5;stroke-linejoin:round;stroke-linecap:round}"
             ".hidden{fill:none;stroke:#555;stroke-width:0.25;stroke-dasharray:2,1.2}"
             ".dim,.ext{fill:none;stroke:#1565C0;stroke-width:0.18}.arrow{fill:#1565C0;stroke:none}"
             ".frame{fill:none;stroke:#000;stroke-width:0.4}.cut{fill:url(#hatch);stroke:#000;stroke-width:0.35;fill-rule:evenodd}"
             "text{font-family:Arial,Helvetica,sans-serif;fill:#000}")
    border = f'<rect x="{MARGIN / 2}" y="{MARGIN / 2}" width="{SHEET_W - MARGIN}" height="{SHEET_H - MARGIN}" class="frame"/>'
    hatch = ('<pattern id="hatch" patternUnits="userSpaceOnUse" width="2" height="2" patternTransform="rotate(45)">'
             '<line x1="0" y1="0" x2="0" y2="2" stroke="#000" stroke-width="0.2"/></pattern>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{SHEET_W}mm" height="{SHEET_H}mm" viewBox="0 0 {SHEET_W} {SHEET_H}">'
            f'<defs><style>{style}</style>{hatch}</defs><rect width="100%" height="100%" fill="white"/>{border}'
            + "".join(canvas.parts) + "</svg>")
