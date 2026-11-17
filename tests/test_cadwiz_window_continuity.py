# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
from integrations.cadwiz_plugin import server


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
