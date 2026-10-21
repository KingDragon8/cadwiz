# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Headless worker for the AI-master path: one job per run, in a separate
`freecadcmd.exe` (ORDER-2026-10-11-03, Phase 2 + hard safety envelope).

    freecadcmd.exe worker.py <request.json>

Jobs (request["action"]):
  build        run the design source script in a NEW document under the sandbox,
               recompute, measure (fact layer), render, save the native .FCStd
  render       reopen a saved .FCStd and render the requested views
  living_test  the E4 test: reopen the saved .FCStd, change ONE named parameter
               in the Params spreadsheet, recompute, check the change landed and
               every other parameter and the document stayed intact; nothing saved
  export       reopen the saved .FCStd and write STL / 3MF / STEP / FCStd

Writes request["result_path"] (JSON) and prints CADWIZ_DONE. The founder's own
documents are never opened here: only files inside the project folder.
"""
from __future__ import annotations

import json
import math
import os
import sys
import time
import traceback

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.dirname(os.path.dirname(_HERE))
for _p in (_SRC, os.path.join(_SRC, "integrations", "mcp_tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

#: Triangles a picture may draw in all (matplotlib draws them one by one).
RENDER_TRIANGLES = 8000
VIEWS = {"iso": (24, -55), "front": (0, -90), "back": (0, 90), "right": (0, 0), "left": (0, 180), "top": (90, -90), "bottom": (-90, -90)}
SKIP_TYPES = ("Sketcher::", "Spreadsheet::", "App::Origin", "App::Line", "App::Plane", "App::Point", "PartDesign::CoordinateSystem")


def _top_level(doc):
    """The objects that ARE the design: shapes nothing else consumes."""
    out = []
    for obj in doc.Objects:
        type_id = str(getattr(obj, "TypeId", ""))
        if type_id.startswith(SKIP_TYPES):
            continue
        shape = getattr(obj, "Shape", None)
        try:
            if shape is None or shape.isNull():
                continue
        except Exception:  # noqa: BLE001
            continue
        users = [u for u in getattr(obj, "InList", []) if not str(getattr(u, "TypeId", "")).startswith(("App::Origin", "Spreadsheet::"))]
        if users:
            continue
        out.append(obj)
    return out


def _picture_mesh(shape, budget):
    """Points and triangles for a picture, at most about `budget` triangles.

    A swept surface comes out of FreeCAD's mesher in tens of thousands of
    triangles (a 66 mm tennis ball with a swept seam groove: 68,000), and
    matplotlib draws each one -- three pictures took ~115 s, past Claude's request
    time (ORDER-2026-10-19-03). A coarser tolerance on the SAME shape changes
    nothing (FreeCAD keeps the finer mesh it already made), so a copy without
    the mesh is meshed coarser, then thinned. At 800 x 600 px it looks the same."""
    diagonal = shape.BoundBox.DiagonalLength
    deviation = max(0.2, min(diagonal / 120.0, 3.0))
    points, triangles = shape.tessellate(deviation)
    if len(triangles) <= budget:
        return points, triangles
    try:
        fresh = shape.copy(True, False)
        points, triangles = fresh.tessellate(max(deviation * 8.0, diagonal / 15.0))
    except Exception:  # noqa: BLE001 - the fine mesh still makes a picture
        pass
    if len(triangles) <= budget:
        return points, triangles
    try:
        import Mesh

        mesh = Mesh.Mesh((points, triangles))
        mesh.decimate(diagonal / 50.0, 1.0 - budget / float(len(triangles)))
        return [p.Vector for p in mesh.Points], [tuple(f.PointIndices) for f in mesh.Facets]
    except Exception:  # noqa: BLE001
        return points, triangles


def _render(doc, objects, path, views, section, size=(800, 600)):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection
    import numpy as np

    written = []
    shapes = []
    for obj in objects:
        shape = obj.Shape
        if section:
            import Part
            box = shape.BoundBox
            half = Part.makeBox(box.XLength + 2, box.YLength / 2 + 1, box.ZLength + 2,
                                __import__("FreeCAD").Vector(box.XMin - 1, box.YMin - 1, box.ZMin - 1))
            try:
                shape = shape.cut(half)
            except Exception:  # noqa: BLE001
                pass
        shapes.append(shape)
    tris_all = []
    budget = RENDER_TRIANGLES // max(1, len(shapes))
    for shape in shapes:
        points, triangles = _picture_mesh(shape, budget)
        pts = np.array([[p.x, p.y, p.z] for p in points])
        if len(triangles):
            tris_all.append(pts[np.array(triangles)])
    if not tris_all:
        return written
    tris = np.concatenate(tris_all)
    normals = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    norms = np.linalg.norm(normals, axis=1)
    norms[norms == 0] = 1
    normals = normals / norms[:, None]
    lo, hi = tris.reshape(-1, 3).min(axis=0), tris.reshape(-1, 3).max(axis=0)
    centre, span = (lo + hi) / 2, max(hi - lo) / 2 or 1
    base, ext = os.path.splitext(path)
    for view in views:
        elev, azim = VIEWS.get(view, VIEWS["iso"])
        e, a = np.radians(elev), np.radians(azim)
        eye = np.array([np.cos(e) * np.cos(a), np.cos(e) * np.sin(a), np.sin(e)])
        light = eye * 0.6 + np.array([0.2, 0.3, 0.7])
        light /= np.linalg.norm(light)
        shade = np.clip(np.abs(normals @ light), 0.15, 1.0)
        colours = np.column_stack([0.23 + 0.55 * shade, 0.42 + 0.45 * shade, 0.85 * shade + 0.1, np.ones_like(shade)])
        fig = plt.figure(figsize=(size[0] / 100, size[1] / 100), dpi=100)
        ax = fig.add_subplot(111, projection="3d")
        ax.add_collection3d(Poly3DCollection(tris, facecolors=colours, edgecolors="none"))
        ax.set_xlim(centre[0] - span, centre[0] + span)
        ax.set_ylim(centre[1] - span, centre[1] + span)
        ax.set_zlim(centre[2] - span, centre[2] + span)
        ax.set_box_aspect((1, 1, 1))
        ax.view_init(elev=elev, azim=azim)
        ax.set_axis_off()
        fig.patch.set_facecolor("white")
        out = path if len(views) == 1 else f"{base}_{view}{'_section' if section else ''}{ext}"
        fig.savefig(out, bbox_inches="tight", pad_inches=0.05, facecolor="white")
        plt.close(fig)
        written.append(out)
    return written


def _measure(doc, request):
    from ai_freecad_core.ai_master.design_contract import DesignContract
    from ai_freecad_core.ai_master.fact_layer import PrinterProfile
    from integrations.ai_master.freecad_facts import measure_document, steep_overhang_note

    objects = _top_level(doc)
    contract = DesignContract.from_dict(request["contract"]) if request.get("contract") else None
    printer = PrinterProfile(**request["printer"]) if request.get("printer") else PrinterProfile()
    facts = measure_document(doc, object_name=request.get("object_name", ""), subject_names=[o.Name for o in objects] or None,
                             contract=contract, printer=None, living_design_verified=bool(request.get("living_design_verified")))
    for obj in objects:
        note = steep_overhang_note(obj.Shape, printer.max_overhang_deg)
        if note:
            facts.notes.append(note)
    from ai_freecad_core.ai_master.fact_layer import finish_report
    finish_report(facts, contract, printer)
    return facts, objects


def _job_build(request, record):
    import FreeCAD
    import cadwiz_sandbox
    # Everything CADWiz needs AFTER the script is imported BEFORE the process
    # is hardened: the core package's import chain touches socket/ssl, which the
    # hardening replaces.
    import ai_freecad_core.ai_master.fact_layer  # noqa: F401
    import integrations.ai_master.freecad_facts  # noqa: F401
    import matplotlib  # noqa: F401
    matplotlib.use("Agg")
    import matplotlib.pyplot  # noqa: F401
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection  # noqa: F401

    doc = FreeCAD.newDocument("CADWizBuild")
    FreeCAD.setActiveDocument(doc.Name)
    policy = cadwiz_sandbox.SandboxPolicy(request["project_dir"])
    record["sandbox"] = cadwiz_sandbox.describe_limits(request.get("time_limit_s", 60), request.get("memory_limit_bytes", 2 * 1024 ** 3))
    namespace = cadwiz_sandbox.make_sandbox_globals(policy, {"FreeCAD": FreeCAD, "App": FreeCAD})
    hardened = cadwiz_sandbox.harden_process(policy)
    record["hardened"] = hardened
    try:
        code = compile(request["script"], "<design source>", "exec")
        exec(code, namespace)  # noqa: S102 - the master's design source, inside the envelope
    except Exception as error:  # noqa: BLE001 - the exact error and line go back to the master
        tb = traceback.extract_tb(sys.exc_info()[2])
        line = next((f.lineno for f in reversed(tb) if f.filename == "<design source>"), None)
        if isinstance(error, SyntaxError):
            line = error.lineno
        record.update(ok=False, error=f"{type(error).__name__}: {error}", error_line=line)
        return
    doc.recompute()
    broken = [o.Label for o in doc.Objects if set(map(str, getattr(o, "State", []) or [])) & {"Invalid", "Error"}]
    facts, objects = _measure(doc, request)
    if not objects:
        record.update(ok=False, error="the script ran but produced no shape", error_line=None, facts=facts.to_dict())
        return
    doc.saveAs(request["native_out"])
    renders = _render(doc, objects, request["render_out"], request.get("views") or ["iso"], False) if request.get("render_out") else []
    record.update(ok=not broken, error=("objects in error: " + ", ".join(broken)) if broken else "", error_line=None,
                  facts=facts.to_dict(), native_path=request["native_out"], renders=renders, top_level=[o.Label for o in objects])


def _open(path):
    return _open_any(path)[0]


def _job_render(request, record):
    doc = _open(request["native_path"])
    objects = _top_level(doc)
    record.update(ok=True, renders=_render(doc, objects, request["render_out"], request.get("views") or ["iso"], bool(request.get("section"))))


def _params_sheet(doc):
    for obj in doc.Objects:
        if str(obj.TypeId).startswith("Spreadsheet::"):
            return obj
    return None


def _job_living_test(request, record):
    """E4: reopen, change one named parameter, others intact. Nothing saved."""
    doc = _open(request["native_path"])
    sheet = _params_sheet(doc)
    if sheet is None:
        record.update(ok=True, verified=False, evidence="no Params spreadsheet: parameters do not drive the features")
        return
    aliases = {}
    for row in range(1, 200):
        cell = f"B{row}"
        alias = sheet.getAlias(cell)
        if alias:
            aliases[alias] = cell
    if not aliases:
        record.update(ok=True, verified=False, evidence="the spreadsheet has no named parameters")
        return
    wanted = [n for n in request.get("commitments") or [] if n in aliases] or sorted(aliases)
    name = wanted[0]
    before_values = {k: float(sheet.get(k).Value if hasattr(sheet.get(k), "Value") else sheet.get(k)) for k in aliases}
    objects = _top_level(doc)
    box0 = objects[0].Shape.BoundBox if objects else None
    vol0 = sum(o.Shape.Volume for o in objects)
    new_value = before_values[name] * 1.1
    sheet.set(aliases[name], f"{new_value} mm")
    doc.recompute()
    broken = [o.Label for o in doc.Objects if set(map(str, getattr(o, "State", []) or [])) & {"Invalid", "Error"}]
    after_values = {k: float(sheet.get(k).Value if hasattr(sheet.get(k), "Value") else sheet.get(k)) for k in aliases}
    others_intact = all(abs(after_values[k] - before_values[k]) < 1e-9 for k in aliases if k != name)
    objects = _top_level(doc)
    vol1 = sum(o.Shape.Volume for o in objects)
    box1 = objects[0].Shape.BoundBox if objects else None
    changed = abs(vol1 - vol0) > 1e-6 or (box0 is not None and box1 is not None and abs(box1.DiagonalLength - box0.DiagonalLength) > 1e-6)
    valid = all(o.Shape.isValid() for o in objects) and not broken
    verified = bool(changed and valid and others_intact)
    record.update(ok=True, verified=verified, parameter=name, before=before_values[name], after=new_value,
                  evidence=(f"changed {name} {before_values[name]:g} -> {new_value:g} mm in the reopened file: shape "
                            f"{'changed' if changed else 'did NOT change'}, {'valid' if valid else 'INVALID'}, other parameters "
                            f"{'intact' if others_intact else 'CHANGED'}"))


def _job_export(request, record):
    doc = _open(request["native_path"])
    objects = _top_level(doc)
    fmt = request["format"].lower()
    out = request["export_path"]
    if fmt in ("stl", "3mf"):
        import Mesh
        Mesh.export(objects, out)
    elif fmt == "step":
        import Part
        Part.export(objects, out)
    elif fmt == "fcstd":
        doc.saveCopy(out)
    else:
        record.update(ok=False, error=f"unknown format {fmt}")
        return
    record.update(ok=os.path.exists(out), path=out, bytes=os.path.getsize(out) if os.path.exists(out) else 0)


# ---- existing models (ORDER-2026-10-12-01) -------------------------------------


def _open_any(path):
    """Open an FCStd, or import an STL/OBJ/STEP/IGES into a new document (the
    adopt path for downloaded models). Returns (doc, kind)."""
    import FreeCAD

    lowered = path.lower()
    if lowered.endswith(".fcstd"):
        doc = FreeCAD.openDocument(path)
        doc.recompute()
        return doc, "fcstd"
    doc = FreeCAD.newDocument("Adopted")
    name = os.path.splitext(os.path.basename(path))[0]
    if lowered.endswith((".stl", ".obj", ".3mf", ".ply")):
        import Mesh
        mesh = Mesh.Mesh(path)
        obj = doc.addObject("Mesh::Feature", name)
        obj.Mesh = mesh
        doc.recompute()
        return doc, "mesh"
    import Part
    shape = Part.read(path)
    obj = doc.addObject("Part::Feature", name)
    obj.Shape = shape
    doc.recompute()
    return doc, "brep"


def _named_parameters(doc):
    """Every value the founder could recognise and change: spreadsheet aliases,
    named sketch constraints, and the main length/angle properties of features."""
    params = []
    for obj in doc.Objects:
        type_id = str(obj.TypeId)
        if type_id.startswith("Spreadsheet::"):
            try:
                for cell in obj.getUsedCells():
                    alias = obj.getAlias(cell)
                    if alias:
                        value = obj.get(cell)
                        params.append({"name": alias, "where": f"{obj.Name}.{alias}", "value": float(getattr(value, "Value", value)), "unit": "mm"})
            except Exception:  # noqa: BLE001
                pass
        elif type_id.startswith("Sketcher::"):
            for index, constraint in enumerate(getattr(obj, "Constraints", []) or []):
                if constraint.Name and constraint.Type in ("Distance", "DistanceX", "DistanceY", "Radius", "Diameter", "Angle"):
                    unit = "deg" if constraint.Type == "Angle" else "mm"
                    value = constraint.Value if unit == "mm" else math.degrees(constraint.Value)
                    params.append({"name": constraint.Name, "where": f"{obj.Name}.Constraints.{constraint.Name}", "value": round(value, 4), "unit": unit})
        elif type_id.startswith(("PartDesign::", "Part::")):
            for prop in ("Length", "Length2", "Radius", "Radius1", "Radius2", "Height", "Width", "Value", "Angle", "Offset", "Size", "Depth"):
                if prop in obj.PropertiesList:
                    raw = getattr(obj, prop)
                    value = float(getattr(raw, "Value", raw)) if isinstance(getattr(raw, "Value", raw), (int, float)) else None
                    if value is not None:
                        params.append({"name": f"{obj.Label}.{prop}", "where": f"{obj.Name}.{prop}", "value": round(value, 4), "unit": "deg" if "Angle" in prop else "mm"})
    return params


def _tree(doc):
    rows = []
    for obj in doc.Objects:
        type_id = str(obj.TypeId)
        if type_id.startswith(("App::Origin", "App::Line", "App::Plane")):
            continue
        row = {"name": obj.Name, "label": obj.Label, "type": type_id, "visible": bool(getattr(obj, "Visibility", True))}
        try:
            placement = obj.Placement
            row["placement"] = [round(placement.Base.x, 3), round(placement.Base.y, 3), round(placement.Base.z, 3)]
        except Exception:  # noqa: BLE001
            pass
        if type_id.startswith("Sketcher::"):
            row["constraints"] = len(getattr(obj, "Constraints", []) or [])
        rows.append(row)
    return rows


def _tight(shape):
    from integrations.ai_master.shape_box import tight_box

    return tight_box(shape)


def _loops_at(shape, z):
    import FreeCAD
    import Part

    box = _tight(shape)
    plane = Part.makePlane(box.XLength + 40, box.YLength + 40, FreeCAD.Vector(box.XMin - 20, box.YMin - 20, z))
    section = shape.section(plane)
    wires = []
    for edges in Part.sortEdges(section.Edges):
        wire = Part.Wire(edges)
        if wire.isClosed():
            wires.append(wire)
    wires.sort(key=lambda w: -w.Length)
    loops = []
    for index, wire in enumerate(wires):
        bb = wire.BoundBox
        loop = {"perimeter_mm": round(wire.Length, 2), "width_mm": round(bb.XLength, 2), "depth_mm": round(bb.YLength, 2),
                "centre": [round(bb.Center.x, 2), round(bb.Center.y, 2)], "equivalent_diameter_mm": round(wire.Length / math.pi, 2)}
        # The true shortest distance to the next loop inward: a wall, or the gap
        # between two walls (ORDER-2026-10-12-02; bounding-box differences
        # mis-read walls whose loops are not centred on each other).
        # Sampled, not exact: an exact distance between two spline loops took
        # over a minute on the founder's helmet. 240 points on this loop against
        # 2400 on the next is accurate to a few hundredths of a millimetre.
        if index + 1 < len(wires) and wires[index + 1].Length >= 0.15 * wires[0].Length:
            try:
                import numpy as np

                outer = np.array([[p.x, p.y] for p in wire.discretize(Number=240)])
                inner = np.array([[p.x, p.y] for p in wires[index + 1].discretize(Number=2400)])
                nearest = np.sqrt(((outer[:, None, :] - inner[None, :, :]) ** 2).sum(axis=2)).min(axis=1)
                loop["to_next_loop_mm"] = round(float(np.median(nearest)), 3)
                loop["to_next_loop_min_mm"] = round(float(nearest.min()), 3)
            except Exception:  # noqa: BLE001
                pass
        loops.append(loop)
    return loops


def _bottom_opening(shape, facts):
    """The bottom opening of a shell (a helmet, a cup). A model measured as solid
    throughout has none to find: the scan cuts it every half millimetre from the
    bottom up -- about 50 s on a tennis ball with a swept seam, which then read
    the seam groove as an "opening" (ORDER-2026-10-19-03)."""
    if getattr(facts, "hollow", None) is False:
        return {"which": "bottom", "note": "solid throughout: no opening to measure"}
    return _opening(shape, "bottom")


def _opening(shape, which="bottom", step=0.5):
    """The opening at the bottom (or top): the innermost closed loop of the first
    horizontal section that cuts the walls, plus the wall thicknesses there.
    Loops under 15% of the largest perimeter (ports, small holes) are listed
    separately and are not the opening."""
    box = _tight(shape)
    heights = [box.ZMin + step * i for i in range(1, int(box.ZLength / step))]
    if which == "top":
        heights = list(reversed(heights))
    for z in heights:
        loops = _loops_at(shape, z)
        big = [l for l in loops if loops and l["perimeter_mm"] >= 0.15 * loops[0]["perimeter_mm"]]
        if len(big) >= 2:
            z_used = round(z + (step if which == "bottom" else -step), 3)
            loops = _loops_at(shape, z_used) or loops
            big = [l for l in loops if l["perimeter_mm"] >= 0.15 * loops[0]["perimeter_mm"]]
            small = [l for l in loops if l not in big]
            inner = big[-1]
            walls = [round((big[i]["width_mm"] - big[i + 1]["width_mm"]) / 2, 2) for i in range(0, len(big) - 1, 2)]
            return {"which": which, "height_mm": z_used, "inside": inner, "loops": big, "wall_thickness_mm_by_width": walls,
                    "small_openings": [{"diameter_mm": round(l["equivalent_diameter_mm"], 2), "centre": l["centre"]} for l in small]}
    return {"which": which, "error": "no horizontal section through the walls was found"}


def _main_shape(doc):
    objs = [o for o in _top_level(doc) if getattr(o, "Visibility", True)] or _top_level(doc)
    if not objs:
        return None, []
    objs.sort(key=lambda o: -o.Shape.BoundBox.DiagonalLength)
    return objs[0], objs


def _job_adopt(request, record):
    import FreeCAD

    path = request["source_path"]
    doc, kind = _open_any(path)
    if kind != "fcstd" and request.get("save_as"):
        doc.saveAs(request["save_as"])
    main, objects = _main_shape(doc)
    record["kind"] = kind
    record["document"] = doc.Label
    record["construction"] = _construction(doc)
    record["tree"] = _tree(doc)
    record["parameters"] = _named_parameters(doc)
    if main is None:
        # An empty document is fine to adopt (ORDER-2026-10-12-05: Claude builds a new
        # part into a fresh document); there is just nothing to measure yet.
        record.update(ok=True, note="no solid shape yet: a mesh (E0) or an empty document")
        return
    facts, _ = _measure(doc, request)
    record["facts"] = facts.to_dict()
    record["main_object"] = main.Label
    record["objects"] = [{"label": o.Label, "visible": bool(o.Visibility), "bbox_mm": [round(_tight(o.Shape).XLength, 2), round(_tight(o.Shape).YLength, 2), round(_tight(o.Shape).ZLength, 2)],
                          "volume_mm3": round(o.Shape.Volume, 2), "solids": len(o.Shape.Solids)} for o in objects]
    try:
        record["bottom_opening"] = _bottom_opening(main.Shape, facts)
    except Exception as error:  # noqa: BLE001
        record["bottom_opening"] = {"error": str(error)}
    visible = [o for o in objects if getattr(o, "Visibility", True)] or objects
    renders = []
    if request.get("render_out"):
        renders = _render(doc, visible, request["render_out"], request.get("views") or ["iso", "front", "top"], False)
    record.update(ok=True, renders=renders)


def _construction(doc):
    """How the main model was built, when CADWiz can edit it at that level
    (ORDER-2026-10-12-04: a lofted ring body is reshaped by its rings)."""
    try:
        from integrations.ai_master import lofted_rings

        for obj in sorted(_top_level(doc), key=lambda o: -_tight(o.Shape).DiagonalLength):
            found = lofted_rings.detect(obj)
            if found:
                return found
    except Exception as error:  # noqa: BLE001 - a fact we could not read is said, not guessed
        return {"kind": "unknown", "note": f"could not read how it was built: {type(error).__name__}"}
    return {"kind": "solid or parametric model"}


def _progress(request):
    """Progress lines for the founder's screen, written as the job runs."""
    path = request.get("progress_path")

    def say(text):
        if not path:
            return
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(text.replace("\n", " ") + "\n")

    return say


def _job_reshape_rings(request, record):
    from integrations.ai_master import lofted_rings

    say = _progress(request)
    doc, _ = _open_any(request["source_path"])
    main, objects = _main_shape(doc)
    shell = next((o for o in objects if lofted_rings.detect(o)), None)
    if shell is None:
        record.update(ok=False, error="the open model is not a lofted ring body, so it cannot be reshaped by its rings; use edit_existing")
        return
    chamber = next((o for o in doc.Objects if o is not shell and "chamber" in (o.Label + o.Name).lower() and getattr(o, "Shape", None) is not None
                    and not o.Shape.isNull() and "cutaway" not in (o.Label + o.Name).lower()), None)
    cutaways = [o for o in doc.Objects if "cutaway" in (o.Label + o.Name).lower() and getattr(o, "Shape", None) is not None and not o.Shape.isNull()]
    say("Measuring the shell before the change")
    before = lofted_rings.measure(shell)
    record["reshape"] = lofted_rings.reshape(shell, float(request["inner_bottom_circumference_mm"]), chamber_obj=chamber, cutaways=cutaways, progress=say)
    doc.recompute()
    say("Checking thickness, height and the top opening")
    after = lofted_rings.measure(shell)
    if not shell.Shape.isValid():
        record.update(ok=False, error="the reshaped shell is not a valid solid")
        return
    doc.saveAs(request["result_path_fcstd"])
    facts, _ = _measure(doc, request)
    record.update(ok=True, before=before, after=after, facts=facts.to_dict(), bottom_opening=_opening(shell.Shape, "bottom"),
                  renders=_render(doc, [o for o in objects if getattr(o, "Visibility", True)] or objects, request["render_out"], ["iso"], False) if request.get("render_out") else [])


def _job_section(request, record):
    doc, _kind = _open_any(request["source_path"])
    main, objects = _main_shape(doc)
    target = next((o for o in objects if o.Label == request.get("object")), main) if objects else None
    if target is None:
        record.update(ok=False, error="no shape to measure")
        return
    if request.get("opening"):
        record.update(ok=True, object=target.Label, result=_opening(target.Shape, request["opening"]))
    else:
        z = float(request.get("height_mm", 0.0))
        record.update(ok=True, object=target.Label, result={"height_mm": z, "loops": _loops_at(target.Shape, z)})


def _set_parameter(doc, where, value_mm):
    parts = where.split(".")
    obj = doc.getObject(parts[0])
    if obj is None:
        raise KeyError(f"no object {parts[0]}")
    if str(obj.TypeId).startswith("Spreadsheet::"):
        cell = obj.getCellFromAlias(parts[1])
        obj.set(cell, f"{value_mm} mm")
    elif len(parts) == 3 and parts[1] == "Constraints":
        index = [c.Name for c in obj.Constraints].index(parts[2])
        import FreeCAD
        obj.setDatum(index, FreeCAD.Units.Quantity(f"{value_mm} mm"))
    else:
        setattr(obj, parts[1], value_mm)


def _job_set_parameters(request, record):
    doc, _ = _open_any(request["source_path"])
    for where, value in request["changes"].items():
        _set_parameter(doc, where, float(value))
    doc.recompute()
    broken = [o.Label for o in doc.Objects if set(map(str, getattr(o, "State", []) or [])) & {"Invalid", "Error"}]
    if broken:
        record.update(ok=False, error="the model broke after the change: " + ", ".join(broken))
        return
    doc.saveAs(request["result_path_fcstd"])
    facts, _ = _measure(doc, request)
    record.update(ok=True, facts=facts.to_dict(), parameters=_named_parameters(doc))


def _job_edit_existing(request, record):
    import FreeCAD
    import cadwiz_sandbox
    import ai_freecad_core.ai_master.fact_layer  # noqa: F401  (before hardening)
    import integrations.ai_master.freecad_facts  # noqa: F401
    import matplotlib  # noqa: F401
    matplotlib.use("Agg")
    import matplotlib.pyplot  # noqa: F401
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection  # noqa: F401
    import Part  # noqa: F401

    doc, _ = _open_any(request["source_path"])
    FreeCAD.setActiveDocument(doc.Name)
    policy = cadwiz_sandbox.SandboxPolicy(request["project_dir"])
    namespace = cadwiz_sandbox.make_sandbox_globals(policy, {"FreeCAD": FreeCAD, "App": FreeCAD, "doc": doc})
    record["hardened"] = cadwiz_sandbox.harden_process(policy)
    try:
        exec(compile(request["script"], "<edit script>", "exec"), namespace)  # noqa: S102 - the master's edit, inside the envelope
    except Exception as error:  # noqa: BLE001
        tb = traceback.extract_tb(sys.exc_info()[2])
        line = next((f.lineno for f in reversed(tb) if f.filename == "<edit script>"), None)
        record.update(ok=False, error=f"{type(error).__name__}: {error}", error_line=getattr(error, "lineno", None) if isinstance(error, SyntaxError) else line)
        return
    doc.recompute()
    broken = [o.Label for o in doc.Objects if set(map(str, getattr(o, "State", []) or [])) & {"Invalid", "Error"}]
    main, objects = _main_shape(doc)
    if main is None or not main.Shape.isValid():
        record.update(ok=False, error="the edit left no valid shape")
        return
    if broken:
        record.update(ok=False, error="objects in error after the edit: " + ", ".join(broken))
        return
    doc.saveAs(request["result_path_fcstd"])
    facts, _ = _measure(doc, request)
    record.update(ok=True, facts=facts.to_dict(), bottom_opening=_bottom_opening(main.Shape, facts),
                  renders=_render(doc, [o for o in objects if getattr(o, "Visibility", True)] or objects, request["render_out"], ["iso"], False) if request.get("render_out") else [])


def main() -> int:
    request_path = sys.argv[-1]
    with open(request_path, encoding="utf-8") as handle:
        request = json.load(handle)
    record = {"ok": False, "action": request.get("action"), "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    started = time.perf_counter()
    try:
        {"build": _job_build, "render": _job_render, "living_test": _job_living_test, "export": _job_export, "adopt": _job_adopt,
         "section": _job_section, "set_parameters": _job_set_parameters, "edit_existing": _job_edit_existing,
         "reshape_rings": _job_reshape_rings}[request["action"]](request, record)
    except Exception as error:  # noqa: BLE001
        record.update(ok=False, error=f"{type(error).__name__}: {error}", worker_traceback=traceback.format_exc())
    record["seconds"] = round(time.perf_counter() - started, 2)
    with open(request["result_path"], "w", encoding="utf-8") as handle:
        json.dump(record, handle, default=str)
    sys.stdout.write("CADWIZ_DONE\n")
    sys.stdout.flush()
    return 0


main()
