# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""A bridge to the FreeCAD we are already running inside.

`vendor/robust-mcp` ships three bridges. Two of them (socket, xmlrpc) talk to
a FreeCAD in another process, and the third (embedded) imports FreeCAD into
its own. None of them is quite our case: the workbench *is* FreeCAD, so the
live `FreeCAD` and `FreeCADGui` modules are already imported and there is a
document open in front of the user.

`EmbeddedBridge` is nearly right - inside FreeCAD, its `import FreeCAD`
returns the live module and `FreeCAD.GuiUp` is True, so screenshots work,
which the headless case never gets. The one thing that is wrong is fatal:
every call is dispatched through a `ThreadPoolExecutor`, and FreeCAD's GUI is
not thread-safe. This repository already carries `GuiThreadViolation` because
that lesson was learned before.

So this subclasses the vendored bridge and swaps the executor for one that
runs inline on the calling thread. Behaviour is otherwise the vendored
behaviour, which is the point - the tools stay the tools.
"""

from __future__ import annotations

import collections
import re
import sys
from concurrent.futures import Executor, Future
from pathlib import Path
from typing import Any, Callable, TypeVar

_T = TypeVar("_T")

_VENDOR = Path(__file__).resolve().parents[3] / "vendor" / "robust-mcp" / "src"


def ensure_vendor_importable() -> None:
    """Put `vendor/robust-mcp/src` on the path. Integrations may; the core may not."""
    if _VENDOR.is_dir() and str(_VENDOR) not in sys.path:
        sys.path.insert(0, str(_VENDOR))


class SameThreadExecutor(Executor):
    """Runs work immediately, on whichever thread submitted it.

    `loop.run_in_executor` only needs something with `submit`, so this keeps
    every FreeCAD call on the thread that asked for it. Inside the workbench
    that is the GUI thread, which is the only thread allowed to touch a
    document or a 3D view.
    """

    def submit(self, fn: Callable[..., _T], /, *args: Any, **kwargs: Any) -> Future[_T]:
        future: Future[_T] = Future()
        if not future.set_running_or_notify_cancel():
            return future
        try:
            future.set_result(fn(*args, **kwargs))
        except BaseException as error:  # noqa: BLE001 - hand it to the caller
            future.set_exception(error)
        return future

    def shutdown(self, wait: bool = True, *, cancel_futures: bool = False) -> None:
        return None


# `EmbeddedBridge.get_console_output` (vendor/robust-mcp) is a stub that
# unconditionally returns `[]` -- its own docstring says so: "In embedded
# mode, we don't have direct access to FreeCAD's console history". That
# makes `get_console_log` (the MCP tool built on it) always report zero
# messages/warnings/errors regardless of what has actually happened in this
# session, the same class of defect PROVE-SWEEP batch 12 already found and
# fixed here for `get_workbenches`/`activate_workbench` (fabricated/no-op
# data reported as if real).
#
# The first fix attempt here tried `FreeCAD.Console.addObserver` (the
# documented desktop-app scripting API). Measured on FreeCAD 1.1.3
# (`freecadcmd.exe`), that raises `AttributeError: module
# '__FreeCADConsole__' has no attribute 'addObserver'` -- this build's
# `Console` module exposes only `Print*`/`GetObservers`/`GetStatus`/
# `SetStatus`, no way to *register* a custom observer from Python. What is
# real and measured on this build: `PrintMessage`/`PrintLog` write to
# `sys.stdout`, and `PrintWarning`/`PrintError`/`PrintCritical` write to
# `sys.stderr`, each call producing exactly the text passed in (newline
# included, no extra framing). So the fix taps the stream both write to
# instead of a Console-level hook: a small tee wraps `sys.stdout`/
# `sys.stderr` at bridge-build time, passing every write through to the
# real stream unchanged while also splitting it into lines for the ring
# buffer. `get_console_log`'s own warning/error split already works off
# line text (`"warning" in line.lower()`), so which stream a line came from
# doesn't need to be tracked separately.
_CONSOLE_BUFFER_MAXLEN = 500
_console_buffer: "collections.deque[str]" = collections.deque(maxlen=_CONSOLE_BUFFER_MAXLEN)
_console_tees_installed = False


class _TeeStream:
    """Passes every write through to `wrapped` and buffers complete lines."""

    def __init__(self, wrapped: Any) -> None:
        self._wrapped = wrapped
        self._partial = ""

    def write(self, text: str) -> int:
        written = self._wrapped.write(text)
        self._partial += text
        while "\n" in self._partial:
            line, self._partial = self._partial.split("\n", 1)
            if line:
                _console_buffer.append(line)
        return written if written is not None else len(text)

    def flush(self) -> None:
        self._wrapped.flush()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._wrapped, name)


def _ensure_console_observer_installed() -> None:
    """Install the stdout/stderr tee at most once per process."""
    global _console_tees_installed
    if _console_tees_installed:
        return
    if not isinstance(sys.stdout, _TeeStream):
        sys.stdout = _TeeStream(sys.stdout)
    if not isinstance(sys.stderr, _TeeStream):
        sys.stderr = _TeeStream(sys.stderr)
    _console_tees_installed = True


# The vendored PartDesign tools set `Symmetric` on a Pad, a Revolution and a
# Groove. No PartDesign feature on FreeCAD 1.1.3 has that property -- the one
# that means "symmetric to the sketch plane" is called `Midplane`, and
# `Symmetric` is not an alias for it, it simply does not exist. Measured
# 2026-09-07 against FreeCAD 1.1.3: Pad, Pocket, Revolution and Groove all
# report Symmetric=False, Midplane=True from `hasattr`.
#
# The cost was total rather than cosmetic. `pad_sketch` raised
# `AttributeError: 'PartDesign.Feature' object has no attribute 'Symmetric'`
# on every call, so capability 4 (pads) and capability 5 (pockets, which needs
# a pad to cut into) scored 0/8, and capabilities 2 and 3 lost their downstream
# point -- four of the seven Phase 1 capabilities held up by one wrong word.
#
# vendor/ is never edited in place (CLAUDE.md), and this is upstream's tree,
# clean and tracking `spkane/freecad-addon-robust-mcp-server` main. So the
# correction lives here, at the same seam that already swaps the bridge's
# thread pool: the tools stay the tools, and only the code on its way to
# FreeCAD is adjusted.
_SYMMETRIC_ASSIGNMENT = re.compile(
    r"^(?P<indent>[ \t]*)(?P<target>[A-Za-z_][A-Za-z0-9_]*)\.Symmetric[ \t]*=[ \t]*"
    r"(?P<value>[^=].*?)[ \t]*$",
    re.MULTILINE,
)


# `spreadsheet_bind_property` is the only vendored tool that reaches
# `DocumentObject.setExpression`, and `setExpression` itself accepts any valid
# FreeCAD expression path, dotted sub-properties included -- `AttachmentOffset
# .Base.z` is ordinary, documented syntax for binding a Placement's Z offset.
# But the tool's own guard before that call is `if not hasattr(target, prop):`,
# and Python's `hasattr` does not walk dots: `hasattr(obj, "AttachmentOffset
# .Base.z")` is False for every object, including one where the path
# genuinely resolves. Confirmed empirically on FreeCAD 1.1.3, 2026-09-07:
# `datum.setExpression("AttachmentOffset.Base.z", "Sheet.PadTop")` succeeds
# and tracks correctly when called directly, but the tool's own validation
# refuses to reach it, reporting "Property not found" for a property that is
# there. Anything a real user or CADWiz asks to bind through a dotted path --
# not just this qualification's own datum-plane fix -- hits the same wall.
#
# The fix walks the path with real attribute resolution instead of asking
# Python's single-segment `hasattr` to answer a multi-segment question.
# A plain name (`"Length"`) resolves in one step and behaves exactly as
# before; nothing that worked stops working.
_BIND_PROPERTY_GUARD = "if not hasattr(target, prop):"
_BIND_PROPERTY_GUARD_FIX = (
    "_prop_ok_ = True\n"
    "_walked_ = target\n"
    "for _segment_ in prop.split('.'):\n"
    "    if not hasattr(_walked_, _segment_):\n"
    "        _prop_ok_ = False\n"
    "        break\n"
    "    _walked_ = getattr(_walked_, _segment_)\n"
    "if not _prop_ok_:"
)


# `spreadsheet_set_cell` and `spreadsheet_get_cell` both read a cell back with
# `sheet.get(cell)` and hand the result straight to the MCP result codec. For
# a bare number that is a `float` or `int` and serializes fine. For a formula
# that evaluates through a dimensioned property -- `=C5Pad.Length`, which is
# exactly what an expression-driven attachment offset (see
# `_BIND_PROPERTY_GUARD` above) needs to read back -- `sheet.get` returns a
# `Base.Quantity`, and the codec has no case for it: "Unable to serialize
# unknown type: <class 'Base.Quantity'>", failing the whole tool call even
# though `sheet.set` and the recompute it triggered had already succeeded.
# Confirmed empirically 2026-09-07, driving the real tool chain: a bare
# `=10` round-trips; `=C5Pad.Length` does not.
#
# `Base.Quantity` converts to `float` in its base unit (mm for a length),
# which is what CADWiz already treats as the unit throughout, so the
# conversion loses nothing a caller here was relying on. A cell that never
# was a Quantity is untouched -- `hasattr(computed, "Value")` is false for a
# plain number or string.
_SPREADSHEET_COMPUTED = re.compile(
    r"^(?P<indent>[ \t]*)computed = sheet\.get\(cell\)$", re.MULTILINE
)
_SPREADSHEET_COMPUTED_FIX = (
    "{indent}computed = sheet.get(cell)\n"
    "{indent}if hasattr(computed, 'Value') and hasattr(computed, 'Unit'):\n"
    "{indent}    computed = float(computed.Value)"
)


def apply_freecad_compatibility(code: str) -> str:
    """Rewrite generated FreeCAD macro code around known vendor-tool gaps.

    Three passes, all leaving working code untouched and each explained where
    it is defined:

    1. `pad.Symmetric = True` -> a property FreeCAD 1.1.3 does not have,
       rewritten to `Midplane` when `Symmetric` is absent. See
       `_SYMMETRIC_ASSIGNMENT` above.
    2. `spreadsheet_bind_property`'s single-segment property guard -> a
       dotted-path-aware walk. See `_BIND_PROPERTY_GUARD` above.
    3. `sheet.get(cell)` returning an unserializable `Base.Quantity` -> a
       plain float. See `_SPREADSHEET_COMPUTED` above.

    The Symmetric rewrite is written on one line so it does not shift line
    numbers; a generated macro reports its traceback against `<mcp>` line
    numbers, and moving them to fix an attribute name would trade one
    debugging problem for another. The other two are fixed, line-for-line
    block replacements of the tools' own code, so they shift lines only
    inside those vendored tools' generated code, never inside a
    caller-authored macro.
    """
    code = _SYMMETRIC_ASSIGNMENT.sub(
        lambda m: (
            f"{m['indent']}setattr({m['target']}, "
            f"'Symmetric' if hasattr({m['target']}, 'Symmetric') else 'Midplane', "
            f"{m['value']})"
        ),
        code,
    )
    code = code.replace(_BIND_PROPERTY_GUARD, _BIND_PROPERTY_GUARD_FIX)
    code = _SPREADSHEET_COMPUTED.sub(
        lambda m: _SPREADSHEET_COMPUTED_FIX.format(indent=m["indent"]), code
    )
    return code


def _json_safe(value: Any) -> Any:
    """Recursively convert FreeCAD-only types the JSON/MCP wire format
    cannot carry into plain, JSON-safe values.

    ORDER-2026-09-27-06 founder ruling 5: a generated macro's `_result_`
    can legitimately contain a `Base.Quantity` -- e.g. `_result_ =
    {"length": obj.Length}` -- confirmed live 2026-09-28: the vendored
    bridge (vendor/robust-mcp, pinned, never edited in place) passes it
    straight through in `ExecutionResult.result`, and the MCP tool-result
    layer crashes serializing it ("Unable to serialize unknown type:
    <class 'Base.Quantity'>"), failing the whole tool call.

    Duck-typed on module/class name rather than a hard `import Base`, so
    this module stays importable outside a FreeCAD process (as the rest
    of this file already assumes -- FreeCAD-specific imports only happen
    lazily inside functions like `build_in_process_bridge` below).
    """
    type_ = type(value)
    if type_.__module__ == "Base" and type_.__name__ == "Quantity":
        try:
            unit = value.getUserPreferred()[2]
        except Exception:  # noqa: BLE001 - a units API surprise is not this call's failure
            unit = ""
        return {"value": value.Value, "unit": unit}
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def build_in_process_bridge() -> Any:
    """The vendored embedded bridge, made safe to use inside the GUI."""
    ensure_vendor_importable()
    from freecad_mcp.bridge.embedded import EmbeddedBridge  # type: ignore[import-not-found]
    from freecad_mcp.bridge.base import ObjectInfo  # type: ignore[import-not-found]

    class InProcessBridge(EmbeddedBridge):  # type: ignore[misc, valid-type]
        """The vendored bridge, with vendor-version corrections applied in transit.

        Subclassed here rather than patched onto the instance so that the
        correction is visible in a traceback and cannot be silently lost if
        the vendored bridge grows another execution entry point.
        """

        async def execute_python(self, code: str, timeout_ms: int = 30000) -> Any:
            transformed = apply_freecad_compatibility(code)
            # ORDER-2026-10-06-01: heavy build steps run in a windowless helper
            # on a protected copy (see offload.py); `None` means "run it here".
            from .offload import offload_wanted, run_offloaded

            if offload_wanted():
                offloaded = await run_offloaded(self, transformed, timeout_ms)
                if offloaded is not None:
                    if getattr(offloaded, "result", None) is not None:
                        offloaded.result = _json_safe(offloaded.result)
                    return offloaded
            result = await super().execute_python(transformed, timeout_ms)
            if getattr(result, "result", None) is not None:
                result.result = _json_safe(result.result)
            return result

        async def get_console_output(self, lines: int = 100) -> Any:
            """Real recent console lines, not the vendored stub's `[]`.

            See `_BufferingConsoleObserver` above for the defect and fix.
            """
            if lines <= 0:
                return []
            return list(_console_buffer)[-lines:]

        async def get_workbenches(self) -> Any:
            """PROVE-SWEEP batch 12 defect fix: the vendored bridge's own
            headless branch returns a HARDCODED, FAKE list of 7 common
            workbench names (`is_active` always false) instead of reporting
            that this is not real, GUI-backed state -- confirmed 2026-09-11:
            the SAME fake list comes back regardless of what has actually
            been activated. Raising here instead is the honest answer,
            matching every other true GUI-only tool's own convention
            (`set_object_visibility` and siblings return a structured
            `{"success": False, "error": "GUI not available..."}` rather
            than fabricating plausible-looking data)."""
            if not await self.is_gui_available():
                raise ValueError("GUI not available - workbench list requires GUI mode")
            return await super().get_workbenches()

        async def activate_workbench(self, workbench_name: str) -> None:
            """PROVE-SWEEP batch 12 defect fix: the vendored bridge's own
            headless branch silently no-ops (`return` immediately) --
            confirmed 2026-09-11 -- yet the calling MCP tool still reports
            `{"success": True}` unconditionally, regardless of whether
            anything actually happened. Raising here instead surfaces the
            real limitation rather than lying about success."""
            if not await self.is_gui_available():
                raise ValueError("GUI not available - workbench activation requires GUI mode")
            return await super().activate_workbench(workbench_name)

        def _get_macro_path(self) -> Path:
            """PROVE-SWEEP final chunk (2026-09-12) defect fix: the vendored
            bridge guesses the macro directory from a hardcoded, unversioned
            path (`%APPDATA%/FreeCAD/Macro` on Windows) instead of asking
            FreeCAD's own `getUserMacroDir()` API -- confirmed directly on
            this machine, where the three disagree:
            `getUserMacroDir(True)` (what `read_macro`/`delete_macro`'s own
            inline `execute_python` code already correctly calls) returns a
            project-customised path, `getUserMacroDir(False)` returns
            FreeCAD 1.1's real versioned default
            (`...\\FreeCAD\\v1-1\\Macro\\`), and this method's own guess
            returns a THIRD, unversioned path that matches neither. Because
            `create_macro`/`run_macro`/`get_macros` (this class's vendored
            base) all route through this one method while `read_macro`/
            `delete_macro` call the real API directly, a macro created via
            `create_macro` was invisible to everything else -- `run_macro`'s
            own review-then-allow guard fetches source via `read_macro`
            before running anything, so every `create_macro` -> `run_macro`
            call failed with "Macro not found", not because of a review
            finding but because the guard was looking in the wrong place
            for a file that was really there. Delegating to the same real
            API `read_macro`/`delete_macro` already use makes all four
            agree.
            """
            import FreeCAD  # noqa: PLC0415

            return Path(FreeCAD.getUserMacroDir(True))

        async def get_object(
            self,
            obj_name: str,
            doc_name: str | None = None,
        ) -> Any:
            """PROVE-SWEEP final chunk (2026-09-12) defect fix: `inspect_object`
            crashed entirely -- not a partial/degraded result, a hard failure
            -- for any object with a `Base`/`Tool` property, which covers
            every `Part::Cut`/`Part::Fuse`/`Part::Common` (the standard
            boolean result types). Confirmed directly: `getattr(obj, "Base")`
            on a real `Part::Cut` returns a `PrimitivePy`-typed value, and the
            vendored code's own guard for "does this need stringifying"
            (`val.__class__.__module__ != 'builtins'`) is wrong for it --
            `PrimitivePy.__module__` reports as `'builtins'` even though the
            type plainly is not one, so the raw, non-serializable object
            passes through untouched and Pydantic's own `model_dump` raises
            `PydanticSerializationError: Unable to serialize unknown type:
            <class 'PrimitivePy'>` on the way out, taking the whole tool call
            down with it.

            The fix replaces the module-name heuristic with an explicit
            allowlist of the plain JSON-safe types (str/int/float/bool/
            NoneType/list/dict) -- anything else is stringified, the same
            outcome the vendored code already intended for e.g. `Placement`,
            just reached by asking "is this actually safe to hand back" (as
            the vendored code was for a `str`/`int`/`bool`), never trusting a
            binding class's own unreliable `__module__` claim.
            """
            result = await self.execute_python(
                f"""
doc = FreeCAD.ActiveDocument if {doc_name!r} is None else FreeCAD.getDocument({doc_name!r})
if doc is None:
    raise ValueError("No document found")

obj = doc.getObject({obj_name!r})
if obj is None:
    raise ValueError(f"Object not found: {obj_name!r}")

_JSON_SAFE_TYPES = (str, int, float, bool, type(None), list, dict)

props = {{}}
for prop in obj.PropertiesList:
    try:
        val = getattr(obj, prop)
        if not isinstance(val, _JSON_SAFE_TYPES):
            val = str(val)
        props[prop] = val
    except Exception:
        props[prop] = "<unreadable>"

shape_info = None
if hasattr(obj, "Shape"):
    shape = obj.Shape
    shape_info = {{
        "type": shape.ShapeType,
        "volume": shape.Volume if hasattr(shape, "Volume") else None,
        "area": shape.Area if hasattr(shape, "Area") else None,
        "is_valid": shape.isValid(),
    }}

_result_ = {{
    "name": obj.Name,
    "label": obj.Label,
    "type_id": obj.TypeId,
    "properties": props,
    "shape_info": shape_info,
    "children": [c.Name for c in obj.OutList] if hasattr(obj, "OutList") else [],
}}
"""
            )

            if result.success and result.result:
                from freecad_mcp.bridge.base import ObjectInfo  # type: ignore[import-not-found] # noqa: PLC0415

                return ObjectInfo(**result.result)

            error_msg = result.error_traceback or "Failed to get object"
            raise ValueError(error_msg)

        async def create_object(
            self,
            type_id: str,
            name: str | None = None,
            properties: dict[str, Any] | None = None,
            doc_name: str | None = None,
        ) -> Any:
            """PROVE-SWEEP batch 8 defect fix: the vendored `create_object`
            (the shared path behind `create_box`/`create_cylinder`/`create_
            sphere`/`create_cone`/`create_helix`/`create_line`/`create_plane`/
            `create_ellipse`/`create_prism`/`create_regular_polygon`/
            `create_partdesign_body`, and any other tool built on it) calls
            `doc.addObject(...)` with no `doc.openTransaction()`/
            `commitTransaction()` wrapping at all -- confirmed directly
            2026-09-11 against its own source. Nothing is ever pushed onto
            the document's own undo stack for these calls, so `undo`/`redo`
            silently no-op on them regardless of `Document.UndoMode` (this
            module's own `document_undo_fix.py` fix for the OTHER half of
            the same defect). Every other mutating tool in this program
            wraps its own generated code this way -- vendor's own CLAUDE.md
            documents it as mandatory ("Object creation: create_box, ...
            MUST use transaction wrapping"), so this corrects the shared
            path to match every other tool's own convention, not to add new
            behaviour.
            """
            properties = properties or {}
            code = f"""
doc = FreeCAD.ActiveDocument if {doc_name!r} is None else FreeCAD.getDocument({doc_name!r})
if doc is None:
    raise ValueError("No document found")

doc.openTransaction("Create Object")
try:
    obj = doc.addObject({type_id!r}, {name!r} or "")

    for prop_name, prop_val in {properties!r}.items():
        if hasattr(obj, prop_name):
            setattr(obj, prop_name, prop_val)

    doc.recompute()
    doc.commitTransaction()

    _result_ = {{
        "name": obj.Name,
        "label": obj.Label,
        "type_id": obj.TypeId,
        "visibility": True,
        "children": [c.Name for c in obj.OutList] if hasattr(obj, "OutList") else [],
        "parents": [p.Name for p in obj.InList] if hasattr(obj, "InList") else [],
    }}
except Exception:
    doc.abortTransaction()
    raise
"""
            result = await self.execute_python(code)
            if result.success and result.result:
                return ObjectInfo(**result.result)
            error_msg = result.error_traceback or "Failed to create object"
            raise ValueError(error_msg)

    _ensure_console_observer_installed()
    bridge = InProcessBridge()
    # Replace the worker pool before anything is dispatched through it.
    old = getattr(bridge, "_executor", None)
    bridge._executor = SameThreadExecutor()  # noqa: SLF001 - deliberate
    if old is not None:
        old.shutdown(wait=False)
    return bridge


def running_inside_freecad() -> bool:
    """Whether a live FreeCAD is already in this process."""
    return "FreeCAD" in sys.modules


def gui_is_up() -> bool:
    """Whether this FreeCAD has a GUI, which is what makes renders possible."""
    module = sys.modules.get("FreeCAD")
    return bool(module is not None and getattr(module, "GuiUp", False))
