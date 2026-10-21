# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""One mode: the AI master designs and edits, always (ORDER-2026-10-12-04).

    ai-master  -- the frontier master owns understanding and design; CADWiz owns
                  truth, memory, execution, evidence, safety and editability.
    classic    -- the older layered path (intent pre-parsing, routing, step-by-step
                  tool choreography, AI judges) and the Tutor/Mentor/Wizard modes.
                  Kept in the code, never founder-facing: only the hidden developer
                  kill switch reaches it (docs/ARCHIVE-TUTOR-MENTOR-WIZARD-MODES.md).

Founder ruling 2026-10-12: CADWiz has one mode and the AI master is never off.
There is no setting for it in the panel. The old `design_path` value in
`~/.cadwiz/settings.json` (written by the retired "Let the AI master design (new)"
checkbox) is IGNORED: a stale "classic" there is exactly what kept the founder's
edits on the classic path on 2026-10-12, so it can never turn the master off again.

The developer kill switch, for emergencies only, in order:
  1. the environment variable CADWIZ_DESIGN_PATH=classic (tests and gate scripts);
  2. `~/.cadwiz/developer-switches.json` containing {"ai_master_off": true}.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

CLASSIC = "classic"
AI_MASTER = "ai-master"
DESIGN_PATHS = (CLASSIC, AI_MASTER)

#: One mode (ORDER-2026-10-12-04). Only the developer kill switch changes it.
DEFAULT_DESIGN_PATH = AI_MASTER

#: The frontier master, by founder ruling. Changing it is a founder stop.
DEFAULT_MASTER_MODEL = "gpt-6-astra"
#: The fallback master, reached through the same adapter when the master is
#: unavailable (outage, unknown model name, no credit).
DEFAULT_FALLBACK_MASTER_MODEL = "claude-opus-5-5"

#: Silent improve-and-rebuild rounds before the result is shown (Phase 2.4).
DEFAULT_SILENT_ITERATIONS = 3

#: The longest one founder request may run before CADWiz stops and reports
#: what it tried (founder ruling: at least five minutes; Cancel always works).
DEFAULT_REQUEST_CEILING_SECONDS = 600.0
MIN_REQUEST_CEILING_SECONDS = 300.0

#: Smaller models never design or edit (founder ruling 2026-10-12).
_NOT_FRONTIER = ("sonnet", "haiku", "mini", "nano", "flash", "lite", "small", "turbo", "gpt-4", "gpt-3", "gpt-5")


def is_frontier_model(model: str) -> bool:
    """True only for the frontier masters: GPT-6 Astra (and later GPT-6/7 frontier
    names) and Claude Opus. Everything smaller is refused on the design path."""
    name = (model or "").strip().lower()
    if not name or any(word in name for word in _NOT_FRONTIER):
        return False
    return name.startswith(("gpt-6", "gpt-7", "claude-opus"))


def settings_path() -> Path:
    override = os.environ.get("CADWIZ_SETTINGS_FILE", "").strip()
    return Path(override) if override else Path.home() / ".cadwiz" / "settings.json"


def developer_switches_path() -> Path:
    override = os.environ.get("CADWIZ_DEVELOPER_SWITCHES_FILE", "").strip()
    return Path(override) if override else Path.home() / ".cadwiz" / "developer-switches.json"


def read_settings() -> dict:
    try:
        return json.loads(settings_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def read_developer_switches() -> dict:
    try:
        data = json.loads(developer_switches_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def write_setting(key: str, value) -> None:
    data = read_settings()
    data[key] = value
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def design_path() -> str:
    env = os.environ.get("CADWIZ_DESIGN_PATH", "").strip().lower()
    if env in DESIGN_PATHS:
        return env
    if read_developer_switches().get("ai_master_off") is True:
        return CLASSIC
    return DEFAULT_DESIGN_PATH


def ai_master_enabled() -> bool:
    return design_path() == AI_MASTER


def classic_modes_enabled() -> bool:
    """The Tutor/Mentor/Wizard modes and the classic path: developer switch only."""
    return design_path() == CLASSIC


def master_model() -> str:
    """The master's model. An override that names a smaller model is ignored."""
    for candidate in (os.environ.get("CADWIZ_MASTER_MODEL", "").strip(), str(read_settings().get("master_model", "")).strip()):
        if candidate and is_frontier_model(candidate):
            return candidate
    return DEFAULT_MASTER_MODEL


def fallback_master_model() -> str:
    for candidate in (os.environ.get("CADWIZ_FALLBACK_MASTER_MODEL", "").strip(), str(read_settings().get("fallback_master_model", "")).strip()):
        if candidate and is_frontier_model(candidate):
            return candidate
    return DEFAULT_FALLBACK_MASTER_MODEL


def request_ceiling_seconds() -> float:
    raw = os.environ.get("CADWIZ_REQUEST_CEILING_SECONDS", "").strip() or str(read_settings().get("request_ceiling_seconds", "")).strip()
    try:
        value = float(raw) if raw else DEFAULT_REQUEST_CEILING_SECONDS
    except ValueError:
        value = DEFAULT_REQUEST_CEILING_SECONDS
    return max(MIN_REQUEST_CEILING_SECONDS, value)


def silent_iterations() -> int:
    raw = os.environ.get("CADWIZ_SILENT_ITERATIONS", "").strip() or str(read_settings().get("silent_iterations", "")).strip()
    try:
        return max(0, min(10, int(raw))) if raw else DEFAULT_SILENT_ITERATIONS
    except ValueError:
        return DEFAULT_SILENT_ITERATIONS
