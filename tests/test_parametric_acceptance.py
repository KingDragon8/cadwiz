# SPDX-License-Identifier: LGPL-2.1-or-later
from types import SimpleNamespace
from ai_freecad_core.ai_master.fact_layer import FactReport, finish_report
from ai_freecad_core.ai_master.editability import EditabilityLevel
from ai_freecad_core.ai_master.design_contract import DesignContract
from ai_freecad_core.ai_master.project_store import safe_name
from ai_freecad_core.cadwiz_screen.preferences import FounderPreferences
from integrations.cadwiz_plugin import preferences_store
from integrations.cadwiz_plugin.session import PluginSession


def test_body_and_spreadsheet_alone_cannot_claim_native_editability():
    facts=FactReport('Counterfeit',valid_solid=True,feature_tree={'bodies':2,'named_parameters':1},parameter_names=['Width'])
    assert finish_report(facts,None).editability.level==EditabilityLevel.E1


def test_e3_requires_actual_mutation_evidence_and_e4_is_not_implied():
    facts=FactReport('Native',valid_solid=True,feature_tree={'functional_tree':1,'named_parameters':1})
    assert finish_report(facts,None).editability.level==EditabilityLevel.E2
    facts.feature_tree['verified_parameters']=1
    assert finish_report(facts,None).editability.level==EditabilityLevel.E3
    assert not facts.living_design_verified


def test_explicit_construction_exception_survives_contract_roundtrip():
    original=DesignContract(project='test',object_name='import',intent_founder_words='keep this imported part',construction_exception='Imported source has no recoverable native feature history.')
    assert DesignContract.from_dict(original.to_dict()).construction_exception==original.construction_exception


def test_chosen_project_root_is_used_by_a_new_session(tmp_path,monkeypatch):
    target=tmp_path/'preferences.json';chosen=tmp_path/'chosen projects'
    monkeypatch.setenv('LOCALAPPDATA',str(tmp_path/'local'))
    monkeypatch.setattr(preferences_store,'preferences_path',lambda:target)
    preferences_store.save(FounderPreferences(project_folder=str(chosen)))
    for _ in range(2):
        session=PluginSession(app=SimpleNamespace(),log_path=tmp_path/'calls.jsonl')
        assert session.project.folder.parent==chosen
        assert session.project.folder.is_dir()


def test_project_names_are_safe_for_windows_and_long_labels():
    assert safe_name('CON')=='_CON'
    assert len(safe_name('x'*300))==100


def test_old_project_version_stores_remain_bound_after_root_change(tmp_path,monkeypatch):
    import hashlib
    monkeypatch.setenv('LOCALAPPDATA',str(tmp_path/'local'))
    logfile=tmp_path/'state/calls.jsonl'
    first=PluginSession(app=SimpleNamespace(),project_root=tmp_path/'first',log_path=logfile)
    model=tmp_path/'existing.FCStd'
    key=hashlib.sha256(str(model.resolve()).casefold().encode('utf-8')).hexdigest()[:12]
    old=first.project.folder/'objects/Existing/adopted'/key
    old.mkdir(parents=True)
    second=PluginSession(app=SimpleNamespace(),project_root=tmp_path/'second',log_path=logfile)
    assert second._project_for(str(model)).folder==first.project.folder
    assert old.is_dir()
    assert second._project_for(str(tmp_path/'new.FCStd')).folder==second.project.folder


def test_an_edit_worker_never_launches_the_freecad_gui(tmp_path,monkeypatch):
    from pathlib import Path
    from integrations.ai_master.executor import AIMasterExecutor,WorkerFailed
    import pytest
    holder=SimpleNamespace(freecadcmd=Path('FreeCAD.exe'))
    def forbidden(*args,**kwargs):
        raise AssertionError('The GUI executable must never be launched as an edit worker')
    monkeypatch.setattr('integrations.ai_master.executor.subprocess.Popen',forbidden)
    with pytest.raises(WorkerFailed,match='will not launch another FreeCAD'):
        AIMasterExecutor._run_worker(holder,{})
