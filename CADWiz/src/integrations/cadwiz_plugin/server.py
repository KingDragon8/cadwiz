# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""CADWiz's MCP server for Claude Desktop (ORDER-2026-10-12-05).

Claude Desktop starts this (stdio) when it opens:

    "C:\\Program Files\\FreeCAD 1.1\\bin\\python.exe" <install>\\src\\integrations\\cadwiz_plugin\\server.py

It makes no AI calls and spends nothing: it only forwards Claude's tool calls to
the CADWiz bridge inside the founder's running FreeCAD and returns plain results
and pictures. Every tool's work is done -- and every rule enforced -- in FreeCAD
(`session.py`), not here.
"""
from __future__ import annotations

import json
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

_SRC = Path(__file__).resolve().parents[2]
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

INSTRUCTIONS = """CADWiz gives you hands and eyes in the user's FreeCAD on this computer. They are usually a maker with a 3D printer; talk plainly.
- At the start of a conversation call `user_preferences` and follow it: how much to explain, whether to ask before building, whether to ask before big changes, their printer and material, which licences are acceptable, inches or millimetres first.
- New designs start as pictures, not 3D. Search for real examples (their preferred sites are in user_preferences) and post up to three cards with `show_concepts` (picture, source page, licence, whether a 3D file exists), or draw your own rough sketch as an SVG card. Say plainly that you find designs and sketch; you do not make photo-real pictures. The user picks and asks for changes on pictures; build NOTHING in 3D until `concept_choice` shows make_3d_requested or they tell you to make it 3D.
- Before building, call `design_questions` with their words: ask at most the three questions it gives, in one message, each with its default; if they say "just make it" (or their preference is no questions) use the defaults and say which. Record the answers with `design_record`, build, then `contract_check`.
- Engineered parts (brackets, bridges, lures, boxes, knobs): follow the build rules `design_questions` returns -- PartDesign bodies, constrained sketches, named sizes, fillets and chamfers, print clearances, walls of at least two nozzle widths. Organic shapes (figurines, sculpted bodies) are meshes: `import_mesh`, `mesh_edit`, `swap_part`, `repair_mesh`.
- If `shown_to_claude` carries `the_founder_asks` (the user pressed a button such as "Ask Claude to fix"), that is their request: do it. `problems` lists what their screen shows as problems, with the technical detail for you.
- Measure instead of asking the user for any number the model holds (`measure`, `inspect_document`).
- When the user says "this", "here", "that one" or "what I'm showing you", call `shown_to_claude` FIRST: it is the frame they froze on their CADWiz screen with the Show Claude button -- the picture, their numbered marks (anchored on the model, with the face each sits on), their selection, the view and the version. "This" means their newest mark or their selection. If they have not pressed Show Claude, use `get_selection` and `render` with current_view=true.
- To point back at something, draw on their screen with `mark_for_user` (your marks appear in orange beside their blue ones and stay on the model as they turn it); clear them when they no longer apply.
- When the user refers to something that is open ("the helmet", "this cone", "it"), adopt and edit THAT object (`edit_object`, `build_model` on that document); never make a new one in its place.
- Their file is backed up beside itself automatically before the first change; every change is a version (`versions` list/restore/compare), a complete saved copy. A version marked broken can still be restored; restoring adds a new version and never deletes a newer one. Never delete anything of theirs.
- After every change, show a render (`render`) and the key measurements, with a one-line description of what changed.
- State assumptions in one line instead of asking; a missing dimension is never a reason to stop.
- Give sizes in both inches and millimetres.
- A body lofted through rings (inspect says so, e.g. a helmet shell) is resized by its rings: `edit_object` with `inner_bottom_circumference_mm` keeps the wall and bladder thickness, the height and the top.
- For concepts, search the web for real examples and show their sources and licences; the user's own picture always wins.
- If a tool result has `say_to_founder`, that is the plain sentence to say to the user; `detail_for_claude` is for you only (fix your code with it) -- never show them raw errors, tracebacks or parameter lists.
- Export or print only when the user asks."""

TIMEOUT_S = 900.0


_chosen: dict[str, Any] = {}
_client: list[str] = []


def client_name(ancestors: list[str] | None = None) -> str:
    """Which AI app started this server, from the programs above it
    (ORDER-2026-10-19-02): the panel turns "ChatGPT connected" green only on
    this. Anything not recognised as ChatGPT's is Claude Desktop, as before."""
    if ancestors is None:
        if not _client:
            from ai_freecad_core.ai.spend_guard import _process_names_of_ancestors

            _client.append(client_name(_process_names_of_ancestors(limit=12)))
        return _client[0]
    names = [a.lower() for a in ancestors]
    if any(n.startswith("chatgpt") for n in names):
        return "ChatGPT"
    if any(n.startswith("codex") for n in names):
        return "ChatGPT (Codex app)"
    return "Claude Desktop"


def _bridges() -> list[dict[str, Any]]:
    """Every FreeCAD that has the CADWiz bridge running, newest first."""
    from integrations.cadwiz_plugin.session import plugin_data_dir

    found = []
    for path in (plugin_data_dir() / "bridges").glob("*.json"):
        try:
            found.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return sorted(found, key=lambda b: str(b.get("started_utc", "")), reverse=True)


def _alive(info: dict[str, Any]) -> bool:
    try:
        _send(info, "hello", {"client": client_name()}, timeout=3)
        return True
    except (urllib.error.URLError, ConnectionError, TimeoutError, OSError, ValueError):
        return False


def _bridge() -> dict[str, Any] | None:
    """The user's FreeCAD: the bridge last used if it still answers, else the
    newest one that does."""
    if _chosen and _alive(_chosen):
        return _chosen
    _chosen.clear()
    for info in _bridges():
        if _alive(info):
            _chosen.update(info)
            return _chosen
    return None


def _send(info: dict[str, Any], route: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(f"http://127.0.0.1:{info['port']}/{route}", data=json.dumps(payload).encode("utf-8"),
                                     headers={"Content-Type": "application/json", "X-CADWiz-Token": str(info.get("token", ""))}, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


NOT_RUNNING = "FreeCAD isn't open with CADWiz right now. Open FreeCAD (CADWiz starts with it), then ask me again."


def _post(route: str, payload: dict[str, Any], timeout: float = TIMEOUT_S) -> dict[str, Any]:
    info = _bridge()
    if not info:
        return {"ok": False, "say_to_founder": NOT_RUNNING}
    try:
        return _send(info, route, payload, timeout)
    except (urllib.error.URLError, ConnectionError, TimeoutError, OSError, ValueError):
        return {"ok": False, "say_to_founder": NOT_RUNNING}


def call(tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return _post("call", {"tool": tool, "arguments": {k: v for k, v in arguments.items() if v is not None}})


def _heartbeat() -> None:
    while True:
        _post("hello", {"client": client_name()}, timeout=5)
        time.sleep(30)


#: Tools that run in this server process rather than in FreeCAD (ORDER-2026-10-21-01).
SERVER_TOOLS = ("cadwiz_known_issues", "cadwiz_send_feedback")


def help_desk() -> Any:
    from integrations.cadwiz_plugin.feedback import HelpDesk
    from integrations.cadwiz_plugin.session import plugin_data_dir

    return HelpDesk(plugin_data_dir(), docs_dir=Path(__file__).resolve().parents[3] / "docs")


def build_server() -> Any:
    from mcp.server.fastmcp import FastMCP, Image

    server = FastMCP("CADWiz", instructions=INSTRUCTIONS)

    def reply(result: dict[str, Any]) -> list[Any]:
        images = [p for p in (result.pop("images", None) or []) if Path(str(p)).is_file()]
        parts: list[Any] = [json.dumps(result, indent=1, default=str)]
        parts.extend(Image(path=str(p)) for p in images[:6])
        return parts

    @server.tool(structured_output=False)
    def inspect_document(document: str | None = None) -> list[Any]:
        """What is open in FreeCAD: documents, object tree (types, parametric features, sketches and constraints, spreadsheets), how the main object was built, its editability level (E0-E4), key measurements and versions."""
        return reply(call("inspect_document", {"document": document}))

    @server.tool(structured_output=False)
    def measure(question: str = "", object: str | None = None, document: str | None = None) -> list[Any]:  # noqa: A002
        """Measure the open model: overall size, wall thickness, openings (inside size, distance around), hole sizes and spacing, any named distance, diameter or circumference, volume. Ask in plain words, e.g. "inside circumference at the bottom opening". Answers in mm and inches."""
        return reply(call("measure", {"question": question, "object": object, "document": document}))

    @server.tool(structured_output=False)
    def render(views: list[str] | None = None, section: bool = False, current_view: bool = True, object: str | None = None,  # noqa: A002
               document: str | None = None) -> list[Any]:
        """Pictures of the model: views such as iso, front, top, right; section=true for a cut-away; current_view=true adds the user's own 3D view."""
        return reply(call("render", {"views": views, "section": section, "current_view": current_view, "object": object, "document": document}))

    @server.tool(structured_output=False)
    def drawing(dimensions: list[dict[str, Any]] | None = None, section: str = "auto", note: str = "",
                document: str | None = None) -> list[Any]:
        """A technical drawing sheet of the open model, shown on their CADWiz screen and saved as SVG and PDF (Letter, landscape): front, top and right views (third-angle; a hollow part gets SECTION A-A instead of the right view), a 3D view, overall sizes in inches with mm, and a title block. `dimensions` adds any they ask for: [{"view": "front"|"top"|"right"|"section", "start": [x, y, z], "end": [x, y, z], "label": optional words, "offset": sheet mm, + below/right of the line, - above/left}] with points in model mm (measure them, or take them from their marks). `section`: "auto", "on" or "off"."""
        return reply(call("drawing", {"dimensions": dimensions, "section": section, "note": note, "document": document}))

    @server.tool(structured_output=False)
    def build_model(code: str, document: str | None = None, note: str = "", new_document: str | None = None) -> list[Any]:
        """Run FreeCAD Python that creates or edits objects in `doc`: the open document, or -- for something NEW -- a fresh document named `new_document` (use this for a new part so it never lands inside the user's open model). Runs sandboxed (no network, files or programs) on a copy; the user's file is backed up first, the result becomes a new version and appears in their FreeCAD. On failure you get the exact error and line."""
        return reply(call("build_model", {"code": code, "document": document, "note": note, "new_document": new_document}))

    @server.tool(structured_output=False)
    def edit_object(object: str | None = None, parameters: dict[str, Any] | None = None, script: str | None = None,  # noqa: A002
                    inner_bottom_circumference_mm: float | None = None, note: str = "", document: str | None = None) -> list[Any]:
        """Change an existing object: `parameters` for named values of a parametric model (e.g. {"Params.wall": "2 mm"}, {"Cone.Radius1": "30 mm"}); `script` for shape operations on a fixed solid or mesh (boolean, offset/thicken, scale, fillet) editing `doc` in place; or `inner_bottom_circumference_mm` to resize a lofted ring body (e.g. a helmet shell) by its rings, keeping wall and bladder thickness, height and top. Backed up first; a new version."""
        return reply(call("edit_object", {"object": object, "parameters": parameters, "script": script,
                                          "inner_bottom_circumference_mm": inner_bottom_circumference_mm, "note": note, "document": document}))

    @server.tool(structured_output=False)
    def versions(action: str = "list", version: int | None = None, other: int | None = None, document: str | None = None) -> list[Any]:
        """Versions of the open model: action = list | save | restore (go back to `version`, exactly) | compare (`version` with `other`)."""
        return reply(call("versions", {"action": action, "version": version, "other": other, "document": document}))

    @server.tool(structured_output=False)
    def check_print(printer: str = "", document: str | None = None) -> list[Any]:
        """Check the model against the user's printer profile: bed fit, overhangs, thin walls, closed (manifold) solid."""
        return reply(call("check_print", {"printer": printer, "document": document}))

    @server.tool(structured_output=False)
    def export(format: str, document: str | None = None) -> list[Any]:  # noqa: A002
        """Export the current version as stl, 3mf, step or fcstd into the project folder. Only when the user asks for a file."""
        return reply(call("export", {"format": format, "document": document}))

    @server.tool(structured_output=False)
    def open_document(path: str) -> list[Any]:
        """Open a FreeCAD file from the user's CAD folders."""
        return reply(call("open_document", {"path": path}))

    @server.tool(structured_output=False)
    def save_document(document: str | None = None, path: str | None = None) -> list[Any]:
        """Save the open document (backed up first), or save it under a new name inside their CAD folders (never over an existing file)."""
        return reply(call("save_document", {"document": document, "path": path}))

    @server.tool(structured_output=False)
    def design_record(action: str = "get", fields: dict[str, Any] | None = None, document: str | None = None) -> list[Any]:
        """Read or update the Design Contract: intent, named dimensions with units, features, relationships, requirements (name, metric, target, tolerance), assumptions."""
        return reply(call("design_record", {"action": action, "fields": fields, "document": document}))

    @server.tool(structured_output=False)
    def contract_check(document: str | None = None) -> list[Any]:
        """Check each requirement of the Design Contract against the measured model: pass/fail with the measured value."""
        return reply(call("contract_check", {"document": document}))

    @server.tool(structured_output=False)
    def shown_to_claude() -> list[Any]:
        """What the user is showing you: the frame they froze with the Show Claude button on their CADWiz screen -- the picture with their numbered marks (blue; yours are orange), every mark anchored on the model in mm with the object and face it sits on, what they had selected, the view, and the document's version. Call this FIRST whenever they say "this", "here" or "that". Reading it tells their screen "Claude has it"."""
        return reply(call("shown_to_claude", {}))

    @server.tool(structured_output=False)
    def mark_for_user(marks: list[dict[str, Any]] | None = None, clear_previous: bool = True, document: str | None = None) -> list[Any]:
        """Draw on the user's CADWiz screen, in orange, anchored to the model so each mark stays on its spot as they turn it. Each mark: {"kind": point | circle | box | highlight | lasso | arrow | measure | note, "at": [x, y, z] in mm, or "on": an object or one of its faces/edges/vertices such as "Pad.Face6", or "picture_xy": [x, y] as fractions across and down the frame they showed you; "to": the same forms, for where an arrow or measure ends or a box's far corner (a box or highlight "on" a face needs none); "radius_mm" for a circle; "points": three or more places for a lasso; "text": a short note}. clear_previous (default true) takes your earlier marks off first; marks=[] with clear_previous=true just clears them. Returns a picture of their screen with your marks."""
        return reply(call("mark_for_user", {"marks": marks or [], "clear_previous": clear_previous, "document": document}))

    @server.tool(structured_output=False)
    def get_selection(document: str | None = None) -> list[Any]:
        """What the user has selected in FreeCAD right now, in any workbench: each object, the faces, edges or vertices they picked, and the exact points they clicked (mm)."""
        return reply(call("get_selection", {"document": document}))

    @server.tool(structured_output=False)
    def show_concepts(cards: list[dict[str, Any]], note: str = "", new_design: bool = False) -> list[Any]:
        """Post up to three design options to the user's CADWiz screen ("Choosing a design") BEFORE any 3D. Each card: {"title": short name, a picture -- "picture_url" (https, a real design you found), "picture_path" (a picture on their PC) or "svg" (your own rough sketch as one <svg> drawing) --, "kind": "found" or "sketch", "source": the page it came from (required for found), "licence": as stated on that page, "has_3d_file": true if a model file exists, "model_url": its page or file link, "note": one line}. note = what this round shows or changed (e.g. "same dog, holding a bone instead of a stick"). new_design=true starts a fresh history. Every round is kept; they pick a card and presses Make it 3D when they are ready."""
        return reply(call("show_concepts", {"cards": cards, "note": note, "new_design": new_design}))

    @server.tool(structured_output=False)
    def concept_choice() -> list[Any]:
        """Which concept card the user picked on their screen, every round so far, and whether they pressed Make it 3D (make_3d_requested). Do not build in 3D before that, unless they tell you to."""
        return reply(call("concept_choice", {}))

    @server.tool(structured_output=False)
    def design_questions(request: str) -> list[Any]:
        """The few questions that change this design (at most three, each with a one-word default), the defaults assumed for the rest, how to record the answers in design_record, which tool to build with (FreeCAD or Blender), and the build rules for a professional part. Pass their request in their own words, e.g. "a fishing lure"."""
        return reply(call("design_questions", {"request": request}))

    @server.tool(structured_output=False)
    def import_mesh(path: str | None = None, url: str | None = None, name: str = "", source: str = "", licence: str = "",
                    separate_parts: bool = False) -> list[Any]:
        """Bring a model into FreeCAD from a file on their PC (path) or a download link (url): STL, 3MF, OBJ or STEP. It goes into its own document in CADWiz's project folder (their file is never changed) and is saved as version 1. Give the source page and the licence as stated there; a non-commercial licence is told to them plainly. separate_parts=true keeps loose pieces as separate parts."""
        return reply(call("import_mesh", {"path": path, "url": url, "name": name, "source": source, "licence": licence,
                                          "separate_parts": separate_parts}))

    @server.tool(structured_output=False)
    def mesh_edit(operation: str, part: str | None = None, document: str | None = None, iterations: int = 8, factor: float = 0.5,
                  voxel_mm: float = 0.3, ratio: float = 0.5, scale: float | None = None, height_mm: float | None = None,
                  thickness_mm: float = 2.0, other: str | None = None, boolean: str = "union", base_height_mm: float = 3.0,
                  base_margin_mm: float = 3.0, base_shape: str = "round") -> list[Any]:
        """Organic mesh work in headless Blender on one mesh part (default: the largest), saved as a new version: smooth (iterations, factor), remesh (voxel_mm detail), decimate (ratio of triangles kept), scale (scale factor or height_mm), hollow (thickness_mm wall inward), solidify (thickness_mm, for an open surface), boolean (union | difference | intersect with part `other`), add_base (base_height_mm, base_margin_mm, base_shape round|square, added as its own part)."""
        return reply(call("mesh_edit", {"operation": operation, "part": part, "document": document, "iterations": iterations, "factor": factor,
                                        "voxel_mm": voxel_mm, "ratio": ratio, "scale": scale, "height_mm": height_mm, "thickness_mm": thickness_mm,
                                        "other": other, "boolean": boolean, "base_height_mm": base_height_mm, "base_margin_mm": base_margin_mm,
                                        "base_shape": base_shape}))

    @server.tool(structured_output=False)
    def swap_part(region: dict[str, Any], replacement: str = "bone", part: str | None = None, replacement_file: str | None = None,
                  length_mm: float | None = None, thickness_mm: float | None = None, document: str | None = None) -> list[Any]:
        """Replace a held or attached piece of a mesh model (the stick in a dog's mouth -> a bone): the piece inside `region` is taken out of the part and the hole closed (the proven swap pipeline), then the replacement -- "bone", "stick", "ball" made in Blender along the same axis, "none", or replacement_file (an STL placed at the region's centre) -- is added as its OWN part. region = {"mark": n} (their arrow or measure along the piece, or a circle around it, from shown_to_claude) or {"center": [x,y,z], "axis": [x,y,z], "radius_mm": r, "length_mm": l}. Saved as a new version."""
        return reply(call("swap_part", {"region": region, "replacement": replacement, "part": part, "replacement_file": replacement_file,
                                        "length_mm": length_mm, "thickness_mm": thickness_mm, "document": document}))

    @server.tool(structured_output=False)
    def repair_mesh(part: str | None = None, document: str | None = None, max_hole_edges: int = 100, drop_bits_under_faces: int = 0) -> list[Any]:
        """Repair a mesh part before printing with pymeshlab: duplicate and broken faces, non-manifold edges, holes (up to max_hole_edges), faces turned the same way; drop_bits_under_faces > 0 removes loose crumbs smaller than that. Reports holes, loose pieces and watertightness before and after. Saved as a new version."""
        return reply(call("repair_mesh", {"part": part, "document": document, "max_hole_edges": max_hole_edges,
                                          "drop_bits_under_faces": drop_bits_under_faces}))

    @server.tool(structured_output=False)
    def user_preferences() -> list[Any]:
        """How the user wants you to work, as they set it on CADWiz's Setup page: explanations (just do it / short and plain / teach me), questions before building (a few with defaults / none), before big changes (ask first / go ahead), their printers, nozzle, material and quality, licences they accept, model sites, inches or mm first. Read it at the start and follow it."""
        return reply(call("user_preferences", {}))

    @server.tool(structured_output=False)
    def problems(document: str | None = None) -> list[Any]:
        """The problems CADWiz's Creating page shows for the open model: failed rebuilds, broken or open sketches, loose or overlapping parts (with the gap in mm), mesh holes. Each has a plain line for the user and `detail_for_claude` (FreeCAD's own error) for you."""
        return reply(call("problems", {"document": document}))

    # ---- ORDER-2026-10-21-01 (Addendum One Part B): Claude as the help desk. These run
    # here, in the server's own process, not in FreeCAD: they read local files and
    # talk only to https://cadwiz.app.
    desk = help_desk()

    @server.tool(structured_output=False)
    def cadwiz_known_issues(about: str = "") -> list[Any]:
        """What the CADWiz project has said about bugs and requests: the maintainer's own labels (accepted = planned, later, fixed in vX.Y, declined with the reason) and what is in and out of scope. Use it to answer "can CADWiz do X?" or "is this a known bug?" (pass the words or a CW- error code as `about`). Falls back to the documents shipped with CADWiz when offline, and says so."""
        return reply(desk.known_issues(about))

    @server.tool(structured_output=False)
    def cadwiz_send_feedback(section: str, title: str, description: str, public: bool | None = None, report_id: str = "",
                             include: list[str] | None = None, confirm: bool = False) -> list[Any]:
        """File a bug, idea or question on cadwiz.app for the user. When CADWiz hits a wall (a missing tool, an error report, a shape it cannot build) offer ONCE: "Want me to send this to Steve?" -- never send without a yes. "Tell Steve CADWiz should do X" is a public idea. section: bug | idea | question; public defaults to false for a bug, true otherwise. report_id: a CWR-... error report to attach; include: which of its items go (screenshot, error, trail, versions, model_file; the model file only if the user asks). Without confirm=true this ONLY returns a preview -- exactly what would be sent, already scrubbed of file paths and the user name -- and sends nothing; show it to the user, and call again with confirm=true only after they say yes. The first send may open a cadwiz.app sign-in page in their browser."""
        try:
            return reply(desk.send_feedback(section, title, description, public=public, report_id=report_id,
                                            include=include, confirm=confirm))
        except (TypeError, ValueError) as error:
            return reply({"ok": False, "sent": False, "say_to_founder": "That couldn't be filed as it is; nothing was sent.",
                          "detail_for_claude": str(error)})

    return server


def main() -> None:
    threading.Thread(target=_heartbeat, name="cadwiz-heartbeat", daemon=True).start()
    build_server().run()


if __name__ == "__main__":
    main()
