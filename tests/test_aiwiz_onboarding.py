import json
from types import SimpleNamespace
import pytest
from integrations.cadwiz_plugin.aiwiz import connected_apps, landing_tab


@pytest.mark.parametrize('system', ['win32', 'darwin', 'linux'])
def test_new_and_returning_navigation_is_platform_independent(tmp_path, monkeypatch, system):
    import sys
    monkeypatch.setattr(sys, 'platform', system)
    path = tmp_path / 'onboarding.json'
    assert landing_tab(path) == 0
    path.write_text(json.dumps({'schema': 1, 'connection_seen': True}))
    assert landing_tab(path) == 1
    assert connected_apps(None) == []  # Saved navigation never claims a live connection.


@pytest.mark.parametrize('raw', ['broken', '[]', '{}', '{"schema":1,"connection_seen":"yes"}',
                                 '{"schema":2,"connection_seen":true}'])
def test_bad_or_unverified_navigation_record_returns_to_setup(tmp_path, raw):
    path = tmp_path / 'state.json'; path.write_text(raw)
    assert landing_tab(path) == 0
    assert path.read_text() == raw


def test_live_connection_is_verified_per_assistant(tmp_path):
    bridge = SimpleNamespace(connected_to=lambda app: app == 'claude')
    assert connected_apps(bridge) == ['Claude Desktop']
    assert landing_tab(tmp_path / 'missing.json', bridge) == 1
    assert connected_apps(SimpleNamespace(connected=True)) == []
