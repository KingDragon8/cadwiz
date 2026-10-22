# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""ORDER-2026-10-18-02 / -03: the new connector tools and what they stand on.

Stand-ins for FreeCAD; the real-FreeCAD, real-Blender run is
scripts/panel_phase2_witness.py. The mesh repair job runs REAL pymeshlab here
(it lives in the system Python these tests run in).
"""
from __future__ import annotations

import json
import struct
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from ai_freecad_core.cadwiz_screen.preferences import FounderPreferences
from ai_freecad_core.visual_communications.anchored import MarkBook, ModelAnchor
from integrations.cadwiz_plugin import fetch, mesh_tools, panel_pages, preferences_store, problems_watch
from integrations.cadwiz_plugin.session import PluginSession

ROOT = Path(__file__).resolve().parents[1]
SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="120"><rect width="200" height="120" fill="white"/><circle cx="60" cy="60" r="30"/></svg>'


@pytest.fixture
def session(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setenv("CADWIZ_SETTINGS_FILE", str(tmp_path / "settings.json"))
    (tmp_path / "settings.json").write_text(json.dumps({"cad_folders": [str(tmp_path)]}))
    doc = SimpleNamespace(Name="Lure", Label="Lure", FileName=str(tmp_path / "Lure.FCStd"), Objects=[])
    app = SimpleNamespace(listDocuments=lambda: {"Lure": doc}, ActiveDocument=doc, setActiveDocument=lambda n: None)
    return PluginSession(app=app, project_root=tmp_path / "projects", log_path=tmp_path / "calls.jsonl")


# ---- user_preferences -----------------------------------------------------------------------

def test_claude_reads_the_preferences_he_saved_on_setup(session) -> None:
    first = session.call("user_preferences", {})
    assert first["ok"] and any("short and plain" in rule for rule in first["follow_these"])
    preferences_store.save(FounderPreferences(explanations="teach", questions="none", big_changes="go_ahead"))
    rules = " ".join(session.call("user_preferences", {})["follow_these"])
    assert "teach as you go" in rules and "use sensible defaults" in rules and "go ahead" in rules


def test_a_broken_preferences_file_never_stops_anything(session, tmp_path) -> None:
    path = preferences_store.preferences_path()
    path.write_text("{ not json", encoding="utf-8")
    assert preferences_store.load(path).text_px == 18
    profile = preferences_store.printer_profile(FounderPreferences())
    assert profile.min_wall_mm == 0.8 and profile.bed_x_mm == 220.0          # two nozzle widths


# ---- the concept stage --------------------------------------------------------------------------

def test_show_concepts_posts_a_round_and_nothing_is_3d_until_he_says(session, tmp_path, monkeypatch) -> None:
    photo = tmp_path / "dog.png"
    photo.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)
    monkeypatch.setattr(fetch, "_get", lambda url, cap: (b"\x89PNG\r\n\x1a\n" + b"1" * 64, "image/png", url))
    result = session.call("show_concepts", {"note": "three dogs", "cards": [
        {"title": "Golden Retriever Wizard", "picture_url": "https://cdn.thingiverse.com/dog.png", "kind": "found",
         "source": "https://www.thingiverse.com/thing:5190074", "licence": "CC BY-NC", "has_3d_file": True},
        {"title": "Dog with a bone", "svg": SVG},
        {"title": "From his folder", "picture_path": str(photo), "source": "his own photo"},
    ]})
    assert result["ok"] and result["round"] == 1 and len(result["cards"]) == 3
    assert result["cards"][0]["licence_line"].endswith("not for selling") and result["cards"][1]["kind"] == "sketch"
    assert all(Path(c["picture"]).is_file() for c in result["cards"])
    assert "photo-real" in result["honest_line"]
    choice = session.call("concept_choice", {})
    assert choice["picked"] is None and choice["make_3d_requested"] is None
    session.screen.concepts.pick(1, 2)
    session.screen.concepts.request_3d()
    session.screen.save_concepts()
    assert session.call("concept_choice", {})["make_3d_requested"]["title"] == "Dog with a bone"
    reopened = PluginSession(app=session.app, project_root=session.project.folder.parent, log_path=session.log_path)
    assert reopened.call("concept_choice", {})["picked"]["card"] == 2            # his choice survives a restart


def test_bad_cards_draw_nothing_and_tell_claude_why(session) -> None:
    four = [{"title": f"c{i}", "svg": SVG} for i in range(4)]
    for cards, words in ((four, "one to 3 cards"), ([{"title": "x"}], "needs a picture"),
                         ([{"title": "x", "svg": "<html>"}], "one <svg> drawing"),
                         ([{"title": "x", "picture_url": "http://example.com/a.png", "source": "s"}], "only https"),
                         ([{"title": "Found thing", "svg": SVG, "kind": "found"}], "needs its source")):
        result = session.call("show_concepts", {"cards": cards})
        assert result["ok"] is False and words in result["detail_for_claude"], words
    assert session.screen.concepts.rounds == []


def test_his_sellable_only_setting_flags_non_commercial_cards(session, monkeypatch) -> None:
    preferences_store.save(FounderPreferences(licences="sellable_only"))
    result = session.call("show_concepts", {"cards": [{"title": "NC dog", "svg": SVG, "kind": "found", "source": "thingiverse", "licence": "CC BY-NC"}]})
    assert result["not_allowed_by_his_licence_setting"] == ["NC dog"]


# ---- guided intent --------------------------------------------------------------------------------

def test_design_questions_follow_his_setting(session) -> None:
    plan = session.call("design_questions", {"request": "a fishing lure for my nephew"})
    assert plan["family"] == "fishing lure" and len(plan["ask"]) == 3 and "design_record" in plan["after_answers"]
    preferences_store.save(FounderPreferences(questions="none", print_material="PETG"))
    plan = session.call("design_questions", {"request": "a fishing lure"})
    assert plan["ask"] == [] and any("PETG (your Setup choice)" in d for d in plan["assumed_defaults"])
    assert session.call("design_questions", {"request": ""})["ok"] is False


# ---- fetch: one file, safely ---------------------------------------------------------------------

def test_fetch_refuses_what_it_should(tmp_path) -> None:
    def getter(kind):
        return lambda url, cap: kind
    for url in ("http://example.com/a.png", "https://localhost/a.png", "https://127.0.0.1/a.png", "file:///c:/a.png", "ftp://x/y"):
        with pytest.raises(fetch.FetchRefused):
            fetch.fetch_picture(url, tmp_path, "a", getter=getter((b"", "image/png", url)))
    with pytest.raises(fetch.FetchRefused, match="did not return a picture"):
        fetch.fetch_picture("https://example.com/a", tmp_path, "a", getter=getter((b"<html>", "text/html", "https://example.com/a")))
    with pytest.raises(fetch.FetchRefused, match="web page, not a model file"):
        fetch.fetch_model("https://www.printables.com/model/1", tmp_path, getter=getter((b"<html>", "text/html", "https://www.printables.com/model/1")))
    with pytest.raises(fetch.FetchRefused, match="not a readable STL"):
        fetch.fetch_model("https://x.com/a.stl", tmp_path, getter=getter((b"tiny", "application/octet-stream", "https://x.com/a.stl")))


def test_fetch_never_overwrites_and_keeps_the_real_file_name(tmp_path) -> None:
    stl = b"solid x\nendsolid x\n"
    getter = lambda url, cap: (stl, "application/octet-stream", "https://files.example.com/dl/Golden_Retriever.stl")  # noqa: E731
    first = fetch.fetch_model("https://example.com/download?id=1", tmp_path, getter=getter)
    second = fetch.fetch_model("https://example.com/download?id=1", tmp_path, getter=getter)
    assert first.name == "Golden_Retriever.stl" and second.name == "Golden_Retriever_2.stl" and first.read_bytes() == stl


# ---- the problems list ------------------------------------------------------------------------------

class _Box:
    def __init__(self, x0, x1):
        self.x0, self.x1 = x0, x1
        self.BoundBox = SimpleNamespace(XMin=x0, XMax=x1, YMin=0, YMax=10, ZMin=0, ZMax=10)
        self.Volume = (x1 - x0) * 100.0

    def distToShape(self, other):  # noqa: N802
        return (max(0.0, other.x0 - self.x1, self.x0 - other.x1), None, None)

    def common(self, other):
        return SimpleNamespace(Volume=max(0.0, min(self.x1, other.x1) - max(self.x0, other.x0)) * 100.0)


def _solid_obj(name, x0, x1):
    shape = SimpleNamespace(isNull=lambda: False, Solids=[_Box(x0, x1)])
    return SimpleNamespace(Name=name, Label=name, TypeId="Part::Feature", Shape=shape, ViewObject=SimpleNamespace(Visibility=True),
                           State=[], getParentGeoFeatureGroup=lambda: None)


def test_a_loose_part_is_found_with_its_gap_in_both_units() -> None:
    doc = SimpleNamespace(Name="D", Objects=[_solid_obj("Jaw", 0, 40), _solid_obj("Stick", 40.5, 50)])
    problems = problems_watch.find_problems(doc, True)
    assert [p.kind for p in problems] == ["loose"]
    assert problems[0].what == "the Stick doesn't touch the Jaw: a 0.02 in (0.5 mm) gap means it prints as a loose piece"
    assert problems[0].objects == ["Stick"]


def test_overlap_failed_rebuild_open_sketch_mesh_holes_and_the_connection() -> None:
    broken = SimpleNamespace(Name="Fillet", Label="Fillet", TypeId="Part::Fillet", State=["Invalid"], getStatusString=lambda: "BRep_API: command not done")
    wire = SimpleNamespace(isClosed=lambda: False, Vertexes=[SimpleNamespace(Point=_P(0, 0)), SimpleNamespace(Point=_P(0.5, 0))])
    sketch = SimpleNamespace(Name="Sketch", Label="Sketch", TypeId="Sketcher::SketchObject", State=[], Shape=SimpleNamespace(Wires=[wire]),
                             InList=[SimpleNamespace(TypeId="PartDesign::Pad", Label="Pad")])
    mesh = SimpleNamespace(Name="Dog", Label="Dog", TypeId="Mesh::Feature", ViewObject=SimpleNamespace(Visibility=True),
                           Mesh=SimpleNamespace(countComponents=lambda: 2, isSolid=lambda: False, hasNonManifolds=lambda: True))
    doc = SimpleNamespace(Name="D", Objects=[broken, sketch, mesh, _solid_obj("A", 0, 20), _solid_obj("B", 15, 30)])
    found = problems_watch.find_problems(doc, connected=False)
    kinds = [p.kind for p in found]
    assert kinds == ["connection", "rebuild", "sketch_open", "loose", "mesh_holes", "overlap"]
    assert found[1].detail_for_claude == "BRep_API: command not done" and "BRep" not in found[1].what
    assert "0.02 in (0.5 mm) gap" in found[2].what
    assert "cubic in" in found[5].what


class _P:
    def __init__(self, x, y):
        self.x, self.y = x, y

    def __sub__(self, other):
        return SimpleNamespace(Length=((self.x - other.x) ** 2 + (self.y - other.y) ** 2) ** 0.5)


def test_the_problems_tool_gives_claude_the_detail(session) -> None:
    session.app.ActiveDocument.Objects = [_solid_obj("Jaw", 0, 40), _solid_obj("Stick", 41, 50)]
    result = session.call("problems", {})
    assert result["ok"] and result["summary"] == "1 problem found." and result["problems"][0]["detail_for_claude"].startswith("min distance")


# ---- mesh tools -------------------------------------------------------------------------------------------

def test_a_region_comes_from_his_arrow_or_circle_or_numbers() -> None:
    book = MarkBook()
    book.add("arrow", [ModelAnchor((0.0, 0.0, 10.0)), ModelAnchor((10.0, 0.0, 10.0))])
    book.add("circle", [ModelAnchor((5.0, 5.0, 5.0)), ModelAnchor((7.0, 5.0, 5.0))])
    along = mesh_tools.region_from({"mark": 1}, book.marks)
    assert along["center"] == [5.0, 0.0, 10.0] and along["axis"] == [1.0, 0.0, 0.0] and along["half_length_mm"] == 5.5
    around = mesh_tools.region_from({"mark": 2}, book.marks)
    assert around["radius_mm"] == 2.0 and around["half_length_mm"] == 2.0
    given = mesh_tools.region_from({"center": [1, 2, 3], "axis": [0, 0, 2], "radius_mm": 1.5, "length_mm": 8}, [])
    assert given["axis"] == [0.0, 0.0, 1.0] and given["half_length_mm"] == 4.0
    for bad in ({"mark": 9}, {"center": [0, 0, 0]}):
        with pytest.raises(mesh_tools.MeshToolError):
            mesh_tools.region_from(bad, book.marks)


def test_mesh_tools_refuse_bad_requests_plainly(session) -> None:
    for tool, args, words in (("mesh_edit", {"operation": "melt"}, "operation must be one of"),
                              ("import_mesh", {"path": "a.stl", "url": "https://x/a.stl"}, "exactly one of"),
                              ("import_mesh", {}, "exactly one of"),
                              ("swap_part", {"region": {"mark": 1}}, "no mesh parts")):
        result = session.call(tool, args)
        assert result["ok"] is False and words in result["detail_for_claude"], tool


def _cube_with_a_hole(path: Path) -> None:
    """A unit cube as a binary STL with one of its 12 triangles missing."""
    v = [(0, 0, 0), (10, 0, 0), (10, 10, 0), (0, 10, 0), (0, 0, 10), (10, 0, 10), (10, 10, 10), (0, 10, 10)]
    faces = [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4), (1, 2, 6), (1, 6, 5), (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7)][:-1]
    data = bytearray(b"\0" * 80) + struct.pack("<I", len(faces))
    for a, b, c in faces:
        data += struct.pack("<12fH", 0, 0, 0, *v[a], *v[b], *v[c], 0)
    path.write_bytes(bytes(data))


def test_the_repair_job_closes_a_hole_with_real_pymeshlab(tmp_path) -> None:
    pytest.importorskip("pymeshlab")
    source, output = tmp_path / "holed.stl", tmp_path / "repaired.stl"
    _cube_with_a_hole(source)
    request, result = tmp_path / "request.json", tmp_path / "result.json"
    request.write_text(json.dumps({"job": "repair", "source": str(source), "output": str(output)}))
    subprocess.run([sys.executable, "-m", "integrations.cadwiz_plugin.mesh_job", str(request), str(result)], cwd=ROOT,
                   env={**__import__("os").environ, "PYTHONPATH": str(ROOT / "src")}, check=True, capture_output=True, timeout=300)
    reply = json.loads(result.read_text())
    assert reply["ok"], reply
    assert reply["before"]["holes"] == 1 and reply["before"]["watertight"] is False
    assert reply["after"]["holes"] == 0 and reply["after"]["watertight"] is True and output.is_file()
    request.write_text(json.dumps({"job": "repair", "source": str(source), "output": str(output)}))
    subprocess.run([sys.executable, "-m", "integrations.cadwiz_plugin.mesh_job", str(request), str(result)], cwd=ROOT,
                   env={**__import__("os").environ, "PYTHONPATH": str(ROOT / "src")}, check=True, capture_output=True, timeout=300)
    assert json.loads(result.read_text())["ok"] is False                       # never overwrites its output


# ---- Printing page lines ------------------------------------------------------------------------------------

def test_the_licence_line_comes_from_the_import_record(tmp_path) -> None:
    model = tmp_path / "Dog.FCStd"
    mesh_tools.write_provenance(model, source="https://www.thingiverse.com/thing:5190074", licence="CC BY-NC 4.0", original="dog.stl")
    line = panel_pages.licence_line(SimpleNamespace(FileName=str(model)))
    assert line.startswith("Licence: CC BY-NC 4.0: personal, non-commercial") and "thing:5190074" in line
    assert panel_pages.licence_line(SimpleNamespace(FileName=str(tmp_path / "Mine.FCStd"))).startswith("Licence: your own design")


def test_bed_fit_says_yes_or_no_with_both_units() -> None:
    printer = FounderPreferences().printer
    assert "bed: yes" in panel_pages.bed_fit_line((100.0, 50.0, 30.0), printer)
    assert "bed: NO" in panel_pages.bed_fit_line((300.0, 50.0, 30.0), printer)
    assert "3.94 in (100 mm)" in panel_pages.bed_fit_line((100.0, 50.0, 30.0), printer)
    assert panel_pages.PRINT_TIME_HONEST.format(slicer="Cura").endswith("CADWiz can't read them from Cura yet.")


def test_a_change_made_by_a_script_is_noticed_without_an_undo_step() -> None:
    box = SimpleNamespace(XMin=0, YMin=0, ZMin=0, XMax=10, YMax=10, ZMax=10)
    part = SimpleNamespace(Name="Stick", TypeId="Part::Box", State=[], Visibility=True, Shape=SimpleNamespace(BoundBox=box))
    doc = SimpleNamespace(Name="D", UndoCount=3, RedoCount=0, Objects=[part])
    before = problems_watch.signature(doc, True)
    box.XMin, box.XMax = 1, 11                                   # moved by a script: same undo count
    assert problems_watch.signature(doc, True) != before
    assert problems_watch.signature(doc, False) != problems_watch.signature(doc, True)


def test_a_turned_view_is_noticed_so_marks_follow_the_pictures_own_line_of_sight() -> None:
    from ai_freecad_core.visual_communications.anchored import Camera
    from integrations.cadwiz_plugin import view_link

    camera = Camera("orthographic", (54.39, -9.39, 36.89), (0.4247, 0.1759, 0.3399, 0.8205), height=75.83, focal_distance=37.91)
    nudged = Camera("orthographic", (54.39, -9.39, 36.89), (0.4247, 0.1759, 0.3399, 0.8205), height=75.84, focal_distance=37.91)
    assert view_link.same_camera(camera, Camera.from_dict(camera.to_dict()))
    assert not view_link.same_camera(camera, nudged)                 # a zoom of 0.01 mm is a different picture
    assert view_link.ray_hit(camera, 0.5, 0.5, 1.0) is None            # outside FreeCAD (no FreeCAD module) it says "missed", never guesses


def test_setup_usage_is_one_sentence_about_the_subscription() -> None:
    # Founder, 2026-10-22: the subscription pays, no charge per question -- nothing else.
    rows = [{"made_by": "founder", "event": "usage", "provider": "p", "utc": "2026-10-12T01:00:00Z", "input_tokens": 1200}]
    for log in ([], rows):
        assert panel_pages.usage_lines(log) == [panel_pages.CLAUDE_USAGE_LINE]
    assert "no charge per question" in panel_pages.CLAUDE_USAGE_LINE


def test_chatgpt_turns_green_only_on_a_real_chatgpt_hello() -> None:
    # ORDER-2026-10-19-02: Claude and ChatGPT each light only on their own hello.
    import time

    from integrations.cadwiz_plugin import bridge as bridge_mod, server
    from integrations.cadwiz_plugin.slim_panel import CONNECTED, GREEN, RED

    assert server.client_name(["node.exe", "claude.exe"]) == "Claude Desktop"
    assert server.client_name(["cmd.exe", "ChatGPT.exe"]) == "ChatGPT"
    assert server.client_name(["node.exe", "codex.exe"]) == "ChatGPT (Codex app)"
    assert bridge_mod.app_of("ChatGPT (Codex app)") == "chatgpt" and bridge_mod.app_of("Claude Desktop") == "claude"

    class FakeBridge:
        def __init__(self, **hellos: float) -> None:
            self.hellos = hellos
        connected = True

        def connected_to(self, app: str) -> bool:
            return time.time() - self.hellos.get(app, 0.0) < bridge_mod.CONNECTED_WITHIN_S

    now = time.time()
    only_claude, both, only_chatgpt = FakeBridge(claude=now), FakeBridge(claude=now, chatgpt=now), FakeBridge(chatgpt=now)
    assert [l["line"] for l in panel_pages.ai_lights(only_claude, "auto")] == [CONNECTED]
    assert [(l["line"], l["light"]) for l in panel_pages.ai_lights(both, "auto")] == [
        (CONNECTED, GREEN), (panel_pages.CHATGPT_CONNECTED, GREEN)]
    assert panel_pages.ai_lights(only_claude, "chatgpt")[0]["light"] == RED
    assert panel_pages.ai_lights(only_chatgpt, "claude")[0]["light"] == RED
    assert [l["line"] for l in panel_pages.ai_lights(only_chatgpt, "auto")] == [panel_pages.CHATGPT_CONNECTED]
    assert panel_pages.ai_lights(None, "auto")[0]["light"] == RED


def test_his_ai_app_choice_is_kept_and_a_bad_one_falls_back() -> None:
    assert FounderPreferences.from_dict({"ai_app": "chatgpt"}).ai_app == "chatgpt"
    assert FounderPreferences.from_dict({"ai_app": "gemini"}).ai_app == "auto"


def test_a_real_bridge_lights_claude_from_its_newest_hello() -> None:
    # The panel witnesses set last_hello directly; that hello is Claude's (no client named).
    import time

    from integrations.cadwiz_plugin.bridge import Bridge

    bridge = Bridge(lambda tool, arguments: {}, info_path=Path("unused.json"))
    try:
        assert not bridge.connected_to("claude")
        bridge.last_hello = time.time()
        assert bridge.connected_to("claude") and not bridge.connected_to("chatgpt")
        bridge.client, bridge.hellos["chatgpt"] = "ChatGPT", time.time()
        assert bridge.connected_to("chatgpt")
    finally:
        bridge._server.server_close()
