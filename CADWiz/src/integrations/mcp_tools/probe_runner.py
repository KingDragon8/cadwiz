# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""Windowless runner for the measurement probe (ORDER-2026-10-06-01 Part 1).

The after-every-build measurement probe (`verification._measure_probe`) does
heavy pure-Python and OCC work -- point-cloud distances, containment tests,
pairwise collision checks -- that used to run on FreeCAD's GUI thread and
froze the window for up to a minute. It is read-only, so it can run in a
separate headless process on a saved copy of the document and hand back its
numbers; the GUI side only waits (keeping the window alive and Cancel live).

Invoked as:

    freecadcmd.exe probe_runner.py <doc.FCStd> <macro.py> <result.json>

The macro is the exact text `_measure_probe` produces; it sets `_result_`.
Progress lines (`CADWIZ_PROGRESS <done> <total>`) go to stdout as they happen.
"""
from __future__ import annotations

import json
import sys


def main() -> int:
    if len(sys.argv) < 4:
        sys.stderr.write("usage: probe_runner.py <doc.FCStd> <macro.py> <result.json>\n")
        return 2
    doc_path, macro_path, result_path = sys.argv[-3], sys.argv[-2], sys.argv[-1]
    try:
        import FreeCAD  # noqa: PLC0415

        document = FreeCAD.openDocument(doc_path)
        FreeCAD.setActiveDocument(document.Name)
        with open(macro_path, "r", encoding="utf-8") as handle:
            macro = handle.read()
        scope = {"FreeCAD": FreeCAD, "App": FreeCAD, "__builtins__": __builtins__}
        exec(compile(macro, "<probe>", "exec"), scope)  # noqa: S102 - our own generated probe text
        payload = json.dumps(scope.get("_result_"))
    except Exception as error:  # noqa: BLE001 - reported to the parent
        sys.stderr.write(f"{type(error).__name__}: {error}\n")
        sys.stderr.flush()
        return 1
    with open(result_path, "w", encoding="utf-8") as handle:
        handle.write(payload)
    sys.stdout.write("CADWIZ_DONE\n")
    sys.stdout.flush()
    return 0


sys.exit(main())
