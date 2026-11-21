# SPDX-License-Identifier: LGPL-2.1-or-later
"""Offline, transactional workbench installation. Never configures an assistant.

The selected FreeCAD supplies its actual data directory. Backups and staging
stay outside Mod; no installed or user files are deleted during replacement.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ESSENTIAL = ('InitGui.py', 'src/integrations/cadwiz_plugin/addon.py',
             'src/integrations/cadwiz_plugin/slim_panel.py',
             'src/integrations/cadwiz_plugin/installation.py')


def validate(source: Path) -> None:
    for name in ESSENTIAL:
        path = source / name
        if not path.is_file() or path.is_symlink():
            raise ValueError(f'Incomplete workbench: missing or linked {name}')
        ast.parse(path.read_text(encoding='utf-8-sig'), filename=name)
    for path in source.rglob('*'):
        if path.is_symlink():
            raise ValueError('Linked source files require manual review; nothing was installed.')


def candidates(mod: Path) -> list[Path]:
    if not mod.exists():
        return []
    result = []
    for folder in sorted(mod.iterdir()):
        name = folder.name.casefold()
        # Include interrupted clones and old backups bearing the installation ID.
        # Do not sweep arbitrary folders containing "cadwiz" (e.g. user models).
        if name in ('cadwiz', 'ai-freecad') or name.startswith(('cadwiz.backup', 'cadwiz-backup', 'cadwiz.old')):
            if folder.is_symlink() or not folder.is_dir():
                raise ValueError(f'Installation candidate requires manual review: {folder.name}')
            result.append(folder)
    return result


def hashes(root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file() and '__pycache__' not in p.parts}


def install(source: Path, user_data: Path) -> dict:
    source = source.resolve(strict=True)
    user_data = user_data.expanduser().absolute()
    if not user_data.is_absolute() or user_data == Path(user_data.anchor):
        raise ValueError('Use the actual FreeCAD application-data directory, not a filesystem root.')
    validate(source)
    user_data.mkdir(parents=True, exist_ok=True)
    mod = user_data / 'Mod'
    if mod.is_symlink():
        raise ValueError('A linked Mod directory requires manual review; no files changed.')
    mod.mkdir(exist_ok=True)
    lock = user_data / '.cadwiz-install.lock'
    # An exclusive lock also protects against two installers swapping folders.
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    transaction = None
    moved = []
    target = mod / 'CADWiz'
    activated = False
    try:
        previous = candidates(mod)
        backup_root = user_data / 'CADWiz-backups'
        if backup_root.is_symlink():
            raise ValueError('Linked backup directory requires manual review.')
        backup_root.mkdir(exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-')
        transaction = Path(tempfile.mkdtemp(prefix=stamp, dir=backup_root))
        stage = transaction / 'staged'
        shutil.copytree(source, stage, ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '.git'))
        validate(stage)
        expected = hashes(source)
        if hashes(stage) != expected:
            raise ValueError('Staged files do not match the source; active installation was not changed.')
        records = []
        for number, old in enumerate(previous):
            saved = transaction / f'previous-{number}'
            record = {'original': str(old), 'backup': str(saved), 'hashes': hashes(old)}
            records.append(record)
        manifest = {'schema_version': 1, 'target': str(target), 'previous': records, 'state': 'staged'}
        manifest_path = transaction / 'rollback.json'
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        for record in records:
            old, saved = Path(record['original']), Path(record['backup'])
            old.rename(saved)
            moved.append((old, saved))
        stage.rename(target)
        activated = True
        validate(target)
        if hashes(target) != expected:
            raise ValueError('Post-install file integrity check failed.')
        for record in records:
            if hashes(Path(record['backup'])) != record['hashes']:
                raise ValueError('Backup integrity check failed.')
        manifest['state'] = 'files_verified'
        manifest['installed_hashes'] = expected
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        return {'files_verified': True, 'startup_verified': False, 'target': str(target),
                'rollback_manifest': str(manifest_path), 'previous_installations': len(moved),
                'message': 'Files and backups verified. Restart FreeCAD and select CADWiz to verify workbench and panel. AI setup is separate.'}
    except BaseException:
        if activated:
            target.rename(transaction / 'failed-new-install')
        for old, saved in reversed(moved):
            saved.rename(old)
        raise
    finally:
        lock.unlink()


def rollback(manifest_path: Path) -> dict:
    manifest_path = manifest_path.resolve(strict=True)
    transaction = manifest_path.parent
    user_data = transaction.parent.parent
    if transaction.parent.name != 'CADWiz-backups':
        raise ValueError('Not a CADWiz rollback manifest.')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    target = user_data / 'Mod/CADWiz'
    if manifest.get('target') != str(target) or manifest.get('state') != 'files_verified':
        raise ValueError('Rollback state or target is invalid.')
    # Validate every path and hash before moving anything. Preserve changed files.
    if not target.is_dir() or target.is_symlink() or hashes(target) != manifest['installed_hashes']:
        raise ValueError('Installed files changed; automatic rollback refused. All files preserved.')
    for number, record in enumerate(manifest['previous']):
        old, saved = Path(record['original']), Path(record['backup'])
        if old.parent != target.parent or saved != transaction / f'previous-{number}' or saved.is_symlink():
            raise ValueError('Unsafe rollback paths.')
        name = old.name.casefold()
        if name not in ('cadwiz', 'ai-freecad') and not name.startswith(('cadwiz.backup', 'cadwiz-backup', 'cadwiz.old')):
            raise ValueError('Rollback may only restore CADWiz installation folders.')
        # macOS uses PosixPath even on case-insensitive APFS: unequal strings
        # can identify the same directory. WindowsPath equality hid this bug.
        occupied = old.exists() and not old.samefile(target)
        if occupied or hashes(saved) != record['hashes']:
            raise ValueError('A backup or destination changed; all files preserved.')
    lock = user_data / '.cadwiz-install.lock'
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    restored = []
    new = transaction / 'rolled-back-install'
    try:
        target.rename(new)
        try:
            for record in manifest['previous']:
                old, saved = Path(record['original']), Path(record['backup'])
                saved.rename(old)
                restored.append((old, saved))
        except BaseException:
            for old, saved in reversed(restored):
                old.rename(saved)
            new.rename(target)
            raise
        manifest['state'] = 'rolled_back'
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        return {'rolled_back': True, 'startup_verified': False, 'preserved_new_install': str(new)}
    finally:
        lock.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument('--user-data', type=Path)
    parser.add_argument('--rollback', type=Path)
    args = parser.parse_args()
    try:
        import FreeCAD
        version = tuple(int(v) for v in FreeCAD.Version()[:2])
        if version < (1, 1):
            raise ValueError('FreeCAD 1.1 or newer is required.')
        data = Path(FreeCAD.getUserAppDataDir())
        if args.user_data and args.user_data.resolve() != data.resolve():
            raise ValueError('Requested user directory differs from the selected FreeCAD runtime.')
        if sys.platform != 'win32':
            running = subprocess.run(['pgrep', '-ix', 'freecad'], capture_output=True)
            if running.returncode == 0:
                raise ValueError('Save your work and quit FreeCAD completely before installation or rollback.')
            if running.returncode != 1:
                raise ValueError('Could not check whether FreeCAD is running; no installation attempted.')
        result = rollback(args.rollback) if args.rollback else install(args.source, data)
        print(json.dumps(result, indent=2))
        return 0
    except Exception as error:
        print(f'CADWiz installation stopped: {type(error).__name__}: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
