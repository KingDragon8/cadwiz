# SPDX-License-Identifier: LGPL-2.1-or-later
"""Deterministic annular edits with whole-solid, native geometry verification.

Supported scope: coaxial circular Sketcher profiles driving a native Pocket or
Pad. Unsupported geometry fails before mutation; no fixed-solid replacement.
"""
from __future__ import annotations
import math

from integrations.cadwiz_plugin.engineering_control import ControlError

TOLERANCE_MM = 0.001
VOLUME_TOLERANCE_MM3 = 0.001


def number(value, name):
    if isinstance(value, bool):
        raise ControlError('USER INPUT REQUIRED', 'Invalid ' + name)
    value = float(value)
    if not math.isfinite(value):
        raise ControlError('USER INPUT REQUIRED', 'Invalid ' + name)
    return value


def circle_parameter(sketch, index, radius):
    import Sketcher
    for i, constraint in enumerate(sketch.Constraints):
        if constraint.First == index and constraint.Type in ('Radius', 'Diameter') and sketch.getDriving(i):
            sketch.setDatum(i, radius * (2 if constraint.Type == 'Diameter' else 1))
            return
    # A valid underconstrained circle can gain a real driving radius without
    # rebuilding the source or pretending its other degrees of freedom are fixed.
    sketch.addConstraint(Sketcher.Constraint('Radius', index, radius))


def coaxial_walls(shape, origin, axis, radii, lo, hi, tolerance=TOLERANCE_MM):
    result = []
    for radius in radii:
        matches = []
        for face in shape.Faces:
            surface = face.Surface
            if type(surface).__name__ != 'Cylinder' or abs(surface.Radius - radius) > tolerance:
                continue
            if abs(abs(surface.Axis.dot(axis)) - 1) > 1e-8 or (surface.Center - origin).cross(axis).Length > tolerance:
                continue
            zs = [(v.Point - origin).dot(axis) for v in face.Vertexes]
            if zs and abs(min(zs) - lo) <= tolerance and abs(max(zs) - hi) <= tolerance:
                matches.append(face)
        if len(matches) != 1:
            raise ControlError('TARGET UNRESOLVED', 'The annular walls are missing or ambiguous; do not infer them from a screenshot.')
        # Radius is measured from the actual resulting cylindrical B-rep face.
        result.append(float(matches[0].Surface.Radius))
    return result


def prepare(document, intent, *, worker_copy=False):
    import FreeCAD as App
    import Part
    from integrations.cadwiz_plugin.engineering_control import resolve_reference, document_revision
    supplied = intent.get('reference') or {}
    if worker_copy:
        obj = document.getObject(supplied.get('object', ''))
        if obj is None or document_revision(document) != supplied.get('revision'):
            raise ControlError('TARGET UNRESOLVED', 'The worker copy does not match the selected document revision.')
        # A saved worker copy has another filename/document name and may have
        # reordered face labels. Rebind only after whole-document revision
        # equality, then require the same placement and a unique geometry match.
        reference = resolve_reference(document, {**supplied, 'document': document.Name, 'file': str(document.FileName)})
    else:
        reference = resolve_reference(document, supplied)
    body = document.getObject(intent.get('body', ''))
    feature = document.getObject(intent.get('feature', ''))
    sketch = document.getObject(intent.get('sketch', ''))
    kind = intent.get('kind')
    expected_type = {'groove': 'PartDesign::Pocket', 'ridge': 'PartDesign::Pad'}.get(kind)
    profile = getattr(feature, 'Profile', None)
    if isinstance(profile, tuple):
        profile = profile[0]
    if (body is None or body.TypeId != 'PartDesign::Body' or feature is None or feature.TypeId != expected_type
            or body.Tip != feature or sketch is None or sketch.TypeId != 'Sketcher::SketchObject'
            or profile != sketch or reference['object'] != body.Name):
        raise ControlError('UNSUPPORTED OPERATION', 'Select a final native annular Pocket or Pad and its connected circular sketch.')
    indices = [int(intent['inner_geometry']), int(intent['outer_geometry'])]
    if indices[0] == indices[1] or any(i < 0 or i >= sketch.GeometryCount for i in indices):
        raise ControlError('TARGET UNRESOLVED', 'Two distinct circular sketch boundaries are required.')
    circles = [sketch.Geometry[i] for i in indices]
    if any(type(c).__name__ != 'Circle' for c in circles) or (circles[0].Center - circles[1].Center).Length > TOLERANCE_MM:
        raise ControlError('UNSUPPORTED OPERATION', 'The boundaries must be concentric complete circles; arcs and chords cannot be substituted.')
    inner, outer = [float(c.Radius) for c in circles]
    if not 0 < inner < outer:
        raise ControlError('TARGET UNRESOLVED', 'Inner and outer boundaries are reversed or invalid.')
    placement = sketch.getGlobalPlacement()
    origin = placement.multVec(circles[0].Center)
    axis = placement.Rotation.multVec(App.Vector(0, 0, 1))
    direction = intent.get('direction')
    amount = number(intent.get('amount_mm', 0), 'amount')
    unit = intent.get('dimension', 'radial')
    if unit not in ('radial', 'diametric') or amount < 0 or direction not in ('inward', 'outward', 'none'):
        raise ControlError('USER INPUT REQUIRED', 'State inward/outward, a nonnegative amount, and radial or diametric units.')
    amount = amount / 2 if unit == 'diametric' else amount
    if direction == 'none' and amount:
        raise ControlError('USER INPUT REQUIRED', 'A nonzero width change needs an explicit direction.')
    new_inner = inner - amount if direction == 'inward' else inner
    new_outer = outer + amount if direction == 'outward' else outer
    if new_inner <= 0:
        raise ControlError('UNSUPPORTED OPERATION', 'The requested change would consume the central opening.')
    depth = float(feature.Length.Value)
    depth_delta = number(intent.get('depth_change_mm', 0), 'depth change')
    if depth + depth_delta <= 0 or (not amount and not depth_delta):
        raise ControlError('USER INPUT REQUIRED', 'The requested dimensions must define a positive depth and an actual change.')
    # Native Pad grows +normal; Pocket removes -normal. Reversed features swap it.
    sense = (1 if kind == 'ridge' else -1) * (-1 if bool(feature.Reversed) else 1)
    if getattr(feature, 'Midplane', False) or str(getattr(feature, 'Type', 'Length')) not in ('0', 'Length'):
        raise ControlError('UNSUPPORTED OPERATION', 'Only one-sided, explicit-length annular features are supported.')
    z0, z1 = sorted((0.0, sense * depth))
    measured = coaxial_walls(body.Shape, origin, axis, [inner, outer], z0, z1)
    selected = body.Shape.getElement(reference['element'])
    geometry = getattr(selected, 'Surface', getattr(selected, 'Curve', None))
    selected_kind = type(geometry).__name__
    selected_radii = []
    if selected_kind == 'Cylinder':
        selected_radii = [geometry.Radius]
        zs = [(v.Point - origin).dot(axis) for v in selected.Vertexes]
        connected = bool(zs) and abs(min(zs)-z0) <= TOLERANCE_MM and abs(max(zs)-z1) <= TOLERANCE_MM
    elif selected_kind == 'Plane':
        circles = [e.Curve for e in selected.Edges if type(e.Curve).__name__ == 'Circle']
        selected_radii = [c.Radius for c in circles]
        connected = len(circles) == len(selected.Edges) == 2 and all((c.Center-origin).cross(axis).Length <= TOLERANCE_MM
            and min(abs((c.Center-origin).dot(axis)-z0),abs((c.Center-origin).dot(axis)-z1)) <= TOLERANCE_MM for c in circles)
    elif selected_kind == 'Circle':
        selected_radii = [geometry.Radius]
        connected = (geometry.Center-origin).cross(axis).Length <= TOLERANCE_MM and min(abs((geometry.Center-origin).dot(axis)-z0),abs((geometry.Center-origin).dot(axis)-z1)) <= TOLERANCE_MM
    else:
        connected = False
    if not connected or not selected_radii or any(min(abs(r-inner),abs(r-outer)) > TOLERANCE_MM for r in selected_radii):
        raise ControlError('TARGET UNRESOLVED', 'The selected geometry does not identify this annular feature; select its wall, circular boundary or annular floor.')
    def tool(r1, r2, length):
        vector = axis * sense
        return Part.makeCylinder(r2, length, origin, vector).cut(Part.makeCylinder(r1, length, origin, vector))
    old_tool, new_tool = tool(inner, outer, depth), tool(new_inner, new_outer, depth + depth_delta)
    baseline = body.Shape.copy()
    # Applying only the changed material region to the original shape independently
    # detects wrong direction, chord substitution, and any unrelated material edit.
    if kind == 'groove':
        expected = baseline.fuse(old_tool.cut(new_tool)).cut(new_tool.cut(old_tool))
    else:
        expected = baseline.cut(old_tool.cut(new_tool)).fuse(new_tool.cut(old_tool))
    return {'body': body, 'body_name': body.Name, 'feature': feature, 'sketch': sketch, 'indices': indices, 'origin': origin, 'axis': axis,
            'before': measured, 'after': [new_inner, new_outer], 'depth': depth, 'new_depth': depth + depth_delta,
            'sense': sense, 'expected': expected, 'baseline': baseline,
            'unrelated': {o.Name: o.Shape.copy() for o in document.Objects if o.TypeId == 'PartDesign::Body' and o != body}}


def verify(document, plan):
    from integrations.ai_master.parametric_checks import broken
    body = document.getObject(plan['body_name'])
    z0, z1 = sorted((0.0, plan['sense'] * plan['new_depth']))
    measured = coaxial_walls(body.Shape, plan['origin'], plan['axis'], plan['after'], z0, z1)
    actual = body.Shape
    if not actual.isValid() or len(actual.Solids) != len(plan['baseline'].Solids) or broken(document):
        raise ControlError('VERIFICATION FAILED', 'The resulting solid or feature history is invalid.')
    error = float(actual.cut(plan['expected']).Volume + plan['expected'].cut(actual).Volume)
    if error > VOLUME_TOLERANCE_MM3:
        raise ControlError('VERIFICATION FAILED', 'The actual solid differs from the authorized change; original geometry was preserved.')
    for name, before in plan['unrelated'].items():
        other = document.getObject(name)
        if other is None or other.Shape.cut(before).Volume + before.cut(other.Shape).Volume > VOLUME_TOLERANCE_MM3:
            raise ControlError('VERIFICATION FAILED', 'An unrelated body changed.')
    return {'inner_radius_change_mm': measured[0] - plan['before'][0], 'outer_radius_change_mm': measured[1] - plan['before'][1],
            'width_change_mm': (measured[1] - measured[0]) - (plan['before'][1] - plan['before'][0]),
            'depth_change_mm': plan['new_depth'] - plan['depth'], 'curvature_preserved': True,
            'whole_solid_difference_mm3': error, 'tolerance_mm': TOLERANCE_MM,
            'volume_tolerance_mm3': VOLUME_TOLERANCE_MM3, 'unrelated_bodies_unchanged': True}


def execute(document, intent, result_path, *, worker_copy=False):
    """Mutate only a worker copy; remeasure the saved/reopened native shape."""
    from integrations.ai_master.parametric_checks import verify_saved, native_evidence
    plan = prepare(document, intent, worker_copy=worker_copy)
    tree = native_evidence(document)['functional_tree']
    # FreeCAD headless documents commonly have undo disabled. Without enabling
    # it, abortTransaction can return normally while leaving the bad edit live.
    previous_undo = int(document.UndoMode)
    if not previous_undo:
        document.UndoMode = 1
    document.openTransaction('Verified annular operation')
    try:
        for index, old, new in zip(plan['indices'], plan['before'], plan['after']):
            if old != new:
                circle_parameter(plan['sketch'], index, new)
        plan['feature'].Length = plan['new_depth']
        document.recompute()
        evidence = verify(document, plan)
        document.commitTransaction()
    except Exception:
        document.abortTransaction()
        document.recompute()
        if not previous_undo:
            document.UndoMode = previous_undo
        raise
    document, health = verify_saved(document, result_path, owned=False)
    if not health['roundtrip'] or (tree and not native_evidence(document)['functional_tree']):
        raise ControlError('VERIFICATION FAILED', 'The saved result did not preserve its native history.')
    evidence['reopened'] = verify(document, plan)
    evidence['save_reopen'] = True
    return document, health, evidence
