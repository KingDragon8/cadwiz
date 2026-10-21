# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""The product's route to the 152 FreeCAD tools, with verification built in.

The M0 audit found 152 working tools in `vendor/robust-mcp` that nothing in
the product could reach. This is the connection. Tools are registered onto a
real `FastMCP` instance and invoked through its own `call_tool`, so what runs
is the vendored tool function, not a reimplementation of it.

Verification is part of `invoke`, not a helper beside it. A mutating tool that
returns without a render is not a success this class can express - the render
happens before the result is handed back, and a failed render turns a success
into a failure. That is the difference between having a render primitive and
enforcing one, which is what the audit found missing.

Read-only tools skip verification: rendering after `list_documents` costs a
screenshot and proves nothing.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any
from uuid import uuid4

from ai_freecad_core.result_verifier import VERIFIER_VERSION
from ai_freecad_core.tool_analytics import (
    ToolCallContext,
    ToolCallLedger,
    ToolCallTimer,
    default_tool_ledger_path,
)
from integrations.provenance import build_tool_provenance

from .bridge import build_in_process_bridge, ensure_vendor_importable
from .macro_guard import is_guarded, refusal_message, review_tool_call
from .datum_pro import register_datum_pro_tools
from .document_undo_fix import register_document_undo_fix
from .fillet_pro import register_fillet_pro_tools
from .groove_axis_fix import register_groove_axis_fix
from .live_result import register_live_result_tools
from .sketch_constraint_pro import register_sketch_constraint_pro_tools
from .draft_text_pro import register_draft_text_pro_tools
from .spreadsheet_pro import register_spreadsheet_pro_tools
from .print_prep import register_print_prep_tools
from .layer3_tools import register_layer3_tools
from .m2b_tools import register_m2b_tools
from .native_tools import (
    ExportVerification,
    is_verifiable_export,
    register_native_tools,
    verify_export_tool_call,
)
from .progress import timed as _build_timer
from .verification import RenderVerification, verify_after_mutation

# Prefixes that only read. Everything else is treated as mutating, because the
# cost of an unnecessary render is a screenshot and the cost of a missed one is
# a silent broken model.
READ_ONLY_PREFIXES = (
    "get_",
    "list_",
    "describe_",
    "validate_",
    "check_",
    "export_",
    "measure_",
    "inspect_",
    "read_",
    "fit_",
    "zoom_",
    "toggle_",
)

# Read-only despite their prefix.
#: design_source_search (M-BETA-SUPPORT, 2026-09-15): a network search
#: against design_sources adapters, never touches a FreeCAD document.
#: design_source_import is deliberately NOT here -- it creates a real
#: Mesh::Feature object and must go through render-after-op like any
#: other mutating tool.
#: draft_list_fonts (TOOL FACTORY, 2026-09-26): searches font directories
#: on disk and never touches a FreeCAD document at all -- with no entry
#: here it fell through to the mutating path on name alone (starts with
#: "draft_", not "list_"), owing a render-after-op verify gate it has no
#: document to satisfy.
READ_ONLY_EXACT = frozenset(
    {
        "recompute_document",
        "get_screenshot",
        "design_source_search",
        "select_edges",
        "draft_list_fonts",
    }
)


class ToolNotFound(KeyError):
    """The requested tool is not one of the registered tools."""


#: How FreeCAD says there is nowhere to put the thing being made. The vendored
#: tools raise a bare ValueError with this text from a dozen call sites, and
#: vendor is never edited in place, so it is recognised here instead.
_NO_DOCUMENT = "no document found"


class DocumentRequired(RuntimeError):
    """The tool needed an open document and there was none.

    Separate from `ToolExecutionFailed` because it is not a failure -- nothing
    is broken and nothing needs fixing. It is a missing precondition with an
    obvious remedy, and the caller can offer that remedy instead of reporting
    an error. Collapsing it into the generic failure is what produced a
    traceback where a question belonged.
    """

    def __init__(self, tool: str) -> None:
        super().__init__(
            f"{tool} needs an open document and none is open."
        )
        self.tool = tool


class ToolExecutionFailed(RuntimeError):
    """The tool ran and reported failure, or its verification did."""


class ProhibitedOperation(ToolExecutionFailed):
    """A code-executing tool was refused before it ran.

    Subclasses `ToolExecutionFailed` so every existing handler keeps working
    unchanged, while new code can catch the refusal precisely. The distinction
    is worth having: nothing ran, so there is no partial mutation to clean up
    and nothing to retry differently - the answer is the same every time until
    the macro changes.
    """


@dataclass(frozen=True, slots=True)
class ToolResult:
    """What a tool did, and the evidence that it worked."""

    tool: str
    arguments: dict[str, Any]
    payload: Any = None
    mutating: bool = False
    verification: RenderVerification | None = None
    content: tuple[Any, ...] = field(default_factory=tuple)
    telemetry_id: str = ""
    workflow_id: str = ""
    #: Present only for an export tool whose output could be read back.
    export_verification: Any = None

    @property
    def verified(self) -> bool:
        """A mutation is only successful once a render has confirmed it.

        ORDER-2026-09-27-06 PHASE 3(b) / audit F3: this used to check only
        `verification.ok` (recompute + render succeeded) -- a document
        could recompute cleanly and render fine while a real, measured
        HARD assertion (an invalid shape, a missing solid, a genuine
        collision) had already failed, and this property would still say
        True. `result_verdict.mandatory_passed` is the actual "did every
        HARD check pass" answer (verification.py's `_build_result_verdict`,
        already scoped to exempt sketches/reference geometry from the
        solid-count check); `None` means measurement was never attempted
        at all (an earlier, cheaper check already failed first), which is
        not itself a failure to report here.
        """
        if not self.mutating:
            return True
        if self.verification is None or not self.verification.ok:
            return False
        verdict = self.verification.result_verdict
        return verdict is None or verdict.mandatory_passed


def is_mutating(tool_name: str) -> bool:
    """Whether a tool changes the document, and so owes us a render."""
    if tool_name in READ_ONLY_EXACT:
        return False
    return not tool_name.startswith(READ_ONLY_PREFIXES)


def _mutation_subjects(
    tool_name: str, arguments: dict[str, Any], payload: Any
) -> tuple[str, ...]:
    """Identify the object or assembly that must be visible after a mutation.

    Feeds `verify_after_mutation`'s viewport framing only, as of 2026-09-08 -
    provenance stamping now uses `_document_object_signatures`'s generic
    before/after diff instead of this argument-name allowlist, so a tool
    with an argument shape this function does not recognize still gets its
    output correctly framed on screen only where it happens to also match
    one of these names; the allowlist is not extended for framing's own
    sake, since an unframed screenshot still passes verification.
    """
    names: list[str] = []
    if isinstance(payload, dict):
        for key in ("name", "result_name", "object_name"):
            if payload.get(key):
                names.append(str(payload[key]))
    for key in (
        "object_name", "result_name", "target_name", "body_name",
        "object1_name", "object2_name",
    ):
        if arguments.get(key):
            names.append(str(arguments[key]))
    # Creation tools sometimes return an opaque payload in older vendored
    # adapters. In that case the viewport probe deliberately frames all solids.
    return tuple(dict.fromkeys(name for name in names if name))


def _vendored_tool_version() -> str:
    """`freecad_mcp`'s own version string, for the provenance record's `created_by`.

    Empty rather than raising when it cannot be determined - a missing
    version is `build_tool_provenance`'s problem to render as UNKNOWN, not a
    reason to fail a mutation that already succeeded.
    """
    ensure_vendor_importable()
    try:
        from freecad_mcp import __version__  # type: ignore[import-not-found]  # noqa: PLC0415
    except Exception:  # noqa: BLE001
        return ""
    return str(__version__)


async def _stamp_tool_provenance(
    bridge: Any, object_names: tuple[str, ...], values: dict[str, str]
) -> tuple[str, ...]:
    """Attach a provenance record to every named object that exists.

    Runs inside the FreeCAD process, the same way every other probe in this
    module reaches live objects: a code string through `bridge.execute_python`,
    not a direct `import FreeCAD` here - this file is imported by
    `tests/contract`, which runs with no FreeCAD installed at all.
    `integrations.provenance` has no FreeCAD import of its own, so it is
    exactly as importable inside that process as `FreeCAD` itself is.

    Returns the names actually stamped. Never raises: a provenance record
    that could not be attached is not a reason to fail a mutation that
    already passed verification, matching `attach_properties`'s own choice
    to do nothing for an object that cannot carry properties.
    """
    if not object_names:
        return ()
    probe = await bridge.execute_python(
        "from integrations.provenance import attach_tool_provenance\n"
        "_doc_ = FreeCAD.ActiveDocument\n"
        f"_result_ = list(attach_tool_provenance(_doc_, tuple({json.dumps(object_names)}), "
        f"{json.dumps(values)}))\n"
    )
    if not getattr(probe, "success", False):
        return ()
    result = getattr(probe, "result", None)
    return tuple(result) if isinstance(result, list) else ()


class ToolInvoker:
    """Registers the vendored tools once, then runs them on demand."""

    def __init__(
        self,
        bridge: Any | None = None,
        *,
        verify: bool = True,
        ledger: ToolCallLedger | None = None,
    ) -> None:
        self._bridge = bridge
        self._verify = verify
        self._mcp: Any | None = None
        self._ledger: ToolCallLedger | None
        # An injected bridge normally means a test or isolated integration.
        # Those callers opt into telemetry explicitly so test traffic cannot
        # pollute the product's operational ledger.
        if ledger is not None:
            self._ledger = ledger
        elif bridge is None:
            try:
                self._ledger = ToolCallLedger(default_tool_ledger_path())
            except (OSError, sqlite3.Error):
                self._ledger = None
        else:
            self._ledger = None

    @property
    def ledger(self) -> ToolCallLedger | None:
        """The local metadata ledger, when operational telemetry is enabled."""
        return self._ledger

    # ---- registration -------------------------------------------------
    def _bridge_now(self) -> Any:
        if self._bridge is None:
            self._bridge = build_in_process_bridge()
        return self._bridge

    def _bridge_ready(self) -> Any:
        """`_bridge_now()`, connected. The helpers called from the sync
        wrappers (active document, protected build, undo count) run outside a
        tool call, so nothing had connected the bridge yet on the FIRST build
        of a session -- they failed with "bridge not connected", the build
        silently skipped its recovery copy and undo protection, and a Cancel
        had nothing to roll back (found 2026-10-06, ORDER-2026-10-06-01)."""
        bridge = self._bridge_now()
        if hasattr(bridge, "connect") and getattr(bridge, "_connected", True) is False:
            try:
                asyncio.run(bridge.connect())
            except Exception:  # noqa: BLE001 - no FreeCAD here (headless tests): behave as before
                pass
        return bridge

    def _server(self) -> Any:
        if self._mcp is not None:
            return self._mcp
        ensure_vendor_importable()
        from freecad_mcp.tools import register_all_tools  # type: ignore[import-not-found]
        from mcp.server.fastmcp import FastMCP  # noqa: PLC0415

        server = FastMCP("cadwiz-tools")

        async def get_bridge() -> Any:
            bridge = self._bridge_now()
            if not getattr(bridge, "_connected", False):
                await bridge.connect()
            return bridge

        register_all_tools(server, get_bridge)
        register_native_tools(server, get_bridge)
        register_layer3_tools(server, get_bridge)
        register_m2b_tools(server, get_bridge)
        register_fillet_pro_tools(server, get_bridge)
        register_datum_pro_tools(server, get_bridge)
        register_document_undo_fix(server, get_bridge)
        register_groove_axis_fix(server, get_bridge)
        register_live_result_tools(server, get_bridge)
        register_spreadsheet_pro_tools(server, get_bridge)
        register_sketch_constraint_pro_tools(server, get_bridge)
        register_draft_text_pro_tools(server, get_bridge)
        register_print_prep_tools(server, get_bridge)
        # M-BETA-SUPPORT, 2026-09-15: CADWiz's own tools, not vendored --
        # registered onto the same FastMCP instance so they reach the
        # model and execute through the exact same invoke() path as every
        # vendored tool, never a second invocation system.
        try:
            from .design_source_tools import register_design_source_tools  # noqa: PLC0415
        except ImportError:   # the open-source build (the Claude plug-in) has no model-library search here
            register_design_source_tools = None
        if register_design_source_tools is not None:
            register_design_source_tools(server, get_bridge)
        if self._ledger is not None:
            names = tuple(tool.name for tool in server._tool_manager.list_tools())  # noqa: SLF001
            self._safely_register_tools(names)
        self._mcp = server
        return server

    def tool_names(self) -> tuple[str, ...]:
        tools = asyncio.run(self._server().list_tools())
        return tuple(sorted(tool.name for tool in tools))

    # ---- invocation ---------------------------------------------------
    async def invoke_async(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        *,
        context: ToolCallContext | None = None,
    ) -> ToolResult:
        timer = ToolCallTimer.start()
        server = self._server()
        arguments = dict(arguments or {})
        # create_macro_from_template's vendored signature uses `name`, but its
        # own siblings in the same tool family (run_macro, read_macro,
        # delete_macro) all use `macro_name` -- a real model call reliably
        # cross-contaminates the argument name from those siblings and fails
        # pydantic validation before the vendored tool ever runs (TOOL FACTORY
        # session, 2026-09-27, runtime_create_macro_from_template_voice_path.py,
        # 3/3 retries). The vendored function itself is pinned (never edited in
        # place), so the alias is normalized here, at the one seam every call
        # passes through, rather than by hoping the model gets the name right.
        if name == "create_macro_from_template" and "macro_name" in arguments and "name" not in arguments:
            arguments["name"] = arguments.pop("macro_name")
        context = context or ToolCallContext()
        if not context.workflow_id:
            context = replace(context, workflow_id=f"workflow-{uuid4().hex}")

        known = {tool.name for tool in await server.list_tools()}
        if name not in known:
            self._record_telemetry(
                name=name,
                context=context,
                outcome="refused",
                mutating=False,
                verified=False,
                verification="not_run",
                timer=timer,
                argument_count=len(arguments),
            )
            raise ToolNotFound(f"No such tool: {name!r}")

        # Prohibited-operations review, before anything runs. Placed here, in
        # the one method every tool call passes through, rather than in the
        # callers - a guard with a way around it is decoration. Founder
        # decision 4, 2026-09-05; see macro_guard.py.
        if is_guarded(name):
            review = await review_tool_call(
                name,
                arguments,
                fetch_macro_source=lambda macro: self._macro_source(server, macro),
            )
            if not review.allowed:
                self._record_telemetry(
                    name=name,
                    context=context,
                    # Refused, not failed: the tool never ran. Recording it as
                    # a failure would put a fault in the ledger against a tool
                    # that works, the same reasoning the missing-document
                    # branch below already uses.
                    outcome="refused",
                    mutating=False,
                    verified=False,
                    verification="not_run",
                    timer=timer,
                    argument_count=len(arguments),
                )
                raise ProhibitedOperation(refusal_message(name, review))

        mutating = is_mutating(name)
        if mutating:
            # ORDER-2026-10-06-01: Cancel is honoured before every build
            # step, and the user is told in plain words what is happening.
            from . import progress as _build_progress
            from .build_safety import check_cancelled as _check_cancelled

            _check_cancelled()
            _build_progress.report(
                "Running the build step" if name == "execute_python" else f"Building: {name.replace('_', ' ')}"
            )
        objects_before = await _document_object_signatures(self._bridge_now()) if mutating else {}
        boolean_base_volume: float | None = None
        boolean_before: dict[str, float] = {}
        if name == "boolean_operation" and str(arguments.get("operation", "")).casefold() in {
            "cut", "difference", "subtract", "subtraction"
        }:
            boolean_base_volume = await _shape_volume(
                self._bridge_now(), str(arguments.get("object1_name", ""))
            )
            boolean_before = await _shape_inventory(self._bridge_now())
        try:
            from .offload import OFFLOAD_TOOLS, offloading

            if name in OFFLOAD_TOOLS:
                with _build_timer(f"tool: {name} (total)"), offloading():
                    raw = await server.call_tool(name, arguments)
            else:
                with _build_timer(f"tool: {name}"):
                    raw = await server.call_tool(name, arguments)
        except Exception as error:  # noqa: BLE001 - reported, not swallowed
            missing_document = _NO_DOCUMENT in str(error).casefold()
            self._record_telemetry(
                name=name,
                context=context,
                # A missing document is refused, not failed. Recording it as a
                # failure would put a fault in the ledger against a tool that
                # works, and the analytics would eventually recommend removing
                # a tool whose only problem was being asked too early.
                outcome="refused" if missing_document else "failure",
                mutating=mutating,
                verified=False,
                verification="not_run",
                timer=timer,
                argument_count=len(arguments),
            )
            if missing_document:
                raise DocumentRequired(name) from error
            raise ToolExecutionFailed(f"{name} raised: {error}") from error

        content, payload = _split_result(raw)

        if boolean_base_volume is not None:
            boolean_after = await _shape_inventory(self._bridge_now())
            result_name = ""
            if isinstance(payload, dict):
                result_name = str(payload.get("name") or payload.get("result_name") or "")
            result_name = result_name or str(arguments.get("result_name", ""))
            if not result_name:
                created = [item for item in boolean_after if item not in boolean_before]
                result_name = created[-1] if created else ""
            if result_name:
                if isinstance(payload, dict):
                    payload = {**payload, "name": result_name}
                else:
                    payload = {"name": result_name, "result": payload}
            result_volume = await _shape_volume(self._bridge_now(), result_name)
            if (
                result_volume is not None
                and abs(boolean_base_volume - result_volume)
                <= max(1e-7, boolean_base_volume * 1e-9)
            ):
                raise ToolExecutionFailed(
                    f"{name} produced no material change; the cutter did not intersect the base"
                )
            await _apply_boolean_presentation_policy(
                self._bridge_now(),
                str(arguments.get("object1_name", "")),
                str(arguments.get("object2_name", "")),
                result_name,
            )

        # Export-and-verify. Part 21 makes export a verified step: the written
        # mesh is read back and held to its HARD predicates before the tool is
        # allowed to report success. Placed here rather than inside a tool so
        # that every export tool gets it, including the vendored ones this
        # repository does not edit.
        export_verification: ExportVerification | None = None
        if self._verify and is_verifiable_export(name):
            export_verification = await verify_export_tool_call(
                self._bridge_now(), name, arguments
            )
            if export_verification.checked and not export_verification.ok:
                self._record_telemetry(
                    name=name,
                    context=context,
                    outcome="verification_failed",
                    mutating=mutating,
                    verified=False,
                    verification="failed",
                    timer=timer,
                    argument_count=len(arguments),
                )
                raise ToolExecutionFailed(
                    f"{name} wrote a file that failed export verification: "
                    f"{export_verification.failure_summary()}"
                )

        # `active_subjects` scopes both the viewport framing below and, more
        # consequentially, `measure_objects`'s own collision/clearance probe
        # inside `verify_after_mutation`: an EMPTY active_subjects makes that
        # probe fall back to checking every shape-bearing object in the
        # document against every other one (`_measure_probe`'s own
        # `not _names_ or ...` condition) -- an O(n^2) all-pairs
        # `Shape.common()`/`distToShape()` BREP computation. Fine, even
        # unnoticeable, on the handful of objects every fixture in this
        # program used before PRINT-PREP (2026-09-08) -- confirmed
        # catastrophic (multi-minute, not sub-second) on
        # `CADW-S3-PIVOT3-PHONE-PLANE-20260830T234002Z`, a real 117-object
        # production assembly with ~90 shape-bearing objects (~4000 pairs).
        # PRINT-PREP's own tools (`part_names`, not `object_name`/
        # `result_name`/...) never matched `_mutation_subjects`'s allowlist,
        # so every one of their calls hit this fallback. Fixed the same way
        # provenance was: the same generic before/after diff already
        # computed for stamping, computed here instead so it is ready
        # before `verify_after_mutation` needs it, and reused for stamping
        # below rather than snapshotted a second time.
        objects_after_call = await _document_object_signatures(self._bridge_now()) if mutating else {}
        diffed_subjects = _changed_or_new_objects(objects_before, objects_after_call) if mutating else ()
        subjects = diffed_subjects or (_mutation_subjects(name, arguments, payload) if mutating else ())
        verification: RenderVerification | None = None
        if mutating and self._verify:
            with _build_timer(f"verify after {name}"):
                verification = await verify_after_mutation(
                    self._bridge_now(), name,
                    active_subjects=subjects,
                    operation_id=f"{context.workflow_id}:{name}",
                )
            if not verification.ok:
                self._record_telemetry(
                    name=name,
                    context=context,
                    outcome="verification_failed",
                    mutating=True,
                    verified=False,
                    verification="failed",
                    timer=timer,
                    argument_count=len(arguments),
                )
                raise ToolExecutionFailed(
                    f"{name} ran but could not be verified: {verification.reason}"
                )
        if mutating:
            # Cancel is honoured AFTER the step too (ORDER-2026-10-11-02, found by
            # the real GP-018 gate: probe_cancel). Only the pumped waits inside
            # verification (the headless measurement) can raise on Cancel; a
            # Cancel pressed while the un-pumped stages ran (recompute, the
            # screenshot) was lost, and the step reported success -- seen on
            # 2026-10-06 (first gate run) and 2026-10-11 whenever the measurement
            # was quick and the rest of verification slow. Checked here so the
            # caller's abort-and-undo path takes the step back.
            _check_cancelled()

        # Provenance is stamped only once a mutation is known-good: reaching
        # here means either verification passed or verification was never
        # asked to run at all (self._verify off, a test/isolated caller's own
        # choice) - never a rolled-back or failed mutation. Nothing is
        # stamped by hand elsewhere; this is the one place a tool-created
        # object gets its record, per the founder's 2026-09-07 Phase 1
        # closeout ruling.
        #
        # Which objects get stamped is answered generically (2026-09-08),
        # not from an argument-name allowlist: whatever this call created or
        # changed, from the SAME before/after diff `active_subjects` above
        # already computed (`diffed_subjects`) - not re-snapshotted a second
        # time. Recompute does not change which objects exist or how their
        # own Shape differs from before the call for an already-consistent
        # mutation, so the pre-verification diff is the settled one too. No
        # per-tool registration, ever again.
        changed_or_new = diffed_subjects if mutating else ()
        if mutating and changed_or_new:
            provenance_values = build_tool_provenance(
                tool_name=name,
                tool_version=_vendored_tool_version(),
                session_id=context.workflow_id,
                intent_id=context.intent_id,
                user_request=context.user_request,
                parameters=arguments,
                verification=verification,
                verifier_version=VERIFIER_VERSION,
            )
            await _stamp_tool_provenance(self._bridge_now(), changed_or_new, provenance_values)

        verified = not mutating or (verification is not None and verification.ok)
        if not mutating:
            verification_outcome = "not_required"
        elif verification is None:
            verification_outcome = "not_run"
        elif verification.render_skipped:
            verification_outcome = "headless_skipped"
        else:
            verification_outcome = "rendered"
        telemetry_id = self._record_telemetry(
            name=name,
            context=context,
            outcome="success",
            mutating=mutating,
            verified=verified,
            verification=verification_outcome,
            timer=timer,
            argument_count=len(arguments),
        )

        return ToolResult(
            tool=name,
            arguments=arguments,
            payload=payload,
            mutating=mutating,
            verification=verification,
            content=content,
            telemetry_id=telemetry_id,
            workflow_id=context.workflow_id,
            export_verification=export_verification,
        )

    @staticmethod
    async def _macro_source(server: Any, macro_name: str) -> str | None:
        """Fetch what `run_macro` is about to run, so it can be reviewed.

        Goes through the vendored `read_macro` tool rather than reading the
        filesystem here: the macro directory is FreeCAD's to locate, and it
        already knows how (user directory first, then the resource directory).

        Returns None when the source cannot be found. The caller treats that as
        a refusal, never as permission - `review_tool_call` is explicit that an
        unreadable macro is an unreviewed macro. This call is deliberately not
        routed back through `invoke_async`: `read_macro` is read-only, and
        recursing would put the gate in front of its own evidence.
        """
        _content, payload = _split_result(await server.call_tool("read_macro", {
            "macro_name": macro_name,
        }))
        if isinstance(payload, dict):
            code = payload.get("code")
            if isinstance(code, str):
                return code
        return None

    def invoke(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        *,
        context: ToolCallContext | None = None,
    ) -> ToolResult:
        """Run one tool. Blocking, because the workbench calls it from the GUI."""
        return asyncio.run(self.invoke_async(name, arguments, context=context))

    def object_bounds(self, object_name: str) -> dict[str, Any]:
        """Read authoritative bounds and center for one real FreeCAD object."""
        return asyncio.run(_object_bounds(self._bridge_ready(), object_name))

    def cylindrical_axes(self, object_name: str) -> tuple[dict[str, Any], ...]:
        """Read cylindrical surface axes from the authoritative result shape."""
        return asyncio.run(_cylindrical_axes(self._bridge_ready(), object_name))

    def preview_box_cut(
        self,
        object_name: str,
        *,
        size: tuple[float, float, float],
        position: tuple[float, float, float],
    ) -> dict[str, Any]:
        """Evaluate a provisional box cut without changing the document."""
        return asyncio.run(
            _preview_box_cut(self._bridge_now(), object_name, size, position)
        )

    def discard_failed_boolean(
        self,
        target_name: str,
        *object_names: str,
    ) -> None:
        """Remove only failed provisional objects and restore the trusted target."""
        asyncio.run(
            _discard_failed_boolean(self._bridge_now(), target_name, object_names)
        )

    # ---- ORDER-2026-09-30-01 Fix 1 ("PROTECT THE USER'S WORK") ------------
    # Deliberately plain ToolInvoker methods, not MCP tools -- opening,
    # committing, and aborting the build's own outer safety transaction is
    # ToolCommandService's job, never something the model's own tool
    # catalogue offers it a choice about. See build_safety.py's module
    # docstring for the three mechanisms these implement together with it.

    def count_through_holes(self, document_name: str) -> int:
        """ORDER-2026-09-30-03 Fix 2 correction: a real, if narrowly scoped,
        geometric measurement -- counts DISTINCT cylindrical faces (by
        center/axis/radius signature) across every solid in the document.
        A plain plate with N drilled through-holes has exactly N such
        faces, which is the founder's own named test case ("a plate has 3
        of 4 holes"). Disclosed limit: a filleted/rounded edge is ALSO a
        cylindrical face, so this over-counts on a part with rounds --
        correct for a simple plate-with-holes, not a general hole
        detector. Real measurement, not a tool-call-name guess (a script
        drilling all N holes in one `execute_python` call would be
        invisible to any tool-call-count heuristic; this reads the actual
        resulting geometry instead)."""
        return asyncio.run(_count_through_holes(self._bridge_ready(), document_name))

    def undo_count(self, document_name: str) -> int:
        """The document's current `UndoCount` -- a real, measured finding
        (ORDER-2026-09-30-01 Fix 1): FreeCAD's transaction API has no true
        nesting. `Document.commitTransaction()` closes WHATEVER transaction
        is currently open, unconditionally -- there is no depth counter, so
        the FIRST tool call inside a build to commit its own transaction
        (every vendored tool does this) closes CADWiz's own outer one too,
        the moment it runs, not when the whole build finishes. Confirmed
        live: a real two-tool-call build produced two separate UndoCount
        increments even with an outer transaction wrapping the whole call.
        `begin_protected_build`'s outer transaction therefore only
        guarantees ONE undo step for a build whose entire effect happens
        before the first tool call commits (the single-tool-call case) --
        for anything more, `undo_last_build` below (repeating native
        `undo()` the right number of times) is what actually delivers
        "revert the whole build in one action" from the PANEL's point of
        view, even though it is several native FreeCAD undo steps
        underneath.
        """
        return asyncio.run(_undo_count(self._bridge_ready(), document_name))

    def undo_last_build(self, document_name: str, steps: int) -> None:
        """Reverts exactly `steps` native undo transactions -- the count
        `run_request`'s wrapper recorded as this build's own real
        `UndoCount` delta. One call from the panel's "Undo my last build"
        action (or a spoken "undo that"), not one native Ctrl+Z per step."""
        if steps <= 0:
            return
        asyncio.run(_undo_last_build(self._bridge_ready(), document_name, steps))

    def active_document_name(self) -> str | None:
        """The active document's name, or None -- a direct bridge probe,
        NOT `invoke()`/`run_tool`, so it never appears in a test's or the
        audit trail's own call log the way an actual `get_active_document`
        tool call would. `run_request`'s own safety wrapper (Fix 1) uses
        this to decide whether a document already exists worth protecting,
        without it looking like the model itself asked a question."""
        return asyncio.run(_active_document_name(self._bridge_ready()))

    def begin_protected_build(self, document_name: str, label: str = "CADWiz build") -> Path:
        """Saves a real recovery copy to disk, then opens one outer
        transaction for the whole build -- every individual tool call's own
        transaction (vendor/robust-mcp, vendor/freecad-ai) nests inside it,
        so committing this one at the end makes the whole build a single
        Undo step instead of one step per tool call."""
        from .build_safety import recovery_copy_path

        path = recovery_copy_path(document_name)
        asyncio.run(_begin_protected_build(self._bridge_ready(), document_name, label, path))
        return path

    def commit_protected_build(self, document_name: str) -> None:
        """A clean finish: commit the outer transaction (one Undo step for
        the whole build) and discard the now-unneeded recovery copy."""
        from .build_safety import discard_recovery_copy

        asyncio.run(_commit_protected_build(self._bridge_ready(), document_name))
        discard_recovery_copy(document_name)

    def abort_protected_build(self, document_name: str, *, discard_recovery: bool) -> None:
        """Reverts every change made since `begin_protected_build` opened
        the transaction, in memory, immediately -- a Stop or any handled
        failure discards the recovery copy too (`discard_recovery=True`,
        the build ended cleanly); an unhandled exception leaves it on disk
        (`discard_recovery=False`), the closest a controlled path gets to
        a real crash's own behaviour, so crash recovery can still find it.
        """
        asyncio.run(_abort_protected_build(self._bridge_ready(), document_name))
        if discard_recovery:
            from .build_safety import discard_recovery_copy

            discard_recovery_copy(document_name)

    def restore_crash_recovery(self, document_name: str, recovery_path: Path) -> dict[str, Any]:
        """Replaces the live document's content with the recovery copy's,
        by closing the live document (if open) and opening the recovery
        file in its place."""
        return asyncio.run(
            _restore_crash_recovery(self._bridge_now(), document_name, recovery_path)
        )

    def _safely_register_tools(self, names: tuple[str, ...]) -> None:
        """Telemetry must never make a CAD operation unavailable."""
        try:
            if self._ledger is not None:
                self._ledger.register_tools(names)
        except (OSError, ValueError, sqlite3.Error):
            pass

    def mark_objective(self, workflow_id: str, outcome: str) -> None:
        """Attach a workflow result without allowing analytics to break CAD."""
        try:
            if self._ledger is not None:
                self._ledger.mark_objective(workflow_id, outcome)
        except (OSError, ValueError, sqlite3.Error):
            pass

    def _record_telemetry(
        self,
        *,
        name: str,
        context: ToolCallContext,
        outcome: str,
        mutating: bool,
        verified: bool,
        verification: str,
        timer: ToolCallTimer,
        argument_count: int,
    ) -> str:
        """Record bounded metadata without risking the primary operation."""
        try:
            if self._ledger is not None:
                return self._ledger.record(
                    tool_name=name,
                    context=context,
                    outcome=outcome,
                    mutating=mutating,
                    verified=verified,
                    verification=verification,
                    duration_ms=timer.milliseconds(),
                    argument_count=argument_count,
                )
        except (OSError, ValueError, sqlite3.Error):
            pass
        return ""


async def _shape_volume(bridge: Any, object_name: str) -> float | None:
    """Read one real object's volume for Boolean-effect verification."""
    if not object_name:
        return None
    probe = await bridge.execute_python(
        "_doc_ = FreeCAD.ActiveDocument\n"
        f"_obj_ = _doc_.getObject({object_name!r}) if _doc_ else None\n"
        "_shape_ = getattr(_obj_, 'Shape', None) if _obj_ else None\n"
        "_result_ = float(_shape_.Volume) if _shape_ is not None and not _shape_.isNull() else None"
    )
    if not getattr(probe, "success", False) or getattr(probe, "result", None) is None:
        return None
    try:
        return float(probe.result)
    except (TypeError, ValueError):
        return None


async def _shape_inventory(bridge: Any) -> dict[str, float]:
    """Return real shape-bearing objects in document order."""
    probe = await bridge.execute_python(
        "_doc_ = FreeCAD.ActiveDocument\n"
        "_result_ = {}\n"
        "if _doc_:\n"
        "    for _obj_ in _doc_.Objects:\n"
        "        _shape_ = getattr(_obj_, 'Shape', None)\n"
        "        if _shape_ is not None and not _shape_.isNull():\n"
        "            _result_[_obj_.Name] = float(_shape_.Volume)"
    )
    result = getattr(probe, "result", None)
    if not getattr(probe, "success", False) or not isinstance(result, dict):
        return {}
    return {str(name): float(volume) for name, volume in result.items()}


async def _document_object_signatures(bridge: Any) -> dict[str, str]:
    """A generic content fingerprint for every real object in the active
    document, keyed by name.

    Replaces `_mutation_subjects`'s argument-name allowlist for provenance
    purposes (2026-09-08): that allowlist had to be extended by hand for
    every tool with a new argument-name shape, and every tool added without
    remembering to extend it landed BLOCKED on provenance_survival forever,
    regardless of whether it created or touched a real object. Comparing
    this snapshot before and after a call needs no knowledge of the tool's
    own arguments at all.

    The signature is `Volume + Area + BoundBox extents + Placement`, not
    `Shape.hashCode()` - hashCode was the first attempt (2026-09-08) and is
    NOT a content hash: confirmed against a real 117-object production
    assembly (`CADW-S3-PIVOT3-PHONE-PLANE-20260830T234002Z`) that it
    changes on every recompute for `App::Link`, datum axes/planes, and an
    `Assembly::AssemblyObject`'s own compound, even when nothing about
    them actually changed - it reflects the freshly-rebuilt TShape's own
    identity, not its geometry. That made roughly half the document read
    as "changed" on every mutating call, which fed straight into
    `verify_after_mutation`'s own collision probe and turned a sub-second
    check into a multi-minute one (PRINT-PREP, T1, 2026-09-08 - see
    `print_prep.py`'s own module docstring). Volume/Area/BoundBox are
    stable across a mere recompute; Placement (position + rotation, read
    once for every object type, not just Shape-bearing ones) changes
    exactly when the object's own position or orientation does, and
    together they change exactly when the object's real geometry does - a
    new position, a new size, a new topology - so an object edited in
    place by a `sketch_name`-keyed call (PROVE-016's own gap) still gets a
    new signature, the same as a newly created object. A `Mesh::Feature`
    has no `Shape` at all (confirmed 2026-09-07); its own facet count,
    point count, and bounding box stand in instead, which is exactly what
    changes when `repair_mesh` or `scale_mesh` edits the same Mesh object
    in place. An object with neither `Shape` nor `Mesh` falls back to
    TypeId + Placement, which still catches its creation and any move,
    just not an in-place edit with no geometry and no Placement change at
    all - no object encountered in this program's own qualification work
    is in that last category.
    """
    probe = await bridge.execute_python(
        # CADWIZ_PROVENANCE_SNAPSHOT: a unique marker so a fake bridge in a
        # test can recognize this specific probe and answer it distinctly
        # from every other execute_python call this module makes (recompute
        # status, viewport checks, _shape_inventory's own Objects walk).
        "# CADWIZ_PROVENANCE_SNAPSHOT\n"
        "_doc_ = FreeCAD.ActiveDocument\n"
        "_result_ = {}\n"
        "if _doc_:\n"
        "    for _obj_ in _doc_.Objects:\n"
        "        _shape_ = getattr(_obj_, 'Shape', None)\n"
        "        _mesh_ = getattr(_obj_, 'Mesh', None)\n"
        "        _placement_ = getattr(_obj_, 'Placement', None)\n"
        "        _pos_ = ''\n"
        "        if _placement_ is not None:\n"
        "            _p_ = _placement_.Base\n"
        "            _ax_ = _placement_.Rotation.Axis\n"
        "            _pos_ = (\n"
        "                f'{round(_p_.x, 6)},{round(_p_.y, 6)},{round(_p_.z, 6)}:'\n"
        "                f'{round(_placement_.Rotation.Angle, 9)}@'\n"
        "                f'{round(_ax_.x, 6)},{round(_ax_.y, 6)},{round(_ax_.z, 6)}'\n"
        "            )\n"
        "        if _shape_ is not None:\n"
        # `Shape.hashCode()` is NOT a content hash -- confirmed 2026-09-08
        # against a real 117-object production assembly
        # (CADW-S3-PIVOT3-PHONE-PLANE-20260830T234002Z): it changed on
        # every single recompute for App::Link, App::Line/Plane/Origin
        # datums, and the Assembly's own compound, even though nothing
        # about them had changed -- it reflects the freshly-rebuilt
        # TShape's own identity, not its geometric content. Using it made
        # `_changed_or_new_objects` report ~50 untouched objects as
        # "changed" on every mutating call, which fed `verify_after_
        # mutation`'s active_subjects and blew up its own collision probe
        # into an all-pairs scan (`_measure_probe`'s empty-active_subjects
        # fallback) -- multi-minute, not sub-second. Volume/Area/BoundBox
        # are stable across a mere recompute (confirmed on the same four
        # objects, byte-identical before and after); combined with the
        # object's own Placement (position + rotation, read once above,
        # generic to every DocumentObject) this changes exactly when the
        # object's real position, size, or shape does, and not otherwise.
        "            try:\n"
        "                _sig_ = (\n"
        "                    f'{_obj_.TypeId}:{round(_shape_.Volume, 6)}:{round(_shape_.Area, 6)}:'\n"
        "                    f'{round(_shape_.BoundBox.XLength, 6)},{round(_shape_.BoundBox.YLength, 6)},'\n"
        "                    f'{round(_shape_.BoundBox.ZLength, 6)}:{_pos_}'\n"
        "                )\n"
        "            except Exception:\n"
        "                _sig_ = _obj_.TypeId\n"
        "        elif _mesh_ is not None:\n"
        # `Mesh::Feature` has no `Shape`/`Volume`/`Area` of its own -- its
        # own facet count, point count, and bounding box are the stand-in,
        # same reasoning as above: what `repair_mesh`/`scale_mesh` actually
        # change in place.
        "            try:\n"
        "                _bb_ = _mesh_.BoundBox\n"
        "                _sig_ = (\n"
        "                    f'{_obj_.TypeId}:{_mesh_.CountFacets}:{_mesh_.CountPoints}:'\n"
        "                    f'{round(_bb_.XLength, 6)}:{round(_bb_.YLength, 6)}:{round(_bb_.ZLength, 6)}:{_pos_}'\n"
        "                )\n"
        "            except Exception:\n"
        "                _sig_ = _obj_.TypeId\n"
        "        else:\n"
        "            _sig_ = f'{_obj_.TypeId}:{_pos_}'\n"
        "        _result_[_obj_.Name] = _sig_"
    )
    result = getattr(probe, "result", None)
    if not getattr(probe, "success", False) or not isinstance(result, dict):
        return {}
    return {str(name): str(sig) for name, sig in result.items()}


def _changed_or_new_objects(before: dict[str, str], after: dict[str, str]) -> tuple[str, ...]:
    """Every object present after a call that either did not exist before
    or now carries a different content signature - document order, since
    `after` was built by iterating `doc.Objects` in that order."""
    return tuple(name for name, signature in after.items() if before.get(name) != signature)


async def _object_bounds(bridge: Any, object_name: str) -> dict[str, Any]:
    probe = await bridge.execute_python(
        "_doc_ = FreeCAD.ActiveDocument\n"
        f"_obj_ = _doc_.getObject({object_name!r}) if _doc_ else None\n"
        "_shape_ = getattr(_obj_, 'Shape', None) if _obj_ else None\n"
        "if _shape_ is None or _shape_.isNull():\n"
        "    _result_ = None\n"
        "else:\n"
        "    _box_ = _shape_.BoundBox\n"
        "    _center_ = _box_.Center\n"
        "    _center_source_ = 'bounding_box'\n"
        "    for _face_ in _shape_.Faces:\n"
        "        _surface_ = _face_.Surface\n"
        "        if type(_surface_).__name__ == 'Sphere':\n"
        "            _center_ = _surface_.Center\n"
        "            _center_source_ = 'spherical_surface'\n"
        "            break\n"
        "    _face_types_ = {}\n"
        "    for _face_ in _shape_.Faces:\n"
        "        _kind_ = type(_face_.Surface).__name__\n"
        "        _face_types_[_kind_] = _face_types_.get(_kind_, 0) + 1\n"
        "    _result_ = {\n"
        "        'center': [_center_.x, _center_.y, _center_.z],\n"
        "        'center_source': _center_source_,\n"
        "        'size': [_box_.XLength, _box_.YLength, _box_.ZLength],\n"
        "        'valid': bool(_shape_.isValid()),\n"
        "        'solid_count': len(_shape_.Solids),\n"
        "        'volume_mm3': float(_shape_.Volume) if _shape_.Solids else 0.0,\n"
        "        'face_types': _face_types_,\n"
        "    }"
    )
    result = getattr(probe, "result", None)
    if not getattr(probe, "success", False) or not isinstance(result, dict):
        raise ToolExecutionFailed(f"could not inspect authoritative target {object_name!r}")
    return result


async def _cylindrical_axes(bridge: Any, object_name: str) -> tuple[dict[str, Any], ...]:
    probe = await bridge.execute_python(
        "_doc_ = FreeCAD.ActiveDocument\n"
        f"_obj_ = _doc_.getObject({object_name!r}) if _doc_ else None\n"
        "_shape_ = getattr(_obj_, 'Shape', None) if _obj_ else None\n"
        "_axes_ = []\n"
        "if _shape_ is not None and not _shape_.isNull():\n"
        "    for _face_ in _shape_.Faces:\n"
        "        _surface_ = _face_.Surface\n"
        "        if type(_surface_).__name__ == 'Cylinder':\n"
        "            _axis_ = _surface_.Axis\n"
        "            _center_ = _surface_.Center\n"
        "            _axes_.append({\n"
        "                'radius': float(_surface_.Radius),\n"
        "                'axis': [_axis_.x, _axis_.y, _axis_.z],\n"
        "                'point': [_center_.x, _center_.y, _center_.z],\n"
        "            })\n"
        "_result_ = _axes_"
    )
    result = getattr(probe, "result", None)
    if not getattr(probe, "success", False) or not isinstance(result, list):
        raise ToolExecutionFailed(f"could not inspect cylindrical axes on {object_name!r}")
    return tuple(item for item in result if isinstance(item, dict))


async def _preview_box_cut(
    bridge: Any,
    object_name: str,
    size: tuple[float, float, float],
    position: tuple[float, float, float],
) -> dict[str, Any]:
    """Return survival evidence for a cut performed on transient OCC shapes."""
    probe = await bridge.execute_python(
        "import Part\n"
        "_doc_ = FreeCAD.ActiveDocument\n"
        f"_obj_ = _doc_.getObject({object_name!r}) if _doc_ else None\n"
        "_base_ = getattr(_obj_, 'Shape', None) if _obj_ else None\n"
        f"_size_ = {tuple(float(value) for value in size)!r}\n"
        f"_position_ = {tuple(float(value) for value in position)!r}\n"
        "if _base_ is None or _base_.isNull():\n"
        "    _result_ = None\n"
        "else:\n"
        "    _tool_ = Part.makeBox(_size_[0], _size_[1], _size_[2], "
        "FreeCAD.Vector(*_position_))\n"
        "    _candidate_ = _base_.cut(_tool_)\n"
        "    _base_volume_ = float(_base_.Volume)\n"
        "    _candidate_volume_ = float(_candidate_.Volume)\n"
        "    _spherical_radii_ = sorted({round(float(_face_.Surface.Radius), 6) "
        "for _face_ in _candidate_.Faces if type(_face_.Surface).__name__ == 'Sphere'})\n"
        "    _result_ = {\n"
        "        'base_volume': _base_volume_,\n"
        "        'result_volume': _candidate_volume_,\n"
        "        'removed_volume': _base_volume_ - _candidate_volume_,\n"
        "        'retained_ratio': (_candidate_volume_ / _base_volume_) "
        "if _base_volume_ > 0 else 0.0,\n"
        "        'valid': bool(_candidate_.isValid()),\n"
        "        'solid_count': len(_candidate_.Solids),\n"
        "        'spherical_radii': _spherical_radii_,\n"
        "    }"
    )
    result = getattr(probe, "result", None)
    if not getattr(probe, "success", False) or not isinstance(result, dict):
        raise ToolExecutionFailed(
            f"could not preview inspection cut on {object_name!r}"
        )
    return result


async def _discard_failed_boolean(
    bridge: Any,
    target_name: str,
    object_names: tuple[str, ...],
) -> None:
    """Rollback objects from one failed candidate without touching user geometry."""
    probe = await bridge.execute_python(
        "_doc_ = FreeCAD.ActiveDocument\n"
        f"_target_ = _doc_.getObject({target_name!r}) if _doc_ else None\n"
        f"_discard_ = {tuple(str(name) for name in object_names if name)!r}\n"
        "if _doc_:\n"
        "    for _name_ in _discard_:\n"
        "        if _doc_.getObject(_name_) is not None:\n"
        "            _doc_.removeObject(_name_)\n"
        "    _doc_.recompute()\n"
        # Visibility only exists where there is a GUI. Headless, ViewObject is
        # None, and an unguarded attribute set raised AttributeError inside the
        # probe - which surfaced as "could not be rolled back", blaming the
        # rollback for a missing view. Found 2026-09-06 while qualifying
        # capability 1 against real headless FreeCAD 1.1.3.
        "if _target_ is not None and getattr(_target_, 'ViewObject', None) is not None:\n"
        "    _target_.ViewObject.Visibility = True\n"
        "_result_ = bool(_target_ is not None)"
    )
    if not getattr(probe, "success", False) or not getattr(probe, "result", False):
        raise ToolExecutionFailed("failed Boolean candidate could not be rolled back")


# ---- ORDER-2026-09-30-01 Fix 1 ("PROTECT THE USER'S WORK") ----------------


async def _count_through_holes(bridge: Any, document_name: str) -> int:
    probe = await bridge.execute_python(
        _resolve_named_document(document_name)
        + "_count_ = 0\n"
        "if _doc_ is not None:\n"
        "    _seen_ = set()\n"
        "    for _obj_ in _doc_.Objects:\n"
        "        _shape_ = getattr(_obj_, 'Shape', None)\n"
        "        if _shape_ is None or _shape_.isNull():\n"
        "            continue\n"
        "        for _face_ in _shape_.Faces:\n"
        "            if type(_face_.Surface).__name__ != 'Cylinder':\n"
        "                continue\n"
        "            _axis_ = _face_.Surface.Axis\n"
        "            _center_ = _face_.Surface.Center\n"
        "            _key_ = (\n"
        "                round(_center_.x, 2), round(_center_.y, 2), round(_center_.z, 2),\n"
        "                round(_axis_.x, 2), round(_axis_.y, 2), round(_axis_.z, 2),\n"
        "                round(float(_face_.Surface.Radius), 3),\n"
        "            )\n"
        "            if _key_ not in _seen_:\n"
        "                _seen_.add(_key_)\n"
        "                _count_ += 1\n"
        "_result_ = _count_"
    )
    if not getattr(probe, "success", False):
        return 0
    return int(getattr(probe, "result", 0) or 0)


async def _undo_count(bridge: Any, document_name: str) -> int:
    probe = await bridge.execute_python(
        _resolve_named_document(document_name) + "_result_ = _doc_.UndoCount if _doc_ is not None else 0"
    )
    if not getattr(probe, "success", False):
        return 0
    return int(getattr(probe, "result", 0) or 0)


async def _undo_last_build(bridge: Any, document_name: str, steps: int) -> None:
    probe = await bridge.execute_python(
        _resolve_named_document(document_name)
        + "if _doc_ is not None:\n"
        f"    for _ in range({int(steps)}):\n"
        "        if _doc_.UndoCount <= 0:\n"
        "            break\n"
        "        _doc_.undo()\n"
        "    _doc_.recompute()\n"
        "_result_ = True"
    )
    if not getattr(probe, "success", False):
        raise ToolExecutionFailed("could not undo the last build")


async def _active_document_name(bridge: Any) -> str | None:
    probe = await bridge.execute_python(
        "_doc_ = FreeCAD.ActiveDocument\n_result_ = _doc_.Name if _doc_ is not None else None"
    )
    if not getattr(probe, "success", False):
        return None
    result = getattr(probe, "result", None)
    return str(result) if result else None


def _resolve_named_document(document_name: str) -> str:
    """One line of generated code, reused by every helper below: the
    named document if it exists, else `FreeCAD.ActiveDocument` as a
    fallback for a caller that only ever has one document open (matching
    every other probe in this file's own `_doc_ = FreeCAD.ActiveDocument`
    convention) -- never silently operating on the WRONG document if one
    happens to be named."""
    return (
        f"_doc_ = FreeCAD.getDocument({document_name!r}) "
        f"if {document_name!r} in FreeCAD.listDocuments() else FreeCAD.ActiveDocument\n"
    )


async def _begin_protected_build(
    bridge: Any,
    document_name: str,
    label: str,
    recovery_path: Path,
) -> None:
    """Saves a real recovery copy to disk, then opens one outer transaction
    for the whole build."""
    probe = await bridge.execute_python(
        _resolve_named_document(document_name)
        + "if _doc_ is None:\n"
        f"    raise RuntimeError({'no document named ' + document_name + ' is open'!r})\n"
        f"_doc_.saveCopy({str(recovery_path)!r})\n"
        f"_doc_.openTransaction({label!r})\n"
        "_result_ = _doc_.Name"
    )
    if not getattr(probe, "success", False):
        raise ToolExecutionFailed(
            f"could not begin a protected build: {getattr(probe, 'error_traceback', '') or getattr(probe, 'stderr', '')}"
        )


async def _commit_protected_build(bridge: Any, document_name: str) -> None:
    probe = await bridge.execute_python(
        _resolve_named_document(document_name)
        + "if _doc_ is not None:\n"
        "    _doc_.commitTransaction()\n"
        "_result_ = _doc_ is not None"
    )
    if not getattr(probe, "success", False) or not getattr(probe, "result", False):
        raise ToolExecutionFailed("could not commit the protected build's transaction")


async def _abort_protected_build(bridge: Any, document_name: str) -> None:
    probe = await bridge.execute_python(
        _resolve_named_document(document_name)
        + "if _doc_ is not None:\n"
        "    _doc_.abortTransaction()\n"
        "    _doc_.recompute()\n"
        "_result_ = _doc_ is not None"
    )
    if not getattr(probe, "success", False) or not getattr(probe, "result", False):
        raise ToolExecutionFailed("could not abort the protected build's transaction")


async def _restore_crash_recovery(
    bridge: Any,
    document_name: str,
    recovery_path: Path,
) -> dict[str, Any]:
    probe = await bridge.execute_python(
        f"_name_ = {document_name!r}\n"
        f"_path_ = {str(recovery_path)!r}\n"
        "if _name_ in FreeCAD.listDocuments():\n"
        "    FreeCAD.closeDocument(_name_)\n"
        "_restored_ = FreeCAD.openDocument(_path_)\n"
        "_result_ = {\n"
        "    'name': _restored_.Name,\n"
        "    'label': _restored_.Label,\n"
        "    'objects': [_obj_.Name for _obj_ in _restored_.Objects],\n"
        "}"
    )
    if not getattr(probe, "success", False):
        raise ToolExecutionFailed(
            f"could not restore the recovery copy: {getattr(probe, 'error_traceback', '') or getattr(probe, 'stderr', '')}"
        )
    return dict(probe.result)


async def _apply_boolean_presentation_policy(
    bridge: Any,
    base_name: str,
    cutter_name: str,
    result_name: str,
) -> None:
    """Hide consumed Boolean inputs and expose only the authoritative result.

    Presentation is a GUI concern and there is no view to reconcile headless:
    `ViewObject` is None there, and the unguarded attribute sets below used to
    raise inside the probe, which surfaced as "boolean result presentation could
    not be reconciled" and failed the whole tool. **Every `boolean_operation`
    failed in a headless session** for a reason that had nothing to do with the
    geometry, which was built correctly and then thrown away.

    Found 2026-09-06 while qualifying capability 1 against real headless
    FreeCAD 1.1.3 — not by reading this code, which looks right until you know
    that `ViewObject` can be None. GUI behaviour is unchanged: where there is a
    view, the same three visibility rules apply.
    """
    if not result_name:
        return
    probe = await bridge.execute_python(
        "_doc_ = FreeCAD.ActiveDocument\n"
        f"_base_ = _doc_.getObject({base_name!r}) if _doc_ else None\n"
        f"_tool_ = _doc_.getObject({cutter_name!r}) if _doc_ else None\n"
        f"_result_obj_ = _doc_.getObject({result_name!r}) if _doc_ else None\n"
        "def _show_(_obj_, _visible_):\n"
        "    _view_ = getattr(_obj_, 'ViewObject', None) if _obj_ is not None else None\n"
        "    if _view_ is not None:\n"
        "        _view_.Visibility = _visible_\n"
        "_show_(_base_, False)\n"
        "_show_(_tool_, False)\n"
        "_show_(_result_obj_, True)\n"
        "_result_ = bool(_result_obj_ is not None)"
    )
    if not getattr(probe, "success", False) or not getattr(probe, "result", False):
        raise ToolExecutionFailed("boolean result presentation could not be reconciled")


def _split_result(raw: Any) -> tuple[tuple[Any, ...], Any]:
    """Normalise FastMCP's return shape across SDK versions.

    Older builds return a list of content blocks; newer ones return
    ``(content, structured)``. Both are handled so an SDK upgrade does not
    quietly change what a caller sees.
    """
    if isinstance(raw, tuple) and len(raw) == 2:
        content, structured = raw
        return tuple(content or ()), structured
    return tuple(raw or ()), None
