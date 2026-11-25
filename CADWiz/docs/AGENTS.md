# CADWiz support instructions

Read CADWIZ-SUPPORT.md in this folder before troubleshooting this release.
Run read-only Doctor checks first. Do not execute untrusted startup code to
inspect it. Preserve all user data and use the existing FreeCAD window.
Ask before repairs or sharing diagnostic information. Do not claim startup or
AI access from installed files. This support package describes version 1.0.0.

Before model changes establish document_operation: inspect, modify, new or variant.
For a variant, use the exact requested source path and a separately named target;
never substitute an active or similarly named document. Once authority is bound,
other targets are protected. Use resolve_geometry for native selection references
and annular_edit for its supported dimensional changes. Inward widening lowers
inner radius and preserves outer radius; radial and diametric units differ.
Never call command execution alone VERIFIED SUCCESS. Respect machine-readable
verification/rollback statuses and inspect actual measured deltas. A visual mark
without a native reference is unresolved geometry. See docs/CADWIZ-ENGINEERING-CONTROL.md
in the release for the supported scope, tolerances and tester procedure.

For connection, login or account questions in ordinary language, use diagnostic_status and connection_status. Separate native account results, authenticated heartbeat, document access and successful CAD operations. Never infer a stale PID from an unreachable bridge. A replacement permits only matching-document read-only recovery until the owner explicitly selects its window with Connect. Do not substitute a standalone macro or another GUI for a failed connection.

## Gear quality and model-aware animation (0.9.4)

Read GEAR-QUALITY-GUARD.md before creating or changing involute/helical gears. Use native helical sweeps; kernel validity and source profiles alone do not validate generated flanks. Check intermediate generated sections and inspect shaded teeth. MODEL-ANIMATION.md explains previews and their limits. Preserve parametric history and the existing FreeCAD window.
