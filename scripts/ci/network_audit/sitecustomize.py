"""Opt-in, disposable CI network audit. Logs addresses/stacks, never payloads."""
import json
import os
from pathlib import Path
import sys
import time
import traceback

folder = os.environ.get('CADWIZ_NETWORK_AUDIT_DIR')
if folder and os.environ.get('CI') == 'true' and not getattr(sys, '_cadwiz_network_audit_installed', False):
    sys._cadwiz_network_audit_installed = True
    destination = Path(folder)
    destination.mkdir(parents=True, exist_ok=True)
    stream = (destination/f'{os.getpid()}.jsonl').open('a', encoding='utf8', buffering=1)
    stream.write(json.dumps({'event':'audit_started', 'pid':os.getpid(), 'executable':sys.executable, 'time':time.time()})+'\n')
    def audit(event, args):
        if event in {'socket.getaddrinfo', 'socket.gethostbyname', 'socket.gethostbyaddr', 'socket.gethostname'}:
            target = list(args[:2])
        elif event in {'socket.connect', 'socket.bind', 'socket.sendto'}:
            target = args[-1] if args else None
        else:
            return
        record = {'event':event, 'target':target, 'time':time.time(),
                  'stack':[{'file':f.filename, 'line':f.lineno, 'function':f.name}
                           for f in traceback.extract_stack(limit=9)[:-1]]}
        stream.write(json.dumps(record, default=str)+'\n')
    sys.addaudithook(audit)
