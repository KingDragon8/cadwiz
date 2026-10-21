# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Run the heavy build steps off the window thread (ORDER-2026-10-06-01 Part 1).

**Design (two sentences).** The model's own FreeCAD code and full recomputes are
run by a separate windowless FreeCAD on a saved copy of the document, while the
GUI thread only waits -- so the window keeps repainting, shows progress, and
Cancel simply stops that helper before anything has touched the document.
When the helper finishes, its result is brought into the visible document in
one short step inside one undo transaction (everything is swapped in, the
user's own colours and visibility are put back), the same "do the heavy work on
a protected copy, then bring in the finished result" shape the what-if previews
already use.

Only code that can run without the 3D view is offloaded. Anything that
mentions the GUI, selection, other documents or saving is run in the window as
before, and so is anything the helper could not run for infrastructure reasons:
the helper never touched the user's document, so falling back is always safe.
"""
from __future__ import annotations

import contextvars
import json
import os
import re
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from . import progress
from .isolated import headless_available, run_headless

#: Tools whose bridge calls are heavy enough to be worth a helper process.
OFFLOAD_TOOLS = frozenset({"execute_python", "recompute", "recompute_document"})

#: Ceiling for one offloaded step. The in-process path had no effective limit
#: at all (a stuck loop froze the window forever); this one can be killed.
_STEP_CEILING_SECONDS = 300.0

_offload_active: contextvars.ContextVar[bool] = contextvars.ContextVar("_offload_active", default=False)

#: Code that needs the live window, other documents, or the disk copy of the
#: document cannot run on a headless copy.
_NEEDS_WINDOW = re.compile(
    r"Selection|PySide|getMainWindow|getSelection|"
    r"\.save\(|saveAs\(|saveCopy\(|runCommand|doCommand|[Ww]orkbench|"
    r"\.restore\(|\.load\(|mergeProject|importObjects|screenshot|[Ss]napshot",
)

#: A helper-side failure that only means "this needed the window".
_WINDOW_ERROR_HINTS = ("Gui", "ViewObject", "No document")


@contextmanager
def offloading():
    token = _offload_active.set(True)
    try:
        yield
    finally:
        _offload_active.reset(token)


def offload_wanted() -> bool:
    return _offload_active.get() and os.environ.get("CADWIZ_OFFLOAD") != "0"


def needs_window(code: str) -> bool:
    return bool(_NEEDS_WINDOW.search(code))


async def run_offloaded(bridge: Any, code: str, timeout_ms: int) -> Any | None:
    """Run `code` in a helper process on a copy of the active document and
    bring the result in. Returns an `ExecutionResult`, or `None` meaning
    "run it in the window as before" (nothing was changed)."""
    if not offload_wanted() or not headless_available():
        return None
    if needs_window(code):
        log_path = os.environ.get("CADWIZ_OFFLOAD_LOG")
        if log_path:
            with open(log_path, "a", encoding="utf-8") as log:
                log.write("--- SKIPPED (needs the window): match=" + repr(_NEEDS_WINDOW.findall(code)[:5]) + chr(10) + code[:1200] + chr(10))
        return None
    fc = getattr(bridge, "_fc_module", None)
    document = getattr(fc, "ActiveDocument", None) if fc is not None else None
    if document is None:
        return None
    from freecad_mcp.bridge.base import ExecutionResult  # type: ignore[import-not-found]

    work_dir = tempfile.mkdtemp(prefix="cadwiz_step_")
    try:
        snapshot = str(Path(work_dir) / "snapshot.FCStd")
        code_path = Path(work_dir) / "step_code.py"
        result_json = Path(work_dir) / "result.json"
        result_fcstd = str(Path(work_dir) / "result.FCStd")
        with progress.timed("offload: save safe copy"):
            progress.report("Saving a safe copy of your design")
            document.saveCopy(snapshot)
            code_path.write_text(code, encoding="utf-8")
        with progress.timed("offload: helper builds the shape"):
            # ORDER-2026-10-11-03, hard safety envelope: memory cap on the helper
            # and the project folder the model's code may touch (the folder of
            # the founder's saved document when it has one, else this step's
            # own work folder). Time cap = the ceiling below (the helper is killed).
            from .cadwiz_sandbox import DEFAULT_MEMORY_LIMIT_BYTES  # noqa: PLC0415

            founder_file = str(getattr(document, "FileName", "") or "")
            project_dir = str(Path(founder_file).resolve().parent) if founder_file else work_dir
            outcome = run_headless(
                str(Path(__file__).resolve().parent / "exec_worker.py"),
                [snapshot, document.Name, str(code_path), str(result_json), result_fcstd],
                timeout_s=min(_STEP_CEILING_SECONDS, max(timeout_ms / 1000.0, 120.0)),
                label="Building the shape in the background",
                memory_limit_bytes=DEFAULT_MEMORY_LIMIT_BYTES,
                env={**os.environ, "CADWIZ_SANDBOX_PROJECT_DIR": project_dir},
            )
        if outcome.timed_out:
            return ExecutionResult(
                success=False, result=None, stdout="",
                stderr=f"The build step ran past its {_STEP_CEILING_SECONDS:.0f}-second limit and was stopped; your design is unchanged.",
                execution_time_ms=_STEP_CEILING_SECONDS * 1000.0,
                error_type="TimeoutError", error_traceback=None,
            )
        if outcome.returncode != 0 or not result_json.exists():
            return None
        record = json.loads(result_json.read_text(encoding="utf-8"))
        if record.get("worker_error") or record.get("needs_window"):
            return None
        if not record.get("success") and any(
            hint in (record.get("error_traceback") or "") for hint in _WINDOW_ERROR_HINTS
        ):
            return None
        log_path = os.environ.get("CADWIZ_OFFLOAD_LOG")
        if log_path:
            with open(log_path, "a", encoding="utf-8") as log:
                names_before = [o.Name for o in document.Objects]
                log.write(chr(10).join([
                    f"--- step changed={record.get('changed')} success={record.get('success')} objects_before={names_before}",
                    code[:1500],
                    f"stdout={record.get('stdout', '')[:300]!r} err={(record.get('error_traceback') or '')[-300:]!r}",
                    "",
                ]))
        if record.get("changed"):
            with progress.timed("offload: bring result in"):
                progress.report("Bringing the finished shape into your design")
                if not _apply_result(document, result_fcstd):
                    return None
        _replay_view_ops(document, record.get("view_ops") or [])
        return ExecutionResult(
            success=bool(record.get("success")),
            result=record.get("result"),
            stdout=record.get("stdout", ""),
            stderr=record.get("stderr", ""),
            execution_time_ms=float(record.get("execution_time_ms", 0.0)),
            error_type=record.get("error_type"),
            error_traceback=record.get("error_traceback"),
        )
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def _capture_view_properties(document: Any) -> dict[str, dict[str, Any]]:
    saved: dict[str, dict[str, Any]] = {}
    for obj in document.Objects:
        view = getattr(obj, "ViewObject", None)
        if view is None:
            continue
        props: dict[str, Any] = {}
        for name in view.PropertiesList:
            try:
                value = getattr(view, name)
            except Exception:  # noqa: BLE001
                continue
            if isinstance(value, (bool, int, float, str, tuple)):
                props[name] = value
        saved[obj.Name] = props
    return saved


def _restore_view_properties(document: Any, saved: dict[str, dict[str, Any]]) -> None:
    for name, props in saved.items():
        obj = document.getObject(name)
        view = getattr(obj, "ViewObject", None) if obj is not None else None
        if view is None:
            continue
        for key, value in props.items():
            try:
                if getattr(view, key) != value:
                    setattr(view, key, value)
            except Exception:  # noqa: BLE001 - read-only or computed; skip
                continue


def _apply_result(document: Any, result_path: str) -> bool:
    """Swap the helper's finished document into `document` in ONE undo step.

    Returns False (document left exactly as it was) if anything goes wrong, so
    the caller can fall back to running the step in the window.
    """
    document.openTransaction("CADWiz build step")
    try:
        saved_views = _capture_view_properties(document)
        for obj in list(reversed(document.Objects)):
            try:
                document.removeObject(obj.Name)
            except Exception:  # noqa: BLE001 - already gone with its parent
                continue
        if document.Objects:
            raise RuntimeError("could not clear the design before bringing the result in")
        document.mergeProject(result_path)
        _restore_view_properties(document, saved_views)
        document.commitTransaction()
        return True
    except Exception:  # noqa: BLE001
        document.abortTransaction()
        return False


def _replay_view_ops(document: Any, ops: list) -> None:
    """Do, on the real objects and the real 3D view, the cosmetic settings the
    helper wrote down (colour, visibility, camera). A step that fails to replay
    costs a colour, never geometry, so each is attempted on its own."""
    if not ops:
        return
    try:
        import FreeCADGui  # type: ignore[import-not-found]
    except Exception:  # noqa: BLE001
        FreeCADGui = None  # noqa: N806
    for op in ops:
        try:
            action, kind, target, path = op[0], op[1], op[2], list(op[3])
            if kind == "view":
                obj = document.getObject(target)
                root = getattr(obj, "ViewObject", None) if obj is not None else None
            else:
                root = FreeCADGui
            if root is None:
                continue
            if action == "set":
                parent = root
                for name in path[:-1]:
                    parent = getattr(parent, name)
                value = op[4]
                setattr(parent, path[-1], tuple(value) if isinstance(value, list) else value)
            else:
                fn = root
                for name in path:
                    fn = getattr(fn, name)
                fn(*[tuple(a) if isinstance(a, list) else a for a in op[4]], **op[5])
        except Exception:  # noqa: BLE001 - cosmetic; skip this one
            continue
