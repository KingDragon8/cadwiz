"""Validate generated helical sections exported by a headless FreeCAD worker.

Usage: python scripts/check_gear_tooth_sections.py samples.json
Input is the per-gear format produced by work/validate_neil_helix.py. No GUI,
model mutation, filename-based gear recognition or solid-validity shortcut.
Shapely is an analysis dependency, imported only when checking exported data.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path


def check_sections(data: dict, tolerance_mm: float = 0.02) -> dict:
    from shapely.affinity import rotate
    from shapely.geometry import Polygon

    if not math.isfinite(tolerance_mm) or tolerance_mm <= 0 or not data:
        raise ValueError("Provide gear samples and a positive finite tolerance.")
    results = {}
    for name, gear in data.items():
        height = float(gear["height_mm"])
        deflection = float(gear["sampling_deflection_mm"])
        if not math.isfinite(deflection) or deflection <= 0 or tolerance_mm < 3 * deflection:
            raise ValueError(f"{name}: sampling is too coarse for the requested tolerance")
        twist = float(gear["twist_deg"])
        if not math.isfinite(height) or height <= 0 or not math.isfinite(twist):
            raise ValueError(f"{name}: invalid helix dimensions")
        reference = Polygon(gear["reference"])
        if not reference.is_valid or reference.area <= 0:
            raise ValueError(f"{name}: invalid reference profile")
        sections = gear["sections"]
        # Require data inside both halves, away from their generating stations.
        required = (0.125, 0.375, 0.625, 0.875)
        zs = [float(s["z"]) / height for s in sections]
        if not all(any(abs(z - f) < 1e-6 for z in zs) for f in required):
            raise ValueError(f"{name}: missing intermediate sections in both halves")
        rows = []
        for section in sections:
            z = float(section["z"])
            if not math.isfinite(z) or not 0 < z < height or len(section["points"]) != 1:
                raise ValueError(f"{name}: invalid generated cross-section")
            actual = Polygon(section["points"][0])
            if not actual.is_valid or actual.area <= 0:
                raise ValueError(f"{name}: invalid generated polygon")
            angle = twist * min(z, height - z) / (height / 2)
            expected = rotate(reference, angle, origin=(0, 0))
            error = float(actual.hausdorff_distance(expected))
            rows.append({"z_mm": z, "profile_error_mm": error,
                         "passed": math.isfinite(error) and error <= tolerance_mm})
        results[name] = {"passed": all(r["passed"] for r in rows), "sections": rows}
    return {"passed": all(r["passed"] for r in results.values()),
            "tolerance_mm": tolerance_mm, "gears": results,
            "scope": "Sampled tooth form only; not strength, backlash or load qualification."}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("samples", type=Path)
    parser.add_argument("--tolerance-mm", type=float, default=0.02)
    args = parser.parse_args()
    try:
        result = check_sections(json.loads(args.samples.read_text(encoding="utf-8")), args.tolerance_mm)
    except (ImportError, KeyError, TypeError, ValueError) as exc:
        print(json.dumps({"passed": False, "error": str(exc)}))
        return 2
    print(json.dumps(result, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
