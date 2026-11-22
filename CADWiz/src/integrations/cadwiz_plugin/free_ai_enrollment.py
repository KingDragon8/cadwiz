# SPDX-License-Identifier: LGPL-2.1-or-later
"""Native setup dialog. Networking stays on a worker; keys never enter settings."""
from __future__ import annotations
import queue
import threading
from typing import Any

from .free_ai_connection import ConnectionFailure, check_groq_key, check_provider_key, validate_key
from .secure_store import credential_store
from .free_ai_manager import CATALOG


def show_enrollment(panel: Any, on_verified=None, provider_id='groq') -> None:
    if provider_id not in CATALOG:
        raise ConnectionFailure('Choose a supported provider.')
    guide=CATALOG[provider_id]
    qt, core = panel.QtWidgets, panel.QtCore
    previous = getattr(panel, "_free_ai_enrollment", None)
    if previous is not None and previous.isVisible():
        previous.raise_()
        previous.activateWindow()
        return
    dialog = qt.QDialog(panel.full)
    dialog.setWindowTitle("Connect a free AI provider")
    dialog.resize(540, 540)
    layout = qt.QVBoxLayout(dialog)

    def text(words):
        item = qt.QLabel(words, dialog)
        item.setWordWrap(True)
        layout.addWidget(item)
        return item

    text("Connect " + guide.name)
    text("Create or use a legitimate Free-plan account. This check verifies API access only; "
         "it does not verify billing protections or authorize CAD generation.")
    links = text(f'<a href="{guide.signup}">Account and API key</a> · '
                 f'<a href="{guide.policy}">Provider limits and policy</a>')
    links.setOpenExternalLinks(True)
    key = qt.QLineEdit(dialog)
    key.setObjectName("CADWiz_Free_AI_Key")
    key.setEchoMode(qt.QLineEdit.Password)
    key.setPlaceholderText("Paste your API key here — never in chat")
    layout.addWidget(key)
    from urllib.parse import urlsplit
    text("The key is sent only to " + urlsplit(guide.models_url).hostname + " over HTTPS for a read-only connection check. "
         "No prompt, model, screenshot or dimensions are sent. No inference call is made. "
         "On success the key is stored in Windows Credential Manager, macOS Keychain, or Linux Secret Service, not your CAD files.")
    consent = qt.QCheckBox("Allow this connection check and secure key storage", dialog)
    consent.setObjectName("CADWiz_Free_AI_Consent")
    layout.addWidget(consent)
    status = text("Ready to verify your connection.")
    status.setObjectName("CADWiz_Free_AI_Enrollment_Status")
    verify = qt.QPushButton("Verify connection", dialog)
    verify.setObjectName("CADWiz_Free_AI_Verify")
    verify.setEnabled(False)
    layout.addWidget(verify)
    remove = qt.QPushButton("Remove saved key from this computer", dialog)
    remove.setObjectName("CADWiz_Free_AI_Remove_Key")
    layout.addWidget(remove)
    close = qt.QPushButton("Close", dialog)
    close.clicked.connect(dialog.reject)
    layout.addWidget(close)
    answers = queue.Queue()
    timer = core.QTimer(dialog)
    timer.setInterval(150)
    state = {"busy": False}

    def enabled(*_):
        verify.setEnabled(bool(key.text().strip()) and consent.isChecked() and not state["busy"])

    def start():
        if not consent.isChecked() or state["busy"]:
            return
        try:
            secret = validate_key(key.text())
            store = credential_store(provider_id)
        except ConnectionFailure as error:
            status.setText(str(error))
            return
        state["busy"] = True
        enabled()
        consent.setEnabled(False)
        key.setEnabled(False)
        key.clear()
        status.setText("Checking API access. No CAD data is sent and no inference is requested…")

        def work():
            try:
                result = (check_groq_key(secret, consent=True) if provider_id=='groq'
                          else check_provider_key(provider_id,secret,consent=True))
                # Closing the dialog revokes permission to persist the key.
                answers.put((True, result, secret, store))
            except ConnectionFailure as error:
                answers.put((False, str(error), None, None))
            except Exception:
                answers.put((False, "Connection check failed safely. No CAD operation was performed.", None, None))
        threading.Thread(target=work, name="CADWizFreeAIEnroll", daemon=True).start()
        timer.start()

    def poll():
        try:
            ok, result, secret, store = answers.get_nowait()
        except queue.Empty:
            return
        timer.stop()
        state["busy"] = False
        consent.setEnabled(True)
        key.setEnabled(True)
        if ok and dialog.isVisible() and consent.isChecked():
            try:
                store.set(secret)
                result['provider_id']=provider_id
                status.setText(result["message"] + " Key saved securely. No automatic CAD route is enabled.")
                if on_verified is not None:
                    on_verified(result)
            except ConnectionFailure as error:
                status.setText(str(error))
        elif not ok:
            status.setText(result)
        enabled()

    def rejected():
        timer.stop()
        key.clear()
    def remove_key():
        if state["busy"]:
            return
        try:
            credential_store(provider_id).remove()
            key.clear()
            status.setText("Saved key removed from this computer. Revoke it at the provider separately if needed.")
            if on_verified is not None:
                on_verified({"connection_verified": False,'provider_id':provider_id})
        except ConnectionFailure as error:
            status.setText(str(error))
    dialog.finished.connect(lambda *_: rejected())
    key.textChanged.connect(enabled)
    consent.toggled.connect(enabled)
    verify.clicked.connect(start)
    remove.clicked.connect(remove_key)
    timer.timeout.connect(poll)
    dialog.setModal(False)
    # Parent owns this nonblocking dialog; replacing it never closes a CAD document.
    panel._free_ai_enrollment = dialog
    dialog.show()
