# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Standalone worker for VERIFY-FAST's tier-3 exact collision/clearance
check (`verification.py`'s own `_measure_probe`), run as a genuinely
killable OS subprocess rather than a thread.

**Why a subprocess, not a thread (2026-09-09).** VERIFY-FAST's first
attempt bounded the exact `Shape.common()`/`distToShape()` call with a
worker THREAD and `concurrent.futures.Future.result(timeout=...)`.
Measured directly against the real S3 model: that bound did not hold --
checkpoint 1 ran past 90 minutes on a single call. `Shape.common()` does
not release Python's GIL for the duration of its own C++ computation, so
the MAIN thread's own timeout check -- which also needs the GIL to run at
all -- never got a chance to fire; the "bounded" call was never actually
bounded. A separate OS process has its own GIL and can be forcibly killed
by the parent regardless of what it is doing, which a thread cannot be.

Invoked as:

    freecadcmd.exe collision_worker.py <common|distance> <shape_a.brep> <shape_b.brep>

Prints a single float to stdout on success (`common` -> overlap volume in
mm3, `distance` -> minimum distance in mm) and exits 0. Writes a message to
stderr and exits non-zero on any failure -- the caller
(`verification.py`'s own `_measure_probe`) already treats a non-zero exit,
a timeout, or unparseable stdout identically: `inconclusive_budget_exceeded`,
never silently "no collision".
"""

from __future__ import annotations

import sys


def main() -> int:
    # `freecadcmd.exe script.py a b c` puts `freecadcmd.exe` itself at
    # argv[0] and the SCRIPT's own path at argv[1] -- confirmed 2026-09-09,
    # different from plain `python.exe`'s own convention (argv[0] is the
    # script). The real arguments are always the last three, regardless of
    # how many interpreter/script entries precede them.
    if len(sys.argv) < 4:
        sys.stderr.write("usage: [freecadcmd.exe] collision_worker.py <common|distance> <shape_a.brep> <shape_b.brep>\n")
        sys.stderr.flush()
        return 2
    op, path_a, path_b = sys.argv[-3], sys.argv[-2], sys.argv[-1]
    try:
        import Part  # noqa: PLC0415

        shape_a = Part.Shape()
        with open(path_a, "r", encoding="utf-8") as handle:
            shape_a.importBrepFromString(handle.read())
        shape_b = Part.Shape()
        with open(path_b, "r", encoding="utf-8") as handle:
            shape_b.importBrepFromString(handle.read())
        if op == "common":
            result = shape_a.common(shape_b).Volume
        elif op == "distance":
            result = shape_a.distToShape(shape_b)[0]
        elif op == "both":
            # one process for both numbers (ORDER-2026-10-06-01): the caller
            # reads two lines, overlap volume then minimum distance
            result = shape_a.common(shape_b).Volume
            distance = shape_a.distToShape(shape_b)[0]
            sys.stdout.write(repr(float(result)) + chr(10) + repr(float(distance)) + chr(10))
            sys.stdout.flush()
            return 0
        else:
            sys.stderr.write(f"unknown op: {op}\n")
            return 2
    except Exception as error:  # noqa: BLE001 - reported to the parent, not swallowed
        sys.stderr.write(f"{type(error).__name__}: {error}\n")
        sys.stderr.flush()
        return 1
    # Confirmed 2026-09-09: an unflushed sys.stdout.write() immediately
    # before sys.exit() under freecadcmd.exe's own script-exit handling
    # (module-imported, not run as __main__ - see this codebase's own
    # documented quirk) can be lost entirely, silently, with no error and
    # exit code 0. Always flush explicitly; do not rely on interpreter
    # shutdown to do it. The trailing newline matters too: freecadcmd's
    # own version banner prints to stdout on process shutdown, appended
    # directly after this write with no separator of its own if this one
    # does not end in "\n" - the caller only ever reads the FIRST line.
    sys.stdout.write(repr(float(result)) + "\n")
    sys.stdout.flush()
    return 0


sys.exit(main())
