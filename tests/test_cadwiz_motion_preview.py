"""Motion controls must not mutate manufacturing geometry or leave view offsets."""
import sys
import math
from types import SimpleNamespace

import pytest

from integrations.cadwiz_plugin import motion_preview, slim_panel, view_link


class Field:
    def setValue(self, *value):
        self.value = value


class Transform:
    def __init__(self):
        self.center, self.translation, self.rotation = Field(), Field(), Field()

    def setName(self, name):
        self.name = name


class Root:
    def __init__(self):
        self.children = [object()]

    def insertChild(self, node, index):
        self.children.insert(index, node)

    def findChild(self, node):
        return self.children.index(node) if node in self.children else -1

    def removeChild(self, node):
        self.children.remove(node)

    def addChild(self, node):
        self.children.append(node)

    def setName(self, name):
        self.name = name


def test_preview_returns_to_rest_and_reverses_with_coupled_crank():
    assert motion_preview.pose(0) == (0, 0)
    assert motion_preview.pose(8)[0] == -100
    assert motion_preview.pose(16)[0] == pytest.approx(0)
    assert motion_preview.pose(4)[0] == pytest.approx(motion_preview.pose(12)[0])
    travel, angle = motion_preview.pose(3)
    assert angle * 6.5 == pytest.approx(travel)


@pytest.mark.parametrize("name", list(motion_preview.CORD_COLORS))
def test_strings_follow_traveler_and_transfer_free_length_to_drum(name):
    rest = motion_preview.cord_route(name)
    moving = motion_preview.cord_route(name, -50)
    assert rest[:-1] == moving[:-1]  # all guide contacts remain fixed
    assert moving[-1][1] == rest[-1][1] - 50
    assert moving[-1][0] == rest[-1][0]
    assert moving[-1][2] == rest[-1][2]
    length = lambda points: sum(math.dist(a,b) for a,b in zip(points,points[1:]))
    assert length(rest)-length(moving) == pytest.approx(50)
    assert min(p[1] for p in moving) == pytest.approx(9.9)


def test_view_nodes_cleaned_and_existing_geometry_preserved(monkeypatch):
    coin = SimpleNamespace(SoTransform=Transform, SoSeparator=Root, SoScale=lambda: SimpleNamespace(setName=lambda n: None, scaleFactor=Field()), SbVec3f=lambda *x: x)
    monkeypatch.setitem(sys.modules, "pivy", SimpleNamespace(coin=coin))
    # The dispenser is upright through a 90-degree parent rotation about X.
    rotate = lambda v: (v[0], -v[2], v[1])
    placement = SimpleNamespace(Rotation=SimpleNamespace(multVec=rotate), multVec=rotate)
    monkeypatch.setitem(sys.modules, "FreeCAD", SimpleNamespace(Placement=lambda: placement, Vector=lambda *v: v))
    scene = Root()
    monkeypatch.setitem(sys.modules, "FreeCADGui", SimpleNamespace(activeDocument=lambda: SimpleNamespace(activeView=lambda: SimpleNamespace(getSceneGraph=lambda: scene))))
    monkeypatch.setattr(motion_preview, "add_shape_drawing", lambda *args: None)
    monkeypatch.setattr(view_link, "world_shape", lambda obj: None)
    objects = {name: SimpleNamespace(ViewObject=SimpleNamespace(RootNode=Root(), ShapeColor=(.5,.5,.5))) for name in motion_preview.PARTS}
    originals = {name: list(obj.ViewObject.RootNode.children) for name, obj in objects.items()}
    doc = SimpleNamespace(getObject=objects.get)
    preview = motion_preview.MotionPreview(doc)
    preview.frame(8)
    nodes = {name: node for name, root, node in preview.nodes}
    assert nodes["RightRollerCarriage"].translation.value == (0, 0, -100)
    assert nodes["EnclosedSweptCrank"].rotation.value[0] == (0, -1, 0)
    assert nodes["EnclosedSweptCrank"].rotation.value[1] == pytest.approx(-100 / 6.5)
    preview.stop()
    preview.stop()
    assert all(obj.ViewObject.RootNode.children == originals[name] for name, obj in objects.items())


def test_incomplete_model_is_untouched():
    with pytest.raises(ValueError, match="complete toothpaste"):
        motion_preview.MotionPreview(SimpleNamespace(getObject=lambda name: None))


def test_center_uses_actual_scene_bounds_after_side_view(monkeypatch):
    calls = []
    monkeypatch.setitem(sys.modules, "pivy", SimpleNamespace(coin=SimpleNamespace(SbViewportRegion=lambda w, h: (w, h))))
    camera = SimpleNamespace(viewAll=lambda scene, size: calls.append((scene, size)))
    view = SimpleNamespace(viewRight=lambda: calls.append("side"), fitAll=lambda: calls.append("fit"),
                           getCameraNode=lambda: camera, getSize=lambda: (900, 600), getSceneGraph=lambda: "actual scene")
    view_link.center(view)
    assert calls == ["side", "fit", ("actual scene", (900, 600))]
    assert slim_panel.VIEWS == (("center", "Center"),)


def test_phone_motion_keeps_joint_endpoints_connected_and_lengths_fixed():
    p1, p2, p3 = (0, -1.6, 47), (127.4, 20.4, 267.663), (366.834, 20.4, 180.517)
    for seconds in (0, 1, 3, 6, 9, 12):
        a1, a2, d2, d3 = motion_preview.phone_pose(p1, p2, p3, seconds)
        q2 = tuple(x+d for x,d in zip(p2,d2))
        q3 = tuple(x+d for x,d in zip(p3,d3))
        assert math.dist(p1, q2) == pytest.approx(math.dist(p1,p2))
        assert math.dist(q2,q3) == pytest.approx(math.dist(p2,p3))
    assert motion_preview.phone_pose(p1,p2,p3,0)[2:] == ((0,0,0),(0,0,0))
