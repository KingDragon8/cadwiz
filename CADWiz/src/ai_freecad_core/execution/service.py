# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Host-neutral safe execution coordination behind explicit adapter ports."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ai_freecad_core.versioning.contracts import ProtectedVersion, VersionStore

from .contracts import (
    Command,
    CommandError,
    CommandErrorCode,
    CommandResult,
    CommandStatus,
)


@dataclass(frozen=True, slots=True)
class TransactionHandle:
    """Opaque identity of one native transaction boundary."""

    identifier: str

    def __post_init__(self) -> None:
        if not self.identifier.strip():
            raise ValueError("transaction identifier must not be empty")


class ModelRevisionReader(Protocol):
    """Read the canonical current model revision for stale-state checks."""

    def current_revision(self, document_id: str) -> int: ...


class TransactionAdapter(Protocol):
    """Open, commit, or abort a native transaction on the proper host thread."""

    def begin(self, command: Command) -> TransactionHandle: ...

    def commit(self, transaction: TransactionHandle) -> None: ...

    def rollback(self, transaction: TransactionHandle) -> None: ...


class CommandExecutionAdapter(Protocol):
    """Single native mutation port; implementations dispatch typed commands."""

    def execute(self, command: Command) -> tuple[str, ...]: ...


@dataclass(frozen=True, slots=True)
class SafeExecutionReport:
    """Correlated execution outcome with protection and transaction evidence."""

    result: CommandResult
    protected_version: ProtectedVersion | None = None
    transaction_id: str | None = None
    rollback_attempted: bool = False
    rollback_succeeded: bool = False


class SafeExecutionService:
    """Enforce stale checks, protection, transactions, and rollback in one path."""

    def __init__(
        self,
        revisions: ModelRevisionReader,
        versions: VersionStore,
        transactions: TransactionAdapter,
        executor: CommandExecutionAdapter,
    ) -> None:
        self._revisions = revisions
        self._versions = versions
        self._transactions = transactions
        self._executor = executor

    def execute(self, command: Command) -> SafeExecutionReport:
        """Execute only after freshness and durable protection preconditions pass."""
        starting_revision = self._revisions.current_revision(command.target.document_id)
        if starting_revision != command.target.expected_model_revision:
            return SafeExecutionReport(
                CommandResult(
                    command.identifier,
                    CommandStatus.REJECTED,
                    starting_revision,
                    errors=(
                        CommandError(
                            CommandErrorCode.STALE_STATE,
                            "Expected model revision does not match current revision",
                        ),
                    ),
                )
            )

        try:
            protected = self._versions.create_protected_version(command)
        except Exception as error:
            return SafeExecutionReport(
                CommandResult(
                    command.identifier,
                    CommandStatus.REJECTED,
                    starting_revision,
                    errors=(_error(CommandErrorCode.PROTECTION_FAILED, error),),
                )
            )

        transaction: TransactionHandle | None = None
        try:
            transaction = self._transactions.begin(command)
            changed = self._executor.execute(command)
            self._transactions.commit(transaction)
            resulting_revision = self._revisions.current_revision(command.target.document_id)
            return SafeExecutionReport(
                CommandResult(
                    command.identifier,
                    CommandStatus.SUCCEEDED,
                    starting_revision,
                    resulting_revision,
                    changed,
                ),
                protected,
                transaction.identifier,
            )
        except Exception as execution_error:
            errors = [_error(CommandErrorCode.EXECUTION_FAILED, execution_error)]
            rollback_attempted = transaction is not None
            rollback_succeeded = False
            if transaction is not None:
                try:
                    self._transactions.rollback(transaction)
                    rollback_succeeded = True
                except Exception as rollback_error:
                    errors.append(_error(CommandErrorCode.ROLLBACK_FAILED, rollback_error))
                    try:
                        self._versions.restore(protected)
                        rollback_succeeded = True
                    except Exception as restore_error:
                        errors.append(_error(CommandErrorCode.ROLLBACK_FAILED, restore_error))
            status = CommandStatus.ROLLED_BACK if rollback_succeeded else CommandStatus.FAILED
            return SafeExecutionReport(
                CommandResult(
                    command.identifier,
                    status,
                    starting_revision,
                    errors=tuple(errors),
                ),
                protected,
                transaction.identifier if transaction else None,
                rollback_attempted,
                rollback_succeeded,
            )


def _error(code: CommandErrorCode, error: Exception) -> CommandError:
    return CommandError(code, str(error) or code.value, technical_detail=type(error).__name__)
