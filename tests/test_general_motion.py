import math
import sys
from types import SimpleNamespace as NS
import pytest
from integrations.cadwiz_plugin import general_motion as gm, motion_preview
from test_cadwiz_motion_preview import Field, Root, Transform


def gear(name, teeth, x, visible=True):
    profile=NS(NumberOfTeeth=teeth,Modules=2.0,ExternalGear=True)
    place=NS(Base=(x,0,0),Rotation=NS(multVec=lambda v:v))
    return NS(Name=name,Label=name,TypeId='PartDesign::Body',Group=[profile],
              getGlobalPlacement=lambda:place,ViewObject=NS(Visibility=visible,RootNode=Root(),ShapeColor=(.5,.5,.5)))


def test_detects_measured_gears_without_project_or_part_names(monkeypatch):
    monkeypatch.setitem(sys.modules,'FreeCAD',NS(Vector=lambda *v:v))
    a,b=gear('ArbitraryDriver',20,0),gear('UnrelatedWheel',60,80.2)
    assert gm.gear_pair(NS(Objects=[b,a]))[0]['object'] is a
    b.Group[0].Modules=3
    assert gm.gear_pair(NS(Objects=[a,b])) is None
    b.Group[0].Modules=2;b.ViewObject.Visibility=False
    assert gm.gear_pair(NS(Objects=[a,b])) is None
    b.ViewObject.Visibility=True;b.Group[0].ExternalGear=False
    assert gm.gear_pair(NS(Objects=[a,b])) is None


def test_gear_ratio_and_turntable_orbit_are_absolute_and_reversible():
    a,b=gm.gear_angles(8,20,60)
    assert a==pytest.approx(math.tau) and b==pytest.approx(-math.tau/3)
    assert gm.gear_angles(0,20,60)==(0,0)
    p,c=(11,20,33),(1,2,3)
    q=gm.orbit_position(p,c,1.7)
    assert math.dist(p,c)==pytest.approx(math.dist(q,c))
    assert gm.orbit_position(p,c,math.tau)==pytest.approx(p)


def test_gear_drawings_rotate_coaxial_attachments_but_not_bearings_or_case(monkeypatch):
    coin=NS(SoTransform=Transform,SoSeparator=Root,SoScale=lambda:NS(scaleFactor=Field()),SbVec3f=lambda *v:v)
    monkeypatch.setitem(sys.modules,'pivy',NS(coin=coin))
    monkeypatch.setitem(sys.modules,'FreeCAD',NS(Vector=lambda *v:v))
    scene=Root();monkeypatch.setattr(gm,'target_view',lambda d:NS(getSceneGraph=lambda:scene))
    monkeypatch.setattr(motion_preview,'add_shape_drawing',lambda *a:None)
    from integrations.cadwiz_plugin import view_link
    monkeypatch.setattr(view_link,'world_shape',lambda obj:None)
    a,b=gear('Driver',20,0),gear('Driven',60,80.2)
    shaft=gear('OutputShaft',0,80.2);shaft.Group=[]
    bearing=gear('OutputBearing',0,80.2);bearing.Group=[]
    case=gear('Housing',0,35);case.Group=[]
    objects=[a,b,shaft,bearing,case]
    originals={o.Name:list(o.ViewObject.RootNode.children) for o in objects}
    doc=NS(Objects=objects,getObject=lambda name:None)
    preview=motion_preview.MotionPreview(doc)
    assert isinstance(preview,gm.GearTrainPreview)
    assert len(preview.nodes)==3
    preview.frame(8)
    assert [n.rotation.value[1] for i,r,n in preview.nodes]==pytest.approx([math.tau,-math.tau/3,-math.tau/3])
    assert bearing.ViewObject.RootNode.children==originals[bearing.Name]
    assert case.ViewObject.RootNode.children==originals[case.Name]
    preview.stop();preview.stop()
    assert all(o.ViewObject.RootNode.children==originals[o.Name] for o in objects)


def test_static_turntable_restores_camera_and_never_writes_model(monkeypatch):
    class Rotation:
        def __init__(self,*args):self.angle=args[1] if len(args)>1 else 0
        def getValue(self):return (0,0,0,1)
        def multVec(self,v):return (0,100,-100)
        def __mul__(self,other):return self
    class Value:
        def __init__(self,v):self.v=v
        def getValue(self):return self.v
        def setValue(self,*v):self.v=v[0] if len(v)==1 else v
    original_rotation=Rotation()
    camera=NS(position=Value(NS(getValue=lambda:(0,-100,100))),orientation=Value(original_rotation),focalDistance=Value(100))
    view=NS(getCameraNode=lambda:camera,redraw=lambda:None)
    monkeypatch.setitem(sys.modules,'pivy',NS(coin=NS(SbRotation=Rotation,SbVec3f=lambda *v:v)))
    monkeypatch.setattr(gm,'target_view',lambda d:view)
    obj=NS(Shape=NS(isNull=lambda:False),ViewObject=NS(Visibility=True))
    doc=NS(Objects=[obj],getObject=lambda n:None)
    preview=motion_preview.MotionPreview(doc)
    assert isinstance(preview,gm.ModelTurntablePreview)
    assert 'no mechanical motion' in preview.description
    preview.frame(3)
    assert camera.position.v!=(0,-100,100)
    preview.stop();preview.stop()
    assert camera.position.v==(0,-100,100)
    assert doc.Objects==[obj]


def test_hidden_or_empty_models_are_not_falsely_animated():
    hidden=NS(Objects=[NS(Shape=NS(isNull=lambda:False),ViewObject=NS(Visibility=False))])
    assert not gm.drawable(hidden)
