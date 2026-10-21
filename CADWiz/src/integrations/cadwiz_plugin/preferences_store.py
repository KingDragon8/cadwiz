# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Where the founder's preferences live: `preferences.json` beside the plug-in's
other files (ORDER-2026-10-18-03). The Setup page writes it; the connector's
`user_preferences` tool reads it for Claude; the print check uses its printer.
"""
from __future__ import annotations

import contextlib
import json
from pathlib import Path
from typing import Any

from ai_freecad_core.cadwiz_screen.preferences import FounderPreferences


def preferences_path() -> Path:
    from integrations.cadwiz_plugin.session import plugin_data_dir

    return plugin_data_dir() / "preferences.json"


def load(path: Path | None = None) -> FounderPreferences:
    target = path or preferences_path()
    data: dict[str, Any] | None = None
    with contextlib.suppress(OSError, ValueError):
        data = json.loads(target.read_text(encoding="utf-8"))
    if data is None:
        data = _first_time_seed()
    return FounderPreferences.from_dict(data)


def save(preferences: FounderPreferences, path: Path | None = None) -> Path:
    target = path or preferences_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(preferences.to_dict(), indent=1), encoding="utf-8")
    return target


def _first_time_seed() -> dict[str, Any]:
    """The first time: carry over what the old panel's settings already knew
    (his slicer, materials and printer name), so he is not asked twice."""
    seed: dict[str, Any] = {}
    with contextlib.suppress(Exception):
        from integrations.freecad_native.panel_preferences import FreeCADPanelPreferencesStore

        old = FreeCADPanelPreferencesStore().load()
        if old.default_slicer:
            seed["slicer"] = old.default_slicer
        if old.preferred_materials:
            seed["materials_on_hand"] = old.preferred_materials
        if old.default_printer:
            seed["printers"] = [{"name": old.default_printer}]
            seed["default_printer"] = old.default_printer
    return seed


def printer_profile(preferences: FounderPreferences) -> Any:
    """His default printer as the print check's profile (walls: two nozzle widths)."""
    from ai_freecad_core.ai_master.fact_layer import PrinterProfile

    printer = preferences.printer
    return PrinterProfile(name=printer.name, bed_x_mm=printer.bed_x_mm, bed_y_mm=printer.bed_y_mm, bed_z_mm=printer.bed_z_mm,
                          min_wall_mm=round(2 * printer.nozzle_mm, 3))
