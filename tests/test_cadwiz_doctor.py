# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
from integrations.cadwiz_plugin.doctor import inspect


def test_broken_install_is_diagnosed_without_loading_it(tmp_path):
    addon = tmp_path / "Mod/CADWiz"
    addon.mkdir(parents=True)
    (addon / "InitGui.py").write_text("raise RuntimeError('PRIVATE_TOKEN')")
    result = inspect(tmp_path)
    assert result["installations"][0]["problems"]
    assert not result["startup_verified"]
    assert "PRIVATE_TOKEN" not in str(result)
    assert str(tmp_path) not in str(result)


def test_duplicate_installs_and_backups_preserved(tmp_path):
    for name in ("CADWiz", "AI-FreeCAD", "CADWiz-backup"):
        addon = tmp_path / "Mod" / name
        addon.mkdir(parents=True)
        (addon / "InitGui.py").write_text("broken python !")
    # AIFreeCAD is a historical install ID too.
    result = inspect(tmp_path)
    assert len(result["installations"]) == 2
    assert any("Multiple" in issue for issue in result["issues"])
    assert (tmp_path / "Mod/CADWiz-backup/InitGui.py").exists()
    assert all(not item.get("startup_verified") for item in result["installations"])


def test_unknown_active_directory_never_reports_verified_startup(monkeypatch, tmp_path):
    monkeypatch.setattr("integrations.cadwiz_plugin.doctor.candidate_mod_dirs", lambda: [tmp_path])
    result = inspect()
    assert result["directory_confidence"] == "undetermined"
    assert result["issues"]
