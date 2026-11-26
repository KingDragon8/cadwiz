"""Lost reconnect confirmations must recover without replaying CAD operations."""
import http.client
import json
import urllib.error
import urllib.request
from types import SimpleNamespace

import pytest
from integrations.cadwiz_plugin import connection_control as control
from integrations.cadwiz_plugin.bridge import Bridge
from integrations.cadwiz_plugin import server as connector


@pytest.mark.parametrize('error', [ConnectionAbortedError(10053, 'injected response abort'),
                                  ConnectionResetError('injected reset'),
                                  http.client.IncompleteRead(b'{', 12)])
def test_lost_confirmation_repeats_only_real_hello(tmp_path, monkeypatch, error):
    monkeypatch.setattr(control, 'directory', lambda: tmp_path/'connectors')
    cad_calls=[]
    bridge=Bridge(lambda *args:cad_calls.append(args) or {'ok':True},info_path=tmp_path/'bridge.json').start()
    hellos=[]
    def hello():
        hellos.append('actual authenticated hello')
        return connector._send(bridge.identity,'hello',{'client':'ChatGPT (Codex app)'},5)['ok']
    endpoint=control.start('chatgpt',hello)
    actual_read=http.client.HTTPResponse.read
    dropped=[]
    def read(response,*args,**kwargs):
        body=actual_read(response,*args,**kwargs)
        if b'"connected": true' in body and not dropped:
            dropped.append(True)
            raise error
        return body
    monkeypatch.setattr(http.client.HTTPResponse,'read',read)
    try:
        assert control.reconnect('chatgpt')
        assert dropped and len(hellos)==2
        assert bridge.connected_to('chatgpt')
        assert cad_calls==[], 'A confirmation retry must never invoke a CAD operation'
    finally:
        endpoint.shutdown();endpoint.server_close()
        bridge.stop();bridge._server.server_close()


def test_authenticated_wrong_assistant_response_does_not_claim_connection(tmp_path,monkeypatch):
    monkeypatch.setattr(control,'directory',lambda:tmp_path)
    endpoint=control.start('claude',lambda:True)
    path=next(tmp_path.glob('*.json'))
    record=json.loads(path.read_text());record['app']='chatgpt';path.write_text(json.dumps(record))
    try:
        assert not control.reconnect('chatgpt')
    finally:
        endpoint.shutdown();endpoint.server_close()


def test_forbidden_request_is_not_retried(tmp_path,monkeypatch):
    monkeypatch.setattr(control,'directory',lambda:tmp_path)
    callbacks=[]
    endpoint=control.start('chatgpt',lambda:callbacks.append(True) or True)
    path=next(tmp_path.glob('*.json'))
    record=json.loads(path.read_text());record['token']='wrong';path.write_text(json.dumps(record))
    original=urllib.request.OpenerDirector.open
    requests=[]
    def opened(*args,**kwargs):
        requests.append('open')
        try:
            return original(*args,**kwargs)
        except urllib.error.HTTPError as error:
            requests.append(error.code)
            raise
    monkeypatch.setattr(urllib.request.OpenerDirector,'open',opened)
    try:
        assert not control.reconnect('chatgpt')
        # A transport loss before a denial arrives may safely retry. Once an
        # actual403 is received there must be no further request or callback.
        assert requests.count(403)==1 and requests[-1]==403 and callbacks==[]
    finally:
        endpoint.shutdown();endpoint.server_close()


def test_persistent_failure_has_one_overall_deadline(tmp_path,monkeypatch):
    monkeypatch.setattr(control,'directory',lambda:tmp_path)
    monkeypatch.setattr(control,'RECONNECT_BUDGET_S',.06,raising=False)
    monkeypatch.setattr(control,'RECONNECT_RETRY_DELAY_S',0,raising=False)
    clock=SimpleNamespace(now=0.0)
    def advance(seconds):
        clock.now+=seconds
    monkeypatch.setattr(control,'time',SimpleNamespace(monotonic=lambda:clock.now,sleep=advance))
    for index in range(12):
        (tmp_path/f'{index}.json').write_text(json.dumps({'app':'chatgpt','port':12345,'token':'private'}))
    timeouts=[]
    class Offline:
        def open(self,request,timeout):
            timeouts.append(timeout)
            advance(min(timeout,.025))
            raise TimeoutError('injected unavailable transport')
    monkeypatch.setattr(urllib.request,'build_opener',lambda *_args:Offline())
    assert not control.reconnect('chatgpt')
    assert clock.now<=.06+1e-9
    # Subtracting absolute monotonic timestamps can add a few floating-point
    # rounding bits. One nanosecond does not relax the actual timeout contract.
    assert timeouts and max(timeouts)<=.06+1e-9


@pytest.mark.parametrize('client,expected',[('claude','claude'),('chatgpt','chatgpt'),('codex_cli','codex_cli')])
def test_connector_registers_its_actual_assistant_identity(monkeypatch,client,expected):
    monkeypatch.setenv('CADWIZ_CLIENT_APP',client)
    registered=[]
    monkeypatch.setattr(control,'start',lambda app,callback:registered.append(app))
    monkeypatch.setattr(connector.threading.Thread,'start',lambda *_args:None)
    class Server:
        def run(self):
            pass
    monkeypatch.setattr(connector,'build_server',lambda:Server())
    connector.main()
    assert registered==[expected]
