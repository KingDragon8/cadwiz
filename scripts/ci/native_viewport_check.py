# SPDX-License-Identifier: LGPL-2.1-or-later
"""CI-only OS-composited viewport evidence, never an owner's document."""
import json
import os
from pathlib import Path
import subprocess
import sys


def compare_paint(visible, background, hits, misses, width, height):
    assert visible.size() == background.size(), 'Capture dimensions changed'
    assert len(hits) >= 5 and len(misses) >= 5, 'Insufficient geometry/background samples'
    def changed(point):
        x = min(visible.width()-1, int(point[0]*visible.width()/width))
        y = min(visible.height()-1, int((height-1-point[1])*visible.height()/height))
        first = visible.pixelColor(x,y).getRgb()[:3]
        second = background.pixelColor(x,y).getRgb()[:3]
        return sum(abs(a-b) for a,b in zip(first,second)) >= 45
    painted = sum(changed(point) for point in hits)
    altered_background = sum(changed(point) for point in misses)
    assert painted >= max(5, len(hits)//3), 'OS capture does not show the model silhouette'
    assert altered_background <= max(1, len(misses)//10), 'Background/camera changed between captures'
    return {'geometry_samples':len(hits),'painted_geometry_samples':painted,
            'background_samples':len(misses),'changed_background_samples':altered_background}


def capture_region(widget, output):
    from PySide import QtCore, QtGui
    origin = widget.mapToGlobal(QtCore.QPoint(0,0))
    rectangle = (origin.x(),origin.y(),widget.width(),widget.height())
    subprocess.run(['/usr/sbin/screencapture','-x','-R'+','.join(map(str,rectangle)),str(output)],
                   check=True,capture_output=True,timeout=15)
    image = QtGui.QImage(str(output))
    assert not image.isNull() and image.width()>0 and image.height()>0, 'OS capture unavailable'
    scale_x=image.width()/rectangle[2];scale_y=image.height()/rectangle[3]
    assert abs(scale_x-scale_y)<.03, ('OS viewport capture clipped by desktop',rectangle,image.width(),image.height())
    return image, rectangle


def verify(app, gui, authority, folder):
    assert os.environ.get('CI') == 'true' and sys.platform == 'darwin'
    from PySide import QtWidgets, QtCore
    from integrations.cadwiz_plugin.view_link import active_view
    target = Path(authority.target_path).resolve()
    document = app.ActiveDocument
    assert Path(document.FileName).resolve() == target, 'Wrong active native document'
    assert gui.activeDocument().Document.Name == document.Name, 'GUI/core document mismatch'
    view = active_view(gui)
    expected = gui.getDocument(document.Name).activeView()
    assert view and view.getCameraNode().getNodeId() == expected.getCameraNode().getNodeId(), 'Wrong native MDI view'
    width,height = view.getSize()
    assert width>=160 and height>=120, (width,height)
    mdi = gui.getMainWindow().findChild(QtWidgets.QMdiArea)
    assert mdi and mdi.activeSubWindow(), 'No active native MDI window'
    content = mdi.activeSubWindow().widget()
    widgets = [content,*content.findChildren(QtWidgets.QWidget)]
    details = [{'class':w.metaObject().className(),'width':w.width(),'height':w.height(),
                'visible':w.isVisible()} for w in widgets]
    Path(folder,'native-widget-diagnostics.json').write_text(json.dumps(details,indent=2))
    candidates = [w for w in widgets if w.isVisible() and w.width()>0 and w.height()>0
                  and any(name in w.metaObject().className() for name in ('Quarter','GLWidget','OpenGL'))
                  and abs(width/w.width()-height/w.height())<.03]
    # Nested render containers can share a size; use the innermost renderer.
    candidates = [w for w in candidates if not any(w is not other and w.isAncestorOf(other)
                                                   for other in candidates)]
    assert len(candidates)==1, ('Ambiguous native render widget',details)
    widget = candidates[0]
    hits=[];misses=[]
    for x in range(1,25):
        for y in range(1,25):
            point=(int(width*x/25),int(height*y/25))
            info=view.getObjectInfo(point)
            (hits if info else misses).append(point)
    visible_shapes = [obj for obj in document.Objects if hasattr(obj,'Shape')
                      and obj.ViewObject.Visibility and not obj.Shape.isNull()]
    assert visible_shapes, 'Bound target has no visible native shapes'
    def refresh():
        gui.updateGui();view.redraw()
        loop=QtCore.QEventLoop();QtCore.QTimer.singleShot(200,loop.quit)
        (getattr(loop,"exec",None) or loop.exec_)()
        gui.updateGui()
    refresh()
    visible,rectangle = capture_region(widget,Path(folder,'native-viewport-visible.png'))
    try:
        for obj in visible_shapes:obj.ViewObject.Visibility=False
        refresh()
        background,_ = capture_region(widget,Path(folder,'native-viewport-background.png'))
    finally:
        for obj in visible_shapes:obj.ViewObject.Visibility=True
        refresh()
    restored,_ = capture_region(widget,Path(folder,'native-viewport-verified.png'))
    result=compare_paint(visible,background,hits,misses,width,height)
    compare_paint(restored,background,hits,misses,width,height)
    capture_region(gui.getMainWindow(),Path(folder,'pointer-edit-verified.png'))
    return {**result,'width':width,'height':height,'document':document.Name,
            'working_file':str(target),'gui_pid':os.getpid(),'os_capture_rect':rectangle,
            'capture':'macOS OS-composited visible/background/restored viewport'}
