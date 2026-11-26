# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Authenticated loopback reconnect requests to the actual MCP connector."""
from __future__ import annotations

import contextlib
import errno
import http.client
import json
import logging
import os
import secrets
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Callable
from integrations.cadwiz_plugin.loopback_http import LoopbackHTTPServer, opener

RECONNECT_BUDGET_S = 12.0
RECONNECT_TIMEOUT_S = 5.5  # The connector's authenticated hello itself allows five seconds.
RECONNECT_ATTEMPTS = 3
RECONNECT_RETRY_DELAY_S = .1
LOG = logging.getLogger(__name__)


def _transient_confirmation_error(error: Exception) -> bool:
    if isinstance(error, urllib.error.HTTPError):
        return False  # Denied requests and other HTTP failures are not lost confirmations.
    if isinstance(error, urllib.error.URLError):
        error = error.reason
    return (isinstance(error, (ConnectionAbortedError, ConnectionResetError, TimeoutError,
                              http.client.IncompleteRead, http.client.RemoteDisconnected))
            or isinstance(error, OSError) and error.errno in {
                errno.ECONNABORTED, errno.ECONNRESET, errno.ETIMEDOUT, errno.EPIPE, 10053, 10054, 10060})


def directory() -> Path:
    from integrations.cadwiz_plugin.session import plugin_data_dir
    return plugin_data_dir() / "connectors"


def start(app: str, reconnect: Callable[[], bool]) -> LoopbackHTTPServer:
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

    server = LoopbackHTTPServer(("127.0.0.1", 0), Handler)
    directory().mkdir(parents=True, exist_ok=True)
    (directory() / f"{os.getpid()}.json").write_text(json.dumps({
        "app": app, "pid": os.getpid(), "port": server.server_port, "token": token,
    }), encoding="utf-8")
    threading.Thread(target=server.serve_forever, name="cadwiz-reconnect", daemon=True).start()
    return server


def reconnect(app: str) -> bool:
    """Repeat only the idempotent hello check-in after a lost confirmation.

    This endpoint never runs CAD operations. Model tool requests in server._post
    are deliberately NOT retried: their effects may already have happened.
    """
    # This authenticated endpoint is strictly loopback. Never route its token
    # through a system proxy or an opener configured for unrelated web traffic.
    local_http = opener()
    deadline = time.monotonic() + RECONNECT_BUDGET_S
    paths = []
    for path in directory().glob("*.json"):
        with contextlib.suppress(OSError):
            paths.append((path.stat().st_mtime_ns, path))
    # Prefer a freshly launched connector over abandoned older process records.
    for _, path in sorted(paths, key=lambda item: item[0], reverse=True):
        with contextlib.suppress(OSError, ValueError, TimeoutError, KeyError, TypeError):
            info = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(info, dict) or info.get("app") != app:
                continue
            port = int(info['port'])
            if not 1 <= port <= 65535 or not isinstance(info.get('token'), str) or not info['token']:
                continue
            request = urllib.request.Request(
                f"http://127.0.0.1:{port}/reconnect", data=b"{}",
                headers={"X-CADWiz-Token": str(info['token'])}, method="POST",
            )
            for attempt in range(RECONNECT_ATTEMPTS):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                try:
                    with local_http.open(request, timeout=min(RECONNECT_TIMEOUT_S, remaining)) as response:
                        result = json.load(response)
                    if isinstance(result, dict) and result.get('app') == app and result.get('connected') is True:
                        return True
                    break
                except (OSError, ValueError, http.client.HTTPException) as error:
                    if not _transient_confirmation_error(error) or attempt+1 == RECONNECT_ATTEMPTS:
                        break
                    LOG.debug('Interrupted reconnect confirmation (%s); repeating hello only', type(error).__name__)
                    time.sleep(min(RECONNECT_RETRY_DELAY_S, max(0, deadline-time.monotonic())))
    return False
