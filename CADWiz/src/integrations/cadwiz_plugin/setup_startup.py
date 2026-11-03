# SPDX-License-Identifier: LGPL-2.1-or-later
"""Fast panel startup; offline verification runs outside the window thread."""
from __future__ import annotations
import threading
import os
import subprocess
from pathlib import Path
from . import install_setup

status = {"code": "CW-SETUP-CHECKING", "message": "Checking the local connection setup…"}


def start(freecad) -> None:
    version = ".".join(str(x) for x in freecad.Version()[:3])
    home = Path(freecad.getHomePath())
    candidates = [home / "bin/python.exe", home / "bin/python", home / "Resources/bin/python",
                  home / "Contents/Resources/bin/python"]
    python = next((p for p in candidates if p.is_file()), None)
    addon = Path(__file__).resolve().parents[3]
    mod = Path(freecad.getUserAppDataDir()) / "Mod"

    def worker():
        global status
        try:
            if python is None:
                raise ValueError("CW-SETUP-PYTHON: FreeCAD's Python was not found. Use the advanced installer.")
            info = install_setup.record_runtime(addon, python, version)
            status = install_setup.repair_owned(info)
            moved = install_setup.relocate_duplicates(mod, addon)
            if moved:
                status = {"code": "CW-SETUP-DUPLICATE", "message": "An older CADWiz copy was kept outside FreeCAD's add-on folder. Undo is available; restart FreeCAD."}
            # Hash validation/extraction can take longer than the fast settings check.
            # It is wholly offline and never blocks FreeCAD's window.
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            checked = subprocess.run([str(python), str(addon / "src/integrations/cadwiz_plugin/offline_launcher.py"), "--check"],
                                     capture_output=True, text=True, timeout=60,
                                     creationflags=flags, env=dict(os.environ))
            if checked.returncode:
                raise ValueError(checked.stderr.strip() or "CW-SETUP-HELPER: The offline helper could not start. Reinstall CADWiz.")
        except Exception as error:
            status = {"code": "CW-SETUP-CHECK", "message": str(error)}
    threading.Thread(target=worker, name="cadwiz-local-check", daemon=True).start()
