# SPDX-License-Identifier: LGPL-2.1-or-later
import json
import tomllib
from pathlib import Path
import pytest
from integrations.cadwiz_plugin import install_setup as setup


@pytest.fixture
def area(tmp_path, monkeypatch):
    monkeypatch.setenv("CADWIZ_SETUP_DIR", str(tmp_path / "private"))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))
    addon = tmp_path / "CADWiz with spaces"
    server = addon / "src/integrations/cadwiz_plugin/server.py"
    server.parent.mkdir(parents=True)
    server.write_text("")
    python = tmp_path / "python.exe"
    python.write_text("")
    return setup.record_runtime(addon, python, "1.1.3")


def test_connect_backup_and_undo_preserve_unrelated_later_changes(area):
    p = setup.config_path()
    p.parent.mkdir(parents=True)
    original = '# important comment\nmodel = "test"\n[mcp_servers.other]\ncommand = "keep"\n[mcp_servers.cadwiz]\ncommand = "old"\n[mcp_servers.cadwiz.env]\nOLD = "value"\n'
    p.write_text(original)
    setup.connect(area)
    assert tomllib.loads(p.read_text())["mcp_servers"]["other"]["command"] == "keep"
    receipt = json.loads((setup.data_dir() / "codex-undo.json").read_text())
    assert Path(receipt["backup"]).read_text() == original
    p.write_text(p.read_text() + '\n[mcp_servers.new]\ncommand="later"\n')
    setup.disconnect()
    parsed = tomllib.loads(p.read_text())
    assert parsed["mcp_servers"]["cadwiz"]["command"] == "old"
    assert parsed["mcp_servers"]["new"]["command"] == "later"
    assert "# important comment" in p.read_text()


def test_connect_twice_is_idempotent_and_runtime_update_preserves_original_undo(area):
    setup.connect(area)
    receipt = (setup.data_dir() / "codex-undo.json").read_bytes()
    setup.connect(area)
    assert (setup.data_dir() / "codex-undo.json").read_bytes() == receipt
    area["python"] += ".moved"
    setup.connect(area)
    setup.disconnect()
    assert "cadwiz" not in tomllib.loads(setup.config_path().read_text()).get("mcp_servers", {})


def test_invalid_toml_and_inline_entry_never_overwrite(area):
    p = setup.config_path();p.parent.mkdir(parents=True)
    for text in ['broken = [', 'mcp_servers = {cadwiz={command="old"}}\n']:
        p.write_text(text)
        with pytest.raises(ValueError): setup.connect(area)
        assert p.read_text() == text


def test_undo_refuses_external_changes_to_own_entry(area):
    setup.connect(area)
    p = setup.config_path();p.write_text(p.read_text().replace('tool_timeout_sec = 180', 'tool_timeout_sec = 181'))
    with pytest.raises(ValueError, match="CONFLICT"): setup.disconnect()
    assert "181" in p.read_text()


def test_owned_deleted_entry_repairs_but_unowned_missing_entry_does_not(area):
    assert setup.repair_owned(area, pause=lambda _: None)["code"] == "CW-SETUP-READY"
    assert not setup.config_path().exists()
    setup.connect(area)
    setup.config_path().write_text('model="keep"\n')
    assert setup.repair_owned(area, pause=lambda _: None)["code"] == "CW-SETUP-RESTART"
    assert tomllib.loads(setup.config_path().read_text())["model"] == "keep"


def test_quoted_table_and_missing_runtime(area):
    p = setup.config_path();p.parent.mkdir(parents=True)
    p.write_text('[mcp_servers."cadwiz"]\ncommand="old"\n[mcp_servers."cadwiz".env]\nA="b"\n')
    setup.connect(area)
    assert tomllib.loads(p.read_text())["mcp_servers"]["cadwiz"] == setup.server_values(area)
    Path(area["python"]).unlink()
    with pytest.raises(ValueError, match="Open FreeCAD"): setup.runtime()


def test_claude_migration_and_undo_preserve_unrelated_settings(area, tmp_path):
    p = tmp_path / "Store Claude/settings.json"
    p.parent.mkdir()
    legacy = {"command": "python", "args": ["C:/CADWiz/src/integrations/cadwiz_plugin/server.py"]}
    p.write_text(json.dumps({"mcpServers": {"cadwiz": legacy, "other": {"command": "keep"}}, "theme": "dark"}))
    plans = setup.migrate_legacy_claude([p])
    assert Path(plans[0]["backup"]).is_file()
    data = json.loads(p.read_text());assert "cadwiz" not in data["mcpServers"]
    data["theme"] = "light";p.write_text(json.dumps(data))
    setup.undo_claude()
    data = json.loads(p.read_text())
    assert data["theme"] == "light" and data["mcpServers"]["other"]["command"] == "keep"
    assert data["mcpServers"]["cadwiz"] == legacy


def test_duplicate_addon_kept_outside_mod_with_undo(area, tmp_path):
    mod = tmp_path / "Mod";old = mod / "old-copy";active = mod / "CADWiz/CADWiz"
    old.mkdir(parents=True);active.mkdir(parents=True)
    (old / "package.xml").write_text('<package><name>CADWiz</name></package>')
    (old / "model.FCStd").write_bytes(b"keep")
    moved = setup.relocate_duplicates(mod, active)
    assert (Path(moved[0]["backup"]) / "model.FCStd").read_bytes() == b"keep"
    assert active.is_dir() and not old.exists()
    setup.undo_duplicates()
    assert (old / "model.FCStd").read_bytes() == b"keep"
