"""Picking must resolve only the winning solid's faces, without changing its anchor."""
from types import SimpleNamespace as NS
import sys

from integrations.cadwiz_plugin import view_link


class Point:
    def __init__(self, z):
        self.x, self.y, self.z = 0., 0., z

    def __getitem__(self, index):
        return (self.x, self.y, self.z)[index]


class Shape:
    Solids = [True]

    def __init__(self, depths):
        self.depths = depths
        self.face_reads = 0
        self.distance_calls = 0

    def isNull(self):
        return False

    def section(self, _line):
        return NS(Vertexes=[NS(Point=Point(z)) for z in self.depths])

    @property
    def Faces(self):
        self.face_reads += 1
        def distance(value):
            self.distance_calls += 1
            return (value,)
        return [NS(distToShape=lambda vertex: distance(2)),
                NS(distToShape=lambda vertex: distance(0))]


def install(monkeypatch, objects):
    monkeypatch.setitem(sys.modules, 'FreeCAD', NS(Vector=lambda *v: v))
    monkeypatch.setitem(sys.modules, 'Part', NS(LineSegment=lambda *args: NS(toShape=lambda: None)))
    monkeypatch.setattr(view_link, '_visible_objects', lambda: objects)
    return NS(ray=lambda *args: ((0., 0., 0.), (0., 0., 1.)))


def test_only_final_nearest_hit_searches_faces_once(monkeypatch):
    far, near = Shape([12, 10]), Shape([7, 5])
    camera = install(monkeypatch, [NS(Name='Far', Shape=far), NS(Name='Near', Shape=near)])
    hit = view_link.ray_hit(camera, .5, .5, 1.)
    assert (hit.obj, hit.element, hit.point) == ('Near', 'Face2', (0., 0., 5))
    assert far.face_reads == 0
    assert near.face_reads == 1
    assert near.distance_calls == 2


def test_miss_performs_no_face_search(monkeypatch):
    shape = Shape([])
    camera = install(monkeypatch, [NS(Name='Miss', Shape=shape)])
    assert view_link.ray_hit(camera, .5, .5, 1.) is None
    assert shape.face_reads == 0


def test_nearer_mesh_cancels_pending_solid_resolution(monkeypatch):
    shape = Shape([5])
    mesh = NS(copy=lambda: NS(transform=lambda matrix: None,
                             nearestFacetOnRay=lambda *args: {3: (0., 0., 2.)}))
    obj = NS(Name='Mesh', TypeId='Mesh::Feature', Mesh=mesh,
             Placement=NS(toMatrix=lambda: None))
    camera = install(monkeypatch, [NS(Name='Solid', Shape=shape), obj])
    hit = view_link.ray_hit(camera, .5, .5, 1.)
    assert (hit.obj, hit.element) == ('Mesh', 'Facet4')
    assert shape.face_reads == 0
