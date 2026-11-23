# SPDX-License-Identifier: LGPL-2.1-or-later
"""Disposable native double-helical fixture; no user files, GUI or AI inference.

LL-051: sample generated intermediate sections, not only source profiles.
The separate host-Python checker evaluates the exported polygons.
"""
from pathlib import Path
import hashlib
import json
import math
import os
import sys
import tempfile
import traceback


def run():
    import FreeCAD as A
    import Part
    import Sketcher
    sys.path.insert(0, str(Path(A.getHomePath()) / 'Mod/PartDesign'))
    import InvoluteGearFeature
    folder = Path(tempfile.mkdtemp(prefix='cadwiz-herringbone-094-'))
    d = A.newDocument('SyntheticHerringboneTrial')
    params = d.addObject('Spreadsheet::Sheet', 'Params')
    values = [('NormalModule', '2'), ('PinionTeeth', '20'), ('WheelTeeth', '60'),
              ('HelixAngle', '25'), ('NormalPressureAngle', '20'), ('HalfWidth', '10'), ('BoreRadius', '5'),
              ('TransverseModule', '=NormalModule/cos(HelixAngle*1 deg)'),
              ('TransversePressureAngle', '=atan(tan(NormalPressureAngle*1 deg)/cos(HelixAngle*1 deg))'),
              ('PinionRadius', '=TransverseModule*PinionTeeth/2'), ('WheelRadius', '=TransverseModule*WheelTeeth/2'),
              ('CenterDistance', '=PinionRadius+WheelRadius'),
              ('PinionTwist', '=HalfWidth*tan(HelixAngle*1 deg)/PinionRadius'),
              ('WheelTwist', '=HalfWidth*tan(HelixAngle*1 deg)/WheelRadius')]
    for i, (name, value) in enumerate(values, 1):
        params.set('A'+str(i), name); params.set('B'+str(i), value); params.setAlias('B'+str(i), name)
    d.recompute()
    for name, left in [('Pinion', False), ('Wheel', True)]:
        print('Building native opposite-hand helices: '+name, flush=True)
        body = d.addObject('PartDesign::Body', name)
        profiles = []
        for half in [0, 1]:
            profile = InvoluteGearFeature.makeInvoluteGear(name+'Profile'+str(half)); body.addObject(profile)
            profile.setExpression('NumberOfTeeth', 'Params.'+name+'Teeth')
            profile.setExpression('Modules', 'Params.TransverseModule')
            profile.setExpression('PressureAngle', 'Params.TransversePressureAngle')
            profile.setExpression('AddendumCoefficient', 'cos(Params.HelixAngle*1 deg)')
            profile.setExpression('DedendumCoefficient', '1.25*cos(Params.HelixAngle*1 deg)')
            if half:
                profile.setExpression('Placement.Base.z', 'Params.HalfWidth')
                profile.Placement.Rotation = A.Rotation(A.Vector(0, 0, 1), 1)
                profile.setExpression('Placement.Rotation.Angle', 'Params.'+name+'Twist*'+str(-1 if left else 1)+'*1 rad')
            d.recompute()
            h = body.newObject('PartDesign::AdditiveHelix', name+('UpperHelix' if half else 'LowerHelix'))
            h.Profile = profile; h.ReferenceAxis = (profile, ['N_Axis']); h.Mode = 2
            h.setExpression('Height', 'Params.HalfWidth')
            h.setExpression('Turns', 'Params.'+name+'Twist/(2*pi)')
            h.LeftHanded = left if not half else not left
            d.recompute(); assert not h.Shape.isNull(), (name, half, h.State)
            profiles.append(profile)
        bore = body.newObject('Sketcher::SketchObject', name+'BoreProfile')
        bore.addGeometry(Part.Circle(A.Vector(), A.Vector(0, 0, 1), 5), False)
        bore.addConstraint(Sketcher.Constraint('Coincident', 0, 3, -1, 1))
        radius = bore.addConstraint(Sketcher.Constraint('Radius', 0, 5.0))
        bore.setExpression('Constraints['+str(radius)+']', 'Params.BoreRadius')
        bore.setExpression('Placement.Base.z', '2*Params.HalfWidth')
        pocket = body.newObject('PartDesign::Pocket', name+'ShaftBore')
        pocket.Profile = bore; pocket.setExpression('Length', '2*Params.HalfWidth')
        if name == 'Wheel':
            body.setExpression('Placement.Base.x', 'Params.CenterDistance')
            body.Placement.Rotation = A.Rotation(A.Vector(0, 0, 1), 183)
        d.recompute(); assert bore.FullyConstrained

    def verify(doc):
        assert abs(doc.Params.WheelTeeth/doc.Params.PinionTeeth-3) < 1e-9
        assert abs(doc.Params.CenterDistance-80/math.cos(math.radians(25))) < 1e-6
        for name in ['Pinion', 'Wheel']:
            body = doc.getObject(name)
            assert body.Shape.isValid() and len(body.Shape.Solids) == 1
            assert abs(body.Shape.BoundBox.ZLength-2*doc.Params.HalfWidth) < 1e-5
            assert doc.getObject(name+'BoreProfile').FullyConstrained
        return {'ratio': 3, 'center_distance_mm': doc.Params.CenterDistance,
                'pinion_volume_mm3': doc.Pinion.Shape.Volume, 'wheel_volume_mm3': doc.Wheel.Shape.Volume}

    def samples(doc):
        data = {}
        for name, sign in [('Pinion', 1), ('Wheel', -1)]:
            profile = doc.getObject(name+'Profile0')
            shape = doc.getObject(name+'UpperHelix').Shape
            height = 2*doc.Params.HalfWidth
            item = {'height_mm': height, 'sampling_deflection_mm': .005,
                    'twist_deg': sign*float(getattr(doc.Params, name+'Twist'))*180/math.pi,
                    'reference': [[v.x, v.y] for v in profile.Shape.Wires[0].discretize(Deflection=.005)], 'sections': []}
            for fraction in [.125, .375, .625, .875]:
                z = fraction*height; wires = shape.slice(A.Vector(0, 0, 1), z)
                assert len(wires) == 1
                item['sections'].append({'z': z, 'points': [[[v.x, v.y] for v in w.discretize(Deflection=.005)] for w in wires]})
            data[name] = item
        return data

    baseline = verify(d)
    first = folder/'01-original.FCStd'; d.saveAs(str(first)); digest = hashlib.sha256(first.read_bytes()).hexdigest()
    A.closeDocument(d.Name); d = A.openDocument(str(first)); d.recompute(); verify(d)
    Path(os.environ.get('CADWIZ_GEARBOX_SAMPLES', 'herringbone-sections.json')).write_text(json.dumps(samples(d)), encoding='utf-8')
    d.Params.set('B6', '12'); d.recompute(); verify(d)
    second = folder/'02-wider-gears.FCStd'; d.saveAs(str(second))
    width_volume = d.Pinion.Shape.Volume
    d.Params.set('B7', '6'); d.recompute(); verify(d)
    assert d.Pinion.Shape.Volume < width_volume
    third = folder/'03-larger-bores.FCStd'; d.saveAs(str(third))
    A.closeDocument(d.Name); d = A.openDocument(str(third)); d.recompute(); verify(d)
    assert hashlib.sha256(first.read_bytes()).hexdigest() == digest
    report = {'status': 'PASS', 'scope': 'Native disposable fixture; generated-section comparison is a separate required check.',
              'assumptions': {'teeth': [20, 60], 'normal_module_mm': 2, 'helix_deg': 25, 'initial_face_width_mm': 20},
              'baseline': baseline, 'saved_reopened_recomputed': True, 'prior_revision_unchanged': True,
              'native_features': ['Involute profiles', 'PartDesign AdditiveHelix, opposite hands', 'Constrained bore pockets'],
              'model': str(third), 'artifacts': str(folder),
              'limitations': ['Not loaded contact/backlash/strength qualification.', 'No paid AI inference or user models.']}
    Path(os.environ.get('CADWIZ_GEARBOX_REPORT', 'herringbone-report.json')).write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2), flush=True); A.closeDocument(d.Name)


# FreeCADCmd executes scripts with its own module name; do not silently skip.
result = 0
try:
    run()
except BaseException:
    traceback.print_exc(); result = 1
sys.stdout.flush(); sys.stderr.flush(); os._exit(result)
