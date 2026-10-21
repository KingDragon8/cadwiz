# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Small host-neutral adapters used to compose the single execution pathway."""

from __future__ import annotations

from typing import Protocol

from ai_freecad_core.contracts import ModelSnapshot

from .contracts import Command
from .service import CommandExecutionAdapter


class SnapshotProvider(Protocol):
    """Return or refresh the canonical immutable model snapshot."""

    def get_snapshot(self) -> ModelSnapshot: ...

    def refresh(self) -> ModelSnapshot: ...


class SnapshotRevisionReader:
    """Read revisions only when the requested document is the canonical document."""

    def __init__(self, snapshots: SnapshotProvider) -> None:
        self._snapshots = snapshots

    def current_revision(self, document_id: str) -> int:
        snapshot = self._snapshots.get_snapshot()
        if snapshot.document is None or snapshot.document.document_id != document_id:
            raise LookupError(f"Document is not the canonical active document: {document_id}")
        return snapshot.revision


class RefreshingCommandExecutionAdapter:
    """Refresh canonical state synchronously after successful native mutation."""

    def __init__(self, executor: CommandExecutionAdapter, snapshots: SnapshotProvider) -> None:
        self._executor = executor
        self._snapshots = snapshots

    def execute(self, command: Command) -> tuple[str, ...]:
        changed = self._executor.execute(command)
        self._snapshots.refresh()
        return changed
