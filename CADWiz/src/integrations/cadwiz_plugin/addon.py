# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""The CADWiz FreeCAD addon on its own: workbench, panel and Claude bridge, with
none of the retired assistant (ORDER-2026-10-21-01, open-source readiness).

The open-source release is the plug-in product only: Claude Desktop is the
designer, CADWiz is its hands and eyes in FreeCAD. This module is what the public
addon's `InitGui.py` calls. It does what `ai_freecad_workbench.bootstrap` does
for the plug-in path -- the panel built when FreeCAD starts and kept in every
workbench (ORDER-2026-10-18-01), the bridge Claude Desktop talks to -- without
building the old assistant's engine, whose panel only opens behind a developer
switch and is not part of the release.
"""
from __future__ import annotations

import contextlib
import os
from importlib import import_module
from pathlib import Path
from typing import Any

#: The dock's object name. Kept equal to the one the founder's install has always
#: used, so FreeCAD's saved window layout puts the panel back where he left it.
DOCK_OBJECT_NAME = "AI_FreeCAD_Status_Dock"
#: How long after FreeCAD's start-up code the panel is built: the main window and
#: its own docks are in place by then, so CADWiz docks on the right of them.
PANEL_AT_STARTUP_DELAY_MS = 1500
#: The logo (hat and gear, no eyes) -- the same icon the workbench list has always shown.
ICON = Path(__file__).resolve().parents[1] / "freecad_native" / "resources" / "cadwizard.svg"

_workbench: Any = None
_bridge: Any = None
_dock: Any = None


def plugin_bridge() -> Any:
    """The running bridge (or None): the panel reads its connection light here."""
    return _bridge


def start_bridge() -> Any:
    global _bridge
    if _bridge is not None:
        return _bridge
    if os.environ.get("CADWIZ_PLUGIN_BRIDGE", "").strip().lower() == "off":
        return None            # a test run starts its own bridge from the tree under test
    try:
        from integrations.cadwiz_plugin.bridge import start_in_freecad  # noqa: PLC0415

        _bridge = start_in_freecad()
    except Exception as error:  # noqa: BLE001 - FreeCAD must still start; the panel shows "Not connected"
        print(f"CADWiz: the Claude connection did not start: {type(error).__name__}: {error}")
    return _bridge


def stop_bridge() -> None:
    global _bridge
    bridge, _bridge = _bridge, None
    stop = getattr(bridge, "stop", None) or getattr(bridge, "shutdown", None)
    if callable(stop):
        with contextlib.suppress(Exception):
            stop()


def ensure_dock() -> Any:
    """The CADWiz panel, docked on the right of FreeCAD's main window (built once)."""
    global _dock
    if _dock is not None:
        return _dock
    gui = import_module("FreeCADGui")
    qt_core = import_module("PySide.QtCore")
    qt_widgets = import_module("PySide.QtWidgets")
    window = gui.getMainWindow()
    existing = window.findChild(qt_widgets.QDockWidget, DOCK_OBJECT_NAME)
    if existing is not None and existing.findChild(qt_widgets.QWidget, "CADWiz_Slim_Panel") is not None:
        _dock = existing
        return existing
    from integrations.cadwiz_plugin import slim_panel  # noqa: PLC0415

    dock = qt_widgets.QDockWidget("CADWiz", window)
    dock.setObjectName(DOCK_OBJECT_NAME)
    slim_panel.build(dock, qt_core, qt_widgets, plugin_bridge)
    area = getattr(qt_core.Qt, "RightDockWidgetArea", None)
    if area is None:
        area = qt_core.Qt.DockWidgetArea.RightDockWidgetArea
    window.addDockWidget(area, dock)
    _dock = dock
    return dock


def show_panel() -> Any:
    try:
        dock = ensure_dock()
        dock.show()
        return dock
    except Exception as error:  # noqa: BLE001 - FreeCAD must still start; the CADWiz workbench brings it back
        print(f"CADWiz: the panel could not be shown: {type(error).__name__}: {error}")
        return None


def _schedule_panel_at_startup() -> None:
    try:
        qt_core = import_module("PySide.QtCore")
        qt_widgets = import_module("PySide.QtWidgets")
    except Exception:  # noqa: BLE001 - no window (FreeCADCmd): nothing to show
        return
    app = qt_widgets.QApplication.instance()
    if app is None:
        return
    with contextlib.suppress(Exception):
        app.aboutToQuit.connect(stop_bridge)
    qt_core.QTimer.singleShot(PANEL_AT_STARTUP_DELAY_MS, show_panel)


def register() -> Any:
    """Register the CADWiz workbench once, start the Claude bridge, and show the
    panel when FreeCAD has finished starting."""
    global _workbench
    if _workbench is not None:
        return _workbench
    gui = import_module("FreeCADGui")

    class CADWizWorkbench(gui.Workbench):  # type: ignore[misc,name-defined]
        MenuText = "CADWiz"
        ToolTip = "CADWiz: lets Claude Desktop see, measure, build and edit your FreeCAD models"
        Icon = str(ICON) if ICON.is_file() else ""

        def Initialize(self) -> None:
            pass

        def Activated(self) -> None:
            show_panel()

        def Deactivated(self) -> None:
            pass               # the panel stays in every workbench (ORDER-2026-10-18-01)

        def GetClassName(self) -> str:
            return "Gui::PythonWorkbench"

    _workbench = CADWizWorkbench()
    gui.addWorkbench(_workbench)
    start_bridge()
    _schedule_panel_at_startup()
    return _workbench
