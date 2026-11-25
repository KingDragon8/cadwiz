# SPDX-License-Identifier: LGPL-2.1-or-later
"""Compile the Windows wizard exclusively from a committed Git archive."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import tomllib
import zipfile


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--compiler', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--source-tree', help='Full immutable staged Git tree for an unpublished OASIS candidate')
    args = p.parse_args()
    root = Path(__file__).resolve().parents[2]
    assert os.name == 'nt' and args.compiler.is_file(), 'Windows and the verified Inno Setup compiler are required'
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root).decode().strip()
    source_ref = args.source_tree or commit
    if args.source_tree:
        import re
        assert re.fullmatch(r'[a-f0-9]{40}', source_ref)
        assert subprocess.check_output(['git','cat-file','-t',source_ref],cwd=root).strip()==b'tree'
    args.output.mkdir(parents=True, exist_ok=True)
    output = args.output.resolve()
    with tempfile.TemporaryDirectory(prefix='cadwiz-setup-build-') as temporary:
        stage = Path(temporary); archive = stage / 'source.zip'
        subprocess.run(['git', 'archive', '--format=zip', '--output=' + str(archive), source_ref], cwd=root, check=True)
        with zipfile.ZipFile(archive) as z:
            assert not any(n.lower().endswith(('.fcstd', '.fcstd1')) for n in z.namelist())
            z.extractall(stage / 'source')
        source = stage / 'source'
        version = tomllib.loads((source / 'pyproject.toml').read_text())['project']['version']
        exe = output / ('CADWiz-Setup-' + version + '.exe')
        if exe.exists(): raise SystemExit('Refusing to overwrite ' + str(exe))
        result = subprocess.run([str(args.compiler.resolve()), str(source / 'scripts/windows/CADWiz.iss'),
                                 '/DSourceRoot=' + str(source), '/DOutputPath=' + str(output),
                                 '/DAppVersion=' + version], capture_output=True, text=True, errors='replace')
        (output / 'Setup-build.log').write_text(result.stdout + result.stderr, encoding='utf8')
        if result.returncode: raise SystemExit(result.stdout[-3000:] + result.stderr[-3000:])
    assert exe.is_file()
    result = {'version': version, 'source_commit': commit if not args.source_tree else None, 'source_tree':source_ref, 'filename': exe.name,
              'bytes': exe.stat().st_size, 'sha256': hashlib.sha256(exe.read_bytes()).hexdigest(),
              'signing': 'No publisher signing certificate configured; do not claim a verified publisher.'}
    (output / 'Setup-build.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
