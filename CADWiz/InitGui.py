# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""CADWiz for FreeCAD: a panel to see, mark, measure, build and edit your models.

FreeCAD runs this file with separate global and local namespaces, so a function
defined here cannot see another one, or an import made at the top: everything
lives inside _start().
"""


def _start(startup_file=None) -> None:
    import sys
    import traceback
    from pathlib import Path

    import FreeCAD

    def addon_folder() -> Path:
        # Prefer the file actually executed; never silently import another copy.
        if startup_file:
            local = Path(startup_file).resolve().parent
            if (local / 'src/integrations/cadwiz_plugin/addon.py').is_file():
                return local
        mod = Path(FreeCAD.getUserAppDataDir()) / "Mod"
        candidates = []
        for folder in mod.iterdir() if mod.is_dir() else []:
            if folder.name.casefold() not in ('cadwiz', 'ai-freecad') or folder.is_symlink():
                continue
            for relative in ('src/integrations/cadwiz_plugin/addon.py',
                             'CADWiz/src/integrations/cadwiz_plugin/addon.py',
                             '*/CADWiz/src/integrations/cadwiz_plugin/addon.py'):
                candidates.extend(p.parents[3] for p in folder.glob(relative))
        candidates = list(dict.fromkeys(candidates))
        if len(candidates) == 1:
            return candidates[0]
        raise FileNotFoundError(f"CADWiz source candidates under {mod}: {len(candidates)}. Run Check Installation; repair from the release ZIP with FreeCAD closed.")

    try:
        source = str(addon_folder() / "src")
        if source not in sys.path:
            sys.path.insert(0, source)
        from integrations.cadwiz_plugin.addon import register

        register()
    except Exception:  # noqa: BLE001 - FreeCAD must still start
        FreeCAD.Console.PrintError("CADWiz could not start:\n" + traceback.format_exc())


_start(locals().get('__file__') or globals().get('__file__'))
