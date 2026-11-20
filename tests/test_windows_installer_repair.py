# SPDX-License-Identifier: LGPL-2.1-or-later
"""Filesystem/command stand-ins. These do not claim a native FreeCAD install."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
from types import SimpleNamespace
import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('windows_installer', ROOT / 'scripts/windows_installer.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


@pytest.fixture
def area(tmp_path):
    root = tmp_path / "Jonny Miskelly [test] O'Neil"
    source = root / 'Extracted Package/CADWiz'
    (source / 'src/integrations/cadwiz_plugin').mkdir(parents=True)
    (source / 'InitGui.py').write_text('from integrations.cadwiz_plugin.addon import register\n')
    (source / 'src/integrations/cadwiz_plugin/addon.py').write_text('# fixture\n')
    (source / 'important.txt').write_text('fixture package')
    profile = root / 'Roaming/FreeCAD/v1-1'; mod = profile / 'Mod'
    data = root / 'Local/CADWiz'
    info = {'version': '1.1.4', 'user_data': str(profile), 'mod_dir': str(mod)}
    return SimpleNamespace(root=root, source=source, mod=mod, data=data, info=info)


def install(area, **kwargs):
    return installer.install(area.source, area.info, area.mod, area.data,
                             prerequisite=lambda _: None, make_shortcuts=lambda *args: [],
                             running=lambda: False, **kwargs)


@pytest.mark.parametrize('version', [('1','1','4'), ('1','1','3'), ('1','10','0'), ('2','0','0')])
def test_documented_version_detection_uses_api_not_folder_name(area, version):
    app = SimpleNamespace(Version=lambda: version, getUserAppDataDir=lambda: str(area.mod.parent))
    found = installer.discover(app)
    assert found['mod_dir'] == str(area.mod) and found['version'] == '.'.join(version)


def test_missing_old_freecad_and_no_directory_are_explicit(area):
    with pytest.raises(installer.SetupError, match='1.1'):
        installer.discover(SimpleNamespace(Version=lambda: ['0','21','2']))
    found = installer.discover(SimpleNamespace(Version=lambda: ['1','1','4'], getUserAppDataDir=lambda: ''))
    with pytest.raises(installer.SetupError, match='Open FreeCAD once'):
        installer.destination(found)
    assert not area.mod.exists()


def test_profile_spaces_and_successful_verified_install_preserve_other_files(area):
    area.mod.mkdir(parents=True)
    other = area.mod / 'Unrelated'; other.mkdir(); (other / 'InitGui.py').write_text('owner module')
    area.data.mkdir(parents=True); prefs = area.data / 'preferences.json'; prefs.write_text('owner preferences')
    assistant = area.root / 'claude_desktop_config.json'; assistant.write_text('{"owner":true}')
    receipt = install(area)
    assert installer.owned_addon(area.mod / 'CADWiz', receipt['installation_id'])
    assert (other / 'InitGui.py').read_text() == 'owner module'
    assert prefs.read_text() == 'owner preferences' and assistant.read_text() == '{"owner":true}'
    assert receipt['freecad_version'] == '1.1.4'


@pytest.mark.parametrize('kind', ['relative', 'wrong_name', 'wrong_profile', 'file'])
def test_invalid_destination_is_rejected_before_install(area, kind):
    paths = {'relative': Path('Mod'), 'wrong_name': area.mod.parent / 'bin',
             'wrong_profile': area.root / 'Other/Mod', 'file': area.mod}
    if kind == 'file':
        area.mod.parent.mkdir(parents=True); area.mod.write_text('owner file')
    with pytest.raises(installer.SetupError):
        installer.destination(area.info, paths[kind])
    assert not area.data.exists()


def test_manual_fallback_requires_real_freecad_config(area):
    info = dict(area.info, user_data=None, mod_dir=None)
    with pytest.raises(installer.SetupError): installer.destination(info, area.mod)
    area.mod.parent.mkdir(parents=True)
    (area.mod.parent / 'user.cfg').write_text('<unrelated/>')
    with pytest.raises(installer.SetupError): installer.destination(info, area.mod)
    (area.mod.parent / 'user.cfg').write_text('<FCParameters/>')
    assert installer.destination(info, area.mod) == area.mod


def test_repeated_install_keeps_prior_addon_outside_mod(area):
    first = install(area)
    (area.mod / 'CADWiz/owner-model.FCStd').write_bytes(b'owner fixture')
    (area.source / 'important.txt').write_text('new fixture package')
    second = install(area)
    assert first['installation_id'] != second['installation_id']
    backup = Path(second['backup'])
    assert area.mod not in backup.parents
    assert (backup / 'owner-model.FCStd').read_bytes() == b'owner fixture'
    assert (area.mod / 'CADWiz/important.txt').read_text() == 'new fixture package'
    assert len([p for p in area.mod.iterdir() if p.is_dir()]) == 1


def test_legacy_target_can_upgrade_but_foreign_or_duplicate_is_preserved(area):
    target = area.mod / 'CADWiz'; target.mkdir(parents=True)
    (target / 'InitGui.py').write_text('unrelated startup')
    with pytest.raises(installer.SetupError, match='unrecognized'): install(area)
    assert (target / 'InitGui.py').read_text() == 'unrelated startup'
    shutil.rmtree(target)
    shutil.copytree(area.source, area.mod / 'AI-FreeCAD')
    with pytest.raises(installer.SetupError, match='Another CADWiz'): install(area)
    assert (area.mod / 'AI-FreeCAD/important.txt').is_file()


def test_legacy_addon_without_receipt_is_backed_up(area):
    shutil.copytree(area.source, area.mod / 'CADWiz')
    receipt = install(area)
    assert Path(receipt['backup']).is_dir()


def test_prerequisite_failure_leaves_existing_installation_untouched(area):
    receipt = install(area); before = (area.data / 'install.json').read_bytes()
    def fail(_): raise installer.SetupError('fixture prerequisite failure')
    with pytest.raises(installer.SetupError):
        installer.install(area.source, area.info, area.mod, area.data, prerequisite=fail, running=lambda: False)
    assert (area.data / 'install.json').read_bytes() == before
    assert installer.owned_addon(area.mod / 'CADWiz', receipt['installation_id'])


def test_commit_failure_restores_old_addon_record_and_manager(area):
    receipt = install(area); original = (area.data / 'install.json').read_bytes()
    helper = (area.data / 'windows_installer.py').read_bytes()
    (area.source / 'important.txt').write_text('changed fixture')
    def fail(source, target):
        if Path(target).name == 'uninstall_windows.ps1': raise OSError('fixture copy failure')
        os.replace(source, target)
    with pytest.raises(OSError, match='fixture'):
        install(area, replace=fail)
    assert installer.owned_addon(area.mod / 'CADWiz', receipt['installation_id'])
    assert (area.mod / 'CADWiz/important.txt').read_text() == 'fixture package'
    assert (area.data / 'install.json').read_bytes() == original
    assert (area.data / 'windows_installer.py').read_bytes() == helper


def test_existing_modified_manager_and_open_freecad_are_not_overwritten(area):
    install(area)
    manager = area.data / 'windows_installer.py'; manager.write_text('owner changes')
    with pytest.raises(installer.SetupError, match='preserved'): install(area)
    assert manager.read_text() == 'owner changes'
    with pytest.raises(installer.SetupError, match='FreeCAD is open'):
        installer.install(area.source, area.info, area.mod, area.data, running=lambda: True)


def test_uninstall_keeps_models_preferences_and_every_unrelated_module(area):
    receipt = install(area)
    (area.mod / 'CADWiz/owner-model.FCStd').write_bytes(b'owned model')
    other = area.mod / 'Other'; other.mkdir(); (other / 'keep.txt').write_text('keep')
    prefs = area.data / 'preferences.json'; prefs.write_text('keep prefs')
    result = installer.uninstall(area.data, running=lambda: False)
    assert not (area.mod / 'CADWiz').exists() and (other / 'keep.txt').read_text() == 'keep'
    assert prefs.read_text() == 'keep prefs'
    assert (Path(result['preserved'][0]) / 'owner-model.FCStd').read_bytes() == b'owned model'
    with pytest.raises(installer.SetupError, match='No CADWiz'):
        installer.uninstall(area.data, running=lambda: False)


@pytest.mark.parametrize('tamper', ['addon', 'id', 'shortcut'])
def test_tampered_uninstall_record_fails_closed(area, tamper):
    receipt = install(area)
    if tamper == 'addon': receipt['addon'] = str(area.root)
    elif tamper == 'id': receipt['installation_id'] = 'wrong'
    else: receipt['shortcuts'] = [str(area.root / 'unrelated.txt')]
    (area.data / 'install.json').write_text(json.dumps(receipt))
    with pytest.raises(installer.SetupError): installer.uninstall(area.data, running=lambda: False)
    assert (area.mod / 'CADWiz/important.txt').is_file()


def test_helper_command_failure_is_a_prerequisite_error(area, monkeypatch):
    monkeypatch.setattr(installer.subprocess, 'run', lambda *a, **k: SimpleNamespace(returncode=1, stderr='fixture helper error', stdout=''))
    with pytest.raises(installer.SetupError, match='helper could not be verified'):
        installer.check_helper(area.source)


def test_receipt_failure_restores_existing_installation(area, monkeypatch):
    first = install(area)
    before = (area.data / 'install.json').read_bytes()
    original = installer.write_json
    def fail_receipt(path, value):
        if Path(path) == area.data / 'install.json':
            raise OSError('fixture receipt failure')
        return original(path, value)
    monkeypatch.setattr(installer, 'write_json', fail_receipt)
    with pytest.raises(OSError, match='fixture receipt'):
        install(area)
    assert installer.owned_addon(area.mod / 'CADWiz', first['installation_id'])
    assert (area.data / 'install.json').read_bytes() == before


def test_reinstall_after_uninstall_reuses_only_verified_manager_files(area):
    install(area)
    installer.uninstall(area.data, running=lambda: False)
    assert json.loads((area.data / 'install.json').read_text())['state'] == 'uninstalled'
    receipt = install(area)
    assert installer.owned_addon(area.mod / 'CADWiz', receipt['installation_id'])
    installer.uninstall(area.data, running=lambda: False)
    (area.data / 'windows_installer.py').write_text('owner modified manager')
    with pytest.raises(installer.SetupError, match='preserved'):
        install(area)
