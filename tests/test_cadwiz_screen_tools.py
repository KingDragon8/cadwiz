# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""ORDER-2026-10-18-01: the connector tools of the shared screen, and the version
rules the time slider shows -- with stand-ins for FreeCAD (the real-FreeCAD run is
scripts/panel_redesign_witness.py).

  shown_to_claude   the frame he froze with Show Claude; reading it is recorded
                    (that is what makes his screen flash "Claude has it")
  mark_for_user  Claude's marks, anchored on the model, in Claude's colour
  get_selection     what he has selected now, in any workbench
  versions          broken versions are recorded and still restorable; a restore
                    adds a version and never deletes a newer one
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ai_freecad_core.ai_master.adopted import AdoptedStore
from ai_freecad_core.visual_communications.anchored import Camera, ModelAnchor
from ai_freecad_core.visual_communications.contracts import VisualMarkAuthor
from integrations.cadwiz_plugin import server as plugin_server
from integrations.cadwiz_plugin.screen import NOTHING_SHOWN
from integrations.cadwiz_plugin.session import PluginSession


class V:
    def __init__(self, x: float, y: float, z: float) -> None:
        self.x, self.y, self.z = x, y, z


class _Box:
    """A 40 x 25 x 12 mm box at the origin: faces, an edge and a vertex."""

    def __init__(self) -> None:
        self.BoundBox = SimpleNamespace(Center=V(20, 12.5, 6), XMin=0, YMin=0, ZMin=0, XMax=40, YMax=25, ZMax=12)

    def getElement(self, name: str):  # noqa: N802
        if name == "Face6":
            outline = [V(0, 0, 12), V(40, 0, 12), V(40, 25, 12), V(0, 25, 12)]
            return SimpleNamespace(CenterOfMass=V(20, 12.5, 12), BoundBox=SimpleNamespace(XMin=0, YMin=0, ZMin=12, XMax=40, YMax=25, ZMax=12),
                                   OuterWire=SimpleNamespace(discretize=lambda Number: outline))
        if name == "Edge1":
            return SimpleNamespace(ParameterRange=(0.0, 40.0), valueAt=lambda t: V(t, 0, 0))
        if name == "Vertex2":
            return SimpleNamespace(Point=V(40, 0, 0))
        raise ValueError(f"no element {name}")


class _Doc:
    def __init__(self, path: str) -> None:
        self.Name = self.Label = "Bracket"
        self.FileName = path
        box = SimpleNamespace(Name="Box", Label="Box", TypeId="Part::Box", Shape=_Box(), Visibility=True, State=[],
                              getParentGeoFeatureGroup=lambda: None)
        bad = SimpleNamespace(Name="Pocket", Label="Pocket", TypeId="PartDesign::Pocket", State=["Invalid"], Visibility=True)
        self.Objects = [box, bad]

    def getObject(self, name: str):  # noqa: N802
        return next((o for o in self.Objects if o.Name == name), None)

    def getObjectsByLabel(self, label: str):  # noqa: N802
        return [o for o in self.Objects if o.Label == label]

    def saveCopy(self, dest: str) -> None:  # noqa: N802
        Path(dest).write_bytes(b"model as it is now")


class _Executor:
    """The plug-in's per-document executor, with a REAL version store beside the file."""

    def __init__(self, project, name, file_name, **hooks):
        self.object_name = name
        self.adoption = {"main_object": "Box"}
        self.founder_file = Path(file_name)
        self.store = AdoptedStore(Path(file_name).parent / "records", file_name)
        self._snapshot = hooks.get("snapshot_open")

    def adopt(self):
        return self.adoption

    def _ensure_backup(self):
        if not self.store.backed_up_this_session:
            self.store.backup(self._snapshot)

    def versions(self, action, version, note):
        self._ensure_backup()
        chosen = self.store.get(int(version))
        record = self.store.add_restore(int(version), measurements=chosen.measurements)
        self.store.write_founder_file(chosen.file)
        return {"version": record.version, "diff": record.diff, "file": chosen.file}

    def current_state(self):
        current = self.store.current()
        return {"version": current.version if current else 0}


@pytest.fixture
def session(tmp_path, monkeypatch):
    monkeypatch.setenv("CADWIZ_SETTINGS_FILE", str(tmp_path / "settings.json"))
    (tmp_path / "settings.json").write_text(json.dumps({"cad_folders": [str(tmp_path)]}))
    model = tmp_path / "Bracket.FCStd"
    model.write_bytes(b"his model")
    doc = _Doc(str(model))
    app = SimpleNamespace(listDocuments=lambda: {"Bracket": doc}, ActiveDocument=doc, setActiveDocument=lambda n: None)
    picked = [SimpleNamespace(DocumentName="Bracket", ObjectName="Box", Object=SimpleNamespace(Label="Box", TypeId="Part::Box"),
                              SubElementNames=["Face6"], PickedPoints=[V(20.0, 12.5, 12.0)])]
    gui = SimpleNamespace(Selection=SimpleNamespace(getSelectionEx=lambda: picked), ActiveDocument=None)
    s = PluginSession(app=app, gui=gui, project_root=tmp_path / "projects", executor_factory=_Executor, log_path=tmp_path / "calls.jsonl")
    s.doc = doc
    return s


CAMERA = Camera("orthographic", (54.39, -9.39, 36.89), (0.4247, 0.1759, 0.3399, 0.8205), height=75.83, focal_distance=37.91)


def _freeze(session, tmp_path, marks=()) -> dict:
    for kind, anchors in marks:
        session.screen.book_for("Bracket").add(kind, anchors)
    session.screen.active_document = "Bracket"
    picture, clean = tmp_path / "marked.png", tmp_path / "clean.png"
    picture.write_bytes(b"png")
    clean.write_bytes(b"png")
    return session.screen.freeze(picture=str(picture), clean_picture=str(clean), camera=CAMERA, aspect=1.6,
                                 selection=[{"object": "Box", "elements": ["Face6"]}], view="iso", cut_away=False, document="Bracket",
                                 file=session.doc.FileName, version=3, latest_version=3, broken=[])


# ---- shown_to_claude ---------------------------------------------------------------------------

def test_nothing_shown_yet_says_how_to_look_instead(session) -> None:
    result = session.call("shown_to_claude", {})
    assert result == {"ok": True, "shown": False, "note_for_claude": NOTHING_SHOWN}


def test_the_frozen_frame_reaches_claude_with_pictures_marks_selection_view_and_version(session, tmp_path) -> None:
    _freeze(session, tmp_path, [("circle", [ModelAnchor((20, 12.5, 12), "Box", "Face6", True), ModelAnchor((25, 12.5, 12), "Box", "Face6", True)])])
    result = session.call("shown_to_claude", {})
    assert result["ok"] and result["shown"] and result["frame"] == 1
    assert result["images"] == [str(tmp_path / "marked.png"), str(tmp_path / "clean.png")]
    assert result["marks"][0]["kind"] == "circle" and result["marks"][0]["author"] == "founder"
    assert result["marks_in_words"] == ["Mark 1 (the founder's circle) on Box.Face6 at (20, 12.5, 12) mm, radius 0.2 in (5 mm)"]
    assert result["selection"] == [{"object": "Box", "elements": ["Face6"]}]
    assert (result["view"], result["version_line"], result["document"]) == ("iso", "version 3 of 3", "Bracket")
    assert result["read_by_claude_utc"]                         # the read is recorded: his panel flashes "Claude has it"
    assert session.screen.shown["read_count"] == 1
    session.call("shown_to_claude", {})
    assert session.screen.shown["read_count"] == 2


def test_the_frame_stays_as_frozen_while_he_keeps_working(session, tmp_path) -> None:
    _freeze(session, tmp_path, [("point", [ModelAnchor((1, 2, 3))])])
    session.screen.book_for("Bracket").add("point", [ModelAnchor((9, 9, 9))])     # a later mark, not shown yet
    result = session.call("shown_to_claude", {})
    assert result["founder_mark_count"] == 1 and len(result["marks"]) == 1


# ---- mark_for_user --------------------------------------------------------------------------

def test_claude_marks_on_a_face_an_edge_a_point_and_the_shown_picture(session, tmp_path) -> None:
    _freeze(session, tmp_path)
    result = session.call("mark_for_user", {"marks": [
        {"kind": "circle", "on": "Box.Face6", "radius_mm": 4, "text": "here"},
        {"kind": "arrow", "on": "Box.Edge1", "to": [40, 25, 12]},
        {"kind": "measure", "at": [0, 0, 0], "on": "Box", "to": "Box.Vertex2"},
        {"kind": "note", "picture_xy": [0.5, 0.5], "text": "thicker?"},
        {"kind": "highlight", "on": "Box.Face6"},
    ]})
    assert result["ok"] and result["your_marks_on_screen"] == 5
    marks = session.screen.book_for("Bracket").by(VisualMarkAuthor.ASSISTANT)
    assert [m.kind.value for m in marks] == ["circle", "arrow", "measurement", "note", "highlight"]
    assert marks[0].anchors[0] == ModelAnchor((20.0, 12.5, 12.0), "Box", "Face6", True)
    assert marks[0].length_mm == pytest.approx(4.0)
    assert marks[1].anchors[0].point == (20.0, 0.0, 0.0)                   # the middle of the edge
    assert marks[2].length_mm == pytest.approx(40.0)                      # origin to Vertex2
    assert marks[3].anchors[0].point == pytest.approx(CAMERA.point_at_focus(0.5, 0.5, 1.6))   # on the frame he showed
    assert [a.point for a in marks[4].anchors] == [(0, 0, 12), (40, 0, 12), (40, 25, 12), (0, 25, 12)]   # the face's own outline
    assert result["drawn"][0].startswith("Mark 1 (your circle) on Box.Face6")


def test_claudes_new_marks_replace_its_old_ones_but_never_his(session) -> None:
    book = session.screen.book_for("Bracket")
    book.add("point", [ModelAnchor((1, 1, 1))])
    session.call("mark_for_user", {"marks": [{"kind": "point", "at": [0, 0, 0]}]})
    session.call("mark_for_user", {"marks": [{"kind": "point", "at": [5, 5, 5]}]})
    assert [(m.author, m.anchors[0].point) for m in book.marks] == [(VisualMarkAuthor.USER, (1, 1, 1)), (VisualMarkAuthor.ASSISTANT, (5.0, 5.0, 5.0))]
    session.call("mark_for_user", {"marks": [], "clear_previous": True})
    assert [m.author for m in book.marks] == [VisualMarkAuthor.USER]


def test_a_bad_mark_draws_nothing_and_tells_claude_why(session) -> None:
    result = session.call("mark_for_user", {"marks": [{"kind": "point", "at": [0, 0, 0]}, {"kind": "arrow", "on": "Box.Face6"}]})
    assert result["ok"] is False and "needs 'to'" in result["detail_for_claude"]
    assert session.screen.book_for("Bracket").marks == []                # all or nothing
    for spec, words in (({"kind": "scribble", "at": [0, 0, 0]}, "not one of"), ({"kind": "point"}, "say where"),
                        ({"kind": "point", "on": "Nope.Face1"}, "no object called"), ({"kind": "point", "picture_xy": [2, 0]}, "fractions"),
                        ({"kind": "lasso", "points": [[0, 0, 0]]}, "at least three")):
        result = session.call("mark_for_user", {"marks": [spec]})
        assert result["ok"] is False and words in result["detail_for_claude"], spec
        assert "Traceback" not in result["say_to_founder"]


def test_the_reply_carries_a_picture_of_his_screen_when_the_panel_is_open(session, tmp_path) -> None:
    shot = tmp_path / "screen-now.png"
    shot.write_bytes(b"png")
    session.screen.compose = lambda: str(shot)
    result = session.call("mark_for_user", {"marks": [{"kind": "point", "at": [0, 0, 0]}]})
    assert result["images"] == [str(shot)]


# ---- get_selection ----------------------------------------------------------------------------

def test_get_selection_reads_faces_and_clicked_points(session) -> None:
    result = session.call("get_selection", {})
    assert result["ok"] and result["summary"] == "Selected: Face6 of Box."
    assert result["selection"][0]["picked_points_mm"] == [[20.0, 12.5, 12.0]]


def test_get_selection_without_a_window_is_plain(session) -> None:
    session.gui = None
    assert session.call("get_selection", {})["summary"] == "FreeCAD has no window open, so nothing can be selected."


# ---- versions: broken, restore keeps everything ---------------------------------------------------

def test_a_backup_of_a_broken_model_is_marked_broken_and_still_restores(session) -> None:
    session.call("versions", {"action": "save"})                 # backup: the open model has a Pocket in error
    session.doc.Objects[1].State = []
    session.call("versions", {"action": "save", "note": "checkpoint you saved"})
    listed = session.call("versions", {"action": "list"})["versions"]
    assert [(v["version"], v["broken"]) for v in listed] == [(1, ["Pocket"]), (2, [])]
    assert listed[1]["note"] == "checkpoint you saved"
    Path(session.doc.FileName).write_bytes(b"model as it is now")    # his file on disk is version 2 exactly
    restored = session.call("versions", {"action": "restore", "version": 1})
    assert restored["ok"] and restored["version"] == 3
    after = session.call("versions", {"action": "list"})["versions"]
    assert [v["version"] for v in after] == [1, 2, 3]            # restoring deleted nothing
    assert after[2]["kind"] == "restore" and after[2]["restored_from"] == 1 and after[2]["broken"] == ["Pocket"]


def test_a_restore_keeps_his_hand_edits_as_a_version_first(session) -> None:
    session.call("versions", {"action": "save"})                         # v1
    session.call("versions", {"action": "save"})                         # v2
    Path(session.doc.FileName).write_bytes(b"he changed it by hand in FreeCAD and saved")
    restored = session.call("versions", {"action": "restore", "version": 1})
    listed = session.call("versions", {"action": "list"})["versions"]
    assert [v["version"] for v in listed] == [1, 2, 3, 4] and restored["version"] == 4
    assert listed[2]["note"] == "your model just before going back to version 1" and listed[2]["kind"] == "backup"
    again = session.call("versions", {"action": "restore", "version": 2})     # nothing changed since: no extra copy
    assert again["version"] == 5
    assert session.call("versions", {"action": "restore", "version": 99})["say_to_founder"] == "There is no version 99."


def test_the_time_slider_reads_versions_without_starting_the_worker(session, tmp_path) -> None:
    assert session.store_for(session.doc) is None                # nothing saved yet, and nothing created to find that out
    session.call("versions", {"action": "save"})
    assert session.store_for(session.doc).latest() == 1


def test_old_version_records_without_the_broken_field_still_read(tmp_path) -> None:
    store = AdoptedStore(tmp_path / "records", tmp_path / "His.FCStd")
    (tmp_path / "records" / "adopted.v1.json").write_text(json.dumps({"version": 1, "file": "x", "sha256": "a", "diff": "d"}))
    assert store.get(1).broken == []


# ---- the server -------------------------------------------------------------------------------

def test_the_server_offers_the_three_new_tools_and_tells_claude_when_to_use_them() -> None:
    import asyncio

    server = plugin_server.build_server()
    tools = {t.name: t for t in asyncio.run(server.list_tools())}
    assert {"shown_to_claude", "mark_for_user", "get_selection"} <= set(tools)
    assert "Show Claude" in tools["shown_to_claude"].description
    assert "picture_xy" in tools["mark_for_user"].description
    assert 'says "this", "here"' in plugin_server.INSTRUCTIONS
