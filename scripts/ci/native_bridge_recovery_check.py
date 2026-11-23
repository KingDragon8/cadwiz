# SPDX-License-Identifier: LGPL-2.1-or-later
"""Real headless FreeCAD process restart and protected parametric editing check.

Never starts a GUI or touches the owner's bridge directory/documents.
"""
from pathlib import Path
import json, os, subprocess, sys, tempfile, time, traceback
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'CADWiz/src'))
sys.path.insert(0,str(Path(__file__).resolve().parent))


def worker(config):
    import FreeCAD as A
    from native_fixtures import plate
    from integrations.cadwiz_plugin.bridge import Bridge
    from integrations.cadwiz_plugin.session import PluginSession
    folder=Path(config['folder']); model=folder/'part.FCStd'
    d=A.openDocument(str(model)) if model.exists() else plate('RecoveryPlate')
    d.recompute();d.saveAs(str(model))
    session=PluginSession(app=A,project_root=folder/'projects',log_path=folder/f'calls-{os.getpid()}.jsonl')
    b=Bridge(session.call,run_on_gui=lambda fn:fn(),info_path=folder/'bridges'/f'{os.getpid()}.json').start()
    def documents():return [{'name':x.Name,'file':x.FileName,'active':x is A.ActiveDocument} for x in A.listDocuments().values()]
    b.document_provider=documents;b.documents=documents()
    if config['select']:b.select_current()
    (folder/'ready.json').write_text(json.dumps({'pid':os.getpid()}))
    try:
        while not (folder/'stop').exists():
            if (folder/'select').exists():b.select_current();(folder/'select').unlink()
            b.drain();time.sleep(.02)
    finally:
        active=A.ActiveDocument
        if active:
            active.recompute()
            (folder/f'final-{os.getpid()}.json').write_text(json.dumps({
                'valid':active.Body.Shape.isValid(),'width':active.Body.Shape.BoundBox.XLength,
                'sketches_constrained':all(o.FullyConstrained for o in active.Objects if o.TypeId=='Sketcher::SketchObject'),
                'types':[o.TypeId for o in active.Objects]}))
        b.stop()


def wait(predicate, timeout=90):
    start=time.monotonic()
    while time.monotonic()-start<timeout:
        try:
            value=predicate()
            if value:return value
        except (OSError,ValueError):pass
        time.sleep(.1)
    raise TimeoutError('Native bridge check did not reach its expected state')


def run():
    folder=Path(tempfile.mkdtemp(prefix='cadwiz-bridge-native-'))
    os.environ['CADWIZ_CLIENT_APP']='chatgpt'
    os.environ['CADWIZ_SETTINGS_FILE']=str(folder/'settings.json')
    os.environ['LOCALAPPDATA']=str(folder/'local')
    from integrations.cadwiz_plugin import server,session
    session.plugin_data_dir=lambda:folder
    processes=[]
    def launch(select):
        for name in ['stop','ready.json']:
            if (folder/name).exists():(folder/name).unlink()
        env=dict(os.environ);env['CADWIZ_NATIVE_BRIDGE_WORKER']=json.dumps({'folder':str(folder),'select':select})
        log=open(folder/f'worker-{len(processes)}.log','w')
        p=subprocess.Popen([sys.executable,str(Path(__file__).resolve())],env=env,stdout=log,stderr=log)
        processes.append((p,log));wait(lambda:(folder/'ready.json').exists());return p
    try:
        old=launch(True)
        assert server.call('inspect_document',{})['ok']
        (folder/'stop').touch();old.wait(timeout=30);assert old.returncode==0
        new=launch(False);assert new.pid!=old.pid
        assert server._bridge() is None
        recovered=server.call('inspect_document',{});assert recovered['ok'] and recovered['connection_recovery']
        assert not server.call('edit_object',{'parameters':{'Params.Width':'46 mm'}})['ok']
        (folder/'select').touch()
        wait(lambda:json.loads((folder/'selected-window.json').read_text())['pid']==new.pid)
        edited=server.call('edit_object',{'parameters':{'Params.Width':'46 mm'}})
        assert edited.get('success') or edited.get('ok'),edited
        saved=server.call('save_document',{});assert saved.get('ok'),saved
        (folder/'stop').touch();new.wait(timeout=30);assert new.returncode==0
        reopened=launch(True)
        assert server.call('inspect_document',{})['ok']
        changed_again=server.call('edit_object',{'parameters':{'Params.Width':'47 mm'}})
        assert changed_again.get('success') or changed_again.get('ok'),changed_again
        assert server.call('save_document',{})['ok']
        (folder/'stop').touch();reopened.wait(timeout=30)
        final=json.loads((folder/f'final-{reopened.pid}.json').read_text())
        assert final['valid'] and final['sketches_constrained'] and abs(final['width']-47)<.001
        assert 'Sketcher::SketchObject' in final['types'] and 'PartDesign::Pad' in final['types']
        print(json.dumps({'result':'PASS','scope':'real headless FreeCAD process restart, authenticated loopback and production PluginSession edit/save/reopen; no GUI or Mac hardware claim','pids':[p.pid for p,_ in processes],'evidence':str(folder),'final':final},indent=2))
    finally:
        (folder/'stop').touch()
        for p,log in processes:
            try:p.wait(timeout=10)
            except subprocess.TimeoutExpired:p.terminate();p.wait(timeout=10)
            log.close()


result=0
try:
    if os.environ.get('CADWIZ_NATIVE_BRIDGE_WORKER'):worker(json.loads(os.environ['CADWIZ_NATIVE_BRIDGE_WORKER']))
    else:run()
except BaseException:
    traceback.print_exc();result=1
sys.stdout.flush();sys.stderr.flush();os._exit(result)
