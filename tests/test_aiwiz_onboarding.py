import json
from types import SimpleNamespace
import pytest
from integrations.cadwiz_plugin.aiwiz import connected_apps, landing_tab, desktop_route


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


def test_openai_app_lookup_targets_codex_identity(monkeypatch):
    from integrations.cadwiz_plugin import connect_claude
    monkeypatch.setattr(connect_claude.sys, 'platform', 'win32')
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(stdout='running=False\nappid=OpenAI.Codex_example!App\n')
    monkeypatch.setattr(connect_claude.subprocess, 'run', run)
    result = connect_claude.ask_windows('chatgpt')
    assert result['appid'] == 'OpenAI.Codex_example!App'
    assert "OpenAI.Codex*!*" in calls[0][-1]
    assert "Name -eq 'ChatGPT'" not in calls[0][-1]
    assert connect_claude.APPS['chatgpt']['start'] == 'Codex'


def test_linux_does_not_offer_a_nonexistent_claude_desktop_install():
    assert desktop_route('claude', 'linux')[2] is False
    assert desktop_route('chatgpt', 'linux') == ('Codex CLI', 'https://developers.openai.com/codex/cli/', True)
    for platform in ('win32', 'darwin'):
        assert desktop_route('claude', platform)[2] is True
        assert desktop_route('chatgpt', platform)[0] == 'Codex'
