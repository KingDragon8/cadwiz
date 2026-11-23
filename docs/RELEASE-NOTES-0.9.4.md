# CADWiz 0.9.4 Beta — model-aware motion and gear quality

This update builds on 0.9.3. Existing connection, secure credential, installer,
backup and parametric-history protections remain in place.

## Changes

- Animate uses the current document. Compatible external involute gears are
  recognized from their parameters and axes, and counter-rotate by tooth ratio.
  Temporary preview drawings do not edit manufacturing placements.
- Other visible models receive a clearly labeled camera turntable. Empty views
  are rejected before changing assembly or camera state. Existing dispenser and
  phone-holder adapters remain available.
- The Problems panel warns about active lofted involute gears needing tooth-form
  verification. This bounded metadata check does not section solids on the GUI
  thread, flag ordinary lofts or treat unused hidden history as the current part.
- A separate checker compares actual generated intermediate sections against
  expected rotated involute sections. Missing or insufficiently sampled data
  fails rather than passing silently.
- The synthetic gearbox benchmark now uses two single-piece, editable gears
  built with native opposite-hand AdditiveHelix features. It exercises save,
  reopen, recomputation and dimensional edits. CI checks generated sections and
  real Pivy/Coin gear rotations, cleanup and camera restoration.
- Installed assistant guidance includes the construction lesson, a reproducible
  beta gearbox exercise, and a compact-project workflow to reduce rework and
  repeated context. No owner model, account data or billing records are bundled.

## Important limits

The loft warning identifies a construction needing verification; it neither
proves every loft defective nor certifies every unflagged gear. Sampled tooth
checks do not establish strength, fatigue, wear, contact stresses or print fit.
Turntable previews do not invent mechanical joints or simulate loads.

Native kernel/Coin checks and automated tests are distinct from live owner-session
button acceptance. Windows control of the owner's open session was intermittent;
that live-button acceptance is not claimed. Native Mac installer evidence is
limited to the CI environments exercised; Intel macOS Monterey is not verified.
The Windows beta installer remains unsigned.

## Updating

Save work and close FreeCAD before upgrading. On Windows run
`CADWiz-Setup-0.9.4.exe`. On macOS extract the complete ZIP and use
`Install-CADWiz.command`. On Linux extract the ZIP and use `scripts/install.sh`
with the intended FreeCAD runtime. Existing settings and user documents use
the established backup/recovery paths. Previous releases remain available.
