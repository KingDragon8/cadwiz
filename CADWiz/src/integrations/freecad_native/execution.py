# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Native transaction and protected-copy adapters for safe execution."""

from __future__ import annotations

from collections.abc import Callable
from importlib import import_module
from pathlib import Path
from typing import Any
from uuid import uuid4

from ai_freecad_core.execution.contracts import Command
from ai_freecad_core.execution.service import TransactionHandle

from .dispatch import FreeCADGuiThreadDispatcher


class FreeCADTransactionAdapter:
    """Manage FreeCAD transactions exclusively through the GUI dispatcher."""

    def __init__(
        self,
        dispatcher: FreeCADGuiThreadDispatcher | None = None,
        app_provider: Callable[[], Any] | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._dispatcher = dispatcher or FreeCADGuiThreadDispatcher()
        self._app_provider = app_provider or (lambda: import_module("FreeCAD"))
        self._id_factory = id_factory or (lambda: uuid4().hex)
        self._documents: dict[str, Any] = {}

    def begin(self, command: Command) -> TransactionHandle:
        def operation() -> TransactionHandle:
            document = self._document(command.target.document_id)
            handle = TransactionHandle(self._id_factory())
            document.openTransaction(f"CADWiz: {command.identifier}")
            self._documents[handle.identifier] = document
            return handle

        return self._dispatcher.dispatch(operation)

    def commit(self, transaction: TransactionHandle) -> None:
        self._finish(transaction, "commitTransaction")

    def rollback(self, transaction: TransactionHandle) -> None:
        self._finish(transaction, "abortTransaction")

    def _finish(self, transaction: TransactionHandle, method: str) -> None:
        def operation() -> None:
            document = self._documents.get(transaction.identifier)
            if document is None:
                raise LookupError(f"Unknown transaction: {transaction.identifier}")
            getattr(document, method)()
            self._documents.pop(transaction.identifier, None)

        self._dispatcher.dispatch(operation)

    def _document(self, document_id: str) -> Any:
        name = document_id.removeprefix("freecad:")
        document = self._app_provider().getDocument(name)
        if document is None:
            raise LookupError(f"Document not found: {document_id}")
        return document


class FreeCADDocumentCopySource:
    """Create recovery copies without ever overwriting a live user document."""

    def __init__(
        self,
        dispatcher: FreeCADGuiThreadDispatcher | None = None,
        app_provider: Callable[[], Any] | None = None,
    ) -> None:
        self._dispatcher = dispatcher or FreeCADGuiThreadDispatcher()
        self._app_provider = app_provider or (lambda: import_module("FreeCAD"))

    def write_copy(self, command: Command, destination: Path) -> None:
        def operation() -> None:
            name = command.target.document_id.removeprefix("freecad:")
            document = self._app_provider().getDocument(name)
            if document is None:
                raise LookupError(f"Document not found: {command.target.document_id}")
            document.saveCopy(str(destination))

        self._dispatcher.dispatch(operation)

    def restore_copy(self, source: Path, document_id: str) -> None:
        raise RuntimeError(
            "Automatic in-place FreeCAD restore is disabled; "
            f"recover {document_id} from protected copy {source}"
        )
