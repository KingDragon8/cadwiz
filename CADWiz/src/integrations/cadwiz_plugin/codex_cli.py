# SPDX-License-Identifier: LGPL-2.1-or-later
"""Discover the user's CLI and check login without inference or reading tokens.

CAD communication reuses CADWiz's existing authenticated STDIO MCP adapter.
No desktop app, second provider manager, automatic login or model execution.
"""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys


def find_command(*, which=shutil.which, home=None, platform=None):
    platform, home = platform or sys.platform, Path(home or Path.home())
    candidates = [which("codex")]
    if platform == "win32":
        candidates += [str(Path(os.environ.get("APPDATA", home / "AppData/Roaming")) / "npm/codex.cmd")]
    else:
        candidates += [str(home / ".local/bin/codex"), "/opt/homebrew/bin/codex", "/usr/local/bin/codex"]
        candidates += [str(p) for p in sorted((home / ".nvm/versions/node").glob("*/bin/codex"), reverse=True)]
    for raw in candidates:
        if not raw:
            continue
        path = Path(raw).expanduser().resolve()
        if not path.is_file():
            continue
        if platform == "win32" and path.suffix.lower() in (".cmd", ".bat", ".ps1"):
            # Invoke the actual npm entry using Node; never run a shell wrapper.
            script = path.parent / "node_modules/@openai/codex/bin/codex.js"
            node = path.parent / "node.exe"
            node_path = str(node) if node.is_file() else which("node")
            if script.is_file() and node_path and Path(node_path).is_file():
                return [str(Path(node_path).resolve()), str(script)]
            continue
        if platform != "win32" and not os.access(path, os.X_OK):
            continue
        if platform != "win32" and path.suffix.lower() == '.js':
            sibling_node = Path(raw).expanduser().parent / 'node'
            if sibling_node.is_file() and os.access(sibling_node, os.X_OK):
                return [str(sibling_node.resolve()), str(path)]
        return [str(path)]
    return None


def probe(*, command=None, runner=subprocess.run):
    """Fixed commands only. Never return raw process output (may contain a key)."""
    command = command or find_command()
    if not command:
        return {"installed": False, "authenticated": False, "state": "Not Installed",
                "guidance": "Install Codex CLI from the official OpenAI instructions. ChatGPT Desktop is not required."}
    base = {"installed": True, "authenticated": False, "command": command, "state": "Installed"}
    options = {"capture_output": True, "text": True, "timeout": 12, "check": False}
    if sys.platform == "win32":
        options["creationflags"] = subprocess.CREATE_NO_WINDOW
    try:
        version = runner([*command, "--version"], **options)
        if version.returncode:
            return {**base, "guidance": "Codex was found but cannot run. Repair its CLI installation or select a compatible runtime."}
        login = runner([*command, "login", "status"], **options)
        words = (login.stdout + login.stderr).lower()
        signed_in = login.returncode == 0 and ('logged in' in words or 'authenticated' in words)
        mode = "api" if "api key" in words else "account" if signed_in else "none"
        return {**base, "authenticated": signed_in, "auth_mode": mode,
                "state": "Authenticated" if signed_in else "Installed",
                "guidance": "Connect the existing CADWiz MCP tools, then inspect a model to verify CAD readiness."
                    if signed_in else "Run codex login in your terminal and approve sign-in yourself. Then check again."}
    except (OSError, subprocess.SubprocessError):
        return {**base, "guidance": "Codex did not answer within the time limit. Check its installation and login locally, then retry."}


def connection_status(result, bridge=None):
    """Authentication, heartbeat and an actual CAD operation are separate facts."""
    state = dict(result)
    if not result.get("installed") or not result.get("authenticated"):
        return state
    if bridge is not None and bridge.connected_to("codex_cli"):
        state.update(state="Connected", guidance="MCP connected. Ask Codex CLI to inspect the open FreeCAD model.")
        if hasattr(bridge, "cad_ready_to") and bridge.cad_ready_to("codex_cli"):
            state.update(state="CAD Ready", guidance="An actual CAD operation succeeded through the connected adapter.")
    return state
