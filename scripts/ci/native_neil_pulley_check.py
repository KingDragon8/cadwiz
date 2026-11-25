# SPDX-License-Identifier: LGPL-2.1-or-later
"""CADWIZ-NEIL-PULLEY-001: representative native geometry, never Neil's files.

Run with FreeCAD's Python on disposable CI/headless workers. No GUI is started.
Pointer/highlight pixel picking is separately required; these tests prove the
native references carried by a selection, not a screenshot's interpretation.
"""
from pathlib import Path
import json
import os
import math
import sys
import tempfile
import time
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
if sys.platform in ('linux', 'darwin'):
    # Bundled Python does not automatically include FreeCAD's native module
    # directory. Keep the same module path in disposable geometry workers.
    bundle = Path(sys.executable).resolve().parent.parent
    if sys.platform == 'darwin':
        bundle = next((p for p in Path(sys.executable).resolve().parents if p.suffix == '.app'), bundle)
    modules = [p for p in bundle.rglob('FreeCAD*.so')
               if p.name == 'FreeCAD.so' or p.name.startswith('FreeCAD.cpython-')]
    if len(modules) != 1:
        raise RuntimeError(f'Expected exactly one FreeCAD native module under {bundle}: {modules}')
    native = str(modules[0].parent)
    sys.path.insert(0, native)
    os.environ['PYTHONPATH'] = native + (os.pathsep + os.environ['PYTHONPATH'] if os.environ.get('PYTHONPATH') else '')
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'CADWiz/src'))
import FreeCAD as App  # noqa: E402
import Part  # noqa: E402
import Sketcher  # noqa: E402
from PySide import QtWidgets  # noqa: E402
from integrations.cadwiz_plugin.engineering_control import (  # noqa: E402
    ControlError, DocumentAuthority, document_revision, file_hash, geometry_reference, resolve_reference,
)
from integrations.cadwiz_plugin.annular_verification import execute, prepare, verify  # noqa: E402
from integrations.cadwiz_plugin.session import PluginSession  # noqa: E402

QT = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
REPORT = {'suite': 'CADWIZ-NEIL-PULLEY-001', 'fixture': 'representative; Neil original pulley files unavailable',
          'visual_pointer_picking': 'not tested by headless suite', 'cases': []}


def pulley(name, path, kind='groove', teeth=False):
    doc = App.newDocument(name)
    body = doc.addObject('PartDesign::Body', 'Pulley')
    base = doc.addObject('Sketcher::SketchObject', 'BaseSketch');body.addObject(base)
    if teeth:
        points=[]
        for tooth in range(18):
            for offset,radius in ((0,40),(.2,42),(.55,42),(.75,40)):
                angle=2*math.pi*(tooth+offset)/18
                points.append(App.Vector(radius*math.cos(angle),radius*math.sin(angle),0))
        for first,second in zip(points,points[1:]+points[:1]):
            base.addGeometry(Part.LineSegment(first,second),False)
    for radius in ((5,) if teeth else (40,5)):
        i = base.addGeometry(Part.Circle(App.Vector(), App.Vector(0, 0, 1), radius), False)
        base.addConstraint(Sketcher.Constraint('Radius', i, radius))
    pad = body.newObject('PartDesign::Pad', 'BasePad');pad.Profile = base;pad.Length = 10
    doc.recompute()
    ring = body.newObject('Sketcher::SketchObject', 'AnnularSketch')
    ring.Placement.Base = App.Vector(0, 0, 10)
    for radius in (20, 24):
        ring.addGeometry(Part.Circle(App.Vector(), App.Vector(0, 0, 1), radius), False)
    feature = body.newObject('PartDesign::Pocket' if kind == 'groove' else 'PartDesign::Pad', 'AnnularFeature')
    feature.Profile = ring;feature.Length = 2
    doc.recompute();doc.saveAs(str(path))
    return doc


def intent(doc, **updates):
    body = doc.getObject('Pulley')
    inner_radius = doc.AnnularSketch.Geometry[0].Radius
    element = next('Face'+str(i+1) for i,f in enumerate(body.Shape.Faces) if type(f.Surface).__name__ == 'Cylinder' and abs(f.Surface.Radius-inner_radius)<1e-7)
    return {'reference': geometry_reference(doc,body,element), 'body':'Pulley','feature':'AnnularFeature','sketch':'AnnularSketch',
            'inner_geometry':0,'outer_geometry':1,'kind':'groove','direction':'inward','amount_mm':0.8,**updates}


class Cases(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix='cadwiz-neil-')
        self.root = Path(self.folder.name)
        self.a = pulley('Variant_A', self.root/'Variant_A.FCStd')
        self.b = pulley('Variant_B', self.root/'Variant_B.FCStd')
        App.setActiveDocument(self.b.Name)
        self.session = PluginSession(app=App, project_root=self.root/'project', log_path=self.root/'calls.jsonl')

    def tearDown(self):
        # Only this test's temporary documents are closed. No owner document path
        # is ever opened by the suite.
        for doc in list(App.listDocuments().values()):
            if str(doc.FileName).startswith(str(self.root)):
                App.closeDocument(doc.Name)
        self.folder.cleanup()

    def variant(self):
        result=self.session.call('document_operation',{'mode':'variant','source_path':str(self.root/'Variant_A.FCStd'),'target_path':str(self.root/'New_Variant.FCStd')})
        self.assertTrue(result['ok'],result)
        return self.session._document(result['document'])

    def edit(self, **updates):
        return execute(self.a, intent(self.a, **updates), self.root/'result.FCStd')

    def test_T01_source_A_while_B_active(self):
        target=self.variant();self.assertEqual(file_hash(target.FileName),file_hash(self.a.FileName));self.assertEqual(App.ActiveDocument.Name,target.Name)

    def test_T02_separate_copy(self):
        original=file_hash(self.a.FileName);target=self.variant();self.assertNotEqual(target.Name,self.a.Name);self.assertEqual(file_hash(self.a.FileName),original)

    def test_T03_protected_B(self):
        self.variant();r=self.session.call('edit_object',{'document':self.b.Name,'parameters':{'BasePad.Length':20}});self.assertFalse(r['ok']);self.assertEqual(r['verification_status'],'TARGET UNRESOLVED')

    def test_T04_native_selected_face_reference(self):
        from ai_freecad_core.visual_communications.anchored import Camera
        from integrations.cadwiz_plugin.view_link import ray_hit
        camera=Camera('orthographic',(0,0,100),(0,0,0,1),height=100)
        u,v=camera.project((22,0,8),1)
        anchor=ray_hit(camera,u,v,1,[self.a.Pulley])
        self.assertTrue(anchor.on_model);self.assertAlmostEqual(anchor.point[2],8)
        r=geometry_reference(self.a,self.a.Pulley,anchor.element);self.assertEqual(r['resolution'],'GEOMETRY RESOLVED')

    def test_T05_native_highlight_reference(self):
        from ai_freecad_core.visual_communications.anchored import ModelAnchor
        from integrations.cadwiz_plugin.view_link import face_outline
        r=intent(self.a)['reference']
        outline=face_outline(self.a,ModelAnchor((20,0,9),'Pulley',r['element'],True))
        self.assertGreater(len(outline),4);self.assertTrue(all(p.element==r['element'] for p in outline))
        self.assertEqual(resolve_reference(self.a,r)['signature'],r['signature'])

    def test_T06_inward(self):
        _,_,e=self.edit();self.assertAlmostEqual(e['inner_radius_change_mm'],-.8);self.assertAlmostEqual(e['outer_radius_change_mm'],0)

    def test_T07_outward(self):
        _,_,e=self.edit(direction='outward');self.assertAlmostEqual(e['outer_radius_change_mm'],.8);self.assertAlmostEqual(e['inner_radius_change_mm'],0)

    def test_T08_reversed_change_rejected(self):
        plan=prepare(self.a,intent(self.a));self.a.AnnularSketch.addConstraint(Sketcher.Constraint('Radius',1,24.8));self.a.recompute()
        with self.assertRaises(ControlError):verify(self.a,plan)

    def test_T09_protected_boundary(self):
        _,_,e=self.edit();self.assertEqual(e['outer_radius_change_mm'],0)

    def test_T10_chord_substitution_rejected(self):
        plan=prepare(self.a,intent(self.a));bad=self.a.Pulley.Shape.cut(Part.makeBox(8,8,4,App.Vector(17,0,7)))
        self.a.Pulley.Tip.Shape=bad
        with self.assertRaises(ControlError):verify(self.a,plan)

    def test_T11_mating_ridge_and_clearance(self):
        female,_,_=self.edit()
        ridge=pulley('Male',self.root/'Male.FCStd','ridge')
        # The mating request independently specifies a 0.2 mm radial clearance.
        ridge.AnnularSketch.addConstraint(Sketcher.Constraint('Radius',0,20.2));ridge.AnnularSketch.addConstraint(Sketcher.Constraint('Radius',1,23.8));ridge.recompute()
        doc,_,e=execute(ridge,intent(ridge,kind='ridge'),self.root/'male-result.FCStd')
        radii=sorted({round(f.Surface.Radius,6) for f in doc.Pulley.Shape.Faces if type(f.Surface).__name__=='Cylinder'})
        self.assertIn(19.4,radii);self.assertIn(23.8,radii);self.assertAlmostEqual(e['inner_radius_change_mm'],-.8)
        measured_female=sorted({round(f.Surface.Radius,6) for f in female.Pulley.Shape.Faces if type(f.Surface).__name__=='Cylinder'})
        self.assertAlmostEqual(19.4-measured_female[1],.2)
        self.assertAlmostEqual(measured_female[2]-23.8,.2)
        # Assemble the male ridge into the female groove using an explicit
        # mating transform; measure actual assembled B-rep interference.
        male=doc.Pulley.Shape.copy();male.rotate(App.Vector(),App.Vector(1,0,0),180);male.translate(App.Vector(0,0,20))
        female_shape=female.Pulley.Shape.copy()
        overlap=female_shape.common(male).Volume
        # Base halves touch at z=10; ridge occupies z=8..10 inside the groove.
        zone=Part.makeCylinder(24,2,App.Vector(0,0,8)).cut(Part.makeCylinder(19.2,2,App.Vector(0,0,8)))
        self.assertLess(female_shape.common(male).common(zone).Volume,.001)
        self.assertLess(overlap,.001)

    def test_T12_depth_independent(self):
        _,_,e=self.edit(direction='none',amount_mm=0,depth_change_mm=.5);self.assertEqual(e['width_change_mm'],0);self.assertEqual(e['depth_change_mm'],.5)

    def test_T13_shaft_and_unrelated_material(self):
        App.closeDocument(self.a.Name);self.a=pulley('Variant_A',self.root/'Variant_A.FCStd',teeth=True)
        other=self.a.addObject('PartDesign::Body','Unrelated')
        sketch=other.newObject('Sketcher::SketchObject','UnrelatedSketch');sketch.Placement.Base=App.Vector(100,0,0)
        i=sketch.addGeometry(Part.Circle(App.Vector(),App.Vector(0,0,1),3),False);sketch.addConstraint(Sketcher.Constraint('Radius',i,3))
        pad=other.newObject('PartDesign::Pad','UnrelatedPad');pad.Profile=sketch;pad.Length=4;self.a.recompute()
        before=other.Shape.copy()
        doc,_,e=self.edit();self.assertTrue(e['unrelated_bodies_unchanged']);self.assertTrue(any(type(f.Surface).__name__=='Cylinder' and abs(f.Surface.Radius-5)<1e-7 for f in doc.Pulley.Shape.Faces))
        self.assertLess(doc.Unrelated.Shape.cut(before).Volume+before.cut(doc.Unrelated.Shape).Volume,.001)

    def test_T14_underconstrained_sketch(self):
        self.assertEqual(len(self.a.AnnularSketch.Constraints),0);doc,_,_=self.edit();self.assertGreater(len(doc.AnnularSketch.Constraints),0)

    def test_T15_history_preserved(self):
        doc,_,_=self.edit();self.assertEqual(doc.Pulley.Tip.TypeId,'PartDesign::Pocket');self.assertEqual(doc.AnnularFeature.Profile[0],doc.AnnularSketch)

    def test_T16_stale_reference_rejected(self):
        r=intent(self.a)['reference'];self.a.AnnularSketch.addConstraint(Sketcher.Constraint('Radius',0,19));self.a.recompute()
        with self.assertRaises(ControlError):resolve_reference(self.a,r)

    def test_T17_same_geometry_reresolves(self):
        r=intent(self.a)['reference'];r['revision']='old';self.assertTrue(resolve_reference(self.a,r)['re_resolved'])

    def test_T18_failed_operation_keeps_original(self):
        original=file_hash(self.a.FileName)
        with self.assertRaises(ControlError):self.edit(amount_mm=100)
        self.assertEqual(file_hash(self.a.FileName),original)

    def test_T19_source_integrity(self):
        self.variant();self.session.document_authority.check_source(App)
        self.a.BasePad.Length=11;self.a.recompute()
        with self.assertRaises(ControlError):self.session.document_authority.check_source(App)

    def test_T20_native_reopen(self):
        _,health,e=self.edit();self.assertTrue(health['roundtrip']);self.assertTrue(e['save_reopen']);self.assertAlmostEqual(e['reopened']['inner_radius_change_mm'],-.8)

    def test_T21_no_false_verification(self):
        self.variant();r=self.session.call('annular_edit',{'document':self.b.Name,'intent':{}});self.assertFalse(r['ok']);self.assertNotEqual(r.get('verification_status'),'VERIFIED SUCCESS')

    def test_T22_ambiguous_names(self):
        self.a.Label=self.b.Label='Pulley'
        from integrations.cadwiz_plugin.session import PlainError
        with self.assertRaises(PlainError):self.session._document('Pulley')

    def test_T23_multi_step_authority(self):
        target=self.variant();App.setActiveDocument(self.b.Name);self.session.document_authority.check(App,target)
        with self.assertRaises(ControlError):self.session.document_authority.check(App,self.b)

    def test_T24_actual_geometry_not_parameters(self):
        plan=prepare(self.a,intent(self.a));plan['sketch'].addConstraint(Sketcher.Constraint('Radius',0,19.2))
        # Deliberately omit recompute. The parameter looks right, actual solid is wrong.
        with self.assertRaises(ControlError):verify(self.a,plan)

    def test_T25_visual_mark_not_resolved(self):
        r=self.session.call('resolve_geometry',{'document':self.a.Name});self.assertFalse(r['ok']);self.assertEqual(r['verification_status'],'TARGET UNRESOLVED')

    def test_T26_explicit_existing_edit(self):
        r=self.session.call('document_operation',{'mode':'modify','document':self.a.Name});self.assertTrue(r['ok']);self.session.document_authority.check(App,self.a)

    def test_T27_exact_path_beats_similar_name(self):
        self.assertIs(self.session._document(str(self.root/'Variant_A.FCStd')),self.a)

    def test_T28_diametric_units(self):
        _,_,e=self.edit(dimension='diametric',amount_mm=1.6);self.assertAlmostEqual(e['inner_radius_change_mm'],-.8)

    def test_T29_unsupported_request_does_not_mutate(self):
        before=document_revision(self.a)
        for _ in range(2):
            with self.assertRaises(ControlError):prepare(self.a,intent(self.a,direction='screen-left'))
        self.assertEqual(document_revision(self.a),before)

    def test_T30_read_only_authority(self):
        self.session.document_authority=DocumentAuthority('inspect',self.a.FileName,self.a.Name)
        r=self.session.call('edit_object',{'document':self.a.Name,'script':'raise RuntimeError()'});self.assertFalse(r['ok']);self.assertEqual(r['verification_status'],'USER INPUT REQUIRED')

    def test_T31_real_worker_and_session_path(self):
        target=self.variant();operation=intent(target)
        result=self.session.call('annular_edit',{'document':target.Name,'intent':operation})
        self.assertTrue(result['ok'],result);self.assertEqual(result['verification_status'],'VERIFIED SUCCESS')
        self.assertAlmostEqual(result['dimensional_verification']['inner_radius_change_mm'],-.8)
        self.session.document_authority.check_source(App)
        failed=self.session.call('annular_edit',{'document':self.b.Name,'intent':{}})
        self.assertFalse(failed['ok']);self.assertNotEqual(self.session.state['verification_status'],'VERIFIED SUCCESS')

    def test_T32_wrong_shaft_selection_rejected(self):
        operation=intent(self.a)
        face=next('Face'+str(i+1) for i,f in enumerate(self.a.Pulley.Shape.Faces) if type(f.Surface).__name__=='Cylinder' and abs(f.Surface.Radius-5)<1e-7)
        operation['reference']=geometry_reference(self.a,self.a.Pulley,face)
        with self.assertRaises(ControlError):prepare(self.a,operation)

    def test_T33_transformed_geometry(self):
        self.a.Pulley.Placement=App.Placement(App.Vector(12,-7,3),App.Rotation(App.Vector(1,1,0),35));self.a.recompute()
        _,_,e=self.edit();self.assertAlmostEqual(e['inner_radius_change_mm'],-.8)

    def test_T34_diameter_driver(self):
        self.a.AnnularSketch.addConstraint(Sketcher.Constraint('Diameter',0,40));self.a.recompute()
        _,_,e=self.edit();self.assertAlmostEqual(e['inner_radius_change_mm'],-.8)

    def test_T35_native_transaction_rolls_back_reversed_mutator(self):
        from unittest.mock import patch
        from integrations.cadwiz_plugin import annular_verification as module
        before=document_revision(self.a);original=module.circle_parameter
        def incorrect(sketch,index,radius):original(sketch,index,20.8 if index==0 else radius)
        with patch.object(module,'circle_parameter',incorrect):
            with self.assertRaises(ControlError):self.edit()
        self.assertEqual(document_revision(self.a),before)

    def test_T36_native_history_downgrade_rejected(self):
        target=self.variant();before=file_hash(target.FileName)
        code="shape=doc.Pulley.Shape.copy()\ndoc.removeObject('Pulley')\nreplacement=doc.addObject('Part::Feature','Replacement')\nreplacement.Shape=shape\n"
        result=self.session.call('build_model',{'document':target.Name,'code':code})
        self.assertFalse(result['ok'],result);self.assertNotEqual(result.get('verification_status'),'VERIFIED SUCCESS')
        self.assertEqual(file_hash(self.session.document_authority.target_path),before)

    def test_T37_concurrent_disk_save_preserved(self):
        import shutil
        target=self.variant();executor=self.session._executor(target);executor._ensure_backup()
        shutil.copyfile(self.b.FileName,target.FileName)
        newer=file_hash(target.FileName)
        with self.assertRaises(ControlError):executor.check_operation_revision(executor.operation_revision)
        self.assertEqual(file_hash(target.FileName),newer)

    def test_T38_non_geometry_edit_preserved(self):
        target=self.variant();executor=self.session._executor(target);executor._ensure_backup()
        target.Pulley.Label='New manual label'
        with self.assertRaises(ControlError):executor.check_operation_revision(executor.operation_revision)
        self.assertEqual(target.Pulley.Label,'New manual label')

    def test_T39_unbound_legacy_edit_cannot_touch_active_variant(self):
        before=file_hash(self.b.FileName)
        result=self.session.call('build_model',{'code':"doc.BasePad.Length=20"})
        self.assertFalse(result['ok']);self.assertEqual(result['verification_status'],'USER INPUT REQUIRED')
        self.assertEqual(file_hash(self.b.FileName),before)

    def test_T40_annular_floor_reference_survives_real_worker_snapshot(self):
        target=self.variant();operation=intent(target)
        floor=next('Face'+str(i+1) for i,f in enumerate(target.Pulley.Shape.Faces)
                   if type(f.Surface).__name__=='Plane' and abs(f.CenterOfMass.z-8)<1e-7)
        operation['reference']=geometry_reference(target,target.Pulley,floor)
        result=self.session.call('annular_edit',{'document':target.Name,'intent':operation})
        self.assertTrue(result['ok'],result)
        self.assertAlmostEqual(result['dimensional_verification']['inner_radius_change_mm'],-.8)

    def test_T41_worker_rebind_requires_unique_geometry_and_rejects_changed_shape(self):
        operation=intent(self.a)
        original=operation['reference']
        other=next('Face'+str(i+1) for i in range(len(self.a.Pulley.Shape.Faces)) if 'Face'+str(i+1)!=original['element'])
        operation['reference']={**original,'element':other}
        self.assertEqual(prepare(self.a,operation,worker_copy=True)['body_name'],'Pulley')
        operation['reference']={**original,'signature':'0'*64,
                                'geometry':{**original['geometry'],'area':original['geometry']['area']+1}}
        with self.assertRaises(ControlError):prepare(self.a,operation,worker_copy=True)

    def test_T42_display_tessellation_cannot_change_native_reference_or_revision(self):
        target=self.variant()
        floor=next('Face'+str(i+1) for i,f in enumerate(target.Pulley.Shape.Faces)
                   if type(f.Surface).__name__=='Plane' and abs(f.CenterOfMass.z-8)<1e-7)
        before=geometry_reference(target,target.Pulley,floor)
        revision=document_revision(target)
        target.Pulley.Shape.tessellate(2.0)
        after=geometry_reference(target,target.Pulley,floor)
        self.assertEqual(before['signature'],after['signature'])
        self.assertEqual(document_revision(target),revision)
        self.assertAlmostEqual(after['geometry']['bounds'][1],-24,places=7)
        self.assertAlmostEqual(after['geometry']['bounds'][4],24,places=7)
        result=self.session.call('annular_edit',{'document':target.Name,'intent':intent(target,reference=after)})
        self.assertTrue(result['ok'],result)


if __name__ == '__main__':
    class Result(unittest.TextTestResult):
        def startTest(self,test):self.started=time.monotonic();super().startTest(test)
        def addSuccess(self,test):REPORT['cases'].append({'case':test._testMethodName,'status':'PASS','seconds':round(time.monotonic()-self.started,3)});super().addSuccess(test)
        def addFailure(self,test,error):REPORT['cases'].append({'case':test._testMethodName,'status':'FAIL'});super().addFailure(test,error)
        def addError(self,test,error):REPORT['cases'].append({'case':test._testMethodName,'status':'ERROR'});super().addError(test,error)
    result=unittest.TextTestRunner(verbosity=2,resultclass=Result).run(unittest.defaultTestLoader.loadTestsFromTestCase(Cases))
    Path('neil-pulley-report.json').write_text(json.dumps(REPORT,indent=2))
    raise SystemExit(0 if result.wasSuccessful() else 1)
