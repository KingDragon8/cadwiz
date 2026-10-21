# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Windowless worker that runs one build step on a protected copy.

ORDER-2026-10-06-01 Part 1 (the window-lock fix). The model's own FreeCAD code
and full recomputes are the slowest steps of a build, and they used to run on
FreeCAD's GUI thread, so the window stopped answering for as long as they took
(measured: 21-76 s per step). This runs the same code in a separate headless
FreeCAD on a saved copy of the document; the GUI side only waits (live window,
live Cancel) and then brings the finished result into the visible document in
one short step (`offload.py`).

Invoked as:

    freecadcmd.exe exec_worker.py <snapshot.FCStd> <doc_name> <code.py> <result.json> <result.FCStd>

Writes `result.json` (an `ExecutionResult`-shaped record plus `changed`) and,
only when the document actually changed, `result.FCStd`.
"""
from __future__ import annotations

import io
import json
import sys
import time
import traceback
from contextlib import redirect_stderr, redirect_stdout


def _signature(document) -> dict:
    """Cheap, order-independent fingerprint of every object: enough to tell
    whether the step changed anything. Over-reporting a change is harmless (one
    extra short merge); under-reporting is not, so it errs towards 'changed'."""
    result = {}
    for obj in document.Objects:
        try:
            content = obj.Content
        except Exception:  # noqa: BLE001
            content = ""
        shape_part = ""
        shape = getattr(obj, "Shape", None)
        if shape is not None:
            try:
                box = shape.BoundBox
                shape_part = "|".join(
                    f"{value:.6g}"
                    for value in (
                        shape.Volume if shape.Solids else 0.0,
                        shape.Area,
                        len(shape.Faces),
                        len(shape.Edges),
                        box.XMin, box.XMax, box.YMin, box.YMax, box.ZMin, box.ZMax,
                    )
                )
            except Exception:  # noqa: BLE001
                shape_part = "?"
        result[obj.Name] = f"{obj.TypeId}|{hash(content)}|{shape_part}"
    return result


def _json_safe(value):
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        pass
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return repr(value)


class _Recorder:
    """Stands in for the 3D view side (`obj.ViewObject`, `FreeCADGui`) in the
    windowless helper: every setting and call is written down instead of done,
    and the window side replays them on the real objects once the result is in.
    Cosmetic only (colour, visibility, camera) -- it never touches geometry."""

    def __init__(self, ops, kind, target, path=()):
        object.__setattr__(self, "_ops", ops)
        object.__setattr__(self, "_kind", kind)
        object.__setattr__(self, "_target", target)
        object.__setattr__(self, "_path", path)

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return _Recorder(self._ops, self._kind, self._target, self._path + (name,))

    def __setattr__(self, name, value):
        self._ops.append(["set", self._kind, self._target, list(self._path) + [name], _json_safe(value)])

    def __call__(self, *args, **kwargs):
        self._ops.append(["call", self._kind, self._target, list(self._path), _json_safe(list(args)), _json_safe(kwargs)])
        return self

    def __bool__(self):
        return True

    def __iter__(self):
        return iter(())


def _make_view_transformer(ast_module):
    class ViewObjectToRecorder(ast_module.NodeTransformer):
        def visit_Attribute(self, node):
            self.generic_visit(node)
            if node.attr == "ViewObject" and isinstance(node.ctx, ast_module.Load):
                return ast_module.copy_location(
                    ast_module.Call(func=ast_module.Name(id="__vo__", ctx=ast_module.Load()), args=[node.value], keywords=[]),
                    node,
                )
            return node

    return ViewObjectToRecorder()


def main() -> int:
    if len(sys.argv) < 6:
        sys.stderr.write("usage: exec_worker.py <snapshot> <doc_name> <code.py> <result.json> <result.FCStd>\n")
        return 2
    snapshot, doc_name, code_path, result_json, result_fcstd = sys.argv[-5:]
    record: dict = {"success": False, "result": None, "stdout": "", "stderr": "",
                    "execution_time_ms": 0.0, "error_type": None, "error_traceback": None,
                    "changed": False, "worker_error": None}
    try:
        import FreeCAD  # noqa: PLC0415

        document = FreeCAD.newDocument(doc_name)
        document.mergeProject(snapshot)
        FreeCAD.setActiveDocument(document.Name)
        before = _signature(document)
        with open(code_path, "r", encoding="utf-8") as handle:
            code = handle.read()
        import ast
        import types

        # Whole-document operations make no sense on a disposable copy: if the
        # step really calls one, say so and the window side runs it itself.
        # (The common `FreeCAD.ActiveDocument or FreeCAD.newDocument(..)` idiom
        # never reaches the call, because the copy always has an active document.)
        def _needs_window(name):
            def guard(*_args, **_kwargs):
                record["needs_window"] = True
                raise RuntimeError(f"{name} needs the window")

            return guard

        for _name in ("newDocument", "closeDocument", "openDocument"):
            setattr(FreeCAD, _name, _needs_window(_name))

        view_ops: list = []
        record["view_ops"] = view_ops
        gui_proxy = _Recorder(view_ops, "gui", "")
        gui_module = types.ModuleType("FreeCADGui")
        gui_module.__getattr__ = lambda name: getattr(gui_proxy, name)  # type: ignore[attr-defined]
        sys.modules["FreeCADGui"] = gui_module

        def view_of(obj):
            name = getattr(obj, "Name", None)
            if name is None:
                raise AttributeError("ViewObject")
            return _Recorder(view_ops, "view", name)

        # ORDER-2026-10-11-03, hard safety envelope: the model's code runs with
        # restricted builtins (imports: FreeCAD modules and maths; files only
        # inside the project folder; no exec/eval) and the process itself has
        # its shell, network, subprocess and deletion entry points refused.
        # The project folder is the one the window side names
        # (CADWIZ_SANDBOX_PROJECT_DIR), else the folder holding this snapshot.
        import os  # noqa: PLC0415

        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import cadwiz_sandbox  # noqa: PLC0415

        project_dir = os.environ.get("CADWIZ_SANDBOX_PROJECT_DIR") or os.path.dirname(os.path.abspath(snapshot))
        policy = cadwiz_sandbox.SandboxPolicy(project_dir, extra_paths=[os.path.dirname(os.path.abspath(result_json))])
        record["sandbox"] = {"project_dir": str(policy.project_dir), "hardened": cadwiz_sandbox.harden_process(policy)}
        scope = cadwiz_sandbox.make_sandbox_globals(
            policy,
            {"FreeCAD": FreeCAD, "App": FreeCAD, "FreeCADGui": gui_proxy, "Gui": gui_proxy, "__vo__": view_of},
        )
        tree = _make_view_transformer(ast).visit(ast.parse(code, "<mcp>"))
        ast.fix_missing_locations(tree)
        code_object = compile(tree, "<mcp>", "exec")
        out, err = io.StringIO(), io.StringIO()
        started = time.perf_counter()
        try:
            with redirect_stdout(out), redirect_stderr(err):
                exec(code_object, scope)  # noqa: S102 - the model's build step, inside the envelope
            record["success"] = True
            record["result"] = _json_safe(scope.get("_result_"))
        except Exception as error:  # noqa: BLE001 - reported, same shape as the in-process path
            record["error_type"] = type(error).__name__
            record["error_traceback"] = traceback.format_exc()
        record["execution_time_ms"] = (time.perf_counter() - started) * 1000
        record["stdout"], record["stderr"] = out.getvalue(), err.getvalue()
        target = FreeCAD.getDocument(document.Name)
        after = _signature(target)
        record["changed"] = after != before
        if record["changed"]:
            target.saveAs(result_fcstd)
    except Exception:  # noqa: BLE001
        record["worker_error"] = traceback.format_exc()
    with open(result_json, "w", encoding="utf-8") as handle:
        json.dump(record, handle)
    sys.stdout.write("CADWIZ_DONE\n")
    sys.stdout.flush()
    return 0


sys.exit(main())
