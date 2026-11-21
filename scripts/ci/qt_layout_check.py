# SPDX-License-Identifier: LGPL-2.1-or-later
"""Qt component witness: right docking, float/back, recovery and Setup controls."""
import os,sys,tempfile
from pathlib import Path
from types import SimpleNamespace
os.environ['QT_QPA_PLATFORM']='offscreen'
os.environ['LOCALAPPDATA']=tempfile.mkdtemp(prefix='cadwiz-qt-086-')
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'CADWiz/src'))
import FreeCAD
sys.path.insert(0,str(Path(FreeCAD.getHomePath())/'Ext'))
from PySide import QtCore,QtGui,QtWidgets
from integrations.cadwiz_plugin.panel_pages import SetupPage
from integrations.cadwiz_plugin.panel_host import PanelHost
from ai_freecad_core.cadwiz_screen.preferences import FounderPreferences
app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
if Path('C:/Windows/Fonts/arial.ttf').exists():QtGui.QFontDatabase.addApplicationFont('C:/Windows/Fonts/arial.ttf')
app.setFont(QtGui.QFont('Arial',11))
win=QtWidgets.QMainWindow();win.resize(1280,900)
mdi=QtWidgets.QMdiArea(win);win.setCentralWidget(mdi)
dock=QtWidgets.QDockWidget('CADWiz',win);dock.setObjectName('AI_FreeCAD_Status_Dock')
content=QtWidgets.QWidget(dock);dock.setWidget(content)
def section(parent,title,name=''):
 box=QtWidgets.QGroupBox(title,parent);box.setObjectName(name);return box,QtWidgets.QVBoxLayout(box)
panel=SimpleNamespace(QtCore=QtCore,QtGui=QtGui,QtWidgets=QtWidgets,full=content,content=content,settings={'docked_width':500},prefs=FounderPreferences(),FOUNDER_BLUE='#234A78',_section=section,bridge=lambda:None,session=lambda:None,document=lambda:None,gui=lambda:None,wiz_player=SimpleNamespace(frames=[]),pop_button=QtWidgets.QPushButton(),show_collapsed=lambda value:None)
panel._call=lambda tool,args:{'ok':True,'health':{'level':'E1','roundtrip':True,'changed_parameters':[]},'note':'Construction display changed without deletion.'}
page=SetupPage(panel);layout=QtWidgets.QVBoxLayout(content);layout.addWidget(page.page)
panel.full=page.page
win.addDockWidget(QtCore.Qt.RightDockWidgetArea,dock)
win.show();app.processEvents()
host=PanelHost(dock,panel);panel.host=host
app.processEvents()
for _ in range(2):
 host.pop_out();app.processEvents();assert dock.isFloating()
 win.addDockWidget(QtCore.Qt.TopDockWidgetArea,dock);dock.setFloating(False);app.processEvents()
 host.dock_back();app.processEvents();assert win.dockWidgetArea(dock)==QtCore.Qt.RightDockWidgetArea
win.addDockWidget(QtCore.Qt.TopDockWidgetArea,dock);dock.setFloating(False)
host.reset_layout();app.processEvents();assert win.dockWidgetArea(dock)==QtCore.Qt.RightDockWidgetArea
assert not dock.isFloating() and mdi.width()>=360 and mdi.height()>=200
page.refresh();page.check_model_health();assert 'reconstruct' in page.report_result.text()
page.run_doctor();assert 'read-only' in page.report_result.text()
page.copy_ai_help();assert 'CADWiz support' in app.clipboard().text()
# Render the real Setup controls; the health reply above tests UI wiring only.
scroll=page.page.findChild(QtWidgets.QScrollArea);scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum());app.processEvents()
if os.environ.get('CADWIZ_QT_SCREENSHOT'):page.page.grab().save(os.environ['CADWIZ_QT_SCREENSHOT'])
print('PASS Qt: repeated float/right reattach; horizontal-layout recovery; CAD viewport preserved; Setup recovery/health/copy controls wired. Native health is verified separately by native_session_check.py.')
win.close()
