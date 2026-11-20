# SPDX-License-Identifier: LGPL-2.1-or-later
"""Execute the actual Setup.exe in an isolated native FreeCAD Windows profile."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import uuid


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--freecad-bin', type=Path, required=True)
    p.add_argument('--installer', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    args.freecad_bin = args.freecad_bin.resolve()
    args.installer = args.installer.resolve()
    args.output = args.output.resolve()
    assert os.name == 'nt', 'This acceptance check requires real Windows'
    args.output.mkdir(parents=True, exist_ok=True)
    qa = Path(tempfile.mkdtemp(prefix="CADWiz QA [spaces] O'Neil ")).resolve()
    profile = qa / 'FreeCAD Profile'; (profile / 'temp').mkdir(parents=True)
    data = qa / 'Setup Manager'; menu = qa / 'Start Menu'; desktop = qa / 'Desktop'
    key = 'Software\\CADWiz\\InstallerTests\\' + uuid.uuid4().hex
    env = dict(os.environ, FREECAD_USER_HOME=str(profile), FREECAD_USER_DATA=str(profile),
               FREECAD_USER_TEMP=str(profile / 'temp'), CADWIZ_TEST_REGISTRY_KEY=key)
    protected = [Path(os.environ['APPDATA']) / 'Claude/claude_desktop_config.json',
                 Path.home() / '.codex/config.toml']
    fc = Path(os.environ['APPDATA']) / 'FreeCAD'
    protected += list(fc.glob('*.cfg')) + list((fc / 'v1-1').glob('*.cfg'))
    before = {str(x): hashlib.sha256(x.read_bytes()).hexdigest() for x in protected if x.is_file()}
    import winreg
    def owner_apps_entry():
        values = []
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r'Software\Microsoft\Windows\CurrentVersion\Uninstall\CADWiz') as handle:
                for index in range(winreg.QueryInfoKey(handle)[1]):
                    values.append(winreg.EnumValue(handle, index))
        except FileNotFoundError:
            pass
        return values
    apps_before = owner_apps_entry()
    result = {'qa_root': str(qa), 'installer_sha256': hashlib.sha256(args.installer.read_bytes()).hexdigest(),
              'freecad_bin': str(args.freecad_bin), 'steps': [], 'protected_files': len(before)}
    def run(name, command, success=True):
        proc = subprocess.run(command, env=env, capture_output=True, text=True, errors='replace', timeout=300)
        (args.output / (name + '.txt')).write_text(proc.stdout + proc.stderr, encoding='utf8')
        result['steps'].append({'name': name, 'exit': proc.returncode})
        (args.output / 'acceptance.json').write_text(json.dumps(result, indent=2))
        assert (proc.returncode == 0) == success, (name, proc.returncode, proc.stdout[-1200:], proc.stderr[-1200:])
    def install(name, success=True, bin_dir=None):
        run(name, [str(args.installer), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/SP-', '/NORESTART',
                   '/FREECADBIN=' + str(bin_dir or args.freecad_bin), '/DATADIR=' + str(data),
                   '/STARTMENUDIR=' + str(menu), '/DESKTOPDIR=' + str(desktop),
                   '/LOG=' + str((args.output / (name + '-setup.log')).resolve())], success)
    def remove(name):
        # No --data-dir: prove installed-manager defaults target its own isolated receipt.
        run(name, [str(args.freecad_bin / 'python.exe'), str(data / 'windows_wizard.py'), '--remove', '--yes'])
        assert not (profile / 'Mod/CADWiz').exists()
        assert not list(menu.glob('*.lnk')) and not list(desktop.glob('*.lnk'))
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key):
                raise AssertionError('Owned Apps registration was not removed')
        except FileNotFoundError:
            pass
    install('missing-freecad', False, qa / 'Missing bin')
    assert not data.exists()
    install('fresh-install')
    receipt = json.loads((data / 'install.json').read_text())
    assert Path(receipt['mod_dir']).samefile(profile / 'Mod'), (receipt['mod_dir'], str(profile / 'Mod'))
    assert receipt['freecad_version'] == '1.1.4', receipt['freecad_version']
    assert len(list(menu.glob('*.lnk'))) == 2 and len(list(desktop.glob('*.lnk'))) == 1
    run('graphical-uninstaller-dependencies', [str(args.freecad_bin / 'python.exe'),
                                             str(data / 'windows_wizard.py'), '--qt-check', '--yes'])
    (profile / 'Mod/CADWiz/owner-model.FCStd').write_bytes(b'PRIVATE FIXTURE PRESERVE ME')
    install('upgrade')
    receipt = json.loads((data / 'install.json').read_text())
    assert (Path(receipt['backup']) / 'owner-model.FCStd').read_bytes() == b'PRIVATE FIXTURE PRESERVE ME'
    remove('uninstall')
    install('reinstall-after-uninstall')
    remove('final-uninstall')
    foreign = profile / 'Mod/CADWiz'; foreign.mkdir()
    (foreign / 'InitGui.py').write_text('# unrelated owner content')
    install('foreign-folder-refused', False)
    assert (foreign / 'InitGui.py').read_text() == '# unrelated owner content'
    foreign.rename(qa / 'Preserved foreign fixture')
    assert all(Path(name).is_file() and hashlib.sha256(Path(name).read_bytes()).hexdigest() == digest
               for name, digest in before.items()), 'Protected settings changed'
    assert owner_apps_entry() == apps_before, 'Owner Windows Apps registration changed'
    result.update(ok=True, native_freecad='1.1.4', protected_unchanged=True,
                  owner_apps_registration_unchanged=True,
                  note='Real packaged Windows installation checks; no desktop-account enrollment or live AI calls.')
    (args.output / 'acceptance.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
