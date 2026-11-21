# SPDX-License-Identifier: LGPL-2.1-or-later
"""Real macOS CI runner acceptance. Never run against an owner's profile.

This starts isolated, disposable FreeCAD GUIs on a CI desktop only. It does not
claim to be Neil's Mac or verify interactive assistant account enrollment.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    assert sys.platform == 'darwin' and os.environ.get('CI') == 'true', 'Isolated macOS CI only'
    repo = Path(__file__).resolve().parents[2]
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    qa = Path(tempfile.mkdtemp(prefix='CADWiz Mac QA '))
    profile = qa/'FreeCAD Profile'
    profile.mkdir()
    env = dict(os.environ, FREECAD_USER_HOME=str(profile), FREECAD_USER_DATA=str(profile),
               CADWIZ_SETTINGS_FILE=str(qa/'settings.json'), CADWIZ_SETUP_DIR=str(qa/'helper'),
               CADWIZ_PLUGIN_BRIDGE='off', CADWIZ_CLIENT_APP='auto')
    python = next(p for p in (args.app/'Contents/Resources/bin/python', args.app/'Contents/Resources/bin/python3') if p.is_file())
    modules = [p for p in args.app.rglob('FreeCAD*.so')
               if p.name == 'FreeCAD.so' or p.name.startswith('FreeCAD.cpython-')]
    assert len(modules) == 1, f'Expected one FreeCAD module in bundle: {modules}'
    env['PYTHONPATH'] = str(modules[0].parent)
    gui = args.app/'Contents/MacOS/FreeCAD'
    def run(command):
        result = subprocess.run(list(map(str, command)), env=env, capture_output=True, text=True, timeout=180)
        with (out/'commands.log').open('a') as log:
            log.write(result.stdout + result.stderr + '\n')
        assert result.returncode == 0, (command, result.stdout[-2000:], result.stderr[-2000:])
        return result.stdout
    reported = run([python, '-c', 'import FreeCAD; print("CADWIZ_DATA="+FreeCAD.getUserAppDataDir())'])
    data = Path(next(line.split('=', 1)[1] for line in reported.splitlines() if line.startswith('CADWIZ_DATA=')))
    assert data.resolve().is_relative_to(qa.resolve()), 'Refusing non-isolated FreeCAD profile'
    mod = data/'Mod'
    results = []
    def install():
        run(['bash', repo/'scripts/install_macos.sh'])
        assert (mod/'CADWiz/InitGui.py').is_file()
    env['FREECAD_PY'] = str(python)
    def startup(label):
        result_file = out/(label+'.json')
        macro = qa/(label+'.FCMacro')
        macro.write_text('''import json
from pathlib import Path
import FreeCAD, FreeCADGui
from PySide import QtCore, QtWidgets
def finish():
    window = FreeCADGui.getMainWindow()
    found = 'CADWizWorkbench' in FreeCADGui.listWorkbenches()
    if found:
        FreeCADGui.activateWorkbench('CADWizWorkbench')
    dock = window.findChild(QtWidgets.QDockWidget, 'AI_FreeCAD_Status_Dock')
    result = dict(workbench_registered=found, panel_visible=bool(dock and dock.isVisible()),
                  freecad_version=FreeCAD.Version()[:3])
    Path(RESULT).write_text(json.dumps(result, indent=2))
    FreeCADGui.getMainWindow().close()
QtCore.QTimer.singleShot(12000, finish)
'''.replace('RESULT', repr(str(result_file))))
        run([gui, macro])
        record = json.loads(result_file.read_text())
        assert record['workbench_registered'] and record['panel_visible'], record
        results.append({'test': label, 'status': 'PASS', **record})
    install()
    startup('clean-install')
    startup('restart-2')
    startup('restart-3')
    # Test an actual prior committed release, not just a directory labelled old.
    archive = qa/'old.zip'
    run(['git', '-C', repo, 'archive', '--format=zip', '--output='+str(archive), 'v0.9.1', 'CADWiz'])
    with zipfile.ZipFile(archive) as package:
        package.extractall(qa/'old')
    # Keep current disposable install outside Mod too.
    (mod/'CADWiz').rename(qa/'clean-before-upgrade')
    shutil.copytree(qa/'old/CADWiz', mod/'cadwiz')
    (mod/'cadwiz/owner-fixture.FCStd').write_bytes(b'preserve owner fixture')
    install()
    startup('upgrade-091')
    assert any(p.read_bytes() == b'preserve owner fixture' for p in (data/'CADWiz-backups').rglob('owner-fixture.FCStd'))
    (mod/'CADWiz').rename(qa/'before-nested')
    shutil.copytree(qa/'old/CADWiz', mod/'cadwiz/cadwiz-release-0.9.1/CADWiz')
    (mod/'cadwiz/.git').mkdir()
    shutil.copytree(qa/'old/CADWiz', mod/'cadwiz.backup.interrupted')
    install()
    startup('neil-nested-recovery')
    # Optional setup failures are forced in the installed code in this QA profile.
    setup = mod/'CADWiz/src/integrations/cadwiz_plugin/setup_startup.py'
    setup.write_text('raise ImportError("forced optional setup dependency failure")\n')
    startup('optional-setup-failure-no-ai')
    results.extend([{'test': 'Neil physical Mac and interactive assistant connection', 'status': 'NOT VERIFIED'},
                    {'test': 'network physically disconnected', 'status': 'NOT VERIFIED'}])
    (out/'acceptance.json').write_text(json.dumps({'platform': 'real macOS CI runner', 'tests': results}, indent=2))


if __name__ == '__main__':
    main()
