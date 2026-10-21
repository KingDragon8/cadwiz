# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""CADWiz for FreeCAD: a panel to see, mark, measure, build and edit your models.

FreeCAD runs this file with separate global and local namespaces, so a function
defined here cannot see another one, or an import made at the top: everything
lives inside _start().
"""


def _start() -> None:
    import sys
    import traceback
    from pathlib import Path

    import FreeCAD

    def addon_folder() -> Path:
        # FreeCAD does not tell this file where it lives, and the two ways of
        # installing put the code at different depths: the installer at Mod/CADWiz,
        # the Addon Manager at Mod/CADWiz/CADWiz.
        mod = Path(FreeCAD.getUserAppDataDir()) / "Mod"
        candidates = [mod / "CADWiz" / "CADWiz", mod / "CADWiz"]
        candidates += sorted(p.parents[2] for p in mod.glob("*/CADWiz/src/integrations/cadwiz_plugin"))
        for candidate in candidates:
            if (candidate / "src" / "integrations" / "cadwiz_plugin").is_dir():
                return candidate
        raise FileNotFoundError(f"the CADWiz code (src/integrations/cadwiz_plugin) was not found under {mod}")

    try:
        source = str(addon_folder() / "src")
        if source not in sys.path:
            sys.path.insert(0, source)
        from integrations.cadwiz_plugin.addon import register

        register()
    except Exception:  # noqa: BLE001 - FreeCAD must still start
        FreeCAD.Console.PrintError("CADWiz could not start:\n" + traceback.format_exc())


_start()
