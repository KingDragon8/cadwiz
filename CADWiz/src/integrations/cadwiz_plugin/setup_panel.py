# SPDX-License-Identifier: LGPL-2.1-or-later
"""Explicit desktop setup, preview, backup and one-click undo."""
from __future__ import annotations
import json
from pathlib import Path
from . import install_setup as setup


def connect(panel) -> None:
    qt = panel.QtWidgets
    app = str(getattr(panel.prefs, "ai_app", "claude"))
    if app == "auto":
        app, ok = qt.QInputDialog.getItem(panel.content, "Connect CADWiz", "Which desktop assistant?", ["Claude Desktop", "OpenAI / Codex"], 0, False)
        if not ok:
            return
        app = "claude" if app.startswith("Claude") else "chatgpt"
    try:
        info = setup.runtime()
        if app == "claude":
            bundle = Path(info["addon"]) / "Resources/CADWiz.mcpb"
            if not bundle.is_file():
                raise ValueError("CW-SETUP-BUNDLE: The Claude extension is missing. Reinstall CADWiz through Addon Manager.")
            answer = qt.QMessageBox.question(panel.content, "Add to Claude", "Claude will show its extension installation screen. Press Install there. If an old CADWiz connector is present, CADWiz will save a backup and remove only that old entry to prevent duplicate connections. Undo is available. Other connectors and models are kept. Continue?", qt.QMessageBox.Yes | qt.QMessageBox.No)
            if answer != qt.QMessageBox.Yes:
                return
            migrated = setup.migrate_legacy_claude()
            from importlib import import_module
            gui = import_module("PySide.QtGui")
            core = import_module("PySide.QtCore")
            if not gui.QDesktopServices.openUrl(core.QUrl.fromLocalFile(str(bundle))):
                if migrated:
                    setup.undo_claude()
                raise ValueError("CW-SETUP-OPEN: Open Claude Desktop, Settings, Extensions, and install " + str(bundle))
            if migrated:
                qt.QMessageBox.information(panel.content, "Finish the Claude upgrade", "After pressing Install in Claude, fully quit and reopen Claude to stop its old connector process. Your old CADWiz entry is backed up and Undo is available.")
        else:
            values = setup.server_values(info)
            # Retain beta.4's authenticated reconnect for an already-correct entry.
            import tomllib
            path = setup.config_path()
            existing = tomllib.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else {}
            if existing.get("mcp_servers", {}).get("cadwiz") == values:
                qt.QMessageBox.information(panel.content, "Codex connection configured", "Open Codex and ask: What’s open in FreeCAD? If it was already open, fully quit and reopen it to load the CADWiz connection. Your existing configuration was kept.")
                return
            text = ("Add CADWiz to Codex on this computer?\n\n"
                    "Only CADWiz’s own connection settings will change. A backup and Undo connection are included. "
                    "Other assistant settings and your models are kept.\n\n"
                    "After approving, fully quit and reopen Codex, then ask what is open in FreeCAD.")
            answer = qt.QMessageBox.question(panel.content, "Connect Codex", text, qt.QMessageBox.Yes | qt.QMessageBox.No)
            if answer != qt.QMessageBox.Yes:
                return
            setup.connect(info)
            qt.QMessageBox.information(panel.content, "Connection saved", "Fully quit and reopen Codex, then ask: What's open in FreeCAD? The light turns green after that assistant checks in.")
    except Exception as error:
        qt.QMessageBox.warning(panel.content, "CADWiz connection", str(error))


def undo(panel) -> None:
    try:
        if (setup.data_dir() / "duplicate-undo.json").exists():
            setup.undo_duplicates()
            panel.QtWidgets.QMessageBox.information(panel.content, "Old add-on restored", "The previous add-on folder was restored. Restart FreeCAD. No models were deleted.")
            return
        if (setup.data_dir() / "claude-undo.json").exists():
            setup.undo_claude()
            panel.QtWidgets.QMessageBox.information(panel.content, "Old Claude connector restored", "The previous CADWiz entry was restored. Uninstall the new CADWiz extension in Claude before restarting Claude to avoid duplicate connections. Other connectors and models were kept.")
            return
        setup.disconnect()
        panel.QtWidgets.QMessageBox.information(panel.content, "Connection undone", "CADWiz's previous OpenAI entry was restored. Other settings and models were kept. Fully quit and reopen the assistant.")
    except Exception as error:
        panel.QtWidgets.QMessageBox.warning(panel.content, "Undo connection", str(error))


def values(panel) -> None:
    try:
        info = setup.runtime()
        qt = panel.QtWidgets
        dialog = qt.QDialog(panel.content)
        dialog.setWindowTitle("Manual OpenAI connection")
        layout = qt.QVBoxLayout(dialog)
        for label, value in [("Name", "cadwiz"), ("Type", "STDIO"), ("Command", info["python"]),
                             ("Arguments", json.dumps(setup.server_values(info)["args"]))]:
            row = qt.QHBoxLayout()
            row.addWidget(qt.QLabel(label))
            edit = qt.QLineEdit(value)
            edit.setReadOnly(True)
            row.addWidget(edit)
            button = qt.QPushButton("Copy")
            button.clicked.connect(lambda _checked=False, v=value: qt.QApplication.clipboard().setText(v))
            row.addWidget(button)
            layout.addLayout(row)
        layout.addWidget(qt.QLabel('Environment: CADWIZ_CLIENT_APP = chatgpt. Save, then Restart the assistant.'))
        dialog.exec() if hasattr(dialog, "exec") else dialog.exec_()
    except Exception as error:
        panel.QtWidgets.QMessageBox.warning(panel.content, "Manual connection", str(error))
