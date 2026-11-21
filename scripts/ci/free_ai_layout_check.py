# SPDX-License-Identifier: LGPL-2.1-or-later
"""Headless native Qt witness; no FreeCAD GUI or provider call."""
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['LOCALAPPDATA'] = tempfile.mkdtemp(prefix='cadwiz-free-ai-ui-test-')
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, os.environ.get('CADWIZ_QA_SOURCE', str(ROOT / 'CADWiz/src')))
import FreeCAD
sys.path.insert(0, str(Path(FreeCAD.getHomePath()) / 'Ext'))
from PySide import QtCore, QtGui, QtWidgets
from integrations.cadwiz_plugin.free_ai import FreeAIPage
from integrations.cadwiz_plugin.slim_panel import _Panel
from integrations.cadwiz_plugin import free_ai_enrollment as enrollment
import time
import threading

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
if Path('C:/Windows/Fonts/arial.ttf').exists():
    QtGui.QFontDatabase.addApplicationFont('C:/Windows/Fonts/arial.ttf')
app.setFont(QtGui.QFont('Arial', 11))
full = QtWidgets.QWidget()
full.resize(420, 850)
opened = []
panel = SimpleNamespace(QtCore=QtCore, QtWidgets=QtWidgets, full=full,
                        bridge=lambda: SimpleNamespace(connected_to=lambda name: name == 'chatgpt'),
                        open_page=opened.append)
layout = QtWidgets.QVBoxLayout(full)
bar = _Panel._build_page_bar(panel)
layout.addWidget(bar)
page = FreeAIPage(panel)
layout.addWidget(page.page)
full.show()
app.processEvents()
assert 'Ready — app assisted' in page.apps.text()
assert 'Unknown' in page.capacity.text()
assert len(panel.page_buttons) == 4
assert len(page.cards)==7
assert all(not widgets[0].isChecked() for widgets in page.cards.values())
full.findChild(QtWidgets.QPushButton, 'CADWiz_Free_AI_Connect').click()
full.findChild(QtWidgets.QPushButton, 'CADWiz_Free_AI_Create').click()
assert opened == [2, 0]
assert full.minimumSizeHint().width() <= 420, full.minimumSizeHint().width()
# Exercise the actual dialog and its background completion using explicit test
# stand-ins. These are wiring tests, never presented as live provider evidence.
class Vault:
    value = None
    def set(self, secret):
        Vault.value = secret
    def remove(self):
        Vault.value = None
enrollment.WindowsCredentialStore = Vault
enrollment.check_groq_key = lambda secret, consent=False: {'message': 'Synthetic connection test only', 'connection_verified': True}
full.findChild(QtWidgets.QPushButton, 'CADWiz_Free_AI_Setup').click()
app.processEvents()
dialog = panel._free_ai_enrollment
key = dialog.findChild(QtWidgets.QLineEdit, 'CADWiz_Free_AI_Key')
consent = dialog.findChild(QtWidgets.QCheckBox, 'CADWiz_Free_AI_Consent')
verify = dialog.findChild(QtWidgets.QPushButton, 'CADWiz_Free_AI_Verify')
assert key.echoMode() == QtWidgets.QLineEdit.Password and not verify.isEnabled()
if os.environ.get('CADWIZ_ENROLLMENT_SCREENSHOT'):
    dialog.grab().save(os.environ['CADWIZ_ENROLLMENT_SCREENSHOT'])
key.setText('synthetic-test-not-a-real-provider-key')
assert not verify.isEnabled()
consent.setChecked(True)
assert verify.isEnabled()
verify.click()
deadline = time.monotonic() + 3
while time.monotonic() < deadline and Vault.value is None:
    app.processEvents()
    time.sleep(0.01)
assert Vault.value == 'synthetic-test-not-a-real-provider-key'
assert key.text() == '' and 'qualification pending' in page.direct.text()
assert page.cards['groq'][4].isChecked()
dialog.findChild(QtWidgets.QPushButton, 'CADWiz_Free_AI_Remove_Key').click()
assert Vault.value is None and 'not connected' in page.direct.text()
assert not page.cards['groq'][4].isChecked()
dialog.reject()
app.processEvents()
# Closing during an in-flight check must not store its later result.
release = threading.Event()
def delayed_check(secret, consent=False):
    release.wait(2)
    return {'message': 'Synthetic late reply'}
enrollment.check_groq_key = delayed_check
page.enroll()
dialog = panel._free_ai_enrollment
dialog.findChild(QtWidgets.QLineEdit, 'CADWiz_Free_AI_Key').setText('synthetic-late-key-not-real')
dialog.findChild(QtWidgets.QCheckBox, 'CADWiz_Free_AI_Consent').setChecked(True)
dialog.findChild(QtWidgets.QPushButton, 'CADWiz_Free_AI_Verify').click()
dialog.reject()
release.set()
deadline = time.monotonic() + 0.3
while time.monotonic() < deadline:
    app.processEvents()
    time.sleep(0.01)
assert Vault.value is None
# Clear synthetic result before screenshot; never show a fake connected account.
page.direct.setText('Direct provider: not connected. Start with one free account.')
panel.bridge = lambda: None
page.refresh()
if os.environ.get('CADWIZ_QT_SCREENSHOT'):
    full.grab().save(os.environ['CADWIZ_QT_SCREENSHOT'])
print('PASS: native Qt Free AI page, masked/consented enrollment, worker completion, secure-store wiring, actions and 420px layout. Network and vault replaced only in this UI witness; real OS vault tested separately.')
full.close()
