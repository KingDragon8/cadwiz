# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""The Connect button: get the Claude app connected without him having to know how
(ORDER-2026-10-20-01).

Founder, 2026-10-20: "if it's not connected, can you give me like a button to
connect it, and it goes through the process." The connection is made by the
Claude app itself: while it runs, its CADWiz connector checks in with FreeCAD
every 30 seconds (`server.py` heartbeat -> `bridge.py`), whichever of the two was
opened first. So the one thing a button can usefully do is make sure the Claude
app is running -- open it when it is not -- and then say plainly what happened.
It never closes the Claude app: that would end his conversations.

All the slow parts (asking Windows which apps run, opening the app) happen on a
background thread; the panel only reads `stage` once a second.
"""
from __future__ import annotations

import subprocess
import threading
import time
from typing import Any, Callable

#: How long after pressing Connect the panel waits (amber) for the first check-in.
WAIT_S = 75.0
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

FIND_APP = (
    # the desktop app, not the coding tool's own claude.exe (which lives under claude-code)
    "$p = Get-Process -Name claude -ErrorAction SilentlyContinue | Where-Object { $_.Path -and $_.Path -notlike '*claude-code*' }; "
    "$a = Get-StartApps | Where-Object { $_.Name -eq 'Claude' -and $_.AppID -notlike '*crx*' } | Select-Object -First 1; "
    "Write-Output ('running=' + [bool]$p); Write-Output ('appid=' + $a.AppID)"
)

SAY = {
    "checking": "Checking the Claude app…",
    "opening": "Opening the Claude app… it connects by itself in about half a minute.",
    "waiting": "The Claude app is open; waiting for it to check in (up to a minute).",
    "connected": "Connected to Claude.",
    "no_app": "I couldn't find the Claude app on this PC. Install it from claude.ai/download, then press Connect again.",
    "open_failed": "Windows wouldn't open the Claude app. Open it from the Start menu, then press Connect again.",
    "app_silent": ("The Claude app is open but its CADWiz connection isn't answering. In the Claude app, check that the CADWiz "
                   "connector is switched on (Settings, Connectors). If it is, quit the Claude app fully -- right-click its icon "
                   "by the clock and choose Quit -- and open it again."),
}


def ask_windows(timeout: float = 8.0) -> dict[str, Any]:
    """Is the Claude desktop app running, and how to open it (its Start-menu id)."""
    done = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", FIND_APP], capture_output=True, text=True,
                          timeout=timeout, creationflags=NO_WINDOW)
    found = dict(line.strip().split("=", 1) for line in done.stdout.splitlines() if "=" in line)
    return {"running": found.get("running", "").lower() == "true", "appid": found.get("appid", "").strip()}


def open_app(appid: str) -> None:
    subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{appid}"], creationflags=NO_WINDOW)  # noqa: S603,S607 - his own Claude app


class Connector:
    """One press of Connect. `stage` is one of SAY's keys; `poll(connected)` moves it on."""

    def __init__(self, ask: Callable[[], dict[str, Any]] = ask_windows, opener: Callable[[str], None] = open_app,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.ask, self.opener, self.clock = ask, opener, clock
        self.stage = "checking"
        self.started = clock()
        self.opened = False
        self.thread = threading.Thread(target=self._work, name="cadwiz-connect", daemon=True)
        self.thread.start()

    def _work(self) -> None:
        try:
            found = self.ask()
        except Exception:  # noqa: BLE001 - not knowing is treated as not running
            found = {"running": False, "appid": ""}
        if found.get("running"):
            self.stage = "waiting"
            return
        if not found.get("appid"):
            self.stage = "no_app"
            return
        try:
            self.opener(found["appid"])
        except Exception:  # noqa: BLE001
            self.stage = "open_failed"
            return
        self.opened, self.stage = True, "opening"

    def poll(self, connected: bool) -> str:
        if connected:
            self.stage = "connected"
        elif self.stage in ("waiting", "opening") and self.clock() - self.started > WAIT_S:
            self.stage = "app_silent"
        return self.stage

    @property
    def busy(self) -> bool:
        return self.stage in ("checking", "opening", "waiting")

    @property
    def words(self) -> str:
        return SAY[self.stage]
