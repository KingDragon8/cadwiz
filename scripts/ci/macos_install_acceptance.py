# SPDX-License-Identifier: LGPL-2.1-or-later
"""Real macOS CI runner acceptance. Never run against an owner's profile.

This starts isolated, disposable FreeCAD GUIs on a CI desktop only. It does not
claim to be the customer's Mac or verify interactive assistant account enrollment.
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
    parser.add_argument('--case-parent', type=Path)
    parser.add_argument('--legacy-addon-archive', type=Path,
                        help='Pinned prior-release CADWiz ZIP fixture when testing an extracted customer download without Git history')
    parser.add_argument('--network-audit', action='store_true', help='Record socket addresses/stacks in disposable CI only')
    args = parser.parse_args()
    assert sys.platform == 'darwin' and os.environ.get('CI') == 'true', 'Isolated macOS CI only'
    repo = Path(__file__).resolve().parents[2]
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    if args.case_parent:
        assert args.case_parent.resolve().is_relative_to(Path(os.environ['RUNNER_TEMP']).resolve())
    qa = Path(tempfile.mkdtemp(prefix='CADWiz Mac QA ', dir=args.case_parent))
    profile = qa/'FreeCAD Profile'
    profile.mkdir()
    env = dict(os.environ, FREECAD_USER_HOME=str(profile), FREECAD_USER_DATA=str(profile),
               CADWIZ_SETTINGS_FILE=str(qa/'settings.json'), CADWIZ_SETUP_DIR=str(qa/'helper'),
               CADWIZ_PLUGIN_BRIDGE='on', CADWIZ_CLIENT_APP='auto', LOCALAPPDATA=str(qa/'plugin-data'))
    python = next(p for p in (args.app/'Contents/Resources/bin/python', args.app/'Contents/Resources/bin/python3') if p.is_file())
    modules = [p for p in args.app.rglob('FreeCAD*.so')
               if p.name == 'FreeCAD.so' or p.name.startswith('FreeCAD.cpython-')]
    assert len(modules) == 1, f'Expected one FreeCAD module in bundle: {modules}'
    env['PYTHONPATH'] = str(modules[0].parent)
    if args.network_audit:
        env['PYTHONPATH'] += os.pathsep+str(repo/'scripts/ci/network_audit')
        env['CADWIZ_NETWORK_AUDIT_DIR'] = str(out/'network-audit')
    gui = args.app/'Contents/MacOS/FreeCAD'
    def run(command):
        try:
            result = subprocess.run(list(map(str, command)), env=env, capture_output=True, text=True, timeout=180)
        except subprocess.TimeoutExpired as error:
            with (out/'commands.log').open('a') as log:
                for value in (error.stdout, error.stderr):
                    if value:
                        log.write(value.decode('utf8',errors='replace') if isinstance(value,bytes) else value)
            raise
        with (out/'commands.log').open('a') as log:
            log.write(result.stdout + result.stderr + '\n')
        assert result.returncode == 0, (command, result.stdout[-2000:], result.stderr[-2000:])
        return result.stdout
    reported = run([python, '-c', 'import FreeCAD; print("CADWIZ_DATA="+FreeCAD.getUserAppDataDir())'])
    data = Path(next(line.split('=', 1)[1] for line in reported.splitlines() if line.startswith('CADWIZ_DATA=')))
    assert data.resolve().is_relative_to(qa.resolve()), 'Refusing non-isolated FreeCAD profile'
    mod = data/'Mod'
    case_probe = qa/'CaseProbe'
    case_probe.write_text('case check')
    case_sensitive = not (qa/'caseprobe').exists()
    results = []
    def save_results():
        (out/'acceptance.json').write_text(json.dumps({'platform': 'real macOS CI runner',
            'case_sensitive': case_sensitive, 'tests': results}, indent=2))
    def install():
        run(['bash', repo/'scripts/install_macos.sh'])
        assert (mod/'CADWiz/InitGui.py').is_file()
    env['FREECAD_PY'] = str(python)
    def startup(label, offline=False):
        result_file = out/(label+'.json')
        macro = qa/(label+'.FCMacro')
        macro.write_text('''import json
from pathlib import Path
import FreeCAD, FreeCADGui, traceback
from PySide import QtCore, QtWidgets
def finish():
    window = FreeCADGui.getMainWindow()
    window.showMaximized()
    FreeCADGui.updateGui()
    result = {}
    try:
        found = 'CADWizWorkbench' in FreeCADGui.listWorkbenches()
        if found:
            FreeCADGui.activateWorkbench('CADWizWorkbench')
        dock = window.findChild(QtWidgets.QDockWidget, 'AI_FreeCAD_Status_Dock')
        creating = window.findChild(QtWidgets.QPushButton, 'CADWiz_Page_Creating')
        if creating:
            creating.click()
        title = window.findChild(QtWidgets.QLabel, 'CADWiz_Communication_Title')
        guidance = window.findChild(QtWidgets.QLabel, 'CADWiz_Communication_Guidance')
        aiwiz = window.findChild(QtWidgets.QTabWidget, 'CADWiz_AIWiz')
        content = window.findChild(QtWidgets.QWidget, 'CADWiz_Slim_Panel')
        support = window.findChild(QtWidgets.QPushButton, 'CADWiz_Support_Help')
        working = window.findChild(QtWidgets.QPushButton, 'CADWiz_Working_File')
        panel = getattr(content, '_cadwiz_panel', None)
        import integrations.cadwiz_plugin as plugin
        result = dict(workbench_registered=found, panel_visible=bool(dock and dock.isVisible()),
                      freecad_version=FreeCAD.Version()[:3], cadwiz_version=plugin.CADWIZ_VERSION,
                      loaded_source=str(Path(plugin.__file__).resolve().parents[3]),
                      communication_title=title.text() if title else '',
                      guidance_present=bool(guidance and 'quick buttons above' in guidance.text()),
                      aiwiz_tabs=[aiwiz.tabText(i) for i in range(aiwiz.count())] if aiwiz else [],
                      restored_ai_choice=getattr(getattr(panel, 'free_ai', None), 'route', ''))
        result['support_button_visible'] = bool(support and support.isVisible())
        result['working_file_button_visible'] = bool(working and working.isVisible())
        if RUN_NEIL_GUI:
            import sys
            sys.path.insert(0, PULLEY_SCRIPTS)
            from native_pulley_gui_check import check
            result['pulley_native_gui'] = check(FreeCAD, FreeCADGui, PULLEY_OUTPUT, panel)
    except Exception:
        result['error'] = traceback.format_exc()
    finally:
        Path(RESULT).write_text(json.dumps(result, indent=2))
        if RUN_NEIL_GUI:
            # Only disposable test documents; avoid an unsaved-file close prompt
            # hiding a recorded assertion failure behind the outer timeout.
            for document in list(FreeCAD.listDocuments().values()):
                if document.FileName and Path(document.FileName).resolve().is_relative_to(Path(PULLEY_OUTPUT).resolve()):
                    FreeCAD.closeDocument(document.Name)
        window.close()
QtCore.QTimer.singleShot(12000, finish)
'''.replace('RESULT', repr(str(result_file))).replace('RUN_NEIL_GUI', repr(label == 'clean-install'))
   .replace('PULLEY_SCRIPTS', repr(str(repo/'scripts/ci'))).replace('PULLEY_OUTPUT', repr(str(out/'pulley-gui'))))
        command = [gui, macro]
        if offline:
            command = ['/usr/bin/sandbox-exec', '-p', '(version 1)(allow default)(deny network*)', *command]
        run(command)
        record = json.loads(result_file.read_text())
        if label == 'clean-install' and record.get('error'):
            # Capture the actual headless snapshot descriptors, without changing
            # the fixture or concealing the original GUI assertion failure.
            fixture=out/'pulley-gui'/'WorkerSnapshot.FCStd'
            if not fixture.is_file():fixture=out/'pulley-gui'/'Working.FCStd'
            if fixture.is_file():
                probe=subprocess.run([str(python),str(repo/'scripts/ci/native_reference_probe.py'),str(fixture),str(fixture.parent/'worker-reference.json')],
                                     env=env,capture_output=True,text=True,timeout=30)
                (out/'reference-probe.log').write_text(probe.stdout+probe.stderr)
        assert record['workbench_registered'] and record['panel_visible'], record
        assert record['support_button_visible'] and record['working_file_button_visible'], record
        if label == 'clean-install':
            assert record.get('pulley_native_gui', {}).get('status') == 'PASS', record
        expected_version = json.loads((repo/'CADWiz/Resources/claude-extension/manifest.json').read_text())['version']
        assert record['cadwiz_version'] == expected_version, record
        assert record['communication_title'] == 'Wiz communication screen' and record['guidance_present'], record
        assert record['aiwiz_tabs'] == ['AI Wiz Setup', 'AI Wiz Management'], record
        assert Path(record['loaded_source']).samefile(mod/'CADWiz'), record
        if label != 'clean-install':
            assert record['restored_ai_choice'] == 'codex_cli', record
        results.append({'test': label, 'status': 'PASS', **record})
        save_results()
    install()
    if case_sensitive:
        identity_report=out/'case-identity-report.json'
        run([python,repo/'scripts/ci/native_case_identity_check.py','--folder',qa/'CaseDocNames',
             '--output',identity_report])
        identity=json.loads(identity_report.read_text())
        assert identity['status']=='PASS', identity
        results.append({'test':'case-sensitive-document-identity','status':'PASS','document_identity':identity})
        save_results()
    startup('clean-install')
    preference = qa/'plugin-data/CADWiz/plugin/preferences.json'
    preference.parent.mkdir(parents=True, exist_ok=True)
    preference.write_text(json.dumps({'ai_app': 'codex_cli', 'ai_setup_route': 'codex_cli'}))
    startup('restart-2')
    startup('restart-3')
    # Test an actual prior committed release, not just a directory labelled old.
    archive = qa/'old.zip'
    if args.legacy_addon_archive:
        shutil.copyfile(args.legacy_addon_archive, archive)
    else:
        run(['git', '-C', repo, 'archive', '--format=zip', '--output='+str(archive), 'v0.9.1', 'CADWiz'])
    with zipfile.ZipFile(archive) as package:
        assert all(not Path(name).is_absolute() and '..' not in Path(name).parts
                   and Path(name).parts[0] == 'CADWiz' for name in package.namelist()), 'Unsafe prior-release fixture'
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
    startup('customer-nested-recovery')
    # Optional setup failures are forced in the installed code in this QA profile.
    setup = mod/'CADWiz/src/integrations/cadwiz_plugin/setup_startup.py'
    setup_source = setup.read_text()
    setup.write_text('raise ImportError("forced optional setup dependency failure")\n')
    startup('optional-setup-failure-no-ai')
    setup.write_text(setup_source)
    # Confirm the process sandbox really denies socket access, then launch the
    # real GUI in that same sandbox. The CI runner itself remains connected.
    proof = ('import socket, errno\ntry:\n socket.create_connection(("127.0.0.1",9),timeout=1)\n'
             'except OSError as e:\n assert e.errno in (errno.EPERM,errno.EACCES),repr(e)\n'
             'else:\n raise AssertionError("network sandbox did not deny access")\n')
    run(['/usr/bin/sandbox-exec', '-p', '(version 1)(allow default)(deny network*)', python, '-c', proof])
    startup('network-denied-startup', offline=True)
    results.append({'test': 'Customer physical Mac and interactive assistant connection', 'status': 'NOT VERIFIED'})
    save_results()


if __name__ == '__main__':
    main()
