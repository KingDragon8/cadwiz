# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""View-only motion for the measured toothpaste mechanism; no document writes.

The 100 mm preview stroke is deliberately inside the guide's available travel.
The 6.5 mm drum radius couples crank angle to roller travel. Cable deformation,
loads and collisions are not simulated. Unsupported models are left untouched.
"""
from __future__ import annotations

import math

NODE_NAME = "CADWiz_MotionPreview"
PARTS = ("EnclosedSweptCrank", "CrownAccessPlug", "RightRollerCarriage",
         "LeftRollerCarriage", "RotatingRollingPin")
CORD_COLORS = {"RightDriveCord": (1.0, 0.35, 0.03), "LeftDriveCord": (0.05, 0.35, 1.0)}


def cord_route(name: str, travel: float = 0.0) -> list[tuple[float, float, float]]:
    """The saved model's two guide routes, with the return end on its traveler.

    The shortened free length winds onto the 6.5 mm drum. These are display
    centerlines; they do not model string stretch, tension, or drum layering.
    """
    right = name == "RightDriveCord"
    if name not in CORD_COLORS:
        raise ValueError("Unknown drive string")
    sign = 1 if right else -1
    top_y = 234.8 if right else 249.0
    points = [(0.0, top_y + 4.1, 22.5 if right else 29.5)]
    # Top quarter-turn guide and lower half-turn guide, radius 4.1 mm.
    for i in range(9):
        angle = math.pi / 2.0 - sign * i * math.pi / 16.0
        points.append((sign * 43.4 + 4.1 * math.cos(angle), top_y + 4.1 * math.sin(angle), 20.5))
    for i in range(17):
        angle = -i * math.pi / 16.0 if right else math.pi + i * math.pi / 16.0
        points.append((sign * 43.4 + 4.1 * math.cos(angle), 14.0 + 4.1 * math.sin(angle), 20.5))
    points.append((sign * 39.3, 216.0 + float(travel), 20.5))
    return points


def pose(seconds: float) -> tuple[float, float]:
    """Smooth, reversible stroke, starting at the model's actual resting pose."""
    travel = -50.0 * (1.0 - math.cos(float(seconds) * math.tau / 16.0))
    return travel, travel / 6.5


class MotionPreview:
    def __new__(cls, document):
        if document is not None and all(document.getObject(name) is not None
                                        for name in ("PhoneArm", "Arm1", "Arm2", "Head", "Arm1_HoleA", "Arm2_HoleA", "Head_JointHole")):
            return PhoneArmPreview(document)
        return super().__new__(cls)

    def __init__(self, document):
        if document is None or any(document.getObject(name) is None for name in PARTS):
            raise ValueError("Motion preview needs a complete toothpaste crank assembly or articulated phone holder.")
        from pivy import coin
        import FreeCAD as App
        import FreeCADGui as Gui
        from integrations.cadwiz_plugin.view_link import world_shape

        self.document = document
        self.nodes = []
        self.coin = coin
        self.hidden = []
        self.cords = {}
        self.scene = Gui.activeDocument().activeView().getSceneGraph()
        self.preview = coin.SoSeparator()
        self.preview.setName(NODE_NAME)
        assembly = document.getObject("Dispenser")
        placement = assembly.getGlobalPlacement() if assembly is not None else App.Placement()
        self.placement, self.vector = placement, App.Vector
        self.travel_axis = tuple(placement.Rotation.multVec(App.Vector(0, 1, 0)))
        self.crank_axis = tuple(placement.Rotation.multVec(App.Vector(0, 0, 1)))
        self.roller_axis = tuple(placement.Rotation.multVec(App.Vector(1, 0, 0)))
        crank_pivot = tuple(placement.multVec(App.Vector(0, 246, 0)))
        roller_pivot = tuple(placement.multVec(App.Vector(0, 200, 11.9)))
        try:
            for name in PARTS:
                obj = document.getObject(name)
                root = coin.SoSeparator()
                node = coin.SoTransform()
                node.setName(NODE_NAME)
                if name in PARTS[:2]:
                    node.center.setValue(*crank_pivot)
                elif name == "RotatingRollingPin":
                    node.center.setValue(*roller_pivot)
                root.insertChild(node, 0)
                self.nodes.append((name, root, node))
                add_shape_drawing(coin, root, world_shape(obj), obj.ViewObject.ShapeColor)
                self.preview.addChild(root)
                # Body roots and independently displayed tips both occur in saved
                # FreeCAD documents. Hide both drawings, never their properties.
                for original in [obj] + list(getattr(obj, "Group", [])):
                    view = getattr(original, "ViewObject", None)
                    if view is not None:
                        hide = coin.SoScale()
                        hide.setName(NODE_NAME)
                        hide.scaleFactor.setValue(0, 0, 0)
                        view.RootNode.insertChild(hide, 0)
                        self.hidden.append((view.RootNode, hide))
            for name, color in CORD_COLORS.items():
                original = document.getObject(name)
                if original is None:
                    continue
                root = coin.SoSeparator()
                light = coin.SoLightModel()
                light.model.setValue(coin.SoLightModel.BASE_COLOR)
                root.addChild(light)
                material = coin.SoBaseColor()
                material.rgb.setValue(*color)
                root.addChild(material)
                style = coin.SoDrawStyle()
                style.lineWidth.setValue(3.5)
                root.addChild(style)
                coordinates = coin.SoCoordinate3()
                root.addChild(coordinates)
                lines = coin.SoLineSet()
                lines.numVertices.setValue(len(cord_route(name)))
                root.addChild(lines)
                self.preview.addChild(root)
                self.cords[name] = coordinates
                hide = coin.SoScale()
                hide.setName(NODE_NAME)
                hide.scaleFactor.setValue(0, 0, 0)
                original.ViewObject.RootNode.insertChild(hide, 0)
                self.hidden.append((original.ViewObject.RootNode, hide))
            self.scene.addChild(self.preview)
            self.frame(0.0)
        except Exception:
            self.stop()
            raise

    def frame(self, seconds):
        travel, angle = pose(seconds)
        for name, coordinates in self.cords.items():
            points = [tuple(self.placement.multVec(self.vector(*p))) for p in cord_route(name, travel)]
            coordinates.point.setValues(0, len(points), points)
        for name, root, node in self.nodes:
            if root.findChild(node) < 0:
                raise RuntimeError("The model view changed.")
            if name in PARTS[:2]:
                node.rotation.setValue(self.coin.SbVec3f(*self.crank_axis), angle)
            else:
                node.translation.setValue(*(travel * c for c in self.travel_axis))
                if name == "RotatingRollingPin":
                    node.rotation.setValue(self.coin.SbVec3f(*self.roller_axis), -travel / 7.5)

    def stop(self):
        if hasattr(self, "scene"):
            try:
                if self.scene.findChild(self.preview) >= 0:
                    self.scene.removeChild(self.preview)
            except (RuntimeError, ReferenceError):
                pass
        for root, hide in getattr(self, "hidden", []):
            try:
                if root.findChild(hide) >= 0:
                    root.removeChild(hide)
            except (RuntimeError, ReferenceError):
                pass
        self.hidden.clear()
        self.cords.clear()
        for _name, root, node in self.nodes:
            try:
                if root.findChild(node) >= 0:
                    root.removeChild(node)
            except (RuntimeError, ReferenceError):
                pass
        self.nodes.clear()


def add_shape_drawing(coin, root, shape, color):
    """A private drawing of the evaluated shape, without a second placement."""
    material = coin.SoMaterial()
    material.diffuseColor.setValue(*color[:3])
    root.addChild(material)
    vertices, triangles = shape.tessellate(0.25)
    coordinates = coin.SoCoordinate3()
    coordinates.point.setValues(0, len(vertices), [tuple(v) for v in vertices])
    faces = coin.SoIndexedFaceSet()
    indices = [index for face in triangles for index in (*face, -1)]
    faces.coordIndex.setValues(0, len(indices), indices)
    root.addChild(coordinates)
    root.addChild(faces)


def phone_pose(p1, p2, p3, seconds):
    """Two measured hinges; keep the holder upright while the arms articulate."""
    phase = math.sin(float(seconds) * math.tau / 12.0)
    a1, a2 = math.radians(12) * phase, math.radians(18) * phase

    def rotate(v, angle):
        x, y, z = v
        c, s = math.cos(angle), math.sin(angle)
        return (c*x + s*z, y, -s*x + c*z)

    def difference(a, b):
        return tuple(x-y for x, y in zip(a, b))

    def add(a, b):
        return tuple(x+y for x, y in zip(a, b))

    next_p2 = add(p1, rotate(difference(p2, p1), a1))
    next_p3 = add(next_p2, rotate(difference(p3, p2), a2))
    return a1, a2, difference(next_p2, p2), difference(next_p3, p3)


class PhoneArmPreview:
    """Independent drawings also support a saved single-compound display.

    The original scene is hidden with reversible Coin scale nodes. The preview
    tessellates the measured bodies without adding or editing document objects.
    """

    def __init__(self, document):
        from pivy import coin
        import FreeCADGui as Gui

        self.document, self.coin, self.nodes = document, coin, []
        self.hidden = []
        self.scene = Gui.activeDocument().activeView().getSceneGraph()
        self.preview = coin.SoSeparator()
        self.preview.setName(NODE_NAME)
        self.pivots = [tuple(float(v) for v in document.getObject(name).Placement.Base)
                       for name in ("Arm1", "Arm2", "Head")]
        try:
            names = ["Clamp", "Knob", "Arm1", "Arm2", "Head"]
            hardware = document.getObject("Hardware")
            if hardware is not None:
                names += [obj.Name for obj in hardware.Group if hasattr(obj, "Shape")]
            for name in names:
                obj = document.getObject(name)
                if obj is None or not hasattr(obj, "Shape") or obj.Shape.isNull():
                    continue
                root = coin.SoSeparator()
                node = coin.SoTransform()
                node.setName(NODE_NAME)
                if name in ("Arm1", "Arm2"):
                    node.center.setValue(*self.pivots[0 if name == "Arm1" else 1])
                root.insertChild(node, 0)
                self.nodes.append((name, root, node))
                material = coin.SoMaterial()
                material.diffuseColor.setValue(*obj.ViewObject.ShapeColor[:3])
                root.addChild(material)
                vertices, triangles = obj.Shape.tessellate(0.25)
                coordinates = coin.SoCoordinate3()
                coordinates.point.setValues(0, len(vertices), [tuple(v) for v in vertices])
                faces = coin.SoIndexedFaceSet()
                indices = [index for face in triangles for index in (*face, -1)]
                faces.coordIndex.setValues(0, len(indices), indices)
                root.addChild(coordinates)
                root.addChild(faces)
                self.preview.addChild(root)
            for obj in document.Objects:
                view = getattr(obj, "ViewObject", None)
                if view is not None and view.Visibility and hasattr(obj, "Shape"):
                    hide = coin.SoScale()
                    hide.setName(NODE_NAME)
                    hide.scaleFactor.setValue(0, 0, 0)
                    view.RootNode.insertChild(hide, 0)
                    self.hidden.append((view.RootNode, hide))
            self.scene.addChild(self.preview)
            self.frame(0)
        except Exception:
            self.stop()
            raise

    def frame(self, seconds):
        a1, a2, d2, d3 = phone_pose(*self.pivots, seconds)
        for name, root, node in self.nodes:
            if root.findChild(node) < 0:
                raise RuntimeError("The model view changed.")
            if name == "Arm1":
                node.rotation.setValue(self.coin.SbVec3f(0, 1, 0), a1)
            elif name == "Arm2":
                node.rotation.setValue(self.coin.SbVec3f(0, 1, 0), a2)
                node.translation.setValue(*d2)
            elif name.startswith("HW_J2_"):
                node.translation.setValue(*d2)
            elif name == "Head" or name.startswith("HW_J3_"):
                node.translation.setValue(*d3)

    def stop(self):
        try:
            if self.scene.findChild(self.preview) >= 0:
                self.scene.removeChild(self.preview)
        except (RuntimeError, ReferenceError):
            pass
        for root, hide in self.hidden:
            try:
                if root.findChild(hide) >= 0:
                    root.removeChild(hide)
            except (RuntimeError, ReferenceError):
                pass
        self.hidden.clear()
        self.nodes.clear()
