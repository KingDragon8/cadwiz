# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""The CADWiz shortcut (founder, 2026-10-23): one click opens FreeCAD and the chosen
assistant app together -- never a second FreeCAD, never closing anything."""
from __future__ import annotations

from integrations.cadwiz_plugin import launch


def look(running: set[str], installed: set[str]):
    return lambda app: {"running": app in running, "appid": f"id-{app}" if app in installed else ""}


def test_whichever_is_open_leaves_a_running_app_alone_and_otherwise_opens_claude_first() -> None:
    opened: list[str] = []
    assert launch.open_assistant("auto", look({"chatgpt"}, {"claude", "chatgpt"}), opened.append) == "running:chatgpt"
    assert launch.open_assistant("auto", look(set(), {"claude", "chatgpt"}), opened.append) == "opened:claude"
    assert launch.open_assistant("auto", look(set(), {"chatgpt"}), opened.append) == "opened:chatgpt"
    assert opened == ["id-claude", "id-chatgpt"]


def test_a_chosen_app_is_the_one_opened_and_a_missing_one_opens_nothing() -> None:
    opened: list[str] = []
    assert launch.open_assistant("chatgpt", look({"claude"}, {"claude", "chatgpt"}), opened.append) == "opened:chatgpt"
    assert launch.open_assistant("claude", look(set(), set()), opened.append) == "none"
    assert opened == ["id-chatgpt"]


def test_freecad_is_started_only_when_it_is_not_already_running(monkeypatch) -> None:
    started: list[list[str]] = []
    monkeypatch.setattr(launch, "chosen_app", lambda: "claude")
    monkeypatch.setattr(launch, "open_assistant", lambda choice: "running:claude")
    monkeypatch.setattr(launch, "freecad_running", lambda: True)
    launch.main(start=started.append)
    assert started == []
    monkeypatch.setattr(launch, "freecad_running", lambda: False)
    launch.main(start=started.append)
    assert len(started) == 1 and started[0][0].lower().endswith("freecad.exe")
