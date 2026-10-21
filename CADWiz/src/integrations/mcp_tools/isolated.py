# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Run a headless FreeCAD helper process while keeping the window alive.

ORDER-2026-10-06-01 Part 1. Heavy geometry and measurement used to run on the
GUI thread, so the window stopped answering for as long as they took. The fix
is to run them in a separate windowless `freecadcmd.exe` on a protected copy
of the document and let the GUI thread only *wait*: repainting, showing plain
progress, and hearing Cancel. This module is that wait, shared by the
measurement probe (`verification.py`) and the build-step offload
(`offload.py`).

Cancel (`BuildCancelled`, raised by `progress.pump()`) kills the helper and
propagates; nothing the helper did ever reached the user's document.
"""
from __future__ import annotations

import queue
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from . import progress


def headless_freecad_exe() -> Path:
    return Path(sys.executable).resolve().with_name("freecadcmd.exe")


def headless_available() -> bool:
    return headless_freecad_exe().exists()


@dataclass
class HeadlessResult:
    returncode: int | None
    stdout_lines: list[str] = field(default_factory=list)
    stderr: str = ""
    timed_out: bool = False


def limit_process_memory(process: "subprocess.Popen[str]", limit_bytes: int) -> bool:
    """Cap a child's memory with a Windows Job Object (ORDER-2026-10-11-03, hard
    safety envelope: "time and memory limits per run"). A child that commits more
    than the limit fails its allocation and dies instead of eating the machine.
    Returns whether the limit was applied; False (not an exception) off Windows
    or if the Job Object calls fail, so a missing cap is reported, never fatal."""
    if sys.platform != "win32" or limit_bytes <= 0:
        return False
    try:
        import ctypes
        from ctypes import wintypes

        class IoCounters(ctypes.Structure):
            _fields_ = [(name, ctypes.c_ulonglong) for name in (
                "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

        class BasicLimit(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD),
            ]

        class ExtendedLimit(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", BasicLimit), ("IoInfo", IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            return False
        info = ExtendedLimit()
        info.BasicLimitInformation.LimitFlags = 0x100  # JOB_OBJECT_LIMIT_PROCESS_MEMORY
        info.ProcessMemoryLimit = int(limit_bytes)
        if not kernel32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):  # 9 = ExtendedLimitInformation
            return False
        handle = wintypes.HANDLE(process._handle)  # type: ignore[attr-defined]  # the Popen's own process handle
        return bool(kernel32.AssignProcessToJobObject(job, handle))
    except Exception:  # noqa: BLE001 - a cap that could not be set is reported by the caller, never fatal here
        return False


def run_headless(
    script: str,
    script_args: Sequence[str],
    *,
    timeout_s: float,
    label: str,
    on_line: Callable[[str], None] | None = None,
    memory_limit_bytes: int = 0,
    env: dict[str, str] | None = None,
) -> HeadlessResult:
    """Run `freecadcmd.exe <script> <args...>` and wait for it, pumping the
    window. The elapsed time is shown on the status line once a second.

    `memory_limit_bytes` > 0 caps the helper with a Job Object (see
    `limit_process_memory`); `env` replaces the helper's environment (the
    sandbox passes the project folder this way)."""
    process = subprocess.Popen(
        [str(headless_freecad_exe()), script, *script_args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        env=env,
    )
    if memory_limit_bytes:
        limit_process_memory(process, memory_limit_bytes)
    lines: "queue.Queue[str]" = queue.Queue()
    collected: list[str] = []
    stderr_chunks: list[str] = []

    def read_stdout() -> None:
        for line in process.stdout:  # type: ignore[union-attr]
            lines.put(line.rstrip("\r\n"))

    threading.Thread(target=read_stdout, daemon=True).start()
    threading.Thread(
        target=lambda: stderr_chunks.append(process.stderr.read()),  # type: ignore[union-attr]
        daemon=True,
    ).start()
    started = time.monotonic()
    last_status = 0.0
    try:
        progress.report(label)
        while process.poll() is None:
            if time.monotonic() - started > timeout_s:
                process.kill()
                process.wait()
                return HeadlessResult(None, collected, "".join(stderr_chunks), timed_out=True)
            progress.pump()
            while not lines.empty():
                line = lines.get()
                collected.append(line)
                if on_line is not None:
                    on_line(line)
            now = time.monotonic()
            if now - last_status >= 1.0:
                last_status = now
                progress.status(f"{label} ({now - started:.0f}s)")
            time.sleep(0.03)
        # let the reader threads drain what the exited process left behind
        time.sleep(0.05)
        while not lines.empty():
            line = lines.get()
            collected.append(line)
            if on_line is not None:
                on_line(line)
        return HeadlessResult(process.returncode, collected, "".join(stderr_chunks))
    except BaseException:
        if process.poll() is None:
            process.kill()
            process.wait()
        raise
    finally:
        if process.poll() is None:
            process.kill()
