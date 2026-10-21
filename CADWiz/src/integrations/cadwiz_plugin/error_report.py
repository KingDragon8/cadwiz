# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Error reports: what was happening when CADWiz hit a wall, kept on this computer
(ORDER-2026-10-21-01, Addendum One Part C).

When a CADWiz tool fails, a report is written to the plug-in's own folder and
given an id such as CWR-20261021-0007:

  * report.json -- the error code and message, the last 10 steps before it (the
    plug-in's own call log, `tool-calls.jsonl`, each step cut to 500 characters),
    and the versions of CADWiz, FreeCAD, the operating system and the AI app;
  * screenshot.png -- FreeCAD's window at that moment.

Nothing leaves the computer here. Reports are kept 30 days. Sending one is
`feedback.py`'s job, and only after the user has seen exactly what goes and said
yes; `scrub()` is applied first (file paths, the user name and anything that
looks like a key are taken out).
"""
from __future__ import annotations

import contextlib
import json
import os
import platform
import re
import shutil
import time
from pathlib import Path
from typing import Any, Callable

KEEP_DAYS = 30
TRAIL_STEPS = 10
STEP_CHARS = 500
REPORT_ID = re.compile(r"^CWR-\d{8}-\d{4,}$")
#: The items a report can carry, in the order the preview lists them. The
#: model file is never included unless the user ticks it.
ITEMS = ("screenshot", "error", "trail", "versions", "model_file")
DEFAULT_ITEMS = ("screenshot", "error", "trail", "versions")


def reports_dir(data_dir: Path) -> Path:
    return Path(data_dir) / "reports"


def new_report_id(folder: Path, when: float | None = None) -> str:
    day = time.strftime("%Y%m%d", time.gmtime(when if when is not None else time.time()))
    taken = [int(p.name.rsplit("-", 1)[1]) for p in folder.glob(f"CWR-{day}-*") if p.name.rsplit("-", 1)[1].isdigit()]
    return f"CWR-{day}-{(max(taken) + 1 if taken else 1):04d}"


def read_trail(log_path: Path, steps: int = TRAIL_STEPS) -> list[dict[str, Any]]:
    """The last `steps` calls from the plug-in's call log, each cut to 500 characters."""
    try:
        lines = Path(log_path).read_text(encoding="utf-8").splitlines()[-steps:]
    except OSError:
        return []
    trail = []
    for line in lines:
        with contextlib.suppress(ValueError):
            entry = json.loads(line)
            asked = json.dumps(entry.get("arguments", {}), default=str)
            result = "ok" if entry.get("ok") else f"failed: {entry.get('detail', '')}"
            trail.append({"at": entry.get("utc", ""), "step": str(entry.get("tool", ""))[:60],
                          "asked": asked[:STEP_CHARS], "result": result[:STEP_CHARS]})
    return trail


def versions(cadwiz_version: str = "", freecad_version: str = "", ai_app: str = "") -> dict[str, str]:
    return {"cadwiz": cadwiz_version or "unknown", "freecad": freecad_version or "unknown",
            "os": f"{platform.system()} {platform.release()}".strip(), "claude_desktop": ai_app or "unknown"}


def prune(folder: Path, now: float | None = None) -> int:
    """Remove this plug-in's own reports older than 30 days."""
    cutoff = (now if now is not None else time.time()) - KEEP_DAYS * 86400
    removed = 0
    for item in folder.glob("CWR-*"):
        if item.is_dir() and REPORT_ID.match(item.name) and item.stat().st_mtime < cutoff:
            shutil.rmtree(item, ignore_errors=True)
            removed += 1
    return removed


def write_report(data_dir: Path, *, error_code: str, message: str, tool: str, log_path: Path,
                 grab_window: Callable[[Path], bool] | None = None, model_file: str = "",
                 version_info: dict[str, str] | None = None, when: float | None = None) -> str:
    """Write a report for a failure and return its id. Never raises: a report that
    cannot be written must not turn one failure into two."""
    try:
        folder = reports_dir(data_dir)
        folder.mkdir(parents=True, exist_ok=True)
        prune(folder, when)
        report_id = new_report_id(folder, when)
        target = folder / report_id
        target.mkdir()
        shot = False
        if grab_window is not None:
            with contextlib.suppress(Exception):
                shot = bool(grab_window(target / "screenshot.png"))
        report = {"report_id": report_id, "error_code": error_code, "message": message[:2000], "tool": tool,
                  "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(when if when is not None else time.time())),
                  "trail": read_trail(log_path), "versions": version_info or versions(),
                  "screenshot": shot, "model_file": model_file}
        (target / "report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
        return report_id
    except Exception:  # noqa: BLE001
        return ""


def load_report(data_dir: Path, report_id: str) -> dict[str, Any] | None:
    if not REPORT_ID.match(str(report_id)):
        return None
    path = reports_dir(data_dir) / report_id / "report.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# ---- the privacy scrub ----------------------------------------------------------------

_KEYLIKE = re.compile(r"\b(?:sk|pk|rk|ghp|gho|xox[abpr]|AKIA|AIza|cws|cwg)[-_A-Za-z0-9]{12,}\b"
                      r"|\b[A-Za-z0-9+/_-]{32,}={0,2}\b")
#: Separators may come doubled: a path inside JSON text reads C:\\Users\\...
_WIN_PATH = re.compile(r"(?i)\b[A-Z]:[\\/]+(?:[^\s\"'<>|:*?\\/]+[\\/]+)*[^\s\"'<>|:*?\\/]*")
_POSIX_PATH = re.compile(r"(?<![\w.])/+(?:Users|home|Volumes|mnt|private|var|tmp|opt)/[^\s\"'<>]*")


def scrub(value: Any, username: str | None = None) -> Any:
    """Take file paths, the user name and anything key-like out of `value`
    (a string, or lists/dicts of them) before it leaves the computer."""
    if isinstance(value, dict):
        return {k: scrub(v, username) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub(v, username) for v in value]
    if not isinstance(value, str):
        return value
    name = username if username is not None else (os.environ.get("USERNAME") or os.environ.get("USER") or "")
    text = _WIN_PATH.sub("<path>", value)
    text = _POSIX_PATH.sub("<path>", text)
    text = _KEYLIKE.sub("<removed>", text)
    if len(name) >= 2:
        text = re.sub(re.escape(name), "<user>", text, flags=re.IGNORECASE)
    return text


def bundle_for_sending(report: dict[str, Any], items: tuple[str, ...] | list[str], username: str | None = None) -> dict[str, Any]:
    """The scrubbed bundle: only the ticked items, exactly as it will be sent."""
    chosen = set(items)
    bundle: dict[str, Any] = {"report_id": report.get("report_id"), "error_code": report.get("error_code")}
    if "error" in chosen:
        bundle["message"] = report.get("message", "")
        bundle["tool"] = report.get("tool", "")
    if "trail" in chosen:
        bundle["trail"] = report.get("trail", [])
    if "versions" in chosen:
        bundle["versions"] = report.get("versions", {})
    return scrub(bundle, username)
