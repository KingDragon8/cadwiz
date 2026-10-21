# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""ORDER-2026-10-15-01: three founder-found bugs in the Claude plug-in path.

1. A shape Claude built arrived HIDDEN in his FreeCAD: the windowless worker's
   file has no window state, and his FreeCAD opened it with the shape switched
   off. He had to find it in the tree and press Space.
2. The slim panel showed no picture of the result.
3. Opening CADWiz crashed with KeyError 'Lifecycle': the old panel's display
   routine wrote to field labels the slim panel never builds.

Stand-ins for FreeCAD and Qt; the files are real FCStd-shaped zips.
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from integrations.cadwiz_plugin import slim_panel
from integrations.cadwiz_plugin.session import PluginSession, show_and_frame, visible_in_file


def _object_data(name: str, visible: bool) -> str:
    return (f'<Object name="{name}"><Properties Count="1">'
            f'<Property name="Visibility" type="App::PropertyBool" status="648"><Bool value="{"true" if visible else "false"}"/></Property>'
            f"</Properties></Object>")


def _fcstd(path: Path, objects: dict[str, bool], window_state: tuple[str, ...] | None = None) -> Path:
    document = ('<?xml version="1.0" encoding="utf-8"?><Document SchemaVersion="4"><Objects Count="1"/>'
                f'<ObjectData Count="{len(objects)}">' + "".join(_object_data(n, v) for n, v in objects.items()) + "</ObjectData></Document>")
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("Document.xml", document)
        if window_state is not None:
            archive.writestr("GuiDocument.xml", '<Document><ViewProviderData>'
                             + "".join(f'<ViewProvider name="{n}"/>' for n in window_state) + "</ViewProviderData></Document>")
    return path


class _Obj:
    def __init__(self, name: str):
        self.Name = name
        self.Visibility = False
        self.ViewObject = SimpleNamespace(Visibility=False)


class _View:
    def __init__(self):
        self.calls: list[str] = []

    def viewIsometric(self):
        self.calls.append("iso")

    def fitAll(self):
        self.calls.append("fit")


class _Gui:
    def __init__(self):
        self.view = _View()
        self.active = None

    def setActiveDocument(self, name):
        self.active = name

    def getDocument(self, name):
        return SimpleNamespace(ActiveView=self.view)


class _OpenedDoc:
    def __init__(self, path: str, names: list[str]):
        self.Name = Path(path).stem
        self.Label = self.Name
        self.FileName = path
        self.objects = {n: _Obj(n) for n in names}
        self.Objects = list(self.objects.values())

    def getObject(self, name):
        return self.objects.get(name)


# ---- 1. new shapes arrive visible, turned and framed ------------------------------------

def test_a_new_document_from_the_worker_shows_what_the_file_marks_visible(tmp_path) -> None:
    path = _fcstd(tmp_path / "Sphere_1in.FCStd", {"Sphere_1in": True, "Helper": False})
    assert visible_in_file(path) == {"Sphere_1in"}


def test_his_own_hidden_choice_is_kept_but_a_newly_added_shape_is_shown(tmp_path) -> None:
    # "Lid" has window state of its own (his file) -> left to it; "Hole" was just added by the worker.
    path = _fcstd(tmp_path / "Box.FCStd", {"Lid": True, "Hole": True, "Old": False}, window_state=("Lid", "Old"))
    assert visible_in_file(path) == {"Hole"}


def test_an_unreadable_file_changes_nothing(tmp_path) -> None:
    bad = tmp_path / "not-a-zip.FCStd"
    bad.write_bytes(b"nope")
    assert visible_in_file(bad) == set()
    assert visible_in_file(tmp_path / "missing.FCStd") == set()


def test_show_and_frame_switches_on_turns_iso_and_fits(tmp_path) -> None:
    gui = _Gui()
    doc = _OpenedDoc(str(tmp_path / "Sphere_1in.FCStd"), ["Sphere_1in", "Helper"])
    show_and_frame(gui, doc, {"Sphere_1in", "NotThere"})
    assert doc.objects["Sphere_1in"].Visibility is True and doc.objects["Sphere_1in"].ViewObject.Visibility is True
    assert doc.objects["Helper"].Visibility is False
    assert gui.active == "Sphere_1in" and gui.view.calls == ["iso", "fit"]


def test_a_view_that_cannot_turn_never_costs_the_change(tmp_path) -> None:
    class _Broken:
        def setActiveDocument(self, name):
            raise RuntimeError("no window")

        def getDocument(self, name):
            raise RuntimeError("no window")

    doc = _OpenedDoc(str(tmp_path / "S.FCStd"), ["S"])
    show_and_frame(_Broken(), doc, {"S"})        # must not raise
    assert doc.objects["S"].Visibility is True


@pytest.fixture
def session(tmp_path, monkeypatch):
    monkeypatch.setenv("CADWIZ_SETTINGS_FILE", str(tmp_path / "settings.json"))
    (tmp_path / "settings.json").write_text(json.dumps({"cad_folders": [str(tmp_path)]}))
    opened: dict[str, _OpenedDoc] = {}

    def open_document(path):
        opened["doc"] = _OpenedDoc(path, ["Sphere_1in"])
        return opened["doc"]

    app = SimpleNamespace(listDocuments=lambda: {}, ActiveDocument=None, openDocument=open_document,
                          setActiveDocument=lambda n: None, closeDocument=lambda n: None)
    s = PluginSession(app=app, gui=_Gui(), project_root=tmp_path / "projects", log_path=tmp_path / "calls.jsonl",
                      executor_factory=lambda *a, **k: None)
    s.opened = opened
    return s


def test_reload_after_a_build_leaves_nothing_for_him_to_press(session, tmp_path) -> None:
    path = _fcstd(tmp_path / "Sphere_1in.FCStd", {"Sphere_1in": True})
    session._reload(str(path))
    shown = session.opened["doc"].objects["Sphere_1in"]
    assert shown.Visibility is True and shown.ViewObject.Visibility is True
    assert session.gui.view.calls == ["iso", "fit"]


# ---- 2. the slim panel's picture box ------------------------------------------------------

def test_the_newest_render_reaches_the_slim_panel(session, tmp_path) -> None:
    picture = tmp_path / "iso.png"
    picture.write_bytes(b"png")
    executor = SimpleNamespace(current_state=lambda: {"version": 2, "diff": "made a sphere"})
    session._after_change(executor, {"success": True, "diff": "made a sphere", "measurements": "25.4 mm (1 in) across",
                                     "images": [str(tmp_path / "gone.png"), str(picture)]})
    assert session.state["picture"] == str(picture)          # the first picture that exists
    lines = slim_panel.panel_lines(SimpleNamespace(session=session, connected=True))
    assert lines["picture"] == str(picture)
    session._after_change(executor, {"success": True, "diff": "x", "images": []})
    assert session.state["picture"] == str(picture)          # no new picture: keep the last one
    assert slim_panel.panel_lines(None)["picture"] == ""


# ---- 3. opening CADWiz with the slim panel no longer crashes ------------------------------

def test_the_panel_display_skips_labels_the_slim_panel_does_not_have() -> None:
    # The old assistant panel is not part of the open-source release (ORDER-2026-10-21-01).
    QtWorkbenchPanel = pytest.importorskip("integrations.freecad_native.workbench_ui").QtWorkbenchPanel

    dock = SimpleNamespace(show=lambda: None, raise_=lambda: None)
    panel = QtWorkbenchPanel.__new__(QtWorkbenchPanel)
    panel._labels = {}                                        # what the slim panel leaves it with
    panel._beginner_toggle = None
    panel._guidance_card = None
    panel._first_run_controls = []
    panel._ensure_dock = lambda: dock
    panel._offer_crash_recovery_once = lambda: None
    view = SimpleNamespace(lifecycle="ready", runtime="FreeCAD 1.1", document="No document", revision=0, execution="", validation="",
                           raw_request="", intent="", assumptions=[], open_questions=[], plan="", commands=[], capabilities=[],
                           validation_evidence=[], repair_attempts=[], final_result="", workflow_id="", workflow_state="",
                           workflow_event="", workflow_pause_reason="", workflow_controls=[], beginner_mode=False,
                           first_run_invitation=False, guidance_title="", guidance_body="")
    panel.show(view)                                          # raised KeyError: 'Lifecycle' before the fix
