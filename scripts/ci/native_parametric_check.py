# SPDX-License-Identifier: LGPL-2.1-or-later
"""Real FreeCAD regression: native features, linked edits, persistence and exceptions."""
from pathlib import Path
import sys, tempfile, json, os, hashlib
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(Path(__file__).resolve().parent))
sys.path.insert(0,str(ROOT/'CADWiz/src'))

def run():
    work=Path(tempfile.mkdtemp(prefix='cadwiz-native-086-'))
    os.environ['CADWIZ_SETTINGS_FILE']=str(work/'settings.json')
    os.environ['LOCALAPPDATA']=str(work/'local')
    import FreeCAD as A, Part, Sketcher
    from integrations.ai_master.parametric_checks import verify_saved,native_evidence,STATUS,broken,remember_references
    from integrations.ai_master.freecad_facts import measure_document
    from native_fixtures import plate

    results={}
    d=plate(); before=measure_document(d)
    assert before.editability.level.name=='E2'
    assert len(before.holes)==4, before.holes
    d,h=verify_saved(d,work/'plate.FCStd',owned=True)
    assert h['level']=='E3' and h['roundtrip']
    assert measure_document(d).editability.level.name=='E3'
    assert all(not o.Visibility for o in d.Objects if o.TypeId in ('App::Origin','App::Line','App::Plane','App::Point'))
    assert d.Pocket.Visibility and not d.Pad.Visibility
    original=d.Body.Shape.Volume;d.Params.set('A1','45');d.recompute();assert d.Body.Shape.isValid() and d.Body.Shape.Volume>original
    original=d.Body.Shape.Volume;d.Params.set('A4','5');d.recompute();assert d.Body.Shape.isValid() and d.Body.Shape.Volume<original
    assert native_evidence(d)['verified_parameters']==0
    results['plate_four_holes_width_diameter_roundtrip_visibility']='PASS'
    d,h=verify_saved(d,work/'changed-plate.FCStd',owned=True)
    d.X_Axis.Visibility=True;remember_references(d)
    d,h=verify_saved(d,work/'reference-preserved.FCStd',owned=True)
    assert d.X_Axis.Visibility and not d.Y_Axis.Visibility
    results['intentional_reference_preserved']='PASS'
    # A dependent upper pad whose attachment follows the base thickness.
    d=plate('Bracket');b=d.Body
    s=b.newObject('Sketcher::SketchObject','UprightProfile')
    for i,(a,z) in enumerate([((0,0),(40,0)),((40,0),(40,5)),((40,5),(0,5)),((0,5),(0,0))]):
     s.addGeometry(Part.LineSegment(A.Vector(a[0],a[1],0),A.Vector(z[0],z[1],0)),False)
     s.addConstraint(Sketcher.Constraint('Block',i))
    s.setExpression('Placement.Base.z','Pad.Length')
    p=b.newObject('PartDesign::Pad','Upright');p.Profile=s;p.Length=20;d.recompute()
    d,h=verify_saved(d,work/'bracket.FCStd',owned=True)
    assert h['level']=='E3',h
    old=d.Body.Shape.BoundBox.ZLength;d.Params.set('A3','7');d.recompute()
    assert d.Body.Shape.isValid() and d.Body.Shape.BoundBox.ZLength>old
    assert abs(d.UprightProfile.Placement.Base.z-7)<0.001
    results['bracket_dependent_features_after_reopen']='PASS'
    # A named spreadsheet and Body containing a finished solid are not parametric.
    f=A.newDocument('Counterfeit');b=f.addObject('PartDesign::Body','Body');v=b.newObject('PartDesign::Feature','Finished');v.Shape=Part.makeBox(40,30,5)
    p=f.addObject('Spreadsheet::Sheet','Params');p.set('A1','40');p.setAlias('A1','Width');f.recompute()
    assert measure_document(f).editability.level.name=='E1'
    f,health=verify_saved(f,work/'fixed.FCStd',owned=True,exception='Imported original geometry has no retained sketch history; retained as a direct solid.')
    assert health['level']=='E1' and not health['changed_parameters']
    results['counterfeit_parametric_rejected']='PASS'
    # Two parametric jaws (synthetic fixture, not a reconstruction of Neil's file).
    c=plate('ClampFixture');group=c.addObject('App::Part','Assembly');group.addObject(c.Body)
    a=c.addObject('PartDesign::Body','SecondJaw');group.addObject(a);s=a.newObject('Sketcher::SketchObject','JawProfile')
    for i,(p,q) in enumerate([((0,0),(40,0)),((40,0),(40,30)),((40,30),(0,30)),((0,30),(0,0))]):
     s.addGeometry(Part.LineSegment(A.Vector(p[0],p[1],0),A.Vector(q[0],q[1],0)),False)
     s.addConstraint(Sketcher.Constraint('Block',i))
    p=a.newObject('PartDesign::Pad','JawPad');p.Profile=s;p.setExpression('Length','Params.Thickness');a.Placement.Base.z=15;c.recompute()
    c,h=verify_saved(c,work/'synthetic-clamp.FCStd',owned=True)
    assert h['level']=='E3' and set(h['verified_components'])=={'Body','SecondJaw'},h
    results['synthetic_clamp_multiple_components']='PASS'
    c.JawPad.Profile=None;c.recompute()
    assert broken(c) or not native_evidence(c)['functional_tree']
    results['broken_dependency_detected']='PASS'
    for name in list(A.listDocuments()):A.closeDocument(name)
    print(json.dumps({'results':results,'scratch':str(work),'scope':'real native FreeCAD; no AI provider, no GUI instance, no original Singer16 file'},indent=2))


import traceback
result = 0
try:
    run()
except BaseException:
    traceback.print_exc()
    result = 1
sys.stdout.flush()
sys.stderr.flush()
os._exit(result)
