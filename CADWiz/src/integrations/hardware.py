# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""What this machine actually has, or `None` where it cannot be known.

The single place hardware is read. The System Requirements panel uses it today
and the RAM-selected model ladder will use it when it exists -- one source, so
the panel cannot tell the user one thing while the router decides another.

Every field is `int | None`. `None` means "could not read", and it is never
collapsed to zero: a machine with unknown memory and a machine with no memory
warrant completely different sentences, and a caller that cannot tell them
apart will eventually print the wrong one.

No third-party packages. Everything here is `ctypes`, `shutil` and `os` from
the standard library, because a requirements checker that needs its own
requirements installed first is not much of a checker.
"""

from __future__ import annotations

import ctypes
import os
import platform
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Hardware:
    """A machine, as far as it could be measured."""

    total_memory_bytes: int | None = None
    available_memory_bytes: int | None = None
    cpu_cores: int | None = None
    cpu_physical_cores: int | None = None
    cpu_name: str | None = None
    free_disk_bytes: int | None = None
    gpu_name: str | None = None
    gpu_memory_bytes: int | None = None
    platform_name: str = ""
    platform_release: str = ""
    architecture: str = ""
    gpu_vendor: str | None = None
    acceleration: tuple[str, ...] = ()

    @property
    def total_memory_gb(self) -> float | None:
        return None if self.total_memory_bytes is None else self.total_memory_bytes / 1024**3

    @property
    def free_disk_gb(self) -> float | None:
        return None if self.free_disk_bytes is None else self.free_disk_bytes / 1024**3

    @property
    def gpu_memory_gb(self) -> float | None:
        return None if self.gpu_memory_bytes is None else self.gpu_memory_bytes / 1024**3


class _MemoryStatusEx(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_uint64),
        ("ullAvailPhys", ctypes.c_uint64),
        ("ullTotalPageFile", ctypes.c_uint64),
        ("ullAvailPageFile", ctypes.c_uint64),
        ("ullTotalVirtual", ctypes.c_uint64),
        ("ullAvailVirtual", ctypes.c_uint64),
        ("ullAvailExtendedVirtual", ctypes.c_uint64),
    ]


def _memory() -> tuple[int | None, int | None]:
    """Total and available physical memory, or `(None, None)`.

    Total is what a model ladder must key off. Available swings with whatever
    else the user has open, so a rung chosen from it would move between one
    launch and the next for reasons the user cannot see.
    """
    if platform.system() != "Windows":
        return (None, None)
    try:
        status = _MemoryStatusEx()
        status.dwLength = ctypes.sizeof(_MemoryStatusEx)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return (None, None)
        return (int(status.ullTotalPhys), int(status.ullAvailPhys))
    except Exception:
        return (None, None)


def _cores() -> int | None:
    try:
        return os.cpu_count()
    except Exception:
        return None


def _cpu_name() -> str | None:
    try:
        value = platform.processor().strip()
        if value:
            return value
        if platform.system() == "Windows":
            value = os.environ.get("PROCESSOR_IDENTIFIER", "").strip()
            return value or None
    except Exception:
        pass
    return None


def _free_disk(where: Path | None = None) -> int | None:
    try:
        target = where or Path(__file__).resolve().anchor or Path.home()
        return int(shutil.disk_usage(str(target)).free)
    except Exception:
        return None


def _gpu() -> tuple[str | None, int | None, str | None, tuple[str, ...]]:
    """Graphics card name and memory, via nvidia-smi if it is present.

    Deliberately shallow. nvidia-smi covers the NVIDIA cards this is aimed at
    and needs nothing installed; AMD and Intel report `None`, which is honest.
    Guessing a card's memory from its name would be inventing a number, and an
    unknown here costs the user one softer sentence rather than a wrong answer.
    """
    if platform.system() != "Windows":
        return (None, None, None, ())
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=8,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception:
        return (None, None, None, ())
    if result.returncode != 0 or not result.stdout.strip():
        return (None, None, None, ())
    first = result.stdout.strip().splitlines()[0]
    parts = [piece.strip() for piece in first.split(",")]
    if len(parts) < 2:
        return (parts[0] or None, None, "NVIDIA", ("CUDA",))
    name = parts[0] or None
    try:
        # nvidia-smi reports MiB with nounits.
        return (name, int(float(parts[1])) * 1024 * 1024, "NVIDIA", ("CUDA",))
    except (TypeError, ValueError):
        return (name, None, "NVIDIA", ("CUDA",))


def detect(disk_target: Path | None = None) -> Hardware:
    """Read the machine once. Never raises; unreadable values come back `None`."""
    total, available = _memory()
    gpu_name, gpu_memory, gpu_vendor, acceleration = _gpu()
    return Hardware(
        total_memory_bytes=total,
        available_memory_bytes=available,
        cpu_cores=_cores(),
        cpu_name=_cpu_name(),
        free_disk_bytes=_free_disk(disk_target),
        gpu_name=gpu_name,
        gpu_memory_bytes=gpu_memory,
        platform_name=platform.system() or "",
        platform_release=platform.release() or "",
        architecture=platform.machine() or "",
        gpu_vendor=gpu_vendor,
        acceleration=acceleration,
    )
