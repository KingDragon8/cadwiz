# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""The plug-in's door into the founder's running FreeCAD (ORDER-2026-10-12-05).

A tiny HTTP server on 127.0.0.1 (never another machine), started with the CADWiz
workbench. Every request must carry the secret token written, with the port, to
`%LOCALAPPDATA%\\CADWiz\\plugin\\bridge.json` -- a file only the founder's own
account can read. A request is queued; FreeCAD's window thread runs it (FreeCAD
documents may only be touched there) from a short timer, and long work inside
it (the headless worker) keeps pumping the window, so FreeCAD keeps answering.

The MCP server (`server.py`, started by Claude Desktop) is the only client. It
says hello every 30 seconds, which is what the slim panel's connection light
reads ("Connected to Claude").
"""
from __future__ import annotations

import json
import os
import queue
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

from integrations.cadwiz_plugin.session import plugin_data_dir

#: How long after the last hello the panel still says "Connected to Claude".
CONNECTED_WITHIN_S = 90.0
#: How long one request may take before the client is told (the work goes on).
REQUEST_TIMEOUT_S = 900.0


def bridge_file(pid: int | None = None) -> Path:
    """One connection file per FreeCAD process, so a second FreeCAD (a test run)
    never takes over the founder's; the MCP server uses the newest one that answers."""
    return plugin_data_dir() / "bridges" / f"{pid or os.getpid()}.json"


def app_of(client: str) -> str:
    """Which AI app a hello came from: "chatgpt" for ChatGPT and its Codex app,
    else "claude" -- every client before ORDER-2026-10-19-02 was Claude Desktop."""
    name = client.lower()
    return "chatgpt" if any(word in name for word in ("chatgpt", "codex")) else "claude"


class Bridge:
    def __init__(self, call: Callable[[str, dict], dict], *, run_on_gui: Callable[[Callable[[], None]], None] | None = None,
                 port: int = 0, info_path: Path | None = None) -> None:
        self._call = call
        self._jobs: "queue.Queue[tuple[str, dict, dict, threading.Event]]" = queue.Queue()
        self._run_on_gui = run_on_gui
        self.token = secrets.token_urlsafe(24)
        self.info_path = info_path or bridge_file()
        self.last_hello = 0.0
        self.client = ""
        #: Each AI app's own last hello (ORDER-2026-10-19-02): Claude and ChatGPT
        #: can both be connected, each through its own copy of the MCP server.
        self.hellos: dict[str, float] = {}
        self.busy = False
        bridge = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args: Any) -> None:  # quiet
                return

            def do_POST(self) -> None:  # noqa: N802
                if self.headers.get("X-CADWiz-Token") != bridge.token:
                    self.send_error(403)
                    return
                length = int(self.headers.get("Content-Length") or 0)
                try:
                    body = json.loads(self.rfile.read(length) or b"{}")
                except ValueError:
                    self.send_error(400)
                    return
                if self.path == "/hello":
                    bridge.last_hello = time.time()
                    bridge.client = str(body.get("client", ""))
                    bridge.hellos[app_of(bridge.client)] = bridge.last_hello
                    reply = {"ok": True, "freecad_pid": os.getpid()}
                else:
                    reply = bridge.submit(str(body.get("tool", "")), dict(body.get("arguments") or {}))
                data = json.dumps(reply, default=str).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self._server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, name="cadwiz-plugin-bridge", daemon=True)

    # ---- lifecycle -------------------------------------------------------------------
    def start(self) -> "Bridge":
        self._thread.start()
        self.info_path.parent.mkdir(parents=True, exist_ok=True)
        self.info_path.write_text(json.dumps({"port": self.port, "token": self.token, "pid": os.getpid(),
                                              "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}), encoding="utf-8")
        return self

    def stop(self) -> None:
        self._server.shutdown()
        try:
            data = json.loads(self.info_path.read_text(encoding="utf-8"))
            if data.get("pid") == os.getpid():
                self.info_path.unlink()          # our own connection file, written above; never a founder file
        except (OSError, ValueError):
            pass

    @property
    def connected(self) -> bool:
        return time.time() - self.last_hello < CONNECTED_WITHIN_S

    def connected_to(self, app: str) -> bool:
        """Whether that AI app ("claude" or "chatgpt") said hello lately. The newest
        hello counts for its own app even if it never reached `hellos` (a witness
        setting `last_hello` directly, as the panel witnesses do)."""
        latest = self.hellos.get(app, 0.0)
        if app == app_of(self.client):
            latest = max(latest, self.last_hello)
        return time.time() - latest < CONNECTED_WITHIN_S

    # ---- requests ----------------------------------------------------------------------
    def submit(self, tool: str, arguments: dict) -> dict:
        if self._run_on_gui is None:            # headless and tests: run right here
            return self._call(tool, arguments)
        box: dict = {}
        done = threading.Event()
        self._jobs.put((tool, arguments, box, done))
        if not done.wait(REQUEST_TIMEOUT_S):
            return {"ok": False, "say_to_founder": "That is taking a long time; FreeCAD is still working on it. Ask me what state it's in in a minute."}
        return box.get("reply") or {"ok": False, "say_to_founder": "Something inside CADWiz went wrong on that step, so I stopped it there; nothing of yours was lost."}

    def drain(self) -> None:
        """Called on FreeCAD's window thread by a timer: run the waiting requests,
        one at a time (never re-entered while one runs)."""
        if self.busy:
            return
        self.busy = True
        try:
            while True:
                try:
                    tool, arguments, box, done = self._jobs.get_nowait()
                except queue.Empty:
                    return
                try:
                    box["reply"] = self._call(tool, arguments)
                finally:
                    done.set()
        finally:
            self.busy = False


def start_in_freecad() -> Bridge | None:
    """Start the bridge inside the founder's FreeCAD (the workbench calls this once).
    Returns None outside a FreeCAD with a window."""
    try:
        import FreeCAD
        import FreeCADGui
        from PySide import QtCore, QtWidgets
    except ImportError:
        return None
    from integrations.cadwiz_plugin.session import PluginSession

    def pump() -> None:
        QtWidgets.QApplication.processEvents()

    session = PluginSession(app=FreeCAD, gui=FreeCADGui, pump=pump)
    bridge = Bridge(session.call, run_on_gui=lambda fn: fn())
    bridge.session = session  # type: ignore[attr-defined]
    timer = QtCore.QTimer()
    timer.setInterval(100)
    timer.timeout.connect(bridge.drain)
    timer.start()
    bridge.timer = timer  # type: ignore[attr-defined]   # kept alive with the bridge
    return bridge.start()
