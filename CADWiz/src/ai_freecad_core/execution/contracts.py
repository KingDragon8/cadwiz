# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Immutable command contracts for the future single FreeCAD mutation path."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class CommandRisk(str, Enum):
    """Policy risk assigned before a command can enter execution."""

    READ_ONLY = "read_only"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    PRIVILEGED = "privileged"


class CommandKind(str, Enum):
    """Supported command envelopes without native implementation details."""

    STRUCTURED = "structured"
    PRIVILEGED_PYTHON = "privileged_python"


class BatchAtomicity(str, Enum):
    """Transaction expectation for a command batch."""

    ALL_OR_NOTHING = "all_or_nothing"
    PER_COMMAND = "per_command"


class CommandStatus(str, Enum):
    """Transport-safe command outcome states; not validation verdicts."""

    ACCEPTED = "accepted"
    REJECTED = "rejected"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"
    CANCELLED = "cancelled"


class CommandErrorCode(str, Enum):
    """Stable categories for command validation and future execution errors."""

    INVALID_COMMAND = "invalid_command"
    STALE_STATE = "stale_state"
    CAPABILITY_DENIED = "capability_denied"
    PROTECTION_FAILED = "protection_failed"
    EXECUTION_FAILED = "execution_failed"
    RECOMPUTE_FAILED = "recompute_failed"
    ROLLBACK_FAILED = "rollback_failed"
    TIMEOUT = "timeout"


@dataclass(frozen=True, slots=True)
class CommandArgument:
    """Named serialization-safe argument to a structured command."""

    name: str
    value: str | int | float | bool | None
    unit: str | None = None

    def __post_init__(self) -> None:
        _text(self.name, "argument name")


@dataclass(frozen=True, slots=True)
class CommandTarget:
    """Document and optimistic model revision a command expects to mutate."""

    document_id: str
    expected_model_revision: int
    object_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _text(self.document_id, "document identifier")
        if self.expected_model_revision < 0:
            raise ValueError("expected model revision must be non-negative")
        _tuple(self.object_ids, "target object identifiers")
        _unique(self.object_ids, "target object identifiers")


@dataclass(frozen=True, slots=True)
class StructuredCommand:
    """Preferred declarative model operation dispatched by capability name."""

    identifier: str
    capability: str
    target: CommandTarget
    risk: CommandRisk
    timeout_seconds: float
    arguments: tuple[CommandArgument, ...] = ()
    affected_object_ids: tuple[str, ...] = ()
    validation_profile_ids: tuple[str, ...] = ()
    preconditions: tuple[str, ...] = ()
    expected_postconditions: tuple[str, ...] = ()
    source_requirement_ids: tuple[str, ...] = ()
    kind: CommandKind = CommandKind.STRUCTURED

    def __post_init__(self) -> None:
        _common(self.identifier, self.capability, self.timeout_seconds)
        if self.kind is not CommandKind.STRUCTURED:
            raise ValueError("structured command kind cannot be overridden")
        for values, label in (
            (self.arguments, "command arguments"),
            (self.affected_object_ids, "affected object identifiers"),
            (self.validation_profile_ids, "validation profile identifiers"),
            (self.preconditions, "command preconditions"),
            (self.expected_postconditions, "expected command postconditions"),
            (self.source_requirement_ids, "source requirement identifiers"),
        ):
            _tuple(values, label)
        _unique(tuple(item.name for item in self.arguments), "command argument names")
        _unique(self.affected_object_ids, "affected object identifiers")
        _unique(self.validation_profile_ids, "validation profile identifiers")
        _unique(self.source_requirement_ids, "source requirement identifiers")


@dataclass(frozen=True, slots=True)
class PrivilegedPythonCommand:
    """Exceptional restricted Python request, explicitly distinct from structured commands."""

    identifier: str
    target: CommandTarget
    timeout_seconds: float
    source: str
    declared_capabilities: tuple[str, ...]
    validation_profile_ids: tuple[str, ...] = ()
    risk: CommandRisk = CommandRisk.PRIVILEGED
    kind: CommandKind = CommandKind.PRIVILEGED_PYTHON

    def __post_init__(self) -> None:
        _common(self.identifier, "privileged_python", self.timeout_seconds)
        _text(self.source, "Python source")
        _tuple(self.declared_capabilities, "declared capabilities")
        if not self.declared_capabilities:
            raise ValueError("privileged Python must declare at least one capability")
        if (
            self.risk is not CommandRisk.PRIVILEGED
            or self.kind is not CommandKind.PRIVILEGED_PYTHON
        ):
            raise ValueError("privileged Python risk and kind cannot be weakened")


Command = StructuredCommand | PrivilegedPythonCommand


@dataclass(frozen=True, slots=True)
class BatchCommand:
    """One command and its explicit command-level dependencies in a batch."""

    command: Command
    depends_on: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _tuple(self.depends_on, "command dependencies")
        _unique(self.depends_on, "command dependencies")
        if self.command.identifier in self.depends_on:
            raise ValueError("command cannot depend on itself")


@dataclass(frozen=True, slots=True)
class CommandBatch:
    """Ordered command graph with an explicit transaction expectation."""

    identifier: str
    commands: tuple[BatchCommand, ...]
    atomicity: BatchAtomicity = BatchAtomicity.ALL_OR_NOTHING

    def __post_init__(self) -> None:
        _text(self.identifier, "batch identifier")
        _tuple(self.commands, "batch commands")
        if not self.commands:
            raise ValueError("command batch must not be empty")
        identifiers = tuple(item.command.identifier for item in self.commands)
        _unique(identifiers, "command identifiers")
        known = set(identifiers)
        for item in self.commands:
            unknown = set(item.depends_on) - known
            if unknown:
                raise ValueError(f"command dependency is not in batch: {sorted(unknown)[0]}")


@dataclass(frozen=True, slots=True)
class CommandError:
    """Structured command failure safe for UI and MCP serialization."""

    code: CommandErrorCode
    message: str
    retryable: bool = False
    technical_detail: str | None = None


@dataclass(frozen=True, slots=True)
class CommandResult:
    """Execution-stage result that deliberately carries no geometry-verification flag."""

    command_id: str
    status: CommandStatus
    starting_model_revision: int
    resulting_model_revision: int | None = None
    changed_object_ids: tuple[str, ...] = ()
    errors: tuple[CommandError, ...] = ()

    def __post_init__(self) -> None:
        _text(self.command_id, "command identifier")
        if self.starting_model_revision < 0:
            raise ValueError("starting model revision must be non-negative")
        if self.resulting_model_revision is not None and self.resulting_model_revision < 0:
            raise ValueError("resulting model revision must be non-negative")
        _tuple(self.changed_object_ids, "changed object identifiers")
        _tuple(self.errors, "command errors")


def _common(identifier: str, capability: str, timeout: float) -> None:
    _text(identifier, "command identifier")
    _text(capability, "command capability")
    if timeout <= 0:
        raise ValueError("command timeout must be positive")


def _text(value: str, label: str) -> None:
    if not value.strip():
        raise ValueError(f"{label} must not be empty")


def _tuple(value: object, label: str) -> None:
    if not isinstance(value, tuple):
        raise TypeError(f"{label} must be a tuple")


def _unique(values: tuple[object, ...], label: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"{label} must be unique")
