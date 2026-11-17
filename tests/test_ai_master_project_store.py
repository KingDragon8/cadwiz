# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""The per-project store: active object line (addendum 1), founder files read-only
(hard safety envelope), download provenance (addendum 6)."""
from __future__ import annotations

import pytest

from ai_freecad_core.ai_master.design_source import DesignSource
from ai_freecad_core.ai_master.project_store import DownloadRecord, Project, safe_name
from ai_freecad_core.ai_master.units import Quantity


def test_working_on_line_and_versions_live_in_the_project(tmp_path) -> None:
    project = Project.open("Cone test", root=tmp_path)
    assert project.working_on_line() == "Working on: nothing yet"
    record = project.versions("Cone").add(DesignSource("Cone", {"height": Quantity(6, "in")}, script="pass"))
    project.set_active("Cone", record.version)
    assert project.working_on_line() == "Working on: Cone, version 1"
    assert project.objects() == ["Cone"]
    assert project.render_path("Cone", 1).name == "v1.png"
    facts_path = project.save_facts("Cone", 1, {"bbox_mm": [1, 2, 3]})
    assert facts_path.exists()


def test_the_founders_files_are_read_only(tmp_path) -> None:
    project = Project.open("Visor", root=tmp_path)
    founder_file = tmp_path / "CoolOff_AI1.FCStd"
    founder_file.write_bytes(b"theirs")
    project.register_founder_file(founder_file)
    assert project.is_founder_file(founder_file)
    with pytest.raises(PermissionError):
        project.guard_write(founder_file)
    project.guard_write(project.native_path("Visor", 1))   # new versions go beside: allowed
    assert founder_file.read_bytes() == b"theirs"


def test_downloads_record_source_url_and_licence(tmp_path) -> None:
    project = Project.open("Lure", root=tmp_path)
    project.record_download(DownloadRecord("lure.stl", "https://www.thingiverse.com/thing:123", "CC BY 4.0", title="Bass lure", author="maker"))
    line = project.downloads()[0].plain()
    assert "thingiverse.com/thing:123" in line and "CC BY 4.0" in line and "E0" in line


def test_names_are_made_safe_for_folders() -> None:
    assert safe_name("Cool/Off: AI1?") == "Cool_Off_ AI1"
    assert safe_name("") == "Untitled"


def test_new_projects_use_documents_but_existing_projects_stay_put(tmp_path, monkeypatch):
    from ai_freecad_core.ai_master import project_store

    monkeypatch.delenv("CADWIZ_PROJECTS_ROOT", raising=False)
    monkeypatch.setattr(project_store.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(project_store, "documents_directory", lambda: tmp_path / "Redirected Documents")
    assert project_store.default_projects_root() == tmp_path / "Redirected Documents/CADWiz"
    legacy = tmp_path / "CADWiz Projects"
    legacy.mkdir()
    assert project_store.default_projects_root() == legacy
    monkeypatch.setenv("CADWIZ_PROJECTS_ROOT", str(tmp_path / "Shared"))
    assert project_store.default_projects_root() == tmp_path / "Shared"
