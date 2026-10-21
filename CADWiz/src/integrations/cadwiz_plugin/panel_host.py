# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Where the CADWiz panel lives in FreeCAD's window (ORDER-2026-10-18-01).

Founder ruling 2026-10-18: CADWiz must not disappear when he switches workbench.
The panel is a FreeCAD-wide dock, like the Report view: created when FreeCAD
starts (`ai_freecad_workbench.bootstrap`), docked on the right, and never hidden
by a workbench switch. This module keeps it that way and adds:

  * collapse to a slim strip (the Wiz, the connection light, Show Claude), and
    open again with one click;
  * the Sketcher's edit mode collapses it automatically; leaving the sketch
    restores it (unless he opened it himself in between);
  * a CADWiz button on its own toolbar, in every workbench, to bring it back;
    FreeCAD's View > Panels lists it too (FreeCAD lists every dock it holds);
  * Pop out / Dock back for a second monitor: the window remembers which
    monitor and what size, and comes back onto the main screen if that monitor
    is not there;
  * its size and position, remembered between sessions (panel.json beside the
    plug-in's other files);
  * FreeCAD's Tasks panel moved to the left, as a tab beside Model, so CADWiz
    is the only thing on the right (ORDER-2026-10-19-01). Done once; if he
    drags Tasks back himself, CADWiz leaves it where he put it.
"""
from __future__ import annotations

import contextlib
from importlib import import_module
from typing import Any

TOOLBAR_NAME = "CADWiz_Panel_Toolbar"
TASKS_DOCK = "Tasks"                # FreeCAD 1.1's Tasks panel (its dock is named by its title)
MODEL_DOCK = "Model"                # FreeCAD 1.1's Model panel (the tree)
DOCK_ALIASES = {TASKS_DOCK: ("Tasks", "Std_TaskView"), MODEL_DOCK: ("Model", "Std_ComboView", "Combo View")}
TASKS_MOVED_KEY = "tasks_moved_left"
TASKS_MOVE_DELAY_MS = 1500          # after FreeCAD has put back its own saved layout
STRIP_WIDTH = 124
FULL_MIN_WIDTH = 420
DEFAULT_FLOAT_SIZE = (1100, 900)
KEEP_HEIGHT_CHECKS_MS = (0, 150, 400, 900)


def attach(dock: Any, panel: Any) -> "PanelHost":
    return PanelHost(dock, panel)


def on_screen(rect: tuple[int, int, int, int], screens: list[tuple[str, tuple[int, int, int, int]]], name: str,
              primary: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    """Where a popped-out window goes: its remembered place when the monitor it was
    on is still there and the window would still be mostly on it; otherwise the
    same size (shrunk to fit) in the middle of the main screen."""
    x, y, w, h = rect
    for screen_name, (sx, sy, sw, sh) in screens:
        if screen_name != name:
            continue
        overlap_w = max(0, min(x + w, sx + sw) - max(x, sx))
        overlap_h = max(0, min(y + h, sy + sh) - max(y, sy))
        if w > 0 and h > 0 and overlap_w * overlap_h >= 0.5 * w * h:
            return rect
    px, py, pw, ph = primary
    w, h = min(w or DEFAULT_FLOAT_SIZE[0], pw - 40), min(h or DEFAULT_FLOAT_SIZE[1], ph - 60)
    return (px + (pw - w) // 2, py + (ph - h) // 2, w, h)


class PanelHost:
    def __init__(self, dock: Any, panel: Any) -> None:
        self.dock = dock
        self.panel = panel
        self.QtCore = import_module("PySide.QtCore")
        self.QtGui = import_module("PySide.QtGui")
        self.QtWidgets = import_module("PySide.QtWidgets")
        self.settings: dict[str, Any] = panel.settings
        self.collapsed = False
        self.auto_collapsed = False
        self.width_before = int(self.settings.get("docked_width") or 0)
        self.window = dock.parent()
        panel.full.setMinimumWidth(FULL_MIN_WIDTH)
        dock.setFeatures(dock.features() | self.QtWidgets.QDockWidget.DockWidgetFloatable | self.QtWidgets.QDockWidget.DockWidgetMovable
                         | self.QtWidgets.QDockWidget.DockWidgetClosable)
        dock.topLevelChanged.connect(self._top_level_changed)
        self._save_timer = self.QtCore.QTimer(panel.content)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(600)
        self._save_timer.timeout.connect(self.remember)
        self._filter = self._make_filter()
        dock.installEventFilter(self._filter)
        self._sketch = self.QtCore.QTimer(panel.content)
        self._sketch.setInterval(500)
        self._sketch.timeout.connect(self._watch_sketcher)
        self._sketch.start()
        self.toolbar = self._ensure_toolbar()
        with contextlib.suppress(Exception):
            self.window.workbenchActivated.connect(self._workbench_changed)
        self.QtCore.QTimer.singleShot(0, self.restore)
        self.QtCore.QTimer.singleShot(TASKS_MOVE_DELAY_MS, self.move_tasks_left)

    # ---- Tasks beside Model, CADWiz alone on the right ----------------------------------------
    def move_tasks_left(self) -> bool:
        """Put FreeCAD's Tasks panel on the left as a tab beside Model, at every start.

        It used to be done once and then left alone; by 2026-10-20 Tasks had ended
        up squeezed into a strip under the property view, and the founder had asked
        "several times" for it beside Model (ORDER-2026-10-20-01). Now: whenever
        Tasks is not already a tab beside Model, it is put there. Returns True when
        Tasks is on the left afterwards."""
        window, Qt = self.window, self.QtCore.Qt
        if window is None:
            return False
        QDockWidget = self.QtWidgets.QDockWidget
        tasks = _find_dock(window, QDockWidget, TASKS_DOCK)
        if tasks is None:
            return False
        model = _find_dock(window, QDockWidget, MODEL_DOCK)
        with contextlib.suppress(Exception):
            if model is not None and tasks in window.tabifiedDockWidgets(model):
                return True                          # already a tab beside Model: nothing to do
        try:
            if tasks.isFloating():
                tasks.setFloating(False)
            if window.dockWidgetArea(tasks) != Qt.LeftDockWidgetArea:
                window.addDockWidget(Qt.LeftDockWidgetArea, tasks)
            if model is not None and model is not tasks and window.dockWidgetArea(model) == Qt.LeftDockWidgetArea:
                window.tabifyDockWidget(model, tasks)
                model.raise_()                       # Model in front; a task (a sketch) brings Tasks forward itself
        except Exception:  # noqa: BLE001 - FreeCAD's own layout is never worth a crash
            return False
        moved = window.dockWidgetArea(tasks) == Qt.LeftDockWidgetArea
        if moved:
            self.settings[TASKS_MOVED_KEY] = True
            self._save_timer.start()
        return moved

    # ---- remembered size and place -----------------------------------------------------------
    def restore(self) -> None:
        if self.settings.get("floating"):
            self.pop_out()
        elif self.width_before:
            self._resize_docked(self.width_before)
        if self.settings.get("collapsed"):
            self.collapse()

    def remember(self) -> None:
        dock = self.dock
        self.settings["floating"] = bool(dock.isFloating())
        self.settings["collapsed"] = bool(self.collapsed and not self.auto_collapsed)
        if dock.isFloating() and not self.collapsed:
            geometry = dock.geometry()
            self.settings["float_geometry"] = [geometry.x(), geometry.y(), geometry.width(), geometry.height()]
            with contextlib.suppress(Exception):
                self.settings["float_screen"] = dock.screen().name()
        elif not dock.isFloating() and not self.collapsed and dock.width() > STRIP_WIDTH + 20:
            self.settings["docked_width"] = int(dock.width())
            self.width_before = int(dock.width())
        from integrations.cadwiz_plugin.slim_panel import _save_settings

        _save_settings(self.settings)

    def _make_filter(self) -> Any:
        QtCore = self.QtCore
        host = self

        class Filter(QtCore.QObject):  # type: ignore[misc]
            def eventFilter(self, _obj: Any, event: Any) -> bool:  # noqa: N802
                if event.type() in (QtCore.QEvent.Move, QtCore.QEvent.Resize):
                    host._save_timer.start()
                return False

        return Filter(self.dock)

    def _resize_docked(self, width: int) -> None:
        with contextlib.suppress(Exception):
            self.window.resizeDocks([self.dock], [int(width)], self.QtCore.Qt.Horizontal)

    # ---- pop out / dock back -------------------------------------------------------------------
    def toggle_floating(self) -> None:
        if self.dock.isFloating():
            self.dock_back()
        else:
            self.pop_out()

    def pop_out(self) -> None:
        if self.collapsed:
            self.expand()
        self.dock.setFloating(True)
        screens = [(s.name(), _rect(s.availableGeometry())) for s in self.QtGui.QGuiApplication.screens()]
        primary = _rect(self.QtGui.QGuiApplication.primaryScreen().availableGeometry())
        remembered = tuple(self.settings.get("float_geometry") or ()) or (0, 0, *DEFAULT_FLOAT_SIZE)
        x, y, w, h = on_screen(remembered, screens, str(self.settings.get("float_screen") or ""), primary)  # type: ignore[arg-type]
        self.dock.setGeometry(x, y, w, h)
        self.dock.show()
        self.dock.raise_()
        self.panel.pop_button.setText("Dock back")
        self._save_timer.start()

    def dock_back(self) -> None:
        self.dock.setFloating(False)
        self.panel.pop_button.setText("Pop out")
        if self.width_before and not self.collapsed:
            self._resize_docked(self.width_before)
        self._save_timer.start()

    def _top_level_changed(self, floating: bool) -> None:
        # Double-clicking the title bar docks or floats it (Qt does that itself).
        self.panel.pop_button.setText("Dock back" if floating else "Pop out")
        self._save_timer.start()

    # ---- collapse to the strip ---------------------------------------------------------------
    def collapse(self, auto: bool = False) -> None:
        if self.collapsed:
            return
        if not self.dock.isFloating() and self.dock.width() > STRIP_WIDTH + 20:
            self.width_before = int(self.dock.width())
        self.collapsed, self.auto_collapsed = True, auto
        self.panel.full.setMinimumWidth(0)
        self.panel.show_collapsed(True)
        self.dock.setMaximumWidth(STRIP_WIDTH + 16)
        if self.dock.isFloating():
            self.dock.resize(STRIP_WIDTH, self.dock.height())
        else:
            self._resize_docked(STRIP_WIDTH)
        self._save_timer.start()

    def expand(self) -> None:
        if not self.collapsed:
            self.dock.show()
            self.dock.raise_()
            return
        self.collapsed = self.auto_collapsed = False
        # Widen first, then show the full screen: shown while still strip-narrow, its
        # rows of buttons wrapped tall and FreeCAD's window grew to fit them and never
        # shrank back -- page 1 then ran off the bottom of his screen (ORDER-2026-10-19-01).
        window = self.window
        height_before = window.height() if window is not None and not window.isMaximized() else 0
        self.dock.setMaximumWidth(16777215)
        if self.dock.isFloating():
            geometry = self.settings.get("float_geometry") or [0, 0, *DEFAULT_FLOAT_SIZE]
            self.dock.resize(int(geometry[2]), self.dock.height())
        else:
            self._resize_docked(self.width_before or 860)
        self.panel.full.setMinimumWidth(FULL_MIN_WIDTH)
        self.panel.show_collapsed(False)
        self.dock.show()
        if not self.dock.isFloating():
            self._resize_docked(self.width_before or 860)
        if height_before:
            for delay in KEEP_HEIGHT_CHECKS_MS:          # the layout settles over several passes
                self.QtCore.QTimer.singleShot(delay, lambda: self._keep_height(height_before))
        self.panel.picture_signature = None
        self._save_timer.start()

    def _keep_height(self, height: int) -> None:
        """Opening CADWiz never leaves FreeCAD's window taller than it was."""
        with contextlib.suppress(Exception):
            if self.window.height() > height and not self.window.isMaximized():
                self.window.resize(self.window.width(), height)

    def _watch_sketcher(self) -> None:
        """Editing a sketch: CADWiz steps aside to its strip, and comes back after."""
        from integrations.cadwiz_plugin.view_link import sketch_in_edit

        gui = None
        with contextlib.suppress(Exception):
            gui = import_module("FreeCADGui")
        editing = bool(gui is not None and sketch_in_edit(gui))
        if editing and not self.collapsed:
            self.collapse(auto=True)
        elif not editing and self.collapsed and self.auto_collapsed:
            self.expand()

    # ---- the toolbar button, in every workbench ---------------------------------------------------
    def _ensure_toolbar(self) -> Any:
        window = self.window
        if window is None:
            return None
        existing = window.findChild(self.QtWidgets.QToolBar, TOOLBAR_NAME)
        if existing is not None:
            return existing
        toolbar = self.QtWidgets.QToolBar("CADWiz", window)
        toolbar.setObjectName(TOOLBAR_NAME)
        action = toolbar.addAction("CADWiz")
        action.setObjectName("CADWiz_Panel_Toggle")
        action.setToolTip("Bring back the CADWiz screen")
        with contextlib.suppress(Exception):
            frames = self.panel.wiz_player.frames
            if frames:
                action.setIcon(self.QtGui.QIcon(frames[9] if len(frames) > 9 else frames[0]))
        action.triggered.connect(self.bring_back)
        window.addToolBar(toolbar)
        toolbar.show()
        return toolbar

    def bring_back(self) -> None:
        self.dock.show()
        if self.collapsed:
            self.expand()
        self.dock.raise_()

    def _workbench_changed(self, _name: Any = None) -> None:
        """A workbench switch never hides CADWiz or its button."""
        with contextlib.suppress(Exception):
            if self.toolbar is not None and not self.toolbar.isVisible():
                self.toolbar.show()


def _find_dock(window: Any, cls: Any, name: str) -> Any:
    for alias in DOCK_ALIASES[name]:
        found = window.findChild(cls, alias)
        if found is not None:
            return found
    return None


def _rect(geometry: Any) -> tuple[int, int, int, int]:
    return (int(geometry.x()), int(geometry.y()), int(geometry.width()), int(geometry.height()))
