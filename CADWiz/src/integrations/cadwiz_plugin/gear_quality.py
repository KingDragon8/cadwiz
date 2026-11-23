"""LL-051: cheap, read-only detection; never section solids on the GUI thread."""
from __future__ import annotations

import contextlib
from typing import Any


def lofted_gears(objects: list[Any]) -> list[Any]:
    """Find active lofts made from involute profiles, using properties, not names.

    A warning requests verification, rather than asserting every loft is bad.
    Hidden construction features are inspected only if used by a visible Body.
    """
    found = []
    for obj in objects:
        if str(getattr(obj, "TypeId", "")) not in {
            "PartDesign::AdditiveLoft", "Part::Loft",
        }:
            continue
        profiles = list(getattr(obj, "Sections", []) or [])
        first = getattr(obj, "Profile", None)
        if isinstance(first, tuple):
            first = first[0]
        if first is not None:
            profiles.insert(0, first)
        if not any(hasattr(p, "NumberOfTeeth") and hasattr(p, "Modules") for p in profiles):
            continue
        parent = None
        with contextlib.suppress(Exception):
            parent = obj.getParentGeoFeatureGroup()
        owner = parent if getattr(parent, "TypeId", "") == "PartDesign::Body" else obj
        view = getattr(owner, "ViewObject", None)
        if not bool(getattr(view, "Visibility", getattr(owner, "Visibility", False))):
            continue
        if owner is not obj:
            tip = getattr(owner, "Tip", None)
            if tip is None:
                continue
            dependencies = getattr(tip, "OutListRecursive", None)
            if dependencies is not None and tip is not obj and obj not in dependencies:
                continue
        found.append(obj)
    return found
