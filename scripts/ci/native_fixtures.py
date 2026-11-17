# SPDX-License-Identifier: LGPL-2.1-or-later
import FreeCAD as A
import Part
import Sketcher

def plate(name='Plate'):
 d=A.newDocument(name)
 p=d.addObject('Spreadsheet::Sheet','Params')
 for i,(alias,value) in enumerate([('Width',40),('Height',30),('Thickness',5),('HoleDiameter',4)],1):
  p.set('A'+str(i),str(value));p.setAlias('A'+str(i),alias)
 b=d.addObject('PartDesign::Body','Body');s=b.newObject('Sketcher::SketchObject','Profile')
 pts=[(0,0),(40,0),(40,30),(0,30)]
 for i in range(4):
  a=pts[i];z=pts[(i+1)%4];s.addGeometry(Part.LineSegment(A.Vector(a[0],a[1],0),A.Vector(z[0],z[1],0)),False)
 for i in range(4):s.addConstraint(Sketcher.Constraint('Coincident',i,2,(i+1)%4,1))
 for i in range(4):s.addConstraint(Sketcher.Constraint('Horizontal' if i%2==0 else 'Vertical',i))
 s.addConstraint(Sketcher.Constraint('Coincident',0,1,-1,1))
 for line,alias,value in [(0,'Width',40),(1,'Height',30)]:
  k=s.addConstraint(Sketcher.Constraint('Distance',line,value));s.renameConstraint(k,alias);s.setExpression('Constraints.'+alias,'Params.'+alias)
 pad=b.newObject('PartDesign::Pad','Pad');pad.Profile=s;pad.setExpression('Length','Params.Thickness');d.recompute()
 holes=b.newObject('Sketcher::SketchObject','Holes');holes.Placement.Base.z=5;holes.setExpression('Placement.Base.z','Pad.Length')
 for x,y in [(8,8),(32,8),(8,22),(32,22)]:
  i=holes.addGeometry(Part.Circle(A.Vector(x,y,0),A.Vector(0,0,1),2),False)
  holes.addConstraint(Sketcher.Constraint('DistanceX',i,3,x));holes.addConstraint(Sketcher.Constraint('DistanceY',i,3,y))
  k=holes.addConstraint(Sketcher.Constraint('Diameter',i,4));holes.setExpression('Constraints['+str(k)+']','Params.HoleDiameter')
 pocket=b.newObject('PartDesign::Pocket','Pocket');pocket.Profile=holes;pocket.Length=5;pocket.setExpression('Length','Pad.Length');d.recompute()
 return d
