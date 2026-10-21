# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Guided intent: the few questions that change a design (ORDER-2026-10-18-02 D).

The founder: "if I say I want a fishing lure, you should think about what kind of
fish ... don't make it too much, but continue to guide the user through the
intent creation." So: at most three questions, the ones that change the design
most, each with a default he can accept in one word; every other choice is a
stated default. If he says "just make it" -- or his Setup says "None, use
defaults" -- nothing is asked and Claude says which defaults it used.

Answers go into the Design Contract (`design_record`): measurable ones as
requirements `contract_check` can test (sizes, wall, holes, hollow, fits the
bed), the rest as assumptions. Also here: the build rules for engineered parts
(ORDER-2026-10-18-02 C) and the FreeCAD-or-Blender routing.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

MAX_ASKED = 3


@dataclass(frozen=True, slots=True)
class Question:
    key: str
    ask: str
    default: str
    options: tuple[str, ...] = ()
    #: A requirement contract_check can measure, from the default: (metric, target, tolerance, unit)
    measure: tuple[str, float | bool, float, str] | None = None

    def line(self, number: int) -> str:
        options = f" ({', '.join(self.options)})" if self.options else ""
        return f"{number}. {self.ask}{options} -- default: {self.default}"


@dataclass(frozen=True, slots=True)
class Family:
    name: str
    words: tuple[str, ...]
    questions: tuple[Question, ...]          # most important first
    route: str = "freecad"                   # freecad | blender | either
    notes: tuple[str, ...] = field(default=())


FAMILIES: tuple[Family, ...] = (
    Family("fishing lure", ("lure", "fishing", "bait", "crankbait", "swimbait", "jig", "spoon", "popper", "jerkbait"), (
        Question("fish", "What fish is it for?", "largemouth bass", ("bass", "trout", "pike", "walleye", "saltwater")),
        Question("action", "Casting or trolling?", "casting", ("casting", "trolling")),
        Question("length", "How long, nose to tail?", "3 in (76 mm)", measure=("width_mm", 76.0, 6.0, "mm")),
        Question("buoyancy", "Floating or sinking?", "floating (hollow body with a sealed air chamber)", ("floating", "sinking"),
                 measure=("hollow", True, 0.0, "")),
        Question("hooks", "Hook style and size?", "two size-6 treble hooks on screw eyes, front and belly"),
        Question("material", "Print material?", "PETG (stands up to water and sun better than PLA)", ("PETG", "PLA", "ASA")),
    ), route="either", notes=("A lip or diving bill sets how deep it runs; a smooth body is a loft through sections in FreeCAD, "
                              "a sculpted one is a mesh job for Blender.",)),
    Family("bracket", ("bracket", "shelf bracket", "l bracket", "mount", "brace", "angle bracket"), (
        Question("load", "What will it hold, and about how heavy?", "a shelf of books, about 10 lb (4.5 kg)"),
        Question("screws", "What screws mount it?", "#8 wood screws (4.2 mm)", measure=("hole_diameter_mm", 4.5, 0.3, "mm")),
        Question("depth", "How far does it reach out from the wall?", "8 in (200 mm)", measure=("depth_mm", 200.0, 5.0, "mm")),
        Question("wall", "How thick?", "4 mm walls with a diagonal brace", measure=("min_wall_mm", 4.0, 0.5, "mm")),
        Question("material", "Print material?", "PETG", ("PETG", "PLA", "ASA")),
    )),
    Family("bridge", ("bridge", "trestle", "viaduct", "overpass", "span"), (
        Question("span", "How long a gap does it cross?", "12 in (300 mm)", measure=("width_mm", 300.0, 5.0, "mm")),
        Question("use", "What crosses it?", "toy cars and trains (a model bridge, not a load-bearing one)"),
        Question("style", "Which style?", "arch", ("arch", "beam", "truss", "suspension")),
        Question("deck", "How wide is the deck?", "3 in (76 mm)", measure=("depth_mm", 76.0, 3.0, "mm")),
    )),
    Family("hook", ("hook", "hanger", "coat hook", "peg"), (
        Question("load", "What hangs on it?", "a coat or a bag, up to 10 lb (4.5 kg)"),
        Question("mount", "How does it attach?", "two screws", ("two screws", "adhesive strip", "over the door")),
        Question("reach", "How far out does it stick?", "2 in (50 mm)", measure=("depth_mm", 50.0, 5.0, "mm")),
    )),
    Family("enclosure", ("box", "case", "enclosure", "container", "housing"), (
        Question("contents", "What goes inside, and its size?", "a small circuit board, 2 x 3 x 1 in (50 x 76 x 25 mm)"),
        Question("lid", "What kind of lid?", "snap-fit", ("snap-fit", "screws", "sliding", "hinged")),
        Question("openings", "Any holes for cables, buttons or air?", "one cable hole on a short side"),
        Question("wall", "Wall thickness?", "2 mm", measure=("min_wall_mm", 2.0, 0.3, "mm")),
    )),
    Family("knob", ("knob", "handle", "dial", "pull"), (
        Question("shaft", "What shaft does it fit?", "6 mm D-shaft", measure=("hole_diameter_mm", 6.2, 0.15, "mm")),
        Question("size", "How big across?", "1.25 in (32 mm)", measure=("diameter_mm", 32.0, 1.0, "mm")),
        Question("grip", "Grip style?", "knurled", ("knurled", "smooth", "fluted", "pointer")),
    )),
    Family("stand", ("stand", "holder", "dock", "cradle"), (
        Question("device", "What does it hold?", "a phone in its case, up to 0.5 in (12 mm) thick"),
        Question("angle", "Viewing angle?", "60 degrees back from flat"),
        Question("cable", "A slot for the charging cable?", "yes", ("yes", "no")),
    )),
    Family("figurine", ("figurine", "statue", "sculpture", "character", "animal", "dog", "cat", "miniature", "bust"), (
        Question("subject", "What should it show, and doing what?", "as described, standing on a round base"),
        Question("size", "How tall?", "3 in (76 mm)", measure=("height_mm", 76.0, 6.0, "mm")),
        Question("base", "On a base?", "yes, a round base 2 in (50 mm) across", ("yes", "no")),
    ), route="blender", notes=("Organic shapes come from a found model or a mesh edited in Blender; FreeCAD adds the base and checks the print.",)),
)
GENERIC = Family("part", (), (
    Question("purpose", "What is it for, and what does it attach to or hold?", "as you described it"),
    Question("size", "Roughly how big?", "palm-sized, about 3 in (76 mm) across"),
    Question("material", "Print material?", "PLA", ("PLA", "PETG", "TPU")),
))

#: How engineered parts are built well in FreeCAD (ORDER-2026-10-18-02 C).
BUILD_RULES: tuple[str, ...] = (
    "Engineered parts: a PartDesign Body; fully constrained sketches; Pad/Pocket/Revolution/Loft; named sizes in a 'Params' "
    "spreadsheet so edit_object can change them later.",
    "Edges: fillet outside edges at least 0.5 mm, chamfer the bottom edge 0.4 mm (stops elephant's foot); no knife edges.",
    "Clearances for parts that fit together: press fit 0.1 mm, sliding fit 0.3 mm, loose fit 0.5 mm per side; screw holes "
    "0.3 mm over the screw; nut traps 0.2 mm over the nut.",
    "Walls at least two nozzle widths (user_preferences gives the nozzle); bosses around screws twice the screw diameter.",
    "Overhangs at most 45 degrees or a chamfer under them; pick the print orientation with the flattest face down.",
    "Several parts: one Body each inside an App::Part, with the clearance between them stated; check with contract_check "
    "(clearance_mm, no_collisions).",
    "Route: measured or mechanical shapes in FreeCAD; organic or sculpted shapes as meshes in Blender (mesh_edit, swap_part); "
    "a mesh and a FreeCAD part can be combined at the end (mesh_edit boolean).",
)


def family_for(request: str) -> Family:
    text = request.casefold()
    best: tuple[int, Family] | None = None
    for family in FAMILIES:
        hits = sum(1 for word in family.words if re.search(r"\b" + re.escape(word) + r"s?\b", text))
        if hits and (best is None or hits > best[0]):
            best = (hits, family)
    return best[1] if best else GENERIC


def plan_questions(request: str, questions_preference: str = "few", *, material_default: str = "") -> dict[str, Any]:
    """The questions to ask (at most three) and the defaults assumed for the rest."""
    family = family_for(request)
    questions = list(family.questions)
    if material_default:
        questions = [Question(q.key, q.ask, f"{material_default} (your Setup choice)", q.options, q.measure) if q.key == "material" else q
                     for q in questions]
    just_make_it = questions_preference == "none" or bool(re.search(r"\bjust (make|build|do) it\b", request, re.I))
    asked = [] if just_make_it else questions[:MAX_ASKED]
    assumed = [q for q in questions if q not in asked]
    return {
        "family": family.name,
        "route": family.route,
        "ask": [q.line(i) for i, q in enumerate(asked, start=1)],
        "assumed_defaults": [f"{q.ask[:-1] if q.ask.endswith('?') else q.ask}: {q.default}" for q in assumed],
        "how_to_ask": ("Do not ask anything: use the defaults and say in one line which ones you used." if just_make_it else
                       "Ask these in ONE short message, numbered, each with its default; the user can answer 'defaults' or one word each. "
                       "Then state the assumed defaults in one line and build."),
        "record_with": record_fields(family, {}),
        "notes": list(family.notes),
        "build_rules": list(BUILD_RULES) if family.route in ("freecad", "either") else list(BUILD_RULES[-1:]),
    }


def record_fields(family: Family, answers: dict[str, str]) -> dict[str, Any]:
    """design_record(action='update') fields: measurable answers as requirements
    contract_check can test, the rest as assumptions."""
    requirements, assumptions = [], []
    for question in family.questions:
        answer = answers.get(question.key, question.default)
        if question.measure is not None and question.key not in answers:
            metric, target, tolerance, unit = question.measure
            requirements.append({"name": question.key, "metric": metric, "target": target, "tolerance": tolerance, "unit": unit,
                                 "kind": "objective", "note": f"{question.ask} {answer}"})
        else:
            assumptions.append(f"{question.key}: {answer}")
    return {"requirements": requirements, "assumptions": assumptions}
