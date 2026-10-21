# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Privacy-safe tool-call telemetry and evidence-based Pareto analysis."""

from __future__ import annotations

import os
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from uuid import uuid4

_IDENTIFIER = re.compile(r"^[A-Za-z0-9_.:-]{1,160}$")
_OUTCOMES = {"success", "failure", "refused", "verification_failed"}
_VERIFICATIONS = {"not_required", "rendered", "headless_skipped", "failed", "not_run"}
_CORRECTIONS = {"not_observed", "corrected", "undone"}
_OBJECTIVES = {"unknown", "completed", "partial", "failed"}


@dataclass(frozen=True, slots=True)
class ToolCallContext:
    """Context that may accompany a tool operation.

    `workflow_id`, `workflow`, `mode`, `retry_index` and `fallback_used` are
    the non-sensitive fields `ToolCallLedger.record` persists -- it reads
    each by name, so nothing added below reaches that ledger by accident.

    `intent_id` and `user_request` exist only to be stamped onto the object a
    mutating tool call creates (`integrations.provenance.attach_tool_provenance`,
    the founder's 2026-09-07 Phase 1 closeout ruling), never to be persisted
    as telemetry. `session_id` needs no field of its own: `workflow_id` is
    already this codebase's per-request correlation id (it is what
    `AuditRecorder` is given as `correlation_id` in
    `integrations.mcp_tools.service`), so the provenance stamp reads it
    directly rather than duplicating it under a second name.
    """

    workflow_id: str = ""
    workflow: str = "direct"
    mode: str = "unknown"
    retry_index: int = 0
    fallback_used: bool = False
    intent_id: str = ""
    user_request: str = ""
    #: PROVE-SWEEP (2026-09-10): true when the IR executor dispatched this
    #: call to a tool docs/TOOL-REGISTER.json does not (yet) record as
    #: PROVEN (eight-point-harness 8/8). The planner rule this exists for:
    #: "prefer PROVEN tools; if the plan reaches for an unproven tool, log
    #: it as an ASSUMED step ... and record it in telemetry. No silent
    #: unproven calls." Never inferred after the fact -- the executor sets
    #: this before the call, from the same registry a human reading
    #: TOOL-REGISTER.json would.
    assumed_unproven_tool: bool = False

    def normalized_workflow_id(self) -> str:
        return self.workflow_id or f"workflow-{uuid4().hex}"


@dataclass(frozen=True, slots=True)
class ToolCallTimer:
    """Monotonic timer retained separately from persisted wall-clock metadata."""

    started: float

    @classmethod
    def start(cls) -> ToolCallTimer:
        return cls(monotonic())

    def milliseconds(self) -> int:
        return max(0, round((monotonic() - self.started) * 1000))


def _repo_root(start: Path | None = None) -> Path:
    """Walk up from `start` (this file, by default) to the nearest directory
    holding `.git` -- a real directory in the main checkout, a file
    (`gitdir: ...`) in a worktree, `.exists()` is true either way. Falls
    back to `start`'s own parent if none is found (an install with no
    `.git` at all), rather than raising over a telemetry path."""
    current = (start or Path(__file__)).resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    return current.parent


def default_tool_ledger_path() -> Path:
    """Per-worktree by default, not one fixed machine-wide file.

    Root cause (2026-09-09): every process that builds a `ToolInvoker`
    without an explicit `ledger=` opens this same path. A single fixed
    location under `%LOCALAPPDATA%` meant a second CADWiz process on the
    same machine -- another worktree, another agent's session, a
    concurrent qualification run -- contended for the identical SQLite
    file. Confirmed 2026-09-08/09: this session ran many overlapping
    `freecadcmd` processes each constructing their own `ToolInvoker`
    against that one file, and traced part of that session's own
    unexplained process instability to lock contention there.

    `artifacts/` is already gitignored (`artifacts/*`), so a repo-root-
    relative path here needs no new ignore rule and naturally gives each
    worktree (each with its own `.git` file/dir and its own `artifacts/`)
    a separate ledger. `CADWIZ_TOOL_LEDGER_PATH` overrides this for a
    caller that genuinely wants one shared location (a fleet dashboard
    aggregating several worktrees, say).
    """
    override = os.environ.get("CADWIZ_TOOL_LEDGER_PATH")
    if override:
        return Path(override)
    return _repo_root() / "artifacts" / "telemetry" / "tool-calls.sqlite3"


def operation_category(tool_name: str) -> str:
    """Map a registered tool name to a stable, non-sensitive operation family."""
    name = tool_name.casefold()
    if name.startswith(("fit_", "zoom_", "toggle_")) or "screenshot" in name:
        return "view"
    if name.startswith(
        ("get_", "list_", "describe_", "validate_", "check_", "measure_", "inspect_", "read_")
    ):
        return "inspection"
    if name.startswith(("export_", "import_")):
        return "exchange"
    if "document" in name or name.startswith(("open_", "close_", "save_")):
        return "document"
    if name.startswith(
        ("create_", "add_", "delete_", "set_", "fillet_", "boolean_", "pad_", "pocket_", "sketch_")
    ):
        return "modeling"
    return "other"


class ToolCallLedger:
    """Append-only local ledger that deliberately has no prompt or argument columns."""

    def __init__(self, path: Path) -> None:
        self.path = path.resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    #: How long a connection waits on `SQLITE_BUSY` before raising
    #: `sqlite3.OperationalError: database is locked`. Raised from 10s to
    #: 60s (2026-09-09) alongside the per-worktree path default above -- the
    #: path fix removes most real contention, but a caller that still
    #: shares a ledger on purpose (`CADWIZ_TOOL_LEDGER_PATH`) should get a
    #: generous wait under real concurrent write load, not a fast failure.
    _LOCK_TIMEOUT_SECONDS = 60

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=self._LOCK_TIMEOUT_SECONDS)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS tool_catalog (
                    tool_name TEXT PRIMARY KEY,
                    category TEXT NOT NULL,
                    first_seen_at TEXT NOT NULL,
                    standard_set INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS tool_calls (
                    event_id TEXT PRIMARY KEY,
                    occurred_at TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    category TEXT NOT NULL,
                    workflow_id TEXT NOT NULL,
                    workflow TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    mutating INTEGER NOT NULL,
                    verified INTEGER NOT NULL,
                    verification TEXT NOT NULL,
                    duration_ms INTEGER NOT NULL,
                    argument_count INTEGER NOT NULL,
                    retry_index INTEGER NOT NULL,
                    fallback_used INTEGER NOT NULL,
                    correction TEXT NOT NULL DEFAULT 'not_observed',
                    objective_outcome TEXT NOT NULL DEFAULT 'unknown',
                    assumed_unproven_tool INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_tool_calls_name ON tool_calls(tool_name);
                CREATE INDEX IF NOT EXISTS idx_tool_calls_time ON tool_calls(occurred_at);
                CREATE INDEX IF NOT EXISTS idx_tool_calls_workflow ON tool_calls(workflow_id);
                """
            )

    def register_tools(
        self, names: tuple[str, ...], *, standard_tools: tuple[str, ...] = ()
    ) -> None:
        now = datetime.now(UTC).isoformat()
        standard = set(standard_tools)
        rows = [
            (name, operation_category(name), now, int(name in standard))
            for name in names
            if _IDENTIFIER.fullmatch(name)
        ]
        with self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO tool_catalog(tool_name, category, first_seen_at, standard_set)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(tool_name) DO UPDATE SET
                    category=excluded.category,
                    standard_set=MAX(tool_catalog.standard_set, excluded.standard_set)
                """,
                rows,
            )

    def record(
        self,
        *,
        tool_name: str,
        context: ToolCallContext,
        outcome: str,
        mutating: bool,
        verified: bool,
        verification: str,
        duration_ms: int,
        argument_count: int,
    ) -> str:
        """Persist bounded metadata only; argument values have no storage field."""
        if not _IDENTIFIER.fullmatch(tool_name):
            raise ValueError("tool telemetry requires a bounded tool identifier")
        if outcome not in _OUTCOMES:
            raise ValueError("unsupported tool outcome")
        if verification not in _VERIFICATIONS:
            raise ValueError("unsupported verification outcome")
        if duration_ms < 0 or argument_count < 0 or context.retry_index < 0:
            raise ValueError("tool telemetry counters cannot be negative")
        workflow_id = context.normalized_workflow_id()
        for value, label in (
            (workflow_id, "workflow identifier"),
            (context.workflow, "workflow"),
            (context.mode, "mode"),
        ):
            if not _IDENTIFIER.fullmatch(value):
                raise ValueError(f"tool telemetry requires a bounded {label}")
        event_id = f"tool-call-{uuid4().hex}"
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO tool_calls(
                    event_id, occurred_at, tool_name, category, workflow_id,
                    workflow, mode, outcome, mutating, verified, verification,
                    duration_ms, argument_count, retry_index, fallback_used,
                    assumed_unproven_tool
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    datetime.now(UTC).isoformat(),
                    tool_name,
                    operation_category(tool_name),
                    workflow_id,
                    context.workflow,
                    context.mode,
                    outcome,
                    int(mutating),
                    int(verified),
                    verification,
                    duration_ms,
                    argument_count,
                    context.retry_index,
                    int(context.fallback_used),
                    int(context.assumed_unproven_tool),
                ),
            )
        return event_id

    def mark_objective(self, workflow_id: str, outcome: str) -> None:
        if outcome not in _OBJECTIVES:
            raise ValueError("unsupported objective outcome")
        if not _IDENTIFIER.fullmatch(workflow_id):
            raise ValueError("invalid workflow identifier")
        with self._connect() as connection:
            connection.execute(
                "UPDATE tool_calls SET objective_outcome=? WHERE workflow_id=?",
                (outcome, workflow_id),
            )

    def mark_correction(self, event_id: str, correction: str) -> None:
        if correction not in _CORRECTIONS:
            raise ValueError("unsupported correction outcome")
        if not _IDENTIFIER.fullmatch(event_id):
            raise ValueError("invalid tool-call identifier")
        with self._connect() as connection:
            connection.execute(
                "UPDATE tool_calls SET correction=? WHERE event_id=?",
                (correction, event_id),
            )

    def events(self) -> list[dict[str, object]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM tool_calls ORDER BY occurred_at, event_id"
            ).fetchall()
        return [dict(row) for row in rows]

    def analytics(self) -> dict[str, object]:
        with self._connect() as connection:
            calls = connection.execute(
                """
                SELECT
                    tool_name,
                    category,
                    COUNT(*) AS calls,
                    SUM(CASE WHEN outcome='success' AND verified=1 THEN 1 ELSE 0 END)
                        AS validated_successes,
                    SUM(CASE WHEN outcome IN ('failure', 'verification_failed') THEN 1 ELSE 0 END)
                        AS failures,
                    SUM(CASE WHEN outcome='refused' THEN 1 ELSE 0 END) AS refusals,
                    SUM(CASE WHEN correction IN ('corrected', 'undone') THEN 1 ELSE 0 END)
                        AS corrections,
                    COUNT(DISTINCT CASE WHEN objective_outcome='completed' THEN workflow_id END)
                        AS objective_completions,
                    COUNT(DISTINCT workflow_id) AS workflows,
                    ROUND(AVG(duration_ms), 1) AS average_duration_ms,
                    SUM(retry_index) AS retries,
                    SUM(fallback_used) AS fallbacks
                FROM tool_calls
                GROUP BY tool_name, category
                ORDER BY validated_successes DESC, calls DESC, tool_name
                """
            ).fetchall()
            totals = connection.execute(
                """
                SELECT
                    COUNT(*) AS calls,
                    SUM(CASE WHEN outcome='success' AND verified=1 THEN 1 ELSE 0 END)
                        AS validated_successes,
                    SUM(CASE WHEN outcome IN ('failure', 'verification_failed') THEN 1 ELSE 0 END)
                        AS failures,
                    SUM(CASE WHEN outcome='refused' THEN 1 ELSE 0 END) AS refusals
                FROM tool_calls
                """
            ).fetchone()
            catalog = connection.execute(
                "SELECT tool_name, category, standard_set FROM tool_catalog ORDER BY tool_name"
            ).fetchall()

        total_validated = int(totals["validated_successes"] or 0)
        cumulative = 0
        tools = []
        for row in calls:
            item = dict(row)
            validated = int(item["validated_successes"] or 0)
            share = validated / total_validated if total_validated else 0.0
            before = cumulative
            cumulative += validated
            cumulative_share = cumulative / total_validated if total_validated else 0.0
            pareto_core = bool(total_validated and before / total_validated < 0.8)
            call_count = int(item["calls"])
            failure_rate = int(item["failures"] or 0) / call_count
            validated_rate = validated / call_count
            if call_count >= 5 and failure_rate >= 0.2:
                classification = "review"
            elif (
                pareto_core
                and call_count >= 10
                and validated_rate >= 0.9
                and int(item["workflows"]) >= 3
                and int(item["objective_completions"] or 0) >= 3
            ):
                classification = "candidate"
            elif validated and not pareto_core:
                classification = "specialist"
            else:
                classification = "insufficient_evidence"
            item.update(
                {
                    "validated_rate": round(validated_rate, 4),
                    "failure_rate": round(failure_rate, 4),
                    "share": round(share, 4),
                    "cumulative_share": round(cumulative_share, 4),
                    "pareto_core": pareto_core,
                    "classification": classification,
                }
            )
            tools.append(item)

        called_names = {str(item["tool_name"]) for item in tools}
        unused = [
            {"tool_name": row["tool_name"], "category": row["category"]}
            for row in catalog
            if row["tool_name"] not in called_names
        ]
        return {
            "available": bool(int(totals["calls"] or 0)),
            "ledger_path": str(self.path),
            "summary": {
                "calls": int(totals["calls"] or 0),
                "validated_successes": total_validated,
                "failures": int(totals["failures"] or 0),
                "refusals": int(totals["refusals"] or 0),
                "catalogued_tools": len(catalog),
                "used_tools": len(tools),
                "unused_tools": len(unused),
                "standard_candidates": sum(item["classification"] == "candidate" for item in tools),
            },
            "tools": tools,
            "unused_preview": unused[:20],
            "policy": {
                "pareto_target": 0.8,
                "candidate_minimum_calls": 10,
                "candidate_minimum_validated_rate": 0.9,
                "candidate_minimum_workflows": 3,
                "candidate_minimum_objective_completions": 3,
                "review_minimum_calls": 5,
                "review_failure_rate": 0.2,
                "promotion": "candidate status nominates a tool; human review promotes it",
            },
            "privacy": (
                "Stores tool name, bounded context labels, outcome, verification, "
                "timing, and counts. "
                "It has no prompt, response, model path, secret, or argument-value columns."
            ),
        }
