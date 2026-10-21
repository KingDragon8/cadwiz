# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""The founder's FreeCAD 3D view, as the CADWiz panel and the Claude plug-in use it
(ORDER-2026-10-18-01).

Everything here touches FreeCAD's window and must run on its window thread (the
panel's timers and the bridge's request pump both do). Each function is best
effort: a view that cannot be read or turned never costs the founder anything
but the picture.

Measured in real FreeCAD 1.1.3 on 2026-10-18 before this was written: the camera
read here, projected by `anchored.Camera`, lands on FreeCAD's own
`getPointOnScreen` to within half a pixel, and on `saveImage` pictures of any
shape to within two; `getObjectInfo` names the object and face under a point; a
clip plane at the scene root shows the inside of the model.
"""
from __future__ import annotations

import contextlib
from typing import Any

from ai_freecad_core.visual_communications.anchored import Camera, ModelAnchor

CUT_AWAY_NODE = "CADWiz_CutAway"
#: The view buttons over the picture (Side is FreeCAD's Right view).
VIEW_NAMES = ("front", "top", "side", "iso")


def active_view(gui: Any) -> Any:
    """The active document's 3D view, or None (no document, or a non-3D view
    such as a spreadsheet is in front)."""
    with contextlib.suppress(Exception):
        view = gui.ActiveDocument.ActiveView
        if view is not None and hasattr(view, "getCameraNode") and hasattr(view, "saveImage"):
            return view
    return None


def read_camera(view: Any) -> Camera | None:
    try:
        from pivy import coin  # noqa: F401 - getCameraNode needs pivy loaded first

        node = view.getCameraNode()
        kind = "perspective" if "erspective" in str(view.getCameraType()) else "orthographic"
        position = tuple(float(c) for c in node.position.getValue().getValue())
        orientation = tuple(float(c) for c in node.orientation.getValue().getValue())
        focal = float(node.focalDistance.getValue())
        if kind == "orthographic":
            return Camera(kind, position, orientation, height=float(node.height.getValue()), focal_distance=focal)  # type: ignore[arg-type]
        return Camera(kind, position, orientation, height_angle=float(node.heightAngle.getValue()), focal_distance=focal)  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001
        return None


def capture(view: Any, path: str, width: int, height: int) -> bool:
    """A picture of the view as it is, at width x height."""
    try:
        view.saveImage(path, int(max(16, width)), int(max(16, height)), "Current")
        return True
    except Exception:  # noqa: BLE001
        return False


def set_view(view: Any, name: str) -> None:
    turn = {"front": "viewFront", "top": "viewTop", "side": "viewRight", "iso": "viewIsometric"}.get(name)
    if turn is None:
        return
    with contextlib.suppress(Exception):
        getattr(view, turn)()
    with contextlib.suppress(Exception):
        view.fitAll()


def view_name(camera: Camera | None) -> str:
    """'front', 'top', 'side', 'iso', or 'turned by hand' -- from where the camera looks."""
    if camera is None:
        return ""
    f = camera.forward
    standard = {"front": (0.0, 1.0, 0.0), "top": (0.0, 0.0, -1.0), "side": (-1.0, 0.0, 0.0),
                "iso": (-0.57735, 0.57735, -0.57735)}
    for name, direction in standard.items():
        if sum(a * b for a, b in zip(f, direction)) > 0.999:
            return name
    return "turned by hand"


def _root(view: Any) -> Any:
    return view.getSceneGraph()


def is_cut_away(view: Any) -> bool:
    with contextlib.suppress(Exception):
        root = _root(view)
        return any(root.getChild(i).getName().getString() == CUT_AWAY_NODE for i in range(root.getNumChildren()))
    return False


def cut_away(view: Any, on: bool, document: Any = None) -> bool:
    """Show the inside of the model: a clip plane through its middle, facing the
    current view, removes the half nearest the founder. Off removes it. Only the
    picture changes; the model is never touched."""
    try:
        from pivy import coin

        root = _root(view)
        for i in reversed(range(root.getNumChildren())):
            if root.getChild(i).getName().getString() == CUT_AWAY_NODE:
                root.removeChild(i)
        if not on:
            return False
        camera = read_camera(view)
        if camera is None:
            return False
        centre = visible_centre(document) or camera.point_at_focus(0.5, 0.5, 1.0)
        clip = coin.SoClipPlane()
        clip.setName(CUT_AWAY_NODE)
        clip.plane.setValue(coin.SbPlane(coin.SbVec3f(*camera.forward), coin.SbVec3f(*centre)))
        root.insertChild(clip, 0)
        return True
    except Exception:  # noqa: BLE001
        return False


#: Name of the transform put in front of each part's drawing while Assembly is on.
EXPLODE_NODE = "CADWiz_Assembly"
#: How far apart the parts are pulled, as a share of the whole model's size.
EXPLODE_SHARE = 0.45


def exploded_offsets(parts: list[tuple[str, tuple[float, float, float], float, float]]) -> dict[str, tuple[float, float, float]]:
    """How far to move each part's drawing for the Assembly view (ORDER-2026-10-19-05).

    parts: (name, centre, volume, size) for every visible part. The biggest part
    stays where it is; every other part moves straight away from it by
    EXPLODE_SHARE of the whole model's size -- a lid lifts off its can. A part
    centred on the biggest one (nothing to move away from) goes straight up."""
    if len(parts) < 2:
        return {}
    main = max(parts, key=lambda p: p[2])
    span = max(p[3] for p in parts) * EXPLODE_SHARE
    offsets: dict[str, tuple[float, float, float]] = {}
    for name, centre, _volume, _size in parts:
        if name == main[0]:
            continue
        d = [centre[i] - main[1][i] for i in range(3)]
        length = sum(c * c for c in d) ** 0.5
        if length < 1e-6:
            d, length = [0.0, 0.0, 1.0], 1.0
        offsets[name] = tuple(span * c / length for c in d)  # type: ignore[assignment]
    return offsets


def _visible_parts(document: Any) -> list[tuple[str, tuple[float, float, float], float, float]]:
    """Every visible shape in the document that stands on its own (not a feature
    inside a Body, not something another shape was made from)."""
    parts = []
    with contextlib.suppress(Exception):
        for obj in document.Objects:
            shape = getattr(obj, "Shape", None)
            visible = getattr(getattr(obj, "ViewObject", None), "Visibility", getattr(obj, "Visibility", False))
            if shape is None or not visible or shape.isNull() or not shape.Solids:
                continue
            type_id = str(getattr(obj, "TypeId", ""))
            if type_id.startswith(("Sketcher::", "App::", "Spreadsheet::")):
                continue
            parent = None
            with contextlib.suppress(Exception):
                parent = obj.getParentGeoFeatureGroup()
            if parent is not None and str(getattr(parent, "TypeId", "")) == "PartDesign::Body":
                continue
            box = shape.BoundBox
            parts.append((obj.Name, (box.Center.x, box.Center.y, box.Center.z), float(shape.Volume), float(box.DiagonalLength)))
    return parts


def is_exploded(document: Any) -> bool:
    with contextlib.suppress(Exception):
        for obj in document.Objects:
            root = obj.ViewObject.RootNode
            if root.getNumChildren() and root.getChild(0).getName().getString() == EXPLODE_NODE:
                return True
    return False


def explode(document: Any, on: bool) -> str:
    """Assembly: draw the parts pulled apart. Only their drawings move (a transform
    in front of each part's picture in the 3D view); the model and its placements
    are never touched. Returns "" when done, or a plain sentence saying why not."""
    try:
        from pivy import coin

        for obj in list(document.Objects):
            with contextlib.suppress(Exception):
                root = obj.ViewObject.RootNode
                while root.getNumChildren() and root.getChild(0).getName().getString() == EXPLODE_NODE:
                    root.removeChild(0)
        if not on:
            return ""
        parts = _visible_parts(document)
        if len(parts) < 2:
            return "This model is one part: there is nothing to pull apart."
        for name, offset in exploded_offsets(parts).items():
            move = coin.SoTransform()
            move.setName(EXPLODE_NODE)
            move.translation.setValue(coin.SbVec3f(*offset))
            document.getObject(name).ViewObject.RootNode.insertChild(move, 0)
        return ""
    except Exception:  # noqa: BLE001
        return "The parts could not be pulled apart in this view."


def visible_centre(document: Any) -> tuple[float, float, float] | None:
    """Middle of everything visible in the document (mm)."""
    box = None
    with contextlib.suppress(Exception):
        for obj in document.Objects:
            shape = getattr(obj, "Shape", None)
            visible = getattr(getattr(obj, "ViewObject", None), "Visibility", getattr(obj, "Visibility", False))
            if shape is None or not visible or shape.isNull():
                continue
            bound = shape.BoundBox
            box = bound if box is None else box.united(bound)
    if box is None:
        return None
    return (box.Center.x, box.Center.y, box.Center.z)


#: A mark placed this close (screen pixels) to a corner of the model snaps onto it,
#: so a Measure between two corners reads the real edge, not a near miss.
SNAP_PX = 10.0


def pick(view: Any, camera: Camera, u: float, v: float, aspect: float, picture_px: tuple[float, float] | None = None) -> ModelAnchor:
    """The point of the model under picture point (u, v): the face (or mesh facet)
    and the exact spot, else -- just off the model -- a corner within reach, else
    the point in the air at the camera's focus.

    The picture's own line of sight is followed into the model's geometry
    (`ray_hit`). FreeCAD's screen pick (`getObjectInfo`) is only the fallback: it
    works in the live window's pixels, which were measured 5 mm off on
    2026-10-18 when the window was not being drawn on screen, and it looks along
    the wrong line once the view has turned since the picture was taken."""
    hit = ray_hit(camera, u, v, aspect)
    if hit is not None:
        return _snap_to_corner(hit, camera, u, v, aspect, picture_px) if picture_px else hit
    along = camera.point_at_focus(u, v, aspect)
    live = read_camera(view)
    if live is not None and same_camera(live, camera):
        try:
            import FreeCAD

            x, y = view.getPointOnScreen(FreeCAD.Vector(*along))
            info = view.getObjectInfo((int(round(x)), int(round(y))))
            if info and "x" in info:
                found = ModelAnchor((float(info["x"]), float(info["y"]), float(info["z"])), str(info.get("Object") or ""),
                                    str(info.get("Component") or ""), True)
                if found.element.startswith("Vertex"):
                    # FreeCAD names the corner it picked but reports a point on its
                    # marker: use the corner itself (measured 2026-10-18: 0.87 mm off).
                    exact = _element_point(found.obj, found.element)
                    if exact is not None:
                        return ModelAnchor(exact, found.obj, found.element, True)
                return _snap_to_corner(found, camera, u, v, aspect, picture_px) if picture_px else found
        except Exception:  # noqa: BLE001
            pass
    if picture_px:
        # Just off the model's edge: a corner within reach still counts (a click on
        # the very corner of a box falls outside its outline about half the time).
        corner = _nearest_corner(_visible_objects(), camera, u, v, aspect, picture_px)
        if corner is not None:
            return corner
    return ModelAnchor(along)


def same_camera(a: Camera, b: Camera, tolerance: float = 1e-4) -> bool:
    if a.kind != b.kind:
        return False
    numbers_a = [*a.position, *a.orientation, a.height, a.height_angle]
    numbers_b = [*b.position, *b.orientation, b.height, b.height_angle]
    scale = max(1.0, max(abs(n) for n in numbers_a))
    return all(abs(x - y) <= tolerance * scale for x, y in zip(numbers_a, numbers_b))


def ray_hit(camera: Camera, u: float, v: float, aspect: float) -> ModelAnchor | None:
    """The first visible surface along the picture's line of sight: solids (the
    face it crosses) and meshes (the facet it crosses). None when it misses."""
    try:
        import FreeCAD
        import Part
    except ImportError:
        return None
    origin, direction = camera.ray(u, v, aspect)
    start = FreeCAD.Vector(*[origin[i] - direction[i] * 1e4 for i in range(3)])
    end = FreeCAD.Vector(*[origin[i] + direction[i] * 1e4 for i in range(3)])
    line = Part.LineSegment(start, end).toShape()
    best: tuple[float, ModelAnchor] | None = None

    def depth(point: Any) -> float:
        return sum((float(point[i]) - origin[i]) * direction[i] for i in range(3))

    for obj in _visible_objects():
        with contextlib.suppress(Exception):
            if str(getattr(obj, "TypeId", "")) == "Mesh::Feature":
                mesh = obj.Mesh.copy()
                mesh.transform(obj.Placement.toMatrix())
                for facet, point in mesh.nearestFacetOnRay(tuple(start), tuple(direction)).items():
                    anchor = ModelAnchor((float(point[0]), float(point[1]), float(point[2])), str(obj.Name), f"Facet{facet + 1}", True)
                    if best is None or depth(point) < best[0]:
                        best = (depth(point), anchor)
                continue
            shape = obj.Shape
            if shape.isNull() or not shape.Solids:
                continue
            for vertex in shape.section(line).Vertexes:
                point = vertex.Point
                if best is not None and depth(point) >= best[0]:
                    continue
                face = min(range(len(shape.Faces)), key=lambda i: shape.Faces[i].distToShape(vertex)[0])
                best = (depth(point), ModelAnchor((point.x, point.y, point.z), str(obj.Name), f"Face{face + 1}", True))
    return best[1] if best else None


def face_outline(document: Any, anchor: ModelAnchor, points: int = 48) -> list[ModelAnchor]:
    """The outline of the face `anchor` sits on, as anchors on that face (the
    founder's Highlight click). Empty when it is not on a face."""
    if not anchor.on_model or not anchor.element.startswith("Face"):
        return []
    try:
        obj = document.getObject(anchor.obj)
        wire = obj.Shape.getElement(anchor.element).OuterWire
        found = list(wire.discretize(Number=points))
        with contextlib.suppress(Exception):
            parent = obj.getParentGeoFeatureGroup()
            if parent is not None:
                placement = parent.getGlobalPlacement()
                found = [placement.multVec(p) for p in found]
    except Exception:  # noqa: BLE001 - no outline, no mark
        return []
    return [ModelAnchor((float(p.x), float(p.y), float(p.z)), anchor.obj, anchor.element, True) for p in found]


def _element_point(name: str, element: str) -> tuple[float, float, float] | None:
    try:
        import FreeCAD

        obj = FreeCAD.ActiveDocument.getObject(name)
        point = obj.Shape.getElement(element).Point
        with contextlib.suppress(Exception):
            parent = obj.getParentGeoFeatureGroup()
            if parent is not None:
                point = parent.getGlobalPlacement().multVec(point)
        return (float(point.x), float(point.y), float(point.z))
    except Exception:  # noqa: BLE001
        return None


def _snap_to_corner(hit: ModelAnchor, camera: Camera, u: float, v: float, aspect: float, picture_px: tuple[float, float]) -> ModelAnchor:
    """The nearest corner of the object under the pointer, if it is within SNAP_PX."""
    try:
        import FreeCAD

        corner = _nearest_corner([FreeCAD.ActiveDocument.getObject(hit.obj)], camera, u, v, aspect, picture_px,
                                 no_deeper_than=_depth(camera, hit.point) + 1.0)
        return corner or hit
    except Exception:  # noqa: BLE001 - no snapping is never worse than the plain pick
        return hit


def _visible_objects() -> list[Any]:
    found: list[Any] = []
    with contextlib.suppress(Exception):
        import FreeCAD

        for obj in FreeCAD.ActiveDocument.Objects:
            visible = getattr(getattr(obj, "ViewObject", None), "Visibility", getattr(obj, "Visibility", False))
            shape = getattr(obj, "Shape", None)
            if visible and shape is not None and not shape.isNull() and len(shape.Vertexes) <= 5000:
                found.append(obj)
    return found


def _depth(camera: Camera, point: Any) -> float:
    position, forward = camera.position, camera.forward
    return sum((float(point[i]) - position[i]) * forward[i] for i in range(3))


def _nearest_corner(objects: list[Any], camera: Camera, u: float, v: float, aspect: float,
                    picture_px: tuple[float, float], no_deeper_than: float | None = None) -> ModelAnchor | None:
    """The corner within SNAP_PX of the pointer that is nearest the eye: a corner
    hidden behind the model can line up with a visible one on screen (in the iso
    view of a box they coincide exactly), and he means the one he can see."""
    width, height = picture_px
    best, best_depth = None, float("inf")
    for obj in objects:
        if obj is None:
            continue
        placement = None
        with contextlib.suppress(Exception):
            parent = obj.getParentGeoFeatureGroup()
            placement = parent.getGlobalPlacement() if parent is not None else None
        with contextlib.suppress(Exception):
            for index, vertex in enumerate(obj.Shape.Vertexes, start=1):
                point = placement.multVec(vertex.Point) if placement is not None else vertex.Point
                at = camera.project((point.x, point.y, point.z), aspect)
                if at is None:
                    continue
                gap = (((at[0] - u) * width) ** 2 + ((at[1] - v) * height) ** 2) ** 0.5
                depth = _depth(camera, (point.x, point.y, point.z))
                if gap <= SNAP_PX and depth < best_depth and (no_deeper_than is None or depth <= no_deeper_than):
                    best = ModelAnchor((float(point.x), float(point.y), float(point.z)), str(obj.Name), f"Vertex{index}", True)
                    best_depth = depth
    return best


def resolve(document: Any, where: str) -> ModelAnchor:
    """'Pad', 'Pad.Face6', 'Body.Pad.Edge3' or an object's label -> a point on it:
    the middle of the face, edge or object, a vertex itself."""
    parts = [p for p in str(where).split(".") if p]
    if not parts:
        raise ValueError("name an object, or an object and one of its faces, edges or vertices")
    element = parts[-1] if parts[-1][:4] in ("Face", "Edge") or parts[-1].startswith("Vertex") else ""
    names = parts[:-1] if element else parts
    obj = None
    for name in reversed(names):
        obj = document.getObject(name)
        if obj is None:
            matches = document.getObjectsByLabel(name) if hasattr(document, "getObjectsByLabel") else []
            obj = matches[0] if matches else None
        if obj is not None:
            break
    if obj is None:
        raise ValueError(f"there is no object called {names[-1]!r} in {document.Label}")
    shape = obj.Shape
    if element:
        sub = shape.getElement(element)
        if element.startswith("Vertex"):
            point = sub.Point
        elif element.startswith("Edge"):
            first, last = sub.ParameterRange
            point = sub.valueAt((first + last) / 2.0)
        else:
            point = sub.CenterOfMass
    else:
        point = shape.BoundBox.Center
    with contextlib.suppress(Exception):
        parent = obj.getParentGeoFeatureGroup()
        if parent is not None:
            point = parent.getGlobalPlacement().multVec(point)
    return ModelAnchor((float(point.x), float(point.y), float(point.z)), str(obj.Name), element, True)


def selection(gui: Any) -> list[dict[str, Any]]:
    """What the founder has selected now: objects, faces/edges/vertices, and the
    exact points he clicked (mm)."""
    picked: list[dict[str, Any]] = []
    with contextlib.suppress(Exception):
        for item in gui.Selection.getSelectionEx():
            obj = item.Object
            picked.append({"document": str(item.DocumentName), "object": str(item.ObjectName), "label": str(getattr(obj, "Label", "")),
                           "type": str(getattr(obj, "TypeId", "")), "elements": [str(s) for s in item.SubElementNames],
                           "picked_points_mm": [[round(p.x, 3), round(p.y, 3), round(p.z, 3)] for p in item.PickedPoints]})
    return picked


def selection_names(gui: Any) -> list[str]:
    """A cheap fingerprint of the selection (the panel retakes its picture when it changes)."""
    names: list[str] = []
    with contextlib.suppress(Exception):
        for item in gui.Selection.getSelectionEx():
            names.extend(f"{item.ObjectName}.{s}" for s in (item.SubElementNames or [""]))
    return names


def selection_summary(picked: list[dict[str, Any]]) -> str:
    if not picked:
        return "Nothing is selected in FreeCAD right now."
    parts = []
    for item in picked:
        name = item["label"] or item["object"]
        parts.append(f"{', '.join(item['elements'])} of {name}" if item["elements"] else name)
    return "Selected: " + "; ".join(parts) + "."


def broken_objects(document: Any) -> list[str]:
    """Labels of the document's objects that are in error after their last recompute."""
    broken: list[str] = []
    with contextlib.suppress(Exception):
        for obj in document.Objects:
            state = set(str(s) for s in (getattr(obj, "State", None) or ()))
            if state & {"Invalid", "Error"}:
                broken.append(str(obj.Label))
    return broken


def sketch_in_edit(gui: Any) -> bool:
    """True while a sketch is open for editing (the Sketcher's edit mode)."""
    with contextlib.suppress(Exception):
        provider = gui.ActiveDocument.getInEdit()
        obj = getattr(provider, "Object", None)
        return str(getattr(obj, "TypeId", "")).startswith("Sketcher::")
    return False
