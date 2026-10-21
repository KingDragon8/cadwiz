# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""The Connect button: get the assistant app connected without him having to know how
(ORDER-2026-10-20-01; ChatGPT added ORDER-2026-10-21-01).

Founder, 2026-10-20: "if it's not connected, can you give me like a button to
connect it, and it goes through the process." The connection is made by the
assistant app itself: while it runs, its CADWiz connector checks in with FreeCAD
every 30 seconds (`server.py` heartbeat -> `bridge.py`). So the one thing a button
can usefully do is make sure the chosen app is running -- open it when it is not
-- and then say plainly what happened. It never closes an app: that would end the
user's conversations.

The app is the one chosen at the top of the panel: Claude (Claude Desktop) or
ChatGPT (the ChatGPT desktop app, which is the Codex package on Windows).
"Whichever I have open" waits for a running one, or opens Claude Desktop, else
ChatGPT, whichever is installed.

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

#: For each app: how to recognise it running, and its Start-menu name.
APPS = {
    # the desktop app, not the coding tool's own claude.exe (which lives under claude-code)
    "claude": {"name": "Claude Desktop", "process": "claude", "not_path": "*claude-code*", "start": "Claude",
               "download": "claude.ai/download", "where": "Settings, Connectors"},
    "chatgpt": {"name": "the ChatGPT app", "process": "ChatGPT", "not_path": "", "start": "ChatGPT",
                "download": "chatgpt.com/download", "where": "Settings, MCP servers"},
}
FIND_APP = (
    "$p = Get-Process -Name {process} -ErrorAction SilentlyContinue | Where-Object {{ $_.Path {path_filter} }}; "
    "$a = Get-StartApps | Where-Object {{ $_.Name -eq '{start}' -and $_.AppID -notlike '*crx*' }} | Select-Object -First 1; "
    "Write-Output ('running=' + [bool]$p); Write-Output ('appid=' + $a.AppID)"
)


def say(stage: str, app: str = "claude") -> str:
    name, download = APPS[app]["name"], APPS[app]["download"]
    return {
        "checking": f"Checking {name}…",
        "opening": f"Opening {name}… it connects by itself in about half a minute.",
        "waiting": f"{name[0].upper() + name[1:]} is open; waiting for it to check in (up to a minute).",
        "connected": "Connected.",
        "no_app": f"I couldn't find {name} on this PC. Install it from {download}, then press Connect again.",
        "open_failed": f"Windows wouldn't open {name}. Open it from the Start menu, then press Connect again.",
        "app_silent": (f"{name[0].upper() + name[1:]} is open but its CADWiz connection isn't answering. Check that the CADWiz "
                       f"connector is switched on ({APPS[app]['where']}; run CADWiz's installer again if it isn't listed). If it "
                       f"is, quit the app fully -- right-click its icon by the clock and choose Quit -- and open it again."),
    }[stage]


#: Kept for the panel's tests and older callers: Claude's wording.
SAY = {stage: say(stage) for stage in ("checking", "opening", "waiting", "connected", "no_app", "open_failed", "app_silent")}


def ask_windows(app: str = "claude", timeout: float = 8.0) -> dict[str, Any]:
    """Is the app running, and how to open it (its Start-menu id)."""
    spec = APPS[app]
    script = FIND_APP.format(process=spec["process"], start=spec["start"],
                             path_filter=f"-and $_.Path -notlike '{spec['not_path']}'" if spec["not_path"] else "")
    done = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True, text=True,
                          timeout=timeout, creationflags=NO_WINDOW)
    found = dict(line.strip().split("=", 1) for line in done.stdout.splitlines() if "=" in line)
    return {"running": found.get("running", "").lower() == "true", "appid": found.get("appid", "").strip()}


def open_app(appid: str) -> None:
    subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{appid}"], creationflags=NO_WINDOW)  # noqa: S603,S607 - the user's own app


class Connector:
    """One press of Connect. `stage` is one of the stages in `say`; `poll(connected)` moves it on."""

    def __init__(self, ask: Callable[..., dict[str, Any]] = ask_windows, opener: Callable[[str], None] = open_app,
                 clock: Callable[[], float] = time.monotonic, app: str = "claude") -> None:
        self.ask, self.opener, self.clock = ask, opener, clock
        self.choice = app if app in APPS or app == "auto" else "claude"
        self.app = "claude" if self.choice == "auto" else self.choice
        self.stage = "checking"
        self.started = clock()
        self.opened = False
        self.thread = threading.Thread(target=self._work, name="cadwiz-connect", daemon=True)
        self.thread.start()

    def _look(self, app: str) -> dict[str, Any]:
        try:
            try:
                return self.ask(app)
            except TypeError:          # a stand-in that takes no app
                return self.ask()
        except Exception:  # noqa: BLE001 - not knowing is treated as not running
            return {"running": False, "appid": ""}

    def _work(self) -> None:
        candidates = list(APPS) if self.choice == "auto" else [self.app]
        found = {app: self._look(app) for app in candidates}
        running = [app for app in candidates if found[app].get("running")]
        if running:
            self.app, self.stage = running[0], "waiting"
            return
        installed = [app for app in candidates if found[app].get("appid")]
        if not installed:
            self.stage = "no_app"
            return
        self.app = installed[0]
        try:
            self.opener(found[self.app]["appid"])
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
        return say(self.stage, self.app)
