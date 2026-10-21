# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Wiz measures the open model itself -- in EVERY path (founder ruling 2026-10-12,
ORDER-2026-10-12-02).

"Wiz can always read the dimensions of any object in the open document (overall
size, wall thickness, openings, hole sizes and spacing, any distance or diameter
the founder names) and must never ask the founder to measure something it can
measure itself."

Two parts:

* `answer_measurement(...)` answers a measurement question from the document,
  with no AI call: quick facts (sizes, holes and their spacing, distances
  between named parts) straight from the shapes; section-based facts (walls,
  openings, inside diameters, distance around) from the headless worker on a
  saved copy, so the window keeps answering.
* `without_measure_requests(...)` removes any reply sentence that tells the
  founder to use a Measure tool or to give a dimension the model holds, and
  puts the measured answer in its place.

Duck-typed over FreeCAD objects so it is testable with stand-ins.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Callable, Iterable

from ai_freecad_core.ai_master.units import both
from integrations.ai_master.shape_box import tight_box

#: ORDER-2026-10-12-04: "I want the circumference of the inner wall" (the
#: founder's own words, 4:34 PM on 2026-10-12) is a measurement question too.
_QUESTION = re.compile(r"\b(what(?:'s| is| are)|how (?:big|wide|tall|high|thick|thin|long|deep|far|large|much)|measure|tell me|give me|"
                       r"do you know|can you (?:tell|find|measure|read)|size of|dimensions?|"
                       r"i (?:want|need|would like|'d like)(?: to know)? (?:the|its|what)|find (?:the|out)|check the)\b")
_MEASURE_WORDS = re.compile(r"\b(size|dimensions?|diameter|radius|circumference|around|perimeter|distance|spacing|apart|gap|clearance|"
                            r"thick(?:ness)?|wall|width|wide|height|tall|high|length|long|deep|depth|opening|hole|holes|port|ports|bore|"
                            r"inside|outside|big|large|volume)\b")
_EDIT_WORDS = re.compile(r"\b(make|change|set|add|remove|cut|move|widen|shrink|enlarge|scale|thicken|resize|drill|fillet|create|build)\b")

#: A reply sentence that sends the founder off to measure, or asks him for a
#: number the model holds.
_ASKS_TO_MEASURE = re.compile(
    r"[^.!?\n]*(?:"
    r"\b(?:use|try|open|select|click)\b[^.!?\n]{0,30}\bmeasure\b[^.!?\n]{0,12}\b(?:tool|feature|command|workbench)\b"
    r"|\bmeasure (?:it|this|that|them|the [a-z ]{1,30}) (?:yourself|with|using|in freecad)\b"
    r"|\b(?:tell|give|send|provide|share|let me know)\b[^.!?\n]{0,12}\b(?:me|us)?\b[^.!?\n]{0,20}\b(?:dimensions?|diameter|radius|measurements?|size|width|height|length|thickness|distance|circumference)\b"
    r"|\bI (?:would )?need (?:to know )?(?:the |its |your )?[a-z ]{0,30}\b(?:dimensions?|diameter|radius|measurements?|size|width|height|length|thickness|distance|circumference)\b"
    r"|\bwhat (?:is|are) (?:the |its |your )[a-z ]{0,30}\b(?:dimensions?|diameter|radius|measurements?|thickness|circumference)\b[^.!?\n]*\?"
    # 2026-10-12, the founder's session: "select the bottom inner edge in FreeCAD
    # and check its Length" / "needs the actual selected inner edge length in FreeCAD".
    r"|\bselect (?:the |an? )?[a-z ]{0,40}\b(?:edge|face|loop|curve)\b[^.!?\n]{0,40}\b(?:check|read|look at|see)\b"
    r"|\bneeds? (?:the )?(?:actual )?selected [a-z ]{0,30}\b(?:edge|face|length)\b"
    r")[^.!?\n]*[.!?]?",
    re.I,
)


def is_measurement_question(text: str) -> bool:
    lowered = " ".join((text or "").casefold().replace("’", "'").split())
    if not lowered or _EDIT_WORDS.search(lowered):
        return False
    return bool(_QUESTION.search(lowered) and _MEASURE_WORDS.search(lowered))


def asks_founder_to_measure(text: str) -> bool:
    return bool(text and _ASKS_TO_MEASURE.search(text))


def without_measure_requests(text: str, measured: Callable[[], str]) -> str:
    """Drop every sentence that asks the founder to measure; put the measured
    answer in front. `measured()` is only called when something was dropped."""
    if not asks_founder_to_measure(text):
        return text
    kept = _ASKS_TO_MEASURE.sub("", text).strip()
    answer = measured().strip()
    return (answer + (" " + kept if kept else "")).strip() if answer else kept


# ---- reading the document ------------------------------------------------------

_SKIP = ("Sketcher::", "Spreadsheet::", "App::Origin", "App::Line", "App::Plane", "App::Point", "App::DocumentObjectGroup")


def _shape(obj: Any) -> Any | None:
    shape = getattr(obj, "Shape", None)
    try:
        if shape is None or (callable(getattr(shape, "isNull", None)) and shape.isNull()):
            return None
    except Exception:  # noqa: BLE001
        return None
    return shape


def shape_objects(document: Any) -> list[Any]:
    out = []
    for obj in list(getattr(document, "Objects", None) or []):
        if str(getattr(obj, "TypeId", "")).startswith(_SKIP):
            continue
        if _shape(obj) is None:
            continue
        users = [u for u in (getattr(obj, "InList", None) or []) if not str(getattr(u, "TypeId", "")).startswith(_SKIP)]
        if users:
            continue
        out.append(obj)
    return out


def _words(label: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", label.casefold()) if len(w) >= 4 and w not in ("temporary", "with", "mm", "part")]


def _best_named(document: Any, phrase: str) -> Any | None:
    found = named_objects(document, phrase)
    return found[0] if found else None


def named_objects(document: Any, text: str) -> list[Any]:
    """Objects the founder named, best match first (label words in his words).
    Temporary/cutaway parts rank last unless he names them as such."""
    lowered = text.casefold()
    wants_temporary = bool(re.search(r"\b(temporary|cutaway|cut-away|temp)\b", lowered))
    scored = []
    for obj in shape_objects(document):
        label = str(getattr(obj, "Label", "") or getattr(obj, "Name", ""))
        if label.casefold() in lowered:
            scored.append((100, obj))
            continue
        hits = sum(1 for w in _words(label) if re.search(r"\b" + re.escape(w), lowered))
        if hits:
            temporary = bool(re.search(r"temporary|cutaway|\btemp\b", label.casefold()))
            scored.append((hits - (5 if temporary and not wants_temporary else 0), obj))
    scored.sort(key=lambda s: -s[0])
    return [obj for _score, obj in scored]


def main_object(document: Any) -> Any | None:
    objects = shape_objects(document)
    visible = [o for o in objects if getattr(o, "Visibility", True)] or objects
    if not visible:
        return None
    return max(visible, key=lambda o: _shape(o).BoundBox.DiagonalLength)


def holes_with_centres(shape: Any) -> list[dict[str, float]]:
    """Round holes: cylindrical faces, one per distinct axis position."""
    found: list[dict[str, float]] = []
    for face in getattr(shape, "Faces", None) or []:
        surface = getattr(face, "Surface", None)
        if surface is None or type(surface).__name__ != "Cylinder":
            continue
        radius = float(getattr(surface, "Radius", 0.0))
        centre = getattr(surface, "Center", None)
        if radius <= 0 or centre is None:
            continue
        x, y, z = float(centre.x), float(centre.y), float(centre.z)
        if any(abs(h["x"] - x) < 0.05 and abs(h["y"] - y) < 0.05 and abs(h["diameter_mm"] - 2 * radius) < 0.05 for h in found):
            continue
        found.append({"diameter_mm": round(2 * radius, 3), "x": round(x, 3), "y": round(y, 3), "z": round(z, 3)})
    return found


def spacing(points: Iterable[tuple[float, float]]) -> list[float]:
    """Nearest-neighbour centre distances, one per point."""
    pts = list(points)
    out = []
    for i, (x, y) in enumerate(pts):
        nearest = min((math.hypot(x - u, y - v) for j, (u, v) in enumerate(pts) if j != i), default=None)
        if nearest is not None:
            out.append(round(nearest, 2))
    return out


@dataclass
class SectionRunner:
    """Runs a section measurement of the open document in the headless worker.
    `run(object_label, opening=None, height_mm=None) -> dict` (worker result)."""

    run: Callable[..., dict[str, Any]]


def _size_line(label: str, box: Any) -> str:
    return f"{label} is {both(box.XLength)} wide (X), {both(box.YLength)} deep (Y) and {both(box.ZLength)} tall (Z)"


def _walls_from_loops(loops: list[dict[str, Any]]) -> list[float]:
    """Walls are the distance from each outer loop to the next loop in (loops
    0-1, 2-3, ...); the worker measures it as a true shortest distance. Results
    without it fall back to half the size difference."""
    walls = []
    for i in range(0, len(loops) - 1, 2):
        outer, inner = loops[i], loops[i + 1]
        if outer.get("to_next_loop_mm") is not None:
            walls.append(round(float(outer["to_next_loop_mm"]), 2))
        else:
            walls.append(round(min(outer["width_mm"] - inner["width_mm"], outer["depth_mm"] - inner["depth_mm"]) / 2, 2))
    return walls


def _gap_between_walls(loops: list[dict[str, Any]]) -> float | None:
    if len(loops) < 4:
        return None
    if loops[1].get("to_next_loop_mm") is not None:
        return round(float(loops[1]["to_next_loop_mm"]), 2)
    return round(min(loops[1]["width_mm"] - loops[2]["width_mm"], loops[1]["depth_mm"] - loops[2]["depth_mm"]) / 2, 2)


def answer_measurement(document: Any, text: str, section: SectionRunner | None = None) -> str:
    """A plain answer to a measurement question about the open document, or ""
    when there is nothing to measure. Never asks the founder for a number."""
    if document is None:
        return ""
    lowered = text.casefold()
    named = named_objects(document, text)
    target = named[0] if named else main_object(document)
    if target is None:
        return ""
    label = str(getattr(target, "Label", "") or getattr(target, "Name", "the part"))
    shape = _shape(target)
    box = tight_box(shape)
    lines: list[str] = []

    # distance between two named parts: each side of "between A and B" on its own
    pair = re.search(r"\bbetween (.+?) and (.+)", lowered)
    a = b = None
    if pair and re.search(r"\b(distance|gap|apart|between|clearance|far)\b", lowered):
        a, b = _best_named(document, pair.group(1)), _best_named(document, pair.group(2))
    elif len(named) >= 2 and re.search(r"\b(distance|gap|apart|clearance)\b", lowered):
        a, b = named[0], named[1]
    if a is not None and b is not None and a is not b:
        try:
            gap = float(_shape(a).distToShape(_shape(b))[0])
            return f"The closest gap between {a.Label} and {b.Label} is {both(gap)}" + (" -- they touch or overlap." if gap < 1e-6 else ".")
        except Exception:  # noqa: BLE001
            pass

    wants_opening = re.search(r"\b(opening|inside|circumference|around|perimeter)\b", lowered)
    wants_wall = re.search(r"\b(wall|thick(?:ness)?|thin)\b", lowered)
    wants_holes = re.search(r"\b(holes?|ports?|bores?|spacing|apart)\b", lowered)
    wants_size = re.search(r"\b(size|dimensions?|big|large|wide|width|tall|height|high|long|length|deep|depth|volume)\b", lowered) and not (wants_opening or wants_wall or wants_holes)

    if wants_opening and section is not None:
        which = "top" if re.search(r"\b(top|upper)\b", lowered) else "bottom"
        result = section.run(label, opening=which)
        inside = (result or {}).get("inside") or {}
        if inside:
            shape_word = "round" if abs(inside["width_mm"] - inside["depth_mm"]) < 0.5 else "oval"
            lines.append(f"The {which} opening of {label} is {shape_word}: inside it measures {both(inside['width_mm'])} front to back (X) and "
                         f"{both(inside['depth_mm'])} side to side (Y), {both(inside['perimeter_mm'])} around"
                         + (f" (the same distance around as a {both(inside['equivalent_diameter_mm'])} circle)" if shape_word == "oval" else
                            f" -- an inside diameter of {both(inside['equivalent_diameter_mm'])}")
                         + f", measured {result.get('height_mm')} mm above its {which}.")
        elif result.get("error"):
            lines.append(f"I could not find an opening at the {which} of {label}: {result['error']}.")

    if wants_wall and section is not None:
        height = round(box.ZMin + box.ZLength / 2, 2)
        result = section.run(label, height_mm=height)
        loops = [l for l in (result or {}).get("loops") or [] if l["perimeter_mm"] >= 0.15 * ((result or {}).get("loops") or [{"perimeter_mm": 1}])[0]["perimeter_mm"]]
        walls = _walls_from_loops(loops)
        if walls:
            names = ["outer wall", "inner wall"] if len(walls) == 2 else [f"wall {i + 1}" for i in range(len(walls))]
            lines.append(f"Halfway up {label} ({both(height)}): " + "; ".join(f"{n} {both(w)} thick" for n, w in zip(names, walls))
                         + (f"; gap between the walls {both(_gap_between_walls(loops))}" if _gap_between_walls(loops) is not None else "")
                         + ".")
        else:
            lines.append(f"{label} is solid where I cut it halfway up ({both(height)}): no wall to measure there.")

    if wants_holes:
        holes = holes_with_centres(shape)
        if not holes and section is not None:
            result = section.run(label, opening="bottom")
            holes = [{"diameter_mm": h["diameter_mm"], "x": h["centre"][0], "y": h["centre"][1]} for h in (result or {}).get("small_openings") or []]
        if holes:
            sizes = sorted({h["diameter_mm"] for h in holes})
            gaps = spacing((h["x"], h["y"]) for h in holes)
            line = f"{label} has {len(holes)} round hole{'s' if len(holes) != 1 else ''}: " + ", ".join(both(s) for s in sizes) + " across"
            if gaps:
                line += f"; centre to nearest centre {both(min(gaps))}" + (f" to {both(max(gaps))}" if max(gaps) - min(gaps) > 0.05 else "")
            lines.append(line + ".")
        else:
            lines.append(f"I found no round holes in {label}.")

    if wants_size or not lines:
        line = _size_line(label, box)
        try:
            line += f"; volume {float(shape.Volume) / 1000:.1f} cm3"
        except Exception:  # noqa: BLE001
            pass
        lines.insert(0, line + ".")
        if re.search(r"\b(diameter|radius)\b", lowered) and abs(box.XLength - box.YLength) < 0.5:
            lines.insert(1, f"Its diameter is {both(box.XLength)}.")
    return " ".join(lines)
