# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Public command contracts and host-neutral execution composition."""

from .adapters import RefreshingCommandExecutionAdapter, SnapshotRevisionReader
from .contracts import (
    BatchAtomicity,
    BatchCommand,
    Command,
    CommandArgument,
    CommandBatch,
    CommandError,
    CommandErrorCode,
    CommandKind,
    CommandResult,
    CommandRisk,
    CommandStatus,
    CommandTarget,
    PrivilegedPythonCommand,
    StructuredCommand,
)
from .service import (
    CommandExecutionAdapter,
    ModelRevisionReader,
    SafeExecutionReport,
    SafeExecutionService,
    TransactionAdapter,
    TransactionHandle,
)

__all__ = [name for name in globals() if not name.startswith("_")]
