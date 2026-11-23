from types import SimpleNamespace
from pathlib import Path
import pytest
from integrations.cadwiz_plugin import connect_claude as connect, launch


@pytest.mark.parametrize('platform',['darwin','linux'])
def test_posix_connect_never_runs_windows_commands(monkeypatch,platform):
    monkeypatch.setattr(connect.sys,'platform',platform)
    calls=[]
    def run(args,**kwargs):calls.append(args);return SimpleNamespace(returncode=0,stdout='')
    monkeypatch.setattr(connect.subprocess,'run',run)
    monkeypatch.setattr(connect.shutil,'which',lambda _:None)
    monkeypatch.setattr(Path,'is_dir',lambda _:False)
    assert not connect.ask_windows('chatgpt')['appid']
    assert calls==[['ps','-A','-o','comm=']]


@pytest.mark.parametrize('platform,expected',[('darwin',['open','-a','/Applications/Codex.app']),('linux',['/bin/codex-desktop'])])
def test_native_assistant_launch(monkeypatch,platform,expected):
    monkeypatch.setattr(connect.sys,'platform',platform);calls=[]
    monkeypatch.setattr(connect.subprocess,'Popen',lambda args,**kwargs:calls.append(args))
    connect.open_app(expected[-1]);assert calls==[expected]


@pytest.mark.parametrize('platform',['darwin','linux','win32'])
def test_failed_process_query_never_allows_duplicate_launch(monkeypatch,platform):
    monkeypatch.setattr(launch.sys,'platform',platform)
    monkeypatch.setattr(launch.subprocess,'run',lambda *a,**k:SimpleNamespace(returncode=1,stdout=''))
    with pytest.raises(OSError):launch.freecad_running()


def test_mac_freecad_uses_own_bundle(monkeypatch):
    monkeypatch.setattr(launch.sys,'platform','darwin')
    monkeypatch.setattr(launch.sys,'executable','/Applications/FreeCAD1.1.4.app/Contents/Resources/bin/python')
    assert str(launch.freecad_exe()).replace('\\','/').endswith('/FreeCAD1.1.4.app/Contents/MacOS/FreeCAD')
