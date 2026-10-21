# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""The AI-master architecture (ORDER-2026-10-11-03, founder ruling 2026-10-11).

    The frontier master owns understanding and design.
    CADWiz owns truth, memory, execution, evidence, safety and editability.
    FreeCAD owns geometry.

Chain of command: Founder > hard safety envelope > master AI > CADWiz execution
> FreeCAD. Nothing below a level can override it.

This package is the CADWiz half, domain-neutral (no FreeCAD, no vendor, no
network): the Design Contract the master authors and CADWiz stores and checks
(`design_contract`), the persistent design source the master patches
incrementally (`design_source`), the editability standard E0-E4
(`editability`), the deterministic fact layer that reports and never redesigns
(`fact_layer`), units with inches and millimetres side by side (`units`), the
per-project store (`project_store`), the provider-neutral master adapter and
coarse tools (`master_adapter`, `tools`), the loop (`loop`) and the switch
(`flags`). FreeCAD-facing pieces live in `integrations.ai_master`.
"""
from __future__ import annotations

from .units import Quantity, parse_quantity

__all__ = ["Quantity", "parse_quantity"]
