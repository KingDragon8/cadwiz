import json
import os
import subprocess
import sys
from types import SimpleNamespace
from uuid import uuid4

import pytest

from integrations.cadwiz_plugin import codex_cli, secure_store as credentials, preferences_store
from integrations.cadwiz_plugin.free_ai_connection import ConnectionFailure


def test_linux_secret_is_piped_and_never_in_arguments_or_errors():
    calls = []
    secret = 'test-only-credential-not-an-account'
    def run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout='', stderr='')
    store = credentials.LinuxCredentialStore('gemini', executable='/usr/bin/secret-tool', runner=run)
    store.set(secret)
    args, opts = calls[0]
    assert secret not in json.dumps(args) and opts['input'] == secret
    assert 'shell' not in opts and opts['timeout'] == 20
    def failed(*args, **kwargs):
        raise subprocess.TimeoutExpired(secret, 20, output=secret)
    store.runner = failed
    with pytest.raises(ConnectionFailure) as error:
        store.get()
    assert secret not in str(error.value)


def test_missing_vault_fails_closed(monkeypatch):
    monkeypatch.setattr(credentials.shutil, 'which', lambda _: None)
    with pytest.raises(ConnectionFailure, match='libsecret-tools'):
        credentials.credential_store('gemini', platform='linux')
    with pytest.raises(ConnectionFailure):
        credentials.credential_store('unknown')


def test_windows_factory_preserves_existing_identifiers(monkeypatch):
    monkeypatch.setattr(credentials, 'WindowsCredentialStore', lambda target: target)
    assert credentials.credential_store('groq', platform='win32') == 'CADWiz/FreeAI/Groq'
    assert credentials.credential_store('gemini', platform='win32') == 'CADWiz/FreeAI/gemini'


def test_cli_login_probe_does_not_return_credentials_or_request_inference():
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout='Logged in using API key: TEST_SECRET_VALUE', stderr='')
    result = codex_cli.probe(command=['/installed/codex'], runner=run)
    assert result['authenticated'] and result['state'] == 'Authenticated'
    assert 'TEST_SECRET_VALUE' not in json.dumps(result)
    assert calls == [['/installed/codex', '--version'], ['/installed/codex', 'login', 'status']]


def test_cli_npm_wrapper_does_not_use_shell(tmp_path):
    wrapper = tmp_path / 'codex.cmd'; wrapper.write_text('ignored shell content')
    script = tmp_path / 'node_modules/@openai/codex/bin/codex.js'
    script.parent.mkdir(parents=True); script.write_text('// fixture')
    node = tmp_path / 'node.exe'; node.write_bytes(b'fixture')
    command = codex_cli.find_command(which=lambda _: str(wrapper), platform='win32', home=tmp_path)
    assert command == [str(node.resolve()), str(script.resolve())]


def test_preference_survives_restart_and_unavailable_cli(tmp_path):
    path = tmp_path / 'preferences.json'
    pref = preferences_store.load(path)
    pref.ai_app = 'codex_cli'; pref.ai_setup_route = 'codex_cli'
    preferences_store.save(pref, path)
    def unavailable(*args, **kwargs):
        raise OSError('unavailable')
    result = codex_cli.probe(command=['/missing/codex'], runner=unavailable)
    assert not result['authenticated']
    reloaded = preferences_store.load(path)
    assert reloaded.ai_app == reloaded.ai_setup_route == 'codex_cli'


def test_connection_and_cad_readiness_are_distinct():
    authenticated = {'installed': True, 'authenticated': True, 'state': 'Authenticated'}
    assert codex_cli.connection_status(authenticated)['state'] == 'Authenticated'
    bridge = SimpleNamespace(connected_to=lambda app: app == 'codex_cli', cad_ready_to=lambda app: False)
    assert codex_cli.connection_status(authenticated, bridge)['state'] == 'Connected'
    bridge.cad_ready_to = lambda app: True
    assert codex_cli.connection_status(authenticated, bridge)['state'] == 'CAD Ready'


def test_cli_settings_identity_survives_startup_repair(tmp_path, monkeypatch):
    import tomllib
    from integrations.cadwiz_plugin import install_setup as setup
    monkeypatch.setenv('CADWIZ_SETUP_DIR', str(tmp_path / 'private'))
    path = tmp_path / 'config.toml'
    monkeypatch.setattr(setup, 'config_path', lambda: path)
    info = {'python': '/test/python', 'addon': '/test/CADWiz', 'freecad_version': '1.1.4', 'client_app': 'codex_cli'}
    setup.connect(info, path)
    assert tomllib.loads(path.read_text())['mcp_servers']['cadwiz']['env']['CADWIZ_CLIENT_APP'] == 'codex_cli'
    startup = {k: v for k, v in info.items() if k != 'client_app'}
    before = path.read_bytes()
    assert setup.repair_owned(startup)['code'] == 'CW-SETUP-READY'
    assert path.read_bytes() == before


@pytest.mark.skipif(sys.platform not in ('win32', 'darwin') and os.environ.get('CADWIZ_NATIVE_SECRET_SERVICE') != '1',
                    reason='requires an actual OS vault (Linux CI starts a disposable Secret Service)')
def test_native_os_vault_roundtrip():
    account = 'cadwiz-regression-' + uuid4().hex
    secret = 'test-only-not-a-provider-key-' + uuid4().hex
    store = (credentials.WindowsCredentialStore('CADWiz/Test/' + account) if sys.platform == 'win32'
             else credentials.MacCredentialStore(account) if sys.platform == 'darwin'
             else credentials.LinuxCredentialStore(account))
    try:
        assert store.get() is None
        store.set(secret); assert store.get() == secret
        store.set(secret + '-updated'); assert store.get() == secret + '-updated'
    finally:
        store.remove()
    assert store.get() is None


def test_actual_bridge_requires_a_successful_cad_operation_for_readiness(tmp_path):
    from integrations.cadwiz_plugin.bridge import Bridge
    from integrations.cadwiz_plugin.server import _send
    def call(tool, args):
        return {'ok': True, 'document': 'Fixture', 'objects': [{'name': 'Body'}]} if tool == 'inspect_document' else {'ok': True}
    bridge = Bridge(call, info_path=tmp_path/'bridge.json').start()
    try:
        info = {'port': bridge.port, 'token': bridge.token}
        _send(info, 'hello', {'client': 'Codex CLI'}, 3)
        assert bridge.connected_to('codex_cli') and not bridge.cad_ready_to('codex_cli')
        _send(info, 'call', {'client': 'Codex CLI', 'tool': 'user_preferences'}, 3)
        assert not bridge.cad_ready_to('codex_cli')
        _send(info, 'call', {'client': 'Codex CLI', 'tool': 'inspect_document'}, 3)
        assert bridge.cad_ready_to('codex_cli') and not bridge.cad_ready_to('chatgpt')
    finally:
        bridge.stop()
