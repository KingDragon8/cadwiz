# SPDX-License-Identifier: LGPL-2.1-or-later
"""Offline runtime discovery and narrowly scoped, reversible assistant setup.

No network access. No settings writes without an explicit connect action.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import time
import tomllib
from pathlib import Path

VERSION = "0.6.0"


def data_dir() -> Path:
    if os.environ.get("CADWIZ_SETUP_DIR"):
        return Path(os.environ["CADWIZ_SETUP_DIR"])
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "CADWiz"
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/CADWiz"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "CADWiz"


def config_path() -> Path:
    return Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "config.toml"


def atomic_write(path: Path, text: str) -> None:
    if path.is_symlink():
        raise ValueError("CW-SETUP-LINK: Choose a regular settings file; linked files are left untouched.")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        if path.exists():
            shutil.copymode(path, name)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def record_runtime(addon: Path, python: Path, freecad_version: str) -> dict:
    addon, python = addon.resolve(), python.resolve()
    if not python.is_file() or not (addon / "src/integrations/cadwiz_plugin/server.py").is_file():
        raise ValueError("CW-SETUP-RUNTIME: FreeCAD's Python or CADWiz connector was not found. Open FreeCAD again.")
    info = {"version": VERSION, "python": str(python), "addon": str(addon), "freecad_version": freecad_version}
    atomic_write(data_dir() / "runtime.json", json.dumps(info, indent=2))
    return info


def runtime() -> dict:
    try:
        info = json.loads((data_dir() / "runtime.json").read_text(encoding="utf-8"))
        if not Path(info["python"]).is_file() or not Path(info["addon"]).is_dir():
            raise ValueError()
        return info
    except (OSError, ValueError, KeyError):
        raise ValueError("CW-SETUP-RUNTIME: Open FreeCAD once, then try connecting again.") from None


def server_values(info: dict) -> dict:
    return {"command": info["python"],
            "args": [str(Path(info["addon"]) / "src/integrations/cadwiz_plugin/offline_launcher.py")],
            "env": {"CADWIZ_CLIENT_APP": "chatgpt"}, "startup_timeout_sec": 60, "tool_timeout_sec": 180}


def _blocks(text: str) -> tuple[str, str]:
    """Remove only headers that TOML itself identifies as CADWiz's tables."""
    parsed = tomllib.loads(text)
    lines = text.splitlines(keepends=True)
    spans = []
    start, owned = 0, False
    for index, line in enumerate(lines):
        if not re.match(r"^\s*\[", line):
            continue
        try:
            header = tomllib.loads(line)
        except tomllib.TOMLDecodeError:
            continue
        if owned:
            spans.append((start, index))
        owned = "cadwiz" in header.get("mcp_servers", {})
        start = index
    if owned:
        spans.append((start, len(lines)))
    if "cadwiz" in parsed.get("mcp_servers", {}) and not spans:
        raise ValueError("CW-SETUP-FORMAT: CADWiz uses an inline settings entry. Use Settings, MCP servers to update it safely.")
    selected = {i for a, b in spans for i in range(a, b)}
    return ("".join(line for i, line in enumerate(lines) if i not in selected),
            "".join(line for i, line in enumerate(lines) if i in selected))


def entry(info: dict) -> str:
    values = server_values(info)
    return ("\n[mcp_servers.cadwiz]\ncommand = " + json.dumps(values["command"]) +
            "\nargs = " + json.dumps(values["args"]) +
            '\nstartup_timeout_sec = 60\ntool_timeout_sec = 180\n\n[mcp_servers.cadwiz.env]\nCADWIZ_CLIENT_APP = "chatgpt"\n')


def connect(info: dict, path: Path | None = None) -> Path:
    target = path or config_path()
    if target.is_symlink():
        raise ValueError("CW-SETUP-LINK: Linked settings were left untouched. Use the manual settings form.")
    before = target.read_text(encoding="utf-8-sig") if target.exists() else ""
    other, previous = _blocks(before)
    after = other.rstrip() + entry(info)
    desired = tomllib.loads(after)["mcp_servers"]["cadwiz"]
    if tomllib.loads(before).get("mcp_servers", {}).get("cadwiz") == desired:
        return target
    backups = data_dir() / "backups"
    backups.mkdir(parents=True, exist_ok=True)
    stamp = str(time.time_ns())
    backup = backups / ("codex-" + stamp + ".toml")
    # Backup exact bytes, including encoding and comments, before any settings change.
    if target.exists():
        shutil.copy2(target, backup)
    else:
        backup.write_bytes(b"")
    receipt_path = data_dir() / "codex-undo.json"
    old_receipt = None
    if receipt_path.exists():
        old_receipt = json.loads(receipt_path.read_text())
        if old_receipt.get("path") != str(target.resolve()):
            raise ValueError("CW-SETUP-UNDO: Undo the previous CADWiz connection before selecting another settings file.")
    receipt = {"path": str(target.resolve()), "backup": str(backup),
               "previous": old_receipt["previous"] if old_receipt else previous,
               "installed": desired, "before_hash": hashlib.sha256(before.encode()).hexdigest()}
    # A failed receipt write must not leave settings changed without an undo.
    atomic_write(receipt_path, json.dumps(receipt, indent=2))
    try:
        if (target.read_text(encoding="utf-8-sig") if target.exists() else "") != before:
            raise ValueError("CW-SETUP-CHANGED: Settings changed while connecting. Try again.")
        atomic_write(target, after)
    except Exception:
        if old_receipt:
            atomic_write(receipt_path, json.dumps(old_receipt))
        else:
            receipt_path.unlink(missing_ok=True)
        raise
    return target


def disconnect() -> None:
    receipt_path = data_dir() / "codex-undo.json"
    receipt = json.loads(receipt_path.read_text())
    target = Path(receipt["path"])
    text = target.read_text(encoding="utf-8-sig")
    if tomllib.loads(text).get("mcp_servers", {}).get("cadwiz") != receipt["installed"]:
        raise ValueError("CW-SETUP-CONFLICT: CADWiz's entry was changed elsewhere. Nothing was overwritten; use MCP settings to remove it.")
    other, _ = _blocks(text)
    updated = other.rstrip() + "\n" + receipt["previous"]
    tomllib.loads(updated)
    backup = data_dir() / "backups" / ("before-disconnect-" + str(time.time_ns()) + ".toml")
    shutil.copy2(target, backup)
    atomic_write(target, updated)
    receipt_path.unlink()


def check(info: dict) -> dict:
    """Local and read-only: silence is never proof that settings are broken."""
    started = time.monotonic()
    status = {"version": VERSION, "code": "CW-SETUP-READY", "message": "Ready to connect your desktop assistant."}
    try:
        if tuple(map(int, info["freecad_version"].split(".")[:2])) < (1, 1):
            raise ValueError("CW-SETUP-FREECAD: FreeCAD 1.1 or newer is required. Get it from freecad.org.")
        path = config_path()
        parsed = tomllib.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else {}
        existing = parsed.get("mcp_servers", {}).get("cadwiz")
        if existing and existing != server_values(info):
            status.update(code="CW-SETUP-PATH", message="The saved OpenAI connection needs an update. Press Connect ChatGPT / Codex; a backup and undo are included.")
    except (OSError, ValueError, KeyError) as error:
        status.update(code="CW-SETUP-CHECK", message=str(error))
    status["elapsed_ms"] = round((time.monotonic() - started) * 1000, 2)
    return status


def repair_owned(info: dict, pause=time.sleep) -> dict:
    """Repair only an entry this setup previously owned, after two observations.

    A missing heartbeat never triggers a write. A changed third-party entry is
    left alone. Two unsuccessful repairs stop; the UI offers help instead.
    """
    receipt_path = data_dir() / "codex-undo.json"
    if not receipt_path.is_file():
        return check(info)
    for _attempt in range(2):
        receipt = json.loads(receipt_path.read_text())
        target = Path(receipt["path"])
        text = target.read_text(encoding="utf-8-sig") if target.exists() else ""
        current = tomllib.loads(text).get("mcp_servers", {}).get("cadwiz")
        desired = server_values(info)
        if current == desired:
            return check(info)
        if current not in (None, receipt["installed"]):
            return {"code": "CW-SETUP-CONFLICT", "message": "CADWiz's settings were changed elsewhere. Use Connect to review them; nothing was overwritten."}
        pause(0.15)
        if (target.read_text(encoding="utf-8-sig") if target.exists() else "") != text:
            continue
        connect(info, target)
        return {"code": "CW-SETUP-RESTART", "message": "CADWiz repaired its saved connection. Backup and Undo are available. Fully quit and reopen ChatGPT / Codex desktop."}
    return {"code": "CW-SETUP-STOPPED", "message": "Settings are still changing. Automatic repair stopped. Use Connect or Get help."}


def relocate_duplicates(mod: Path, active: Path) -> list[dict]:
    """Move only positively identified old CADWiz add-ons outside Mod, never delete."""
    import xml.etree.ElementTree as ET
    moved = []
    active = active.resolve()
    for candidate in mod.iterdir() if mod.is_dir() else []:
        resolved = candidate.resolve()
        if candidate.is_symlink() or not candidate.is_dir() or resolved == active or resolved in active.parents:
            continue
        metadata = candidate / "package.xml"
        if not metadata.is_file():
            continue
        try:
            package = ET.parse(metadata).getroot()
            name = next((node.text for node in package if node.tag.rsplit("}", 1)[-1] == "name"), "")
            if name != "CADWiz":
                continue
            destination = data_dir() / "backups" / (candidate.name + "-duplicate-" + str(time.time_ns()))
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(candidate), destination)
            moved.append({"original": str(candidate), "backup": str(destination)})
        except (OSError, ET.ParseError):
            continue
    if moved:
        receipt = data_dir() / "duplicate-undo.json"
        previous = json.loads(receipt.read_text()) if receipt.exists() else []
        atomic_write(receipt, json.dumps(previous + moved, indent=2))
    return moved


def undo_duplicates() -> None:
    receipt = data_dir() / "duplicate-undo.json"
    entries = json.loads(receipt.read_text())
    if any(Path(item["original"]).exists() for item in entries):
        raise ValueError("CW-SETUP-CONFLICT: A replacement add-on now occupies that folder; the saved copies were kept.")
    for item in entries:
        shutil.move(item["backup"], item["original"])
    receipt.unlink()


def claude_config_paths() -> list[Path]:
    if sys.platform == "darwin":
        return [Path.home() / "Library/Application Support/Claude/claude_desktop_config.json"]
    roaming = Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming"))
    local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
    paths = [roaming / "Claude/claude_desktop_config.json"]
    for pattern in ("Claude_*", "AnthropicPBC.Claude*"):
        paths += list((local / "Packages").glob(pattern + "/LocalCache/Roaming/Claude/claude_desktop_config.json"))
    return list(dict.fromkeys(paths))


def migrate_legacy_claude(paths: list[Path] | None = None) -> list[dict]:
    """Explicit Add-to-Claude action only; retire a positively identified legacy server."""
    plans = []
    for path in paths if paths is not None else claude_config_paths():
        if not path.is_file():
            continue
        if path.is_symlink():
            raise ValueError("CW-SETUP-LINK: Claude's linked settings were left untouched.")
        text = path.read_text(encoding="utf-8-sig")
        data = json.loads(text)
        previous = data.get("mcpServers", {}).get("cadwiz")
        if previous is None:
            continue
        args = str(previous.get("args", [])).replace("\\", "/").lower()
        if "integrations/cadwiz_plugin/server.py" not in args and "integrations/cadwiz_plugin/offline_launcher.py" not in args:
            raise ValueError("CW-SETUP-CONFLICT: Another connector uses the name cadwiz. Its settings were kept; review Claude's connector settings.")
        backup = data_dir() / "backups" / ("claude-" + str(time.time_ns()) + ".json")
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, backup)
        del data["mcpServers"]["cadwiz"]
        plans.append({"path": str(path), "previous": previous, "backup": str(backup), "before": text, "after": json.dumps(data, indent=2)})
    if not plans:
        return []
    receipt = data_dir() / "claude-undo.json"
    if receipt.exists():
        raise ValueError("CW-SETUP-UNDO: Undo the earlier Claude migration before replacing another old connector.")
    atomic_write(receipt, json.dumps(plans, indent=2))
    completed = []
    try:
        for item in plans:
            path = Path(item["path"])
            if path.read_text(encoding="utf-8-sig") != item["before"]:
                raise ValueError("CW-SETUP-CHANGED: Claude's settings changed during setup. Try again.")
            atomic_write(path, item["after"])
            completed.append(item)
    except Exception:
        for item in completed:
            atomic_write(Path(item["path"]), item["before"])
        receipt.unlink(missing_ok=True)
        raise
    return plans


def undo_claude() -> None:
    receipt = data_dir() / "claude-undo.json"
    plans = json.loads(receipt.read_text())
    ready = []
    for item in plans:
        path = Path(item["path"])
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if "cadwiz" in data.get("mcpServers", {}):
            raise ValueError("CW-SETUP-CONFLICT: A new CADWiz entry already exists. The backup was kept; nothing overwritten.")
        data.setdefault("mcpServers", {})["cadwiz"] = item["previous"]
        ready.append((path, json.dumps(data, indent=2)))
    for path, text in ready:
        backup = data_dir() / "backups" / ("before-claude-undo-" + str(time.time_ns()) + ".json")
        shutil.copy2(path, backup)
        atomic_write(path, text)
    receipt.unlink()
