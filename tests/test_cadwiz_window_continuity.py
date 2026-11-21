# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
from integrations.cadwiz_plugin import server
import pytest


@pytest.fixture(autouse=True)
def no_saved_selection(monkeypatch):
    monkeypatch.setattr(server, "_selected_window", lambda: {})


def test_lost_selected_window_cannot_redirect_edit_to_new_blank_window(monkeypatch):
    original = dict(server._chosen)
    try:
        server._chosen.clear()
        server._chosen.update(pid=101, port=1)
        monkeypatch.delenv("CADWIZ_FREECAD_PID", raising=False)
        monkeypatch.setattr(server, "_alive", lambda info: info["pid"] == 202)
        monkeypatch.setattr(server, "_bridges", lambda: [{"pid": 202, "port": 2}])
        assert server._bridge() is None
        assert server._chosen["pid"] == 101
        monkeypatch.setattr(server, "_alive", lambda info: True)
        assert server._bridge()["pid"] == 101
    finally:
        server._chosen.clear()
        server._chosen.update(original)


def test_explicit_instance_selection_ignores_newer_instance(monkeypatch):
    original = dict(server._chosen)
    try:
        server._chosen.clear()
        monkeypatch.setenv("CADWIZ_FREECAD_PID", "101")
        monkeypatch.setattr(server, "_alive", lambda info: True)
        monkeypatch.setattr(server, "_bridges", lambda: [{"pid": 202}, {"pid": 101}])
        assert server._bridge()["pid"] == 101
    finally:
        server._chosen.clear()
        server._chosen.update(original)


def test_first_connection_never_guesses_between_multiple_windows(monkeypatch):
    original = dict(server._chosen)
    try:
        server._chosen.clear()
        monkeypatch.delenv('CADWIZ_FREECAD_PID', raising=False)
        monkeypatch.setattr(server, '_alive', lambda info: True)
        monkeypatch.setattr(server, '_bridges', lambda: [{'pid': 202}, {'pid': 101, 'started_utc': 'a'}])
        assert server._bridge() is None
        monkeypatch.setattr(server, '_selected_window', lambda: {'pid': 101, 'started_utc': 'a'})
        assert server._bridge()['pid'] == 101
        monkeypatch.setattr(server, '_bridges', lambda: [{'pid': 101, 'started_utc': 'reused-pid'}])
        assert server._bridge() is None
    finally:
        server._chosen.clear()
        server._chosen.update(original)


def test_explicit_panel_selection_saves_no_connection_secret(tmp_path):
    import json
    from integrations.cadwiz_plugin.bridge import Bridge
    bridge = Bridge(lambda tool, args: {}, info_path=tmp_path / 'bridges/101.json').start()
    try:
        bridge.select_current()
        selected = json.loads((tmp_path / 'selected-window.json').read_text())
        assert selected == {key: bridge.identity[key] for key in ('pid', 'started_utc')}
        assert 'token' not in selected
    finally:
        bridge.stop()
