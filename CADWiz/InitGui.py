# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""CADWiz for FreeCAD: lets Claude Desktop see, measure, build and edit your models."""


def _start() -> None:
    import sys
    import traceback
    from pathlib import Path

    import FreeCAD

    try:
        here = Path(FreeCAD.getUserAppDataDir()) / "Mod" / "CADWiz"
        for candidate in (Path(__file__).resolve().parent if "__file__" in globals() else None, here):
            if candidate is not None and (candidate / "src" / "integrations").is_dir():
                here = candidate
                break
        source = str(here / "src")
        if source not in sys.path:
            sys.path.insert(0, source)
        from integrations.cadwiz_plugin.addon import register

        register()
    except Exception:  # noqa: BLE001 - FreeCAD must still start
        FreeCAD.Console.PrintError("CADWiz could not start:\n" + traceback.format_exc())


_start()
