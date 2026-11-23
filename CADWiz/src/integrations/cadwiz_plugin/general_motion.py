# SPDX-License-Identifier: LGPL-2.1-or-later
"""View-only previews selected from the current document, never a project name."""
from __future__ import annotations
import math


def visible(obj):
    view = getattr(obj, 'ViewObject', None)
    if view is not None and not bool(getattr(view, 'Visibility', True)):
        return False
    parent_of = getattr(obj, 'getParentGeoFeatureGroup', None)
    parent = parent_of() if callable(parent_of) else None
    while parent is not None:
        if not bool(getattr(getattr(parent, 'ViewObject', None), 'Visibility', True)):
            return False
        next_parent = getattr(parent, 'getParentGeoFeatureGroup', None)
        parent = next_parent() if callable(next_parent) else None
    return True


def drawable(document):
    for obj in getattr(document, 'Objects', ()):
        if not visible(obj):
            continue
        shape = getattr(obj, 'Shape', None)
        if shape is not None and not shape.isNull():
            return True
        mesh = getattr(obj, 'Mesh', None)
        if mesh is not None and getattr(mesh, 'CountFacets', 0):
            return True
    return False


def target_view(document):
    import FreeCADGui as Gui
    from integrations.cadwiz_plugin.view_link import activate_document_view
    view = activate_document_view(Gui, document)
    if view is None:
        raise ValueError('Open a 3D model view before starting Animate.')
    return view


def orbit_position(position, center, angle):
    x, y, z = (a-b for a, b in zip(position, center))
    c, s = math.cos(angle), math.sin(angle)
    return (center[0]+c*x-s*y, center[1]+s*x+c*y, center[2]+z)


class ModelTurntablePreview:
    """Rotate the camera, without inventing joints or changing a model property."""
    description = 'Model turntable — no mechanical motion is defined for this model.'
    button_text = 'Stop turntable'

    def __init__(self, document):
        if document is None or not drawable(document):
            raise ValueError('Open a 3D model before starting Animate.')
        from pivy import coin
        self.document, self.coin = document, coin
        self.view = target_view(document)
        self.camera = self.view.getCameraNode()
        self.position = tuple(self.camera.position.getValue().getValue())
        self.orientation = coin.SbRotation(*self.camera.orientation.getValue().getValue())
        distance = float(self.camera.focalDistance.getValue())
        direction = self.orientation.multVec(coin.SbVec3f(0, 0, -distance))
        self.center = tuple(a+b for a, b in zip(self.position, direction))
        self.stopped = False

    def frame(self, seconds):
        if self.stopped:
            return
        angle = float(seconds)*math.tau/24.0
        self.camera.position.setValue(*orbit_position(self.position, self.center, angle))
        rotation = self.coin.SbRotation(self.coin.SbVec3f(0, 0, 1), angle)
        self.camera.orientation.setValue(rotation*self.orientation)

    def stop(self):
        if self.stopped:
            return
        self.stopped = True
        try:
            self.camera.position.setValue(*self.position)
            self.camera.orientation.setValue(self.orientation)
            self.view.redraw()
        except (RuntimeError, ReferenceError):
            pass


def _number(obj, names):
    for name in names:
        try:
            value = getattr(obj, name)
            return float(getattr(value, 'Value', value))
        except (AttributeError, TypeError, ValueError, ReferenceError):
            pass
    return None


def gear_pair(document):
    """Recognize two external involute gears with compatible module and centers.

    Unknown/multi-stage mechanisms fall back to a labeled turntable; names alone
    never establish a ratio. Both native involute profiles and common gear-addon
    property names are accepted.
    """
    gears = []
    for obj in getattr(document, 'Objects', ()):
        if str(getattr(obj, 'TypeId', '')) != 'PartDesign::Body' or not visible(obj):
            continue
        for profile in getattr(obj, 'Group', ()):
            teeth = _number(profile, ('NumberOfTeeth', 'teeth', 'Teeth'))
            module = _number(profile, ('Modules', 'module', 'Module'))
            if teeth is None or module is None or teeth < 4 or module <= 0 or not math.isclose(teeth, round(teeth), abs_tol=1e-6):
                continue
            if getattr(profile, 'ExternalGear', True) is False:
                continue
            placement = obj.getGlobalPlacement()
            import FreeCAD as App
            axis = tuple(placement.Rotation.multVec(App.Vector(0, 0, 1)))
            center = tuple(placement.Base)
            gears.append({'object': obj, 'teeth': teeth, 'module': module,
                          'axis': axis, 'center': center, 'radius': teeth*module/2})
            break
    if len(gears) != 2:
        return None
    a, b = sorted(gears, key=lambda g: g['teeth'])
    if not math.isclose(a['module'], b['module'], rel_tol=1e-6):
        return None
    dot = sum(x*y for x, y in zip(a['axis'], b['axis']))
    if dot < .99999:  # reversed or nonparallel local frames need explicit joints
        return None
    delta = tuple(y-x for x, y in zip(a['center'], b['center']))
    axial = sum(x*y for x, y in zip(delta, a['axis']))
    radial = math.sqrt(max(0, sum(x*x for x in delta)-axial*axial))
    expected = a['radius']+b['radius']
    if abs(radial-expected) > max(.5*a['module'], .01) or abs(axial) > .01:
        return None
    return (a, b)


def gear_angles(seconds, driver_teeth, driven_teeth):
    angle = float(seconds)*math.tau/8.0
    return angle, -angle*float(driver_teeth)/float(driven_teeth)


class GearTrainPreview:
    """Private Coin drawings rotate; geometry, placements and file stay untouched."""
    button_text = 'Stop motion'

    def __init__(self, document, pair):
        from pivy import coin
        from integrations.cadwiz_plugin.motion_preview import add_shape_drawing
        from integrations.cadwiz_plugin.view_link import world_shape
        self.document, self.coin, self.nodes, self.hidden = document, coin, [], []
        self.pair = pair
        self.description = f"Gear motion: {pair[0]['teeth']:g}/{pair[1]['teeth']:g} teeth; counter-rotation, {pair[1]['teeth']/pair[0]['teeth']:g}:1. View preview, not a load simulation."
        self.scene = target_view(document).getSceneGraph()
        self.preview = coin.SoSeparator(); self.preview.setName('CADWiz_GearMotion')
        moving = [(g['object'], i) for i, g in enumerate(pair)]
        gear_names = {o.Name for o, _ in moving}
        for obj in getattr(document, 'Objects', ()):
            if str(getattr(obj, 'TypeId', '')) != 'PartDesign::Body' or obj.Name in gear_names or not visible(obj):
                continue
            role = str(getattr(obj, 'MotionRole', '')).lower()
            name = (str(obj.Name)+' '+str(getattr(obj, 'Label', ''))).lower()
            if role == 'fixed' or not (role == 'rotating' or any(word in name for word in ('shaft', 'collar', 'spacer'))):
                continue
            point = tuple(obj.getGlobalPlacement().Base)
            for i, gear in enumerate(pair):
                delta = tuple(x-y for x, y in zip(point, gear['center']))
                axial = sum(x*y for x, y in zip(delta, gear['axis']))
                radial = math.sqrt(max(0, sum(x*x for x in delta)-axial*axial))
                if radial < .01:
                    moving.append((obj, i)); break
        try:
            for obj, index in moving:
                root = coin.SoSeparator(); node = coin.SoTransform()
                node.center.setValue(*pair[index]['center']); root.addChild(node)
                color = obj.ViewObject.ShapeColor
                materials = getattr(obj, 'CADWizAppearance', ())
                if materials:
                    color = materials[0].DiffuseColor
                add_shape_drawing(coin, root, world_shape(obj), color)
                self.preview.addChild(root); self.nodes.append((index, root, node))
                for original in [obj]+list(getattr(obj, 'Group', ())):
                    view = getattr(original, 'ViewObject', None)
                    if view is not None:
                        hide = coin.SoScale(); hide.scaleFactor.setValue(0, 0, 0)
                        view.RootNode.insertChild(hide, 0); self.hidden.append((view.RootNode, hide))
            self.scene.addChild(self.preview); self.frame(0)
        except Exception:
            self.stop(); raise

    def frame(self, seconds):
        angles = gear_angles(seconds, self.pair[0]['teeth'], self.pair[1]['teeth'])
        for index, root, node in self.nodes:
            if root.findChild(node) < 0:
                raise RuntimeError('The model view changed.')
            node.rotation.setValue(self.coin.SbVec3f(*self.pair[index]['axis']), angles[index])

    def stop(self):
        try:
            if self.scene.findChild(self.preview) >= 0:self.scene.removeChild(self.preview)
        except (RuntimeError, ReferenceError):pass
        for root, hide in self.hidden:
            try:
                if root.findChild(hide) >= 0:root.removeChild(hide)
            except (RuntimeError, ReferenceError):pass
        self.hidden.clear(); self.nodes.clear()
