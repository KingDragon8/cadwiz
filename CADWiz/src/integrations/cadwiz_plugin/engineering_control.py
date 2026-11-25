# SPDX-License-Identifier: LGPL-2.1-or-later
"""Provider-independent document authority and measured geometry references.

This module never executes model-generated code. FreeCAD is the geometry authority.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
import json
from pathlib import Path
import time
import io
import zipfile


class ControlError(ValueError):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def file_hash(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def document_revision(document):
    from integrations.ai_master.parametric_checks import signature
    return signature(document)


def geometry_signature(properties):
    """Canonical numeric identity without signed-zero noise.

    Kernel save/reopen can perturb floating values below its own tolerance.
    Preserve exact topology/type checks and keep identity much stricter than
    the independent operation's 0.001 mm dimensional verification.
    """
    def normalized(value):
        if isinstance(value, float):
            if not math.isfinite(value):
                raise ControlError('TARGET UNRESOLVED', 'The selected geometry has invalid measurements.')
            rounded = round(value, 9)
            return 0.0 if rounded == 0 else rounded
        if isinstance(value, dict):
            return {key: normalized(item) for key, item in value.items()}
        if isinstance(value, (tuple, list)):
            return [normalized(item) for item in value]
        return value
    return hashlib.sha256(json.dumps(normalized(properties), sort_keys=True).encode()).hexdigest()


def geometry_matches(current, expected):
    """Allow kernel serialization noise, never a changed type or missing field."""
    if isinstance(current, dict) and isinstance(expected, dict):
        return set(current) == set(expected) and all(geometry_matches(current[k], expected[k]) for k in current)
    if isinstance(current, (list, tuple)) and isinstance(expected, (list, tuple)):
        return len(current) == len(expected) and all(geometry_matches(a, b) for a, b in zip(current, expected))
    if isinstance(current, (float, int)) and isinstance(expected, (float, int)):
        return math.isfinite(current) and math.isfinite(expected) and math.isclose(current, expected, rel_tol=1e-10, abs_tol=1e-8)
    return type(current) is type(expected) and current == expected


def live_state_fingerprint(document):
    """Hash all persisted object properties and presentation, ignoring ZIP dates.

    Geometry revision remains the compact reference identity; this stronger
    fingerprint prevents overwriting newer labels, properties or view styling.
    """
    result = hashlib.sha256()
    def add(value):
        if value is None:
            result.update(b'none');return
        method = getattr(value, 'dumpContent', None)
        if callable(method):
            with zipfile.ZipFile(io.BytesIO(bytes(method()))) as archive:
                for name in sorted(archive.namelist()):
                    result.update(name.encode());result.update(archive.read(name))
        else:
            for name in sorted(getattr(value, 'PropertiesList', [])):
                result.update(name.encode());result.update(str(value.getPropertyByName(name)).encode())
    for name in sorted(getattr(document, 'PropertiesList', [])):
        result.update(name.encode());result.update(str(document.getPropertyByName(name)).encode())
    for obj in sorted(document.Objects, key=lambda item:item.Name):
        result.update(obj.Name.encode());add(obj);add(getattr(obj, 'ViewObject', None))
    return result.hexdigest()


@dataclass
class DocumentAuthority:
    mode: str
    target_path: str
    target_name: str
    source_path: str = ''
    source_sha256: str = ''
    source_name: str = ''
    source_revision: str = ''

    def check(self, app, target):
        if self.mode == 'inspect':
            raise ControlError('USER INPUT REQUIRED', 'This operation is read-only. Authorize an edit or create a variant first.')
        actual = str(getattr(target, 'FileName', '') or '')
        if not actual or Path(actual).resolve() != Path(self.target_path).resolve():
            raise ControlError('TARGET UNRESOLVED', 'The edit target is protected. Use the authorized working document: ' + self.target_name)
        self.check_source(app)

    def check_source(self, app):
        if not self.source_path:
            return
        if file_hash(self.source_path) != self.source_sha256:
            raise ControlError('VERIFICATION FAILED', 'The original source file changed. Stop and inspect it before continuing.')
        for document in app.listDocuments().values():
            path = str(getattr(document, 'FileName', '') or '')
            if path and Path(path).resolve() == Path(self.source_path).resolve() and live_state_fingerprint(document) != self.source_revision:
                raise ControlError('VERIFICATION FAILED', 'The original open source document changed. Its working state must be reviewed.')

    def record(self):
        return {'mode': self.mode, 'source': self.source_path, 'working_file': self.target_path,
                'working_document': self.target_name, 'source_sha256': self.source_sha256}


def geometry_reference(document, obj, element):
    """Record actual geometry, not the meaning guessed from a picture."""
    if not element.startswith(('Face', 'Edge', 'Vertex')):
        raise ControlError('TARGET UNRESOLVED', 'Select an actual face, edge or vertex.')
    shape = obj.Shape.getElement(element)
    center = getattr(shape, 'CenterOfMass', None)
    geometry = getattr(shape, 'Surface', getattr(shape, 'Curve', None))
    from integrations.ai_master.parametric_checks import geometric_bounds
    box = geometric_bounds(shape)
    properties = {'kind': type(geometry).__name__, 'area': float(getattr(shape, 'Area', 0)),
                  'length': float(getattr(shape, 'Length', 0)),
                  'center': list(center) if center is not None else None,
                  'bounds': [box.XMin, box.YMin, box.ZMin, box.XMax, box.YMax, box.ZMax]}
    for name in ('Radius', 'MajorRadius', 'MinorRadius'):
        if geometry is not None and hasattr(geometry, name):
            properties[name] = float(getattr(geometry, name))
    for name in ('Axis', 'Center'):
        if geometry is not None and hasattr(geometry, name):
            properties[name.lower()] = list(getattr(geometry, name))
    if element.startswith('Face'):
        try:
            u0, u1, v0, v1 = shape.ParameterRange
            properties['normal'] = list(shape.normalAt((u0 + u1) / 2, (v0 + v1) / 2))
        except (AttributeError, RuntimeError):
            pass
    return {'document': document.Name, 'file': str(document.FileName), 'revision': document_revision(document),
            'object': obj.Name, 'body': next((o.Name for o in getattr(obj, 'InList', []) if o.TypeId == 'PartDesign::Body'), None),
            'feature': obj.Name, 'element': element, 'geometry': properties,
            'placement': str(obj.Placement), 'signature': geometry_signature(properties),
            'timestamp': time.time(), 'resolution': 'GEOMETRY RESOLVED'}


def resolve_reference(document, reference):
    if document.Name != reference.get('document') or str(document.FileName) != reference.get('file'):
        raise ControlError('TARGET UNRESOLVED', 'The selected geometry belongs to a different document.')
    obj = document.getObject(reference.get('object', ''))
    if obj is None or str(obj.Placement) != reference.get('placement'):
        raise ControlError('TARGET UNRESOLVED', 'The selected object or its coordinate system changed; select it again.')
    if document_revision(document) == reference.get('revision'):
        current = geometry_reference(document, obj, reference['element'])
        if current['signature'] == reference.get('signature') or geometry_matches(current['geometry'], reference.get('geometry')):
            return current
    # A topological name alone is never trusted after recomputation. Re-resolve
    # only a unique exact geometric match; changed geometry needs a new selection.
    prefix = 'Face' if reference['element'].startswith('Face') else 'Edge' if reference['element'].startswith('Edge') else 'Vertex'
    shapes = getattr(obj.Shape, {'Face': 'Faces', 'Edge': 'Edges', 'Vertex': 'Vertexes'}[prefix])
    matches = [geometry_reference(document, obj, prefix + str(i + 1)) for i in range(len(shapes))]
    matches = [item for item in matches if item['signature'] == reference.get('signature') or geometry_matches(item['geometry'], reference.get('geometry'))]
    if len(matches) != 1:
        raise ControlError('TARGET UNRESOLVED', 'The selection is stale or ambiguous. Select the intended geometry again.')
    return {**matches[0], 're_resolved': True}


def mark_geometry(document, marks):
    """Freeze bounded native geometry alongside visual marks, without guessing."""
    records = []
    seen = set()
    for mark in marks:
        for anchor in mark.anchors:
            key = (anchor.obj, anchor.element)
            if key in seen or len(records) >= 8:
                continue
            seen.add(key)
            obj = document.getObject(anchor.obj) if anchor.obj else None
            if obj is None or not anchor.on_model or not anchor.element.startswith(('Face', 'Edge', 'Vertex')):
                records.append({'mark': mark.number, 'resolution': 'VISUAL ANNOTATION ONLY'})
                continue
            try:
                records.append({'mark': mark.number, 'reference': geometry_reference(document, obj, anchor.element)})
            except (AttributeError, ValueError, RuntimeError):
                records.append({'mark': mark.number, 'resolution': 'TARGET UNRESOLVED'})
    return records
