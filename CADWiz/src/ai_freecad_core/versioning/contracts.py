# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Host-neutral protected-version contracts for recoverable model mutation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ai_freecad_core.execution.contracts import Command


@dataclass(frozen=True, slots=True)
class DocumentVersionId:
    """Stable identity of a protected document version."""

    value: str

    def __post_init__(self) -> None:
        if not self.value.strip():
            raise ValueError("document version identifier must not be empty")


@dataclass(frozen=True, slots=True)
class ProtectedVersion:
    """Immutable metadata proving a recoverable version was created."""

    version_id: DocumentVersionId
    document_id: str
    source_model_revision: int
    content_hash: str
    storage_location: str


class VersionStore(Protocol):
    """Port that must durably protect state before mutation starts."""

    def create_protected_version(self, command: Command) -> ProtectedVersion: ...

    def restore(self, version: ProtectedVersion) -> None: ...
