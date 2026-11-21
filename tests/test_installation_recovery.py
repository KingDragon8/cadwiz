# SPDX-License-Identifier: LGPL-2.1-or-later
"""Filesystem/registration acceptance, not a substitute for real Mac GUI tests."""
import json
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from integrations.cadwiz_plugin import installation as ins
from integrations.cadwiz_plugin import addon
from integrations.cadwiz_plugin.doctor import inspect

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def source(tmp_path):
    result = tmp_path/'source'
    result.mkdir()
    for name in ins.ESSENTIAL:
        p = result/name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('pass\n')
    return result


@pytest.mark.parametrize('old_name', ['CADWiz', 'cadwiz'])
def test_clean_upgrade_and_rollback_preserve_user_files(source, tmp_path, old_name):
    data = tmp_path/'FreeCAD v1-1'
    first = ins.install(source, data)
    assert first['files_verified'] and not first['startup_verified']
    target = data/'Mod/CADWiz'
    if old_name != 'CADWiz':
        # Case-only rename uses a temporary name on case-insensitive filesystems.
        target.rename(data/'Mod/intermediate')
        (data/'Mod/intermediate').rename(data/'Mod'/old_name)
    previous = data/'Mod'/old_name
    (previous/'Sue.FCStd').write_bytes(b'owner model')
    settings = data/'user.cfg'
    settings.write_bytes(b'preferences')
    other = data/'Mod/OtherAddon'
    other.mkdir()
    (other/'InitGui.py').write_text('pass')
    result = ins.install(source, data)
    assert len(list((data/'Mod').iterdir())) == 2
    manifest = json.loads(Path(result['rollback_manifest']).read_text())
    assert Path(manifest['previous'][0]['backup']).parent.parent == data/'CADWiz-backups'
    assert (Path(manifest['previous'][0]['backup'])/'Sue.FCStd').read_bytes() == b'owner model'
    ins.rollback(Path(result['rollback_manifest']))
    assert (previous/'Sue.FCStd').read_bytes() == b'owner model'
    assert settings.read_bytes() == b'preferences'
    assert (other/'InitGui.py').exists()


def test_neil_nested_partial_clone_and_backups_recover(source, tmp_path):
    data = tmp_path/'profile'
    nested = data/'Mod/cadwiz/cadwiz-release-0.9.1/CADWiz'
    shutil.copytree(source, nested)
    abandoned = data/'Mod/cadwiz.backup.interrupted'
    shutil.copytree(source, abandoned)
    (data/'Mod/cadwiz/.git').mkdir()
    before = inspect(data)
    assert before['loadable_backups'] == 1
    assert any('Nested' in issue for issue in before['installations'][0]['problems'])
    result = ins.install(source, data)
    assert result['previous_installations'] == 2
    after = inspect(data)
    assert len(after['installations']) == 1 and after['loadable_backups'] == 0
    assert after['installations'][0]['method'] == 'manual'
    assert not after['startup_verified']


def test_stage_failure_keeps_old_install(source, tmp_path, monkeypatch):
    data = tmp_path/'profile'
    ins.install(source, data)
    old = ins.hashes(data/'Mod/CADWiz')
    monkeypatch.setattr(ins.shutil, 'copytree', lambda *a, **k: (_ for _ in ()).throw(OSError('disk full')))
    with pytest.raises(OSError):
        ins.install(source, data)
    assert ins.hashes(data/'Mod/CADWiz') == old
    assert not (data/'.cadwiz-install.lock').exists()


def test_post_install_failure_restores_original(source, tmp_path, monkeypatch):
    data = tmp_path/'profile'
    ins.install(source, data)
    (data/'Mod/CADWiz/owner.json').write_text('keep me')
    validate = ins.validate
    def fail_active(p):
        if p == data/'Mod/CADWiz':
            raise ValueError('post-activation failure')
        return validate(p)
    monkeypatch.setattr(ins, 'validate', fail_active)
    with pytest.raises(ValueError):
        ins.install(source, data)
    assert (data/'Mod/CADWiz/owner.json').read_text() == 'keep me'


def test_invalid_source_lock_and_tampered_rollback_refused(source, tmp_path):
    data = tmp_path/'profile'
    data.mkdir()
    (data/'.cadwiz-install.lock').touch()
    with pytest.raises(FileExistsError):
        ins.install(source, data)
    (data/'.cadwiz-install.lock').unlink()
    result = ins.install(source, data)
    (data/'Mod/CADWiz/owner.FCStd').write_text('new work')
    with pytest.raises(ValueError, match='changed'):
        ins.rollback(Path(result['rollback_manifest']))
    assert (data/'Mod/CADWiz/owner.FCStd').exists()
    (source/'InitGui.py').write_text('broken ! python')
    with pytest.raises(SyntaxError):
        ins.install(source, data)


def test_optional_setup_and_ai_failures_do_not_block_registration(monkeypatch):
    scheduled, registered = [], []
    gui = SimpleNamespace(Workbench=object, addWorkbench=registered.append)
    monkeypatch.setattr(addon, '_workbench', None)
    monkeypatch.setattr(addon, 'import_module', lambda name: gui if name == 'FreeCADGui' else object())
    broken = lambda *a: (_ for _ in ()).throw(RuntimeError('offline or missing optional dependency'))
    monkeypatch.setitem(sys.modules, 'integrations.cadwiz_plugin.setup_startup', SimpleNamespace(start=broken))
    monkeypatch.setattr(addon, 'start_bridge', broken)
    monkeypatch.setattr(addon, '_schedule_panel_at_startup', lambda: scheduled.append(True))
    workbench = addon.register()
    assert registered == [workbench] and scheduled == [True]
    assert addon.register() is workbench and len(registered) == 1


@pytest.mark.parametrize('layout', ['', 'CADWiz', 'cadwiz-release-0.9.1/CADWiz'])
def test_startup_discovery_repeated_separate_namespaces(tmp_path, monkeypatch, layout):
    data = tmp_path/'profile'
    root = data/'Mod/cadwiz'/layout
    (root/'src/integrations/cadwiz_plugin').mkdir(parents=True)
    (root/'src/integrations/cadwiz_plugin/addon.py').write_text('pass')
    errors, registered = [], []
    fake = SimpleNamespace(getUserAppDataDir=lambda: str(data), Console=SimpleNamespace(PrintError=errors.append))
    monkeypatch.setitem(sys.modules, 'FreeCAD', fake)
    monkeypatch.setattr(addon, 'register', lambda: registered.append(True))
    text = (ROOT/'CADWiz/InitGui.py').read_text()
    original_path = list(sys.path)
    try:
        for _ in range(3):
            exec(compile(text, 'InitGui.py', 'exec'), {}, {})
        assert len(registered) == 3 and not errors
        assert str(root/'src') in sys.path
    finally:
        sys.path[:] = original_path


def test_valid_repository_layout_is_not_misdiagnosed(source, tmp_path):
    shutil.copytree(source, tmp_path/'Mod/cadwiz/CADWiz')
    result = inspect(tmp_path)
    assert result['installations'][0]['method'] == 'repository-layout'
    assert not any('Nested' in x for x in result['installations'][0]['problems'])
