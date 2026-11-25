# SPDX-License-Identifier: LGPL-2.1-or-later
"""Native evidence for the existing fact layer; mutation tests use disposable files only."""
from __future__ import annotations

import hashlib
import json
import re

STATUS = "CADWiz_Model_Health"
DIMENSIONS = ("Length", "Length2", "Width", "Height", "Radius", "Diameter", "Depth", "Angle")
REFERENCE_TYPES = ("App::Origin", "App::Line", "App::Plane", "App::Point", "PartDesign::Plane",
                   "PartDesign::Line", "PartDesign::Point", "PartDesign::CoordinateSystem")


def geometric_bounds(shape):
    """Native geometric bounds, independent of the GUI's display triangulation."""
    optimal = getattr(shape, 'optimalBoundingBox', None)
    return optimal(False, False) if callable(optimal) else shape.BoundBox


def shape_signature(obj):
    shape = getattr(obj, "Shape", None)
    if shape is None or shape.isNull():
        return None
    box = geometric_bounds(shape)
    faces = sorted([type(f.Surface).__name__, round(f.Area, 6),
                    *(round(x, 6) for x in f.CenterOfMass)] for f in shape.Faces)
    return [round(float(x), 6) for x in (shape.Volume, shape.Area, box.XMin, box.YMin, box.ZMin,
                                         box.XMax, box.YMax, box.ZMax)] + [len(shape.Solids), len(shape.Faces), len(shape.Edges), faces]


def final_shapes(doc):
    result = {}
    for obj in doc.Objects:
        kind = str(obj.TypeId)
        if kind in ("App::Part", "App::DocumentObjectGroup", "App::LinkGroup") or kind.startswith(("Sketcher::", *REFERENCE_TYPES)):
            continue
        if kind == "PartDesign::Body" or not getattr(obj, "InList", []):
            signature = shape_signature(obj)
            if signature is not None:
                result[obj.Name] = signature
    return result


def broken(doc):
    return [o.Name for o in doc.Objects if set(map(str, getattr(o, "State", []))) & {"Invalid", "Error"}]


def drivers(doc):
    """Only connected aliases, driving sketch dimensions and real feature dimensions."""
    expressions = " ".join(str(expr) for o in doc.Objects for _prop, expr in getattr(o, "ExpressionEngine", []))
    for obj in doc.Objects:
        kind = str(obj.TypeId)
        controlled = {str(prop) for prop, _expr in getattr(obj, "ExpressionEngine", [])}
        if kind.startswith("Spreadsheet::"):
            for cell in obj.getUsedCells():
                alias = obj.getAlias(cell)
                if alias and any(re.search(re.escape(prefix + alias) + r"(?![A-Za-z0-9_])", expressions)
                                 for prefix in (f"{obj.Name}.", f"<<{obj.Label}>>.")):
                    try:
                        value = float(getattr(obj.get(cell), "Value", obj.get(cell)))
                        if value > 0:
                            yield obj, "cell", cell, value, f"{obj.Name}.{alias}"
                    except (ValueError, TypeError):
                        continue
        elif kind.startswith("Sketcher::"):
            for index, constraint in enumerate(obj.Constraints):
                if constraint.Type not in ("Distance", "DistanceX", "DistanceY", "Radius", "Diameter", "Angle"):
                    continue
                if f"Constraints[{index}]" in controlled or f"Constraints.{constraint.Name}" in controlled or not obj.getDriving(index):
                    continue
                datum = obj.getDatum(index)
                if abs(datum.Value) > 0.001:
                    yield obj, "constraint", index, datum, f"{obj.Name}.{constraint.Name or 'dimension_' + str(index)}"
        elif kind.startswith(("PartDesign::", "Part::")) and kind not in ("PartDesign::Body", "PartDesign::Feature", "Part::Feature"):
            for prop in DIMENSIONS:
                if prop not in getattr(obj, "PropertiesList", []) or prop in controlled:
                    continue
                value = getattr(obj, prop)
                scalar = getattr(value, "Value", value)
                if isinstance(scalar, (int, float)) and abs(scalar) > 0.001:
                    yield obj, "property", prop, value, f"{obj.Name}.{prop}"


def signature(doc):
    rows = []
    for obj in doc.Objects:
        if obj.Name == STATUS:
            continue
        rows.append([obj.Name, obj.TypeId, shape_signature(obj),
                     list(getattr(obj, "ExpressionEngine", [])),
                     [str(c) for c in getattr(obj, "Constraints", [])]])
    values = [(label, str(value)) for _obj, _kind, _key, value, label in drivers(doc)]
    return hashlib.sha256(json.dumps([rows, values], sort_keys=True, default=str).encode()).hexdigest()


def native_evidence(doc):
    features = [o for o in doc.Objects if str(o.TypeId).startswith("PartDesign::")
                and str(o.TypeId) not in ("PartDesign::Body", "PartDesign::Feature")
                and not str(o.TypeId).startswith(REFERENCE_TYPES)
                and shape_signature(o) is not None and getattr(o, "OutList", [])]
    sketches = [o for o in doc.Objects if str(o.TypeId).startswith("Sketcher::") and getattr(o, "Constraints", [])]
    bodies = [o for o in doc.Objects if str(o.TypeId) == "PartDesign::Body" and shape_signature(o) is not None]
    fixed_bases = [o for o in doc.Objects if o.TypeId in ("Part::Feature", "PartDesign::Feature") and shape_signature(o) is not None]
    tree = bool(features and sketches and bodies and not fixed_bases and all(getattr(b, "Tip", None) in features for b in bodies)
                and all(doc.getObject(name).TypeId == "PartDesign::Body" for name in final_shapes(doc)) and not broken(doc))
    names = sorted({item[4] for item in drivers(doc)})
    verified = []
    status = doc.getObject(STATUS)
    if status is not None:
        try:
            record = json.loads(status.Verification)
            if record.get("signature") == signature(doc) and record.get("level") == "E3":
                verified = record.get("changed_parameters", [])
        except (ValueError, AttributeError):
            pass
    return {"functional_tree": int(tree), "linked_parameters": len(names),
            "verified_parameters": len(verified), "parameter_names": names,
            "unconstrained_sketches": sum(not bool(getattr(s, "FullyConstrained", False)) for s in sketches),
            "broken": broken(doc), "changed_parameters": verified}


def present(doc, *, created=False, show=False):
    """Clean only CADWiz-owned documents or an explicit recovery action."""
    status = doc.getObject(STATUS)
    if not created and status is None:
        return
    try:
        keep = set(json.loads(getattr(status, "VisibleReferences", "[]"))) if status is not None else set()
    except (TypeError, ValueError):
        keep = set()
    show = bool(show or getattr(status, "ConstructionVisible", False))
    for body in doc.Objects:
        if str(body.TypeId) != "PartDesign::Body":
            continue
        for obj in getattr(body, "Group", []):
            if str(obj.TypeId).startswith("PartDesign::") and not str(obj.TypeId).startswith(REFERENCE_TYPES) and shape_signature(obj) is not None:
                visible = obj == getattr(body, "Tip", None)
                obj.Visibility = visible
                if obj.ViewObject is not None:
                    obj.ViewObject.Visibility = visible
    for obj in doc.Objects:
        kind = str(obj.TypeId)
        reference = kind.startswith(REFERENCE_TYPES) or (kind.startswith("Sketcher::") and bool(getattr(obj, "InList", [])))
        if reference and (show or obj.Name not in keep):
            obj.Visibility = bool(show)
            if obj.ViewObject is not None:
                obj.ViewObject.Visibility = bool(show)


def remember_references(doc):
    status = doc.getObject(STATUS)
    if status is not None and "VisibleReferences" in status.PropertiesList:
        status.VisibleReferences = json.dumps([o.Name for o in doc.Objects
            if (str(o.TypeId).startswith(REFERENCE_TYPES) or str(o.TypeId).startswith("Sketcher::"))
            and bool(getattr(o, "Visibility", False))])


def verify_saved(doc, path, *, owned=False, exception=""):
    """Save/reopen, perturb up to three driving dimensions, discard probes, reopen unchanged."""
    import FreeCAD

    status = doc.getObject(STATUS)
    exception = exception or str(getattr(status, "ConstructionException", ""))
    present(doc, created=owned)
    baseline = final_shapes(doc)
    doc.saveAs(str(path))
    FreeCAD.closeDocument(doc.Name)
    doc = FreeCAD.openDocument(str(path))
    doc.recompute()
    persisted = final_shapes(doc) == baseline and not broken(doc)
    evidence = native_evidence(doc)
    candidates = [(kind, obj.Name, key, label) for obj, kind, key, _value, label in drivers(doc)][:12]
    changed = []
    covered = set()
    if persisted and evidence["functional_tree"]:
        for kind, name, key, label in candidates:
            obj = doc.getObject(name)
            try:
                before = final_shapes(doc)
                unaffected = {k: v for k, v in before.items() if doc.getObject(k) not in getattr(obj, "InListRecursive", []) and k != name}
                if kind == "cell":
                    value = float(getattr(obj.get(key), "Value", obj.get(key)))
                    obj.set(key, str(value * 1.05))
                elif kind == "constraint":
                    obj.setDatum(key, obj.getDatum(key) * 1.05)
                else:
                    setattr(obj, key, getattr(obj, key) * 1.05)
                doc.recompute()
                after = final_shapes(doc)
                valid = bool(after) and all(o.Shape.isValid() for o in doc.Objects if o.Name in after)
                if after != before and set(after) == set(before) and valid and not broken(doc) and all(after[k] == v for k, v in unaffected.items()):
                    changed.append(label)
                    covered.update(k for k in after if after[k] != before[k])
            except Exception:
                pass
            finally:
                # Never save a trial change, even when it broke downstream features.
                FreeCAD.closeDocument(doc.Name)
                doc = FreeCAD.openDocument(str(path))
                doc.recompute()
            if len(changed) >= 3 and covered >= set(baseline):
                break
    restored = final_shapes(doc) == baseline and not broken(doc)
    solid = any(len(doc.getObject(name).Shape.Solids) > 0 for name in final_shapes(doc))
    report = {"roundtrip": bool(persisted and restored), "changed_parameters": changed,
              "functional_tree": evidence["functional_tree"], "exception": exception,
              "verified_components": sorted(covered),
              "level": "E3" if changed and covered >= set(baseline) and evidence["functional_tree"] and not evidence["unconstrained_sketches"] and persisted and restored else "E2" if evidence["functional_tree"] else "E1" if solid else "E0"}
    if owned:
        status = doc.getObject(STATUS) or doc.addObject("App::FeaturePython", STATUS)
        for prop in ("Verification", "Editability", "ConstructionException", "VisibleReferences"):
            if prop not in status.PropertiesList:
                status.addProperty("App::PropertyString", prop, "CADWiz")
        status.Label = "CADWiz model health"
        if "ConstructionVisible" not in status.PropertiesList:
            status.addProperty("App::PropertyBool", "ConstructionVisible", "CADWiz")
        status.Editability = report["level"]
        status.ConstructionException = exception
        if not status.VisibleReferences:
            status.VisibleReferences = "[]"
        status.Verification = json.dumps({**report, "signature": signature(doc)})
        doc.save()
    return doc, report
