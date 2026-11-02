import urllib.error
import urllib.request

import pytest
from types import SimpleNamespace

from integrations.cadwiz_plugin import connection_control as control


def test_other_assistant_cannot_satisfy_selected_reconnect():
    import time
    from integrations.cadwiz_plugin.slim_panel import _Panel, AMBER
    class Connector:
        app = "chatgpt"
        busy = True
        words = "Reconnecting ChatGPT"
        def poll(self, connected):
            assert connected is False
            return "waiting"
    bridge = SimpleNamespace(connected=True, connected_to=lambda app: app == "claude")
    panel = SimpleNamespace(bridge=lambda: bridge, opened_at=time.monotonic(), connector=Connector())
    assert _Panel.light_now(panel)["light"] == AMBER


def test_button_requests_real_reconnect_before_launching(monkeypatch):
    from integrations.cadwiz_plugin.connect_claude import Connector
    calls = []
    monkeypatch.setattr(control, "reconnect", lambda app: calls.append(app) or True)
    connector = Connector(app="chatgpt", ask=lambda app: pytest.fail("app launch was unnecessary"))
    connector.thread.join(5)
    assert calls == ["chatgpt"] and connector.stage == "waiting"
    assert connector.poll(True) == "connected"


def test_explicit_host_identity_overrides_ambiguous_launcher(monkeypatch):
    from integrations.cadwiz_plugin import server
    monkeypatch.setenv("CADWIZ_CLIENT_APP", "chatgpt")
    assert server.client_name() == "ChatGPT (Codex app)"


def test_reconnect_uses_real_connector_and_selected_app(tmp_path, monkeypatch):
    monkeypatch.setattr(control, "directory", lambda: tmp_path)
    calls = []
    server = control.start("chatgpt", lambda: calls.append("hello") or True)
    try:
        assert not control.reconnect("claude")
        assert calls == []
        assert control.reconnect("chatgpt")
        assert calls == ["hello"]
        req = urllib.request.Request(f"http://127.0.0.1:{server.server_port}/reconnect", data=b"{}")
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(req)
        assert error.value.code == 403
        assert calls == ["hello"]
    finally:
        server.shutdown()
        server.server_close()


def test_failed_connector_does_not_claim_connection(tmp_path, monkeypatch):
    monkeypatch.setattr(control, "directory", lambda: tmp_path)
    server = control.start("chatgpt", lambda: False)
    try:
        assert not control.reconnect("chatgpt")
    finally:
        server.shutdown()
        server.server_close()
