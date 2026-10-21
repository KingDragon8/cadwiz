# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""The hard safety envelope for master-written code (ORDER-2026-10-11-03).

Chain of command: Founder > hard safety envelope > master AI > CADWiz execution >
FreeCAD. The master's code already runs in a SEPARATE headless FreeCAD process
on a saved copy of the document (`exec_worker.py`, started by `offload.py`
through `isolated.run_headless`). This module adds, inside that process, the
limits the envelope demands and that the master cannot relax:

* no network, no shell, no subprocesses  -- `harden_process()` replaces the
  entry points (`socket`, `subprocess`, `os.system`/`popen`/`spawn*`/`exec*`)
  with ones that raise `SandboxViolation`, and the restricted `__import__`
  refuses the modules outright;
* file access only inside the current project folder (plus the worker's own
  result paths) -- a restricted `open` enforces it; `os.remove`/`unlink`/
  `rmdir`/`rename`/`replace` and `shutil` are refused;
* imports limited to FreeCAD and math modules -- an allow-list, nothing else;
* time and memory limits per run -- time is `run_headless`'s ceiling (kills the
  helper), memory is a Windows Job Object limit set by `isolated.run_headless`
  (`memory_limit_bytes`, default 2 GB) on the helper process.

Honest limit: this is Python-level containment of a model's accidental harm.
A determined adversary with arbitrary Python can escape a restricted
`__builtins__`; the process boundary, the saved copy, the Job Object and the
read-only founder files are the layers that hold then. Nothing here imports
FreeCAD; it is plain Python so it can be tested without it.
"""
from __future__ import annotations

import builtins
import math
import os
import sys
from pathlib import Path
from typing import Any, Callable, Iterable

#: Default per-run limits (founder-changeable by ruling, not by the master).
DEFAULT_TIME_LIMIT_SECONDS = 60.0
DEFAULT_MEMORY_LIMIT_BYTES = 2 * 1024 ** 3

#: Modules the master's code may import. FreeCAD's own module family, plus the
#: maths the geometry needs. Nothing that reaches the network, the shell, the
#: filesystem or other processes.
ALLOWED_IMPORTS: frozenset[str] = frozenset(
    {
        "FreeCAD", "App", "FreeCADGui", "Gui", "Part", "PartDesign", "Sketcher", "Mesh", "MeshPart",
        "Draft", "Spreadsheet", "Import", "ImportGui", "TechDraw", "BOPTools", "Points", "Fem", "Arch",
        "math", "cmath", "statistics", "numbers", "decimal", "fractions", "random", "itertools",
        "functools", "operator", "collections", "dataclasses", "typing", "enum", "copy", "re", "json",
        "string", "textwrap", "datetime", "time",
    }
)

#: Imports refused by name even when a FreeCAD module would pull them in
#: indirectly through the master's code.
FORBIDDEN_IMPORTS: frozenset[str] = frozenset(
    {
        "os", "sys", "subprocess", "socket", "shutil", "pathlib", "glob", "urllib", "http", "ftplib",
        "smtplib", "ssl", "asyncio", "multiprocessing", "threading", "ctypes", "importlib", "io",
        "tempfile", "pickle", "shelve", "marshal", "code", "codeop", "pty", "signal", "webbrowser",
        "requests", "httpx", "aiohttp", "builtins", "gc", "inspect", "resource", "winreg", "msvcrt",
    }
)


class SandboxViolation(RuntimeError):
    """The master's code tried something the envelope forbids. Nothing ran."""


class SandboxPolicy:
    """Where the code may read and write, and what it may import."""

    def __init__(self, project_dir: str | os.PathLike[str], extra_paths: Iterable[str | os.PathLike[str]] = ()) -> None:
        self.project_dir = Path(project_dir).resolve()
        self.extra_paths = tuple(Path(p).resolve() for p in extra_paths)

    def allows_path(self, path: str | os.PathLike[str]) -> bool:
        try:
            resolved = Path(path).resolve()
        except (OSError, RuntimeError, ValueError):
            return False
        for root in (self.project_dir, *self.extra_paths):
            if resolved == root or root in resolved.parents:
                return True
        return False


def _restricted_import(policy: SandboxPolicy) -> Callable[..., Any]:
    real_import = builtins.__import__

    def guarded_import(name: str, globals_: Any = None, locals_: Any = None, fromlist: Any = (), level: int = 0) -> Any:
        top = (name or "").split(".")[0]
        if level != 0 or not top:
            raise SandboxViolation("relative imports are not allowed in a design script")
        if top in FORBIDDEN_IMPORTS:
            raise SandboxViolation(f"import of '{top}' is not allowed in a design script (no shell, network, files or processes)")
        if top not in ALLOWED_IMPORTS:
            raise SandboxViolation(f"import of '{top}' is not allowed in a design script; allowed: FreeCAD modules and maths")
        return real_import(name, globals_, locals_, fromlist, level)

    return guarded_import


def _restricted_open(policy: SandboxPolicy) -> Callable[..., Any]:
    real_open = builtins.open

    def guarded_open(file: Any, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        if isinstance(file, int):
            raise SandboxViolation("opening raw file descriptors is not allowed in a design script")
        if not policy.allows_path(file):
            raise SandboxViolation(f"a design script may only read and write inside the project folder; refused: {file}")
        return real_open(file, mode, *args, **kwargs)

    return guarded_open


def _refused(what: str) -> Callable[..., Any]:
    def refuse(*_args: Any, **_kwargs: Any) -> Any:
        raise SandboxViolation(f"{what} is not allowed in a design script")

    return refuse


def make_sandbox_globals(policy: SandboxPolicy, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """The globals a design script runs with: ordinary builtins minus the
    dangerous ones, a restricted `__import__` and `open`, `math` ready to use."""
    safe_builtins = dict(vars(builtins))
    for name in ("exec", "eval", "compile", "input", "breakpoint", "exit", "quit", "help", "memoryview", "globals", "locals", "vars", "__loader__", "__spec__"):
        safe_builtins.pop(name, None)
    safe_builtins["__import__"] = _restricted_import(policy)
    safe_builtins["open"] = _restricted_open(policy)
    namespace: dict[str, Any] = {"__builtins__": safe_builtins, "__name__": "__design_script__", "math": math}
    if extra:
        namespace.update(extra)
    return namespace


def exec_sandboxed(code: str, policy: SandboxPolicy, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run a design script under the envelope and return its namespace."""
    namespace = make_sandbox_globals(policy, extra)
    compiled = compile(code, "<design script>", "exec")
    exec(compiled, namespace)  # noqa: S102 -- this IS the sandboxed execution point
    return namespace


def harden_process(policy: SandboxPolicy) -> list[str]:
    """Process-wide belt and braces for the headless helper: even code that
    reaches the real modules (through a FreeCAD object, say) finds the shell,
    network and process entry points refused. Returns what was replaced.
    Call once, after FreeCAD is imported and before the design script runs."""
    replaced: list[str] = []
    try:
        import socket as _socket  # noqa: PLC0415

        _socket.socket = _refused("network access")  # type: ignore[misc]
        _socket.create_connection = _refused("network access")  # type: ignore[assignment]
        _socket.getaddrinfo = _refused("network access")  # type: ignore[assignment]
        replaced.append("socket")
    except Exception:  # noqa: BLE001
        pass
    try:
        import subprocess as _subprocess  # noqa: PLC0415

        _subprocess.Popen = _refused("starting a program")  # type: ignore[misc]
        _subprocess.run = _refused("starting a program")  # type: ignore[assignment]
        _subprocess.call = _refused("starting a program")  # type: ignore[assignment]
        _subprocess.check_output = _refused("starting a program")  # type: ignore[assignment]
        replaced.append("subprocess")
    except Exception:  # noqa: BLE001
        pass
    for name in ("system", "popen", "execv", "execve", "execl", "execlp", "execvp", "execvpe", "spawnl", "spawnv", "spawnle", "spawnve", "startfile", "kill", "remove", "unlink", "rmdir", "removedirs", "rename", "replace", "truncate", "chmod"):
        if hasattr(os, name):
            setattr(os, name, _refused(f"os.{name}"))
            replaced.append(f"os.{name}")
    try:
        import shutil as _shutil  # noqa: PLC0415

        for name in ("rmtree", "move", "copy", "copy2", "copyfile", "copytree"):
            setattr(_shutil, name, _refused(f"shutil.{name}"))
        replaced.append("shutil")
    except Exception:  # noqa: BLE001
        pass
    os.environ["CADWIZ_SANDBOX_PROJECT_DIR"] = str(policy.project_dir)
    return replaced


def describe_limits(time_limit_s: float = DEFAULT_TIME_LIMIT_SECONDS, memory_limit_bytes: int = DEFAULT_MEMORY_LIMIT_BYTES) -> str:
    return (
        f"separate FreeCAD process on a saved copy; no network, shell or subprocesses; files only inside the "
        f"project folder; imports: FreeCAD modules and maths; {time_limit_s:g} s and {memory_limit_bytes // (1024 ** 2)} MB per run"
    )


__all__ = [
    "ALLOWED_IMPORTS", "DEFAULT_MEMORY_LIMIT_BYTES", "DEFAULT_TIME_LIMIT_SECONDS", "FORBIDDEN_IMPORTS",
    "SandboxPolicy", "SandboxViolation", "describe_limits", "exec_sandboxed", "harden_process", "make_sandbox_globals",
]

if sys.platform != "win32":  # pragma: no cover - the product runs on Windows; keep importable elsewhere
    pass
