# SPDX-License-Identifier: LGPL-2.1-or-later
"""A path spelling collision cannot authorize another document or its history."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ai_freecad_core.ai_master.adopted import AdoptedStore
from integrations.cadwiz_plugin.engineering_control import ControlError, DocumentAuthority
from integrations.cadwiz_plugin.session import PluginSession


def case_files(tmp_path):
    a, b = tmp_path/'part.FCStd', tmp_path/'Part.FCStd'
    a.write_bytes(b'first');b.write_bytes(b'second')
    if a.samefile(b):
        pytest.skip('Case-sensitive filesystem required; native APFS gate also exercises this')
    return a,b


def test_reload_preserves_the_other_unsaved_case_only_document(tmp_path):
    a,b=case_files(tmp_path)
    first=SimpleNamespace(Name='First',FileName=str(a),Modified=True,Label='unsaved work')
    second=SimpleNamespace(Name='Second',FileName=str(b),Modified=False)
    docs={'First':first,'Second':second};closed=[]
    def close(name):
        closed.append(name);del docs[name]
    session=PluginSession.__new__(PluginSession)
    session.app=SimpleNamespace(listDocuments=lambda:docs,closeDocument=close,
        openDocument=lambda path:SimpleNamespace(Name='Reopened',FileName=path),setActiveDocument=lambda name:None)
    session.gui=None;session.document_authority=SimpleNamespace(target_name='Second',target_path=str(b))
    session._reload(str(b))
    assert closed==['Second'] and docs['First'] is first and first.Modified
    assert first.Label=='unsaved work' and a.read_bytes()==b'first' and b.read_bytes()==b'second'


def test_cached_executor_cannot_be_rebound_to_a_case_only_sibling(tmp_path,monkeypatch):
    a,b=case_files(tmp_path)
    monkeypatch.setenv('CADWIZ_SETTINGS_FILE',str(tmp_path/'settings.json'))
    docs=[SimpleNamespace(Name=name,Label='Shared',FileName=str(path),Objects=[])
          for name,path in [('First',a),('Second',b)]]
    calls=[]
    def factory(project,name,file_name,**hooks):
        calls.append(file_name)
        return SimpleNamespace(original_source=Path(file_name),adoption={},
                               store=SimpleNamespace(latest=lambda:0,current=lambda:None))
    session=PluginSession(app=SimpleNamespace(listDocuments=lambda:{d.Name:d for d in docs}),
        project_root=tmp_path/'projects',log_path=tmp_path/'calls.jsonl',executor_factory=factory)
    DocumentAuthority('modify',str(a),'First').check(SimpleNamespace(),docs[0])
    with pytest.raises(ControlError):
        DocumentAuthority('modify',str(a),'First').check(SimpleNamespace(),docs[1])
    session._executor(docs[0],adopt=False)
    with pytest.raises(ControlError,match='uniquely named'):
        session._executor(docs[1],adopt=False)
    assert calls==[str(a)] and session.store_for(docs[1]) is None


def test_legacy_history_is_preserved_but_cannot_be_claimed_by_another_file(tmp_path):
    a,b=tmp_path/'First.FCStd',tmp_path/'Second.FCStd'
    a.write_bytes(b'first');b.write_bytes(b'second')
    folder=tmp_path/'records'
    store=AdoptedStore(folder,a)
    store.backup(lambda dest:Path(dest).write_bytes(a.read_bytes()))
    record=folder/'adopted.v1.json';before=record.read_bytes()
    (folder/'source.json').unlink()  # An actual pre-binding legacy history.
    inspected=AdoptedStore(folder,a,read_only=True)
    assert inspected.get(1).file==str(tmp_path/'First.v1.FCStd')
    assert not (folder/'source.json').exists()
    with pytest.raises(PermissionError):
        AdoptedStore(folder,b)
    assert record.read_bytes()==before and not (folder/'source.json').exists()
    assert AdoptedStore(folder,a).latest()==1 and record.read_bytes()==before
    assert json.loads((folder/'source.json').read_text())['founder_file']==str(a.resolve())


def test_snapshot_follows_live_file_after_document_name_changes(tmp_path):
    source=tmp_path/'Working.FCStd';source.write_bytes(b'saved')
    live=SimpleNamespace(Name='AfterReload',FileName=str(source),
                         saveCopy=lambda dest:Path(dest).write_bytes(b'unsaved live work'))
    session=PluginSession.__new__(PluginSession)
    session.app=SimpleNamespace(listDocuments=lambda:{live.Name:live})
    session.document_authority=None
    target=tmp_path/'snapshot.FCStd'
    session._snapshot('BeforeReload',str(source),str(target))
    assert target.read_bytes()==b'unsaved live work' and source.read_bytes()==b'saved'


def test_document_authority_uses_physical_identity_for_existing_aliases(tmp_path):
    import os
    source=tmp_path/'Actual.FCStd';source.write_bytes(b'original')
    alias=tmp_path/'Alias.FCStd'
    try:
        os.link(source,alias)
    except OSError as error:
        pytest.skip('Native hard-link creation unavailable: '+str(error))
    authority=DocumentAuthority('modify',str(source),'Working')
    authority.check(SimpleNamespace(),SimpleNamespace(FileName=str(alias)))
    other=tmp_path/'Other.FCStd';other.write_bytes(b'other')
    with pytest.raises(ControlError):
        authority.check(SimpleNamespace(),SimpleNamespace(FileName=str(other)))
