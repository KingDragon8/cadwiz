# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Fail-closed GUI-thread dispatch boundary for native FreeCAD access."""

from collections.abc import Callable
from importlib import import_module
from threading import current_thread, main_thread
from typing import TypeVar

T = TypeVar("T")


class GuiThreadViolation(RuntimeError):
    """Raised when GUI-sensitive work is requested from a background thread."""


class FreeCADGuiThreadDispatcher:
    """Execute on the GUI thread and refuse unsafe background access.

    Asynchronous Qt scheduling will be added with native UI composition. This
    adapter never silently runs native work on the wrong thread.
    """

    def __init__(self, thread_check: Callable[[], bool] | None = None) -> None:
        self._thread_check = thread_check or self._is_current_gui_thread

    def is_gui_thread(self) -> bool:
        return self._thread_check()

    def dispatch(self, operation: Callable[[], T]) -> T:
        if not self.is_gui_thread():
            raise GuiThreadViolation("FreeCAD GUI access requires the GUI thread")
        return operation()

    @staticmethod
    def _is_current_gui_thread() -> bool:
        try:
            app_module = import_module("FreeCAD")
            if not getattr(app_module, "GuiUp", False):
                return current_thread() is main_thread()
            QtCore = import_module("PySide.QtCore")
            QtWidgets = import_module("PySide.QtWidgets")
            application = QtWidgets.QApplication.instance()
            return (
                application is not None and QtCore.QThread.currentThread() == application.thread()
            )
        except (ImportError, AttributeError):
            return False
