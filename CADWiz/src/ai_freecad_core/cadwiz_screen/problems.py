# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Problems and fixes: what the Creating and Printing pages list (ORDER-2026-10-18-03).

Each problem is said in plain words with both units, says how to resolve it,
and names what to highlight for "Show me". The technical detail (FreeCAD's own
error text) is kept apart in `detail_for_claude`: it goes to Claude when the
founder presses "Ask Claude to fix" and is never shown to him (the standing
rule: no raw errors on his screen).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from ai_freecad_core.visual_communications.anchored import inches_first

#: kind -> (plain heading, how to resolve it)
KINDS: dict[str, tuple[str, str]] = {
    "connection": ("Your assistant can't reach CADWiz", "Open your assistant app (Claude Desktop, or the ChatGPT app), or quit it fully and open it again; the light turns green within a minute."),
    "rebuild": ("A step of the model failed to rebuild", "Ask Claude to fix it, or go back to the last version that rebuilt."),
    "sketch_open": ("A sketch has a gap in its outline", "Close the gap so the outline is one closed loop; your assistant can find and join the ends."),
    "sketch_broken": ("A sketch's rules contradict each other", "Remove the clashing rule (constraint); your assistant can find which one."),
    "loose": ("A loose piece", "Move it until it touches, or join it; on its own it prints as a separate piece or falls over."),
    "overlap": ("Two parts overlap", "Fine if they are meant to print as one; otherwise move one so they only touch."),
    "mesh_holes": ("The mesh has holes", "Repair it before printing (your assistant can run the mesh repair); a slicer may print it wrong."),
    "overhang": ("Steep overhangs", "Add supports in the slicer, turn the model, or add a chamfer under the overhang."),
    "thin": ("Thin walls", "Make the walls thicker than your nozzle can print, or the printer will skip them."),
    "bed": ("Too big for the bed", "Scale it down, turn it, or split it into parts."),
    "watertight": ("Not a closed solid", "Repair the mesh or close the open faces so the slicer sees a solid."),
}


#: "Explain": why it matters, in a few plain sentences (no FreeCAD jargon unexplained).
EXPLAIN: dict[str, str] = {
    "connection": "CADWiz talks to Claude through a small connector the Claude app starts. While it is not connected, Claude "
                  "can't look at your model, measure it or change it. Nothing of yours is lost.",
    "rebuild": "FreeCAD builds a model step by step, each step from the one before. When one step can't be made (a fillet too "
               "big for its edge, a pocket that cuts nothing, a sketch that moved), that step and the ones after it go wrong.",
    "sketch_open": "A sketch is the flat outline a solid is made from. FreeCAD can only make a solid from an outline that closes "
                   "on itself; even a tiny gap between two ends stops it.",
    "sketch_broken": "A sketch's rules (constraints) fix sizes and positions -- 'this line is 40 mm', 'these two are parallel'. "
                     "When two rules ask for different things, FreeCAD can't satisfy both and stops.",
    "loose": "Everything you print sits on the bed together. A piece that doesn't touch the rest prints on its own: it may "
             "fall over, or come off as a separate part.",
    "overlap": "Two parts that overlap print as one solid. That is often what you want; if they should come apart, move one.",
    "mesh_holes": "A mesh is a surface of tiny triangles. Missing triangles or torn edges leave holes, and a slicer can't tell "
                  "inside from outside, so it may leave walls out or fill the wrong side.",
    "overhang": "Each printed layer has to sit on the one below. Parts that lean out further than about 45 degrees have "
                "nothing under them and droop unless supported.",
    "thin": "The nozzle lays plastic about as wide as the nozzle itself. A wall thinner than two lines of plastic is skipped or "
            "prints weak.",
    "bed": "The printer can only print what fits on its bed and under its height.",
    "watertight": "A slicer needs a closed surface to know what is solid. An open edge anywhere makes that guess unreliable.",
}


@dataclass(slots=True)
class Problem:
    kind: str
    what: str                              # plain words, both units
    objects: list[str] = field(default_factory=list)       # what "Show me" selects
    elements: list[str] = field(default_factory=list)      # faces/edges, "Obj.Face3"
    detail_for_claude: str = ""

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"unknown problem kind {self.kind!r}")

    @property
    def heading(self) -> str:
        return KINDS[self.kind][0]

    @property
    def how_to_fix(self) -> str:
        return KINDS[self.kind][1]

    @property
    def key(self) -> str:
        return f"{self.kind}:{','.join(self.objects)}"

    @property
    def explanation(self) -> str:
        return EXPLAIN[self.kind]

    def for_founder(self) -> dict[str, object]:
        return {"heading": self.heading, "what": self.what, "how_to_fix": self.how_to_fix, "explain": self.explanation}

    def to_dict(self) -> dict[str, object]:
        return {**asdict(self), "heading": self.heading, "how_to_fix": self.how_to_fix}


def gap_words(name: str, other: str, gap_mm: float) -> str:
    """'the Stick doesn't touch the Jaw: a 0.02 in (0.5 mm) gap means it prints as a loose piece'"""
    return f"{name} doesn't touch {other}: a {inches_first(gap_mm)} gap means it prints as a loose piece"


def overlap_words(name: str, other: str, volume_mm3: float) -> str:
    cubic_in = volume_mm3 / 16387.064
    return f"{name} and {other} overlap by {cubic_in:.3g} cubic in ({volume_mm3:.3g} cubic mm)"


def from_print_notes(notes: list[str]) -> list[Problem]:
    """The print check's notes as Printing-page problems."""
    import re

    words = (("bed", r"\bbed\b"), ("thin", r"\b(walls?|thin)\b"), ("overhang", r"\boverhangs?\b"),
             ("watertight", r"\b(manifold|watertight|not closed|open edges?)\b"), ("loose", r"\b(loose|separate)\b"))
    problems = []
    for note in notes:
        lowered = note.lower()
        kind = next((name for name, pattern in words if re.search(pattern, lowered)), None)
        if kind is not None:
            problems.append(Problem(kind, note[0].upper() + note[1:] if note else note))
    return problems


def summary_line(problems: list[Problem]) -> str:
    if not problems:
        return "No problems found: the model rebuilds, its sketches are closed, and every part touches the rest."
    return f"{len(problems)} problem{'s' if len(problems) != 1 else ''} found."
