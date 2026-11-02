# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Authenticated loopback reconnect requests to the actual MCP connector."""
from __future__ import annotations

import contextlib
import json
import os
import secrets
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable


def directory() -> Path:
    from integrations.cadwiz_plugin.session import plugin_data_dir
    return plugin_data_dir() / "connectors"


def start(app: str, reconnect: Callable[[], bool]) -> ThreadingHTTPServer:
    token = secrets.token_urlsafe(24)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            if self.path != "/reconnect" or self.headers.get("X-CADWiz-Token") != token:
                self.send_error(403)
                return
            try:
                ok = reconnect()
            except Exception:
                ok = False
            data = json.dumps({"connected": bool(ok), "app": app}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    directory().mkdir(parents=True, exist_ok=True)
    (directory() / f"{os.getpid()}.json").write_text(json.dumps({
        "app": app, "pid": os.getpid(), "port": server.server_port, "token": token,
    }), encoding="utf-8")
    threading.Thread(target=server.serve_forever, name="cadwiz-reconnect", daemon=True).start()
    return server


def reconnect(app: str) -> bool:
    """Ask a connector to check in; never manufacture a heartbeat in the panel."""
    for path in directory().glob("*.json"):
        with contextlib.suppress(OSError, ValueError, TimeoutError, KeyError, TypeError):
            info = json.loads(path.read_text(encoding="utf-8"))
            if info.get("app") != app:
                continue
            request = urllib.request.Request(
                f"http://127.0.0.1:{int(info['port'])}/reconnect", data=b"{}",
                headers={"X-CADWiz-Token": str(info['token'])}, method="POST",
            )
            with urllib.request.urlopen(request, timeout=10) as response:
                if json.load(response).get("connected"):
                    return True
    return False
