# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Adapters that connect native reads to the canonical live-state service."""

from __future__ import annotations

from ai_freecad_core.contracts import DocumentIdentity, SelectionState
from ai_freecad_core.model_state import ActiveDocumentCapture
from ai_freecad_core.model_state.observers import ChangeListener

from .adapter import FreeCADReadAdapter, _Subscription
from .dispatch import FreeCADGuiThreadDispatcher


class FreeCADModelStateBridge:
    """Implement all live-state read ports through one serialized native reader."""

    def __init__(
        self,
        reader: FreeCADReadAdapter,
        dispatcher: FreeCADGuiThreadDispatcher,
    ) -> None:
        self._reader = reader
        self._dispatcher = dispatcher
        self._subscription: _Subscription | None = None

    def capture(
        self, document: DocumentIdentity | None = None
    ) -> ActiveDocumentCapture | SelectionState:
        """Capture active-document state or selection for the supplied context."""
        if document is not None:
            return self._dispatcher.dispatch(lambda: self._reader.selection(document))

        def active() -> ActiveDocumentCapture:
            identity = self._reader.active_document()
            return ActiveDocumentCapture(
                identity,
                recompute=self._reader.recompute_status(identity),
            )

        return self._dispatcher.dispatch(active)

    def start(self, listener: ChangeListener) -> None:
        if self._subscription is not None:
            return
        self._subscription = self._dispatcher.dispatch(lambda: self._reader.subscribe(listener))

    def stop(self) -> None:
        subscription = self._subscription
        if subscription is None:
            return
        self._subscription = None
        self._dispatcher.dispatch(subscription.cancel)


class FreeCADActiveDocumentPort:
    """Narrow active-document view of the shared native state bridge."""

    def __init__(self, bridge: FreeCADModelStateBridge) -> None:
        self._bridge = bridge

    def capture(self) -> ActiveDocumentCapture:
        result = self._bridge.capture()
        if not isinstance(result, ActiveDocumentCapture):
            raise TypeError("Native bridge returned selection for active-document capture")
        return result


class FreeCADSelectionPort:
    """Narrow selection view of the shared native state bridge."""

    def __init__(self, bridge: FreeCADModelStateBridge) -> None:
        self._bridge = bridge

    def capture(self, document: DocumentIdentity | None) -> SelectionState:
        if document is None:
            return SelectionState()
        result = self._bridge.capture(document)
        if not isinstance(result, SelectionState):
            raise TypeError("Native bridge returned document state for selection capture")
        return result
