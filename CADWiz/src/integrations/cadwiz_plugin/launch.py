# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""The CADWiz shortcut: one click opens FreeCAD and the user's assistant app together
(founder, 2026-10-23: "one CADWiz shortcut ... that opens FreeCAD and my assistant
app together").

The installer's shortcut runs this with FreeCAD's own windowless Python:

    <FreeCAD>\\bin\\pythonw.exe <CADWiz>\\src\\integrations\\cadwiz_plugin\\launch.py

so no console window flashes. It starts FreeCAD (unless it is already running),
then makes sure the assistant chosen at the top of the panel is open -- the same
look-up and open the panel's Connect button uses (`connect_claude`), and the same
rule: an app that is already running is left alone, and nothing is ever closed.
"Whichever I have open" opens nothing when one is running, else Claude Desktop,
else the ChatGPT app.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

if __package__ in (None, ""):  # run as a file by the shortcut: make `integrations` importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from integrations.cadwiz_plugin.connect_claude import APPS, NO_WINDOW, ask_windows, open_app  # noqa: E402


def freecad_exe() -> Path:
    """freecad.exe beside the Python running this (the shortcut uses FreeCAD's own)."""
    return Path(sys.executable).resolve().with_name("freecad.exe")


def freecad_running() -> bool:
    done = subprocess.run(["tasklist", "/FI", "IMAGENAME eq freecad.exe", "/NH"], capture_output=True, text=True,
                          timeout=10, creationflags=NO_WINDOW)
    return "freecad.exe" in done.stdout.lower()


def chosen_app() -> str:
    try:
        from integrations.cadwiz_plugin.preferences_store import load

        return load().ai_app
    except Exception:  # noqa: BLE001 - no preferences yet: "whichever I have open"
        return "auto"


def open_assistant(choice: str, ask: Callable[[str], dict[str, Any]] = ask_windows,
                   opener: Callable[[str], None] = open_app) -> str:
    """Open the chosen app unless it (or, for "auto", either) is already running.
    Returns what happened: 'running:<app>', 'opened:<app>' or 'none'."""
    candidates = list(APPS) if choice not in APPS else [choice]
    found = {}
    for app in candidates:
        try:
            found[app] = ask(app)
        except Exception:  # noqa: BLE001 - not knowing is treated as not running
            found[app] = {"running": False, "appid": ""}
    for app in candidates:
        if found[app].get("running"):
            return f"running:{app}"
    for app in candidates:
        if found[app].get("appid"):
            opener(found[app]["appid"])
            return f"opened:{app}"
    return "none"


def main(start: Callable[[list[str]], Any] = subprocess.Popen) -> int:
    exe = freecad_exe()
    if not freecad_running():
        start([str(exe)])
    open_assistant(chosen_app())
    return 0


if __name__ == "__main__":
    sys.exit(main())
