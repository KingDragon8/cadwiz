"""Authenticated restart recovery: read-only discovery is never edit consent."""
import json
from pathlib import Path
import urllib.error
import pytest
from integrations.cadwiz_plugin import server
from integrations.cadwiz_plugin.bridge import Bridge


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    from integrations.cadwiz_plugin import session
    monkeypatch.setattr(session, 'plugin_data_dir', lambda: tmp_path)
    monkeypatch.delenv('CADWIZ_FREECAD_PID', raising=False)
    server._chosen.clear()
    yield
    server._chosen.clear()


def start(tmp_path, filename='project.FCStd'):
    calls=[]
    bridge=Bridge(lambda tool, args: calls.append(tool) or {'ok':True,'tool':tool},
                  info_path=tmp_path/'bridges'/(str(len(list((tmp_path/'bridges').glob('*.json')))) + '.json')).start()
    bridge.documents=[{'name':'Part','file':str(tmp_path/filename),'active':True}]
    return bridge,calls


@pytest.mark.parametrize('platform', ['win32','darwin','linux'])
def test_close_restart_read_recovers_but_edit_requires_selection(tmp_path, monkeypatch, platform):
    monkeypatch.setattr(server.sys, 'platform', platform)
    old,_=start(tmp_path)
    old.select_current()
    assert server.call('inspect_document',{})['ok']
    old.stop()
    replacement,calls=start(tmp_path)
    try:
        assert server._bridge() is None
        read=server.call('inspect_document',{})
        assert read['ok'] and 'Read-only' in read['connection_recovery']
        denied=server.call('edit_object',{'document':'Part','parameters':{'Length':12}})
        assert not denied['ok'] and calls==['inspect_document']
        # Discovery does not rewrite consent or expose connection secrets.
        selected=json.loads((tmp_path/'selected-window.json').read_text())
        assert selected['instance_id']==old.identity['instance_id']
        status,_=server._recovery_status()
        assert replacement.token not in json.dumps(status)
        replacement.select_current()
        assert server.call('edit_object',{'document':'Part'})['ok']
    finally:replacement.stop()


@pytest.mark.parametrize('same_document', [True,False])
def test_ambiguous_or_different_document_never_recovers(tmp_path,same_document):
    old,_=start(tmp_path);old.select_current();old.stop()
    a,ac=start(tmp_path, 'project.FCStd' if same_document else 'other.FCStd')
    b,bc=start(tmp_path, 'project.FCStd' if same_document else 'third.FCStd')
    try:
        assert not server.call('inspect_document',{})['ok']
        assert not server.call('build_model',{})['ok']
        assert not ac and not bc
    finally:a.stop();b.stop()


def test_legacy_selection_unknown_document_requires_connect(tmp_path):
    b,calls=start(tmp_path)
    try:
        (tmp_path/'selected-window.json').write_text(json.dumps({'pid':989,'started_utc':'old'}))
        result=server.call('edit_object',{})
        assert not result['ok'] and not calls
        assert result['connection']['state']=='selection_required'
        assert not server.call('inspect_document',{})['ok']
    finally:b.stop()


def test_explicit_pid_does_not_recover_to_another_instance(tmp_path,monkeypatch):
    b,calls=start(tmp_path)
    try:
        monkeypatch.setenv('CADWIZ_FREECAD_PID','989')
        assert not server.call('inspect_document',{})['ok']
        assert not calls
    finally:b.stop()


def test_reused_pid_or_authenticated_wrong_identity_is_not_alive(monkeypatch):
    info={'pid':989,'started_utc':'old','instance_id':'one'}
    monkeypatch.setattr(server,'_send',lambda *a,**k: {'ok':True,'freecad_pid':989,'started_utc':'old','instance_id':'two'})
    assert not server._alive(info)
    monkeypatch.setattr(server,'_send',lambda *a,**k: {'ok':False,'freecad_pid':989})
    assert not server._alive(info)


def test_permissions_are_not_diagnosed_as_closed(monkeypatch):
    monkeypatch.setattr(server,'_bridges',lambda:[{'pid':989,'port':1,'token':'private'}])
    def denied(*a,**k):raise PermissionError('denied')
    monkeypatch.setattr(server,'_send',denied)
    status,candidate=server._recovery_status()
    assert candidate is None and status['state']=='no_reachable_bridge'
    assert 'does not prove FreeCAD is closed' in status['guidance']


def test_malformed_registry_files_are_ignored(tmp_path):
    folder=tmp_path/'bridges';folder.mkdir()
    for index,value in enumerate([[],None,{'port':'bad'},42]):
        (folder/f'{index}.json').write_text(json.dumps(value))
    assert server._bridges()==[]


def test_timeout_after_send_is_never_retried(monkeypatch):
    monkeypatch.setattr(server,'_bridge',lambda:{'pid':1})
    calls=[]
    def timeout(*a,**k):calls.append(a);raise urllib.error.URLError('timeout')
    monkeypatch.setattr(server,'_send',timeout)
    assert not server.call('edit_object',{})['ok']
    assert len(calls)==1


def test_unsaved_document_cannot_match_replacement(tmp_path):
    old,_=start(tmp_path);old.documents[0]['file']='';old.select_current();old.stop()
    b,calls=start(tmp_path)
    try:
        assert not server.call('inspect_document',{})['ok'] and not calls
    finally:b.stop()


@pytest.mark.parametrize('value',['{','[]','{}','{"pid":989,"started_utc":"old","document":[]}'])
def test_corrupt_selection_never_becomes_implicit_edit_consent(tmp_path,value):
    b,calls=start(tmp_path)
    try:
        (tmp_path/'selected-window.json').write_text(value)
        assert not server.call('edit_object',{})['ok']
        assert not calls
    finally:b.stop()
