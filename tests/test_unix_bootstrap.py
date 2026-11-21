# SPDX-License-Identifier: LGPL-2.1-or-later
"""Bootstrap environment tests; real FreeCAD/Mac acceptance is a separate gate."""
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(sys.platform == 'win32', reason='POSIX executable fixture; native Mac/Linux CI required')
@pytest.mark.parametrize('explicit_python', [True, False])
def test_mac_bundle_discovers_module_directory_without_manual_python_edits(tmp_path, explicit_python):
    app = tmp_path/'Custom Apps/FreeCAD QA.app'
    python = app/'Contents/Resources/bin/python'
    python.parent.mkdir(parents=True)
    lib = app/'Contents/unusual-library-location'
    lib.mkdir()
    (lib/'FreeCAD.so').touch()
    (lib/'FreeCADGui.so').touch()
    output = tmp_path/'selected.txt'
    python.write_text('#!/bin/bash\nset -eu\n'
                      'test "${PYTHONPATH%%:*}" = "$EXPECTED_LIB"\n'
                      'if [ "$1" = -c ]; then exit 0; fi\n'
                      'printf "%s\\n" "$@" > "$BOOTSTRAP_OUT"\n')
    python.chmod(0o755)
    bins = tmp_path/'bin'
    bins.mkdir()
    uname = bins/'uname'
    uname.write_text('#!/bin/bash\necho Darwin\n')
    uname.chmod(0o755)
    env = dict(os.environ, EXPECTED_LIB=str(lib), BOOTSTRAP_OUT=str(output),
               PATH=str(bins)+os.pathsep+os.environ['PATH'])
    env.pop('FREECAD_PY', None)
    env.pop('MOD_DIR', None)
    if explicit_python:
        env['FREECAD_PY'] = str(python)
    else:
        env['FREECAD_APP'] = str(app)
    result = subprocess.run(['bash', str(ROOT/'scripts/install.sh')], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout+result.stderr
    assert 'installation.py' in output.read_text()
    assert '--source' in output.read_text()
