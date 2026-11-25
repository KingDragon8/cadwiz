# SPDX-License-Identifier: LGPL-2.1-or-later
"""Real headless FreeCAD identity checks on a disposable case-sensitive volume."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'CADWiz/src'))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--folder',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if os.environ.get('CI')!='true':
        raise RuntimeError('Disposable CI fixtures only')
    folder=args.folder.resolve()
    if not folder.is_relative_to(Path(os.environ['RUNNER_TEMP']).resolve()) or folder.exists():
        raise RuntimeError('Refusing an existing or non-temporary fixture folder')
    if args.output.suffix!='.json' or args.output.exists():
        raise RuntimeError('A new JSON report path is required')
    import FreeCAD as app
    import Part  # noqa: F401
    from integrations.cadwiz_plugin.engineering_control import ControlError,DocumentAuthority
    from integrations.cadwiz_plugin.session import PluginSession
    folder.mkdir(parents=True,exist_ok=False)
    a_path,b_path=folder/'part.FCStd',folder/'Part.FCStd'
    a_path.write_bytes(b'a');b_path.write_bytes(b'b')
    assert not a_path.samefile(b_path), 'Actual case-sensitive filesystem required'
    os.environ['CADWIZ_SETTINGS_FILE']=str(folder/'settings.json')
    (folder/'settings.json').write_text(json.dumps({'cad_folders':[str(folder)]}))
    def make(name,path,length):
        doc=app.newDocument(name);obj=doc.addObject('Part::Box','Solid')
        obj.Length=length;doc.recompute();doc.saveAs(str(path))
        # Native saveAs resets the document label to its filename. Set the
        # shared label afterward so separate sessions truly collide in history.
        doc.Label='Shared';doc.save();return doc
    a=make('CaseLower',a_path,10);b=make('CaseUpper',b_path,20)
    assert a.Label==b.Label=='Shared', 'History-collision precondition required'
    sha=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
    original=[sha(a_path),sha(b_path)]
    session=PluginSession(app=app,gui=None,project_root=folder/'projects',log_path=folder/'calls.jsonl')
    authority=DocumentAuthority('modify',str(a_path),a.Name)
    authority.check(app,a)
    try:
        authority.check(app,b)
    except ControlError:
        pass
    else:
        raise AssertionError('Document authority accepted a case-only sibling')
    first=session._executor(a,adopt=False)
    try:
        session._executor(b,adopt=False)
    except ControlError:
        pass
    else:
        raise AssertionError('Case-only sibling reused another file executor')
    first.store.backup(lambda dest:a.saveCopy(dest))
    record=first.store.folder/'adopted.v1.json';history=record.read_bytes()
    other=PluginSession(app=app,gui=None,project_root=folder/'projects',log_path=folder/'other-calls.jsonl')
    try:
        other._executor(b,adopt=False)
    except ControlError:
        pass
    else:
        raise AssertionError('Persisted history was rebound to a different case-only file')
    assert session.store_for(b) is None and record.read_bytes()==history
    a.Solid.Length=11;a.recompute();a_name=a.Name
    old_name=b.Name
    session.document_authority=DocumentAuthority('modify',str(b_path),b.Name)
    session._reload(str(b_path))
    assert a.Name==a_name and float(app.getDocument(a_name).Solid.Length)==11
    reopened=app.ActiveDocument
    assert Path(reopened.FileName).samefile(b_path) and float(reopened.Solid.Length)==20
    reopened.Solid.Length=21;reopened.recompute()
    copied=folder/'LiveSnapshot.FCStd'
    # Native reload may reuse the old Name. A guaranteed absent handle must
    # exercise the live-file fallback rather than accidentally use direct lookup.
    stale_name=old_name
    while stale_name in app.listDocuments():stale_name+='_BeforeReload'
    assert stale_name not in app.listDocuments()
    session._snapshot(stale_name,str(b_path),str(copied))
    snapshot=app.openDocument(str(copied))
    assert float(snapshot.Solid.Length)==21
    assert original==[sha(a_path),sha(b_path)] and record.read_bytes()==history
    report={'status':'PASS','fixture':'anonymous native boxes on actual case-sensitive filesystem',
            'wrong_unsaved_document_preserved':True,'cached_executor_collision_refused':True,
            'persisted_history_collision_refused':True,'renamed_live_snapshot_preserved':True,
            'founder_files_and_existing_history_unchanged':True,
            'snapshot_lookup':'Guaranteed absent stale handle; native name reuse is allowed'}
    args.output.write_text(json.dumps(report,indent=2))
    for name in list(app.listDocuments()):app.closeDocument(name)
    print(json.dumps(report))


if __name__=='__main__':
    main()
