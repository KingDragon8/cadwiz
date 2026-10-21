# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Coordinator that publishes immutable snapshots from injected adapters."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from threading import Lock, RLock
from typing import Protocol, TypeAlias

from ai_freecad_core.contracts import ModelSnapshot

from .active_document import ActiveDocumentAdapter
from .observers import ChangeListener, ModelChangeEvent, ObserverAdapter
from .selection import SelectionAdapter

SnapshotListener: TypeAlias = Callable[[ModelSnapshot], None]
"""Function notified after a new snapshot has been published."""

Clock: TypeAlias = Callable[[], datetime]
"""Injectable clock used to make snapshot capture deterministic in tests."""


class RefreshScheduler(Protocol):
    """Host adapter that schedules a coalesced refresh on the proper thread."""

    def schedule(self, callback: Callable[[], None]) -> None: ...


class ModelStateErrorCode(str, Enum):
    """Machine-readable model-state service failure categories."""

    CAPTURE_FAILED = "capture_failed"
    SUBSCRIBER_FAILED = "subscriber_failed"
    DISPOSED = "disposed"


@dataclass(frozen=True, slots=True)
class ModelStateError:
    """Structured service error retained for diagnostics and translation."""

    code: ModelStateErrorCode
    message: str
    listener_id: int | None = None
    exception_type: str | None = None


class ImmediateRefreshScheduler:
    """Synchronous scheduler for tests and hosts without thread affinity."""

    def schedule(self, callback: Callable[[], None]) -> None:
        callback()


class Subscription:
    """Idempotent cancellation handle for one snapshot listener."""

    def __init__(self, cancel_callback: Callable[[], None]) -> None:
        """Store the service-owned callback used to remove the listener."""
        self._cancel_callback = cancel_callback
        self._cancelled = False
        self._lock = RLock()

    def cancel(self) -> None:
        """Remove the listener once; subsequent calls have no effect."""
        with self._lock:
            if self._cancelled:
                return
            self._cancelled = True
        self._cancel_callback()


class LiveModelStateService:
    """Build, cache, revision, and publish model snapshots.

    Native API access is delegated to adapters. The service contains no FreeCAD
    imports and can therefore run in unit tests or alternative CAD hosts.
    Observer events are treated only as invalidation signals; each event causes
    both adapters to be read again so consumers receive a consistent snapshot.
    """

    def __init__(
        self,
        active_document: ActiveDocumentAdapter,
        selection: SelectionAdapter,
        observers: ObserverAdapter | None = None,
        clock: Clock | None = None,
        scheduler: RefreshScheduler | None = None,
    ) -> None:
        """Create a service with all native behavior supplied as dependencies."""
        self._active_document = active_document
        self._selection = selection
        self._observers = observers
        self._clock = clock or (lambda: datetime.now(UTC))
        self._scheduler = scheduler or ImmediateRefreshScheduler()
        self._lock = RLock()
        self._refresh_lock = Lock()
        self._listeners: dict[int, SnapshotListener] = {}
        self._next_listener_id = 0
        self._running = False
        self._disposed = False
        self._refresh_scheduled = False
        self._errors: list[ModelStateError] = []
        self._snapshot = ModelSnapshot(revision=0, captured_at=self._clock())

    def get_snapshot(self) -> ModelSnapshot:
        """Return the latest published immutable snapshot."""
        with self._lock:
            return self._snapshot

    def refresh(self) -> ModelSnapshot:
        """Capture adapter state, increment revision, and notify listeners."""
        with self._refresh_lock:
            with self._lock:
                if self._disposed:
                    error = ModelStateError(
                        ModelStateErrorCode.DISPOSED, "Model-state service is disposed"
                    )
                    self._errors.append(error)
                    raise RuntimeError(error.message)
            try:
                active = self._active_document.capture()
                selected = self._selection.capture(active.document)
                with self._lock:
                    snapshot = ModelSnapshot(
                        revision=self._snapshot.revision + 1,
                        captured_at=self._clock(),
                        document=active.document,
                        selection=selected,
                        active_body=active.active_body,
                        recompute=active.recompute,
                    )
                    self._snapshot = snapshot
                    listeners = tuple(self._listeners.items())
            except Exception as exc:
                with self._lock:
                    self._errors.append(
                        ModelStateError(
                            ModelStateErrorCode.CAPTURE_FAILED,
                            str(exc),
                            exception_type=type(exc).__name__,
                        )
                    )
                raise
        for listener_id, listener in listeners:
            try:
                listener(snapshot)
            except Exception as exc:
                with self._lock:
                    self._errors.append(
                        ModelStateError(
                            ModelStateErrorCode.SUBSCRIBER_FAILED,
                            str(exc),
                            listener_id,
                            type(exc).__name__,
                        )
                    )
        return snapshot

    def request_refresh(self) -> None:
        """Coalesce invalidations until the injected scheduler runs one refresh."""
        with self._lock:
            if self._disposed or not self._running or self._refresh_scheduled:
                return
            self._refresh_scheduled = True
        self._scheduler.schedule(self._run_scheduled_refresh)

    def subscribe(self, listener: SnapshotListener) -> Subscription:
        """Register for future publications without immediately invoking listener."""
        with self._lock:
            if self._disposed:
                raise RuntimeError("Model-state service is disposed")
            listener_id = self._next_listener_id
            self._next_listener_id += 1
            self._listeners[listener_id] = listener
        return Subscription(lambda: self._remove_listener(listener_id))

    def start(self) -> ModelSnapshot:
        """Publish initial state and start the optional observer adapter once."""
        with self._lock:
            if self._running:
                return self._snapshot
            self._running = True
        try:
            snapshot = self.refresh()
            if self._observers is not None:
                listener: ChangeListener = self._on_model_change  # type: ignore[assignment]
                self._observers.start(listener)
            return snapshot
        except Exception:
            with self._lock:
                self._running = False
            raise

    def stop(self) -> None:
        """Stop observer delivery; calling stop repeatedly is safe."""
        with self._lock:
            if not self._running:
                return
            self._running = False
            self._refresh_scheduled = False
        if self._observers is not None:
            self._observers.stop()

    def dispose(self) -> None:
        """Stop native delivery and permanently release all subscribers."""
        self.stop()
        with self._lock:
            self._disposed = True
            self._listeners.clear()

    @property
    def errors(self) -> tuple[ModelStateError, ...]:
        """Return structured errors in deterministic occurrence order."""
        with self._lock:
            return tuple(self._errors)

    def is_stale(self, snapshot: ModelSnapshot) -> bool:
        """Check a retained snapshot against the current service revision."""
        with self._lock:
            return snapshot.is_stale_against(self._snapshot.revision)

    @property
    def is_running(self) -> bool:
        """Report whether the service observer lifecycle is active."""
        with self._lock:
            return self._running

    def _on_model_change(self, _event: ModelChangeEvent) -> None:
        """Refresh state when an observer adapter reports invalidation."""
        with self._lock:
            running = self._running
        if running:
            self.request_refresh()

    def _run_scheduled_refresh(self) -> None:
        """Clear coalescing state and execute one serialized refresh."""
        with self._lock:
            if self._disposed or not self._running:
                self._refresh_scheduled = False
                return
            self._refresh_scheduled = False
        self.refresh()

    def _remove_listener(self, listener_id: int) -> None:
        """Remove a listener by its internal registration identifier."""
        with self._lock:
            self._listeners.pop(listener_id, None)
