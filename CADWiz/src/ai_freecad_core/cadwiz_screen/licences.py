# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Model licences in plain words (ORDER-2026-10-18-02 B, -03 Printing).

"Flag non-commercial licences plainly." A downloaded model carries its licence
from import to the Printing page's licence line. The classification is
deliberately conservative: anything not recognised is "unknown -- check the
source page before selling", never assumed sellable.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LicenceReading:
    name: str                    # as given, e.g. "CC BY-NC 4.0"
    can_sell: bool | None        # None = unknown
    plain: str                   # the Printing page's licence line

    def to_dict(self) -> dict[str, object]:
        return {"licence": self.name, "can_sell": self.can_sell, "plain": self.plain}


_NON_COMMERCIAL = re.compile(r"\b(nc|non[- ]?commercial|noncommercial|personal use only|personal only)\b", re.I)
_OPEN = re.compile(r"\b(cc[- ]?by(?![- ]?nc)(?:[- ]?sa)?|cc0|public domain|mit|bsd|apache|gpl|lgpl|cc[- ]?by[- ]?nd)\b", re.I)
_STANDARD_DIGITAL = re.compile(r"standard digital file licen[cs]e", re.I)


def read_licence(text: str | None) -> LicenceReading:
    name = (text or "").strip()
    if not name:
        return LicenceReading("unknown", None, "licence unknown -- check the source page before printing to sell")
    if _NON_COMMERCIAL.search(name) or re.search(r"\bby[- ]?nc\b", name, re.I):
        return LicenceReading(name, False, f"{name}: personal, non-commercial -- fine for printing at home, not for selling")
    if _STANDARD_DIGITAL.search(name):
        return LicenceReading(name, False, f"{name}: personal use -- fine for printing at home, not for selling")
    if re.search(r"\bnd\b|no[- ]?deriv", name, re.I):
        return LicenceReading(name, True, f"{name}: can be sold, but must not be changed -- an edited copy may not be shared or sold")
    if _OPEN.search(name):
        attribution = " (credit the designer)" if re.search(r"\bby\b", name, re.I) else ""
        return LicenceReading(name, True, f"{name}: can be printed and sold{attribution}")
    return LicenceReading(name, None, f"{name}: not recognised -- check the source page before printing to sell")


def allowed_by(preference: str, reading: LicenceReading) -> bool:
    """Whether a model fits the founder's 'Models and licences' choice."""
    if preference == "sellable_only":
        return reading.can_sell is True
    return True
