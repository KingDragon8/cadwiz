# SPDX-License-Identifier: LGPL-2.1-or-later
"""Thin native-setup adapter. Installation remains in the verified transaction core."""
from __future__ import annotations
import argparse
import configparser
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

VERSION = '0.9.8'
REGISTRY = r'Software\Microsoft\Windows\CurrentVersion\Uninstall\CADWiz'


def widgets():
    try:
        from PySide6 import QtWidgets
    except ImportError:
        from PySide2 import QtWidgets
    return QtWidgets


def core(data):
    helper = Path(__file__).with_name('windows_installer.py').resolve()
    # Installed managers must prove integrity before loading executable helper code.
    record = Path(data) / 'install.json'
    if Path(__file__).parent.resolve() == Path(data).resolve() and record.is_file():
        value = json.loads(record.read_text(encoding='utf-8-sig'))
        expected = value.get('managed_files', {}).get(str(helper))
        if not expected or hashlib.sha256(helper.read_bytes()).hexdigest() != expected:
            raise RuntimeError('The uninstall helper changed. Your files were kept; reinstall CADWiz or get help.')
    spec = importlib.util.spec_from_file_location('cadwiz_windows_setup', helper)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def registry_key():
    test = os.environ.get('CADWIZ_TEST_REGISTRY_KEY', '')
    if test:
        if not test.startswith('Software\\CADWiz\\InstallerTests\\'):
            raise RuntimeError('Invalid isolated registry test location.')
        return test
    return REGISTRY


def registry_read(key):
    import winreg
    result = {}
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as handle:
            index = 0
            while True:
                try:
                    name, value, kind = winreg.EnumValue(handle, index)
                    result[name] = (value, kind); index += 1
                except OSError:
                    break
    except FileNotFoundError:
        pass
    return result


def registry_write(key, values):
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key) as handle:
        for name, (value, kind) in values.items():
            winreg.SetValueEx(handle, name, 0, kind, value)


def registry_commit(receipt):
    import winreg
    data = Path(receipt['python']).parent
    manager = Path(next(name for name in receipt['managed_files'] if Path(name).name == 'windows_wizard.py'))
    key = registry_key(); previous = registry_read(key)
    if previous and previous.get('CADWizManaged', ('', 0))[0] != str(manager):
        raise RuntimeError('An unrelated Windows Apps entry exists. It was preserved; get help.')
    command = '"' + str(data / 'pythonw.exe') + '" "' + str(manager) + '" --remove'
    values = {name: (value, winreg.REG_SZ) for name, value in {
        'DisplayName': 'CADWiz', 'DisplayVersion': VERSION, 'Publisher': 'WizLabs',
        'UninstallString': command, 'QuietUninstallString': command + ' --yes',
        'InstallLocation': receipt['addon'], 'CADWizManaged': str(manager),
        'DisplayIcon': str(Path(receipt['addon']) / 'Resources/icons/cadwiz.ico'),
        'URLInfoAbout': 'https://cadwiz.app'}.items()}
    values.update({'NoModify': (1, winreg.REG_DWORD), 'NoRepair': (1, winreg.REG_DWORD)})
    if previous:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as handle:
            if winreg.QueryInfoKey(handle)[0]:
                raise RuntimeError('The Apps entry has additional owner data. It was preserved; get help.')
    def restore():
        try: winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key)
        except FileNotFoundError: pass
        if previous: registry_write(key, previous)
    try:
        registry_write(key, values)
    except Exception:
        # A partial registration must not survive a failed add-on transaction.
        restore()
        raise
    written = registry_read(key)
    receipt['wizard_registry_key'] = key
    def undo():
        if registry_read(key) == written:
            restore()
    return undo


def remove(data, yes):
    backend = core(data)
    record = json.loads((Path(data) / 'install.json').read_text(encoding='utf-8-sig'))
    if not yes:
        QtWidgets = widgets()
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv[:1])
        if QtWidgets.QMessageBox.question(None, 'Uninstall CADWiz',
                'Remove CADWiz from FreeCAD?\n\nYour models, preferences and a recovery copy will be kept.',
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No, QtWidgets.QMessageBox.No) != QtWidgets.QMessageBox.Yes:
            return {'message': 'Cancelled. Nothing removed.'}
    result = ({'message': 'CADWiz is already removed. Saved files were kept.'}
              if record.get('state') == 'uninstalled' else backend.uninstall(data))
    key = record.get('wizard_registry_key')
    if key and key == registry_key():
        import winreg
        current = registry_read(key)
        if current.get('CADWizManaged', ('', 0))[0] == str(Path(data) / 'windows_wizard.py'):
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key)
    return result


def perform(args):
    data = Path(args.data_dir).resolve()
    if args.qt_check:
        QtWidgets = widgets()
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv[:1])
        box = QtWidgets.QMessageBox(); box.setWindowTitle('CADWiz Setup'); box.setText('UI dependency check')
        assert box.windowTitle() == 'CADWiz Setup'
        box.close()
        return {'message': 'Graphical uninstall controls loaded.'}
    if args.open:
        import subprocess
        backend = core(data)
        if not backend.running_freecad():
            subprocess.Popen([str(Path(sys.executable).with_name('FreeCAD.exe'))])
        return {'message': 'Use the running FreeCAD window.'}
    if args.remove:
        return remove(data, args.yes)
    backend = core(data); info = backend.discover()
    mod = backend.destination(info)
    if args.action == 'probe':
        if args.require_closed and backend.running_freecad():
            raise RuntimeError('FreeCAD is already open. Use its existing window.')
        return {'version': info['version'], 'mod_dir': str(mod),
                'message': 'FreeCAD ' + info['version'] + ' is ready. Your add-on folder was verified.'}
    bin_dir = Path(info['python']).parent
    if not (bin_dir / 'pythonw.exe').is_file():
        raise RuntimeError('FreeCAD pythonw.exe is missing. Repair FreeCAD, then try again.')
    manager = data / 'windows_wizard.py'
    icon = str(mod / 'CADWiz/Resources/icons/cadwiz.ico') + ',0'
    command = '"' + str(manager) + '" --remove'
    menu = Path(args.start_menu)
    specs = [dict(path=str(menu / 'CADWiz.lnk'), target=str(bin_dir / 'pythonw.exe'), arguments='"' + str(manager) + '" --open',
                  working_directory=str(bin_dir), description='Open FreeCAD with CADWiz', icon=icon),
             dict(path=str(menu / 'Uninstall CADWiz.lnk'), target=str(bin_dir / 'pythonw.exe'), arguments=command,
                  working_directory=str(data), description='Uninstall CADWiz; keep models and preferences', icon=icon)]
    if args.desktop:
        specs.append(dict(specs[0], path=str(Path(args.desktop) / 'CADWiz.lnk')))
    receipt = backend.install(Path(args.source), info, mod, data, specs, commit=registry_commit)
    return {'version': info['version'], 'mod_dir': str(mod), 'addon': receipt['addon'],
            'message': 'CADWiz files are installed and verified. Open FreeCAD, then use CADWiz Setup to connect your assistant.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['probe', 'install'], nargs='?', default='probe')
    parser.add_argument('--remove', action='store_true'); parser.add_argument('--yes', action='store_true')
    parser.add_argument('--open', action='store_true'); parser.add_argument('--require-closed', action='store_true')
    parser.add_argument('--qt-check', action='store_true')
    parser.add_argument('--source'); parser.add_argument('--desktop'); parser.add_argument('--start-menu')
    default_data = (Path(__file__).parent if Path(__file__).with_name('install.json').is_file()
                    else Path(os.environ['LOCALAPPDATA']) / 'CADWiz')
    parser.add_argument('--data-dir', default=str(default_data))
    parser.add_argument('--ini')
    args = parser.parse_args()
    try:
        result = perform(args); ok = True
    except Exception as error:
        result = {'message': str(error) or type(error).__name__}; ok = False
    if args.ini:
        ini = configparser.ConfigParser(interpolation=None)
        ini['result'] = dict(ok='1' if ok else '0', **{k: str(v).replace('\n', ' ') for k, v in result.items()})
        with open(args.ini, 'w', encoding='utf-16') as stream: ini.write(stream)
    elif args.open and ok:
        pass
    elif not args.yes:
        QtWidgets = widgets()
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv[:1])
        box = QtWidgets.QMessageBox.information if ok else QtWidgets.QMessageBox.warning
        box(None, 'CADWiz Setup', result['message'])
    else:
        print(json.dumps(dict(ok=ok, **result)))
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
