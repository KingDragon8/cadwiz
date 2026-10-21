# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""ORDER-2026-10-12-05: CADWiz as a Claude Desktop plug-in (MCP server).

Stand-ins for FreeCAD and the worker; the real-FreeCAD session is
scripts/plugin_witness.py. These pin the rules that live in code: the tool set,
the instructions Claude gets, plain failures, folder limits, backup before any
write, no delete, every call logged, and the bridge's token.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import pytest

from ai_freecad_core.conversation.founder_words import findings
from integrations.cadwiz_plugin import server as plugin_server
from integrations.cadwiz_plugin.bridge import Bridge
from integrations.cadwiz_plugin.session import TOOL_NAMES, PluginSession


class _Store:
    def __init__(self):
        self.versions = []
        self.backed_up_this_session = False

    def backup(self, snapshot, note=""):
        self.backed_up_this_session = True
        self.versions.append(SimpleNamespace(version=len(self.versions) + 1, kind="backup", diff="backup", file="v.FCStd", utc="", sha256="a", measurements={}))
        return self.versions[-1]

    def list_recent(self, limit=10):
        return self.versions[-limit:]

    def current(self):
        return self.versions[-1] if self.versions else None

    def get(self, n):
        return next((v for v in self.versions if v.version == n), None)

    def latest(self):
        return len(self.versions)


class _Executor:
    def __init__(self, project, name, file_name, **hooks):
        self.object_name = name
        self.adoption = {}
        self.store = _Store()
        self.calls = []
        self.export_allowed = False

    def adopt(self):
        self.adoption = {"main_object": "Cone", "facts": {"editability": {"level": "E3", "evidence": ["Part::Cone"]}},
                         "construction": {"kind": "solid or parametric model"}}
        return self.adoption

    def measure(self, queries):
        return {"summary": "60 mm (2.362 in) wide", "bottom_opening": None}

    def edit_existing(self, script, note):
        self.calls.append(("edit_existing", script))
        if "boom" in script:
            return {"success": False, "error": "NameError: name 'boom' is not defined", "error_line": 3}
        if not self.store.backed_up_this_session:
            self.store.backup(None)
        self.store.versions.append(SimpleNamespace(version=len(self.store.versions) + 1, kind="edit", diff="width 60 -> 70 mm", file="v2", utc="", sha256="b", measurements={}))
        return {"success": True, "version": len(self.store.versions), "diff": "width 60 -> 70 mm", "measurements": "70 mm wide"}

    def reshape_rings(self, target, note):
        self.calls.append(("reshape_rings", target))
        return {"success": True, "version": 2, "diff": f"inside bottom -> {target} mm around"}

    def set_parameters(self, changes, note):
        self.calls.append(("set_parameters", changes))
        return {"success": True, "version": 2, "diff": "changed"}

    def current_state(self):
        current = self.store.current()
        return {"version": current.version if current else 0, "diff": current.diff if current else ""}

    def versions(self, action, version, note):
        return {"version": 3, "diff": f"restored version {version} exactly"}

    def export(self, fmt):
        assert self.export_allowed
        return {"path": f"x.{fmt}"}


class _Doc:
    def __init__(self, label, file_name):
        self.Label = label
        self.Name = label
        self.FileName = file_name
        self.Objects = [SimpleNamespace(Name="Cone", Label="Cone", TypeId="Part::Cone", Visibility=True)]
        self.saved_as = None

    def saveAs(self, path):
        self.saved_as = path
        self.FileName = path


@pytest.fixture
def session(tmp_path, monkeypatch):
    monkeypatch.setenv("CADWIZ_SETTINGS_FILE", str(tmp_path / "settings.json"))
    (tmp_path / "cad").mkdir()
    (tmp_path / "settings.json").write_text(json.dumps({"cad_folders": [str(tmp_path / "cad")]}))
    cone = tmp_path / "cad" / "Cone.FCStd"
    cone.write_bytes(b"cone")
    doc = _Doc("Cone", str(cone))
    app = SimpleNamespace(listDocuments=lambda: {"Cone": doc}, ActiveDocument=doc, openDocument=lambda p: _Doc(Path(p).stem, p),
                          setActiveDocument=lambda n: None, newDocument=lambda n: _Doc(n, ""))
    s = PluginSession(app=app, project_root=tmp_path / "projects", executor_factory=_Executor, log_path=tmp_path / "calls.jsonl")
    s.doc = doc
    return s


def test_the_tool_set_is_the_founders_list() -> None:
    assert set(TOOL_NAMES) == {"inspect_document", "measure", "render", "build_model", "edit_object", "versions", "check_print", "export",
                               "open_document", "save_document", "design_record", "contract_check",
                               # ORDER-2026-10-18-01: the screen he and Claude share
                               "shown_to_claude", "mark_for_user", "get_selection",
                               # ORDER-2026-10-18-02 / -03: preferences, problems, concepts, guided intent, mesh and Blender
                               "user_preferences", "problems", "show_concepts", "concept_choice", "design_questions",
                               "import_mesh", "mesh_edit", "swap_part", "repair_mesh",
                               # ORDER-2026-10-19-06: technical drawings, founder ruling 2026-10-19
                               "drawing"}
    assert not any("delete" in name or "remove" in name for name in TOOL_NAMES)


def test_the_server_offers_exactly_those_tools_with_the_instructions() -> None:
    import asyncio

    server = plugin_server.build_server()
    tools = {t.name for t in asyncio.run(server.list_tools())}
    assert tools == set(TOOL_NAMES) | set(plugin_server.SERVER_TOOLS)
    text = plugin_server.INSTRUCTIONS
    for rule in ("Measure instead of asking", "adopt and edit THAT object", "backed up", "render", "assumptions in one line",
                 "inches and millimetres", "sources and licences", "the user's own picture always wins", "never show them raw errors",
                 "call `shown_to_claude` FIRST", "`mark_for_user`", "`get_selection`", "never deletes a newer one"):
        assert rule in text, rule


def test_inspect_reads_the_open_document(session) -> None:
    result = session.call("inspect_document", {})
    assert result["ok"] and result["document"] == "Cone" and result["editability"]["level"] == "E3"
    assert result["objects"][0]["parametric"] is True


def test_an_edit_backs_up_first_and_makes_a_version(session) -> None:
    result = session.call("build_model", {"code": "doc.getObject('Cone').Radius1 = 35"})
    executor = next(iter(session._executors.values()))
    assert result["ok"] and executor.store.versions[0].kind == "backup" and result["version"] == 2
    assert session.state["version"] == 2 and session.state["last_change"] == "width 60 -> 70 mm"


def test_claudes_code_error_comes_back_exact_but_the_founder_line_is_plain(session) -> None:
    result = session.call("build_model", {"code": "boom()"})
    assert not result["ok"] and "NameError" in result["detail_for_claude"] and "line 3" in result["detail_for_claude"]
    assert not findings(result["say_to_founder"])


def test_ring_resize_goes_to_reshape_rings(session) -> None:
    result = session.call("edit_object", {"inner_bottom_circumference_mm": 902})
    executor = next(iter(session._executors.values()))
    assert result["ok"] and ("reshape_rings", 902.0) in executor.calls


def test_open_and_save_stay_inside_the_cad_folders(session, tmp_path) -> None:
    outside = tmp_path / "elsewhere.FCStd"
    outside.write_bytes(b"x")
    refused = session.call("open_document", {"path": str(outside)})
    assert not refused["ok"] and "outside your CAD folders" in refused["say_to_founder"]
    inside_file = tmp_path / "cad" / "Other.FCStd"
    inside_file.write_bytes(b"x")
    assert session.call("open_document", {"path": str(inside_file)})["ok"]
    existing = session.call("save_document", {"path": str(inside_file)})
    assert not existing["ok"] and "never overwrite" in existing["say_to_founder"]


def test_saving_his_file_backs_it_up_first(session) -> None:
    session.doc.save = lambda: None
    result = session.call("save_document", {})
    executor = next(iter(session._executors.values()))
    assert result["ok"] and executor.store.versions and executor.store.versions[0].kind == "backup"


def test_export_only_through_the_tool_and_every_call_is_logged(session, tmp_path) -> None:
    assert session.call("export", {"format": "stl"})["ok"]
    session.call("no_such_tool", {})
    lines = [json.loads(l) for l in (tmp_path / "calls.jsonl").read_text().splitlines()]
    assert [l["tool"] for l in lines] == ["export", "no_such_tool"] and lines[1]["ok"] is False


def test_nothing_open_is_a_plain_sentence(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CADWIZ_SETTINGS_FILE", str(tmp_path / "s.json"))
    app = SimpleNamespace(listDocuments=lambda: {}, ActiveDocument=None)
    s = PluginSession(app=app, project_root=tmp_path / "p", executor_factory=_Executor, log_path=tmp_path / "c.jsonl")
    result = s.call("measure", {"question": "how big is it"})
    assert result == {"ok": False, "say_to_founder": "Nothing is open in FreeCAD yet. Open a model, or ask me to build one."}


# ---- the bridge -------------------------------------------------------------------------

def _post(port, route, body, token):
    request = urllib.request.Request(f"http://127.0.0.1:{port}/{route}", data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json", **({"X-CADWiz-Token": token} if token else {})})
    return json.loads(urllib.request.urlopen(request, timeout=10).read())


def test_the_bridge_needs_the_token_and_listens_only_locally(tmp_path) -> None:
    bridge = Bridge(lambda tool, args: {"ok": True, "tool": tool, "args": args}, info_path=tmp_path / "bridge.json").start()
    try:
        info = json.loads((tmp_path / "bridge.json").read_text())
        assert info["port"] == bridge.port and info["token"] == bridge.token
        assert bridge._server.server_address[0] == "127.0.0.1"
        with pytest.raises(urllib.error.HTTPError) as refused:
            _post(bridge.port, "call", {"tool": "measure"}, token="wrong")
        assert refused.value.code == 403
        assert _post(bridge.port, "call", {"tool": "measure", "arguments": {"question": "q"}}, bridge.token) == {"ok": True, "tool": "measure", "args": {"question": "q"}}
        assert not bridge.connected
        _post(bridge.port, "hello", {"client": "Claude Desktop"}, bridge.token)
        assert bridge.connected and bridge.client == "Claude Desktop"
    finally:
        bridge.stop()
    assert not (tmp_path / "bridge.json").exists()


def test_the_server_says_plainly_when_freecad_is_not_open(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    result = plugin_server.call("inspect_document", {})
    assert result == {"ok": False, "say_to_founder": plugin_server.NOT_RUNNING}


def test_a_reply_with_pictures_reaches_claude_as_text_and_images(monkeypatch, tmp_path) -> None:
    """Found by the real witness session, 2026-10-12: FastMCP's structured output
    could not carry a picture, so the edit's reply never reached Claude."""
    import asyncio
    import struct
    import zlib

    picture = tmp_path / "render.png"
    raw = b"\x00\xff\x00\x00"
    png = (b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
           + struct.pack(">I", zlib.crc32(b"IHDR" + struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)))
           + struct.pack(">I", len(zlib.compress(raw))) + b"IDAT" + zlib.compress(raw)
           + struct.pack(">I", zlib.crc32(b"IDAT" + zlib.compress(raw))) + struct.pack(">I", 0) + b"IEND" + struct.pack(">I", zlib.crc32(b"IEND")))
    picture.write_bytes(png)
    monkeypatch.setattr(plugin_server, "call", lambda tool, args: {"ok": True, "version": 2, "images": [str(picture)], "after": {"height_mm": 88.79}})
    result = asyncio.run(plugin_server.build_server().call_tool("edit_object", {"inner_bottom_circumference_mm": 902}))
    content = result[0] if isinstance(result, tuple) else result
    assert [c.type for c in content] == ["text", "image"]
    assert json.loads(content[0].text)["after"]["height_mm"] == 88.79


# ---- the slim panel (Part 4) ---------------------------------------------------------------

def test_the_slim_panel_lines(session) -> None:
    from integrations.cadwiz_plugin import slim_panel

    assert slim_panel.panel_lines(None)["connection"] == slim_panel.NO_BRIDGE
    session.call("build_model", {"code": "doc.getObject('Cone').Radius1 = 35"})
    bridge = SimpleNamespace(session=session, connected=False)
    lines = slim_panel.panel_lines(bridge)
    # ORDER-2026-10-18-01: when not connected the light is red and says what to do.
    assert lines["connection"] == slim_panel.NOT_CONNECTED and lines["light"] == slim_panel.RED
    assert "Open your assistant app" in lines["todo"]
    assert lines["working_on"] == "Working on: Cone / Cone, version 2"
    assert lines["last_change"] == "Last change: width 60 -> 70 mm"
    bridge.connected = True
    assert slim_panel.panel_lines(bridge)["connection"] == "Connected to Claude"
