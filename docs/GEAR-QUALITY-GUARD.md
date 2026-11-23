# Gear tooth quality guard (LL-051)

The CADWiz Problems panel identifies active lofts built from native involute
profiles. Detection uses feature types, profile parameters, visible Body state,
and the current Tip's dependencies, never project or feature names. Hidden,
unused history and ordinary lofts do not trigger this warning. Native helical
features do not trigger this particular construction warning.

This is a request for tooth-form verification, not proof that every loft is bad
or that every unflagged gear is correct. Solid validity, source-profile
clearance, and an animation are insufficient evidence of a correct tooth form.
No slicing, Boolean operations, geometry changes, or expensive calculations
run on FreeCAD's window thread as part of this guard.

For a detailed check, export generated transverse sections in a headless worker
and run `python scripts/check_gear_tooth_sections.py samples.json`. Use an
analysis Python environment with Shapely installed. Exit 0 means the sampled
profile comparison passed, 1 means distortion was detected, and 2 means the
check could not be completed. Missing data must never be treated as a pass.

The JSON maps gear identifiers to `reference` (closed XY profile points),
`height_mm`, `twist_deg` (signed twist from bottom to the central junction),
`sampling_deflection_mm`, and `sections` (each has `z` and `points`, a list of
closed XY outlines from the actual generated solid). Coordinates must be in
the gear's local frame with the shaft on Z at XY origin and bottom at z=0.
The current checker supports symmetric herringbone gears and requires
intermediate sections at 1/8, 3/8, 5/8, and 7/8 of face width. It compares dense
polygonal sections using Hausdorff distance, with default tolerance 0.02 mm.
Sampling deflection must be no larger than one third of that tolerance.

The check does not suppress construction warnings automatically: exported data
can become stale after an edit. It does not establish load capacity, backlash,
contact stresses, material suitability, manufacturing fit, or whole-surface
quality between the tested sections. Native validity, a correct center junction,
mesh clearance, and shaded/edge visual inspection are separate acceptance steps.

Regression coverage: `tests/unit/test_gear_quality_guard.py`. Native evidence
from the original and corrected gearbox is retained under
`work/gear-quality-native-result.json`, `work/gear-tooth-good-result.json`, and
`work/gear-tooth-bad-result.json` in this workspace.

Installed changes take effect when FreeCAD next loads CADWiz. Do not restart or
close an owner's unsaved session to load a validation improvement. This local
patch is not evidence of publication in the website download.

Closed-wire seam endpoints are normalized only within 1e-8 mm to remove floating-point duplication. Other self-intersections remain failures; polygons are never repaired with buffer(0).
