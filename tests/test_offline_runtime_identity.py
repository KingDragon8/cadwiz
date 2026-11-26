from types import SimpleNamespace
import pytest
from integrations.cadwiz_plugin import offline_launcher as launcher


def windows(monkeypatch, compiled):
    monkeypatch.setattr(launcher, "sys", SimpleNamespace(platform="win32", version_info=SimpleNamespace(major=3, minor=11)))
    monkeypatch.setattr(launcher.sysconfig, "get_platform", lambda: compiled)


def test_windows_helper_selection_uses_interpreter_not_missing_shell_metadata(monkeypatch):
    windows(monkeypatch, "win-amd64")
    monkeypatch.setattr(launcher.platform, "machine", lambda: "")
    assert launcher.runtime_tag() == "win32-x86_64-cp311"


def test_32_bit_interpreter_cannot_load_64_bit_wheels_on_64_bit_host(monkeypatch):
    windows(monkeypatch, "win32")
    monkeypatch.setattr(launcher.platform, "machine", lambda: "AMD64")
    assert launcher.runtime_tag() == "win32-x86-cp311"


def test_unknown_windows_build_fails_closed(monkeypatch):
    windows(monkeypatch, "unknown")
    with pytest.raises(RuntimeError, match="CW-SETUP-ARCH"):
        launcher.runtime_tag()


@pytest.mark.parametrize("platform,machine,tag", [
    ("darwin", "arm64", "darwin-arm64-cp311"),
    ("darwin", "x86_64", "darwin-x86_64-cp311"),
    ("linux", "x86_64", "linux-x86_64-cp311"),
    ("linux", "aarch64", "linux-arm64-cp311"),
])
def test_posix_runtime_identity(monkeypatch, platform, machine, tag):
    monkeypatch.setattr(launcher, "sys", SimpleNamespace(platform=platform, version_info=SimpleNamespace(major=3, minor=11)))
    monkeypatch.setattr(launcher.platform, "machine", lambda: machine)
    assert launcher.runtime_tag() == tag


@pytest.mark.parametrize("platform", ["darwin", "linux"])
def test_posix_missing_architecture_fails_clearly(monkeypatch, platform):
    monkeypatch.setattr(launcher, "sys", SimpleNamespace(platform=platform, version_info=SimpleNamespace(major=3, minor=11)))
    monkeypatch.setattr(launcher.platform, "machine", lambda: "")
    with pytest.raises(RuntimeError, match="CW-SETUP-ARCH"):
        launcher.runtime_tag()
