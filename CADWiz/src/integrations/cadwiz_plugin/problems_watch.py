# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Finds the problems the Creating page lists, in the founder's open document
(ORDER-2026-10-18-03, docs/CADWIZ-PANEL-REDESIGN-PROPOSAL.md section 2.6).

Watched: failed rebuilds, broken or open sketches, broken features, loose or
overlapping parts, holes in a mesh, and a lost Claude connection. Runs on
FreeCAD's window thread, so it is bounded: it is re-run only when the document
changes (`signature`) and skips the pairwise part checks beyond MAX_PARTS.

The pairwise checks (how far apart two parts are, how much they overlap) are
OpenCASCADE calls with no time limit of their own. On 2026-10-19 they held the
founder's window for good: a tennis ball with a swept seam groove, its sphere
and seam tube left visible, took 27 s for ONE distance, then an open-ended
intersection, repeated every 30 s (ORDER-2026-10-19-03). A time budget checked
BETWEEN calls cannot stop a call that is already running. So inside FreeCAD's
window those checks run in a windowless FreeCAD (`geometry_job.py`,
BackgroundGeometry): the window only writes each part out and later reads the
answer; a job past GEOMETRY_TIME_LIMIT_S is stopped. Outside the window (tests,
the headless worker) they run inline as before.
"""
from __future__ import annotations

import contextlib
import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from ai_freecad_core.cadwiz_screen.problems import Problem, gap_words, overlap_words

#: Two shapes this close (mm) touch.
TOUCHING_MM = 0.01
#: More separate parts than this and the pairwise checks are skipped (said so).
MAX_PARTS = 24
#: Seconds the overlap checks may take in all, once the gaps are known.
OVERLAP_BUDGET_S = 0.8
#: The windowless parts check is stopped after this many seconds.
GEOMETRY_TIME_LIMIT_S = 90.0
#: Features that need a closed outline from their sketch.
PROFILE_FEATURES = ("PartDesign::Pad", "PartDesign::Pocket", "PartDesign::Revolution", "PartDesign::Groove",
                    "PartDesign::AdditiveLoft", "PartDesign::SubtractiveLoft", "Part::Extrusion", "Part::Revolution", "Part::Face")


def signature(document: Any, connected: bool) -> Any:
    """Changes whenever the document does (an edit, an undo, a reload) or the
    connection changes: the problems are looked for again only then."""
    if document is None:
        return ("none", connected)
    with contextlib.suppress(Exception):
        return (document.Name, getattr(document, "UndoCount", 0), getattr(document, "RedoCount", 0), len(document.Objects),
                tuple(sorted(o.Name for o in document.Objects if "Touched" in (getattr(o, "State", None) or ()))),
                _shape_fingerprint(document.Objects), connected, BACKGROUND.finished())
    return (getattr(document, "Name", ""), connected)


def _shape_fingerprint(objects: list[Any]) -> tuple:
    """Where every shape is: a change made by a script (Claude's, or a macro) leaves
    no undo step, but it moves a bounding box. Bounding boxes are cached by
    FreeCAD, so this costs next to nothing."""
    marks = []
    for obj in objects:
        with contextlib.suppress(Exception):
            box = obj.Mesh.BoundBox if str(getattr(obj, "TypeId", "")) == "Mesh::Feature" else obj.Shape.BoundBox
            marks.append((obj.Name, round(box.XMin, 3), round(box.YMin, 3), round(box.ZMin, 3),
                          round(box.XMax, 3), round(box.YMax, 3), round(box.ZMax, 3), bool(getattr(obj, "Visibility", True))))
    return tuple(marks)


def find_problems(document: Any, connected: bool = True) -> list[Problem]:
    problems: list[Problem] = []
    if not connected:
        problems.append(Problem("connection", "The connection light is red: Claude cannot see or change the model right now."))
    if document is None:
        return problems
    objects = list(getattr(document, "Objects", []) or [])
    problems.extend(_rebuild_problems(objects))
    problems.extend(_open_sketches(objects))
    problems.extend(_mesh_problems(objects))
    problems.extend(BACKGROUND.problems(objects) if _in_freecad_window() else _loose_and_overlapping(objects))
    return problems


def _in_freecad_window() -> bool:
    with contextlib.suppress(Exception):
        import FreeCAD  # noqa: PLC0415 - only there inside FreeCAD

        return bool(FreeCAD.GuiUp)
    return False


def _state(obj: Any) -> set[str]:
    with contextlib.suppress(TypeError):
        return set(str(s) for s in (getattr(obj, "State", None) or ()))
    return set()


def _rebuild_problems(objects: list[Any]) -> list[Problem]:
    found = []
    for obj in objects:
        if not _state(obj) & {"Invalid", "Error"}:
            continue
        detail = ""
        with contextlib.suppress(Exception):
            detail = str(obj.getStatusString())
        label = str(getattr(obj, "Label", obj.Name))
        if str(getattr(obj, "TypeId", "")).startswith("Sketcher::"):
            found.append(Problem("sketch_broken", f"The sketch {label} can't be solved: some of its rules contradict each other.",
                                 [obj.Name], detail_for_claude=detail))
        else:
            found.append(Problem("rebuild", f"{label} failed to rebuild, so the model after it may be wrong or missing.",
                                 [obj.Name], detail_for_claude=detail))
    return found


def _open_sketches(objects: list[Any]) -> list[Problem]:
    found = []
    for obj in objects:
        if not str(getattr(obj, "TypeId", "")).startswith("Sketcher::") or _state(obj) & {"Invalid", "Error"}:
            continue
        users = [u for u in (getattr(obj, "InList", None) or []) if str(getattr(u, "TypeId", "")) in PROFILE_FEATURES]
        if not users:
            continue                                   # a path or a construction sketch may be open on purpose
        with contextlib.suppress(Exception):
            wires = list(obj.Shape.Wires)
            ends = []
            for wire in wires:
                if not wire.isClosed() and wire.Vertexes:
                    ends.extend([wire.Vertexes[0].Point, wire.Vertexes[-1].Point])
            if not ends:
                continue
            gap = min((a - b).Length for i, a in enumerate(ends) for b in ends[i + 1:]) if len(ends) > 1 else 0.0
            from ai_freecad_core.visual_communications.anchored import inches_first

            found.append(Problem("sketch_open", f"The outline of {obj.Label} is not closed (a {inches_first(gap)} gap), "
                                                f"so {users[0].Label} can't use it.", [obj.Name],
                                 detail_for_claude=f"{obj.Name}: {len(ends) // 2} open wire(s); smallest end-to-end gap {gap:.4f} mm"))
    return found


def _visible(obj: Any) -> bool:
    view = getattr(obj, "ViewObject", None)
    with contextlib.suppress(Exception):
        if view is not None:
            return bool(view.Visibility)
    return bool(getattr(obj, "Visibility", False))


def _mesh_problems(objects: list[Any]) -> list[Problem]:
    found = []
    for obj in objects:
        if str(getattr(obj, "TypeId", "")) != "Mesh::Feature" or not _visible(obj):
            continue
        with contextlib.suppress(Exception):
            mesh = obj.Mesh
            pieces = int(mesh.countComponents())
            if pieces > 1:
                found.append(Problem("loose", f"{obj.Label} is in {pieces} separate pieces: the small ones print loose.", [obj.Name],
                                     detail_for_claude=f"{obj.Name}: Mesh.countComponents() = {pieces}"))
            if not mesh.isSolid() or mesh.hasNonManifolds():
                found.append(Problem("mesh_holes", f"{obj.Label}'s surface has holes or torn edges, so it is not a closed solid yet.",
                                     [obj.Name], detail_for_claude=f"{obj.Name}: isSolid={mesh.isSolid()} hasNonManifolds={mesh.hasNonManifolds()}"))
    return found


def _parts(objects: list[Any]) -> list[tuple[str, str, Any]]:
    """(name, label, solid) for every separate visible solid that would print."""
    parts = []
    for obj in objects:
        type_id = str(getattr(obj, "TypeId", ""))
        if (type_id.startswith(("Sketcher::", "App::", "PartDesign::Plane", "PartDesign::Line", "PartDesign::Point", "Spreadsheet::"))
                or type_id == "Mesh::Feature" or not _visible(obj)):
            continue
        parent = None
        with contextlib.suppress(Exception):
            parent = obj.getParentGeoFeatureGroup()
        if parent is not None and str(getattr(parent, "TypeId", "")) == "PartDesign::Body":
            continue                                   # the Body stands for its features
        shape = getattr(obj, "Shape", None)
        with contextlib.suppress(Exception):
            if shape is None or shape.isNull():
                continue
            solids = list(shape.Solids)
            if len(solids) == 1:
                parts.append((obj.Name, str(obj.Label), solids[0]))
            else:
                for index, solid in enumerate(solids, start=1):
                    parts.append((obj.Name, f"{obj.Label} (piece {index} of {len(solids)})", solid))
    return parts


def _loose_and_overlapping(objects: list[Any]) -> list[Problem]:
    return pair_problems(_parts(objects))


def pair_problems(parts: list[tuple[str, str, Any]], overlap_budget_s: float = OVERLAP_BUDGET_S) -> list[Problem]:
    """Loose and overlapping parts among (name, label, solid). Unbounded OCC work:
    never call it on FreeCAD's window thread (see the module note)."""
    if len(parts) < 2 or len(parts) > MAX_PARTS:
        return []
    count = len(parts)
    gaps: dict[tuple[int, int], float] = {}
    for i in range(count):
        for j in range(i + 1, count):
            gaps[(i, j)] = _gap(parts[i][2], parts[j][2])
    group = list(range(count))

    def root(k: int) -> int:
        while group[k] != k:
            group[k] = group[group[k]]
            k = group[k]
        return k

    for (i, j), gap in gaps.items():
        if gap <= TOUCHING_MM:
            group[root(i)] = root(j)
    clusters: dict[int, list[int]] = {}
    for k in range(count):
        clusters.setdefault(root(k), []).append(k)
    found: list[Problem] = []
    if len(clusters) > 1:
        main = max(clusters.values(), key=lambda members: sum(_volume(parts[m][2]) for m in members))
        for members in clusters.values():
            if members is main:
                continue
            nearest = min(((gaps[(min(a, b), max(a, b))], a, b) for a in members for b in main), key=lambda t: t[0])
            _, piece, other = nearest
            gap = _exact_gap(parts[piece][2], parts[other][2])
            found.append(Problem("loose", gap_words(f"the {parts[piece][1]}", f"the {parts[other][1]}", gap),
                                 [parts[piece][0]], detail_for_claude=f"min distance {parts[piece][0]} -> {parts[other][0]} = {gap:.4f} mm"))
    started = time.monotonic()
    for (i, j), gap in gaps.items():
        if gap > TOUCHING_MM or parts[i][0] == parts[j][0]:
            continue
        if time.monotonic() - started > overlap_budget_s:
            break
        with contextlib.suppress(Exception):
            volume = float(parts[i][2].common(parts[j][2]).Volume)
            if volume > 0.01:
                found.append(Problem("overlap", overlap_words(f"the {parts[i][1]}", f"the {parts[j][1]}", volume),
                                     [parts[i][0], parts[j][0]], detail_for_claude=f"common volume {volume:.3f} mm3"))
    return found


def _gap(a: Any, b: Any) -> float:
    with contextlib.suppress(Exception):
        box_a, box_b = a.BoundBox, b.BoundBox
        dx = max(0.0, max(box_a.XMin, box_b.XMin) - min(box_a.XMax, box_b.XMax))
        dy = max(0.0, max(box_a.YMin, box_b.YMin) - min(box_a.YMax, box_b.YMax))
        dz = max(0.0, max(box_a.ZMin, box_b.ZMin) - min(box_a.ZMax, box_b.ZMax))
        apart = (dx * dx + dy * dy + dz * dz) ** 0.5
        if apart > 5.0:
            return apart                               # clearly apart: the boxes say enough
        return float(a.distToShape(b)[0])
    return float("inf")


def _exact_gap(a: Any, b: Any) -> float:
    with contextlib.suppress(Exception):
        return float(a.distToShape(b)[0])
    return _gap(a, b)


def _volume(solid: Any) -> float:
    with contextlib.suppress(Exception):
        return float(solid.Volume)
    return 0.0


class BackgroundGeometry:
    """The pairwise parts check, in a windowless FreeCAD, for FreeCAD's window.

    `problems(objects)` never waits: the first look at a set of parts writes each
    solid out (a BREP file, milliseconds) and starts `geometry_job.py`; later looks
    return its answer once it is there, and nothing until then. A change to the
    parts stops the old job and starts a new one. `finished()` counts answers, so
    `signature` changes when one arrives and the panel looks again at once."""

    def __init__(self, launch: Any = None) -> None:
        self.launch = launch or _launch_job
        self.key: Any = None
        self.process: Any = None
        self.folder: Path | None = None
        self.started = 0.0
        self.answer: list[Problem] = []
        self.answered_key: Any = None
        self.count = 0
        self.timed_out = False

    def finished(self) -> int:
        self._poll()
        return self.count

    def problems(self, objects: list[Any]) -> list[Problem]:
        parts = _parts(objects)
        if len(parts) < 2 or len(parts) > MAX_PARTS:
            return []
        key = _parts_key(parts)
        self._poll()
        if key == self.answered_key:
            return list(self.answer)
        if key != self.key:
            self._start(key, parts)
        return []

    def _start(self, key: Any, parts: list[tuple[str, str, Any]]) -> None:
        self.stop()
        self.key = key
        folder = Path(tempfile.mkdtemp(prefix="cadwiz_parts_check_"))
        try:
            manifest = []
            for index, (name, label, solid) in enumerate(parts):
                brep = folder / f"part{index}.brep"
                solid.exportBrep(str(brep))
                manifest.append({"name": name, "label": label, "brep": str(brep)})
            (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            self.process = self.launch(folder / "manifest.json")
        except Exception:  # noqa: BLE001 - no parts check is better than a held window
            self._answer(key, [], folder)
            return
        self.folder, self.started = folder, time.monotonic()

    def _poll(self) -> None:
        if self.process is None:
            return
        if self.process.poll() is None:
            if time.monotonic() - self.started > GEOMETRY_TIME_LIMIT_S:
                self._answer(self.key, [], self.folder, timed_out=True)
            return
        found: list[Problem] = []
        with contextlib.suppress(Exception):
            rows = json.loads((self.folder / "answer.json").read_text(encoding="utf-8"))  # type: ignore[operator]
            found = [Problem(kind=r["kind"], what=r["what"], objects=list(r.get("objects") or []),
                             elements=list(r.get("elements") or []), detail_for_claude=str(r.get("detail_for_claude") or ""))
                     for r in rows]
        self._answer(self.key, found, self.folder)

    def _answer(self, key: Any, found: list[Problem], folder: Path | None, timed_out: bool = False) -> None:
        self.stop()
        self.answered_key, self.answer, self.timed_out = key, found, timed_out
        self.count += 1
        if folder is not None:
            shutil.rmtree(folder, ignore_errors=True)

    def stop(self) -> None:
        process, self.process = self.process, None
        if process is not None and process.poll() is None:
            with contextlib.suppress(Exception):
                process.kill()
        if process is not None and self.folder is not None:
            shutil.rmtree(self.folder, ignore_errors=True)
        self.folder = None


def _launch_job(manifest: Path) -> Any:
    from integrations.ai_master.executor import find_freecadcmd

    return subprocess.Popen(  # noqa: S603 - FreeCAD's own windowless program running our own script
        [str(find_freecadcmd()), str(Path(__file__).with_name("geometry_job.py")), str(manifest)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _parts_key(parts: list[tuple[str, str, Any]]) -> tuple:
    """Which parts, and where. Cheap on purpose (runs in the window): bounding
    boxes are cached by FreeCAD; a volume would be an integration over the faces."""
    marks = []
    for name, label, solid in parts:
        box = solid.BoundBox
        faces = 0
        with contextlib.suppress(Exception):
            faces = len(solid.Faces)
        marks.append((name, label, round(box.XMin, 3), round(box.YMin, 3), round(box.ZMin, 3),
                      round(box.XMax, 3), round(box.YMax, 3), round(box.ZMax, 3), faces))
    return tuple(marks)


#: The one parts check FreeCAD's window uses.
BACKGROUND = BackgroundGeometry()


def show_me(gui: Any, document: Any, problem: Problem) -> None:
    """Select what the problem is about in FreeCAD and frame it in the view."""
    with contextlib.suppress(Exception):
        gui.Selection.clearSelection()
        for name in problem.objects:
            gui.Selection.addSelection(document.Name, name)
        for item in problem.elements:
            obj, _, element = item.partition(".")
            gui.Selection.addSelection(document.Name, obj, element)
        gui.SendMsgToActiveView("ViewSelection")
