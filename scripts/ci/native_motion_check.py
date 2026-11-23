# SPDX-License-Identifier: LGPL-2.1-or-later
from pathlib import Path
from types import SimpleNamespace as NS
import sys,math,json,os
import FreeCAD as A,Part
from pivy import coin
sys.path.insert(0,str(Path(A.getHomePath())/'Mod/PartDesign'))
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'CADWiz/src'))
import InvoluteGearFeature
from integrations.cadwiz_plugin import general_motion as gm,motion_preview as mp
file=Path(json.loads(Path(os.environ.get('CADWIZ_GEARBOX_REPORT','herringbone-report.json')).read_text(encoding='utf-8'))['model'])
d=A.openDocument(str(file))
objects=[]
for body in [o for o in d.Objects if o.TypeId=='PartDesign::Body']:
 vo=NS(Visibility=True,RootNode=coin.SoSeparator(),ShapeColor=(.5,.5,.5))
 objects.append(NS(Name=body.Name,Label=body.Label,TypeId=body.TypeId,Group=body.Group,
   getGlobalPlacement=body.getGlobalPlacement,getParentGeoFeatureGroup=body.getParentGeoFeatureGroup,
   Shape=body.Shape,Placement=body.Placement,ViewObject=vo,CADWizAppearance=[]))
doc=NS(Objects=objects,getObject=lambda name:next((o for o in objects if o.Name==name),None))
scene=coin.SoSeparator();gm.target_view=lambda doc:NS(getSceneGraph=lambda:scene)
before=[tuple(o.Placement.toMatrix().A) for o in objects]
print('Constructing native Coin gear preview',flush=True)
p=mp.MotionPreview(doc);assert isinstance(p,gm.GearTrainPreview)
p.frame(1)
rotations=[]
for index,root,node in p.nodes:
 v=node.rotation.getValue().multVec(coin.SbVec3f(1,0,0));angle=math.atan2(v[1],v[0])
 expected=math.pi/4 if index==0 else -math.pi/12
 assert abs(angle-expected)<1e-5,(index,angle)
 rotations.append([index,angle])
count=len(p.nodes);p.stop();p.stop()
assert scene.getNumChildren()==0
assert before==[tuple(o.Placement.toMatrix().A) for o in objects]
assert all(o.ViewObject.RootNode.getNumChildren()==0 for o in objects)
print('Native gear ratio and cleanup passed',flush=True)
camera=coin.SoOrthographicCamera();camera.position.setValue(100,-100,100)
camera.pointAt(coin.SbVec3f(0,0,0),coin.SbVec3f(0,0,1));camera.focalDistance.setValue(math.sqrt(30000))
view=NS(getCameraNode=lambda:camera,redraw=lambda:None);gm.target_view=lambda doc:view
static=NS(Objects=[NS(Shape=Part.makeBox(24,17,13),ViewObject=NS(Visibility=True))],getObject=lambda n:None)
initial_position=tuple(camera.position.getValue());initial_rotation=tuple(camera.orientation.getValue().getValue())
p=mp.MotionPreview(static);assert isinstance(p,gm.ModelTurntablePreview)
p.frame(2.3);assert tuple(camera.position.getValue())!=initial_position
p.stop();p.stop()
assert tuple(camera.position.getValue())==initial_position
assert all(abs(a-b)<1e-6 for a,b in zip(tuple(camera.orientation.getValue().getValue()),initial_rotation))
result={'status':'PASS','scope':'Native FreeCAD shapes and actual Pivy/Coin transforms, not GUI-button acceptance',
 'gear_teeth':[20,60],'moving_drawings':count,'native_rotations_radians':rotations,
 'original_drawings_and_placements_restored':True,'native_static_camera_restored':True}
Path(os.environ.get('CADWIZ_MOTION_REPORT','native-motion-report.json')).write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2),flush=True)
A.closeDocument(d.Name);sys.stdout.flush();os._exit(0)
