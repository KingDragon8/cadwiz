# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""ORDER-2026-10-20-01: the Connect button and the light he could not read.

Founder, 2026-10-20: "It's not connected open in the Claude app. I don't know what
that means. I thought all I needed to do was open CADWiz when Claude was [open]" and
"can you give me like a button to connect it, and it goes through the process."
Windows and the clock are stand-ins; nothing here opens an app.
"""
from __future__ import annotations

from integrations.cadwiz_plugin import connect_claude


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _press(found: dict, clock: _Clock | None = None) -> tuple[connect_claude.Connector, list[str]]:
    opened: list[str] = []
    connector = connect_claude.Connector(ask=lambda: found, opener=opened.append, clock=clock or _Clock())
    connector.thread.join(5)
    return connector, opened


def test_claude_closed_it_is_opened_and_the_light_says_so_until_it_checks_in() -> None:
    clock = _Clock()
    connector, opened = _press({"running": False, "appid": "Claude_x!Claude"}, clock)
    assert opened == ["Claude_x!Claude"] and connector.stage == "opening" and connector.busy
    assert "connects by itself" in connector.words
    assert connector.poll(connected=True) == "connected"


def test_claude_already_open_nothing_is_opened_and_it_waits_for_the_check_in() -> None:
    connector, opened = _press({"running": True, "appid": "Claude_x!Claude"})
    assert opened == [] and connector.stage == "waiting"


def test_still_silent_after_the_wait_it_says_exactly_what_to_check() -> None:
    clock = _Clock()
    connector, _ = _press({"running": True, "appid": "Claude_x!Claude"}, clock)
    clock.now = connect_claude.WAIT_S + 1
    assert connector.poll(connected=False) == "app_silent" and not connector.busy
    assert "Connectors" in connector.words and "Quit" in connector.words


def test_no_claude_app_on_this_pc_says_where_to_get_it() -> None:
    connector, opened = _press({"running": False, "appid": ""})
    assert connector.stage == "no_app" and opened == [] and "claude.ai/download" in connector.words


def test_the_button_never_closes_the_claude_app() -> None:
    source = (connect_claude.__file__ and open(connect_claude.__file__, encoding="utf-8").read()).lower()
    for closing in ("taskkill", "stop-process", ".kill(", "terminate("):
        assert closing not in source, closing
