# SPDX-License-Identifier: LGPL-2.1-or-later
"""Verify real Windows shortcut branding, including paths with spaces."""
import json
import os
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(os.name != 'nt', reason='Real Windows Shell shortcut verification')
def test_shortcut_uses_installed_wiz_icon_and_stable_launcher(tmp_path):
    icon = ROOT/'CADWiz/Resources/icons/cadwiz.ico'
    target = Path(os.environ['WINDIR'])/'System32/notepad.exe'
    link = tmp_path/"CADWiz O'Neil [test].lnk"
    plan = tmp_path/'plan.json'
    plan.write_text(json.dumps([{'stage':str(link),'target':str(target),
        'arguments':'--open','working_directory':str(tmp_path),'description':'CADWiz',
        'icon':str(icon)+',0'}]),encoding='utf-8')
    made = subprocess.run(['powershell.exe','-NoProfile','-File',str(ROOT/'scripts/windows_shortcuts.ps1'),
                           '-Plan',str(plan)],capture_output=True,text=True)
    assert made.returncode == 0, made.stderr
    script = tmp_path/'inspect.ps1'
    script.write_text('param([string]$Link)\n$s=New-Object -ComObject WScript.Shell\n'
                      '$l=$s.CreateShortcut($Link)\n'
                      '@{target=$l.TargetPath;arguments=$l.Arguments;icon=$l.IconLocation} | ConvertTo-Json -Compress\n')
    read = subprocess.run(['powershell.exe','-NoProfile','-File',str(script),'-Link',str(link)],
                          capture_output=True,text=True,check=True)
    result=json.loads(read.stdout)
    assert Path(result['target']).samefile(target)
    assert result['arguments']=='--open'
    assert Path(result['icon'].rsplit(',',1)[0]).samefile(icon)
