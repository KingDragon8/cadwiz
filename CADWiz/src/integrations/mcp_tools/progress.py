# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Plain-words progress and window-keep-alive hooks for long builds.

ORDER-2026-10-06-01 Part 1. A build can spend a long time inside a single
call that cannot yield by itself (a model reply, a geometry check). The panel
installs two hooks around a build so those calls can (a) say, in plain words,
what they are doing and (b) let the window repaint and hear Cancel:

- `report(text)`  -- show `text` as the current status line.
- `pump()`        -- service the window's event loop once; raises
                     `BuildCancelled` if Cancel / "stop" has been pressed.

With no hooks installed (tests, headless runs) both are cheap no-ops, so core
code can call them unconditionally.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from contextlib import contextmanager

_reporter: Callable[[str], None] | None = None
_pump: Callable[[], None] | None = None
_status: Callable[[str], None] | None = None


def set_gui_hooks(
    report: Callable[[str], None] | None,
    pump: Callable[[], None] | None,
    status: Callable[[str], None] | None = None,
) -> None:
    global _reporter, _pump, _status
    _reporter = report
    _pump = pump
    _status = status


def status(text: str) -> None:
    """Update the status line without starting a new stage (no pump)."""
    hook = _status
    if hook is not None:
        try:
            hook(text)
        except Exception:  # noqa: BLE001
            pass


def report(text: str) -> None:
    hook = _reporter
    if hook is not None:
        try:
            hook(text)
        except Exception:  # noqa: BLE001 - status text must never break a build
            pass
    pump()


def pump() -> None:
    hook = _pump
    if hook is not None:
        hook()


#: (stage label, seconds) for every timed stage of the current process, oldest
#: first. Read by the window-lock proof script to print the per-stage timing
#: table (ORDER-2026-10-06-01 Part 1f); never used to make a decision.
TIMINGS: list[tuple[str, float]] = []


@contextmanager
def timed(label: str):
    started = time.monotonic()
    try:
        yield
    finally:
        TIMINGS.append((label, time.monotonic() - started))
        del TIMINGS[:-500]


def run_pumped(fn: Callable[[], object], label: str = "") -> object:
    """Run a blocking call (a network search or download) on a helper thread
    while the window keeps answering and hears Cancel. With no hooks installed
    (tests, headless) it just calls `fn()`. The helper's exception, if any,
    is re-raised here; a Cancel abandons the wait (the helper finishes alone).
    """
    if _pump is None:
        return fn()
    import threading

    box: dict[str, object] = {}

    def work() -> None:
        try:
            box["value"] = fn()
        except BaseException as error:  # noqa: BLE001 - handed back to the caller below
            box["error"] = error

    if label:
        report(label)
    thread = threading.Thread(target=work, name="cadwiz-pumped-call", daemon=True)
    thread.start()
    started = time.monotonic()
    last_status = started
    while thread.is_alive():
        pump()
        thread.join(timeout=0.05)
        now = time.monotonic()
        if label and now - last_status >= 1.0:
            last_status = now
            status(f"{label} ({now - started:.0f}s)")
    if "error" in box:
        raise box["error"]  # type: ignore[misc]
    return box.get("value")
