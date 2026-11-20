"""Real Windows shells and Python, mocked FreeCAD API (not a native 1.1.4 test)."""
import os
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
BIN = Path('C:/Program Files/FreeCAD 1.1/bin')
PWSH = Path(shutil.which('pwsh') or str(Path.home() / '.cache/codex-runtimes/codex-primary-runtime/dependencies/native/powershell/pwsh.exe'))


@pytest.mark.skipif(os.name != 'nt' or not (BIN / 'python.exe').exists(), reason='Windows FreeCAD Python required')
@pytest.mark.parametrize('shell', ['powershell.exe', str(PWSH)])
def test_native_shell_preserves_script_and_profile_paths(tmp_path, shell):
    if not shutil.which(shell):
        pytest.skip('shell unavailable')
    package = tmp_path / "Extracted [package] O'Neil"
    (package / 'scripts').mkdir(parents=True)
    (package / 'CADWiz').mkdir()
    (package / 'CADWiz/InitGui.py').touch()
    for name in ['install_windows.ps1', 'windows_installer.py']:
        shutil.copy2(ROOT / 'scripts' / name, package / 'scripts' / name)
    (package / 'scripts/FreeCAD.py').write_text(
        "import os\ndef Version(): return ['1','1','4']\ndef getUserAppDataDir(): return os.environ['CADWIZ_TEST_PROFILE']\n")
    profile = tmp_path / "User Profile [spaces] O'Neil"
    result = subprocess.run([shell, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                             str(package / 'scripts/install_windows.ps1'), '-FreeCADBin', str(BIN), '-CheckOnly', '-Yes'],
                            env=dict(os.environ, CADWIZ_TEST_PROFILE=str(profile)), capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert '1.1.4' in result.stdout and str(profile / 'Mod') in result.stdout
    assert not profile.exists()


@pytest.mark.skipif(os.name != 'nt' or not (BIN / 'python.exe').exists(), reason='Windows FreeCAD Python required')
def test_original_inline_command_reproduces_nameerror(tmp_path):
    script = tmp_path / 'original.ps1'
    script.write_text("& 'C:/Program Files/FreeCAD 1.1/bin/python.exe' -c 'from pathlib import Path; print(Path.cwd() / \"Mod\")'\nexit $LASTEXITCODE\n")
    result = subprocess.run(['powershell.exe', '-NoProfile', '-File', str(script)], capture_output=True, text=True, timeout=60)
    assert result.returncode != 0 and "name 'Mod' is not defined" in result.stderr


@pytest.mark.skipif(os.name != 'nt', reason='Windows shell required')
@pytest.mark.parametrize('tampered', [False, True])
def test_uninstall_hash_verification_without_optional_ps_modules(tmp_path, tampered):
    helper=tmp_path/'windows_installer.py'; helper.write_text('# fixture, never executed')
    digest=hashlib.sha256(helper.read_bytes()).hexdigest()
    record={'schema':2,'product':'CADWiz','managed_files':{str(helper):digest},'python':'C:/CADWiz-Missing-Python/python.exe'}
    (tmp_path/'install.json').write_text(json.dumps(record))
    if tampered: helper.write_text('modified fixture')
    result=subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',
                           str(ROOT/'scripts/uninstall_windows.ps1'),'-DataDir',str(tmp_path),'-Yes'],
                          env=dict(os.environ,PSModulePath=str(tmp_path/'No Modules')),capture_output=True,text=True,timeout=60)
    assert result.returncode != 0
    assert ('helper changed' if tampered else 'FreeCAD Python is unavailable') in result.stdout
