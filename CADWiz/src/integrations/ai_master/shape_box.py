# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
"""A shape's true extents (ORDER-2026-10-12-03).

FreeCAD's `Shape.BoundBox` of a trimmed spline face covers the whole UNTRIMMED
surface. On the founder's CoolOff_AI1 helmet that made the shell read 117.6 mm
tall when it is 88.8 mm (its head-side surface runs 12 mm below the bottom and
17 mm above the top before it is trimmed), and that wrong height went into
CADWiz's measurement answers. `optimalBoundingBox` measures the trimmed shape.
"""
from __future__ import annotations

from typing import Any


def tight_box(shape: Any) -> Any:
    try:
        box = shape.optimalBoundingBox(True, False)
        if box is not None and box.isValid():
            return box
    except Exception:  # noqa: BLE001 - older FreeCAD, a mesh, or a test stand-in
        pass
    return shape.BoundBox
