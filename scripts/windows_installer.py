# SPDX-License-Identifier: LGPL-2.1-or-later
"""Offline Windows setup. Python code is a file, never a native -c argument."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import uuid
import xml.etree.ElementTree as ET

MARKER = '.cadwiz-install.json'
PRODUCT = 'CADWiz'
LEGACY_UNINSTALL_SHA = 'b66cfbaca1e146b1f45673a946f1403cd94251f82c94913ecde351066b4eb050'


class SetupError(RuntimeError):
    pass


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def linked(path):
    path = Path(path)
    return path.is_symlink() or (path.exists() and bool(getattr(path.lstat(), 'st_file_attributes', 0)
                                                      & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 1024)))


def absolute(path):
    path = Path(path)
    if not path.is_absolute() or linked(path):
        raise SetupError('Choose an absolute, regular folder, not a shortcut or linked folder: ' + str(path))
    return path.resolve()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix='.cadwiz-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf8') as stream:
            json.dump(value, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        Path(temp).unlink(missing_ok=True)


def discover(app=None):
    if app is None:
        import FreeCAD as app
    version = list(app.Version())
    if tuple(int(v) for v in version[:2]) < (1, 1):
        raise SetupError('CADWiz needs FreeCAD 1.1 or newer. Install a supported FreeCAD release first.')
    if sys.version_info < (3, 11):
        raise SetupError('This package needs FreeCAD Python 3.11 or newer.')
    result = {'version': '.'.join(str(v) for v in version[:3]), 'python': sys.executable,
              'user_data': None, 'mod_dir': None}
    try:
        raw = app.getUserAppDataDir()
        if not raw or not Path(raw).is_absolute():
            raise ValueError('FreeCAD returned no absolute user-data folder')
        base = absolute(raw)
        result.update(user_data=str(base), mod_dir=str(base / 'Mod'))
    except (OSError, ValueError, SetupError) as error:
        result['discovery_error'] = str(error)
    return result


def destination(info, supplied=None):
    raw = supplied or info.get('mod_dir')
    if not raw:
        raise SetupError('FreeCAD could not report its user folder. Open FreeCAD once, close it, and run setup again. '
                         'The advanced -ModDir fallback accepts the Mod folder beside FreeCAD user.cfg.')
    mod = absolute(raw)
    if mod.parent.exists() and not mod.parent.is_dir():
        raise SetupError('FreeCAD\'s user-data location is not a directory. Nothing installed.')
    if mod.name.casefold() != 'mod' or (mod.exists() and not mod.is_dir()):
        raise SetupError('The destination must be FreeCAD\'s user Mod directory, not the program bin folder.')
    if info.get('mod_dir'):
        if mod != absolute(info['mod_dir']):
            raise SetupError('The selected Mod directory differs from this FreeCAD\'s reported user directory. Nothing installed.')
    else:
        config = mod.parent / 'user.cfg'
        if not config.is_file() or config.stat().st_size > 8 * 1024 * 1024:
            raise SetupError('Manual fallback needs a FreeCAD user.cfg beside Mod. Open FreeCAD once first.')
        try:
            if ET.parse(config).getroot().tag != 'FCParameters':
                raise ValueError()
        except (ET.ParseError, ValueError):
            raise SetupError('The selected folder does not contain a recognizable FreeCAD user.cfg.') from None
    return mod


def owned_addon(path, installation_id=None):
    path = Path(path)
    if linked(path) or not path.is_dir():
        return False
    marker = path / MARKER
    if marker.exists():
        try:
            value = json.loads(marker.read_text(encoding='utf8'))
            return value.get('product') == PRODUCT and bool(value.get('installation_id')) and (
                installation_id is None or value['installation_id'] == installation_id)
        except (OSError, ValueError):
            return False
    if installation_id is not None:
        return False
    # Recognize the actual legacy public add-on without executing its startup.
    for candidate in (path, path / 'CADWiz'):
        init = candidate / 'InitGui.py'
        if (not linked(candidate) and init.is_file() and
                (candidate / 'src/integrations/cadwiz_plugin/addon.py').is_file() and
                'integrations.cadwiz_plugin.addon' in init.read_text(encoding='utf8', errors='replace')):
            return True
    return False


def running_freecad():
    if os.name != 'nt':
        return False
    # Toolhelp does not depend on WMI/tasklist, which can be disabled or broken.
    import ctypes
    from ctypes import wintypes
    class ProcessEntry(ctypes.Structure):
        _fields_ = [('dwSize', wintypes.DWORD), ('cntUsage', wintypes.DWORD),
                    ('th32ProcessID', wintypes.DWORD), ('th32DefaultHeapID', ctypes.c_size_t),
                    ('th32ModuleID', wintypes.DWORD), ('cntThreads', wintypes.DWORD),
                    ('th32ParentProcessID', wintypes.DWORD), ('pcPriClassBase', wintypes.LONG),
                    ('dwFlags', wintypes.DWORD), ('szExeFile', wintypes.WCHAR * 260)]
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
    kernel.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateToolhelp32Snapshot(2, 0)
    if handle == ctypes.c_void_p(-1).value:
        raise SetupError('Windows could not check open applications. Close FreeCAD and retry.')
    try:
        entry = ProcessEntry(); entry.dwSize = ctypes.sizeof(entry)
        found = kernel.Process32FirstW(handle, ctypes.byref(entry))
        if not found:
            raise SetupError('Windows could not enumerate open applications. Nothing installed.')
        while found:
            if entry.szExeFile.casefold() in {'freecad.exe', 'freecadmain.exe', 'freecadcmd.exe'}:
                return True
            found = kernel.Process32NextW(handle, ctypes.byref(entry))
        if ctypes.get_last_error() != 18:  # ERROR_NO_MORE_FILES
            raise SetupError('Windows process enumeration failed. Nothing installed.')
        return False
    finally:
        kernel.CloseHandle(handle)


def check_helper(addon):
    # Verification uses a disposable private cache: no pip, network or account settings.
    with tempfile.TemporaryDirectory(prefix='cadwiz-offline-check-') as temp:
        env = dict(os.environ, CADWIZ_SETUP_DIR=temp, PYTHONUTF8='1')
        result = subprocess.run([sys.executable, str(addon / 'src/integrations/cadwiz_plugin/offline_launcher.py'), '--check'],
                                env=env, capture_output=True, text=True, encoding='utf8', errors='replace', timeout=180,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode:
            raise SetupError('The bundled assistant helper could not be verified. No installation was replaced.\n'
                             + (result.stderr or result.stdout)[-1600:])


def shortcut_stage(specs, stage, helper):
    if not specs:
        return []
    plan = []
    for index, spec in enumerate(specs):
        item = dict(spec, stage=str(stage / (str(index) + '.lnk')))
        plan.append(item)
    path = stage / 'shortcuts.json'
    write_json(path, plan)
    result = subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                             str(helper), '-Plan', str(path)], capture_output=True, text=True, timeout=60,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode or any(not Path(item['stage']).is_file() for item in plan):
        raise SetupError('Windows could not prepare CADWiz shortcuts. No installation was replaced.')
    return [(Path(item['stage']), Path(item['path'])) for item in plan]


def source_hashes(addon):
    values = {}
    for path in addon.rglob('*'):
        if linked(path):
            raise SetupError('The package contains a linked file. Extract a fresh release ZIP.')
        if path.is_file() and '__pycache__' not in path.parts and not path.name.endswith(('.pyc', '.pyo')):
            values[str(path.relative_to(addon))] = sha(path)
    return values


def link_identity(path, identity):
    path = Path(path)
    if (path.name.casefold() not in {'cadwiz.lnk', 'uninstall cadwiz.lnk'} or linked(path)
            or not path.is_file() or path.stat().st_size > 1024 * 1024):
        return False
    content = path.read_bytes().lower()
    return identity.lower().encode('utf-16-le') in content or identity.lower().encode('utf8') in content


def install(source, info, mod, data, specs=(), *, prerequisite=check_helper, make_shortcuts=shortcut_stage,
            running=running_freecad, replace=os.replace, commit=None):
    source = absolute(source); data = absolute(data); mod = destination(info, mod)
    if running():
        raise SetupError('FreeCAD is open. Save your work and close FreeCAD before installing. Nothing installed.')
    if not (source / 'InitGui.py').is_file() or not (source / 'src/integrations/cadwiz_plugin/addon.py').is_file():
        raise SetupError('The CADWiz package is incomplete. Extract the whole ZIP, then double-click install_windows.bat.')
    target = mod / 'CADWiz'
    if source == target or target in source.parents or source in target.parents or mod == data or mod in data.parents:
        raise SetupError('Package, data and destination folders must be separate. Nothing installed.')
    if target.exists() and not owned_addon(target):
        raise SetupError('A different or unrecognized CADWiz folder exists. It was preserved. Use Addon Manager or get help.')
    if mod.exists():
        for other in mod.iterdir():
            if other != target and owned_addon(other):
                raise SetupError('Another CADWiz installation exists under ' + other.name + '. It was preserved; resolve the duplicate before installing.')
    record_path = data / 'install.json'
    try:
        old = json.loads(record_path.read_text(encoding='utf-8-sig')) if record_path.is_file() else {}
    except (ValueError, OSError):
        raise SetupError('The previous setup record could not be read. It was preserved; get help before replacing it.') from None
    if not isinstance(old, dict) or (old.get('schema') == 2 and old.get('product') != PRODUCT):
        raise SetupError('An unrelated setup record exists in DataDir. It was preserved.')
    manager = [('windows_installer.py', Path(__file__)),
               ('uninstall_windows.ps1', Path(__file__).with_name('uninstall_windows.ps1'))]
    wizard = Path(__file__).with_name('windows_wizard.py')
    if wizard.is_file():
        manager.append(('windows_wizard.py', wizard))
    replacements = [(data / name, old.get('managed_files', {}).get(str(data / name))) for name, src in manager]
    replacements += [(absolute(spec['path']), old.get('shortcut_hashes', {}).get(str(absolute(spec['path'])))) for spec in specs]
    legacy = bool(old and old.get('schema') is None and old.get('addon')
                  and absolute(old['addon']) == target and owned_addon(target))
    if legacy:
        for index, (path, expected) in enumerate(replacements):
            if expected is None and path.is_file() and not linked(path):
                if path == data / 'uninstall_windows.ps1' and sha(path) == LEGACY_UNINSTALL_SHA:
                    replacements[index] = (path, sha(path))
                elif str(path) in old.get('shortcuts', []):
                    identity = str(target / 'src/integrations/cadwiz_plugin/launch.py') if path.name == 'CADWiz.lnk' else str(data / 'uninstall_windows.ps1')
                    if link_identity(path, identity):
                        replacements[index] = (path, sha(path))
    for path, expected in replacements:
        if path.exists() and (linked(path) or expected is None or not path.is_file() or sha(path) != expected):
            raise SetupError('An existing or modified setup file was preserved: ' + str(path))
    original = source_hashes(source)
    prerequisite(source)
    # Stage outside Mod, on the destination volume; backups are never loadable add-ons.
    profile = mod.parent
    profile.mkdir(parents=True, exist_ok=True)
    data.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.cadwiz-stage-', dir=profile))
    installation_id = uuid.uuid4().hex
    addon_stage = stage / 'CADWiz'
    backup_root = profile / '.cadwiz-backups'
    if linked(backup_root):
        raise SetupError('The CADWiz backup folder is linked. Nothing installed.')
    backup_root.mkdir(exist_ok=True)
    transaction = backup_root / installation_id
    transaction.mkdir()
    changed_files = []; earlier = None; installed = False; undo_commit = None
    try:
        shutil.copytree(source, addon_stage, ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.pyo'))
        if source_hashes(addon_stage) != original:
            raise SetupError('Package copy verification failed. The previous installation was preserved.')
        write_json(addon_stage / MARKER, {'schema': 1, 'product': PRODUCT, 'installation_id': installation_id})
        owned_specs = [dict(spec, description=spec.get('description', PRODUCT) + ' [CADWiz ' + installation_id + ']') for spec in specs]
        prepared = make_shortcuts(owned_specs, stage, Path(__file__).with_name('windows_shortcuts.ps1'))
        prepared += [(src, data / name) for name, src in manager]
        if running():
            raise SetupError('FreeCAD opened during setup. Close it and retry; the prior installation was preserved.')
        mod.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if not owned_addon(target):
                raise SetupError('The destination changed during setup. Nothing replaced.')
            earlier = transaction / 'previous-addon'
            target.rename(earlier)
        addon_stage.rename(target); installed = True
        for index, (src, dest) in enumerate(prepared):
            dest = absolute(dest); dest.parent.mkdir(parents=True, exist_ok=True)
            expected = dict(replacements).get(dest)
            if dest.exists() and (expected is None or linked(dest) or sha(dest) != expected):
                raise SetupError('A setup file changed during installation; it was preserved: ' + str(dest))
            backup = transaction / ('file-' + str(index)) if dest.exists() else None
            if backup:
                shutil.copy2(dest, backup)
            fd, name = tempfile.mkstemp(prefix='.cadwiz-', dir=dest.parent); os.close(fd)
            temp = Path(name)
            try:
                shutil.copy2(src, temp)
                digest = sha(temp)
                replace(temp, dest)
                changed_files.append((dest, backup, digest))
            finally:
                temp.unlink(missing_ok=True)
        receipt = {'schema': 2, 'product': PRODUCT, 'installation_id': installation_id,
                   'addon': str(target), 'mod_dir': str(mod), 'python': sys.executable,
                   'freecad_version': info['version'], 'source_hashes': original,
                   'backup': str(earlier) if earlier else None,
                   'managed_files': {str(data / name): sha(data / name) for name, src in manager},
                   'shortcuts': [str(absolute(spec['path'])) for spec in specs],
                   'shortcut_hashes': {str(absolute(spec['path'])): sha(absolute(spec['path'])) for spec in specs}}
        if record_path.exists():
            shutil.copy2(record_path, transaction / 'previous-install.json')
        if commit is not None:
            undo_commit = commit(receipt)
        write_json(record_path, receipt)
        return receipt
    except Exception as error:
        commit_error = None
        if undo_commit is not None:
            try: undo_commit()
            except Exception as failure: commit_error = failure
        for dest, backup, digest in reversed(changed_files):
            if dest.is_file() and not linked(dest) and sha(dest) == digest:
                if backup:
                    shutil.copy2(backup, dest)
                else:
                    dest.unlink()
        if installed and owned_addon(target, installation_id):
            target.rename(transaction / 'failed-new-addon')
        if earlier and earlier.exists() and not target.exists():
            earlier.rename(target)
        if commit_error is not None:
            raise SetupError('Installation files were rolled back, but the Windows Apps entry needs support. '
                             'Recovery copies were kept.') from error
        raise
    finally:
        # Delete only this newly created, verified staging directory outside Mod.
        if stage.parent == profile and stage.name.startswith('.cadwiz-stage-') and not linked(stage):
            shutil.rmtree(stage)


def uninstall(data, *, running=running_freecad):
    data = absolute(data); path = data / 'install.json'
    if not path.is_file():
        raise SetupError('No CADWiz installation record found. Nothing removed.')
    record = json.loads(path.read_text(encoding='utf-8-sig'))
    if record.get('schema') != 2 or record.get('product') != PRODUCT:
        raise SetupError('This older installation record cannot prove ownership. Nothing removed; use FreeCAD Addon Manager.')
    if record.get('state') == 'uninstalled':
        raise SetupError('No CADWiz add-on is installed by this record. Nothing removed.')
    mod = absolute(record['mod_dir']); addon = absolute(record['addon'])
    if mod.name.casefold() != 'mod' or addon != mod / 'CADWiz':
        raise SetupError('Unsafe installation record. Nothing removed.')
    if running():
        raise SetupError('FreeCAD is open. Save and close it first. Nothing removed.')
    if addon.exists() and not owned_addon(addon, record['installation_id']):
        raise SetupError('The add-on ownership marker does not match. Nothing removed.')
    for link in record.get('shortcuts', []):
        link = Path(link)
        if link.name.casefold() not in {'cadwiz.lnk', 'uninstall cadwiz.lnk'} or not link.is_absolute():
            raise SetupError('Unsafe shortcut record. Nothing removed.')
    kept = []
    if addon.exists():
        parent = mod.parent / '.cadwiz-backups'
        if linked(parent):
            raise SetupError('The backup folder is linked. Nothing removed.')
        parent.mkdir(exist_ok=True)
        backup = parent / ('uninstalled-' + uuid.uuid4().hex)
        addon.rename(backup); kept.append(str(backup))
    for name in record.get('shortcuts', []):
        link = Path(name)
        if link_identity(link, record['installation_id']) and sha(link) == record.get('shortcut_hashes', {}).get(name):
            link.unlink()
        elif link.exists():
            kept.append(str(link))
    shutil.copy2(path, data / ('uninstalled-' + uuid.uuid4().hex + '.json'))
    # Keep ownership hashes so a later install can safely reuse our manager files.
    record['state'] = 'uninstalled'
    write_json(path, record)
    return {'removed_from_freecad': True, 'preserved': kept,
            'message': 'CADWiz removed from FreeCAD. Models, preferences, assistant settings and saved add-on copies were kept.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['discover', 'install', 'uninstall'])
    parser.add_argument('--output-file', required=True)
    parser.add_argument('--source'); parser.add_argument('--mod-dir'); parser.add_argument('--data-dir')
    parser.add_argument('--shortcut-plan')
    args = parser.parse_args()
    try:
        if args.action == 'discover':
            result = discover()
        elif args.action == 'install':
            specs = json.loads(Path(args.shortcut_plan).read_text(encoding='utf-8-sig')) if args.shortcut_plan else []
            result = install(Path(args.source), discover(), args.mod_dir, Path(args.data_dir), specs)
        else:
            result = uninstall(Path(args.data_dir))
        write_json(args.output_file, dict(ok=True, result=result)); return 0
    except Exception as error:
        write_json(args.output_file, {'ok': False, 'message': str(error) or type(error).__name__})
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
