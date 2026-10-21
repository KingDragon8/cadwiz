# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Mesh and Blender as Claude's tools (ORDER-2026-10-18-02 B).

The founder: "a model that's every bit as good as the best FreeCAD can offer and
Blender can offer". The pieces existed (the stick-to-bone swap on the Golden
Retriever Wizard, pymeshlab, Blender 5.2) but Claude could not reach them. Here
they become connector tools, run inside his FreeCAD:

  import_mesh   an STL/3MF/OBJ (or STEP) from a file or a link, into its own
                document, with its source and licence kept beside it (a
                non-commercial licence is said plainly); loose pieces can be
                kept as separate parts.
  mesh_edit     headless Blender on one part: smooth, remesh, decimate, scale,
                hollow, solidify, boolean with another part, add a base.
  swap_part     the proven swap pipeline: remove the held or attached part in a
                marked region (the founder's mark, or a centre and axis), fill
                the hole, and add a replacement (a bone, stick or ball made in
                Blender, or a file) as its OWN part, so the next swap is a
                one-part change.
  repair_mesh   pymeshlab clean-up before printing, before and after measured.

Rules kept here, in code: every operation saves the model as a version first and
after (the time slider); a founder file is never written or deleted (imports go
into CADWiz's project folder; edits change the imported copy); Blender and
Python run as separate processes with no window, while FreeCAD's window keeps
answering.
"""
from __future__ import annotations

import contextlib
import glob
import json
import math
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

from ai_freecad_core.cadwiz_screen.licences import read_licence
from ai_freecad_core.visual_communications.anchored import inches_first

MESH_SUFFIXES = (".stl", ".3mf", ".obj")
SOLID_SUFFIXES = (".step", ".stp")
OPERATIONS = ("smooth", "remesh", "decimate", "scale", "hollow", "solidify", "boolean", "add_base")
REPLACEMENTS = ("bone", "stick", "ball", "none")
JOB_TIME_LIMIT_S = 900.0
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class MeshToolError(Exception):
    """A plain reason for Claude (the founder gets one line from the session)."""


# ---- finding the tools ----------------------------------------------------------------------------
def find_blender() -> Path | None:
    configured = os.environ.get("CADWIZ_BLENDER", "")
    if configured and Path(configured).is_file():
        return Path(configured)
    found = sorted(glob.glob(r"C:\Program Files\Blender Foundation\Blender *\blender.exe"), reverse=True)
    if found:
        return Path(found[0])
    which = shutil.which("blender")
    return Path(which) if which else None


_PYTHON_WITH_PYMESHLAB: list[Path] = []


def find_mesh_python() -> Path | None:
    """A Python that has pymeshlab (the founder's system Python; FreeCAD's has not)."""
    if _PYTHON_WITH_PYMESHLAB:
        return _PYTHON_WITH_PYMESHLAB[0]
    candidates = [os.environ.get("CADWIZ_SYSTEM_PYTHON", "")]
    candidates += sorted(glob.glob(str(Path.home() / "AppData" / "Local" / "Python" / "pythoncore-*" / "python.exe")), reverse=True)
    candidates += sorted(glob.glob(str(Path.home() / "AppData" / "Local" / "Programs" / "Python" / "Python3*" / "python.exe")), reverse=True)
    candidates += [shutil.which("python") or "", shutil.which("py") or ""]
    for candidate in candidates:
        if not candidate or not Path(candidate).is_file() or "FreeCAD" in candidate:
            continue
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            probe = subprocess.run([candidate, "-c", "import pymeshlab"], capture_output=True, timeout=60, creationflags=NO_WINDOW)
            if probe.returncode == 0:
                _PYTHON_WITH_PYMESHLAB.append(Path(candidate))
                return Path(candidate)
    return None


def run_pumped(command: list[str], pump: Callable[[], None] | None, *, env: dict[str, str] | None = None,
               time_limit_s: float = JOB_TIME_LIMIT_S) -> subprocess.CompletedProcess:
    """Run a helper process with no window while FreeCAD's window keeps answering."""
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        process = subprocess.Popen(command, stdout=out, stderr=err, env=env, creationflags=NO_WINDOW)  # noqa: S603 - fixed tools, no shell
        started = time.monotonic()
        while process.poll() is None:
            if pump is not None:
                pump()
            time.sleep(0.05)
            if time.monotonic() - started > time_limit_s:
                process.kill()
                raise MeshToolError("the mesh job took too long and was stopped; nothing was changed")
        out.seek(0)
        err.seek(0)
        return subprocess.CompletedProcess(command, process.returncode, out.read().decode("utf-8", "replace"),
                                           err.read().decode("utf-8", "replace"))


# ---- Blender ------------------------------------------------------------------------------------------
BLENDER_SCRIPT = r'''
import bpy, json, math, sys
from mathutils import Vector
params = json.load(open(sys.argv[sys.argv.index("--") + 1], encoding="utf-8"))
bpy.ops.wm.read_factory_settings(use_empty=True)

def load(path):
    before = set(bpy.data.objects)
    bpy.ops.wm.stl_import(filepath=path)
    new = [o for o in bpy.data.objects if o not in before and o.type == "MESH"]
    if not new:
        raise RuntimeError("nothing was imported from " + path)
    if len(new) > 1:
        bpy.ops.object.select_all(action="DESELECT")
        for o in new:
            o.select_set(True)
        bpy.context.view_layer.objects.active = new[0]
        bpy.ops.object.join()
    obj = new[0]
    bpy.context.view_layer.objects.active = obj
    return obj

def apply(obj, kind, **settings):
    bpy.context.view_layer.objects.active = obj
    mod = obj.modifiers.new(name="cadwiz", type=kind)
    for key, value in settings.items():
        setattr(mod, key, value)
    bpy.ops.object.modifier_apply(modifier=mod.name)

def aim(obj, center, axis):
    direction = Vector(axis).normalized()
    obj.rotation_mode = "QUATERNION"
    obj.rotation_quaternion = Vector((0, 0, 1)).rotation_difference(direction)
    obj.location = Vector(center)

op = params["operation"]
if op == "make_replacement":
    kind, length, thick = params["kind"], float(params["length_mm"]), float(params["thickness_mm"])
    parts = []
    if kind == "ball":
        bpy.ops.mesh.primitive_uv_sphere_add(radius=length / 2, segments=48, ring_count=24)
        parts.append(bpy.context.active_object)
    else:
        shaft = thick * (0.36 if kind == "bone" else 0.5)
        bpy.ops.mesh.primitive_cylinder_add(radius=shaft, depth=length, vertices=48)
        parts.append(bpy.context.active_object)
        if kind == "bone":
            for z in (-length / 2, length / 2):
                for x in (-thick * 0.32, thick * 0.32):
                    bpy.ops.mesh.primitive_uv_sphere_add(radius=thick * 0.42, location=(x, 0, z), segments=32, ring_count=16)
                    parts.append(bpy.context.active_object)
    bpy.ops.object.select_all(action="DESELECT")
    for p in parts:
        p.select_set(True)
    bpy.context.view_layer.objects.active = parts[0]
    if len(parts) > 1:
        bpy.ops.object.join()
        apply(parts[0], "REMESH", mode="VOXEL", voxel_size=max(thick / 24.0, 0.05))
    obj = parts[0]
    aim(obj, params["center"], params["axis"])
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
elif op == "place_file":
    obj = load(params["source"])
    bpy.ops.object.origin_set(type="ORIGIN_GEOMETRY", center="BOUNDS")
    obj.location = Vector(params["center"])
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
elif op == "add_base":
    lo, hi = params["min"], params["max"]
    height, margin = float(params["height_mm"]), float(params["margin_mm"])
    cx, cy = (lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2
    top = lo[2] + float(params.get("overlap_mm", 0.6))
    if params.get("shape", "round") == "square":
        bpy.ops.mesh.primitive_cube_add(size=1, location=(cx, cy, top - height / 2))
        obj = bpy.context.active_object
        obj.scale = ((hi[0] - lo[0]) + 2 * margin, (hi[1] - lo[1]) + 2 * margin, height)
    else:
        radius = max(hi[0] - lo[0], hi[1] - lo[1]) / 2 + margin
        bpy.ops.mesh.primitive_cylinder_add(radius=radius, depth=height, location=(cx, cy, top - height / 2), vertices=96)
        obj = bpy.context.active_object
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
else:
    obj = load(params["source"])
    if op == "smooth":
        apply(obj, "LAPLACIANSMOOTH", iterations=int(params.get("iterations", 8)), lambda_factor=float(params.get("factor", 0.5)),
              use_volume_preserve=True)
    elif op == "remesh":
        apply(obj, "REMESH", mode="VOXEL", voxel_size=float(params["voxel_mm"]))
    elif op == "decimate":
        apply(obj, "DECIMATE", ratio=float(params["ratio"]))
    elif op == "scale":
        f = float(params["factor"])
        obj.scale = (f, f, f)
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    elif op in ("hollow", "solidify"):
        apply(obj, "SOLIDIFY", thickness=float(params["thickness_mm"]), offset=(-1.0 if op == "hollow" else 0.0), use_even_offset=True)
    elif op == "boolean":
        other = load(params["other"])
        bpy.context.view_layer.objects.active = obj
        mod = obj.modifiers.new(name="cadwiz", type="BOOLEAN")
        mod.operation = params["boolean"].upper()
        mod.solver = "EXACT"
        mod.object = other
        bpy.ops.object.modifier_apply(modifier=mod.name)
        bpy.data.objects.remove(other, do_unlink=True)
    else:
        raise RuntimeError("unknown operation " + op)
bpy.ops.object.select_all(action="DESELECT")
obj.select_set(True)
bpy.context.view_layer.objects.active = obj
bpy.ops.wm.stl_export(filepath=params["output"], export_selected_objects=True)
print("CADWIZ_BLENDER_OK", len(obj.data.polygons))
'''


def run_blender(params: dict[str, Any], pump: Callable[[], None] | None) -> Path:
    blender = find_blender()
    if blender is None:
        raise MeshToolError("Blender is not installed on this computer (looked in Program Files\\Blender Foundation)")
    with tempfile.TemporaryDirectory(prefix="cadwiz-blender-") as work:
        params_path = Path(work) / "params.json"
        params_path.write_text(json.dumps(params), encoding="utf-8")
        result = run_pumped([str(blender), "--background", "--factory-startup", "--python-expr", BLENDER_SCRIPT, "--", str(params_path)], pump)
    output = Path(params["output"])
    if result.returncode != 0 or "CADWIZ_BLENDER_OK" not in result.stdout or not output.is_file():
        tail = (result.stderr or result.stdout).strip().splitlines()[-3:]
        raise MeshToolError("Blender could not do that: " + " | ".join(tail)[:500])
    return output


def run_mesh_job(request: dict[str, Any], pump: Callable[[], None] | None) -> dict[str, Any]:
    python = find_mesh_python()
    if python is None:
        raise MeshToolError("the mesh repair tools (pymeshlab) are not installed in a Python on this computer")
    src = Path(__file__).resolve().parents[2]
    with tempfile.TemporaryDirectory(prefix="cadwiz-meshjob-") as work:
        request_path, result_path = Path(work) / "request.json", Path(work) / "result.json"
        request_path.write_text(json.dumps(request), encoding="utf-8")
        env = dict(os.environ, PYTHONPATH=str(src), PYTHONIOENCODING="utf-8")
        result = run_pumped([str(python), "-m", "integrations.cadwiz_plugin.mesh_job", str(request_path), str(result_path)], pump, env=env)
        if not result_path.is_file():
            raise MeshToolError("the mesh job stopped without an answer: " + (result.stderr.strip().splitlines() or ["no detail"])[-1][:300])
        return json.loads(result_path.read_text(encoding="utf-8"))


# ---- FreeCAD side --------------------------------------------------------------------------------------
def mesh_parts(document: Any) -> list[Any]:
    return [o for o in document.Objects if str(getattr(o, "TypeId", "")) == "Mesh::Feature"]


def part(document: Any, name: str | None) -> Any:
    parts = mesh_parts(document)
    if not parts:
        raise MeshToolError(f"{document.Label} has no mesh parts; import_mesh brings one in")
    if not name:
        # The main body first (imports name it Body), else the largest part -- never
        # a base or a held part by accident (found by eye 2026-10-18).
        body = next((o for o in parts if o.Label == "Body"), None)
        return body or max(parts, key=lambda o: o.Mesh.CountFacets)
    for obj in parts:
        if name in (obj.Name, obj.Label):
            return obj
    raise MeshToolError(f"there is no mesh part called {name!r}; the parts are {', '.join(o.Label for o in parts)}")


def export_part(obj: Any, path: Path) -> Path:
    mesh = obj.Mesh.copy()
    with contextlib.suppress(Exception):
        mesh.transform(obj.Placement.toMatrix())
    mesh.write(str(path))
    return path


def set_part_mesh(obj: Any, path: Path) -> None:
    import FreeCAD
    import Mesh

    obj.Mesh = Mesh.Mesh(str(path))
    obj.Placement = FreeCAD.Placement()


def add_part(document: Any, label: str, path: Path) -> Any:
    import Mesh

    obj = document.addObject("Mesh::Feature", label.replace(" ", "_"))
    obj.Label = label
    obj.Mesh = Mesh.Mesh(str(path))
    return obj


def size_mm(document: Any) -> tuple[float, float, float] | None:
    box = None
    for obj in mesh_parts(document):
        with contextlib.suppress(Exception):
            mesh = obj.Mesh.copy()
            mesh.transform(obj.Placement.toMatrix())
            box = mesh.BoundBox if box is None else box.united(mesh.BoundBox)
    for obj in document.Objects:
        shape = getattr(obj, "Shape", None)
        if str(getattr(obj, "TypeId", "")).startswith("Part::") and shape is not None and not shape.isNull():
            box = shape.BoundBox if box is None else box.united(shape.BoundBox)
    return (box.XLength, box.YLength, box.ZLength) if box is not None else None


def size_words(size: tuple[float, float, float] | None) -> str:
    if size is None:
        return "no size yet"
    return " x ".join(inches_first(v) for v in size)


def region_from(spec: dict[str, Any], marks: list[Any]) -> dict[str, Any]:
    """The region to take out: one of the founder's marks (an arrow or measure
    along the held part, or a circle around it), or a centre, axis, radius and length."""
    if spec.get("mark") is not None:
        number = int(spec["mark"])
        mark = next((m for m in marks if m.number == number), None)
        if mark is None:
            raise MeshToolError(f"there is no mark {number} on this model")
        kind = mark.kind.value
        if kind in ("arrow", "measurement"):
            a, b = mark.anchors[0].point, mark.anchors[1].point
            length = math.dist(a, b)
            if length <= 0:
                raise MeshToolError("that mark has no length")
            axis = tuple((b[i] - a[i]) / length for i in range(3))
            return {"center": [(a[i] + b[i]) / 2 for i in range(3)], "axis": list(axis), "half_length_mm": length / 2 + 0.5,
                    "radius_mm": float(spec.get("radius_mm") or max(1.0, length * 0.18))}
        if kind == "circle":
            centre, rim = mark.anchors[0].point, mark.anchors[1].point
            radius = math.dist(centre, rim)
            return {"center": list(centre), "axis": list(spec.get("axis") or (1.0, 0.0, 0.0)),
                    "half_length_mm": float(spec.get("length_mm") or 2 * radius) / 2, "radius_mm": radius}
        raise MeshToolError("mark the held part with an arrow or measure along it, or a circle around it")
    try:
        axis = [float(c) for c in spec["axis"]]
        norm = math.sqrt(sum(c * c for c in axis)) or 1.0
        return {"center": [float(c) for c in spec["center"]], "axis": [c / norm for c in axis],
                "half_length_mm": float(spec["length_mm"]) / 2, "radius_mm": float(spec["radius_mm"])}
    except (KeyError, TypeError, ValueError):
        raise MeshToolError("say where the held part is: region={'mark': n} or {'center', 'axis', 'radius_mm', 'length_mm'}") from None


def provenance_path(document_file: str | Path) -> Path:
    return Path(document_file).with_suffix(".source.json")


def write_provenance(document_file: str | Path, *, source: str, licence: str, original: str) -> dict[str, Any]:
    reading = read_licence(licence)
    record = {"source": source, "licence": licence or "unknown", "licence_plain": reading.plain, "can_sell": reading.can_sell,
              "original_file": original, "imported_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    provenance_path(document_file).write_text(json.dumps(record, indent=1), encoding="utf-8")
    return record

