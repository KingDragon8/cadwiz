# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""The one place the product asks a language model anything.

`ask_model` is the seam. Every call into a provider goes through it, and no
module outside `integrations/llm/` may name a provider, hold an API key, or
know an API style. That is the entire contract, and it exists so the multi-AI
swap later on changes one adapter instead of the codebase.

The types here are deliberately small. A provider that needs more than
`ModelRequest` carries can put it in `options`; a provider that cannot honour
something in there ignores it. Anything richer would leak provider shape into
the domain, which is the thing this module is for preventing.

Nothing here imports a vendor package, a network library, or FreeCAD -
`scripts/check_domain_imports.py` enforces that for the whole of
`ai_freecad_core`, and this module is the reason that rule matters.

Typical use::

    from ai_freecad_core.ai import ModelRequest, ask_model

    reply = ask_model(ModelRequest("Make the lip 18 mm tall"))

Wiring happens once, at startup, from the integrations side::

    from integrations.llm import build_default_provider
    set_model_provider(build_default_provider())
"""

from __future__ import annotations

import concurrent.futures
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

# Founder-found bug, 2026-09-27 (ORDER-2026-09-27-04): a "make me a simple
# bracket" request froze the founder's real, live FreeCAD for ~14 minutes
# (Windows AppHangB1) and had to be force-closed. Root cause: every build
# request runs `ask_model` inline on FreeCAD's Qt GUI thread (it has to --
# live documents and views are GUI-thread-only), and the vendored provider
# client (`vendor/freecad-ai/freecad_ai/llm/client.py`, never edited in
# place) retries up to 6 times at a 120s socket timeout each -- up to ~12
# minutes blocked in a single call, with nothing pumping Qt's event loop.
# This is the one seam every model call goes through, so a hard wall-clock
# ceiling here protects every caller at once, present and future, without
# touching the vendored retry logic.
DEFAULT_TIMEOUT_SECONDS = 45.0


class ModelUnavailable(RuntimeError):
    """No provider is wired, or the wired provider could not answer.

    Raised rather than returning an empty reply: a silent empty answer from a
    model is indistinguishable from a model that said nothing on purpose, and
    the caller cannot tell those apart.

    `kind` and `plain` (ORDER-2026-10-11-01 Part 1c): a provider layer that can
    tell WHY sets `kind` to one of "no_credit", "bad_key", "no_network",
    "rate_limited", "provider_down", "blocked_automated" or "unknown", and
    `plain` to the one sentence a 3D-printer owner should read, saying what
    to do. `str(error)` keeps the technical text for logs and scripts. A UI
    shows `plain` when it is set and never the technical text.
    """

    kind: str = "unknown"
    plain: str = ""


@dataclass(frozen=True, slots=True)
class ToolRequest:
    """A tool the model may call, described the way the model expects."""

    name: str
    description: str
    schema: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ToolInvocation:
    """A tool the model asked for. Nothing here executes it."""

    call_id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ModelRequest:
    """One question for a model.

    ``history`` is a plain list of ``{"role": ..., "content": ...}`` mappings,
    oldest first, excluding ``prompt`` itself. Keeping it primitive means the
    conversation store (M2-AI) and the providers never have to agree on a
    class, only on a shape.
    """

    prompt: str
    system: str = ""
    history: tuple[dict[str, Any], ...] = ()
    tools: tuple[ToolRequest, ...] = ()
    options: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.prompt.strip() and not self.history:
            raise ValueError("a model request needs a prompt or some history")

    def messages(self) -> list[dict[str, Any]]:
        """History plus the prompt, in the order providers expect."""
        conversation = [dict(turn) for turn in self.history]
        if self.prompt.strip():
            conversation.append({"role": "user", "content": self.prompt})
        return conversation


@dataclass(frozen=True, slots=True)
class ModelReply:
    """What came back. ``provider`` and ``model`` are recorded for the audit
    trail: knowing which model produced a change matters as much as the change.
    """

    text: str = ""
    tool_calls: tuple[ToolInvocation, ...] = ()
    provider: str = ""
    model: str = ""
    stop_reason: str = ""

    @property
    def wants_tools(self) -> bool:
        return bool(self.tool_calls)


@runtime_checkable
class ModelPort(Protocol):
    """What a provider adapter has to offer. One method, on purpose."""

    def complete(self, request: ModelRequest) -> ModelReply: ...


_provider: ModelPort | None = None


def set_model_provider(provider: ModelPort | None) -> None:
    """Install the provider `ask_model` will use. Called once, at startup."""
    global _provider
    if provider is not None and not isinstance(provider, ModelPort):
        raise TypeError("a model provider must implement complete(ModelRequest)")
    _provider = provider


#: Called repeatedly (about every 50 ms) while `ask_model` waits on a slow
#: provider. A host with a GUI thread installs one so the window keeps
#: repainting and answering Cancel during the wait (ORDER-2026-10-06-01);
#: it may raise to abandon the wait (the worker thread is simply left to
#: finish on its own). `None` means a plain blocking wait, as before.
_wait_pump: Callable[[], None] | None = None


def set_wait_pump(pump: Callable[[], None] | None) -> None:
    global _wait_pump
    _wait_pump = pump


def current_model_provider() -> ModelPort | None:
    """Whatever is wired, or None. Useful for reporting what is configured."""
    return _provider


def ask_model(
    request: ModelRequest,
    provider: ModelPort | None = None,
    timeout: float | None = None,
) -> ModelReply:
    """Ask the wired model. The only route from the product to a provider.

    ``provider`` overrides the installed one for a single call, which is what
    tests use so they never touch the global.

    ``timeout`` bounds how long this call may block, in seconds (default
    ``DEFAULT_TIMEOUT_SECONDS``). The call runs on a worker thread so a slow
    or hung provider cannot block the caller past that ceiling -- the caller
    gets ``ModelUnavailable`` back and stays responsive, which matters most
    when the caller is a GUI thread with no other way to stay alive.
    """
    active = provider or _provider
    if active is None:
        raise ModelUnavailable(
            "No model provider is configured. Wire one at startup with "
            "set_model_provider(build_default_provider())."
        )
    effective_timeout = DEFAULT_TIMEOUT_SECONDS if timeout is None else timeout
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = pool.submit(active.complete, request)
    try:
        pump = _wait_pump
        if pump is not None:
            # Waited here, outside the translation below: whatever the host's
            # pump raises (a Cancel) must reach the caller as itself, not be
            # dressed up as a model failure.
            give_up_at = time.monotonic() + effective_timeout
            while not future.done() and time.monotonic() < give_up_at:
                pump()
                concurrent.futures.wait([future], timeout=0.05)
        try:
            return future.result(timeout=effective_timeout if pump is None else 0.0)
        except concurrent.futures.TimeoutError as error:
            raise ModelUnavailable(
                f"The model did not respond within {effective_timeout:.0f} seconds."
            ) from error
        except ModelUnavailable:
            raise
        except Exception as error:  # noqa: BLE001 - provider failures are data here
            raise ModelUnavailable(f"The model provider failed: {error}") from error
    finally:
        # wait=False: a genuinely hung call must not make this call block
        # again on its own way out. The worker thread finishes or dies on
        # its own; it is never touched again once we give up on it.
        pool.shutdown(wait=False)
