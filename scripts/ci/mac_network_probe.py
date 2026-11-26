"""Identify the first permission-prompt phase on a disposable native Mac CI host."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]


def worker(folder,host_python=False):
    def phase(name, **details):
        record = folder/(name+'.json')
        record.write_text(json.dumps({'phase':name, **details}, default=str))
        deadline = time.monotonic()+45
        while not (folder/(name+'.continue')).exists():
            if time.monotonic()>deadline:
                raise TimeoutError(name)
            time.sleep(.1)
    phase('00-python-start')
    if host_python:
        phase('01-host-python-no-freecad', executable=sys.executable)
    else:
        import FreeCAD
        phase('01-freecad-import', version=FreeCAD.Version()[:3])
    from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
    import threading
    import http.client
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-Length','2')
            self.end_headers()
            self.wfile.write(b'ok')
    listener = ThreadingHTTPServer(('127.0.0.1',0), Handler)
    threading.Thread(target=listener.serve_forever, daemon=True).start()
    try:
        phase('02-stdlib-http-bind', server_name=listener.server_name)
        connection = http.client.HTTPConnection('127.0.0.1',listener.server_port,timeout=5)
        connection.request('GET','/')
        assert connection.getresponse().read()==b'ok'
        connection.close()
        phase('03-stdlib-http-request')
    finally:
        listener.shutdown()
        listener.server_close()
    from integrations.cadwiz_plugin import session, server, connection_control
    session.plugin_data_dir=lambda:folder/'plugin'
    connection_control.directory=lambda:folder/'connectors'
    from integrations.cadwiz_plugin.bridge import Bridge
    bridge=Bridge(lambda *_args:{'ok':True},info_path=folder/'plugin/bridges/probe.json').start()
    try:
        phase('04-production-bridge-start')
        assert server._send(bridge.identity,'hello',{'client':'ChatGPT (Codex app)'},5)['ok']
        phase('05-production-bridge-hello')
        control=connection_control.start('chatgpt',lambda:server._send(bridge.identity,'hello',{'client':'ChatGPT (Codex app)'},5)['ok'])
        try:
            assert connection_control.reconnect('chatgpt')
            phase('06-production-reconnect')
        finally:
            control.shutdown()
            control.server_close()
    finally:
        bridge.stop()
        bridge._server.server_close()
    from integrations.cadwiz_plugin.offline_launcher import prepare
    prepare(ROOT/'CADWiz')
    import mcp
    phase('07-mcp-import', module=mcp.__file__)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--python', type=Path)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--worker',action='store_true')
    parser.add_argument('--host-python',action='store_true',help='Isolate the SDK test-client interpreter, without loading FreeCAD')
    args=parser.parse_args()
    assert sys.platform=='darwin' and os.environ.get('CI')=='true', 'Disposable Mac CI only'
    args.output.mkdir(parents=True,exist_ok=True)
    if args.worker:
        worker(args.output,args.host_python)
        return
    extra=[]
    if not args.host_python:
        resources=args.python.resolve().parent.parent
        modules=[p for p in resources.rglob('FreeCAD*.so') if p.name=='FreeCAD.so' or p.name.startswith('FreeCAD.cpython-')]
        assert len(modules)==1
        extra.append(str(modules[0].parent))
    env=dict(os.environ,PYTHONPATH=os.pathsep.join(extra+[str(ROOT/'CADWiz/src'),str(ROOT/'scripts/ci/network_audit')]),
             CADWIZ_NETWORK_AUDIT_DIR=str(args.output/'network-audit'),CADWIZ_SETUP_DIR=str(args.output/'helper'))
    with (args.output/'worker.log').open('w') as log:
        command=[sys.executable if args.host_python else str(args.python),str(Path(__file__)), '--worker','--output',str(args.output)]
        if args.host_python:
            command.append('--host-python')
        process=subprocess.Popen(command,env=env,stdout=log,stderr=log)
        seen=set()
        deadline=time.monotonic()+240
        try:
            while process.poll() is None:
                for phase in sorted(args.output.glob('[0-9][0-9]-*.json')):
                    if phase.name in seen:
                        continue
                    time.sleep(2)
                    subprocess.run(['screencapture','-x',str(phase.with_suffix('.png'))],check=True,timeout=15)
                    phase.with_suffix('.continue').touch()
                    seen.add(phase.name)
                if time.monotonic()>deadline:
                    raise TimeoutError('Mac permission probe timed out')
                time.sleep(.1)
            assert process.returncode==0, (args.output/'worker.log').read_text()
            assert len(seen)==8, seen
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)


if __name__=='__main__':
    main()
