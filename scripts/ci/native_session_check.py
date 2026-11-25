# SPDX-License-Identifier: LGPL-2.1-or-later
"""Exercise production session, sandbox worker and acceptance on real FreeCAD copies."""
from pathlib import Path
import sys,tempfile,os,json,hashlib
root=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(Path(__file__).resolve().parent))
sys.path.insert(0,str(root/'CADWiz/src'))

def run():
    work=Path(tempfile.mkdtemp(prefix='cadwiz-086-session-'))
    os.environ['LOCALAPPDATA']=str(work/'local')
    os.environ['CADWIZ_SETTINGS_FILE']=str(work/'settings.json')
    import FreeCAD as A
    from integrations.cadwiz_plugin.session import PluginSession
    from integrations.ai_master.adopted_executor import AdoptedExecutor
    from integrations.ai_master.parametric_checks import STATUS
    session=PluginSession(app=A,project_root=work,executor_factory=lambda p,n,f,**hooks:AdoptedExecutor(p,n,f,freecadcmd=Path(sys.executable),**hooks))
    import inspect
    from native_fixtures import plate
    code='import FreeCAD as A, Part, Sketcher\n'+inspect.getsource(plate).replace('d=A.newDocument(name)','d=doc')+'\nplate()'
    result=session.call('build_model',{'new_document':'VerifiedPlate','code':code})
    print('BUILD',json.dumps(result,default=str));assert result.get('success'),result
    current=A.ActiveDocument;path=Path(current.FileName)
    assert current.getObject(STATUS).Editability=='E3'
    before=hashlib.sha256(path.read_bytes()).hexdigest()
    result=session.call('edit_object',{'parameters':{'Params.Width':'45 mm'}})
    print('PARAM',json.dumps(result,default=str));assert result.get('success'),result
    assert A.ActiveDocument.Body.Shape.isValid()
    accepted=hashlib.sha256(path.read_bytes()).hexdigest()
    result=session.call('edit_object',{'script':"b=doc.getObject('Body'); b.Tip=None; import Part; x=doc.addObject('Part::Feature','Flattened'); x.Shape=Part.makeBox(45,30,5)"})
    print('REJECT',json.dumps(result,default=str));assert not result.get('ok'),result
    assert hashlib.sha256(path.read_bytes()).hexdigest()==accepted,'failed edit must not overwrite accepted document'
    print('PASS session: native build accepted, named edit accepted, flattened replacement rejected; accepted file unchanged.',work)

    # Health checks must capture unsaved work without saving, closing or modifying it.
    current=A.ActiveDocument;current.Label='Unsaved label for diagnostic snapshot'
    filename=current.FileName;label=current.Label;digest=hashlib.sha256(Path(filename).read_bytes()).hexdigest()
    health=session.call('model_health',{})
    assert health.get('ok') and health['health']['level']=='E3',health
    assert current.Label==label and current.FileName==filename
    assert hashlib.sha256(Path(filename).read_bytes()).hexdigest()==digest
    # A wrong objective dimension is refused before promotion.
    result=session.call('design_record',{'action':'update','fields':{'requirements':[{'name':'width','metric':'width_mm','target':999,'tolerance':0.01,'unit':'mm'}]}})
    assert result.get('ok'),result
    result=session.call('edit_object',{'parameters':{'Params.Width':'46 mm'}})
    assert not result.get('ok'),result
    assert hashlib.sha256(Path(filename).read_bytes()).hexdigest()==digest
    # Direct-solid results require a persisted, visible exception, never a silent fallback.
    from integrations.cadwiz_plugin.document_actions import user_document_operation
    assert user_document_operation(session,{'mode':'new','target_path':str(session.project.folder/'DirectRejected.FCStd')})['ok']
    result=session.call('build_model',{'document':A.ActiveDocument.Name,'code':"import Part; o=doc.addObject('Part::Feature','Solid'); o.Shape=Part.makeBox(10,20,3)"})
    assert not result.get('ok'),result
    result=session.call('design_record',{'action':'update','fields':{'construction_exception':'User-supplied imported solid has no original native feature history; retain this direct representation explicitly.'}})
    assert result.get('ok'),result
    result=session.call('build_model',{'document':A.ActiveDocument.Name,'code':"import Part; o=doc.addObject('Part::Feature','Solid'); o.Shape=Part.makeBox(10,20,3)"})
    assert result.get('success') and result.get('limitation') and result['health']['level']=='E1',result
    print('PASS: health copy preserves unsaved work; objective mismatch blocked; direct solid rejected unless exception is recorded and disclosed.')


import traceback
result = 0
try:
    run()
except BaseException:
    traceback.print_exc()
    result = 1
sys.stdout.flush()
sys.stderr.flush()
os._exit(result)

