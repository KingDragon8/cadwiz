# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""CADWiz for FreeCAD: a panel to see, mark, measure, build and edit your models."""


def _addon_folder():
    """Where this addon's `src` folder is. FreeCAD runs this file without telling it
    where it lives, and the two ways of installing put the code at different depths:
    the installer at Mod/CADWiz, the Addon Manager at Mod/CADWiz/CADWiz."""
    from pathlib import Path

    import FreeCAD

    mod = Path(FreeCAD.getUserAppDataDir()) / "Mod"
    candidates = []
    if "__file__" in globals():
        candidates.append(Path(__file__).resolve().parent)
    candidates += [mod / "CADWiz" / "CADWiz", mod / "CADWiz"]
    candidates += sorted(p.parents[2] for p in mod.glob("*/CADWiz/src/integrations/cadwiz_plugin"))
    for candidate in candidates:
        if (candidate / "src" / "integrations" / "cadwiz_plugin").is_dir():
            return candidate
    raise FileNotFoundError(f"the CADWiz code (src/integrations/cadwiz_plugin) was not found under {mod}")


def _start() -> None:
    import sys
    import traceback

    import FreeCAD

    try:
        source = str(_addon_folder() / "src")
        if source not in sys.path:
            sys.path.insert(0, source)
        from integrations.cadwiz_plugin.addon import register

        register()
    except Exception:  # noqa: BLE001 - FreeCAD must still start
        FreeCAD.Console.PrintError("CADWiz could not start:\n" + traceback.format_exc())


_start()
