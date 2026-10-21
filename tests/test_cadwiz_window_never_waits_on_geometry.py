# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""ORDER-2026-10-19-03: a solid tennis ball froze the founder's FreeCAD for good.

Found 2026-10-19. Claude built a 66 mm ball cut by a swept seam groove. The
windowless worker left the cut's sphere and seam tube visible, the reload showed
all three, and the Problems watch -- on the window thread -- measured the gap
between each pair: 27 s for one pair (measured on a copy of his file), then an
open-ended intersection, repeated every 30 s. The window never answered again.

1. Inside FreeCAD's window the pairwise check never runs on the window thread:
   it goes to a windowless job, and its answer arrives later.
2. What went into another shape (a cut's inputs, a pad's sketch) stays hidden
   when a build is shown.

Stand-ins for FreeCAD shapes and the job process; the files are real FCStd-shaped zips.
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from integrations.cadwiz_plugin import problems_watch
from integrations.cadwiz_plugin.session import visible_in_file


# ---- 1. the pairwise check leaves the window thread ------------------------------------------

class _SlowSolid:
    """Calling the OCC work on it is the bug: in the window it would never return."""

    def __init__(self, x0: float, x1: float):
        self.BoundBox = SimpleNamespace(XMin=x0, XMax=x1, YMin=0, YMax=10, ZMin=0, ZMax=10)
        self.Volume = (x1 - x0) * 100.0

    def distToShape(self, _other):  # noqa: N802
        raise AssertionError("distToShape ran on the window thread")

    def common(self, _other):
        raise AssertionError("common ran on the window thread")

    def exportBrep(self, path):  # noqa: N802
        Path(path).write_text("brep", encoding="utf-8")


def _obj(name: str, solid: _SlowSolid):
    return SimpleNamespace(Name=name, Label=name, TypeId="Part::Feature", State=[], ViewObject=SimpleNamespace(Visibility=True),
                           Shape=SimpleNamespace(isNull=lambda: False, Solids=[solid]), getParentGeoFeatureGroup=lambda: None)


class _Job:
    def __init__(self, manifest: Path):
        self.manifest = manifest
        self.done = False
        self.killed = False

    def poll(self):
        return 0 if self.done or self.killed else None

    def kill(self):
        self.killed = True

    def finish(self, rows: list[dict]):
        self.manifest.with_name("answer.json").write_text(json.dumps(rows), encoding="utf-8")
        self.done = True


@pytest.fixture
def background(monkeypatch):
    jobs: list[_Job] = []

    def launch(manifest: Path) -> _Job:
        jobs.append(_Job(manifest))
        return jobs[-1]

    check = problems_watch.BackgroundGeometry(launch=launch)
    monkeypatch.setattr(problems_watch, "BACKGROUND", check)
    monkeypatch.setattr(problems_watch, "_in_freecad_window", lambda: True)
    return check, jobs


def _ball_doc():
    # The ball as it arrived: sphere, seam tube and the cut, all three visible and overlapping.
    return SimpleNamespace(Name="Tennis_Ball_2", UndoCount=0, RedoCount=0,
                           Objects=[_obj("Ball", _SlowSolid(0, 66)), _obj("SeamGroove", _SlowSolid(-1, 67)), _obj("TennisBall", _SlowSolid(0, 66))])


def test_in_the_window_the_parts_check_goes_to_a_windowless_job_and_never_waits(background) -> None:
    check, jobs = background
    doc = _ball_doc()
    assert problems_watch.find_problems(doc, True) == []          # nothing yet, and no OCC call here
    assert len(jobs) == 1
    manifest = json.loads(jobs[0].manifest.read_text(encoding="utf-8"))
    assert [row["name"] for row in manifest] == ["Ball", "SeamGroove", "TennisBall"]
    assert all(Path(row["brep"]).is_file() for row in manifest)
    problems_watch.find_problems(doc, True)
    assert len(jobs) == 1                                           # the same parts: no second job


def test_the_answer_arrives_and_the_panel_is_told_to_look_again(background) -> None:
    check, jobs = background
    doc = _ball_doc()
    problems_watch.find_problems(doc, True)
    before = problems_watch.signature(doc, True)
    jobs[0].finish([{"kind": "overlap", "what": "the Ball overlaps the SeamGroove", "objects": ["Ball", "SeamGroove"],
                     "elements": [], "detail_for_claude": "common volume 1.000 mm3"}])
    assert problems_watch.signature(doc, True) != before           # ProblemsCard.watch looks again at once
    found = problems_watch.find_problems(doc, True)
    assert [p.kind for p in found] == ["overlap"] and found[0].objects == ["Ball", "SeamGroove"]
    assert not jobs[0].manifest.parent.exists()                     # its scratch folder is gone


def test_a_job_past_its_time_limit_is_stopped_and_not_started_again(background, monkeypatch) -> None:
    check, jobs = background
    doc = _ball_doc()
    problems_watch.find_problems(doc, True)
    check.started -= problems_watch.GEOMETRY_TIME_LIMIT_S + 1
    assert problems_watch.find_problems(doc, True) == []
    assert jobs[0].killed and check.timed_out
    problems_watch.find_problems(doc, True)
    assert len(jobs) == 1                                           # never a restart loop on the same shapes


def test_a_changed_model_stops_the_old_job_and_starts_a_new_one(background) -> None:
    check, jobs = background
    problems_watch.find_problems(_ball_doc(), True)
    moved = SimpleNamespace(Name="Tennis_Ball_2", Objects=[_obj("Ball", _SlowSolid(0, 60)), _obj("TennisBall", _SlowSolid(100, 166))])
    problems_watch.find_problems(moved, True)
    assert jobs[0].killed and len(jobs) == 2


def test_a_job_that_cannot_start_never_holds_the_window(monkeypatch) -> None:
    def launch(_manifest):
        raise OSError("no freecadcmd")

    check = problems_watch.BackgroundGeometry(launch=launch)
    monkeypatch.setattr(problems_watch, "BACKGROUND", check)
    monkeypatch.setattr(problems_watch, "_in_freecad_window", lambda: True)
    assert problems_watch.find_problems(_ball_doc(), True) == []
    assert check.count == 1


# ---- 2. what went into another shape stays hidden --------------------------------------------

def _fcstd(path: Path, objects: list[tuple[str, str, bool, str]]) -> Path:
    """objects: (name, type, visible, extra property XML)."""
    types = "".join(f'<Object type="{t}" name="{n}"/>' for n, t, _v, _x in objects)
    data = "".join(f'<Object name="{n}"><Properties>'
                   f'<Property name="Visibility" type="App::PropertyBool"><Bool value="{"true" if v else "false"}"/></Property>{x}'
                   f"</Properties></Object>" for n, _t, v, x in objects)
    document = f'<?xml version="1.0" encoding="utf-8"?><Document><Objects>{types}</Objects><ObjectData>{data}</ObjectData></Document>'
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("Document.xml", document)
    return path


def _link(prop: str, target: str) -> str:
    return f'<Property name="{prop}" type="App::PropertyLink"><Link value="{target}"/></Property>'


def test_the_tennis_ball_shows_only_the_finished_ball(tmp_path) -> None:
    path = _fcstd(tmp_path / "ball.FCStd", [
        ("Params", "Spreadsheet::Sheet", True, ""),
        ("Ball", "Part::Sphere", True, ""),
        ("SeamGroove", "Part::Feature", True, ""),
        ("TennisBall", "Part::Cut", True, _link("Base", "Ball") + _link("Tool", "SeamGroove")),
    ])
    assert "Ball" not in visible_in_file(path) and "SeamGroove" not in visible_in_file(path)
    assert "TennisBall" in visible_in_file(path)


def test_a_pads_sketch_hides_but_a_sketch_attached_to_the_pad_does_not_hide_the_pad(tmp_path) -> None:
    attached = ('<Property name="AttachmentSupport" type="App::PropertyLinkSubList"><LinkSubList count="1">'
                '<Link obj="Pad" sub="Face6"/></LinkSubList></Property>')
    path = _fcstd(tmp_path / "bracket.FCStd", [
        ("Body", "PartDesign::Body", True, '<Property name="Tip" type="App::PropertyLink"><Link value="Pad"/></Property>'),
        ("Sketch", "Sketcher::SketchObject", True, ""),
        ("Pad", "PartDesign::Pad", True, '<Property name="Profile" type="App::PropertyLinkSub"><LinkSub value="Sketch" count="0"/></Property>'),
        ("Sketch001", "Sketcher::SketchObject", True, attached),
    ])
    shown = visible_in_file(path)
    assert "Sketch" not in shown
    assert {"Pad", "Sketch001", "Body"} <= shown
