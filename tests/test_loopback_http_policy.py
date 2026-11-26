"""Local authenticated IPC must not resolve LAN names or use global proxies."""
import socket
import threading
import urllib.error
import urllib.request

import pytest
from integrations.cadwiz_plugin import connection_control, server
from integrations.cadwiz_plugin.bridge import Bridge
from integrations.cadwiz_plugin.loopback_http import LoopbackHTTPServer, opener
from http.server import BaseHTTPRequestHandler


@pytest.mark.parametrize('endpoint',['bridge','reconnect'])
def test_numeric_listener_does_not_resolve_hostnames(tmp_path,monkeypatch,endpoint):
    monkeypatch.setattr(connection_control,'directory',lambda:tmp_path/'connectors')
    def forbidden(*args,**kwargs):
        pytest.fail('A numeric loopback listener must not perform DNS lookup')
    monkeypatch.setattr(socket,'getfqdn',forbidden)
    if endpoint=='bridge':
        listener=Bridge(lambda *_args:{'ok':True},info_path=tmp_path/'bridge.json').start()
        listener.stop();listener._server.server_close()
    else:
        listener=connection_control.start('chatgpt',lambda:True)
        listener.shutdown();listener.server_close()


def test_bridge_hello_bypasses_global_proxy_and_keeps_authentication(tmp_path,monkeypatch):
    class DeniedProxy:
        def open(self,*args,**kwargs):
            raise urllib.error.URLError('global proxy must not see local authentication')
    monkeypatch.setattr(urllib.request,'_opener',DeniedProxy())
    bridge=Bridge(lambda *_args:{'ok':True},info_path=tmp_path/'bridge.json').start()
    try:
        result=server._send(bridge.identity,'hello',{'client':'ChatGPT (Codex app)'},5)
        assert result['ok'] and bridge.connected_to('chatgpt')
        with pytest.raises(urllib.error.HTTPError) as denied:
            server._send(dict(bridge.identity,token='wrong'),'hello',{},5)
        assert denied.value.code==403
    finally:
        bridge.stop();bridge._server.server_close()


@pytest.mark.parametrize('host',['0.0.0.0','localhost','192.0.2.1','::1'])
def test_listener_refuses_non_numeric_ipv4_loopback(host):
    with pytest.raises(ValueError,match='loopback'):
        LoopbackHTTPServer((host,0),BaseHTTPRequestHandler)


def test_local_authentication_request_cannot_follow_redirect():
    paths=[]
    class Redirect(BaseHTTPRequestHandler):
        def log_message(self,*args):
            pass
        def do_POST(self):
            paths.append(self.path)
            self.send_response(302)
            self.send_header('Location',f'http://127.0.0.1:{self.server.server_port}/target')
            self.end_headers()
        def do_GET(self):
            paths.append(self.path)
            self.send_response(200);self.end_headers()
    listener=LoopbackHTTPServer(('127.0.0.1',0),Redirect)
    threading.Thread(target=listener.serve_forever,daemon=True).start()
    try:
        request=urllib.request.Request(f'http://127.0.0.1:{listener.server_port}/hello',data=b'{}',
                                       headers={'X-CADWiz-Token':'private'})
        with pytest.raises(urllib.error.HTTPError) as rejected:
            opener().open(request,timeout=5)
        assert rejected.value.code==302 and paths==['/hello']
    finally:
        listener.shutdown();listener.server_close()


@pytest.mark.parametrize('port',[0,65536,True,'80@external.invalid',None])
def test_bridge_endpoint_rejects_invalid_registry_port_before_network(port,monkeypatch):
    from integrations.cadwiz_plugin import loopback_http
    monkeypatch.setattr(loopback_http,'opener',lambda:pytest.fail('Invalid endpoint reached networking'))
    with pytest.raises(ValueError,match='endpoint'):
        server._send({'port':port,'token':'private'},'hello',{},5)


@pytest.mark.parametrize('url',['http://external.invalid:80/','https://127.0.0.1:80/',
                               'file:///private/local-file','http://127.0.0.1@external.invalid:80/'])
def test_shared_ipc_client_rejects_non_loopback_targets(url,monkeypatch):
    monkeypatch.setattr(urllib.request.HTTPHandler,'http_open',lambda *_args:pytest.fail('Unexpected network request'))
    with pytest.raises(urllib.error.URLError,match='loopback'):
        opener().open(url,timeout=1)
