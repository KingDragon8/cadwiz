# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Dimensions with their unit, shown in inches and millimetres (founder addendum 5).

Every stored dimension keeps the unit the founder used; every display shows
both. FreeCAD works in millimetres, so `Quantity.mm` is what reaches geometry.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

#: Millimetres per unit. Only length units: that is what a design parameter is.
UNIT_TO_MM: dict[str, float] = {
    "mm": 1.0, "millimeter": 1.0, "millimetre": 1.0, "millimeters": 1.0, "millimetres": 1.0,
    "cm": 10.0, "centimeter": 10.0, "centimetre": 10.0,
    "m": 1000.0, "meter": 1000.0, "metre": 1000.0,
    "in": 25.4, "inch": 25.4, "inches": 25.4, '"': 25.4,
    "ft": 304.8, "foot": 304.8, "feet": 304.8,
}

_CANONICAL = {"millimeter": "mm", "millimetre": "mm", "millimeters": "mm", "millimetres": "mm",
              "centimeter": "cm", "centimetre": "cm", "meter": "m", "metre": "m",
              "inch": "in", "inches": "in", '"': "in", "foot": "ft", "feet": "ft"}

_QUANTITY_RE = re.compile(r"^\s*([-+]?\d+(?:\.\d+)?(?:\s+\d+/\d+)?|\d+/\d+)\s*([a-zA-Z\"]+)?\s*$")


class UnitError(ValueError):
    """A dimension without a usable length unit."""


def _canonical(unit: str) -> str:
    key = (unit or "").strip().lower()
    key = _CANONICAL.get(key, key)
    if key not in UNIT_TO_MM:
        raise UnitError(f"unknown length unit {unit!r}; use mm, cm, m, in or ft")
    return key


def fmt_num(value: float, places: int = 2) -> str:
    text = f"{value:.{places}f}".rstrip("0").rstrip(".")
    return text if text not in ("", "-0") else "0"


@dataclass(frozen=True, slots=True)
class Quantity:
    value: float
    unit: str = "mm"

    def __post_init__(self) -> None:
        object.__setattr__(self, "unit", _canonical(self.unit))
        object.__setattr__(self, "value", float(self.value))

    @property
    def mm(self) -> float:
        return self.value * UNIT_TO_MM[self.unit]

    @property
    def inches(self) -> float:
        return self.mm / 25.4

    def to(self, unit: str) -> "Quantity":
        unit = _canonical(unit)
        return Quantity(self.mm / UNIT_TO_MM[unit], unit)

    def native(self) -> str:
        """In the unit it was given: '2 in', '1.6 mm'."""
        return f"{fmt_num(self.value, 3)} {self.unit}"

    def display(self) -> str:
        """Both systems, the given unit first: '2 in (50.8 mm)' / '1.6 mm (0.063 in)'."""
        if self.unit == "in":
            return f"{fmt_num(self.value, 3)} in ({fmt_num(self.mm, 2)} mm)"
        if self.unit == "mm":
            return f"{fmt_num(self.value, 2)} mm ({fmt_num(self.inches, 3)} in)"
        return f"{self.native()} ({fmt_num(self.mm, 2)} mm / {fmt_num(self.inches, 3)} in)"

    def to_dict(self) -> dict[str, float | str]:
        return {"value": self.value, "unit": self.unit}

    @classmethod
    def from_dict(cls, data: dict) -> "Quantity":
        return cls(float(data["value"]), str(data.get("unit", "mm")))

    def close_to(self, other: "Quantity", tolerance_mm: float = 0.05) -> bool:
        return abs(self.mm - other.mm) <= tolerance_mm


def parse_quantity(text: str, default_unit: str = "mm") -> Quantity:
    """'2 in', '6 inches', '1.6mm', '4', '1 1/2 in' -> Quantity. Bare numbers take
    `default_unit`. Raises UnitError for anything else."""
    match = _QUANTITY_RE.match(str(text).replace("”", '"'))
    if not match:
        raise UnitError(f"not a dimension: {text!r}")
    number, unit = match.group(1), match.group(2)
    if "/" in number:
        whole, _, frac = number.rpartition(" ")
        num, den = frac.split("/")
        value = (float(whole) if whole else 0.0) + float(num) / float(den)
    else:
        value = float(number)
    return Quantity(value, unit or default_unit)


def both(mm: float) -> str:
    """A millimetre measurement shown both ways: '101.6 mm (4 in)'."""
    return Quantity(mm, "mm").display()
