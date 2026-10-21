# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""ORDER-2026-09-30-01 Fix 1 ("PROTECT THE USER'S WORK") -- the parts that
need no FreeCAD/bridge access at all: cancellation and where a recovery
copy lives on disk. The FreeCAD-touching operations themselves (saving a
copy, opening/committing/aborting the outer build transaction, restoring
a crashed session) are real `ToolInvoker` methods
(`begin_protected_build`/`commit_protected_build`/`abort_protected_build`/
`find_crash_recovery`/`restore_crash_recovery` in `invoker.py`), following
the SAME private-async-helper + public-sync-wrapper pattern its existing
`object_bounds`/`preview_box_cut`/`discard_failed_boolean` methods already
use -- deliberately NOT registered as MCP tools the model's own catalogue
could offer: opening/committing/aborting the build's own safety
transaction is `ToolCommandService`'s job, never a choice the model makes.

See that module's docstring for the three mechanisms this implements:
cancellation, one-step Undo, and crash recovery.
"""
from __future__ import annotations

import contextvars
import os
import threading
from pathlib import Path


class BuildCancelled(RuntimeError):
    """Raised when Stop was pressed before or during a model call. The
    caller must discard whatever the in-flight call returns and unwind
    back to the build-transaction abort path -- never apply a late reply
    to the document."""


#: Set at the top of `run_request` when a caller passes a cancellation
#: token; read by `_ask_model_within_deadline`. `None` (the default, no
#: token given) means cancellation was never wired for this call -- the
#: same "absent means off, unchanged" contract `_active_request_deadline`
#: already uses for the same reason (many call sites, one place to check).
_active_cancellation: contextvars.ContextVar[threading.Event | None] = contextvars.ContextVar(
    "_active_cancellation", default=None
)


def check_cancelled() -> None:
    """Raise `BuildCancelled` if the active token (if any) is set."""
    token = _active_cancellation.get()
    if token is not None and token.is_set():
        raise BuildCancelled("stopped -- no further model calls or document changes")


def _recovery_root() -> Path:
    configured = os.environ.get("CADWIZ_RECOVERY_DIR")
    root = Path(configured) if configured else Path.home() / ".cadwiz" / "recovery"
    root.mkdir(parents=True, exist_ok=True)
    return root


def recovery_copy_path(document_name: str) -> Path:
    """Where this document's recovery copy would live. One per document
    name -- a second build on the same document overwrites the first
    build's own now-stale recovery copy, which is correct: only the most
    recent in-flight build is worth recovering."""
    safe_name = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in document_name)
    return _recovery_root() / f"{safe_name}.recovery.FCStd"


def find_recovery_copy(document_name: str) -> Path | None:
    """Called when the panel opens: a leftover recovery copy for this
    document name means the last build never finished cleanly (most
    likely a crash -- a normal Stop or completion always discards its own
    copy)."""
    path = recovery_copy_path(document_name)
    return path if path.exists() else None


def discard_recovery_copy(document_name: str) -> None:
    """A build finished (committed) or was cleanly stopped (aborted) --
    the recovery copy's job is done."""
    recovery_copy_path(document_name).unlink(missing_ok=True)
