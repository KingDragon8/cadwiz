# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""The founder's preferences: set on the Setup page, read and followed by Claude.

ORDER-2026-10-18-03 (section 2.6, Setup): "How Claude works with you" --
Explanations, Questions before building, Before big changes -- are settings
Claude reads through the connector (`user_preferences`) and follows. Teaching
itself lives in the Claude app; the panel only holds the preference. The workshop
(printers, nozzle, materials, slicer, units, text size), models and licences, and
saving and versions are kept here too.

One honest limit, stated where it applies: CADWiz never deletes a version (the
founder's own rule), so "how many versions" is how many the time slider shows,
not how many are kept on disk.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from typing import Any

EXPLANATIONS = {"just_do_it": "Just do it", "short": "Short and plain", "teach": "Teach me as we go"}
QUESTIONS = {"few": "A few, with defaults", "none": "None, use defaults"}
BIG_CHANGES = {"ask": "Ask me first", "go_ahead": "Go ahead, I can go back"}
LICENCE_CHOICES = {"personal_ok": "Personal use is fine", "sellable_only": "Only ones I can sell"}
QUALITIES = {"standard": "Standard", "fine": "Fine", "fast": "Fast"}
TEXT_SIZES = (18, 20, 22, 24)
MODEL_SITES = ("Printables", "Thingiverse", "MakerWorld")


@dataclass(slots=True)
class Printer:
    name: str
    bed_x_mm: float = 220.0
    bed_y_mm: float = 220.0
    bed_z_mm: float = 250.0
    nozzle_mm: float = 0.4

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("a printer needs a name")
        for value in (self.bed_x_mm, self.bed_y_mm, self.bed_z_mm, self.nozzle_mm):
            if value <= 0:
                raise ValueError("printer sizes must be positive")


#: Which AI app he talks to (ORDER-2026-10-19-02): picked at the top of the Creating
#: page; "auto" = whichever of them is connected.
AI_APPS = {"auto": "Whichever app I have open", "claude": "Claude", "chatgpt": "ChatGPT"}


@dataclass(slots=True)
class FounderPreferences:
    # The AI app he talks to
    ai_app: str = "auto"
    # My workshop
    printers: list[Printer] = field(default_factory=lambda: [Printer("My printer")])
    default_printer: str = "My printer"
    materials_on_hand: str = "PLA, PETG, TPU"
    print_material: str = "PLA"
    print_quality: str = "standard"
    slicer: str = "UltiMaker Cura"
    inches_first: bool = True
    text_px: int = 18
    # How Claude works with you
    explanations: str = "short"
    questions: str = "few"
    big_changes: str = "ask"
    # Models and licences
    licences: str = "personal_ok"
    model_sites: list[str] = field(default_factory=lambda: list(MODEL_SITES))
    # Saving and versions
    project_folder: str = ""
    versions_shown: int = 20

    def __post_init__(self) -> None:
        for name, allowed in (("explanations", EXPLANATIONS), ("questions", QUESTIONS), ("big_changes", BIG_CHANGES),
                              ("licences", LICENCE_CHOICES), ("print_quality", QUALITIES), ("ai_app", AI_APPS)):
            if getattr(self, name) not in allowed:
                raise ValueError(f"{name} must be one of {', '.join(allowed)}")
        if self.text_px not in TEXT_SIZES:
            raise ValueError(f"text size must be one of {TEXT_SIZES}")
        if not 1 <= int(self.versions_shown) <= 500:
            raise ValueError("versions shown must be between 1 and 500")
        if not self.printers:
            raise ValueError("keep at least one printer")
        if self.default_printer not in [p.name for p in self.printers]:
            self.default_printer = self.printers[0].name

    @property
    def printer(self) -> Printer:
        return next(p for p in self.printers if p.name == self.default_printer)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "FounderPreferences":
        """Tolerant read: unknown keys are ignored and a bad value falls back to
        its default, so a hand-edited file never stops the panel."""
        data = dict(data or {})
        known = {f.name for f in fields(cls)}
        clean: dict[str, Any] = {}
        for key, value in data.items():
            if key not in known:
                continue
            if key == "printers":
                printers = []
                for item in value or []:
                    try:
                        printers.append(Printer(**{k: v for k, v in dict(item).items() if k in Printer.__dataclass_fields__}))
                    except (TypeError, ValueError):
                        continue
                if printers:
                    clean[key] = printers
                continue
            clean[key] = value
        try:
            return cls(**clean)
        except (TypeError, ValueError):
            good = cls()
            for key, value in clean.items():
                trial = cls.to_dict(good) | {key: value}
                trial["printers"] = [Printer(**p) if isinstance(p, dict) else p for p in trial["printers"]]
                try:
                    good = cls(**trial)
                except (TypeError, ValueError):
                    continue
            return good

    # ---- what Claude is told -------------------------------------------------------------
    def rules_for_claude(self) -> list[str]:
        """The preferences as plain rules Claude follows in every reply."""
        printer = self.printer
        rules = [
            {"just_do_it": "Explanations: just do it -- one short line on what changed, no teaching.",
             "short": "Explanations: short and plain -- a sentence or two, no jargon.",
             "teach": "Explanations: teach as you go -- say briefly why, and name the FreeCAD idea in plain words."}[self.explanations],
            {"few": "Questions before building: at most three that change the design, each with a default the user can accept in one word.",
             "none": "Questions before building: none -- use sensible defaults and say in one line which ones you used."}[self.questions],
            {"ask": "Before big changes (replacing a part, rebuilding the whole model, deleting features): describe it and wait for their yes.",
             "go_ahead": "Before big changes: go ahead -- every change is a version the user can go back to; say what you did."}[self.big_changes],
            {"personal_ok": "Downloaded models: personal-use licences are fine; still say the licence of each.",
             "sellable_only": "Downloaded models: only offer ones the user can sell (no 'non-commercial' licences); say the licence of each."}[self.licences],
            "Sizes: " + ("inches first, millimetres beside." if self.inches_first else "millimetres first, inches beside."),
            f"His printer: {printer.name}, bed {printer.bed_x_mm:g} x {printer.bed_y_mm:g} x {printer.bed_z_mm:g} mm, nozzle {printer.nozzle_mm:g} mm; "
            f"material {self.print_material} (on hand: {self.materials_on_hand}); quality {QUALITIES[self.print_quality]}.",
            "When searching for models, look on: " + ", ".join(self.model_sites) + ".",
        ]
        return rules
