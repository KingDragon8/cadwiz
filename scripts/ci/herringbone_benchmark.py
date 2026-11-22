# SPDX-License-Identifier: LGPL-2.1-or-later
"""Synthetic herringbone trial authorized by the owner; NOT Neil's dimensions.

Run with native FreeCADCmd. Uses FreeCAD's included involute profile generator,
native additive lofts and a constrained bore pocket. Helical surfaces are a
three-station ruled approximation per half, not manufacturing-grade flank proof.
No AI inference, user documents, GUI, network or destructive history edits.
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
    print('Starting synthetic herringbone benchmark', flush=True)
    import FreeCAD as A
    import Part
    import Sketcher
    sys.path.insert(0, str(Path(A.getHomePath()) / 'Mod/PartDesign'))
    import InvoluteGearFeature

    folder = Path(tempfile.mkdtemp(prefix='cadwiz-herringbone-093-'))
    d = A.newDocument('SyntheticHerringboneTrial')
    params = d.addObject('Spreadsheet::Sheet', 'Params')
    values = [('NormalModule', '2'), ('PinionTeeth', '20'), ('WheelTeeth', '60'),
              ('HelixAngle', '25'), ('NormalPressureAngle', '20'), ('HalfWidth', '10'), ('BoreRadius', '5'),
              ('TransverseModule', '=NormalModule/cos(HelixAngle*1 deg)'),
              ('TransversePressureAngle', '=atan(tan(NormalPressureAngle*1 deg)/cos(HelixAngle*1 deg))'),
              ('PinionRadius', '=TransverseModule*PinionTeeth/2'),
              ('WheelRadius', '=TransverseModule*WheelTeeth/2'),
              ('CenterDistance', '=PinionRadius+WheelRadius'),
              ('PinionTwist', '=HalfWidth*tan(HelixAngle*1 deg)/PinionRadius'),
              ('WheelTwist', '=HalfWidth*tan(HelixAngle*1 deg)/WheelRadius')]
    for i, (name, value) in enumerate(values, 1):
        params.set('A'+str(i), name); params.set('B'+str(i), value); params.setAlias('B'+str(i), name)
    d.recompute()
    gear_halves = []
    for gear_name, handedness, half in [('Pinion', 1, 0), ('Pinion', 1, 1), ('Wheel', -1, 0), ('Wheel', -1, 1)]:
        name = gear_name + ('Lower' if half == 0 else 'Upper')
        print('Building '+name+' involute profiles', flush=True)
        body = d.addObject('PartDesign::Body', name); gear_halves.append(name)
        profiles = []
        for j in range(3):
            i = 2*j+4*half
            profile = InvoluteGearFeature.makeInvoluteGear(name+'Section'+str(i))
            body.addObject(profile)
            profile.setExpression('NumberOfTeeth', 'Params.'+gear_name+'Teeth')
            profile.setExpression('Modules', 'Params.TransverseModule')
            profile.setExpression('PressureAngle', 'Params.TransversePressureAngle')
            profile.setExpression('AddendumCoefficient', 'cos(Params.HelixAngle*1 deg)')
            profile.setExpression('DedendumCoefficient', '1.25*cos(Params.HelixAngle*1 deg)')
            profile.setExpression('Placement.Base.z', 'Params.HalfWidth*'+str(i/4))
            fraction = min(i/4, 2-i/4) * handedness
            profile.Placement.Rotation = A.Rotation(A.Vector(0, 0, 1), 1)
            profile.setExpression('Placement.Rotation.Angle', 'Params.'+gear_name+'Twist*'+str(fraction)+'*1 rad')
            profiles.append(profile)
        d.recompute()
        print('Lofting '+name+' lower helix', flush=True)
        lower = body.newObject('PartDesign::AdditiveLoft', name+'LowerHelix')
        lower.Profile = profiles[0]; lower.Sections = profiles[1:]; lower.Ruled = True
        d.recompute()
        print('Cutting '+name+' bore', flush=True)
        bore = body.newObject('Sketcher::SketchObject', name+'BoreProfile')
        bore.addGeometry(Part.Circle(A.Vector(0, 0, 0), A.Vector(0, 0, 1), 5), False)
        bore.addConstraint(Sketcher.Constraint('Coincident', 0, 3, -1, 1))
        radius = bore.addConstraint(Sketcher.Constraint('Radius', 0, 5.0))
        bore.setExpression('Constraints['+str(radius)+']', 'Params.BoreRadius')
        bore.setExpression('Placement.Base.z', 'Params.HalfWidth*'+str(half+1))
        pocket = body.newObject('PartDesign::Pocket', name+'ShaftBore')
        pocket.Profile = bore; pocket.setExpression('Length', 'Params.HalfWidth')
        if gear_name == 'Wheel':
            body.setExpression('Placement.Base.x', 'Params.CenterDistance')
            # Opposite handedness, half-tooth indexing at the reference section.
            body.Placement.Rotation = A.Rotation(A.Vector(0, 0, 1), 180+180/60)
        d.recompute()
        assert bore.FullyConstrained
        assert not body.Shape.isNull() and body.Shape.isValid() and len(body.Shape.Solids) == 1, (name, body.State)
    def verify(doc):
        p = doc.Params
        ratio = p.WheelTeeth / p.PinionTeeth
        assert abs(ratio-3) < 1e-9
        expected = 2*(20+60)/(2*math.cos(math.radians(25)))
        assert abs(p.CenterDistance-expected) < 1e-6
        for name in gear_halves:
            body = doc.getObject(name)
            assert body.Shape.isValid() and len(body.Shape.Solids) == 1
            assert abs(body.Shape.BoundBox.ZLength - p.HalfWidth) < 1e-5
            first_section = name+'Section'+('0' if name.endswith('Lower') else '4')
            assert doc.getObject(first_section).NumberOfTeeth == (20 if name.startswith('Pinion') else 60)
            assert doc.getObject(name+'BoreProfile').FullyConstrained
        return {'ratio': ratio, 'center_distance_mm': p.CenterDistance,
                'pinion_volume_mm3': doc.PinionLower.Shape.Volume+doc.PinionUpper.Shape.Volume,
                'wheel_volume_mm3': doc.WheelLower.Shape.Volume+doc.WheelUpper.Shape.Volume}
    baseline = verify(d)
    first = folder/'01-original.FCStd'; d.saveAs(str(first))
    digest = hashlib.sha256(first.read_bytes()).hexdigest()
    A.closeDocument(d.Name); d = A.openDocument(str(first)); d.recompute(); verify(d)
    # Scripted equivalent of follow-up dimensional instructions; no AI turn claimed.
    d.Params.set('B6', '12'); d.recompute()
    assert all(abs(d.getObject(n).Shape.BoundBox.ZLength-12) < 1e-5 for n in gear_halves)
    assert all(d.getObject(n).Shape.isValid() for n in gear_halves)
    second = folder/'02-wider-gears.FCStd'; d.saveAs(str(second))
    d.Params.set('B7', '6'); d.recompute()
    assert d.PinionLower.Shape.Volume+d.PinionUpper.Shape.Volume < baseline['pinion_volume_mm3']*1.2
    third = folder/'03-larger-bores.FCStd'; d.saveAs(str(third))
    A.closeDocument(d.Name); d = A.openDocument(str(third)); d.recompute()
    assert all(d.getObject(n).Shape.isValid() for n in gear_halves)
    assert hashlib.sha256(first.read_bytes()).hexdigest() == digest
    report = {'status': 'PASS', 'scope': 'Synthetic assumed dimensions; scripted follow-up edits, no live AI conversation.',
              'assumptions': {'ratio': 3, 'teeth': [20, 60], 'normal_module_mm': 2, 'helix_deg': 25,
                              'normal_pressure_deg': 20, 'initial_width_mm': 20},
              'baseline': baseline, 'saved_reopened_recomputed': True, 'prior_revision_unchanged': True,
              'native_features': ['InvoluteGear profiles', 'PartDesign additive lofts', 'constrained bore pockets'],
              'limitations': ['Ruled helical approximation; not a loaded contact/backlash/strength validation.',
                             'Split herringbone construction: two editable halves per gear, not a fused single-piece gear.',
                             'Complete automated housing/bearing/shaft assembly is a separate gate.',
                             'No live paid inference performed.'], 'artifacts': str(folder)}
    target = Path(os.environ.get('CADWIZ_GEARBOX_REPORT', folder/'report.json'))
    target.write_text(json.dumps(report, indent=2)); print(json.dumps(report, indent=2), flush=True)
    for name in list(A.listDocuments()): A.closeDocument(name)


result = 0
try: run()
except BaseException:
    traceback.print_exc(); result = 1
sys.stdout.flush(); sys.stderr.flush(); os._exit(result)
