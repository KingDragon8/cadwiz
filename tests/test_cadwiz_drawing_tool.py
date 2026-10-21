# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""ORDER-2026-10-19-06: the Drawing button and Claude's `drawing` tool, without FreeCAD.

The real sheet is made in FreeCAD's windowless program (scripts/assembly_view_witness.py
drives it in real FreeCAD); here: the job never makes the window wait, says plainly
when it fails or runs too long, and the tool refuses bad requests in plain words.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from integrations.cadwiz_plugin import drawings


class _Process:
    def __init__(self) -> None:
        self.done = False
        self.killed = False

    def poll(self):
        return 0 if self.done or self.killed else None

    def kill(self):
        self.killed = True


def _job(tmp_path: Path) -> tuple[drawings.DrawingJob, _Process]:
    process = _Process()
    job = drawings.DrawingJob(str(tmp_path / "model.FCStd"), str(tmp_path / "sheet.svg"), title="Trash can A", version=2,
                              dimensions=[{"view": "front", "start": [0, 0, 0], "end": [0, 0, 90]}], launch=lambda _r: process)
    return job, process


def test_the_job_never_waits_and_hands_back_the_finished_sheet(tmp_path) -> None:
    job, process = _job(tmp_path)
    request = json.loads(job.request_path.read_text(encoding="utf-8"))
    assert request["title"] == "Trash can A" and request["version"] == 2 and request["dimensions"][0]["end"] == [0, 0, 90]
    assert job.poll() is None                                       # still working: nothing, at once
    (job.folder / "result.json").write_text(json.dumps({"ok": True, "svg": str(tmp_path / "sheet.svg"), "scale": 1 / 3}), encoding="utf-8")
    process.done = True
    assert job.poll()["ok"] is True


def test_a_job_that_ends_without_a_result_says_so_plainly(tmp_path) -> None:
    job, process = _job(tmp_path)
    process.done = True
    result = job.poll()
    assert result["ok"] is False and result["say"] == "The drawing could not be made from this model."


def test_a_job_past_its_time_limit_is_stopped_and_says_so(tmp_path) -> None:
    job, process = _job(tmp_path)
    job.started -= drawings.TIME_LIMIT_S + 1
    result = job.poll()
    assert process.killed and result["ok"] is False and "was stopped" in result["say"]


@pytest.fixture
def session(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from integrations.cadwiz_plugin.session import PluginSession

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    app = SimpleNamespace(listDocuments=lambda: {}, ActiveDocument=None, setActiveDocument=lambda n: None)
    return PluginSession(app=app, project_root=tmp_path / "projects", log_path=tmp_path / "calls.jsonl")


def test_the_drawing_tool_refuses_bad_requests_in_plain_words(session) -> None:
    bad_section = session.call("drawing", {"section": "sideways"})
    assert bad_section["ok"] is False and "on, off, or auto" in bad_section["say_to_founder"]
    bad_dim = session.call("drawing", {"dimensions": [{"view": "front", "start": [0, 0]}]})
    assert bad_dim["ok"] is False and "[x, y, z]" in bad_dim["say_to_founder"]
    nothing_open = session.call("drawing", {})
    assert nothing_open["ok"] is False and "Nothing is open" in nothing_open["say_to_founder"]
