# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""The evidence trail for why a request was answered the way it was.

Every routing decision, provider call, tool call, escalation and failure lands
here as a machine-readable event tied to one correlation id, so a run can be
reconstructed afterwards by something that was not present when it happened.

Four rules, and they are the whole point:

**Nothing is fabricated.** A value that could not be measured is recorded as
`UNKNOWN`, never as zero, an empty string, or a plausible estimate. A cost of
0.0 means the call was free; a cost of `UNKNOWN` means nobody knows what it
cost. Collapsing those two is how a bill becomes unexplainable.

**Secrets never enter the log.** Redaction happens when the event is recorded,
not when it is read, because a log that is only safe if every reader remembers
to redact is not safe.

**Negative decisions are evidence.** A rejected candidate and a refusal to
escalate are recorded with the same weight as a selection. They are what shows
the cheap path was tried, and without them a low bill is indistinguishable from
luck.

**Order is recorded, not inferred.** Events carry a sequence number as well as
a timestamp. Two events in the same millisecond are common, and reconstructing
a run from timestamps alone silently reorders them.
"""

from __future__ import annotations

import json
import os
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Callable, Protocol
from uuid import uuid4

from .security import redact_diagnostics

#: What a value is when it could not be determined. Never substituted with a
#: default -- see the module docstring.
UNKNOWN = "UNKNOWN"


class EventKind(StrEnum):
    REQUEST_RECEIVED = "request_received"
    TASK_CLASSIFIED = "task_classified"
    CANDIDATES_EVALUATED = "candidates_evaluated"
    CANDIDATE_REJECTED = "candidate_rejected"
    MODEL_SELECTED = "model_selected"
    APPROVAL_REQUIRED = "approval_required"
    PROVIDER_CALLED = "provider_called"
    PROVIDER_RESULT = "provider_result"
    FALLBACK_SELECTED = "fallback_selected"
    RETRY = "retry"
    ESCALATED = "escalated"
    ESCALATION_DECLINED = "escalation_declined"
    TOOL_SELECTION = "tool_selection"
    TOOL_CALLED = "tool_called"
    TOOL_RESULT = "tool_result"
    FOLLOW_UP_REASONING = "follow_up_reasoning"
    COST_REPORTED = "cost_reported"
    FAILURE = "failure"
    FINAL_RESULT = "final_result"


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """One thing that happened, and when, within one run."""

    correlation_id: str
    sequence: int
    kind: EventKind
    occurred_at: str
    payload: dict[str, Any] = field(default_factory=dict)
    event_id: str = ""

    def machine_readable(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id or UNKNOWN,
            "correlation_id": self.correlation_id,
            "sequence": self.sequence,
            "kind": self.kind.value,
            "occurred_at": self.occurred_at,
            "payload": self.payload,
        }


class AuditSink(Protocol):
    """Where events go. Deliberately narrow so a sink cannot alter a run."""

    def write(self, event: AuditEvent) -> None: ...


@dataclass(slots=True)
class InMemoryAuditSink:
    """Collects events. Enough for tests, benchmarks, and one session."""

    events: list[AuditEvent] = field(default_factory=list)

    def write(self, event: AuditEvent) -> None:
        self.events.append(event)

    def for_run(self, correlation_id: str) -> tuple[AuditEvent, ...]:
        return tuple(
            event for event in self.events if event.correlation_id == correlation_id
        )

    def of_kind(self, kind: EventKind) -> tuple[AuditEvent, ...]:
        return tuple(event for event in self.events if event.kind is kind)


def default_audit_log_root() -> Path:
    """Keep the on-disk audit log beside other app data, not in the repository.

    Mirrors `ai_freecad_core.tool_analytics.default_tool_ledger_path` exactly
    -- same base directory, same reasoning -- so an operator looking for
    CADWiz's local state finds both under one parent rather than two
    unrelated ones.
    """
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".local" / "share")
    return base / "CADWiz" / "audit"


@dataclass(slots=True)
class FilesystemAuditSink:
    """Append-only, dated on-disk `AuditSink`.

    Per the founder's 2026-09-07 Phase 1 closeout ruling: `InMemoryAuditSink`
    was, until now, the only concrete sink anywhere in this tree, so every
    audit event vanished when the process exited -- the second half of why
    `provenance_survival` was blocked (docs/reports/2026-09-07-provenance-blocker.md).
    This does not by itself fix provenance (the stamp on the FreeCAD object
    carries what a viewer of that object needs, and does not depend on this
    file existing); it closes the *other* gap the report named: a
    correlation id that pointed at nothing durable.

    One file per UTC calendar day (`audit-YYYY-MM-DD.jsonl`), each event one
    JSON Lines row, fsynced before `write` returns -- the same durability
    rule `FilesystemVersionStore._journal` already follows for protected
    versions, applied here to the audit trail instead. A day boundary keeps
    any single file bounded without needing rotation logic, and "which day
    did this happen" is answerable from the filename alone.
    """

    root: Path
    clock: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))

    def write(self, event: AuditEvent) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        day = self.clock().astimezone(UTC).date().isoformat()
        path = self.root / f"audit-{day}.jsonl"
        with path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(
                json.dumps(event.machine_readable(), sort_keys=True, separators=(",", ":"))
            )
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())


def unknown_if_missing(value: Any) -> Any:
    """`UNKNOWN` for anything absent, the value itself otherwise.

    `False` and `0` pass through. They are answers -- "no fallback was used"
    and "this cost nothing" are facts, and turning either into UNKNOWN would
    discard the very thing worth recording.
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        return UNKNOWN
    return value


class AuditRecorder:
    """Records one run's events under a single correlation id.

    Holds the sequence counter so callers cannot get ordering wrong, and
    redacts on the way in so no caller can forget to.
    """

    def __init__(
        self, sink: AuditSink | None = None, correlation_id: str = ""
    ) -> None:
        self._sink = sink or InMemoryAuditSink()
        self.correlation_id = correlation_id or f"run-{uuid4().hex[:16]}"
        self._sequence = 0

    @property
    def sink(self) -> AuditSink:
        return self._sink

    def record(self, kind: EventKind, /, **payload: Any) -> AuditEvent:
        """Write one event. Never raises into the caller's path.

        `kind` is positional-only so a payload may use any key it likes,
        including `kind` itself -- a failure's own kind is exactly what you
        want to record, and a collision there would be found at runtime by
        whichever caller happened to hit it first.

        Telemetry must not be able to fail a request. A run that succeeded but
        could not be recorded is still a run that succeeded, and turning an
        unwritable log into a user-visible error would be the tail wagging the
        dog -- the same rule the tool ledger follows.
        """
        self._sequence += 1
        event = AuditEvent(
            correlation_id=self.correlation_id,
            sequence=self._sequence,
            kind=kind,
            occurred_at=datetime.now(UTC).isoformat(),
            payload={
                key: redact_diagnostics(unknown_if_missing(value))
                for key, value in payload.items()
            },
            event_id=f"event-{uuid4().hex[:16]}",
        )
        with suppress(Exception):
            self._sink.write(event)
        return event

    def as_callable(self) -> Callable[[dict[str, Any]], None]:
        """A `(dict) -> None` for the gateway's existing `audit` hook.

        Lets this replace the no-op without changing the gateway's signature,
        so nothing that already calls it has to know the difference.
        """

        def _audit(event: dict[str, Any]) -> None:
            kind = event.get("status") or event.get("kind") or ""
            self.record(
                EventKind.FINAL_RESULT
                if kind == "completed"
                else EventKind.FAILURE
                if kind == "failed"
                else EventKind.PROVIDER_RESULT,
                **event,
            )

        return _audit
