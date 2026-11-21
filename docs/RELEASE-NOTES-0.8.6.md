# CADWiz Beta 0.8.6

This beta strengthens editable-model acceptance, model presentation, layout recovery and project-folder persistence. Install the attached ZIP or use Addon Manager branch `release/0.8.6`. Restart FreeCAD after updating, after saving your work.

- New mechanical models must retain native features and driving dimensions, survive save/reopen, and pass actual dimension-change probes before acceptance. A Body container or spreadsheet alone is insufficient. Failed edits preserve the accepted file. Technical direct-solid exceptions must be recorded and disclosed.
- Editability ratings use the existing E0–E4 fact layer. E3 now requires measured evidence; E4 is never inferred from a successful build. Check model health tests a disposable snapshot, including unsaved work.
- CADWiz-owned models hide origins, construction planes and completed sketches by default while preserving intentionally visible references. Setup offers Show construction and Clean model view.
- Reset CADWiz Layout returns the panel to the right. Floating/docking and cramped top/bottom placements recover without changing unrelated docks.
- New projects use Documents/CADWiz or the saved custom folder. Existing files and version stores stay where they are; earlier custom roots remain discoverable.
- Model changes reload the document inside the connected FreeCAD application. A GUI executable cannot be used as the geometry worker; CADWiz will refuse rather than launch another application window.

## Scope and limits

Existing fixed solids do not acquire missing feature history by installing this update. Reconstruct a separate native copy using the original as the reference. Parameter probes are bounded representative checks, not proof that every possible dimension remains valid. Complex unsupported construction may be refused and require correction or a disclosed exception.

Native geometry and production tool acceptance are tested with FreeCAD, without a paid AI provider. Cross-platform automated checks do not replace physical macOS GUI or printer testing. Scan remains excluded. See AUDIT-0.8.6.md for evidence and limits.
